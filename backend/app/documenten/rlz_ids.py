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


def rlz_vendor_id(administratie_id: uuid.UUID, naam: str) -> uuid.UUID:
    """Deterministisch client-GUID voor een vanuit de app aangemaakte RLZ-crediteur (fix 2
    2026-07-10: "nieuwe crediteur aanmaken in RLZ" vanaf het controlescherm). Functie van
    administratie + genormaliseerde naam: twee keer op de knop drukken voor dezelfde naam raakt
    dezelfde RLZ-vendor (PUT is idempotent), nooit een duplicaat-crediteur."""
    genormaliseerd = " ".join(naam.split()).lower()
    return uuid.uuid5(_NAMESPACE, f"vendor:{administratie_id}:{genormaliseerd}")


def rlz_bank_boeking_id(payment_transaction_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch client-GUID voor de RLZ-BankMutationDirectBooking die een bankmutatie
    direct op grootboek boekt (bankmodule). Functie van de RLZ-PaymentTransaction-id: een retry
    na een halve mislukking raakt hetzelfde RLZ-document, en de eigen duplicaatcheck in
    app/bank/boeken.py kan aan de PaymentReferenceList zien dat een eerdere poging al slaagde
    (het gekoppelde document draagt exact dit GUID). Elke mutatie heeft hooguit één actieve
    directe boeking — na een storno (actie 19) is een nieuwe boekpoging opnieuw dezelfde PUT op
    hetzelfde GUID, wat het gestorneerde concept-document hergebruikt in plaats van een tweede
    document te laten ontstaan."""
    return uuid.uuid5(_NAMESPACE, f"bankboeking:{payment_transaction_id}")


def rlz_sales_invoice_id(document_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch client-GUID voor de RLZ-SalesInvoice van een omzetboeking (kassarapport-
    document). Zelfde idempotentie-redenering als rlz_purchase_invoice_id — en hier extra
    zwaarwegend: de SalesInvoices-collectie ziet API-aangemaakte facturen niet (STAP 0 §2), dus
    GET-op-dit-GUID is het enige betrouwbare "bestaat mijn factuur al"-pad bij een retry."""
    return uuid.uuid5(_NAMESPACE, f"salesinvoice:{document_id}")


def rlz_kostprijs_memoriaal_id(document_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch client-GUID voor het gekoppelde kostprijsmemoriaal van dezelfde
    omzetboeking — apart van de verkoopfactuur (twee RLZ-documenten, één logische transactie)."""
    return uuid.uuid5(_NAMESPACE, f"kostprijsmemoriaal:{document_id}")


def rlz_omzet_upload_id(document_id: uuid.UUID, *, doel: str) -> uuid.UUID:
    """Client-GUID voor de PDF-bijlage bij de verkoopfactuur (`doel="verkoop"`) of het memoriaal
    (`doel="memoriaal"`) — hetzelfde rapport hangt als bijlage aan béíde documenten (mockup),
    maar de upload-GUID's moeten verschillen (twee documenten, twee uploads)."""
    return uuid.uuid5(_NAMESPACE, f"omzet-upload-{doel}:{document_id}")


def rlz_customer_id(administratie_id: uuid.UUID, naam: str) -> uuid.UUID:
    """Deterministisch client-GUID voor een vanuit de app aangemaakte RLZ-debiteur (systeemdebiteur
    "Kasomzet" per administratie) — zelfde vorm als rlz_vendor_id: dubbel aanmaken raakt dezelfde
    RLZ-Customer, nooit een duplicaat."""
    genormaliseerd = " ".join(naam.split()).lower()
    return uuid.uuid5(_NAMESPACE, f"customer:{administratie_id}:{genormaliseerd}")


def rlz_waarborg_memoriaal_id(document_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch client-GUID voor het waarborg-memoriaal (§2d-waarborgroute v1.11) —
    zelfde idempotentie-redenering als rlz_kostprijs_memoriaal_id: een retry na een halve
    mislukking raakt hetzelfde RLZ-ManualJournal, nooit een tweede."""
    return uuid.uuid5(_NAMESPACE, f"waarborgmemoriaal:{document_id}")


def rlz_upload_id(document_id: uuid.UUID) -> uuid.UUID:
    """Zelfde idempotentie-redenering als rlz_purchase_invoice_id(), voor de PDF-bijlage
    (`RlzClient.upload_bijlage`): een retry na boeken_mislukt uploadt niet telkens een nieuwe
    bijlage naast de vorige, maar overschrijft (PUT) dezelfde."""
    return uuid.uuid5(_NAMESPACE, f"upload:{document_id}")
