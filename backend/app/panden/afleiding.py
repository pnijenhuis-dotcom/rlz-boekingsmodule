"""Deterministische afleiding pandenregister (bundel 10-09 blok D2) — pure functies, geen AI, geen I/O.

- `adres_uit_tekst`: NL straat + huisnummer (+ toevoeging) + optioneel postcode/plaats uit referentie/omschrijving.
  Straatherkenning op een vaste suffixlijst (straat, laan, weg, plein, kade, …) zodat "keuring Kerkstraat 44" wél en
  "factuur 2026047" nooit een adres wordt. Meerdere adressen in één tekst = MEERDUIDIG → None (nooit gokken).
- `dossiernummers_uit_tekst`: notaris-dossiernummers (vorm `2025.058870.01`, `2026/014221`, "dossier …").
- `notaris_herkenning`: bekende notarissen van de casus (Ouwerkerk — in de opdracht ook "Ouwekerk" gespeld —, Buma
  Algera) + generiek "notaris"/"notariaat"/"notarissen" in de relatienaam.
- `classificeer`: soort + zekerheid uit collectie, dagboek/boekstukreeks, notaris, adres, dossier en bijlage.
  Aankoop = memoriaal (RLZ-06) mét adres + notaris-PDF/dossier → hoog; verkoop = verkoopfactuur (RLZ-01) op een
  notaris mét adres → hoog; adres zonder notaris → midden; alleen dossier → laag; niets → geen pand-signaal
  (kosten horen dan op het Overhead-project — een keuze voor de mens in run 2, nooit automatisch).
AI-extractie uit de PDF komt hier bewust NIET voor; die is hooguit aanvulling mét mens-bevestiging (run 2)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

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
)
#: Woorden vóór de straatnaam die geen deel van de naam zijn ("Betreft Kerkstraat 44", "pand Goeverneurlaan 310").
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
    }
)
_GEEN_TOEVOEGING: frozenset[str] = frozenset({"te", "en", "of", "in", "op", "bv", "nv", "cv", "ex", "no", "nr"})

_SUFFIX_ALT = "|".join(sorted(STRAAT_SUFFIXEN, key=len, reverse=True))
_PREFIX_WOORD = r"(?:[A-Z][\w'’.-]*|\d{1,2}e|van|der|de|den|het|'t|op|aan|ten|ter)"
_ADRES = re.compile(
    rf"\b(?P<straat>(?:{_PREFIX_WOORD}\s+){{0,3}}[A-Za-z][\w'’-]*(?:{_SUFFIX_ALT}))"
    r"\s+(?P<nummer>\d{1,5})"
    r"(?P<toevoeging>-\s?\d{1,3}|(?<=\d)[A-Za-z]{1,2}|\s(?:[A-Za-z]|bis|hs))?(?![\w'’])"
    r"(?P<rest>(?:\s*,\s*|\s+te\s+|\s+)(?:(?P<postcode>\d{4}\s?[A-Z]{2})\s*,?\s*)?"
    r"(?P<plaats>[A-Z][a-zA-Z'’-]+(?:\s(?:[A-Z][a-zA-Z'’-]+|aan|den|de|op|en|het|'t|bij|van|der)){0,2})?)?",
    re.UNICODE,
)
_DOSSIER_NOTARIS = re.compile(r"\b(20\d{2}\.\d{4,6}\.\d{2})\b")
_DOSSIER_KORT = re.compile(r"\b(20\d{2}[./-]\d{4,6})\b(?![./-]\d{2}\b)")
_DOSSIER_EXPLICIET = re.compile(r"\bdossier(?:nr|nummer|no|\.|:)?\.?:?\s*#?\s*([A-Za-z]?\d[\w./-]{4,})", re.IGNORECASE)
_DATUM_ACHTIG = re.compile(r"^20\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01])$")

BEKENDE_NOTARISSEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ouwerkerk", ("ouwerkerk", "ouwekerk")),
    ("Buma Algera", ("buma algera", "buma-algera", "bumaalgera")),
)
_GENERIEK_NOTARIS = re.compile(r"notari(?:s|ssen|aat|eel)", re.IGNORECASE)

MEMORIAAL_REEKS = "RLZ-06"
VERKOOP_REEKS = "RLZ-01"


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


@dataclass(frozen=True)
class NotarisHerkenning:
    naam: str  # genormaliseerde weergavenaam ("Ouwerkerk", "Buma Algera") of de relatienaam bij generiek
    bekend: bool  # True = één van de casus-notarissen


@dataclass(frozen=True)
class BoekingsFeit:
    """Wat de afleiding van één RLZ-document nodig heeft — platgeslagen door de service."""

    collectie: str  # PurchaseInvoices | SalesInvoices | ManualJournals
    boekstuk: str | None
    entity_naam: str | None
    tekst: str  # referentie + omschrijving + header, spatie-gescheiden
    heeft_bijlage: bool | None = None  # None = niet gecontroleerd
    dagboek: str | None = None


@dataclass(frozen=True)
class Classificatie:
    soort: str  # aankoop | verkoop | kosten
    zekerheid: str  # hoog | midden | laag
    reden: str
    adres: AdresVoorstel | None
    dossiers: tuple[str, ...] = field(default_factory=tuple)
    notaris: NotarisHerkenning | None = None


# ---- tekst ------------------------------------------------------------------------------------------


def _norm(tekst: str) -> str:
    plat = unicodedata.normalize("NFKD", tekst).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plat.lower()).strip("-")


_PARTIKELS: frozenset[str] = frozenset({"van", "de", "den", "der", "het", "'t", "ten", "ter"})


def _strip_stopwoorden(straat: str) -> str:
    """Vulwoorden vóór de straatnaam weg. Een partikel ("van", "de") blijft staan als het met een hoofdletter
    geschreven is — dan hoort het bij de naam ("Van der Kunstraat"); kleingeschreven is het filler ("kosten van
    Kerkstraat 44")."""
    woorden = straat.split()
    while len(woorden) > 1:
        w = woorden[0].strip(".:")
        laag = w.lower()
        if laag not in _STOPWOORDEN:
            break
        if laag in _PARTIKELS and w[:1].isupper():
            break
        woorden.pop(0)
    return " ".join(woorden)


def adressen_uit_tekst(*teksten: str | None) -> list[AdresVoorstel]:
    """Alle herkende adressen (uniek op code, volgorde van voorkomen)."""
    tekst = " ".join(t for t in teksten if isinstance(t, str) and t.strip())
    uit: list[AdresVoorstel] = []
    codes: set[str] = set()
    for m in _ADRES.finditer(tekst):
        straat = _strip_stopwoorden(" ".join(m.group("straat").split()))
        if not straat or not straat[0].isalpha():
            continue
        toevoeging = (m.group("toevoeging") or "").strip() or None
        if toevoeging and toevoeging.lower() in _GEEN_TOEVOEGING:
            toevoeging = None
        plaats = m.group("plaats")
        postcode = m.group("postcode")
        if plaats and not (postcode or (m.group("rest") or "").lstrip().startswith((",", "te "))):
            # Een los woord ná het huisnummer zonder komma/te/postcode is geen plaats ("Kerkstraat 44 Keuring").
            plaats = None
        voorstel = AdresVoorstel(
            straat=straat,
            huisnummer=m.group("nummer"),
            toevoeging=toevoeging.replace(" ", "") if toevoeging else None,
            postcode=postcode.replace(" ", "").upper() if postcode else None,
            plaats=plaats.strip() if plaats else None,
        )
        if voorstel.code not in codes:
            codes.add(voorstel.code)
            uit.append(voorstel)
    return uit


def adres_uit_tekst(*teksten: str | None) -> AdresVoorstel | None:
    """Precies één adres, anders None (nul = geen signaal, twee of meer = meerduidig — nooit invullen)."""
    gevonden = adressen_uit_tekst(*teksten)
    return gevonden[0] if len(gevonden) == 1 else None


def dossiernummers_uit_tekst(*teksten: str | None) -> tuple[str, ...]:
    tekst = " ".join(t for t in teksten if isinstance(t, str) and t.strip())
    uit: list[str] = []
    for patroon in (_DOSSIER_NOTARIS, _DOSSIER_EXPLICIET, _DOSSIER_KORT):
        for m in patroon.finditer(tekst):
            nummer = m.group(1).strip().rstrip(".,;:")
            if _DATUM_ACHTIG.match(nummer) or nummer in uit:
                continue
            # Een kort nummer dat het begin van een al gevonden notarisnummer is, is hetzelfde dossier.
            if any(bestaand.startswith(nummer) for bestaand in uit):
                continue
            uit.append(nummer)
    return tuple(uit)


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


def classificeer(feit: BoekingsFeit) -> Classificatie | None:
    adres = adres_uit_tekst(feit.tekst)
    dossiers = dossiernummers_uit_tekst(feit.tekst)
    notaris = notaris_herkenning(feit.entity_naam)
    meerduidig = len(adressen_uit_tekst(feit.tekst)) > 1

    def _maak(soort: str, zekerheid: str, reden: str) -> Classificatie:
        if meerduidig:
            reden += " — meerdere adressen in de tekst, adres niet ingevuld"
        return Classificatie(
            soort=soort, zekerheid=zekerheid, reden=reden, adres=adres, dossiers=dossiers, notaris=notaris
        )

    if feit.collectie == "ManualJournals":
        if not is_memoriaal(feit):
            return None
        if adres and (feit.heeft_bijlage or dossiers):
            bron = "notaris-PDF" if feit.heeft_bijlage else "dossiernummer"
            return _maak("aankoop", "hoog", f"memoriaal {MEMORIAAL_REEKS} met adres + {bron}")
        if adres:
            return _maak("aankoop", "midden", f"memoriaal {MEMORIAAL_REEKS} met adres, zonder bijlage/dossier")
        if dossiers:
            return _maak("aankoop", "laag", "memoriaal met alleen een dossiernummer")
        return None

    if feit.collectie == "SalesInvoices":
        if notaris and adres:
            return _maak("verkoop", "hoog", f"verkoopfactuur op notaris {notaris.naam} met adres")
        if adres:
            return _maak("verkoop", "midden", "verkoopfactuur met adres, geen notaris als relatie")
        if dossiers:
            wie = f"notaris {notaris.naam}" if notaris else "relatie"
            return _maak("verkoop", "laag", f"verkoopfactuur op {wie} met alleen een dossiernummer")
        return None

    if feit.collectie == "PurchaseInvoices":
        if adres and (dossiers or notaris):
            return _maak("kosten", "hoog", "inkoopfactuur met adres + dossier/notaris")
        if adres:
            return _maak("kosten", "midden", "inkoopfactuur met adres in de omschrijving")
        if dossiers:
            return _maak("kosten", "laag", "inkoopfactuur met alleen een dossiernummer")
        return None

    return None
