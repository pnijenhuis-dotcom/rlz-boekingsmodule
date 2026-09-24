"""Bijlage-paren bundelen vóór de routing (diagnose intake 02-09, punt 2 — casus 2026-8151.xml +
.pdf, 114164, V01260706): één factuur die als UBL én als PDF in dezelfde mail zit wordt één
document — de UBL leidend voor de velden en de tenaamstelling (deterministisch, geen AI-call voor
de PDF), de PDF als beeld via het bestaande `bron_bestand`-mechanisme (document.bron_*).

Deterministisch, in deze volgorde:
1. **Ingesloten-PDF-hash** — de UBL draagt een `cac:AdditionalDocumentReference` mét
   `EmbeddedDocumentBinaryObject` (PrimaryImage); is de sha256 daarvan gelijk aan die van een
   losse PDF-bijlage, dan horen ze aantoonbaar bij elkaar.
2. **Naamstam (genormaliseerd)** — anders: `.xml` en `.pdf` met dezelfde bestandsnaam-stam in dezelfde
   mail, waarbij een suffix `-ubl`/`_ubl`/`-xml`/`_xml` (hoofdletterongevoelig) vóór de vergelijking van de
   stam wordt gestript (Vastly-batch 23-09: `factuur-RUB-2026-0031-ubl.xml` + `factuur-RUB-2026-0031.pdf` —
   blok 1 bundelrun 24-09); uitsluitend als er precies één kandidaat is (twee PDF's met dezelfde stam =
   twijfel = geen paar).
3. **Factuurnummer** — anders: het UBL-factuurnummer (`cbc:ID`, ≥ 4 tekens) komt tekstueel voor in de
   PDF-bestandsnaam óf in de PDF-tekstlaag (pypdf, genormaliseerd: witruimte weg + casefold), en er is
   precies één zo'n PDF-kandidaat (blok 1 bundelrun 24-09).
4. Een UBL mét ingesloten PDF maar zónder losse PDF-bijlage krijgt de ingesloten PDF als beeld
   (dat lost "geen voorbeeld op de XML-rij" op zonder tweede rij).

Alles wat niet in een paar valt blijft een losse bijlage in de oorspronkelijke volgorde. Wat de
detectie mist, vangt de handmatige "Samenvoegen"-actie in de verzamelbak (app/intake/verzamelbak.py).
Puur; geen DB, geen I/O."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.documenten.ubl import GeenGeldigeUbl, lees_ingesloten_pdf, parseer_ubl_factuur
from app.intake.eml import IntakeBijlage

logger = logging.getLogger(__name__)

REDEN_INGESLOTEN_HASH = "ingesloten_pdf_hash"
REDEN_NAAMSTAM = "naamstam"
REDEN_FACTUURNUMMER = "factuurnummer"
REDEN_INGESLOTEN_ALLEEN = "ingesloten_pdf"

#: Suffixen die een UBL-exporteur achter de factuurstam plakt (Vastly 23-09: `…-ubl.xml`) — gestript vóór de
#: stam-vergelijking, aan beide kanten (symmetrisch: een PDF `…-xml.pdf` zou 'm ook verliezen).
_STAM_SUFFIX_RE = re.compile(r"[-_](ubl|xml)$", re.IGNORECASE)
#: Een factuurnummer korter dan dit is te generiek om op te paren ("1", "2026").
MIN_FACTUURNUMMER_LENGTE = 4


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


def genormaliseerde_stam(bestandsnaam: str) -> str:
    """Stam zonder exporteur-suffix: `factuur-RUB-2026-0031-ubl.xml` → `factuur-rub-2026-0031`."""
    return _STAM_SUFFIX_RE.sub("", _stam(bestandsnaam)).strip()


def normaliseer_tekst(tekst: str) -> str:
    """Álle witruimte weg + casefold — dezelfde toets als `app/doorbelasting/factuur.normaliseer_tekst` (pypdf
    breekt tekst in fragmenten); één plek voor de bundeling zodat het intake-pad geen doorbelasting-import draagt."""
    return re.sub(r"\s+", "", tekst).casefold()


def ubl_factuurnummer(inhoud: bytes) -> str | None:
    """`cbc:ID` van de UBL, of None als de UBL onleesbaar is of het nummer te kort/generiek (< 4 tekens)."""
    try:
        nummer = parseer_ubl_factuur(inhoud).factuurnummer
    except GeenGeldigeUbl:
        return None
    nummer = (nummer or "").strip()
    return nummer if len(nummer) >= MIN_FACTUURNUMMER_LENGTE else None


def pdf_tekstlaag_genormaliseerd(inhoud: bytes) -> str:
    """Genormaliseerde tekstlaag van een PDF (lege string bij geen/kapotte tekstlaag — nooit een fout)."""
    from io import BytesIO

    from pypdf import PdfReader

    try:
        lezer = PdfReader(BytesIO(inhoud))
        return normaliseer_tekst("\n".join((pagina.extract_text() or "") for pagina in lezer.pages))
    except Exception:  # noqa: BLE001 — onleesbare PDF telt als "geen tekst"
        return ""


def pdf_draagt_factuurnummer(
    bestandsnaam: str, inhoud: bytes | None, factuurnummer: str, *, tekstlaag: str | None = None
) -> bool:
    """Staat het factuurnummer tekstueel in de PDF-bestandsnaam óf in de (genormaliseerde) tekstlaag? `tekstlaag`
    = al berekende genormaliseerde tekst (cache); zonder tekstlaag én zonder inhoud telt alleen de bestandsnaam."""
    nummer = normaliseer_tekst(factuurnummer)
    if not nummer or len(nummer) < MIN_FACTUURNUMMER_LENGTE:
        return False
    if nummer in normaliseer_tekst(bestandsnaam):
        return True
    if tekstlaag is None:
        tekstlaag = pdf_tekstlaag_genormaliseerd(inhoud) if inhoud is not None else ""
    return nummer in tekstlaag


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

    # Stap 2: naamstam (genormaliseerd — exporteur-suffix `-ubl`/`_ubl`/`-xml`/`_xml` weg; alleen ondubbelzinnig).
    for b in bijlagen:
        if not b.is_xml or id(b) in paren:
            continue
        stam = genormaliseerde_stam(b.bestandsnaam)
        kandidaten = [
            pdf for pdf in pdfs if id(pdf) not in gebruikt and stam and genormaliseerde_stam(pdf.bestandsnaam) == stam
        ]
        if len(kandidaten) == 1:
            paren[id(b)] = BijlagePaar(ubl=b, pdf=kandidaten[0], reden=REDEN_NAAMSTAM, pdf_is_losse_bijlage=True)
            gebruikt.add(id(kandidaten[0]))

    # Stap 3: factuurnummer (UBL cbc:ID) in de PDF-bestandsnaam of -tekstlaag (alleen ondubbelzinnig).
    tekstlagen: dict[int, str] = {}
    for b in bijlagen:
        if not b.is_xml or id(b) in paren:
            continue
        vrije = [pdf for pdf in pdfs if id(pdf) not in gebruikt]
        if not vrije:
            continue
        nummer = ubl_factuurnummer(b.inhoud)
        if nummer is None:
            continue
        kandidaten = []
        for pdf in vrije:
            if id(pdf) not in tekstlagen:
                tekstlagen[id(pdf)] = pdf_tekstlaag_genormaliseerd(pdf.inhoud)
            if pdf_draagt_factuurnummer(pdf.bestandsnaam, None, nummer, tekstlaag=tekstlagen[id(pdf)]):
                kandidaten.append(pdf)
        if len(kandidaten) == 1:
            paren[id(b)] = BijlagePaar(ubl=b, pdf=kandidaten[0], reden=REDEN_FACTUURNUMMER, pdf_is_losse_bijlage=True)
            gebruikt.add(id(kandidaten[0]))
        elif len(kandidaten) > 1:
            logger.info(
                "bundeling: factuurnummer %s past op %d PDF's — niet gebundeld (twijfel)", nummer, len(kandidaten)
            )

    # Stap 4: UBL mét ingesloten PDF, zonder losse PDF → de ingesloten PDF als beeld.
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
