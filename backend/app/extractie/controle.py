from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.documenten.regelsom import REDEN_GEEN_REGELS, toets_regelsom
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
    schoon = waarde.strip().replace("€", "").replace(" ", "").replace(" ", "")
    # Kortings-/creditregels (bugfix 04-09, Huvanco "Korting 10% −56,44"): Unicode-minteken (U+2212)
    # en en-dash (U+2013) → gewoon minteken; achtergeplaatst minteken ("56,44-", NL-boekhoudnotatie)
    # → voorgeplaatst. Deterministisch, geen gok: één minteken, anders valt Decimal() hieronder uit.
    schoon = schoon.replace("−", "-").replace("–", "-")
    if schoon.endswith("-") and not schoon.startswith("-"):
        schoon = "-" + schoon[:-1]
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


@dataclass(frozen=True)
class VendorWaarschuwing:
    """Naam-match die bewust NIET is voorgesteld (controlescherm v2 ⑥, casus Hello Kitchen Son ↔
    Duiven): de dichtstbijzijnde naam-kandidaat draagt een ánder KvK-/btw-nummer dan de factuur —
    waarschijnlijk een andere vestiging/entiteit. De mens ziet de waarschuwing en kiest of maakt."""

    vendor_id: uuid.UUID
    naam: str
    reden: str  # 'kvk_afwijkend' | 'btw_afwijkend'
    factuur_nummer: str
    kandidaat_nummer: str

    def als_dict(self) -> dict:
        return {
            "vendor_id": str(self.vendor_id),
            "naam": self.naam,
            "reden": self.reden,
            "factuur_nummer": self.factuur_nummer,
            "kandidaat_nummer": self.kandidaat_nummer,
        }


def _kenmerk_conflict(
    kandidaat: VendorKandidaat, *, btw_nummer: str | None, kvk_nummer: str | None
) -> tuple[str, str, str] | None:
    """(reden, factuur_nummer, kandidaat_nummer) als de kandidaat een bekend nummer draagt dat
    afwijkt van dat op de factuur; None als er niets te vergelijken valt of het klopt."""
    if kvk_nummer and kandidaat.kvk_nummer and kandidaat.kvk_nummer != kvk_nummer:
        return "kvk_afwijkend", kvk_nummer, kandidaat.kvk_nummer
    if btw_nummer and kandidaat.btw_nummer and kandidaat.btw_nummer != btw_nummer:
        return "btw_afwijkend", btw_nummer, kandidaat.btw_nummer
    return None


def match_vendor(
    leverancier_naam: str | None,
    kandidaten: list[VendorKandidaat],
    *,
    btw_nummer: str | None = None,
    kvk_nummer: str | None = None,
) -> tuple[uuid.UUID | None, str | None]:
    """Compat-vorm: alleen (vendor_id, match) — zie `match_vendor_met_waarschuwing`."""
    vendor_id, match, _ = match_vendor_met_waarschuwing(
        leverancier_naam, kandidaten, btw_nummer=btw_nummer, kvk_nummer=kvk_nummer
    )
    return vendor_id, match


def match_vendor_met_waarschuwing(
    leverancier_naam: str | None,
    kandidaten: list[VendorKandidaat],
    *,
    btw_nummer: str | None = None,
    kvk_nummer: str | None = None,
) -> tuple[uuid.UUID | None, str | None, VendorWaarschuwing | None]:
    """Crediteur-suggestie uit de vendor-cache: (vendor_id, "btw_nummer"|"kvk_nummer"|"exact"|"fuzzy")
    of (None, None). Voorstel, geen automatische keuze — bij meerdere plausibele kandidaten géén
    suggestie (consistent met "nooit auto-toewijzen bij twijfel").

    Volgorde (punt 14, besluit Peter 27-08): éérst het btw-nummer van de factuur tegen de bekende
    nummers per crediteur, dan het KvK-nummer, dan pas de naam — exact, dan fuzzy (genormaliseerde
    naam zonder rechtsvorm/leestekens exact óf SequenceMatcher ≥ 0.85 met een uniek beste resultaat).
    Een nummer dat bij méér dan één crediteur hoort (dubbele crediteur in RLZ) geeft géén
    nummer-suggestie en valt terug op de naam — de dubbel-signalering op Instellingen toont 'm.

    KvK-/btw-mismatch-guard (controlescherm v2 ⑥, 02-09): een naam-match (exact óf fuzzy) waarvan
    het bekende KvK-/btw-nummer afwijkt van dat op de factuur wordt NOOIT stil voorgesteld — die
    komt terug als `VendorWaarschuwing` (derde element), zodat de mens 'm ziet en zelf kiest of
    een nieuwe crediteur aanmaakt (casus Hello Kitchen Son ↔ Duiven)."""
    if btw_nummer:
        op_btw = [k for k in kandidaten if k.btw_nummer and k.btw_nummer == btw_nummer]
        if len(op_btw) == 1:
            return op_btw[0].id, "btw_nummer", None
    if kvk_nummer:
        op_kvk = [k for k in kandidaten if k.kvk_nummer and k.kvk_nummer == kvk_nummer]
        if len(op_kvk) == 1:
            return op_kvk[0].id, "kvk_nummer", None
    if not leverancier_naam:
        return None, None, None
    doel = _genormaliseerd(leverancier_naam)
    if not doel:
        return None, None, None

    def met_guard(kandidaat: VendorKandidaat, match: str) -> tuple[uuid.UUID | None, str | None, VendorWaarschuwing | None]:
        conflict = _kenmerk_conflict(kandidaat, btw_nummer=btw_nummer, kvk_nummer=kvk_nummer)
        if conflict is None:
            return kandidaat.id, match, None
        reden, factuur, bekend = conflict
        return None, None, VendorWaarschuwing(
            vendor_id=kandidaat.id, naam=kandidaat.naam, reden=reden, factuur_nummer=factuur, kandidaat_nummer=bekend
        )

    exact = [k for k in kandidaten if k.naam and k.naam.strip().lower() == leverancier_naam.strip().lower()]
    if len(exact) == 1:
        return met_guard(exact[0], "exact")
    if len(exact) > 1:
        return None, None, None

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
        return None, None, None
    scores.sort(key=lambda item: item[0], reverse=True)
    beste_score = scores[0][0]
    besten = [kandidaat for score, kandidaat in scores if beste_score - score < 0.02]
    if len(besten) != 1:
        return None, None, None
    return met_guard(besten[0], "fuzzy")


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
    betalingskenmerk = tekst_van("betalingskenmerk")
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

    vendor_id, vendor_match, vendor_waarschuwing = match_vendor_met_waarschuwing(
        leverancier_naam, vendors, btw_nummer=btw_nummer, kvk_nummer=kvk_nummer
    )

    regels: list[dict] = []
    regel_zekerheid: list[float] = []
    # Geparste bedragen per regel (None = niet gelezen/onparseerbaar) — voeding voor de gedeelde
    # regelsom-beslisboom hieronder. Kortings-/creditregels zijn gewoon negatieve bedragen.
    netto_per_regel: list[Decimal | None] = []
    btw_per_regel: list[Decimal | None] = []
    for index, regel in enumerate(extractie.regels, start=1):
        netto = parse_bedrag(regel.netto_bedrag)
        btw = parse_bedrag(regel.btw_bedrag)
        if regel.netto_bedrag is not None and netto is None:
            onparseerbaar.append(f"netto_bedrag (regel {index})")
        if regel.btw_bedrag is not None and btw is None:
            onparseerbaar.append(f"btw_bedrag (regel {index})")
        netto_per_regel.append(netto)
        btw_per_regel.append(btw)
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
    # Sinds 04-09 (Huvanco-bugfix) ÉÉN gedeelde beslisboom met de harde check "Regeltelling vs
    # totaal" (app/documenten/regelsom.py) — twee bomen liepen uit de pas. Kortings-/creditregels
    # tellen als negatieve regel gewoon mee in netto_som/btw_som.
    toets = toets_regelsom(
        netto=netto_per_regel,
        btw=btw_per_regel,
        totaal_incl=totaal_incl,
        totaal_excl=totaal_excl,
        factuur_btw=btw_bedrag,
        tolerantie=_ROND_TOLERANTIE,
    )
    regelsom = toets.regelsom
    regelsom_basis = toets.basis
    regelsom_wijkt_af = toets.wijkt_af
    # Reden waarom er níét getoetst is (bv. btw per regel ontbreekt + alleen incl gelezen) — zichtbaar
    # i.p.v. stil geen badge; None zolang er wél getoetst is of er simpelweg geen regels zijn.
    regelsom_reden = toets.reden if toets.reden != REDEN_GEEN_REGELS else None

    return {
        "bron": "ai",
        "leverancier_naam": leverancier_naam,
        "factuurnummer": factuurnummer,
        "factuurdatum": factuurdatum.isoformat() if factuurdatum else None,
        "vervaldatum": vervaldatum.isoformat() if vervaldatum else None,
        # Betalingskenmerk (fase 1 Odoo): alleen doorgeven, nooit afleiden; Odoo `payment_reference`.
        "betalingskenmerk": betalingskenmerk,
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
        # KvK-/btw-mismatch-guard (v2 ⑥): de naam-match die bewust níét is voorgesteld.
        "vendor_waarschuwing": vendor_waarschuwing.als_dict() if vendor_waarschuwing is not None else None,
        "controle": {
            "regelsom": _bedrag_str(regelsom) if regelsom is not None else None,
            "regelsom_basis": regelsom_basis,
            "regelsom_wijkt_af": regelsom_wijkt_af,
            "regelsom_reden": regelsom_reden,
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
