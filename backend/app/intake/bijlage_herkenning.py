"""Welke bijlage van een mail is een FACTUUR en welke hoort erbij als bijlage? (Peter 02-10 "één mail = één document —
alle bijlagen vanuit de verhuur zijn losgekoppeld van de factuur … dat moet als eerste gefixt worden, scheelt heel veel
werk"; BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)").

Deterministisch per bijlage, vóór élke AI-stap, drie klassen:
- FACTUUR — een UBL (altijd een factuur: `cbc:ID` + totalen + partijen) óf een PDF mét tekstlaag die de drie
  factuursignalen draagt: een factuurwoord (factuur/invoice/creditnota), een totaalsignaal (totaal/te betalen/amount
  due/…) én een btw-/bedragsignaal (btw/vat/€/eur). Een huurstaat, specificatie of werkbon draagt die drie niet samen.
- KANDIDAAT — niet deterministisch te zeggen: een PDF ZONDER tekstlaag (scan, foto-naar-PDF), een ProfX-kassarapport
  (eigen omzetroute), een omzetbron-spreadsheet (dagstaat/kascheck/betalingsexport — eigen route), een inline/te
  kleine afbeelding (logo-filter) en élk bijlagetype dat de intake niet kent. Kandidaten lopen de BESTAANDE routing
  (AI-splitsing, verzamelbak, niet_verwerkbaar) — niets verandert daar.
- BIJLAGE — een PDF mét tekstlaag zónder de factuursignalen, een spreadsheet die geen omzetbron is, een csv/doc(x)
  en een (niet-inline, groot genoeg) foto: dat hoort bij de factuur uit dezelfde mail (specificatie, huurstaat,
  werkbon, foto). Niet extraheren, niet splitsen, geen eigen werkvoorraad-rij.

De MAIL-regel staat in `app/intake/verwerking.py::_verdeel_bijlagen`: precies één factuur(-document) → álle BIJLAGEN
eraan; meerdere → treffer op factuur-/werknummer in bestandsnaam of tekst, anders bij álle facturen mét chip
"bijlage niet eenduidig" (liever dubbel dan kwijt); nul facturen → bestaand gedrag (de bijlagen lopen de oude route).
Puur: geen DB, geen I/O behalve de tekstlaag-lezing van de PDF-bytes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.intake.bundeling import BijlagePaar, BundelItem, normaliseer_tekst, pdf_tekstlaag_genormaliseerd
from app.intake.eml import IntakeBijlage

KLASSE_FACTUUR = "factuur"
KLASSE_KANDIDAAT = "kandidaat"
KLASSE_BIJLAGE = "bijlage"

#: Bijlagetypen die als bijlage bij een factuur horen (naast PDF-zonder-factuursignalen en foto's). Bewust een
#: whitelist: handtekening-vCards, .ics, .p7s en ander mailgruis blijven `niet_verwerkbaar` (bestaande route).
BIJLAGE_EXTENSIES = frozenset({".xlsx", ".xls", ".csv", ".docx", ".doc", ".txt"})

# Factuursignalen op de GENORMALISEERDE tekstlaag (witruimte weg + casefold — `bundeling.normaliseer_tekst`).
_FACTUURWOORD = re.compile(r"factuur|invoice|creditnota|creditnote|credit-note|facture|rechnung")
_TOTAALSIGNAAL = re.compile(r"totaal|total|tebetalen|amountdue|eindbedrag|teontvangen|balancedue")
_BTW_OF_BEDRAG = re.compile(r"\bbtw\b|btw|\bvat\b|vat|€|\beur\b|eur\d|\d,\d{2}")
#: Cijfer-tokens van 3–6 cijfers (werk-/projectnummers, factuurnummer-kernen) — zelfde grens als
#: `app/projecten/match.nummers_in`.
_NUMMER_TOKEN = re.compile(r"(?<![\d.,-])(\d{3,6})(?![\d.,-])")


@dataclass(frozen=True)
class Herkenning:
    klasse: str
    reden: str


def heeft_factuursignalen(tekstlaag_genormaliseerd: str) -> bool:
    """Drie signalen samen op één tekstlaag: factuurwoord + totaal + btw/bedrag. Lege tekst = False."""
    t = tekstlaag_genormaliseerd
    if not t:
        return False
    return bool(_FACTUURWOORD.search(t) and _TOTAALSIGNAAL.search(t) and _BTW_OF_BEDRAG.search(t))


def herken_pdf(inhoud: bytes, *, tekstlaag: str | None = None) -> Herkenning:
    """PDF: ProfX-kassarapport → kandidaat (eigen route); geen tekstlaag → kandidaat (scan: alleen de AI kan het
    zeggen); factuursignalen → factuur; anders bijlage."""
    from app.omzet.bronnen import herkenning as omzet_herkenning

    try:
        if omzet_herkenning.herken_pdf(inhoud) is not None:
            return Herkenning(KLASSE_KANDIDAAT, "kassarapport (ProfX) — eigen omzetroute")
    except Exception:  # noqa: BLE001 — onleesbaar = geen omzetbron
        pass
    laag = tekstlaag if tekstlaag is not None else pdf_tekstlaag_genormaliseerd(inhoud)
    if not laag.strip():
        return Herkenning(KLASSE_KANDIDAAT, "PDF zonder tekstlaag (scan) — niet deterministisch te herkennen")
    if heeft_factuursignalen(laag):
        return Herkenning(KLASSE_FACTUUR, "PDF mét factuursignalen (factuurwoord + totaal + btw/bedrag)")
    return Herkenning(KLASSE_BIJLAGE, "PDF mét tekstlaag zonder factuursignalen")


def _is_omzetbron_spreadsheet(bijlage: IntakeBijlage) -> bool:
    from app.omzet.bronnen import herken_bron

    try:
        return herken_bron(bijlage.bestandsnaam, bijlage.inhoud) is not None
    except Exception:  # noqa: BLE001
        return False


def _afbeelding_groot_genoeg(bijlage: IntakeBijlage) -> bool:
    """Zelfde drempel als de logo-filter in verwerking (MIN_DOCUMENT_PIXELS): een te klein plaatje is ruis."""
    from app.documenten.afbeelding import AfbeeldingOnbruikbaar, afbeelding_naar_pdf

    try:
        omgezet = afbeelding_naar_pdf(bijlage.inhoud, bestandsnaam=bijlage.bestandsnaam)
    except AfbeeldingOnbruikbaar:
        return False
    from app.intake.verwerking import MIN_DOCUMENT_PIXELS

    return not (omgezet.breedte < MIN_DOCUMENT_PIXELS and omgezet.hoogte < MIN_DOCUMENT_PIXELS)


def herken_bijlage(bijlage: IntakeBijlage, *, logo_filter: bool = True) -> Herkenning:
    """Eén losse mailbijlage → klasse + leesbare reden (de reden landt in het intake-bericht)."""
    if bijlage.is_xml:
        return Herkenning(KLASSE_FACTUUR, "UBL/XML = factuur")
    if bijlage.is_pdf:
        return herken_pdf(bijlage.inhoud)
    if bijlage.is_afbeelding:
        if logo_filter and bijlage.inline:
            return Herkenning(KLASSE_KANDIDAAT, "inline afbeelding (logo/handtekening) — bestaande filter")
        if logo_filter and not _afbeelding_groot_genoeg(bijlage):
            return Herkenning(KLASSE_KANDIDAAT, "afbeelding te klein voor een document — bestaande filter")
        return Herkenning(KLASSE_BIJLAGE, "foto/afbeelding bij de factuur")
    if bijlage.is_spreadsheet:
        if _is_omzetbron_spreadsheet(bijlage):
            return Herkenning(KLASSE_KANDIDAAT, "omzetbron-spreadsheet (dagstaat/kascheck) — eigen route")
        return Herkenning(KLASSE_BIJLAGE, "spreadsheet (geen omzetbron) bij de factuur")
    if Path(bijlage.bestandsnaam).suffix.lower() in BIJLAGE_EXTENSIES:
        return Herkenning(KLASSE_BIJLAGE, f"{Path(bijlage.bestandsnaam).suffix.lower()}-bestand bij de factuur")
    return Herkenning(KLASSE_KANDIDAAT, f"bijlagetype {bijlage.content_type} — bestaande route (niet verwerkbaar)")


def herken_item(item: BundelItem, *, logo_filter: bool = True) -> Herkenning:
    """Een gebundeld UBL+PDF-paar is per definitie een factuur; een losse bijlage via `herken_bijlage`."""
    if isinstance(item, BijlagePaar):
        return Herkenning(KLASSE_FACTUUR, "UBL+PDF-paar = factuur")
    return herken_bijlage(item, logo_filter=logo_filter)


def sleutels_uit_ubl(inhoud: bytes) -> frozenset[str]:
    """Factuurnummer (`cbc:ID`) + cijfer-tokens (werknummers) uit de UBL-`cbc:Note` — genormaliseerd, ≥ 4 tekens."""
    from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur

    try:
        factuur = parseer_ubl_factuur(inhoud)
    except GeenGeldigeUbl:
        return frozenset()
    uit: set[str] = set()
    nummer = normaliseer_tekst(factuur.factuurnummer or "")
    if len(nummer) >= 4:
        uit.add(nummer)
    note = getattr(factuur, "note", None) or ""
    for token in _NUMMER_TOKEN.findall(str(note)):
        if len(token) >= 4:
            uit.add(token)
    return frozenset(uit)


def sleutels_uit_tekst(*teksten: str | None) -> frozenset[str]:
    """Genormaliseerde sleutels uit vrije tekst (bv. het AI-gelezen factuurnummer van een PDF-factuur)."""
    uit: set[str] = set()
    for tekst in teksten:
        genormaliseerd = normaliseer_tekst(tekst or "")
        if len(genormaliseerd) >= 4:
            uit.add(genormaliseerd)
    return frozenset(uit)


def bijlage_draagt_sleutel(
    bestandsnaam: str, inhoud: bytes | None, sleutels: frozenset[str], *, tekstlaag: str | None = None
) -> bool:
    """Staat één van de sleutels (factuur-/werknummer) in de bestandsnaam of — bij een PDF — in de tekstlaag?"""
    if not sleutels:
        return False
    naam = normaliseer_tekst(bestandsnaam)
    if any(s in naam for s in sleutels):
        return True
    if bestandsnaam.lower().endswith(".pdf"):
        laag = tekstlaag if tekstlaag is not None else (pdf_tekstlaag_genormaliseerd(inhoud) if inhoud else "")
        return any(s in laag for s in sleutels)
    return False
