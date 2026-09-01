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


@dataclass(frozen=True)
class DoelPostSpecs:
    tegenpartij_naam: str | None
    documentsoort: str | None
    boekstuknummer: str | None
    factuurdatum: date | None


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
    document = (brondata or {}).get("Document") if isinstance(brondata, dict) else None
    document = document if isinstance(document, dict) else None
    return DoelPostSpecs(
        tegenpartij_naam=entity_naam or ((document or {}).get("Entity") or {}).get("Name") or None,
        documentsoort=documentsoort_label((document or {}).get("DocumentType")),
        boekstuknummer=boekstuknummer_uit(document, referentie2),
        factuurdatum=boekdatum,
    )
