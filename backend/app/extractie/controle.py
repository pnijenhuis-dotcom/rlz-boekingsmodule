from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer
from app.extractie.iban import is_geldig_iban, normaliseer_iban
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
    # Punt 14 (28-08): bekende nummers per crediteur (crediteur_kenmerk + RLZ-KvK uit de vendor-cache)
    # — een nummer-match wint vóór de fuzzy naam-match (Wola vs Wola b.v.).
    btw_nummer: str | None = None
    kvk_nummer: str | None = None


@dataclass(frozen=True)
class TaxRateKandidaat:
    id: uuid.UUID
    percentage: Decimal | None
    # RLZ-vlaggen uit TaxRateCache.brondata (feedbackronde 26-08 punt 3). `is_favoriet` =
    # RLZ's eigen `IsFavorite` — de deterministische tiebreak tussen tarieven met hetzélfde
    # percentage ("NL, Hoog Tarief" vs "NL, Hoog Tarief (vooruit)" zijn beide 21%; in alle 14
    # gesyncte administraties draagt precies één van beide de vlag). Verlegd/vrijgesteld/gemengd
    # ("BTW-bedrag zelf specificeren") doen nooit mee in de bedrag-afleiding.
    is_favoriet: bool = False
    is_verlegd: bool = False
    is_vrijgesteld: bool = False
    is_gemengd: bool = False


@dataclass(frozen=True)
class BtwAfleiding:
    """Uitkomst van `leid_btw_af`: het tarief dat deterministisch uit netto/btw van de regel
    volgt. `taxrate_id` None = niets invullen (0/onbepaalbaar/meerduidig) — dan geldt de
    bestaande volgorde (boekingsgeheugen per leverancier, anders mens). `bron` is altijd
    "factuur": een factuur-afgeleide waarde is géén seed-only-geheugenwaarde en mag dus als
    ingevuld voorstel staan; de harde checks blijven de poort."""

    taxrate_id: uuid.UUID | None
    percentage: Decimal | None
    bron: str | None
    # Waarom er níet ingevuld is (leesbaar in tests/tijdlijn): "btw_nul", "geen_match",
    # "meerduidig"; None bij een geslaagde afleiding.
    reden: str | None = None


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
    leverancier_naam: str | None,
    kandidaten: list[VendorKandidaat],
    *,
    btw_nummer: str | None = None,
    kvk_nummer: str | None = None,
) -> tuple[uuid.UUID | None, str | None]:
    """Crediteur-suggestie uit de vendor-cache: (vendor_id, "btw_nummer"|"kvk_nummer"|"exact"|"fuzzy")
    of (None, None). Voorstel, geen automatische keuze — bij meerdere plausibele kandidaten géén
    suggestie (consistent met "nooit auto-toewijzen bij twijfel").

    Volgorde (punt 14, besluit Peter 27-08): éérst het btw-nummer van de factuur tegen de bekende
    nummers per crediteur, dan het KvK-nummer, dan pas de naam — exact, dan fuzzy (genormaliseerde
    naam zonder rechtsvorm/leestekens exact óf SequenceMatcher ≥ 0.85 met een uniek beste resultaat).
    Een nummer dat bij méér dan één crediteur hoort (dubbele crediteur in RLZ) geeft géén
    nummer-suggestie en valt terug op de naam — de dubbel-signalering op Instellingen toont 'm."""
    if btw_nummer:
        op_btw = [k for k in kandidaten if k.btw_nummer and k.btw_nummer == btw_nummer]
        if len(op_btw) == 1:
            return op_btw[0].id, "btw_nummer"
    if kvk_nummer:
        op_kvk = [k for k in kandidaten if k.kvk_nummer and k.kvk_nummer == kvk_nummer]
        if len(op_kvk) == 1:
            return op_kvk[0].id, "kvk_nummer"
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


def leid_btw_af(netto: Decimal | None, btw: Decimal | None, kandidaten: list[TaxRateKandidaat]) -> BtwAfleiding:
    """Btw-code deterministisch uit de regel afleiden (CODE, geen AI — feedbackronde 26-08 punt 3):
    netto × tarief ≈ btw-bedrag (tolerantie ±1 cent per regel) tegen de gesyncte TaxRates van de
    administratie (percentage = fractie, bv. 0.21 — zie app/sync/btw.py voor de eenheidsregel).

    HARD: bij 0/onbepaalbaar/meerduidig NOOIT invullen. 0% is ambigu (0%-tarief/vrijgesteld/
    verlegd — de bouwketen-norm is verlegd) en aangifte-kritisch; daar wint het boekingsgeheugen
    per leverancier, anders kiest de mens. Negatieve regels (creditnota) rekenen gewoon mee:
    −100 × 0,21 = −21.

    Meerdere tarieven met hetzélfde percentage (RLZ: "Hoog Tarief" én "Hoog Tarief (vooruit)"):
    precies één RLZ-favoriet → die; anders meerduidig = leeg. Twee verschillende percentages die
    beide binnen de tolerantie vallen (alleen bij centbedragen) = meerduidig = leeg."""
    if netto is None or btw is None or netto == 0:
        return BtwAfleiding(taxrate_id=None, percentage=None, bron=None, reden="onbepaalbaar")
    if btw == 0:
        return BtwAfleiding(taxrate_id=None, percentage=None, bron=None, reden="btw_nul")
    passend = [
        kandidaat
        for kandidaat in kandidaten
        if kandidaat.percentage is not None
        and kandidaat.percentage > 0
        and not (kandidaat.is_verlegd or kandidaat.is_vrijgesteld or kandidaat.is_gemengd)
        and abs(netto * kandidaat.percentage - btw) <= _ROND_TOLERANTIE
    ]
    if not passend:
        return BtwAfleiding(taxrate_id=None, percentage=None, bron=None, reden="geen_match")
    percentages = {kandidaat.percentage for kandidaat in passend}
    if len(percentages) > 1:
        return BtwAfleiding(taxrate_id=None, percentage=None, bron=None, reden="meerduidig")
    percentage = next(iter(percentages))
    if len(passend) == 1:
        return BtwAfleiding(taxrate_id=passend[0].id, percentage=percentage, bron="factuur")
    favorieten = [kandidaat for kandidaat in passend if kandidaat.is_favoriet]
    if len(favorieten) == 1:
        return BtwAfleiding(taxrate_id=favorieten[0].id, percentage=percentage, bron="factuur")
    # Nul of meerdere favorieten met hetzelfde percentage: geen gok — de controleur kiest.
    return BtwAfleiding(taxrate_id=None, percentage=percentage, bron=None, reden="meerduidig")


def match_taxrate(
    netto: Decimal | None, btw: Decimal | None, kandidaten: list[TaxRateKandidaat]
) -> uuid.UUID | None:
    """Alleen het tarief-id uit `leid_btw_af` (compat-vorm voor bestaande aanroepers/tests)."""
    return leid_btw_af(netto, btw, kandidaten).taxrate_id


def is_verlegd_vermelding(tekst: str | None) -> bool:
    """Deterministische toets of een door de AI vóórgelezen kop-tekst een btw-verleggings-
    vermelding is (hint voor de controleur — nooit een invulling)."""
    if not tekst:
        return False
    genormaliseerd = tekst.lower()
    return "verleg" in genormaliseerd or "verlegd" in genormaliseerd or "reverse charge" in genormaliseerd


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
    # IBAN: deterministische mod-97-validatie (app/extractie/iban.py) — een ongeldig IBAN wordt
    # gemarkeerd (onparseerbaar) en nooit doorgegeven; de IBAN-wissel-check mag alleen op een
    # bewezen-geldig nummer draaien.
    iban_ruw = tekst_van("iban")
    iban = normaliseer_iban(iban_ruw) if is_geldig_iban(iban_ruw) else None
    if iban_ruw is not None and iban is None:
        onparseerbaar.append("iban")
    factuurdatum = datum_van("factuurdatum")
    vervaldatum = datum_van("vervaldatum")
    totaal_excl = bedrag_van("totaal_excl")
    totaal_incl = bedrag_van("totaal_incl")
    btw_bedrag = bedrag_van("btw_bedrag")
    # "Btw verlegd"-vermelding (punt 3, 26-08): de AI leest de letterlijke tekst voor, code
    # toetst of het een verleggings-vermelding is. Uitsluitend een HINT voor de controleur —
    # 0% blijft ambigu en wordt nooit vanuit deze vermelding ingevuld.
    verlegd_ruw = tekst_van("btw_verlegd_vermelding")
    btw_verlegd_vermelding = verlegd_ruw if is_verlegd_vermelding(verlegd_ruw) else None

    # Btw-/KvK-nummer van de leverancier (punt 14): deterministisch genormaliseerd + getoetst; een
    # herkenbaar foute vorm wordt niet overgenomen (liever leeg dan een gok). De ruwe tekst blijft
    # zichtbaar via `ruw`-velden hieronder.
    btw_gelezen = valideer_btw_nummer(tekst_van("btw_nummer"))
    btw_nummer = btw_gelezen.genormaliseerd if btw_gelezen else None
    kvk_nummer = normaliseer_kvk_nummer(tekst_van("kvk_nummer"))
    if tekst_van("btw_nummer") and btw_gelezen is None:
        onparseerbaar.append("btw_nummer")
    if tekst_van("kvk_nummer") and kvk_nummer is None:
        onparseerbaar.append("kvk_nummer")

    vendor_id, vendor_match = match_vendor(leverancier_naam, vendors, btw_nummer=btw_nummer, kvk_nummer=kvk_nummer)

    regels: list[dict] = []
    regel_zekerheid: list[float] = []
    netto_som = Decimal(0)
    btw_som = Decimal(0)
    regelsom_compleet = True
    btw_per_regel_compleet = True
    for index, regel in enumerate(extractie.regels, start=1):
        netto = parse_bedrag(regel.netto_bedrag)
        btw = parse_bedrag(regel.btw_bedrag)
        if regel.netto_bedrag is not None and netto is None:
            onparseerbaar.append(f"netto_bedrag (regel {index})")
        if regel.btw_bedrag is not None and btw is None:
            onparseerbaar.append(f"btw_bedrag (regel {index})")
        if netto is None:
            regelsom_compleet = False
        if btw is None:
            btw_per_regel_compleet = False
        netto_som += netto or Decimal(0)
        btw_som += btw or Decimal(0)
        afleiding = leid_btw_af(netto, btw, taxrates)
        regels.append(
            {
                "omschrijving": regel.omschrijving,
                "netto_bedrag": _bedrag_str(netto),
                "btw_bedrag": _bedrag_str(btw),
                "hoeveelheid": regel.hoeveelheid,
                # Blok D 28-08 (voorraad-aansluiting): eenheid + stuksprijs zoals vermeld — ruw.
                "eenheid": regel.eenheid,
                "stuksprijs": regel.stuksprijs,
                # Voorraad-normalisatie v2 (30-08): leverancierscode als deterministische sleutel.
                "artikelcode": regel.artikelcode,
                "taxrate_id": str(afleiding.taxrate_id) if afleiding.taxrate_id else None,
                # Herkomst van de btw-code (punt 3, 26-08): "factuur" = deterministisch uit
                # netto/btw afgeleid; None = leeg gelaten (0/onbepaalbaar/meerduidig — reden erbij).
                "btw_bron": afleiding.bron,
                "btw_afleiding_reden": afleiding.reden,
            }
        )
        regel_zekerheid.append(regel.zekerheid)
        if regel.zekerheid < zekerheid_drempel:
            lage_zekerheid.append(f"regel {index}")

    # Regelsom-toets (C3 26-08, casus AddGuests 1.328,14 + 278,91 = 1.607,05): EXACT dezelfde
    # netto+btw=incl-logica als de boekingsregels-toets onderin het controlescherm. Een scan
    # zonder btw per regel telde eerder alleen netto op en riep vals "wijkt af" tegen het
    # incl-totaal. Nu: (1) btw per regel bekend → Σnetto+Σbtw vs incl; (2) anders Σnetto vs het
    # excl-totaal; (3) anders Σnetto + factuur-btw vs incl; (4) niets te toetsen → geen badge.
    regelsom: Decimal | None = None
    regelsom_basis: str | None = None
    regelsom_wijkt_af: bool | None = None
    if regels and regelsom_compleet:
        if btw_per_regel_compleet and totaal_incl is not None:
            regelsom, regelsom_basis, vergelijk = netto_som + btw_som, "incl", totaal_incl
        elif totaal_excl is not None:
            regelsom, regelsom_basis, vergelijk = netto_som, "excl", totaal_excl
        elif btw_bedrag is not None and totaal_incl is not None:
            regelsom, regelsom_basis, vergelijk = netto_som + btw_bedrag, "incl", totaal_incl
        else:
            vergelijk = None
        if regelsom is not None and vergelijk is not None:
            regelsom_wijkt_af = abs(regelsom - vergelijk) > _ROND_TOLERANTIE

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
        "btw_verlegd_vermelding": btw_verlegd_vermelding,
        "iban": iban,
        # Punt 14 (28-08): nummers van de leverancier — herkomst-chip op het controlescherm, opslag per
        # crediteur bij het opslaan van het boekvoorstel (documenten/crediteur_kenmerk.py).
        "btw_nummer": btw_nummer,
        "btw_nummer_geverifieerd": btw_gelezen.geverifieerd if btw_gelezen else None,
        "kvk_nummer": kvk_nummer,
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
            "regelsom": _bedrag_str(regelsom) if regelsom is not None else None,
            "regelsom_basis": regelsom_basis,
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
