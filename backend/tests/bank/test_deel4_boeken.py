"""Deel 4 (25-08) — directe boeking: cyclus-GUID ná storno, deelmodus en de verificatie ná de PUT
(STAP-0 §2.2/§2.6: RLZ accepteert deelbedragen; her-PUT op een gestorneerd BMDB = 204 zonder effect)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bank import boeken
from app.bank.boeken import BankBoekRegelInput, DeelBoeking
from app.documenten.rlz_ids import rlz_bank_boeking_cyclus_id, rlz_bank_boeking_id, rlz_bank_deel_boeking_id
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie


def _tx(mutatie_id: uuid.UUID, bedrag: str = "-300.00") -> dict:
    return {"id": str(mutatie_id), "Amount": float(bedrag), "OpenAmount": float(bedrag), "PaymentReferenceList": [],
            "Date": "2026-08-25T00:00:00"}


def _regels(netto: str, btw: str | None = None) -> list[BankBoekRegelInput]:
    return [BankBoekRegelInput(ledger_id=uuid.uuid4(), netto_bedrag=Decimal(netto),
                               btw_bedrag=Decimal(btw) if btw else None)]


def _open_bedrag(admin_engine: Engine, mutatie_id: uuid.UUID) -> Decimal:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}).scalar_one()


def test_herboeken_na_storno_gebruikt_nieuw_cyclus_guid(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
    eerste = boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        regels=_regels("-300.00"), actor_id=beheerder_id, client=client)
    assert eerste.rlz_document_id == rlz_bank_boeking_id(mutatie_id) == rlz_bank_boeking_cyclus_id(mutatie_id, 0)
    boeken.storno_bank_boeking(administratie_id=administratie_id, boeking_id=eerste.boeking_id,
                               actor_id=beheerder_id, reden="verkeerde rekening", client=client)
    assert _open_bedrag(admin_engine, mutatie_id) == Decimal("-300.00")

    tweede = boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        regels=_regels("-300.00"), actor_id=beheerder_id, client=client)
    # Nieuw GUID (cyclus 1) — een her-PUT op het oude GUID zou bij RLZ 204-zonder-effect geven.
    assert tweede.rlz_document_id == rlz_bank_boeking_cyclus_id(mutatie_id, 1) != eerste.rlz_document_id
    assert client.direct_bookings[str(tweede.rlz_document_id)]["Status"] == 3
    assert _open_bedrag(admin_engine, mutatie_id) == Decimal("0")


def test_204_zonder_effect_wordt_zichtbare_fout_en_registreert_niets(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)}, faal_op="put_zonder_effect")
    with pytest.raises(boeken.RlzBankBoekingMislukt, match="effect is niet zichtbaar"):
        boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                   regels=_regels("-300.00"), actor_id=beheerder_id, client=client)
    with admin_engine.connect() as conn:
        aantal = conn.execute(text("SELECT COUNT(*) FROM boekhouding.bank_boeking WHERE administratie_id = :aid"),
                              {"aid": administratie_id}).scalar_one()
    assert aantal == 0
    assert _open_bedrag(admin_engine, mutatie_id) == Decimal("-300.00")


def test_deelmodus_boekt_deel_met_eigen_guid_en_verse_open_stand(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
    deel_a, deel_b = uuid.uuid4(), uuid.uuid4()
    r1 = boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                    regels=_regels("-82.64", "-17.36"), actor_id=beheerder_id, client=client,
                                    deel=DeelBoeking(deel_id=deel_a, bedrag=Decimal("-100.00")))
    assert r1.rlz_document_id == rlz_bank_deel_boeking_id(mutatie_id, deel_a, 0)
    assert _open_bedrag(admin_engine, mutatie_id) == Decimal("-200.00")
    r2 = boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                    regels=_regels("-200.00"), actor_id=beheerder_id, client=client,
                                    deel=DeelBoeking(deel_id=deel_b, bedrag=Decimal("-200.00")))
    assert r2.rlz_document_id != r1.rlz_document_id
    assert _open_bedrag(admin_engine, mutatie_id) == Decimal("0")
    with admin_engine.connect() as conn:
        rijen = conn.execute(text("SELECT deel_id FROM boekhouding.bank_boeking WHERE administratie_id = :aid ORDER BY geboekt_op"),
                             {"aid": administratie_id}).all()
    assert {r[0] for r in rijen} == {deel_a, deel_b}


def test_deelmodus_weigert_deel_dat_niet_past(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)})
    with pytest.raises(boeken.RegelsDekkenMutatieNiet):
        boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                   regels=_regels("100.00"), actor_id=beheerder_id, client=client,
                                   deel=DeelBoeking(deel_id=uuid.uuid4(), bedrag=Decimal("100.00")))  # verkeerd teken
    with pytest.raises(boeken.RegelsDekkenMutatieNiet):
        boeken.boek_mutatie_direct(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                   regels=_regels("-100.00"), actor_id=beheerder_id, client=client,
                                   deel=DeelBoeking(deel_id=uuid.uuid4(), bedrag=Decimal("-120.00")))  # regels ≠ deel
    assert client.direct_bookings == {}
