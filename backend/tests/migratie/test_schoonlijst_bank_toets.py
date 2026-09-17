"""Feiten eerst 17-09 (blok C): een dubbel-signaal uit de schoonlijst draagt verplicht `bank_toets` (bevestigd | weerlegd |
geen_mutatie) — codificatie van "bank is altijd leidend" (Peter 12-09/17-09). Een rij zonder bank_toets kan niet ontstaan."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.migratie import schoonlijst
from app.migratie.bankdekking import BankMutatie

BANK_TOETSEN = {"bevestigd", "weerlegd", "geen_mutatie"}


def _rijen(collectie: str = "ManualJournals") -> list[schoonlijst.Rij]:
    docs = [
        {"id": "a" * 32, "ReceiptNumber": "RLZ-06-00000001", "BaseInvoiceAmount": "135000.00", "Date": "2026-05-01", "Status": 2, "Description": "aanbetaling"},
        {"id": "b" * 32, "ReceiptNumber": "RLZ-06-00000002", "BaseInvoiceAmount": "135000.00", "Date": "2026-05-01", "Status": 2, "Description": "aanbetaling"},
    ]
    return schoonlijst.dubbelen(collectie, docs)


def test_elke_dubbelen_of_bank_bevestigd_rij_draagt_bank_toets() -> None:
    rijen = _rijen()
    zonder_bank = schoonlijst.beoordeel_dubbelen(rijen, bank=None)
    met_bank_weerlegd = schoonlijst.beoordeel_dubbelen(
        rijen,
        bank=[
            BankMutatie(rlz_id="m1", bedrag=Decimal("135000.00"), boekdatum=date(2026, 5, 1), teken=1),
            BankMutatie(rlz_id="m2", bedrag=Decimal("135000.00"), boekdatum=date(2026, 5, 2), teken=1),
        ],
    )
    met_bank_bevestigd = schoonlijst.beoordeel_dubbelen(
        rijen, bank=[BankMutatie(rlz_id="m1", bedrag=Decimal("135000.00"), boekdatum=date(2026, 5, 1), teken=1)]
    )
    for uit, verwacht in ((zonder_bank, "geen_mutatie"), (met_bank_weerlegd, "weerlegd"), (met_bank_bevestigd, "bevestigd")):
        alle = uit["dubbelen"] + uit["bank_bevestigd"]
        assert alle, "geen rijen — de casus hoort een groep van twee te geven"
        assert all(r.extra.get("bank_toets") in BANK_TOETSEN for r in alle)
        assert {r.extra["bank_toets"] for r in alle} == {verwacht}, (verwacht, [r.extra for r in alle])
    assert met_bank_weerlegd["dubbelen"] == [] and len(met_bank_weerlegd["bank_bevestigd"]) == 2
    assert len(met_bank_bevestigd["dubbelen"]) == 2
