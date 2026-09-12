"""Deterministische afleiding pandenregister (bundel 10-09 blok D2; HERBOUWD run 2 VGG 12-09 blok 3) — pure functies,
geen AI, geen I/O.

Tekstbron: `BoekingsFeit.tekst` is de ONTKNIPTE samenvoeging van Reference/Description/Header (`app/rlz/tekst.py::
ontknip` — RLZ knipt bank-geïmporteerde omschrijvingen op 32 tekens met `\\n`); deze module normaliseert nooit zelf.

- `adressen_uit_tekst`: NL straat + huisnummer (+ toevoeging) + optioneel postcode/plaats. Twee herkenners: (1) vaste
  straat-suffixlijst (straat, laan, weg, …) zodat "keuring Kerkstraat 44" wél en "factuur 2026047" nooit een adres
  wordt;
  (2) ná een trigger ("aanbetaling", "overdracht", "vaste lasten", "betreft", "afspraak", ":") een gecapitaliseerd woord
  + nummer ("Merwede 43", "Wadden 66", "Knopkruid 45"). Vulwoorden vóór de straat (aanbetaling, overdracht, vaste
  lasten,
  volgens afspraak, maandnamen, …), plaatsnaam-restanten ("Rotterdam Tapuitstraat 52A") en postcode-restanten ("HL
  Arnhem
  Papaverstraat 44") vallen weg; een door RLZ-Reference + Description herhaalde straatnaam ("Burgemeester Norbrui
  Burgemeester Norbruislaan 422") wordt gevouwen. Meerdere adressen in één tekst = MEERDUIDIG → `adres_uit_tekst` None.
- `dossiernummers_uit_tekst`: ALLEEN het notarisformaat `JJJJ.NNNNNN.NN` is een sleutel; afgekapte vormen ("2025.079",
  "2026.0", "2025.079507") zijn ONVOLLEDIG (apart veld, nooit sleutel); "dossier(nummer): <nummer>" in een ander formaat
  is
  `overig` (informatie, nooit een pand); leveranciers-factuurnummers (`JJJJ-NNNN`, `F2026-0083`, `2026-021018`) nooit.
- `notaris_herkenning`: casus-notarissen (Ouwerkerk/Ouwekerk, Buma Algera) + generiek "notaris"/"notariaat".
- `classificeer`: soort `aankoop | verkoop | kosten | aanbetaling | vaste_lasten | balans` + zekerheid uit collectie,
  boekstukreeks, teken van het bedrag, notaris, adres, dossier en bijlage. Regels (besluiten Peter 12-09):
  * 31-12-memoriaal mét adres = `balans` (jaareinde), NOOIT aankoop/aankoopdatum;
  * "aanbetaling" (alle varianten) = `aanbetaling` (vooruitbetaald op voorraad), "vaste lasten"/"vastelasten" =
    `vaste_lasten` (W&V), ongeacht collectie;
  * verkoop-woorden (verkoopsaldo, belasting verkoop, hypotheekgelden, doorstorten saldo, "verkoop") = `verkoop`;
  * bank-directe boeking (Receipts, PaymentTransactions, bankdagboek-reeks) van/aan een notaris of met "overdracht"/
    "afrekening": TEKEN beslist — positief = `verkoop`, negatief = `aankoop`;
  * memoriaal RLZ-06 mét adres = `aankoop` (hoog mét notaris-PDF/dossier); verkoopfactuur op notaris = `verkoop` hoog;
    inkoopfactuur mét adres = `kosten`; "rente"/"huur" op een verkoopfactuur = `kosten` (opbrengst per pand, geen
    verkoop).
  Zekerheid: hoog = adres + tweede signaal (notaris/dossier/bijlage/plaats), midden = alleen adres, laag = alleen
  dossier.
AI-extractie uit de PDF komt hier bewust NIET voor."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

STRAAT_SUFFIXEN: tuple[str, ...] = (
    "straat",
    "laan",
    "weg",
    "plein",
    "kade",
    "dijk",
    "singel",
    "gracht",
    "hof",
    "pad",
    "steeg",
    "dreef",
    "baan",
    "markt",
    "park",
    "erf",
    "lei",
    "allee",
    "boulevard",
    "ring",
    "hoek",
    "wal",
    "plantsoen",
    "weide",
    "akker",
    "kamp",
    "tuin",
    "gaarde",
    "gaard",
    "oord",
    "veld",
    "dam",
    "haven",
    "burg",
    "berg",
    "veer",
    "sloot",
    "ven",
    "horst",
    "kolk",
    "wijk",
    "donk",
    "hout",
    "land",
    "huis",
    "kruid",
    "vecht",
    "hoven",
    "polder",
    "beemd",
    "egge",
    "wede",
    "brink",
    "hoeve",
    "werf",
    "poort",
    "bos",
    "meer",
    "zicht",
    "stede",
)
#: Vulwoorden vóór de straatnaam die geen deel van de naam zijn ("Aanbetaling volgens afspraak: Kerkstraat 44").
_STOPWOORDEN: frozenset[str] = frozenset(
    {
        "betreft",
        "inzake",
        "pand",
        "object",
        "adres",
        "woning",
        "aankoop",
        "verkoop",
        "levering",
        "dossier",
        "dossiernummer",
        "dossiernr",
        "nota",
        "factuur",
        "ref",
        "re",
        "afrekening",
        "koop",
        "huur",
        "kosten",
        "keuring",
        "taxatie",
        "project",
        "onroerende",
        "zaak",
        "appartement",
        "perceel",
        "het",
        "de",
        "van",
        "te",
        "aan",
        "op",
        "voor",
        "bij",
        "en",
        "the",
        # run 2 VGG (12-09): omschrijvingsvormen uit de nameting 11-09
        "aanbetaling",
        "extra",
        "maandelijkse",
        "maandelijks",
        "overdracht",
        "terugbetaling",
        "vaste",
        "lasten",
        "vastelasten",
        "verhuizing",
        "volgens",
        "afspraak",
        "afspraal",  # tikfout in de brondata ("volgens afspraal")
        "ons",
        "dubbel",
        "retour",
        "verkoopsaldo",
        "doorstorten",
        "saldo",
        "commissie",
        "hypotheekgelden",
        "belasting",
        "laatste",
        "maand",
        "t/m",
        "tm",
        "euro",
        "rente",
        "vve",
        "2/2",
        "1/2",
        "januari",
        "februari",
        "maart",
        "april",
        "mei",
        "juni",
        "juli",
        "augustus",
        "september",
        "oktober",
        "november",
        "december",
        "mrt",
        "sept",
        "okt",
    }
)
#: Woorden ná het huisnummer die nooit een plaats zijn ("Fazantstraat 79a Rotterdam Vve kosten", "… Dordrecht Rente").
_GEEN_PLAATS_WOORDEN: frozenset[str] = _STOPWOORDEN | frozenset({"bv", "b.v.", "nv", "cv", "r"})
#: Plaatsnamen — guard tegen plaatsnaam-restanten vóór de straat ("Rotterdam Tapuitstraat 52A") en tegen een plaats
#: als straat ("Amsterdam 7R"); tevens acceptatie van een plaats ná het nummer zonder komma/te. Deterministische lijst
#: (casus-plaatsen uit de nameting 11-09 + grotere NL-gemeenten), géén woordenboek voor straatnamen.
PLAATSNAMEN: frozenset[str] = frozenset(
    p.lower()
    for p in (
        "Kollum",
        "Utrecht",
        "Amsterdam",
        "Rotterdam",
        "Tilburg",
        "Kerkrade",
        "Almere",
        "Den Haag",
        "'s-Gravenhage",
        "Hulst",
        "Zeist",
        "Heerlen",
        "Hoensbroek",
        "Arnhem",
        "Goes",
        "Roermond",
        "Venray",
        "Leusden",
        "Purmerend",
        "Den Helder",
        "Zevenaar",
        "Amersfoort",
        "Breda",
        "Brunssum",
        "Ede",
        "Dordrecht",
        "Leiden",
        "Berlicum",
        "Bergen op Zoom",
        "Weert",
        "Olst",
        "Zwijndrecht",
        "IJmuiden",
        "Lelystad",
        "Leeuwarden",
        "Zoetermeer",
        "Heerhugowaard",
        "de Meern",
        "De Meern",
        "Groningen",
        "Eindhoven",
        "Nijmegen",
        "Haarlem",
        "Enschede",
        "Apeldoorn",
        "Zwolle",
        "Maastricht",
        "Delft",
        "Deventer",
        "Alkmaar",
        "Venlo",
        "Sittard",
        "Geleen",
        "Emmen",
        "Assen",
        "Hilversum",
        "Amstelveen",
        "Gouda",
        "Schiedam",
        "Vlaardingen",
        "Spijkenisse",
        "Nieuwegein",
        "Veenendaal",
        "Oss",
        "Helmond",
        "Roosendaal",
        "Middelburg",
        "Vlissingen",
        "Terneuzen",
        "Hengelo",
        "Almelo",
        "Alphen aan den Rijn",
        "Leidschendam",
        "Voorburg",
        "Rijswijk",
        "Zaandam",
        "Hoorn",
        "Heerenveen",
        "Drachten",
        "Sneek",
        "Meppel",
        "Hoogeveen",
        "Doetinchem",
        "Tiel",
        "Culemborg",
        "Woerden",
        "Houten",
        "IJsselstein",
        "Harderwijk",
        "Barneveld",
        "Wageningen",
        "Soest",
        "Baarn",
        "Bussum",
        "Huizen",
        "Weesp",
        "Diemen",
        "Hoofddorp",
        "Uithoorn",
        "Aalsmeer",
        "Castricum",
        "Heemskerk",
        "Beverwijk",
        "Heiloo",
        "Schagen",
        "Landgraaf",
        "Voerendaal",
        "Simpelveld",
        "Valkenburg",
        "Meerssen",
        "Echt",
        "Susteren",
        "Nederweert",
        "Tegelen",
        "Panningen",
        "Gennep",
        "Boxmeer",
        "Cuijk",
        "Uden",
        "Veghel",
        "Schijndel",
        "Boxtel",
        "Oirschot",
        "Veldhoven",
        "Valkenswaard",
        "Geldrop",
        "Nuenen",
        "Capelle aan den IJssel",
        "Krimpen aan den IJssel",
        "Ridderkerk",
        "Barendrecht",
        "Papendrecht",
        "Sliedrecht",
        "Gorinchem",
        "Oosterhout",
        "Waalwijk",
        "Etten-Leur",
        "Bergen",
        "Katwijk",
        "Noordwijk",
        "Lisse",
        "Voorschoten",
        "Wassenaar",
        "Zoeterwoude",
        "Leiderdorp",
        "Maassluis",
        "Hellevoetsluis",
        "Brielle",
        "Vianen",
        "Bunnik",
        "Bilthoven",
        "Maarssen",
        "Breukelen",
    )
)
_GEEN_TOEVOEGING: frozenset[str] = frozenset({"te", "en", "of", "in", "op", "bv", "nv", "cv", "ex", "no", "nr"})
_PARTIKELS: frozenset[str] = frozenset({"van", "de", "den", "der", "het", "'t", "ten", "ter"})

_SUFFIX_ALT = "|".join(sorted(STRAAT_SUFFIXEN, key=len, reverse=True))
_PREFIX_WOORD = r"(?:[A-Z][A-Za-z'’.-]*|\d{1,2}e|van|der|de|den|het|'t|op|aan|ten|ter)"
_TOEVOEGING_RE = r"(?P<toevoeging>-\s?\d{1,3}|(?<=\d)[A-Za-z]{1,2}|\s(?:[A-Za-z]|bis|hs))?(?![\w'’])"
_REST_RE = (
    r"(?P<rest>(?:\s*,\s*(?:te\s+)?|\s+te\s+|\s+)(?:(?P<postcode>\d{4}\s?[A-Z]{2})\s*,?\s*)?"
    r"(?P<plaats>(?:(?:de|den|het|'t)\s)?[A-Z'][a-zA-Z'’-]+"
    r"(?:\s(?:[A-Z][a-zA-Z'’-]+|aan|den|de|op|en|het|'t|bij|van|der)){0,3})?)?"
)
_ADRES = re.compile(
    rf"(?<![\w'’-])(?P<straat>(?:{_PREFIX_WOORD}\s+){{0,3}}[A-Za-z][A-Za-z'’-]*(?:{_SUFFIX_ALT}))"
    rf"\s*(?P<nummer>\d{{1,5}}){_TOEVOEGING_RE}{_REST_RE}",
    re.UNICODE,
)
#: Adres zonder straat-suffix, direct ná een trigger: "Aanbetaling Heidebeemd 3 Weert", "afspraak Merwede 43".
_TRIGGER = (
    r"(?i:aanbetaling|overdracht|afrekening|vaste\s+lasten|vastelasten|afspraak|afspraal|betreft|inzake|verkoop|:)"
)
_ADRES_NA_TRIGGER = re.compile(
    rf"{_TRIGGER}\s*(?P<straat>(?:[A-Z][A-Za-z'’-]*\s+){{0,2}}[A-Z][A-Za-z'’-]{{2,}})"
    rf"\s+(?P<nummer>\d{{1,5}}){_TOEVOEGING_RE}{_REST_RE}",
    re.UNICODE,
)
_POSTCODE_RESTANT = re.compile(r"^[A-Z]{2}$")

_DOSSIER_NOTARIS = re.compile(r"(?<![\d.])(20\d{2}\.\d{6}\.\d{2})(?![\d.])")
_DOSSIER_ONVOLLEDIG = re.compile(r"(?<![\d.])(20\d{2}\.\d{1,6}(?:\.\d{1,2})?)(?![\d.])")
_DOSSIER_EXPLICIET = re.compile(r"\bdossier(?:nr|nummer|no)?\.?\s*[:#]?\s*([A-Za-z]?\d[\w./-]{2,})", re.IGNORECASE)
_DOSSIERWOORD = re.compile(r"\bdossier", re.IGNORECASE)
_FACTUURNUMMER = re.compile(r"^[A-Za-z]?20\d{2}-\d{3,6}$")
_DATUM_ACHTIG = re.compile(r"^20\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01])$")

BEKENDE_NOTARISSEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ouwerkerk", ("ouwerkerk", "ouwekerk")),
    ("Buma Algera", ("buma algera", "buma-algera", "bumaalgera")),
)
_GENERIEK_NOTARIS = re.compile(r"notari(?:s|ssen|aat|eel)", re.IGNORECASE)

MEMORIAAL_REEKS = "RLZ-06"
VERKOOP_REEKS = "RLZ-01"
BANK_COLLECTIES: frozenset[str] = frozenset({"Receipts", "PaymentTransactions"})
DOCUMENT_COLLECTIES: frozenset[str] = (
    frozenset({"ManualJournals", "SalesInvoices", "PurchaseInvoices"}) | BANK_COLLECTIES
)

SOORTEN: tuple[str, ...] = ("aankoop", "verkoop", "kosten", "aanbetaling", "vaste_lasten", "balans")

_SIG_AANBETALING = re.compile(r"aanbetaling", re.IGNORECASE)
_SIG_VASTE_LASTEN = re.compile(r"vaste[\s-]*lasten", re.IGNORECASE)
_SIG_VERKOOP = re.compile(
    r"verkoopsaldo|belasting\s+verkoop|hypotheekgeld|doorstorten\s+saldo|\bverkoop\b|\bverkocht\b", re.IGNORECASE
)
_SIG_OVERDRACHT = re.compile(r"\boverdracht|\bafrekening|\bnotaris|\blevering\b", re.IGNORECASE)
_SIG_RENTE = re.compile(r"\brente\b|\bhuur\b|\bhuurpenningen\b", re.IGNORECASE)


@dataclass(frozen=True)
class AdresVoorstel:
    straat: str
    huisnummer: str
    toevoeging: str | None = None
    postcode: str | None = None
    plaats: str | None = None

    @property
    def code(self) -> str:
        """Genormaliseerde pand-sleutel: diacritics weg, kleine letters, alleen letters/cijfers, '-' tussen delen.
        "Goeverneurlaan 310, Den Haag" → "goeverneurlaan-310"; plaats hoort er niet bij (één adres = één pand)."""
        delen = [_norm(self.straat), self.huisnummer]
        if self.toevoeging:
            delen.append(_norm(self.toevoeging))
        return "-".join(d for d in delen if d)

    @property
    def weergave(self) -> str:
        adres = f"{self.straat} {self.huisnummer}"
        if self.toevoeging:
            los = self.toevoeging.lower() in {"bis", "hs"}
            adres += f" {self.toevoeging}" if los else self.toevoeging
        return f"{adres}, {self.plaats}" if self.plaats else adres

    @property
    def weergave_kort(self) -> str:
        return self.weergave.split(",")[0]


@dataclass(frozen=True)
class NotarisHerkenning:
    naam: str  # genormaliseerde weergavenaam ("Ouwerkerk", "Buma Algera") of de relatienaam bij generiek
    bekend: bool  # True = één van de casus-notarissen


@dataclass(frozen=True)
class BoekingsFeit:
    """Wat de afleiding van één RLZ-document of bankmutatie nodig heeft — platgeslagen door de service."""

    collectie: str  # PurchaseInvoices | SalesInvoices | ManualJournals | Receipts | PaymentTransactions
    boekstuk: str | None
    entity_naam: str | None  # Entity.Name (documenten) / Name = tegenpartij (PaymentTransactions)
    tekst: str  # ontknipte referentie + omschrijving + header, spatie-gescheiden
    heeft_bijlage: bool | None = None  # None = niet gecontroleerd
    dagboek: str | None = None
    bedrag: Decimal | None = None  # mét teken (bank-direct: teken van de mutatie)
    datum: date | None = None


@dataclass(frozen=True)
class Classificatie:
    soort: str  # aankoop | verkoop | kosten | aanbetaling | vaste_lasten | balans
    zekerheid: str  # hoog | midden | laag
    reden: str
    adres: AdresVoorstel | None
    dossiers: tuple[str, ...] = field(default_factory=tuple)  # volledige notarisdossiers (sleutel)
    notaris: NotarisHerkenning | None = None
    dossiers_onvolledig: tuple[str, ...] = field(default_factory=tuple)  # afgekapt notarisformaat, nooit sleutel
    dossiers_overig: tuple[str, ...] = field(default_factory=tuple)  # "dossier: 118261" — informatie, nooit een pand
    meerduidig: bool = False  # meerdere adressen in de tekst → adres None
    dossierwoord: bool = False  # het woord "dossier" staat in de tekst


# ---- tekst ------------------------------------------------------------------------------------------


def _norm(tekst: str) -> str:
    plat = unicodedata.normalize("NFKD", tekst).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plat.lower()).strip("-")


def _is_plaats(woorden: list[str]) -> bool:
    return " ".join(woorden).lower() in PLAATSNAMEN


def _vouw_herhaling(woorden: list[str]) -> list[str]:
    """ "Burgemeester Norbrui Burgemeester Norbruislaan" → "Burgemeester Norbruislaan": RLZ zet een (op 20 tekens
    afgekapte) Reference vóór de Description; de eerste helft is dan woord-voor-woord een prefix van de tweede."""
    n = len(woorden)
    for k in range(1, n // 2 + 1):
        if n - k < k:
            break
        eerste, tweede = woorden[:k], woorden[k : 2 * k]
        if len(tweede) != k:
            continue
        paren = list(zip(eerste, tweede, strict=True))
        kop_gelijk = all(a.lower() == b.lower() for a, b in paren[:-1])
        staart_prefix = tweede[-1].lower().startswith(eerste[-1].lower()) and len(eerste[-1]) >= 3
        if kop_gelijk and staart_prefix:
            return woorden[k:]
    return woorden


def _strip_stopwoorden(straat: str) -> str:
    """Vulwoorden, plaatsnaam- en postcode-restanten vóór de straatnaam weg. Een partikel ("van", "de") blijft staan als
    het met een hoofdletter geschreven is ("Van der Kunstraat") óf als het een keten van ≥ 2 partikels vormt direct vóór
    de naam ("van de Spiegelstraat"); een los kleingeschreven partikel is filler ("kosten van Kerkstraat 44")."""
    woorden = _vouw_herhaling(straat.split())
    while len(woorden) > 1:
        w = woorden[0].strip(".:,;")
        laag = w.lower()
        if _POSTCODE_RESTANT.match(w):
            woorden.pop(0)
            continue
        geknipt = False
        for lengte in (3, 2, 1):
            if len(woorden) > lengte and _is_plaats(woorden[:lengte]):
                del woorden[:lengte]
                geknipt = True
                break
        if geknipt:
            continue
        if laag not in _STOPWOORDEN:
            break
        if laag in _PARTIKELS:
            if w[:1].isupper():
                break
            keten = 0
            for x in woorden[:-1]:
                if x.lower() in _PARTIKELS:
                    keten += 1
                else:
                    break
            if keten >= 2 and keten == len(woorden) - 1:
                woorden[0] = woorden[0][:1].upper() + woorden[0][1:]
                break
        woorden.pop(0)
    return " ".join(woorden)


def _plaats_uit(m: re.Match[str]) -> str | None:
    """Plaats ná het huisnummer: mét trigger (komma / "te" / postcode) tot het eerste vulwoord; zonder trigger alleen
    een
    bekende plaatsnaam (langste bekende prefix)."""
    ruw = m.group("plaats")
    if not ruw:
        return None
    woorden = ruw.split()
    for lengte in range(min(4, len(woorden)), 0, -1):
        if _is_plaats(woorden[:lengte]):
            return " ".join(woorden[:lengte])
    rest = (m.group("rest") or "").lstrip()
    trigger = bool(m.group("postcode")) or rest.startswith(",") or rest.lower().startswith("te ")
    if not trigger:
        return None
    uit: list[str] = []
    for w in woorden:
        if w.lower().strip(".,:;") in _GEEN_PLAATS_WOORDEN or len(w) == 1:
            break
        uit.append(w)
    return " ".join(uit) or None


def _voorstel_uit_match(m: re.Match[str]) -> AdresVoorstel | None:
    straat = _strip_stopwoorden(" ".join(m.group("straat").split()))
    if not straat or not straat[0].isalpha() or straat.lower() in PLAATSNAMEN:
        return None
    if len(straat) < 4 or straat.lower() in _STOPWOORDEN:
        return None
    if straat.split()[-1].lower() in PLAATSNAMEN or m.group("nummer").startswith("0"):
        # "Cafe … Amsterdam 7R-…", "Meyer Amsterdam 04-09-2026": een plaats is geen straat, een 0-nummer geen huisnummer
        return None
    toevoeging = (m.group("toevoeging") or "").strip() or None
    if toevoeging and toevoeging.lower() in _GEEN_TOEVOEGING:
        toevoeging = None
    postcode = m.group("postcode")
    return AdresVoorstel(
        straat=straat[:1].upper() + straat[1:],
        huisnummer=m.group("nummer"),
        toevoeging=toevoeging.replace(" ", "") if toevoeging else None,
        postcode=postcode.replace(" ", "").upper() if postcode else None,
        plaats=_plaats_uit(m),
    )


def _zelfde_pand(a: AdresVoorstel, b: AdresVoorstel) -> bool:
    """Zelfde huisnummer en de ene straat bevat de andere ("Kleiweg" ⊂ "Overschiese Kleiweg") — dedup binnen één
    tekst."""
    if a.huisnummer != b.huisnummer:
        return False
    na, nb = _norm(a.straat), _norm(b.straat)
    return na == nb or na.endswith(nb) or nb.endswith(na) or na.startswith(nb) or nb.startswith(na)


def adressen_uit_tekst(*teksten: str | None) -> list[AdresVoorstel]:
    """Alle herkende adressen (uniek op pand, volgorde van voorkomen)."""
    tekst = " ".join(t for t in teksten if isinstance(t, str) and t.strip())
    uit: list[AdresVoorstel] = []
    for patroon in (_ADRES, _ADRES_NA_TRIGGER):
        for m in patroon.finditer(tekst):
            voorstel = _voorstel_uit_match(m)
            if voorstel is None:
                continue
            bestaand = next((i for i, b in enumerate(uit) if _zelfde_pand(voorstel, b)), None)
            if bestaand is None:
                uit.append(voorstel)
            elif not uit[bestaand].plaats and voorstel.plaats:
                uit[bestaand] = AdresVoorstel(**{**uit[bestaand].__dict__, "plaats": voorstel.plaats})
    return uit


def adres_uit_tekst(*teksten: str | None) -> AdresVoorstel | None:
    """Precies één adres, anders None (nul = geen signaal, twee of meer = meerduidig — nooit invullen)."""
    gevonden = adressen_uit_tekst(*teksten)
    return gevonden[0] if len(gevonden) == 1 else None


@dataclass(frozen=True)
class Dossiers:
    volledig: tuple[str, ...]
    onvolledig: tuple[str, ...]
    overig: tuple[str, ...]
    dossierwoord: bool


def dossiers_uit_tekst(*teksten: str | None) -> Dossiers:
    tekst = " ".join(t for t in teksten if isinstance(t, str) and t.strip())
    volledig: list[str] = []
    onvolledig: list[str] = []
    overig: list[str] = []
    for m in _DOSSIER_NOTARIS.finditer(tekst):
        if m.group(1) not in volledig:
            volledig.append(m.group(1))
    for m in _DOSSIER_ONVOLLEDIG.finditer(tekst):
        nummer = m.group(1)
        if _DATUM_ACHTIG.match(nummer) or nummer in volledig or nummer in onvolledig:
            continue
        if any(v.startswith(nummer) for v in volledig):
            continue
        onvolledig.append(nummer)
    for m in _DOSSIER_EXPLICIET.finditer(tekst):
        nummer = m.group(1).strip().rstrip(".,;:")
        if nummer in volledig or nummer in onvolledig or nummer in overig:
            continue
        if _DATUM_ACHTIG.match(nummer) or _FACTUURNUMMER.match(nummer):
            continue  # leveranciers-factuurnummer of datum: nooit een dossier
        if any(v.startswith(nummer) for v in volledig) or any(o.startswith(nummer) for o in onvolledig):
            continue
        overig.append(nummer)
    return Dossiers(tuple(volledig), tuple(onvolledig), tuple(overig), bool(_DOSSIERWOORD.search(tekst)))


def dossiernummers_uit_tekst(*teksten: str | None) -> tuple[str, ...]:
    """Alleen volledige notarisdossiers `JJJJ.NNNNNN.NN` — de enige dossier-SLEUTEL."""
    return dossiers_uit_tekst(*teksten).volledig


def dossiernummer_uit_tekst(*teksten: str | None) -> str | None:
    gevonden = dossiernummers_uit_tekst(*teksten)
    return gevonden[0] if len(gevonden) == 1 else None


def notaris_herkenning(entity_naam: str | None) -> NotarisHerkenning | None:
    if not entity_naam or not entity_naam.strip():
        return None
    laag = entity_naam.lower()
    for weergave, varianten in BEKENDE_NOTARISSEN:
        if any(v in laag for v in varianten):
            return NotarisHerkenning(naam=weergave, bekend=True)
    if _GENERIEK_NOTARIS.search(entity_naam):
        return NotarisHerkenning(naam=" ".join(entity_naam.split()), bekend=False)
    return None


# ---- classificatie ----------------------------------------------------------------------------------


def is_memoriaal(feit: BoekingsFeit) -> bool:
    """ManualJournal in het memoriaal-dagboek: boekstukreeks RLZ-06 of een dagboeknaam met 'memoriaal'; zonder
    boekstuk en dagboek geldt de collectie zelf (ManualJournals zijn per definitie memoriaal)."""
    if feit.collectie != "ManualJournals":
        return False
    if feit.boekstuk and feit.boekstuk.upper().startswith(MEMORIAAL_REEKS):
        return True
    if feit.dagboek and "memoriaal" in feit.dagboek.lower():
        return True
    return not feit.boekstuk and not feit.dagboek


def is_bank_direct(feit: BoekingsFeit) -> bool:
    """Bank-directe boeking: de Receipts-collectie, een PaymentTransaction, of een ManualJournal buiten het memoriaal-
    dagboek (bankdagboek-reeksen RLZ-09/-25/-28/-46/-60 — het document IS een bankmutatie-boeking)."""
    if feit.collectie in BANK_COLLECTIES:
        return True
    return feit.collectie == "ManualJournals" and not is_memoriaal(feit)


def is_jaareinde(datum: date | None) -> bool:
    return datum is not None and (datum.month, datum.day) == (12, 31)


def _teken(bedrag: Decimal | None) -> int | None:
    if bedrag is None or bedrag == 0:
        return None
    return 1 if bedrag > 0 else -1


def classificeer(feit: BoekingsFeit) -> Classificatie | None:
    if feit.collectie not in DOCUMENT_COLLECTIES:
        return None
    adressen = adressen_uit_tekst(feit.tekst)
    adres = adressen[0] if len(adressen) == 1 else None
    meerduidig = len(adressen) > 1
    d = dossiers_uit_tekst(feit.tekst)
    notaris = notaris_herkenning(feit.entity_naam)
    dossier_signaal = bool(d.volledig or d.onvolledig)
    if adres is None and not meerduidig and not dossier_signaal:
        return None  # ook: notaris zonder adres/dossier, "Dossiernummer: 118261", kale factuurnummers

    def _maak(soort: str, zekerheid: str, reden: str) -> Classificatie:
        if meerduidig:
            reden += " — meerdere adressen in de tekst, adres niet ingevuld"
            zekerheid = "laag"
        return Classificatie(
            soort=soort,
            zekerheid=zekerheid,
            reden=reden,
            adres=adres,
            dossiers=d.volledig,
            notaris=notaris,
            dossiers_onvolledig=d.onvolledig,
            dossiers_overig=d.overig,
            meerduidig=meerduidig,
            dossierwoord=d.dossierwoord,
        )

    def _zekerheid(*tweede: object) -> str:
        if adres and any(tweede):
            return "hoog"
        if adres:
            return "midden"
        return "laag"

    tweede_signaal = (notaris, dossier_signaal, adres.plaats if adres else None)
    t = feit.tekst

    if is_memoriaal(feit) and is_jaareinde(feit.datum):
        return _maak(
            "balans", "midden" if adres else "laag", "31-12-memoriaal — jaareinde-/balansboeking, geen aankoop"
        )
    if _SIG_AANBETALING.search(t):
        return _maak(
            "aanbetaling", _zekerheid(*tweede_signaal), "aanbetaling aan verkoper (vooruitbetaald op voorraad)"
        )
    if _SIG_VASTE_LASTEN.search(t):
        return _maak("vaste_lasten", _zekerheid(*tweede_signaal), "vaste lasten voor de verkoper (W&V)")
    if _SIG_VERKOOP.search(t):
        wie = f" · notaris {notaris.naam}" if notaris else ""
        return _maak("verkoop", _zekerheid(notaris, dossier_signaal), f"verkoop-signaal in de omschrijving{wie}")

    if feit.collectie == "SalesInvoices":
        if _SIG_RENTE.search(t):
            return _maak(
                "kosten", _zekerheid(*tweede_signaal), "verkoopfactuur rente/huur — opbrengst per pand, geen verkoop"
            )
        if notaris:
            return _maak("verkoop", _zekerheid(notaris), f"verkoopfactuur op notaris {notaris.naam}")
        if adres:
            return _maak("verkoop", "midden", "verkoopfactuur met adres, geen notaris als relatie")
        return _maak("verkoop", "laag", "verkoopfactuur met alleen een dossiernummer")

    if is_bank_direct(feit):
        overdracht = bool(_SIG_OVERDRACHT.search(t))
        if notaris or overdracht:
            teken = _teken(feit.bedrag)
            bron = f"notaris {notaris.naam}" if notaris else "overdracht/afrekening"
            if teken == 1:
                return _maak("verkoop", _zekerheid(notaris, dossier_signaal), f"bank-ontvangst van {bron} (positief)")
            if teken == -1:
                return _maak("aankoop", _zekerheid(notaris, dossier_signaal), f"betaling aan {bron} (negatief)")
            if notaris:
                return _maak("verkoop", "midden" if adres else "laag", f"bankboeking {bron}, teken onbekend")
        return _maak("kosten", _zekerheid(*tweede_signaal), "bank-directe boeking met adres/dossier")

    if feit.collectie == "ManualJournals":  # memoriaal RLZ-06
        if adres and (feit.heeft_bijlage or dossier_signaal):
            bron = "notaris-PDF" if feit.heeft_bijlage else "dossiernummer"
            return _maak("aankoop", "hoog", f"memoriaal {MEMORIAAL_REEKS} met adres + {bron}")
        if adres:
            return _maak("aankoop", "midden", f"memoriaal {MEMORIAAL_REEKS} met adres, zonder bijlage/dossier")
        return _maak("aankoop", "laag", "memoriaal met alleen een dossiernummer")

    if feit.collectie == "PurchaseInvoices":
        if adres and (dossier_signaal or notaris):
            return _maak("kosten", "hoog", "inkoopfactuur met adres + dossier/notaris")
        if adres:
            return _maak("kosten", "midden", "inkoopfactuur met adres in de omschrijving")
        return _maak("kosten", "laag", "inkoopfactuur met alleen een dossiernummer")

    return None


def classificeer_bankmutatie(feit: BoekingsFeit) -> Classificatie | None:
    """Eén PaymentTransaction als feit (collectie "PaymentTransactions", `entity_naam` = tegenpartij `Name`, `tekst` =
    ontknipte `Reference`, `bedrag` mét teken). Positief van een notaris of met "overdracht" + adres = VERKOOP; negatief
    aan een notaris met overdracht/afrekening = AANKOOP; "aanbetaling"/"vaste lasten" = die soorten."""
    if feit.collectie != "PaymentTransactions":
        return None
    return classificeer(feit)
