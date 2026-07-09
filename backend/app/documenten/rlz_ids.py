from __future__ import annotations

import uuid

# Vast, mag NOOIT wijzigen: elke wijziging verandert de uitkomst van rlz_purchase_invoice_id()
# voor bestaand geboekte documenten, wat de idempotentie (retry raakt hetzelfde RLZ-document)
# stilletjes doorbreekt. Willekeurig gegenereerd, geen betekenis buiten "namespace van deze app".
_NAMESPACE = uuid.UUID("2033ffda-2537-4230-bf8e-0019ed645a81")


def rlz_purchase_invoice_id(document_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch client-GUID voor de RLZ-PurchaseInvoice die bij dit document hoort
    (CLAUDE.md, idempotentie-fundament: UUIDv5 op document-id). Een herhaalde boekpoging op
    hetzelfde document — bv. na boeken_mislukt — raakt hierdoor altijd hetzelfde RLZ-document,
    nooit een nieuw duplicaat. Puur een functie van `document_id`, geen state: bewust NIET
    opgeslagen als eigen kolom, om twee bronnen van waarheid voor dezelfde waarde te voorkomen."""
    return uuid.uuid5(_NAMESPACE, str(document_id))


def rlz_upload_id(document_id: uuid.UUID) -> uuid.UUID:
    """Zelfde idempotentie-redenering als rlz_purchase_invoice_id(), voor de PDF-bijlage
    (`RlzClient.upload_bijlage`): een retry na boeken_mislukt uploadt niet telkens een nieuwe
    bijlage naast de vorige, maar overschrijft (PUT) dezelfde."""
    return uuid.uuid5(_NAMESPACE, f"upload:{document_id}")
