"""Direct-op-grootboek: failsafes, harde dekking-check, idempotentie, storno en de opt-in
autoflow — geldlogica, dus volledig getest vóór UI-werk."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bank import boeken
from app.bank.boeken import BankBoekingBron, BankBoekRegelInput
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.rlz_ids import rlz_bank_boeking_id
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie


def _tx_record(mutatie_id: uuid.UUID, *, bedrag: str = "-121.00", open_bedrag: str | None = None) -> dict:
    return {
        "id": str(mutatie_id),
        "Amount": float(bedrag),
        "OpenAmount": float(open_bedrag if open_bedrag is not None else bedrag),
        "PaymentReferenceList": [],
    }


def _regels(*, netto: str = "-100.00", btw: str | None = "-21.00") -> list[BankBoekRegelInput]:
    return [
        BankBoekRegelInput(
            ledger_id=uuid.uuid4(),
            netto_bedrag=Decimal(netto),
            btw_bedrag=Decimal(btw) if btw is not None else None,
        )
    ]


def _boekingen(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id, status, bron, rlz_boekstuknummer FROM boekhouding.bank_boeking "
                "WHERE administratie_id = :aid"
            ),
            {"aid": administratie_id},
        ).all()


def test_failsafe_blokkeert_zonder_boeken_toggle(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    with pytest.raises(boeken.BankBoekenUitgeschakeld):
        boeken.boek_mutatie_direct(
            administratie_id=administratie_id,
            payment_transaction_id=mutatie_id,
            regels=_regels(),
            actor_id=beheerder_id,
            client=client,
        )
    assert client.direct_bookings == {}  # geen byte richting RLZ


def test_regels_moeten_mutatiebedrag_exact_dekken(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    with pytest.raises(boeken.RegelsDekkenMutatieNiet):
        boeken.boek_mutatie_direct(
            administratie_id=administratie_id,
            payment_transaction_id=mutatie_id,
            regels=_regels(netto="-100.00", btw="-20.99"),  # 1 cent mis
            actor_id=beheerder_id,
            client=client,
        )
    assert client.direct_bookings == {}


def test_happy_path_boekt_met_deterministisch_guid_en_audit(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})

    resultaat = boeken.boek_mutatie_direct(
        administratie_id=administratie_id,
        payment_transaction_id=mutatie_id,
        regels=_regels(),
        actor_id=beheerder_id,
        omschrijving="bankkosten juni",
        client=client,
    )

    assert resultaat.rlz_document_id == rlz_bank_boeking_id(mutatie_id)
    assert resultaat.rlz_boekstuknummer is not None
    document = client.direct_bookings[str(resultaat.rlz_document_id)]
    # Regelbedragen dragen het teken van de mutatie (schrijf-PoC: NetAmount = Amount).
    assert document["DocumentLineList"][0]["NetAmount"] == -100.00
    assert document["DocumentLineList"][0]["TaxAmount"] == -21.00

    rijen = _boekingen(admin_engine, administratie_id)
    assert len(rijen) == 1 and rijen[0][1] == "geboekt"

    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(
            text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}
        ).scalar_one()
        audit = conn.execute(
            text("SELECT COUNT(*) FROM platform.audit_event WHERE actie = 'bank_mutatie_direct_geboekt'")
        ).scalar_one()
    assert open_bedrag == Decimal("0")
    assert audit == 1


def test_tweede_boeking_op_dezelfde_mutatie_weigert(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )
    with pytest.raises(boeken.BankBoekingBestaatAl):
        boeken.boek_mutatie_direct(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id,
            regels=_regels(), actor_id=beheerder_id, client=client,
        )
    assert len(client.direct_bookings) == 1


def test_in_rlz_afgeletterde_mutatie_wordt_nooit_overboekt(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    """Eigen duplicaatcheck tegen RLZ: OpenAmount 0 met een vreemde koppeling = iemand was ons
    voor in de RLZ-UI — hard weigeren."""
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    record = _tx_record(mutatie_id, open_bedrag="0")
    record["PaymentReferenceList"] = [
        {"Document": {"id": str(uuid.uuid4()), "Status": 3, "DocumentType": 4}}
    ]
    client = FakeBankClient(transacties={str(mutatie_id): record})
    with pytest.raises(boeken.MutatieAlAfgeletterd):
        boeken.boek_mutatie_direct(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id,
            regels=_regels(), actor_id=beheerder_id, client=client,
        )


def test_retry_na_halve_mislukking_haalt_lokale_registratie_in(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    """RLZ heeft de PUT al verwerkt (PaymentReference wijst naar óns deterministische GUID) maar
    de lokale registratie ontbrak nog — de retry registreert alleen, boekt niet dubbel."""
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    boeking_id = rlz_bank_boeking_id(mutatie_id)
    record = _tx_record(mutatie_id, open_bedrag="0")
    record["PaymentReferenceList"] = [
        {"Document": {"id": str(boeking_id), "Status": 3, "DocumentType": 19}}
    ]
    client = FakeBankClient(transacties={str(mutatie_id): record})
    client.direct_bookings[str(boeking_id)] = {
        "id": str(boeking_id), "Status": 3, "ReceiptNumber": "RLZ-07-00000042", "DocumentType": 19,
    }

    resultaat = boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )
    assert resultaat.al_eerder_geboekt is True
    assert resultaat.rlz_boekstuknummer == "RLZ-07-00000042"
    rijen = _boekingen(admin_engine, administratie_id)
    assert len(rijen) == 1


def test_volumerem_stopt_bij_daglimiet(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 1)
    eerste = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    tweede = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(
        transacties={str(eerste): _tx_record(eerste), str(tweede): _tx_record(tweede)}
    )
    boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=eerste,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )
    with pytest.raises(boeken.BankVolumeremBereikt):
        boeken.boek_mutatie_direct(
            administratie_id=administratie_id, payment_transaction_id=tweede,
            regels=_regels(), actor_id=beheerder_id, client=client,
        )


def test_storno_zet_status_en_herstelt_open_bedrag(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    resultaat = boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )

    boeken.storno_bank_boeking(
        administratie_id=administratie_id, boeking_id=resultaat.boeking_id,
        actor_id=beheerder_id, reden="verkeerde rubricering", client=client,
    )
    assert client.correcties == [str(resultaat.rlz_document_id)]
    with admin_engine.connect() as conn:
        status, reden = conn.execute(
            text("SELECT status, storno_reden FROM boekhouding.bank_boeking WHERE id = :id"),
            {"id": resultaat.boeking_id},
        ).one()
        open_bedrag = conn.execute(
            text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}
        ).scalar_one()
    assert status == "gestorneerd"
    assert reden == "verkeerde rubricering"
    assert open_bedrag == Decimal("-121.00")

    # Na storno mag dezelfde mutatie opnieuw geboekt worden (zelfde deterministische GUID).
    boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )


def test_storno_zonder_reden_weigert(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    resultaat = boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )
    with pytest.raises(boeken.BankBoekenFout):
        boeken.storno_bank_boeking(
            administratie_id=administratie_id, boeking_id=resultaat.boeking_id,
            actor_id=beheerder_id, reden="  ", client=client,
        )


# --- volautomatische verwerking (opt-in) -----------------------------------------------------------


def _maak_vaste_regel(
    admin_engine: Engine, *, administratie_id: uuid.UUID, sleutel: str, beheerder_id: uuid.UUID
) -> uuid.UUID:
    regel_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_regel "
                "(id, administratie_id, tegenpartij_sleutel, ledger_id, aangemaakt_door, actief) "
                "VALUES (:id, :aid, :sleutel, :ledger, :door, true)"
            ),
            {"id": regel_id, "aid": administratie_id, "sleutel": sleutel, "ledger": uuid.uuid4(), "door": beheerder_id},
        )
    return regel_id


def test_autoflow_niets_zonder_opt_in(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, tegenpartij_naam="ING Bank N.V.")
    _maak_vaste_regel(
        admin_engine, administratie_id=administratie_id, sleutel="bank ing n v", beheerder_id=beheerder_id
    )
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    geboekt, fouten = boeken.verwerk_vaste_regels_automatisch(administratie_id=administratie_id, client=client)
    assert (geboekt, fouten) == (0, [])
    assert client.direct_bookings == {}


def test_autoflow_boekt_vaste_regel_mutaties_met_systeem_actor(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    from app.bank.matchmotor import tegenpartij_sleutel

    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET bank_autoboeken_ingeschakeld = true WHERE id = :aid"),
            {"aid": administratie_id},
        )
    mutatie_id = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id, bedrag="-24.50", tegenpartij_naam="ING Bank N.V.",
        omschrijving="kosten zakelijk juni",
    )
    _maak_vaste_regel(
        admin_engine,
        administratie_id=administratie_id,
        sleutel=tegenpartij_sleutel("ING Bank N.V.") or "",
        beheerder_id=beheerder_id,
    )
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-24.50")})

    geboekt, fouten = boeken.verwerk_vaste_regels_automatisch(administratie_id=administratie_id, client=client)
    assert (geboekt, fouten) == (1, [])
    with admin_engine.connect() as conn:
        bron, geboekt_door = conn.execute(
            text("SELECT bron, geboekt_door FROM boekhouding.bank_boeking WHERE administratie_id = :aid"),
            {"aid": administratie_id},
        ).one()
    assert bron == BankBoekingBron.AUTOMATISCH.value
    assert geboekt_door == SYSTEEM_ACTOR_ID


def test_autoflow_respecteert_boeken_failsafe(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """Opt-in autoboeken zonder de boeken-toggle → zichtbare fout per mutatie, geen boeking."""
    from app.bank.matchmotor import tegenpartij_sleutel

    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET bank_autoboeken_ingeschakeld = true WHERE id = :aid"),
            {"aid": administratie_id},
        )
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, tegenpartij_naam="ING Bank N.V.")
    _maak_vaste_regel(
        admin_engine,
        administratie_id=administratie_id,
        sleutel=tegenpartij_sleutel("ING Bank N.V.") or "",
        beheerder_id=beheerder_id,
    )
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)})
    geboekt, fouten = boeken.verwerk_vaste_regels_automatisch(administratie_id=administratie_id, client=client)
    assert geboekt == 0
    assert len(fouten) == 1 and "uit" in fouten[0]
    assert client.direct_bookings == {}
