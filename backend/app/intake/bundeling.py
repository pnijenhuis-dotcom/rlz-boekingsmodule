"""Bijlage-paren bundelen vóór de routing (diagnose intake 02-09, punt 2 — casus 2026-8151.xml +
.pdf, 114164, V01260706): één factuur die als UBL én als PDF in dezelfde mail zit wordt één
document — de UBL leidend voor de velden en de tenaamstelling (deterministisch, geen AI-call voor
de PDF), de PDF als beeld via het bestaande `bron_bestand`-mechanisme (document.bron_*).

Deterministisch, in deze volgorde:
1. **Ingesloten-PDF-hash** — de UBL draagt een `cac:AdditionalDocumentReference` mét
   `EmbeddedDocumentBinaryObject` (PrimaryImage); is de sha256 daarvan gelijk aan die van een
   losse PDF-bijlage, dan horen ze aantoonbaar bij elkaar.
2. **Naamstam** — anders: `.xml` en `.pdf` met exact dezelfde bestandsnaam-stam in dezelfde mail,
   uitsluitend als er precies één kandidaat is (twee PDF's met dezelfde stam = twijfel = geen paar).
3. Een UBL mét ingesloten PDF maar zónder losse PDF-bijlage krijgt de ingesloten PDF als beeld
   (dat lost "geen voorbeeld op de XML-rij" op zonder tweede rij).

Alles wat niet in een paar valt blijft een losse bijlage in de oorspronkelijke volgorde. Wat de
detectie mist, vangt de handmatige "Samenvoegen"-actie in de verzamelbak (app/intake/verzamelbak.py).
Puur; geen DB, geen I/O."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.documenten.ubl import lees_ingesloten_pdf
from app.intake.eml import IntakeBijlage

REDEN_INGESLOTEN_HASH = "ingesloten_pdf_hash"
REDEN_NAAMSTAM = "naamstam"
REDEN_INGESLOTEN_ALLEEN = "ingesloten_pdf"


@dataclass(frozen=True)
class BijlagePaar:
    """UBL + PDF die samen één document worden. `pdf_is_losse_bijlage` = de PDF was een eigen
    mailbijlage (en krijgt dus een eigen 'gebundeld'-regel in het intake-bericht); False = de PDF
    komt uit de UBL zelf."""

    ubl: IntakeBijlage
    pdf: IntakeBijlage
    reden: str
    pdf_is_losse_bijlage: bool


BundelItem = IntakeBijlage | BijlagePaar


def _sha256(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


def _stam(bestandsnaam: str) -> str:
    return Path(bestandsnaam).stem.strip().lower()


def bundel_bijlagen(bijlagen: list[IntakeBijlage]) -> list[BundelItem]:
    """Bundelt UBL+PDF-paren; volgorde = die van de UBL (het leidende bestand). Nooit twee UBL's of
    twee PDF's aan elkaar; nooit een PDF aan meer dan één UBL."""
    pdfs = [b for b in bijlagen if b.is_pdf and not b.is_xml]
    gebruikt: set[int] = set()  # id() van gepaarde PDF-bijlagen
    paren: dict[int, BijlagePaar] = {}  # id(ubl) → paar

    # Stap 1: ingesloten-PDF-hash.
    ingesloten: dict[int, IntakeBijlage | None] = {}
    for b in bijlagen:
        if not b.is_xml:
            continue
        gevonden = lees_ingesloten_pdf(b.inhoud)
        ingesloten[id(b)] = (
            IntakeBijlage(bestandsnaam=gevonden.bestandsnaam, inhoud=gevonden.inhoud, content_type="application/pdf")
            if gevonden
            else None
        )
        if gevonden is None:
            continue
        hash_ingesloten = _sha256(gevonden.inhoud)
        for pdf in pdfs:
            if id(pdf) in gebruikt:
                continue
            if _sha256(pdf.inhoud) == hash_ingesloten:
                paren[id(b)] = BijlagePaar(ubl=b, pdf=pdf, reden=REDEN_INGESLOTEN_HASH, pdf_is_losse_bijlage=True)
                gebruikt.add(id(pdf))
                break

    # Stap 2: naamstam (alleen ondubbelzinnig).
    for b in bijlagen:
        if not b.is_xml or id(b) in paren:
            continue
        kandidaten = [pdf for pdf in pdfs if id(pdf) not in gebruikt and _stam(pdf.bestandsnaam) == _stam(b.bestandsnaam)]
        if len(kandidaten) == 1:
            paren[id(b)] = BijlagePaar(ubl=b, pdf=kandidaten[0], reden=REDEN_NAAMSTAM, pdf_is_losse_bijlage=True)
            gebruikt.add(id(kandidaten[0]))

    # Stap 3: UBL mét ingesloten PDF, zonder losse PDF → de ingesloten PDF als beeld.
    for b in bijlagen:
        if not b.is_xml or id(b) in paren:
            continue
        pdf = ingesloten.get(id(b))
        if pdf is not None:
            paren[id(b)] = BijlagePaar(ubl=b, pdf=pdf, reden=REDEN_INGESLOTEN_ALLEEN, pdf_is_losse_bijlage=False)

    items: list[BundelItem] = []
    for b in bijlagen:
        if id(b) in gebruikt:
            continue  # gepaarde PDF: reist mee met zijn UBL
        items.append(paren.get(id(b), b))
    return items
