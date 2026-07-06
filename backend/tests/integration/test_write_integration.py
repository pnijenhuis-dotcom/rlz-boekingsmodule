"""Schrijf-integratietests — uitsluitend tegen de RLZ-test-administratie ('Administratiekantoor
Nijenhuis', Platform/registers/entiteiten.md). Marker `write_integration`; skipt automatisch
zolang TESTADMIN_USERNAME/TESTADMIN_PASSWORD leeg zijn in verkenning/.env.

Flow (koppelcontract §7.3): eigen duplicaatcheck (Entity+Reference+bedrag) -> vendor aanmaken ->
inkoopfactuur met regel -> boeken (17) -> storneren (19). Nooit hard verwijderen.

Idempotentie-fundament (verkenning/api-verkenning.md "Actie 138" + "Boekt RLZ zelf..."):
RLZ's actie 138 (DetermineDuplicateInvoice) is bewezen zonder waarneembaar effect — geen
onderscheid tussen duplicaat/unieke factuur in respons of document, en Book (17) blokkeert
duplicaten zelf ook niet (getest met een byte-identieke Entity+Reference+bedrag-factuur die
gewoon geboekt werd). Idempotentie moet dus volledig aan onze kant: deterministische
client-GUID's (UUIDv5 waar mogelijk, zodat een herhaalde PUT vanzelf hetzelfde document raakt)
+ RlzClient.find_purchase_invoices_by_reference() vóór elke PUT als vangnet voor niet-
deterministische GUID's.
"""

from __future__ import annotations

import uuid

import pytest

from app.rlz.client import RlzClient

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
    total_amount = 1.21

    # 1. Eigen duplicaatcheck vóór de PUT (idempotentie-fundament — niet RLZ's actie 138, zie
    # moduledocstring). Nieuw client-GUID + nieuwe Reference, dus verwacht leeg.
    existing = testadmin_client.find_purchase_invoices_by_reference(
        vendor_id=test_vendor_id, reference=reference, total_amount=total_amount
    )
    assert existing == [], f"Onverwacht al aanwezig vóór aanmaken: {existing}"

    # 2. Inkoopfactuur met regel (PUT + client-GUID)
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

    # Duplicaatcheck vindt het net aangemaakte document nu wél (regressietest voor de filter zelf).
    found = testadmin_client.find_purchase_invoices_by_reference(
        vendor_id=test_vendor_id, reference=reference, total_amount=total_amount
    )
    assert [f["id"] for f in found] == [str(invoice_id)]

    # 3. RLZ's eigen actie 138 — bewezen geen effect (zie moduledocstring), hier alleen een
    # regressietest dat het per-document-endpoint nog 204 geeft (niet meer op de collectie-vorm,
    # die altijd 400 gaf).
    dup_response = testadmin_client.run_unreliable_duplicate_check_action(invoice_id)
    assert dup_response.status_code < 300, dup_response.text

    # 4. Boeken (actie 17)
    book_response = testadmin_client.book_purchase_invoice(invoice_id)
    assert book_response.status_code < 300, book_response.text
    invoice = testadmin_client.get(f"PurchaseInvoices/{invoice_id}")
    assert invoice["Status"] == 2, "Verwachtte definitief-geboekt (2) na actie 17"

    # 5. Storneren (actie 19) — nooit hard verwijderen (contract §7.3). Vastleggen wat de API
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
