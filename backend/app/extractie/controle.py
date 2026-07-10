from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.extractie.service import AiFactuurExtractie, AiVeld

# Deterministische controlelaag over de AI-output (kernprincipe: AI leest, code rekent). Pure
# functies op primitieven — geen DB-sessie, geen AI, volledig unit-testbaar (zelfde patroon als
# app/documenten/checks.py). De aanroeper (app/documenten/service.py) levert de vendor-/taxrate-
# kandidaten uit de sync-caches aan; suggesties komen dus per definitie alléén uit de cache.

_ROND_TOLERANTIE = Decimal("0.01")
_FUZZY_DREMPEL = 0.85
# Rechtsvorm-ruis die een exacte naammatch onnodig laat mislukken ("Jansen Bouw B.V." vs
# "Jansen Bouw BV") — alleen voor het matchen genormaliseerd, nooit in de getoonde waarde.
_RECHTSVORM = re.compile(r"\b(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?|holding)\b", re.IGNORECASE)


@dataclass(frozen=True)
class VendorKandidaat:
    id: uuid.UUID
    naam: str


@dataclass(frozen=True)
class TaxRateKandidaat:
    id: uuid.UUID
    percentage: Decimal | None


def parse_bedrag(waarde: str | None) -> Decimal | None:
    """Valide parsen of niets: accepteert punt-decimaal ("1234.56", de gevraagde notatie) en, als
    vangnet, NL-notatie ("1.234,56" — komma is het onderscheidende signaal, zelfde regel als
    app/documenten/schemas.py). Alles wat daarbuiten valt is None — nooit gokken."""
    if not waarde:
        return None
    schoon = waarde.strip().replace("€", "").replace(" ", "")
    if "," in schoon:
        schoon = schoon.replace(".", "").replace(",", ".")
    try:
        bedrag = Decimal(schoon)
    except InvalidOperation:
        return None
    # Bedragen met meer dan 2 decimalen of absurde grootte zijn vrijwel zeker een leesfout.
    if bedrag != bedrag.quantize(_ROND_TOLERANTIE) or abs(bedrag) >= Decimal("100000000"):
        return None
    return bedrag


def parse_datum(waarde: str | None) -> date | None:
    """ISO 8601 + plausibiliteitsvenster; een factuur uit 1926 of 2126 is een leesfout."""
    if not waarde:
        return None
    try:
        datum = date.fromisoformat(waarde.strip()[:10])
    except ValueError:
        return None
    if not (2000 <= datum.year <= 2100):
        return None
    return datum


def _genormaliseerd(naam: str) -> str:
    zonder_rechtsvorm = _RECHTSVORM.sub(" ", naam.lower())
    return re.sub(r"[^a-z0-9]+", " ", zonder_rechtsvorm).strip()


def match_vendor(
    leverancier_naam: str | None, kandidaten: list[VendorKandidaat]
) -> tuple[uuid.UUID | None, str | None]:
    """Crediteur-suggestie uit de vendor-cache: (vendor_id, "exact"|"fuzzy") of (None, None).
    Voorstel, geen automatische keuze — bij meerdere plausibele kandidaten géén suggestie
    (consistent met "nooit auto-toewijzen bij twijfel"). Fuzzy = genormaliseerde naam (zonder
    rechtsvorm/leestekens) exact óf SequenceMatcher ≥ 0.85 met een uniek beste resultaat."""
    if not leverancier_naam:
        return None, None
    doel = _genormaliseerd(leverancier_naam)
    if not doel:
        return None, None

    exact = [k for k in kandidaten if k.naam and k.naam.strip().lower() == leverancier_naam.strip().lower()]
    if len(exact) == 1:
        return exact[0].id, "exact"
    if len(exact) > 1:
        return None, None

    scores: list[tuple[float, VendorKandidaat]] = []
    for kandidaat in kandidaten:
        if not kandidaat.naam:
            continue
        kandidaat_norm = _genormaliseerd(kandidaat.naam)
        if not kandidaat_norm:
            continue
        score = 1.0 if kandidaat_norm == doel else SequenceMatcher(None, doel, kandidaat_norm).ratio()
        if score >= _FUZZY_DREMPEL:
            scores.append((score, kandidaat))
    if not scores:
        return None, None
    scores.sort(key=lambda item: item[0], reverse=True)
    beste_score = scores[0][0]
    besten = [kandidaat for score, kandidaat in scores if beste_score - score < 0.02]
    if len(besten) != 1:
        return None, None
    return besten[0].id, "fuzzy"


def match_taxrate(
    netto: Decimal | None, btw: Decimal | None, kandidaten: list[TaxRateKandidaat]
) -> uuid.UUID | None:
    """Btw-code-suggestie uitsluitend uit de sync-cache: het btw-percentage dat deterministisch
    uit netto/btw van de regel volgt, gematcht op TaxRateCache.percentage (fractie, bv. 0.21).
    Alleen bij precies één passende kandidaat — anders geen suggestie. Verlegd/vrijgesteld (btw
    0 op de regel) krijgt bewust géén automatische suggestie: 0% kan meerdere codes betekenen
    (verlegd, vrijgesteld, 0%-tarief) en dat onderscheid is aangifte-kritisch (CLAUDE.md)."""
    if netto is None or btw is None or netto == 0 or btw == 0:
        return None
    passend = [
        kandidaat
        for kandidaat in kandidaten
        if kandidaat.percentage is not None
        and kandidaat.percentage != 0
        and abs(netto * kandidaat.percentage - btw) <= _ROND_TOLERANTIE
    ]
    if len(passend) == 1:
        return passend[0].id
    # Nul of meerdere passende codes (bv. 21% inkoop én 21% verkoop als aparte TaxRates): geen
    # gok — de controleur kiest zelf uit de combobox.
    return None


def _bedrag_str(bedrag: Decimal | None) -> str | None:
    return str(bedrag) if bedrag is not None else None


def bouw_veldvoorstel(
    extractie: AiFactuurExtractie,
    *,
    vendors: list[VendorKandidaat],
    taxrates: list[TaxRateKandidaat],
    zekerheid_drempel: float,
) -> dict:
    """Zet de AI-extractie om in het veldvoorstel-dict dat (net als het UBL-voorstel) in de
    document-tijdlijn wordt opgeslagen en het controlescherm voedt. Alle cijfers hier zijn door
    déze code geparst en getoetst; onparseerbare waarden worden leeg gelaten en benoemd
    (controle.onparseerbaar) — nooit een gok doorgegeven. De AI-tekstwaarde blijft wel zichtbaar
    in `ruw` zodat de controleur ziet wat er gelezen is."""
    kop = extractie.kop

    def veld(naam: str) -> AiVeld:
        return kop.get(naam, AiVeld(waarde=None, zekerheid=0.0))

    onparseerbaar: list[str] = []
    lage_zekerheid: list[str] = []
    zekerheid: dict[str, float] = {}

    def bedrag_van(naam: str) -> Decimal | None:
        v = veld(naam)
        zekerheid[naam] = v.zekerheid
        if v.waarde is not None and v.zekerheid < zekerheid_drempel:
            lage_zekerheid.append(naam)
        bedrag = parse_bedrag(v.waarde)
        if v.waarde is not None and bedrag is None:
            onparseerbaar.append(naam)
        return bedrag

    def datum_van(naam: str) -> date | None:
        v = veld(naam)
        zekerheid[naam] = v.zekerheid
        if v.waarde is not None and v.zekerheid < zekerheid_drempel:
            lage_zekerheid.append(naam)
        datum = parse_datum(v.waarde)
        if v.waarde is not None and datum is None:
            onparseerbaar.append(naam)
        return datum

    def tekst_van(naam: str) -> str | None:
        v = veld(naam)
        zekerheid[naam] = v.zekerheid
        if v.waarde is not None and v.zekerheid < zekerheid_drempel:
            lage_zekerheid.append(naam)
        return v.waarde

    leverancier_naam = tekst_van("leverancier_naam")
    factuurnummer = tekst_van("factuurnummer")
    valuta = tekst_van("valuta")
    factuurdatum = datum_van("factuurdatum")
    vervaldatum = datum_van("vervaldatum")
    totaal_excl = bedrag_van("totaal_excl")
    totaal_incl = bedrag_van("totaal_incl")
    btw_bedrag = bedrag_van("btw_bedrag")

    vendor_id, vendor_match = match_vendor(leverancier_naam, vendors)

    regels: list[dict] = []
    regel_zekerheid: list[float] = []
    regelsom = Decimal(0)
    regelsom_compleet = True
    for index, regel in enumerate(extractie.regels, start=1):
        netto = parse_bedrag(regel.netto_bedrag)
        btw = parse_bedrag(regel.btw_bedrag)
        if regel.netto_bedrag is not None and netto is None:
            onparseerbaar.append(f"netto_bedrag (regel {index})")
        if regel.btw_bedrag is not None and btw is None:
            onparseerbaar.append(f"btw_bedrag (regel {index})")
        if netto is None:
            regelsom_compleet = False
        regelsom += (netto or Decimal(0)) + (btw or Decimal(0))
        taxrate_id = match_taxrate(netto, btw, taxrates)
        regels.append(
            {
                "omschrijving": regel.omschrijving,
                "netto_bedrag": _bedrag_str(netto),
                "btw_bedrag": _bedrag_str(btw),
                "hoeveelheid": regel.hoeveelheid,
                "taxrate_id": str(taxrate_id) if taxrate_id else None,
            }
        )
        regel_zekerheid.append(regel.zekerheid)
        if regel.zekerheid < zekerheid_drempel:
            lage_zekerheid.append(f"regel {index}")

    regelsom_wijkt_af: bool | None = None
    if regels and regelsom_compleet and totaal_incl is not None:
        regelsom_wijkt_af = abs(regelsom - totaal_incl) > _ROND_TOLERANTIE

    return {
        "bron": "ai",
        "leverancier_naam": leverancier_naam,
        "factuurnummer": factuurnummer,
        "factuurdatum": factuurdatum.isoformat() if factuurdatum else None,
        "vervaldatum": vervaldatum.isoformat() if vervaldatum else None,
        "valuta": valuta,
        "totaal_excl": _bedrag_str(totaal_excl),
        "totaal_incl": _bedrag_str(totaal_incl),
        "btw_bedrag": _bedrag_str(btw_bedrag),
        "regelaantal": len(regels),
        "regels": regels,
        "zekerheid": zekerheid,
        "regel_zekerheid": regel_zekerheid,
        # De drempel reist mee zodat de frontend exact dezelfde grens markeert als de backend
        # hanteerde — geen tweede, hardcoded drempel die stil uit de pas kan lopen.
        "zekerheid_drempel": zekerheid_drempel,
        "vendor_suggestie": (
            {"vendor_id": str(vendor_id), "match": vendor_match} if vendor_id is not None else None
        ),
        "controle": {
            "regelsom": _bedrag_str(regelsom) if regels and regelsom_compleet else None,
            "regelsom_wijkt_af": regelsom_wijkt_af,
            "onparseerbaar": onparseerbaar,
            "lage_zekerheid": lage_zekerheid,
            "bsn_verwijderd": extractie.bsn_verwijderd,
            # True = ook chunking kreeg de regelset niet aantoonbaar compleet — bij
            # projectadministraties komt dit voorstel er überhaupt niet (documenten/service
            # blokkeert dan), bij andere administraties is dit het oranje signaal voor de
            # controleur naast de regelsom-check.
            "onvolledig": not extractie.volledig,
        },
    }
