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
from app.rlz.aangifte import StornoGeblokkeerdDoorAangifte
from app.tijd import vandaag_nl
from tests.aitoets.stub import StubPlausibiliteitClient, zet_ai_toets_stub, zet_intake_ai
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


def test_storno_geblokkeerd_als_boekdatum_in_ingediende_aangifte_valt(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    """Aangifte-poort (besluit Peter 2026-08-15): de fake-boekdatum (2026-08-10) valt in een
    ingediende (Status 2) aangifte-periode → storno geweigerd vóór de correct-call."""
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(
        transacties={str(mutatie_id): _tx_record(mutatie_id)},
        aangiften=[{"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}],
    )
    resultaat = boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )
    with pytest.raises(StornoGeblokkeerdDoorAangifte):
        boeken.storno_bank_boeking(
            administratie_id=administratie_id, boeking_id=resultaat.boeking_id,
            actor_id=beheerder_id, reden="verkeerde rubricering", client=client,
        )
    # geen correct-call gedaan, lokale status onaangeroerd
    assert client.correcties == []
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM boekhouding.bank_boeking WHERE id = :id"),
            {"id": resultaat.boeking_id},
        ).scalar_one()
    assert status == "geboekt"


def test_storno_fail_closed_als_aangiften_niet_leesbaar_zijn(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id)}, faal_op=None)
    resultaat = boeken.boek_mutatie_direct(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        regels=_regels(), actor_id=beheerder_id, client=client,
    )
    client.faal_op = "aangiften"
    with pytest.raises(StornoGeblokkeerdDoorAangifte):
        boeken.storno_bank_boeking(
            administratie_id=administratie_id, boeking_id=resultaat.boeking_id,
            actor_id=beheerder_id, reden="verkeerde rubricering", client=client,
        )
    assert client.correcties == []


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
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    from app.bank.matchmotor import tegenpartij_sleutel

    # Blok B (10-09): de AI-plausibiliteitstoets is een poort vóór élke automatische boeking — AVG-gate aan + stub.
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch)
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
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, monkeypatch
) -> None:
    """Opt-in autoboeken zonder de boeken-toggle → zichtbare fout per mutatie, geen boeking."""
    from app.bank.matchmotor import tegenpartij_sleutel

    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch)
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


# --- blok B bundel 10-09: AI-plausibiliteitstoets als poort + historie-regel in de autoflow -------------------


def _zet_autoboeken_aan(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET bank_autoboeken_ingeschakeld = true WHERE id = :aid"),
            {"aid": administratie_id},
        )


def _ai_kolommen(admin_engine: Engine, mutatie_id: uuid.UUID) -> tuple:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT ai_toets_uitkomst, ai_toets_reden, ai_toets_op IS NOT NULL, ai_toets_invoer_hash "
                "FROM boekhouding.bank_mutatie WHERE id = :id"
            ),
            {"id": mutatie_id},
        ).one()


def _vaste_regel_kandidaat(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    from app.bank.matchmotor import tegenpartij_sleutel

    _zet_autoboeken_aan(admin_engine, administratie_id)
    mutatie_id = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id, bedrag="-24.50", tegenpartij_naam="ING Bank N.V.",
        omschrijving="kosten zakelijk juni",
    )
    _maak_vaste_regel(
        admin_engine, administratie_id=administratie_id, sleutel=tegenpartij_sleutel("ING Bank N.V.") or "",
        beheerder_id=beheerder_id,
    )
    return mutatie_id


def test_ai_twijfel_boekt_niet_vult_kolommen_en_meldt_overgeslagen(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    zet_intake_ai(admin_engine, True)
    stub = zet_ai_toets_stub(
        monkeypatch, StubPlausibiliteitClient(antwoorden={"ING Bank": ("twijfel", "bankkosten op een omzetrekening?")})
    )
    mutatie_id = _vaste_regel_kandidaat(admin_engine, administratie_id, beheerder_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-24.50")})

    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)

    assert resultaat.geboekt == 0 and resultaat.fouten == [] and resultaat.zonder_ai_toets == []
    assert len(resultaat.overgeslagen) == 1 and resultaat.overgeslagen[0].startswith("twijfel: ")
    assert "bankkosten op een omzetrekening" in resultaat.overgeslagen[0]
    assert client.direct_bookings == {}  # geen byte richting RLZ
    uitkomst, reden, op_gevuld, invoer_hash = _ai_kolommen(admin_engine, mutatie_id)
    assert (uitkomst, op_gevuld) == ("twijfel", True) and "omzetrekening" in reden and invoer_hash
    assert len(stub.aanroepen) == 1

    # Idempotent: een tweede nacht met hetzelfde voorstel toetst NIET opnieuw (hash gelijk), meldt wél overgeslagen.
    resultaat2 = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)
    assert resultaat2.geboekt == 0 and len(resultaat2.overgeslagen) == 1
    assert "eerder getoetst" in resultaat2.overgeslagen[0]
    assert len(stub.aanroepen) == 1


def test_ai_plausibel_boekt(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    zet_intake_ai(admin_engine, True)
    zet_ai_toets_stub(monkeypatch)
    mutatie_id = _vaste_regel_kandidaat(admin_engine, administratie_id, beheerder_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-24.50")})

    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)

    assert (resultaat.geboekt, resultaat.fouten, resultaat.overgeslagen) == (1, [], [])
    assert _ai_kolommen(admin_engine, mutatie_id)[0] == "plausibel"
    assert len(client.direct_bookings) == 1


def _audit_zonder_toets(admin_engine: Engine, mutatie_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'automatisch_geboekt_zonder_ai_toets' AND tabel = 'bank_mutatie' AND record_id = :id"
                ),
                {"id": mutatie_id},
            ).all()
        ]


@pytest.mark.parametrize(
    "uitval,oorzaak",
    [
        ("avg_gate", "avg_gate"),
        ("geen_key", "api_key"),
        ("kostengrens", "kostengrens"),
        ("ai_fout", "ai_fout"),
    ],
)
def test_ai_uitval_boekt_door_zonder_ai_toets_zichtbaar(
    administratie_id: uuid.UUID,
    admin_engine: Engine,
    beheerder_id: uuid.UUID,
    boeken_aan: None,
    monkeypatch,
    uitval: str,
    oorzaak: str,
) -> None:
    """Blok 4 (10-09 avond, besluit Peter): technische uitval van de AI-toets (AVG-gate uit, geen API-key, kostengrens,
    AI-fout) = WÉL boeken — de deterministische poorten waren groen. Zichtbaar via `ai_toets_uitkomst = overgeslagen` +
    reden op de mutatie (chip "zonder AI-toets"), audit `automatisch_geboekt_zonder_ai_toets` mét oorzaak en de
    regel in `resultaat.zonder_ai_toets`. Nooit een regel in `overgeslagen` (dat is nu alleen twijfel)."""
    from tests.aitoets.stub import zet_ai_toets_geen_key

    if uitval == "avg_gate":
        zet_intake_ai(admin_engine, False)
        zet_ai_toets_stub(monkeypatch)
    else:
        zet_intake_ai(admin_engine, True)
        if uitval == "geen_key":
            zet_ai_toets_geen_key(monkeypatch)
        elif uitval == "kostengrens":
            zet_ai_toets_stub(
                monkeypatch, StubPlausibiliteitClient(kostenfout="AI-maandlimiet bereikt (€ 100 van € 100)")
            )
        else:
            zet_ai_toets_stub(monkeypatch, StubPlausibiliteitClient(fout="Claude API-timeout na 120s"))
    mutatie_id = _vaste_regel_kandidaat(admin_engine, administratie_id, beheerder_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-24.50")})

    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)

    assert (resultaat.geboekt, resultaat.fouten, resultaat.overgeslagen) == (1, [], [])
    assert len(client.direct_bookings) == 1
    assert len(resultaat.zonder_ai_toets) == 1
    assert resultaat.zonder_ai_toets[0].startswith(f"zonder AI-toets: {oorzaak} — ")
    uitkomst, reden, op_gevuld, _hash = _ai_kolommen(admin_engine, mutatie_id)
    assert (uitkomst, op_gevuld) == ("overgeslagen", True) and reden.startswith(oorzaak)
    audit = _audit_zonder_toets(admin_engine, mutatie_id)
    assert len(audit) == 1 and audit[0]["oorzaak"] == oorzaak and audit[0]["soort"] == "bank_vaste_regel"
    assert audit[0]["bron"] == "bank_autoboeken"
    with admin_engine.connect() as conn:
        bron = conn.execute(
            text("SELECT bron FROM boekhouding.bank_boeking WHERE payment_transaction_id = :id"), {"id": mutatie_id}
        ).scalar_one()
    assert bron == "automatisch"


def test_ai_avg_gate_uit_blokkeert_de_call_niet_de_boeking(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    """AVG-gate uit = geen byte naar de Claude API (stub nooit aangeroepen) — de boeking loopt door (blok 4)."""
    zet_intake_ai(admin_engine, False)
    stub = zet_ai_toets_stub(monkeypatch)
    mutatie_id = _vaste_regel_kandidaat(admin_engine, administratie_id, beheerder_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-24.50")})

    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)

    assert resultaat.geboekt == 1 and stub.aanroepen == [] and len(client.direct_bookings) == 1
    assert _ai_kolommen(admin_engine, mutatie_id)[0] == "overgeslagen"
    assert _audit_zonder_toets(admin_engine, mutatie_id)[0]["oorzaak"] == "avg_gate"


def test_ai_uitval_mislukte_boeking_telt_niet_als_zonder_ai_toets(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, monkeypatch
) -> None:
    """De audit-rij `automatisch_geboekt_zonder_ai_toets` komt alleen ná een GESLAAGDE boeking — faalt het boekpad
    (hier: boeken-toggle uit), dan staat er een fout en géén 'zonder AI-toets'-regel (de teller telt échte
    boekingen)."""
    zet_intake_ai(admin_engine, False)
    zet_ai_toets_stub(monkeypatch)
    mutatie_id = _vaste_regel_kandidaat(admin_engine, administratie_id, beheerder_id)
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-24.50")})

    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)

    assert resultaat.geboekt == 0 and len(resultaat.fouten) == 1 and resultaat.zonder_ai_toets == []
    assert _audit_zonder_toets(admin_engine, mutatie_id) == []


def test_historie_regel_groen_boekt_automatisch_na_plausibel(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    """Stap 3b in de autoflow: ≥ 3 eerdere boekingen (≥ 6 maanden dekking) op IBAN + kern, 100 % zelfde rekening →
    direct-op-grootboek met bron AUTOMATISCH en omschrijving "Historie-regel: …"."""
    from datetime import timedelta

    zet_intake_ai(admin_engine, True)
    stub = zet_ai_toets_stub(monkeypatch)
    _zet_autoboeken_aan(admin_engine, administratie_id)
    iban = "NL91ABNA0417164300"
    ledger = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.grootboekrekening "
                "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                "VALUES (:id, :aid, '4400', 'Huur', 2, false)"
            ),
            {"id": ledger, "aid": administratie_id},
        )
        for i in range(3):
            conn.execute(
                text(
                    "INSERT INTO boekhouding.bank_historie_boeking (id, administratie_id, payment_transaction_id, datum, "
                    "tegenrekening_iban, omschrijving, tegenpartij_naam, ledger_id, taxrate_id, bron) VALUES "
                    "(:id, :aid, :tx, :datum, :iban, :oms, 'Vastgoed Oost B.V.', :ledger, NULL, 'rlz')"
                ),
                {
                    "id": uuid.uuid4(), "aid": administratie_id, "tx": uuid.uuid4(),
                    "datum": vandaag_nl() - timedelta(days=200 + 30 * i), "iban": iban,
                    "oms": f"Huur kantoor Deventer periode 0{6 - i}-2026", "ledger": ledger,
                },
            )
    mutatie_id = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id, bedrag="-1250.00", tegenpartij_naam="Vastgoed Oost B.V.",
        omschrijving="Huur kantoor Deventer periode 09-2026", tegenrekening_iban=iban,
    )
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-1250.00")})

    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)

    assert (resultaat.geboekt, resultaat.fouten, resultaat.overgeslagen) == (1, [], [])
    document = next(iter(client.direct_bookings.values()))
    assert document["DocumentLineList"][0]["Account"] == {"id": str(ledger)}
    assert document["DocumentLineList"][0]["NetAmount"] == -1250.0
    with admin_engine.connect() as conn:
        bron, omschrijving = conn.execute(
            text("SELECT bron, omschrijving FROM boekhouding.bank_boeking WHERE administratie_id = :aid"),
            {"aid": administratie_id},
        ).one()
    assert bron == BankBoekingBron.AUTOMATISCH.value and omschrijving == "Historie-regel: Vastgoed Oost B.V."
    # De AI kreeg het voorstel mét leesbare rekening en de historie-samenvatting, geen keuzelijst.
    opdracht = stub.aanroepen[0]["opdracht"]
    assert "4400 Huur" in opdracht and "3 eerdere mutaties, 3× 4400 Huur (100 %)" in opdracht


def test_historie_regel_oranje_boekt_niet_automatisch(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None, monkeypatch
) -> None:
    from datetime import timedelta

    zet_intake_ai(admin_engine, True)
    stub = zet_ai_toets_stub(monkeypatch)
    _zet_autoboeken_aan(admin_engine, administratie_id)
    iban = "NL91ABNA0417164300"
    with admin_engine.begin() as conn:
        for i, ledger in enumerate([uuid.uuid4()] * 3 + [uuid.uuid4()]):
            conn.execute(
                text(
                    "INSERT INTO boekhouding.bank_historie_boeking (id, administratie_id, payment_transaction_id, datum, "
                    "tegenrekening_iban, omschrijving, tegenpartij_naam, ledger_id, taxrate_id, bron) VALUES "
                    "(:id, :aid, :tx, :datum, :iban, 'Huur kantoor Deventer', 'Vastgoed Oost B.V.', :ledger, NULL, 'module')"
                ),
                {"id": uuid.uuid4(), "aid": administratie_id, "tx": uuid.uuid4(),
                 "datum": vandaag_nl() - timedelta(days=200 + 30 * i), "iban": iban, "ledger": ledger},
            )
    mutatie_id = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id, bedrag="-1250.00", tegenpartij_naam="Vastgoed Oost B.V.",
        omschrijving="Huur kantoor Deventer", tegenrekening_iban=iban,
    )
    client = FakeBankClient(transacties={str(mutatie_id): _tx_record(mutatie_id, bedrag="-1250.00")})
    resultaat = boeken.verwerk_automatisch(administratie_id=administratie_id, client=client)
    assert (resultaat.geboekt, resultaat.overgeslagen) == (0, []) and client.direct_bookings == {}
    assert stub.aanroepen == []  # oranje = mens bevestigt; geen AI-call, geen AI-kosten
