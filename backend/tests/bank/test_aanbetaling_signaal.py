"""Deel 4 punt 3 (aansluitend) — aanbetaling-open-signaal: Entity-match + IBAN-herkenning, alleen open."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Engine, text

from app.bank import aanbetaling_signaal, relatie
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_relatie_referentiedata


def test_signaal_op_entity_en_iban_en_verdwijnt_na_storno(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-250.00")
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE boekhouding.bank_mutatie SET tegenrekening_iban = 'NL91 ABNA 0417 1643 00' WHERE id = :id"), {"id": mutatie_id})
    client = FakeBankClient(transacties={str(mutatie_id): {"id": str(mutatie_id), "Amount": -250.0, "OpenAmount": -250.0,
                                                           "PaymentReferenceList": [], "Date": "2026-08-25T00:00:00"}})
    r = relatie.boek_mutatie_op_relatie(administratie_id=administratie_id, payment_transaction_id=mutatie_id,
                                        relatie_soort="crediteur", entity_id=ref["vendor_id"], actor_id=beheerder_id, client=client)

    treffers = aanbetaling_signaal.zoek_open_aanbetalingen(administratie_id=administratie_id, vendor_id=ref["vendor_id"])
    assert [(t.bedrag, t.herkenning, t.boeking_id) for t in treffers] == [(Decimal("250.00"), "entity", r.boeking_id)]
    # Andere crediteur (duplicaat-kaart) met dezelfde vertrouwde IBAN → herkenning via IBAN.
    andere = aanbetaling_signaal.zoek_open_aanbetalingen(administratie_id=administratie_id, vendor_id=uuid.uuid4(),
                                                          vendor_ibans={"NL91ABNA0417164300"})
    assert [t.herkenning for t in andere] == ["iban"]
    # Onbekende crediteur zonder IBAN-overlap → niets.
    assert aanbetaling_signaal.zoek_open_aanbetalingen(administratie_id=administratie_id, vendor_id=uuid.uuid4()) == []

    relatie.storno_relatie_boeking(administratie_id=administratie_id, boeking_id=r.boeking_id, actor_id=beheerder_id,
                                   reden="toch factuur", client=client)
    assert aanbetaling_signaal.zoek_open_aanbetalingen(administratie_id=administratie_id, vendor_id=ref["vendor_id"]) == []
