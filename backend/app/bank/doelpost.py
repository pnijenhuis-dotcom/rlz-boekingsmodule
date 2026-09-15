"""Doel-post-specs voor de voorstel-kaart (blok E5 nachtrun 01/02-09, mockup bank-voorstel-kaart.html):
tegenpartij, documentsoort, boekstuknummer en factuurdatum — PUUR uit de bestaande payment_item_cache
(Document($expand=Entity)), géén extra RLZ-calls per rij. Ontbreekt een veld in de cache, dan blijft het
None en toont de kaart die regel niet (nooit gokken, nooit een wachtende kaart)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

# RLZ DocumentType (geverifieerd in api-verkenning: 1 = inkoopfactuur/creditnota, 10 = verkoopfactuur/
# Receipt, 19 = bankboeking). Onbekend = geen label — de kaart laat de soort dan weg.
_DOCUMENTSOORT = {1: "Inkoopfactuur", 10: "Verkoopfactuur", 19: "Bankboeking"}
_BOEKSTUK = re.compile(r"\bRLZ-\d{2}-\d+\b")


#: Reference2 = "RLZ-<factuurnummer> <d-m-jjjj>" (STAP-0 15-09 Clean Care: "RLZ-2025689 29-8-2026") — terugval voor de
#: factuurdatum als de Document-expand ontbreekt (rijen van vóór de expand).
_REFERENCE2_DATUM = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")


@dataclass(frozen=True)
class DoelPostSpecs:
    tegenpartij_naam: str | None
    documentsoort: str | None
    boekstuknummer: str | None
    factuurdatum: date | None
    #: Peter 15-09 (Clean Care Arnhem): `Document.Reference` (= `InvoiceNumber`) — de referentie die de bank noemt;
    #: de matchmotor toetst 'm als "nummer" naast RLZ's volgnummer van de post.
    klantreferentie: str | None = None


def _iso_datum(waarde: Any) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def factuurdatum_uit(document: dict[str, Any] | None, referentie2: str | None) -> date | None:
    """De ÉCHTE factuurdatum (Peter 15-09, casus Clean Care: de kaart toonde 12-9-2026 = `PaymentItem.BookDate` =
    vervaldatum, RLZ toont 29-8-2026 = `Document.Date`): `Document.Date` uit de expand, anders de datum in Reference2
    ("RLZ-2025689 29-8-2026"), anders None — nooit de boekdatum van de post als factuurdatum tonen."""
    if document:
        d = _iso_datum(document.get("Date")) or _iso_datum(document.get("BookDate"))
        if d is not None:
            return d
    if referentie2:
        m = _REFERENCE2_DATUM.search(referentie2)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
    return None


def klantreferentie_uit(document: dict[str, Any] | None) -> str | None:
    """`Document.Reference` (RLZ "Referentie", = `InvoiceNumber` bij verkoopfacturen, klantkenmerk bij inkoop), anders
    `InvoiceReference`, anders `InvoiceNumber` — gestript; leeg = None."""
    if not document:
        return None
    for sleutel in ("Reference", "InvoiceReference", "InvoiceNumber"):
        waarde = document.get(sleutel)
        if waarde is None:
            continue
        tekst = str(waarde).strip()
        if tekst:
            return tekst
    return None


def documentsoort_label(document_type: Any) -> str | None:
    try:
        return _DOCUMENTSOORT.get(int(document_type))
    except (TypeError, ValueError):
        return None


def boekstuknummer_uit(document: dict[str, Any] | None, referentie2: str | None) -> str | None:
    """`Document.ReceiptNumber` uit de expand als die er is; anders het RLZ-boekstuk uit Reference2
    (api-verkenning: "RLZ-boekstuknummer + datum")."""
    if document and isinstance(document.get("ReceiptNumber"), str) and document["ReceiptNumber"].strip():
        return document["ReceiptNumber"].strip()
    if referentie2:
        m = _BOEKSTUK.search(referentie2)
        if m:
            return m.group(0)
    return None


def specs_uit_cache(
    *, entity_naam: str | None, brondata: dict[str, Any] | None, referentie2: str | None, boekdatum: date | None
) -> DoelPostSpecs:
    """`boekdatum` (PaymentItem.BookDate) wordt sinds 15-09 NIET meer als factuurdatum gebruikt — het is de vervaldatum
    van de post (STAP-0 Clean Care: BookDate = DueDate = 12-9-2026); de parameter blijft voor de aanroepers."""
    document = (brondata or {}).get("Document") if isinstance(brondata, dict) else None
    document = document if isinstance(document, dict) else None
    return DoelPostSpecs(
        tegenpartij_naam=entity_naam or ((document or {}).get("Entity") or {}).get("Name") or None,
        documentsoort=documentsoort_label((document or {}).get("DocumentType")),
        boekstuknummer=boekstuknummer_uit(document, referentie2),
        factuurdatum=factuurdatum_uit(document, referentie2),
        klantreferentie=klantreferentie_uit(document),
    )
