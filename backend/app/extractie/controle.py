from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.documenten.regelsom import CENT_TOLERANTIE, REDEN_GEEN_REGELS, btw_uit_tarief, toets_regelsom
from app.documenten.veldvoorstel_regels import VLAG_TARIEFSTAFFEL, is_nulregel, parse_hoeveelheid
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

    def met_guard(kandidaat: VendorKandidaat, match: str) -> tuple[uuid.UUID | None, str | None, VendorWaarschuwing
        | None]:
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


def leid_btw_af(
    netto: Decimal | None,
    btw: Decimal | None,
    kandidaten: list[TaxRateKandidaat],
    *,
    tolerantie: Decimal = _ROND_TOLERANTIE,
) -> BtwAfleiding:
    """Btw-code deterministisch uit de regel afleiden (CODE, geen AI — feedbackronde 26-08 punt 3):
    netto × tarief ≈ btw-bedrag (tolerantie ±1 cent per regel) tegen de gesyncte TaxRates van de
    administratie (percentage = fractie, bv. 0.21 — zie app/sync/btw.py voor de eenheidsregel).

    HARD: bij 0/onbepaalbaar/meerduidig NOOIT invullen. 0% is ambigu (0%-tarief/vrijgesteld/
    verlegd — de bouwketen-norm is verlegd) en aangifte-kritisch; daar wint het boekingsgeheugen
    per leverancier, anders kiest de mens. Negatieve regels (creditnota) rekenen gewoon mee:
    −100 × 0,21 = −21.

    Meerdere tarieven met hetzélfde percentage (RLZ: "Hoog Tarief" én "Hoog Tarief (vooruit)"):
    precies één RLZ-favoriet → die; anders meerduidig = leeg. Twee verschillende percentages die
    beide binnen de tolerantie vallen (alleen bij centbedragen) = meerduidig = leeg.

    `tolerantie` (15-09, btw-uit-factuur-totaal): de factuur-niveau-afleiding rekent over de som van meerdere regels en
    krijgt één cent speling per regel mee — per regel blijft de default ±1 cent."""
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
        and abs(netto * kandidaat.percentage - btw) <= tolerantie
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


# ---- btw-percentage uit de btw-KOLOM van de regel (BUG 18-09, casus Zilver Horeca Fac-25-022711) ---------------------
#
# De factuur draagt per regel een btw-kolom "9%"/"0%" en géén btw-bedrag; `leid_btw_af` (netto × tarief ≈ btw) kan dan
# niets en het leverancier-geheugen (9 %) won ook op de acht Emballage-regels (statiegeld, 0 %). Een factuurkolom "0%"
# IS
# de basis (besluit Peter 18-09): dat is géén ambigu 0 %-zonder-context — de leverancier zégt 0 %. Code parst het
# percentage, matcht het exact op de gesyncte tarieven (verlegd/vrijgesteld/gemengd doen niet mee) en rekent het
# regel-btw-
# bedrag uit (netto × p) zodat bruto, regelsom en boekingsregel de FACTUUR volgen, nooit het geheugen-tarief.

BTW_BRON_FACTUUR_REGEL = "factuur_regel"
_KOLOM_PERCENTAGE = re.compile(r"^\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*$")


def parse_btw_kolom_percentage(tekst: str | None) -> Decimal | None:
    """"9%", "0 %", "21,0%" → fractie (0.09, 0, 0.21). Zonder procentteken (kolomcode "V", "vrij", "1") → None: een kaal
    cijfer kan een RLZ-code zijn — nooit als percentage lezen."""
    if not tekst:
        return None
    m = _KOLOM_PERCENTAGE.match(tekst)
    if m is None:
        return None
    try:
        pct = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if pct > 100:
        return None
    return (pct / 100).quantize(Decimal("0.0001"))


def leid_btw_af_uit_kolom(percentage: Decimal, kandidaten: list[TaxRateKandidaat]) -> BtwAfleiding:
    """Het tarief dat exact het kolom-percentage draagt (fractie-gelijkheid, bv. 0.09 ↔ 0.0900). Verlegd/vrijgesteld/
    gemengd doen niet mee — een kolom "0%" is het 0 %-tarief ("NL, Nul tarief"), nooit verlegd of vrijgesteld raden.
    Meerdere tarieven met dat percentage: precies één RLZ-favoriet → die; anders meerduidig = leeg (de mens kiest)."""
    passend = [
        k
        for k in kandidaten
        if k.percentage is not None
        and not (k.is_verlegd or k.is_vrijgesteld or k.is_gemengd)
        and k.percentage.quantize(Decimal("0.0001")) == percentage.quantize(Decimal("0.0001"))
    ]
    if not passend:
        return BtwAfleiding(taxrate_id=None, percentage=percentage, bron=None, reden="geen_match")
    if len(passend) == 1:
        return BtwAfleiding(taxrate_id=passend[0].id, percentage=percentage, bron=BTW_BRON_FACTUUR_REGEL)
    favorieten = [k for k in passend if k.is_favoriet]
    if len(favorieten) == 1:
        return BtwAfleiding(taxrate_id=favorieten[0].id, percentage=percentage, bron=BTW_BRON_FACTUUR_REGEL)
    return BtwAfleiding(taxrate_id=None, percentage=percentage, bron=None, reden="meerduidig")


# ---- totaal uit de pinbon (BUG 18-09, regel 4) ----------------------------------------------------------------

PINBON_GROEN = "groen"
PINBON_AFWIJKEND = "afwijkend"
PINBON_NIET_TOETSBAAR = "niet_toetsbaar"


@dataclass(frozen=True)
class PinbonToets:
    """`status`: None (geen bon-totaal gelezen) | "groen" (bon-totaal = Σ(netto + btw) van álle regels binnen 5 ct → mag
    als factuurtotaal voorgesteld worden, chip "uit pinbon") | "afwijkend" (alle regels bekend, som sluit niet — oranje,
    de mens beslist) | "niet_toetsbaar" (regels zonder bedrag/btw — oranje, nooit stil overnemen)."""

    totaal: Decimal | None
    status: str | None
    som: Decimal | None = None
    verschil: Decimal | None = None

    @property
    def overnemen(self) -> bool:
        return self.status == PINBON_GROEN and self.totaal is not None


def toets_pinbon_totaal(
    *, netto: list[Decimal | None], btw: list[Decimal | None], totaal_pinbon: Decimal | None
) -> PinbonToets:
    if totaal_pinbon is None:
        return PinbonToets(totaal=None, status=None)
    if not netto or any(n is None for n in netto) or any(b is None for b in btw):
        return PinbonToets(totaal=totaal_pinbon, status=PINBON_NIET_TOETSBAAR)
    som = sum((n + b for n, b in zip(netto, btw, strict=True) if n is not None and b is not None), Decimal(0))
    verschil = abs(totaal_pinbon - som).quantize(Decimal("0.01"))
    return PinbonToets(
        totaal=totaal_pinbon,
        status=PINBON_GROEN if verschil <= CENT_TOLERANTIE else PINBON_AFWIJKEND,
        som=som,
        verschil=verschil,
    )


def match_taxrate(netto: Decimal | None, btw: Decimal | None, kandidaten: list[TaxRateKandidaat]) -> uuid.UUID | None:
    """Alleen het tarief-id uit `leid_btw_af` (compat-vorm voor bestaande aanroepers/tests)."""
    return leid_btw_af(netto, btw, kandidaten).taxrate_id


@dataclass(frozen=True)
class FactuurBtwAfleiding:
    """Uitkomst van `leid_btw_af_uit_totaal` (bugfix 15-09, casus L.H.G. Holding / patroon KPN-, telecom- en
    energiefacturen: regels excl. btw, één btw-totaal onderaan). `taxrate_id` None = niets ingevuld, `reden` zegt
    waarom; `regel_indexen` (0-gebaseerd) zijn de regels die het tarief kregen, `btw_per_regel` hun deterministisch
    berekende btw-bedragen (som = het restant van de factuur-btw, cent-exact)."""

    taxrate_id: uuid.UUID | None
    percentage: Decimal | None
    reden: str | None = None
    regel_indexen: tuple[int, ...] = ()
    btw_per_regel: tuple[Decimal, ...] = ()
    # Het bewijs: restant-netto × tarief ≈ restant-btw (leesbaar in tests/tijdlijn).
    rest_netto: Decimal | None = None
    rest_btw: Decimal | None = None


REDEN_TOTAAL_GEEN_KANDIDATEN = "geen_regels_zonder_btw"
REDEN_TOTAAL_NETTO_ONBEKEND = "netto_onbekend"
REDEN_TOTAAL_GEEN_FACTUUR_BTW = "geen_factuur_btw"
REDEN_TOTAAL_REGELSOM_SLUIT_NIET = "regelsom_sluit_niet"
REDEN_TOTAAL_REST_NEGATIEF = "rest_btw_tegengesteld"


def _rond_cent(bedrag: Decimal) -> Decimal:
    return bedrag.quantize(_ROND_TOLERANTIE, rounding=ROUND_HALF_UP)


def leid_btw_af_uit_totaal(
    *,
    netto: list[Decimal | None],
    btw: list[Decimal | None],
    totaal_excl: Decimal | None,
    totaal_incl: Decimal | None,
    factuur_btw: Decimal | None,
    kandidaten: list[TaxRateKandidaat],
) -> FactuurBtwAfleiding:
    """Tweede bewijs op FACTUURNIVEAU (bugfix 15-09; opdrachttekst: "bij één btw-percentage op de factuur geldt dat voor
    álle regels zonder eigen btw"): veel facturen (telecom, energie, abonnementen) zetten de regels excl. btw en één
    btw-totaal onderaan — per regel is de btw dan "onbepaalbaar" en bleef de code leeg, terwijl de factuur het
    percentage wél bewijst. Puur code, geen AI-keuze:

    1. kandidaten = regels mét netto (≠ 0) en ZONDER eigen btw-bedrag; regels mét eigen btw houden hun regel-afleiding;
    2. álle netto's moeten gelezen zijn en — als het excl-totaal er is — cent-exact op dat totaal sluiten (anders is er
       geen bewijs dat het percentage óók voor deze regels geldt);
    3. factuur-btw = gelezen btw-totaal, anders incl − excl; restant-btw = factuur-btw − Σ btw van de regels mét eigen
       btw; restant-netto = Σ netto van de kandidaten;
    4. `leid_btw_af(restant-netto, restant-btw)` mét één cent speling per kandidaat-regel (afronding per regel op de
       factuur) — 0/geen match/meerduidig blijft leeg (dezelfde harde regels als per regel; 0 % is ambigu);
    5. per kandidaat-regel btw = netto × tarief (half-up op de cent); het afrondingsrestant landt op de regel met het
       grootste |netto| zodat Σ regel-btw exact het restant is (de regelsom-toets sluit dan cent-exact).

    Zonder regels (`netto` leeg) is de uitkomst alleen de factuur-niveau-afleiding uit excl/btw — voeding voor de
    één-regel-terugval in documenten/boekvoorstel.py."""
    if len(netto) != len(btw):
        raise ValueError("netto en btw moeten per regel gepaard zijn (zelfde lengte)")
    if not netto:
        if totaal_excl is None:
            return FactuurBtwAfleiding(None, None, REDEN_TOTAAL_NETTO_ONBEKEND)
        f_btw = (
            factuur_btw if factuur_btw is not None else (totaal_incl - totaal_excl if totaal_incl is not None else None)
        )
        if f_btw is None:
            return FactuurBtwAfleiding(None, None, REDEN_TOTAAL_GEEN_FACTUUR_BTW)
        afleiding = leid_btw_af(totaal_excl, f_btw, kandidaten)
        return FactuurBtwAfleiding(
            afleiding.taxrate_id, afleiding.percentage, afleiding.reden, rest_netto=totaal_excl, rest_btw=f_btw
        )
    kandidaat_indexen = tuple(
        i for i, (n, b) in enumerate(zip(netto, btw, strict=True)) if b is None and n is not None and n != 0
    )
    if not kandidaat_indexen:
        return FactuurBtwAfleiding(None, None, REDEN_TOTAAL_GEEN_KANDIDATEN)
    if any(n is None for n in netto):
        return FactuurBtwAfleiding(None, None, REDEN_TOTAAL_NETTO_ONBEKEND, regel_indexen=kandidaat_indexen)
    netto_som = sum((n for n in netto if n is not None), Decimal(0))
    factuur_netto = totaal_excl if totaal_excl is not None else netto_som
    if totaal_excl is not None and abs(netto_som - totaal_excl) > _ROND_TOLERANTIE:
        return FactuurBtwAfleiding(None, None, REDEN_TOTAAL_REGELSOM_SLUIT_NIET, regel_indexen=kandidaat_indexen)
    f_btw = factuur_btw
    if f_btw is None and totaal_incl is not None:
        f_btw = totaal_incl - factuur_netto
    if f_btw is None:
        return FactuurBtwAfleiding(None, None, REDEN_TOTAAL_GEEN_FACTUUR_BTW, regel_indexen=kandidaat_indexen)
    bekende_btw = sum((b for b in btw if b is not None), Decimal(0))
    rest_btw = f_btw - bekende_btw
    rest_netto = sum((netto[i] for i in kandidaat_indexen), Decimal(0))  # type: ignore[misc]
    if rest_btw != 0 and rest_netto != 0 and (rest_btw > 0) != (rest_netto > 0):
        return FactuurBtwAfleiding(
            None,
            None,
            REDEN_TOTAAL_REST_NEGATIEF,
            regel_indexen=kandidaat_indexen,
            rest_netto=rest_netto,
            rest_btw=rest_btw,
        )
    afleiding = leid_btw_af(rest_netto, rest_btw, kandidaten, tolerantie=_ROND_TOLERANTIE * len(kandidaat_indexen))
    if afleiding.taxrate_id is None or afleiding.percentage is None:
        return FactuurBtwAfleiding(
            None, None, afleiding.reden, regel_indexen=kandidaat_indexen, rest_netto=rest_netto, rest_btw=rest_btw
        )
    per_regel = [_rond_cent(netto[i] * afleiding.percentage) for i in kandidaat_indexen]  # type: ignore[operator]
    restant = rest_btw - sum(per_regel, Decimal(0))
    if restant != 0:
        grootste = max(range(len(kandidaat_indexen)), key=lambda k: (abs(netto[kandidaat_indexen[k]]), -k))  # type: ignore[arg-type]
        per_regel[grootste] += restant
    return FactuurBtwAfleiding(
        afleiding.taxrate_id,
        afleiding.percentage,
        None,
        regel_indexen=kandidaat_indexen,
        btw_per_regel=tuple(per_regel),
        rest_netto=rest_netto,
        rest_btw=rest_btw,
    )


def is_verlegd_vermelding(tekst: str | None) -> bool:
    """Deterministische toets of een door de AI vóórgelezen kop-tekst een btw-verleggings-
    vermelding is (hint voor de controleur — nooit een invulling)."""
    if not tekst:
        return False
    genormaliseerd = tekst.lower()
    return "verleg" in genormaliseerd or "verlegd" in genormaliseerd or "reverse charge" in genormaliseerd


#: Btw-kolomcodes die op een Nederlandse factuur "verlegd" betekenen (Peter 15-09, casus Olieman: "V" in de BTW-kolom,
#: nergens het woord verlegd). Genormaliseerd: lowercase, alleen letters. Bewust smal — "0", "0%", "vrij", "nul" zijn
#: GÉÉN verlegd (0 % ≠ verlegd, de valkuil blijft bewaakt).
_VERLEGD_KOLOMCODES = frozenset({"v", "vl", "verl", "verlegd", "btwverlegd", "verlegging", "verleggingsregeling", "rc",
                                 "reversecharge"})
_ALLEEN_LETTERS = re.compile(r"[^a-z]+")


def is_verlegd_kolomcode(tekst: str | None) -> bool:
    """Deterministisch: is de btw-kolomtekst van een regel een verlegd-code ("V", "VL", "verl.", "BTW verlegd",
    "reverse charge")? Percentages en vrijgesteld-codes ("0%", "vrij") zijn dat nooit."""
    if not tekst:
        return False
    kern = _ALLEEN_LETTERS.sub("", tekst.lower())
    return kern in _VERLEGD_KOLOMCODES


def verlegd_kolomcode_voor_factuur(kolommen: list[str | None], *, netto: list[Decimal | None]) -> str | None:
    """Peter 15-09 (b): de factuur is op KOLOMCODE verlegd als élke regel mét een nettobedrag ≠ 0 een verlegd-kolomcode
    draagt (minstens één zo'n regel). → de gelezen code (bv. "V"), anders None. De aanroeper toetst zelf nog de
    factuur-btw 0 (boekvoorstel._factuur_is_verlegd)."""
    if len(kolommen) != len(netto):
        raise ValueError("kolommen en netto moeten per regel gepaard zijn")
    dragend = [(k, n) for k, n in zip(kolommen, netto, strict=True) if n is not None and n != 0]
    if not dragend:
        return None
    if all(is_verlegd_kolomcode(k) for k, _ in dragend):
        return next(k for k, _ in dragend if k).strip()
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
    betalingskenmerk = tekst_van("betalingskenmerk")
    # Betreft-/onderwerpregel (blok 9 vervolgrun 07-09): alleen doorgeven; de kop-omschrijving wordt in
    # documenten/kop_omschrijving.py deterministisch afgeleid (één regel → regeltekst, anders dit veld).
    betreft = tekst_van("betreft")
    # Projectnummer/werknummer van de opdrachtgever (blok 10 07-09): alleen doorgeven (ruw); de match tegen de
    # project-cache + het leverancier-werknummer-geheugen gebeurt deterministisch bij de prefill
    # (documenten/regel_prefill.py + app/projecten/match.py) — dan klopt oranje/groen met de actuele stand.
    project_tekst = tekst_van("project_tekst")
    # Factuurperiode (blok 11 07-09): alleen doorgeven (ruw); de normalisatie naar ISO-weken gebeurt deterministisch
    # bij de prefill (documenten/periode.py) — dan is de factuurdatum (jaar-anker) de opgeslagen stand.
    periode_tekst = tekst_van("periode")
    # Betaalwijze/incassodatum (blok 3 bundel 08-09): alleen doorgeven (ruw); óf het een incasso is beslist
    # app/documenten/betaalstatus.py deterministisch (documenten/service.py, samen met de PDF-tekstlaag).
    betaalwijze_tekst = tekst_van("betaalwijze_tekst")
    incasso_datum_tekst = tekst_van("incasso_datum_tekst")
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
        afleiding = leid_btw_af(netto, btw, taxrates)
        # BUG 18-09 (Zilver Horeca): btw-KOLOM "9%"/"0%" als basis zodra netto × tarief ≈ btw niets oplevert (geen
        # regel-btw gelezen). Het regel-btw-bedrag volgt dan deterministisch uit netto × kolom-percentage — de factuur
        # zegt het tarief, dus bruto/regelsom/boekingsregel volgen de factuur en nooit het geheugen-tarief.
        kolom_pct = parse_btw_kolom_percentage(regel.btw_kolom)
        btw_berekend = False
        afleiding_basis: str | None = "regel" if afleiding.taxrate_id else None
        if afleiding.taxrate_id is None and kolom_pct is not None:
            kolom_afleiding = leid_btw_af_uit_kolom(kolom_pct, taxrates)
            if kolom_afleiding.taxrate_id is not None:
                afleiding = kolom_afleiding
                afleiding_basis = "kolom"
                if btw is None and netto is not None:
                    btw = btw_uit_tarief(netto, kolom_pct)
                    btw_berekend = True
        netto_per_regel.append(netto)
        btw_per_regel.append(btw)
        # Blok 4 (08-09, Spot Services): tariefstaffel-regel (aantal 0/ontbrekend, netto 0, btw 0) — blijft als
        # BRON in `regels` (tariefkaart/self-billing), wordt géén boekingsregel (documenten/veldvoorstel_regels.py).
        tariefstaffel = is_nulregel(netto=netto, btw=btw, hoeveelheid=parse_hoeveelheid(regel.hoeveelheid))
        regels.append(
            {
                "omschrijving": regel.omschrijving,
                "netto_bedrag": _bedrag_str(netto),
                "btw_bedrag": _bedrag_str(btw),
                # BUG 18-09: regel-btw deterministisch uit netto × kolom-percentage (geen gelezen bedrag).
                "btw_bedrag_berekend": btw_berekend,
                # BUG 18-09: het kolom-percentage als fractie ("0.0900"); None zonder (parsbaar) percentage in de kolom.
                "btw_kolom_percentage": _bedrag_str(kolom_pct),
                # BUG 18-09 (regel 5): bedrag niet gelezen omdat het afgedekt/onleesbaar is — chip i.p.v. lege cel.
                "bedrag_niet_gelezen": bool(regel.niet_gelezen) and netto is None,
                "niet_gelezen_reden": regel.niet_gelezen if netto is None else None,
                "hoeveelheid": regel.hoeveelheid,
                VLAG_TARIEFSTAFFEL: tariefstaffel,
                # Blok D 28-08 (voorraad-aansluiting): eenheid + stuksprijs zoals vermeld — ruw.
                "eenheid": regel.eenheid,
                "stuksprijs": regel.stuksprijs,
                # Voorraad-normalisatie v2 (30-08): leverancierscode als deterministische sleutel.
                "artikelcode": regel.artikelcode,
                # Blok 10 07-09: project-/werknummer op de regel (ruw; regel wint van kop bij de prefill).
                "project_tekst": regel.project_tekst,
                # Peter 15-09: btw-kolomtekst zoals vermeld ("V") + de deterministische duiding.
                "btw_kolom": regel.btw_kolom,
                "btw_kolom_verlegd": is_verlegd_kolomcode(regel.btw_kolom),
                "taxrate_id": str(afleiding.taxrate_id) if afleiding.taxrate_id else None,
                # Herkomst van de btw-code (punt 3, 26-08): "factuur" = deterministisch uit
                # netto/btw afgeleid; None = leeg gelaten (0/onbepaalbaar/meerduidig — reden erbij).
                "btw_bron": afleiding.bron,
                "btw_afleiding_reden": afleiding.reden,
                # 15-09: waarop de btw-code steunt — "regel" (netto × tarief ≈ regel-btw), "kolom" (btw-kolom "9%"/"0%",
                # 18-09), "factuur_totaal" (hieronder) of None (leeg gelaten).
                "btw_afleiding_basis": afleiding_basis,
            }
        )
        regel_zekerheid.append(regel.zekerheid)
        if regel.zekerheid < zekerheid_drempel:
            lage_zekerheid.append(f"regel {index}")

    # Tweede bewijs op factuurniveau (bugfix 15-09, casus L.H.G. Holding "Kosten mobiele telefonie" / KPN-patroon):
    # regels zonder eigen btw-bedrag krijgen het ene percentage dat het btw-totaal van de factuur bewijst — code
    # rekent (leid_btw_af_uit_totaal), de AI leverde alleen bedragen. Vult óók de regel-btw-bedragen (som cent-exact =
    # factuur-btw) zodat de regelsom-toets hieronder op incl kan sluiten. Regels mét eigen btw houden hun uitkomst.
    factuur_afleiding = leid_btw_af_uit_totaal(
        netto=netto_per_regel,
        btw=btw_per_regel,
        totaal_excl=totaal_excl,
        totaal_incl=totaal_incl,
        factuur_btw=btw_bedrag,
        kandidaten=taxrates,
    )
    if factuur_afleiding.taxrate_id is not None and factuur_afleiding.regel_indexen:
        for index, regel_btw in zip(factuur_afleiding.regel_indexen, factuur_afleiding.btw_per_regel, strict=True):
            regels[index].update(
                {
                    "taxrate_id": str(factuur_afleiding.taxrate_id),
                    "btw_bron": "factuur",
                    "btw_afleiding_reden": None,
                    "btw_afleiding_basis": "factuur_totaal",
                    "btw_bedrag": _bedrag_str(regel_btw),
                    "btw_bedrag_berekend": True,
                }
            )
            btw_per_regel[index] = regel_btw

    # Totaal uit de pinbon (BUG 18-09, regel 4): de factuur zelf draagt geen totaal, de meegefotografeerde bon wél.
    # Code toetst: bon-totaal = Σ(netto + btw) van álle regels binnen 5 ct → groen en als factuurtotaal voorgesteld
    # (chip "uit pinbon"); anders oranje (afwijkend / regels niet volledig gelezen) — de mens beslist, nooit stil
    # overnemen.
    totaal_pinbon = bedrag_van("totaal_pinbon")
    pinbon = toets_pinbon_totaal(netto=netto_per_regel, btw=btw_per_regel, totaal_pinbon=totaal_pinbon)
    totaal_bron: str | None = "factuur" if totaal_incl is not None else None
    if totaal_incl is None and pinbon.overnemen:
        totaal_incl = pinbon.totaal
        totaal_bron = "pinbon"

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
        # 15-09: de factuur-niveau-afleiding (ook zonder regels — voeding voor de één-regel-terugval in
        # boekvoorstel.py).
        "btw_factuur_totaal": {
            "taxrate_id": str(factuur_afleiding.taxrate_id) if factuur_afleiding.taxrate_id else None,
            "percentage": _bedrag_str(factuur_afleiding.percentage),
            "reden": factuur_afleiding.reden,
            "regels": [i + 1 for i in factuur_afleiding.regel_indexen],
            "rest_netto": _bedrag_str(factuur_afleiding.rest_netto),
            "rest_btw": _bedrag_str(factuur_afleiding.rest_btw),
        },
        "leverancier_naam": leverancier_naam,
        "factuurnummer": factuurnummer,
        "factuurdatum": factuurdatum.isoformat() if factuurdatum else None,
        "vervaldatum": vervaldatum.isoformat() if vervaldatum else None,
        # Betalingskenmerk (fase 1 Odoo): alleen doorgeven, nooit afleiden; Odoo `payment_reference`.
        "betalingskenmerk": betalingskenmerk,
        "betreft": betreft,
        "project_tekst": project_tekst,
        "periode_tekst": periode_tekst,
        "betaalwijze_tekst": betaalwijze_tekst,
        "incasso_datum_tekst": incasso_datum_tekst,
        "valuta": valuta,
        "totaal_excl": _bedrag_str(totaal_excl),
        "totaal_incl": _bedrag_str(totaal_incl),
        # BUG 18-09 (regel 4): herkomst van het totaal ("factuur" | "pinbon" | None) + de bon-toets voor de chip.
        "totaal_bron": totaal_bron,
        "totaal_pinbon": _bedrag_str(pinbon.totaal),
        "totaal_pinbon_status": pinbon.status,
        "totaal_pinbon_som": _bedrag_str(pinbon.som),
        "totaal_pinbon_verschil": _bedrag_str(pinbon.verschil),
        "btw_bedrag": _bedrag_str(btw_bedrag),
        "btw_verlegd_vermelding": btw_verlegd_vermelding,
        # Peter 15-09 (b): álle regels mét bedrag dragen een verlegd-kolomcode ("V") → de code; boekvoorstel toetst
        # de factuur-btw 0 en zet dan het verlegd-tarief voor (oranje, `factuur_verlegd`).
        "btw_verlegd_kolom": verlegd_kolomcode_voor_factuur(
            [regel.btw_kolom for regel in extractie.regels], netto=netto_per_regel
        ),
        "iban": iban,
        # Punt 14 (28-08): nummers van de leverancier — herkomst-chip op het controlescherm, opslag per
        # crediteur bij het opslaan van het boekvoorstel (documenten/crediteur_kenmerk.py).
        "btw_nummer": btw_nummer,
        "btw_nummer_geverifieerd": btw_gelezen.geverifieerd if btw_gelezen else None,
        "kvk_nummer": kvk_nummer,
        "regelaantal": len(regels),
        # Aantal tariefstaffel-regels (aantal 0, bedrag 0) dat géén boekingsregel wordt — leesbaar in de tijdlijn.
        "tariefstaffel_aantal": sum(1 for r in regels if r[VLAG_TARIEFSTAFFEL]),
        "regels": regels,
        "zekerheid": zekerheid,
        "regel_zekerheid": regel_zekerheid,
        # De drempel reist mee zodat de frontend exact dezelfde grens markeert als de backend
        # hanteerde — geen tweede, hardcoded drempel die stil uit de pas kan lopen.
        "zekerheid_drempel": zekerheid_drempel,
        "vendor_suggestie": ({"vendor_id": str(vendor_id), "match": vendor_match} if vendor_id is not None else None),
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
