"""Deel 4 punt 3 — koppel aan relatie = aanbetalingsdocument + actie 15 (STAP-0 25-08 §1 H1–H5)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bank import boeken, relatie
from app.bank.relatie import bepaal_instelling
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_bank_aanbetaling_id
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_relatie_referentiedata


def _tx(mutatie_id: uuid.UUID, bedrag: str = "-100.00") -> dict:
    return {"id": str(mutatie_id), "Amount": float(bedrag), "OpenAmount": float(bedrag), "PaymentReferenceList": [],
            "Date": "2026-08-25T00:00:00"}


def _rij(admin_engine: Engine, boeking_id: uuid.UUID) -> tuple:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT status, bedrag, rlz_boekstuknummer, storno_reden, verrekend_met_document_id "
                                 "FROM boekhouding.bank_relatie_boeking WHERE id = :id"), {"id": boeking_id}).one()


def test_instelling_deterministisch_uit_caches(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    with scoped_session(administratie_id) as session:
        inst = bepaal_instelling(session, administratie_id=administratie_id, relatie_soort="crediteur")
        assert inst.vooruit_ledger_id == ref["gb_1403"] and inst.vooruit_code == "1403"
        assert inst.taxrate_id == ref["nul_tarief"]  # vrijgesteld/verlegd/21% tellen niet
        inst_d = bepaal_instelling(session, administratie_id=administratie_id, relatie_soort="debiteur")
        assert inst_d.vooruit_ledger_id == ref["gb_1806"]


def test_instelling_fail_closed_bij_ambiguiteit_of_ontbrekende_rekening(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id, met_1806=False, extra_nul_tarief=True)
    with scoped_session(administratie_id) as session:
        with pytest.raises(relatie.RelatieInstellingOntbreekt, match="0%-tarief"):
            bepaal_instelling(session, administratie_id=administratie_id, relatie_soort="crediteur")
        with pytest.raises(relatie.RelatieInstellingOntbreekt, match="1806"):
            bepaal_instelling(session, administratie_id=administratie_id, relatie_soort="debiteur")


def test_vooruitbetaling_crediteur_volledige_cyclus(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-100.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})

    r = relatie.boek_mutatie_op_relatie(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id, relatie_soort="crediteur",
        entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client, omschrijving="aanbetaling steigerhout",
    )
    assert r.rlz_document_id == rlz_bank_aanbetaling_id(r.boeking_id)
    doc = client.aanbetalingen[str(r.rlz_document_id)]
    regel = doc["DocumentLineList"][0]
    # Eén regel op 1403, positief |deel|, expliciet 0%-tarief (zonder tarief rekent RLZ 21% — probe I).
    assert regel["Account"]["id"] == str(ref["gb_1403"]) and regel["NetAmount"] == 100.0
    assert regel["TaxRate"]["id"] == str(ref["nul_tarief"]) and regel["TaxAmount"] == 0.0
    assert doc["Status"] == 2
    assert client.links[-1]["linked_amount"] == -100.0 and r.open_restant == Decimal("0")
    status, bedrag, boekstuk, _, _ = _rij(admin_engine, r.boeking_id)
    assert status == "geboekt" and bedrag == Decimal("-100.00") and boekstuk == doc["ReceiptNumber"]
    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}).scalar_one()
        audit = conn.execute(text("SELECT COUNT(*) FROM platform.audit_event WHERE actie = 'bank_mutatie_op_relatie_geboekt'")).scalar_one()
    assert open_bedrag == Decimal("0") and audit == 1
    # Open-posten-weergave: de aanbetaling staat open in ónze administratie (RLZ kent alleen GB 1403).
    lijst = relatie.open_aanbetalingen(administratie_id=administratie_id)
    assert [a.boeking_id for a in lijst] == [r.boeking_id] and lijst[0].entity_naam == "Steigerhout Import B.V."

    # Tweede koppeling op dezelfde mutatie weigert (één per mutatie).
    with pytest.raises(relatie.RelatieBoekingBestaatAl):
        relatie.boek_mutatie_op_relatie(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id, relatie_soort="crediteur",
            entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client,
        )

    # Storno: reden verplicht, actie 19 op het aanbetalingsdocument, mutatie volledig terug (H4).
    with pytest.raises(relatie.RelatieBoekenFout):
        relatie.storno_relatie_boeking(administratie_id=administratie_id, boeking_id=r.boeking_id,
                                       actor_id=beheerder_id, reden="  ", client=client)
    relatie.storno_relatie_boeking(administratie_id=administratie_id, boeking_id=r.boeking_id,
                                   actor_id=beheerder_id, reden="was toch een factuurbetaling", client=client)
    assert client.factuur_correcties == [str(r.rlz_document_id)]
    status, _, _, reden, _ = _rij(admin_engine, r.boeking_id)
    assert status == "gestorneerd" and reden == "was toch een factuurbetaling"
    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}).scalar_one()
    assert open_bedrag == Decimal("-100.00")
    assert relatie.open_aanbetalingen(administratie_id=administratie_id) == []

    # Herboeken ná storno = nieuwe registratie-rij = NIEUW GUID (H5: her-PUT geeft geen nieuw item).
    r2 = relatie.boek_mutatie_op_relatie(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id, relatie_soort="crediteur",
        entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client,
    )
    assert r2.rlz_document_id != r.rlz_document_id and r2.open_restant == Decimal("0")


def test_koppeling_zonder_effect_draait_aanbetalingsdocument_terug(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-100.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)}, faal_op="link_zonder_effect")
    with pytest.raises(relatie.RlzRelatieBoekingMislukt, match="niet zichtbaar"):
        relatie.boek_mutatie_op_relatie(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id, relatie_soort="crediteur",
            entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client,
        )
    # Best-effort storno van het losse document + niets geregistreerd.
    assert len(client.factuur_correcties) == 1
    with admin_engine.connect() as conn:
        aantal = conn.execute(text("SELECT COUNT(*) FROM boekhouding.bank_relatie_boeking WHERE administratie_id = :aid"),
                              {"aid": administratie_id}).scalar_one()
    assert aantal == 0


def test_failsafes_en_bedragcontrole(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-100.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
    with pytest.raises(relatie.BedragPastNiet):
        relatie.boek_mutatie_op_relatie(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        relatie_soort="crediteur", entity_id=ref["vendor_id"], actor_id=beheerder_id,
                                        client=client, bedrag=Decimal("-150.00"))
    with pytest.raises(relatie.RelatieNietGevonden):
        relatie.boek_mutatie_op_relatie(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        relatie_soort="crediteur", entity_id=uuid.uuid4(), actor_id=beheerder_id, client=client)
    client.transacties[str(mutatie_id)]["OpenAmount"] = 0.0  # intussen in RLZ zelf afgeletterd
    with pytest.raises(boeken.MutatieAlAfgeletterd):
        relatie.boek_mutatie_op_relatie(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        relatie_soort="crediteur", entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client)
    assert client.aanbetalingen == {}


def test_debiteur_spiegelbeeld_boekt_salesinvoice_op_1806(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="80.00")
    customer_id = uuid.uuid4()
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id, "80.00")})
    client.customers[str(customer_id)] = {"id": str(customer_id), "Name": "Huurder Jansen"}
    r = relatie.boek_mutatie_op_relatie(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id, relatie_soort="debiteur",
        entity_id=customer_id, actor_id=beheerder_id, client=client,
    )
    doc = client.aanbetalingen[str(r.rlz_document_id)]
    assert doc["_pad"] == "SalesInvoices" and doc["DocumentLineList"][0]["Account"]["id"] == str(ref["gb_1806"])
    assert client.links[-1]["linked_amount"] == 80.0
    assert relatie.open_aanbetalingen(administratie_id=administratie_id)[0].entity_naam == "Huurder Jansen"


def test_markeer_verrekend_bij_boeking_sluit_exact_passende_tegenregel(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    from types import SimpleNamespace

    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-100.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
    r = relatie.boek_mutatie_op_relatie(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        relatie_soort="crediteur", entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client)
    document_id = uuid.uuid4()
    regels = [SimpleNamespace(ledger_id=uuid.uuid4(), netto_bedrag=Decimal("165.29")),
              SimpleNamespace(ledger_id=ref["gb_1403"], netto_bedrag=Decimal("-100.00"))]
    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        # Ander bedrag → geen match (nooit gokken).
        assert relatie.markeer_verrekend_bij_boeking(session, administratie_id=administratie_id, document_id=document_id,
                                                     vendor_id=ref["vendor_id"], actor_id=beheerder_id,
                                                     regels=[SimpleNamespace(ledger_id=ref["gb_1403"], netto_bedrag=Decimal("-99.00"))]) == []
        assert relatie.markeer_verrekend_bij_boeking(session, administratie_id=administratie_id, document_id=document_id,
                                                     vendor_id=ref["vendor_id"], actor_id=beheerder_id, regels=regels) == [r.boeking_id]
    status, _, _, _, verrekend_met = _rij(admin_engine, r.boeking_id)
    assert status == "verrekend" and verrekend_met == document_id
    # Verrekend = niet meer open, en niet meer storneerbaar zonder eerst de factuur terug te draaien.
    assert relatie.open_aanbetalingen(administratie_id=administratie_id) == []
    with pytest.raises(relatie.RelatieBoekenFout, match="verrekend"):
        relatie.storno_relatie_boeking(administratie_id=administratie_id, boeking_id=r.boeking_id,
                                       actor_id=beheerder_id, reden="x", client=client)
