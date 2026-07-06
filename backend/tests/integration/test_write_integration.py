"""Schrijf-integratietests — uitsluitend tegen de RLZ-test-administratie ('Administratiekantoor
Nijenhuis', Platform/registers/entiteiten.md). Marker `write_integration`; skipt automatisch
zolang TESTADMIN_USERNAME/TESTADMIN_PASSWORD leeg zijn in verkenning/.env.

Flow (koppelcontract §7.3): vendor aanmaken -> inkoopfactuur met regel -> duplicaatcheck (138)
-> boeken (17) -> storneren (19 + creditboeking). Nooit hard verwijderen.
"""

from __future__ import annotations

import uuid

import pytest

from app.rlz.client import RlzApiError, RlzClient

pytestmark = pytest.mark.write_integration

# Vaste testrekeningen in de test-administratie (gevonden via Ledgers/TaxRates met
# UseForPurchaseInvoiceDetails=true, zie sessie-notities) — 4699 Diverse algemene kosten / 21% NL.
TEST_ACCOUNT_ID = "79b6f64a-dad9-4683-9e47-9c182ebae1c1"
TEST_TAXRATE_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"


@pytest.fixture
def test_vendor_id(testadmin_client: RlzClient) -> uuid.UUID:
    vendor_id = uuid.uuid4()
    response = testadmin_client.put_vendor(
        vendor_id, name="TEST PoC RLZ-boekingsmodule — verwijderen"
    )
    assert response.status_code < 300, response.text
    return vendor_id


def test_volledige_boekflow_met_stornering(
    testadmin_client: RlzClient, test_vendor_id: uuid.UUID
) -> None:
    invoice_id = uuid.uuid4()
    reference = f"TEST-{invoice_id}"

    # 1. Inkoopfactuur met regel (PUT + client-GUID)
    response = testadmin_client.put_purchase_invoice(
        invoice_id,
        vendor_id=test_vendor_id,
        lines=[
            {
                "Account": {"id": TEST_ACCOUNT_ID},
                "TaxRate": {"id": TEST_TAXRATE_ID},
                "NetAmount": 1.00,
                "TaxAmount": 0.21,
            }
        ],
        reference=reference,
    )
    assert response.status_code < 300, response.text

    invoice = testadmin_client.get(f"PurchaseInvoices/{invoice_id}")
    assert invoice["Status"] == 1, "Verwachtte concept (1) vóór boeken"

    # 2. Duplicaatcheck (collectie-actie 138) vóór boeken — idempotentie-hard-rule. Payload-vorm
    # nog niet geverifieerd (open punt, verkenning/api-verkenning.md): elke geprobeerde vorm
    # (Reference-criteria, volledige documentvorm, kale Type-only body) geeft 400 _InvalidData.
    # Niet blokkerend maken voor de rest van de flow zolang dit openstaat — wél zichtbaar loggen.
    try:
        dup_response = testadmin_client.check_purchase_invoice_duplicate(Reference=reference)
        print(f"\n[138-observatie] status={dup_response.status_code} body={dup_response.text}")
    except RlzApiError as exc:
        print(f"\n[138-observatie] payload-vorm nog onbekend, API gaf: {exc}")

    # 3. Boeken (actie 17)
    book_response = testadmin_client.book_purchase_invoice(invoice_id)
    assert book_response.status_code < 300, book_response.text
    invoice = testadmin_client.get(f"PurchaseInvoices/{invoice_id}")
    assert invoice["Status"] == 2, "Verwachtte definitief-geboekt (2) na actie 17"

    # 4. Storneren (actie 19) — nooit hard verwijderen (contract §7.3). Vastleggen wat de API
    # daadwerkelijk teruggeeft: geverifieerd 2026-07-06, zie verkenning/api-verkenning.md
    # ("Actie 19 Correct — geverifieerd gedrag").
    correct_response = testadmin_client.correct_purchase_invoice(invoice_id)
    assert correct_response.status_code < 300, correct_response.text
    invoice_after_correct = testadmin_client.get(f"PurchaseInvoices/{invoice_id}")
    print(f"\n[storno-observatie] Status na actie 19: {invoice_after_correct['Status']}")
    print(f"[storno-observatie] volledige respons: {invoice_after_correct}")
    assert invoice_after_correct["Status"] == 1, (
        "Actie 19 zet hetzelfde document terug naar concept (1), i.p.v. een los creditdocument "
        "aan te maken — zie verkenning/api-verkenning.md."
    )
