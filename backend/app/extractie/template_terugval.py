"""Deterministische extractie-terugval: template-parser per bekende leverancier (best-practice-
besluit 2, 31-08 — aanleiding: de AI-extractie bleek een single point of failure (schema-bug 30/31-08
= álle extracties stuk; AI-kostengrens = extractie valt weg) én kost geld op facturen die er elke
maand identiek uitzien).

Pure logica, geen DB en geen AI — volledig unit-testbaar (zelfde patroon als controle.py):

1. TEMPLATE LEREN (`leer_template`): uit de tekstlaag van N ≥ 3 mens-bevestigde documenten van één
   crediteur worden per kopveld ankers afgeleid (het label vóór de waarde op dezelfde regel, het label
   op de regel erboven, of de kolomkop in een tabel). Een anker geldt alleen als hij in ÉLK leerdocument
   voorkomt én toegepast exact de bevestigde waarde oplevert (bedragen cent-exact, datums exact,
   referentie letterlijk). Eén veld zonder reproduceerbaar anker = géén template — nooit een
   gedeeltelijk template.
2. TOEPASSEN (`pas_template_toe`): parse + interne validaties — alle velden gevonden, excl + btw =
   incl cent-exact, referentie conform het geleerde vormpatroon, btw-percentage binnen de geleerde
   set, vervaldatum niet vóór de factuurdatum. Eén validatie rood = `TemplateVerworpen`: de uitkomst
   wordt VOLLEDIG verworpen, de aanroeper markeert het template ongeldig en gaat door naar het AI-pad.
3. CREDITEUR-HERKENNING zonder AI (`herken_crediteur`): btw-nummer → KvK-nummer → IBAN → exacte naam
   uit de eigen caches; bij meer dan één kandidaat géén herkenning ("nooit auto bij twijfel").

Regelniveau: uitsluitend de deterministisch veilige vorm — één boekingsregel gelijk aan de kop-
totalen wanneer álle leerdocumenten zo bevestigd zijn (`regels_modus` "enkel"); anders kop-only en de
regels via het bestaande boekingsgeheugen-voorstel. Nooit gokken op tabellen.

BSN-regel onverkort: de parser leest uitsluitend de gevraagde kopvelden (getal-/datum-/referentie-
patronen achter een anker) en slaat nooit vrije tekst op; de tekstlaag zelf wordt niet gepersisteerd.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.extractie.btw_nummer import normaliseer_kvk_nummer, valideer_btw_nummer
from app.extractie.controle import VendorKandidaat, _genormaliseerd
from app.extractie.iban import is_geldig_iban, normaliseer_iban

logger = logging.getLogger(__name__)

TEMPLATE_VERSIE = 1

# Kopvelden die het template levert. Verplicht uit de tekst: factuurnummer, factuurdatum, totaal_excl,
# totaal_incl. btw_bedrag mag "nul" zijn (btw verlegd/vrijgesteld: bevestigd 0 in álle leerdocumenten
# en incl == excl), vervaldatum mag "afwezig" zijn (niet op de factuur, in álle leerdocumenten leeg).
KOPVELDEN = ("factuurnummer", "factuurdatum", "vervaldatum", "totaal_excl", "btw_bedrag", "totaal_incl")
_BEDRAG_VELDEN = frozenset({"totaal_excl", "btw_bedrag", "totaal_incl"})
_DATUM_VELDEN = frozenset({"factuurdatum", "vervaldatum"})

# Bekende NL-tarieven voor de percentage-validatie (fracties, zelfde eenheidsregel als app/sync/btw.py).
_BEKENDE_PERCENTAGES: tuple[tuple[int, Decimal], ...] = ((21, Decimal("0.21")), (9, Decimal("0.09")))
_CENT = Decimal("0.01")
_KOLOM_TOLERANTIE = 4
_MAX_ANKER_WOORDEN = 6
_MIN_TEKSTLAAG_TEKENS = 20


# --- Tekstlaag -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tekstlaag:
    """Genormaliseerde tekstregels van een PDF (lege regels weg, NBSP → spatie, rechts gestript) +
    de pypdf-extractiemodus waarmee ze gelezen zijn. Templates onthouden de modus: layout-modus
    bewaart kolomposities (kolomkop-ankers), plain is de terugval."""

    regels: tuple[str, ...]
    modus: str  # "layout" | "plain"


def _normaliseer_regels(tekst: str) -> tuple[str, ...]:
    regels = []
    for ruw in tekst.replace("\xa0", " ").splitlines():
        regel = ruw.rstrip()
        if regel.strip():
            regels.append(regel)
    return tuple(regels)


def _heeft_tekst(regels: tuple[str, ...]) -> bool:
    return sum(ch.isalnum() for regel in regels for ch in regel) >= _MIN_TEKSTLAAG_TEKENS


def lees_tekstlaag(pdf_bytes: bytes, *, modus: str | None = None) -> Tekstlaag | None:
    """Tekstlaag van een PDF via pypdf, of None als er geen (bruikbare) tekstlaag is — een scan
    zonder OCR-laag gaat dan gewoon het AI-pad. `modus` dwingt de modus van een bestaand template
    af (leren en toepassen moeten dezelfde tekstweergave zien); zonder modus: layout, terugval plain."""
    from pypdf import PdfReader  # lokaal: zelfde lazy-import-conventie als documenten/pdf.py

    try:
        lezer = PdfReader(io.BytesIO(pdf_bytes))
        paginas = list(lezer.pages)
    except Exception:  # noqa: BLE001 — een onleesbare PDF is geen tekstlaag, geen fout
        return None
    modi = (modus,) if modus else ("layout", "plain")
    for kandidaat in modi:
        try:
            tekst = "\n".join((pagina.extract_text(extraction_mode=kandidaat) or "") for pagina in paginas)
        except Exception:  # noqa: BLE001 — layout-modus kan op exotische fonts struikelen: dan plain
            continue
        regels = _normaliseer_regels(tekst)
        if _heeft_tekst(regels):
            return Tekstlaag(regels=regels, modus=kandidaat)
    return None


# --- Waardepatronen + parsen ----------------------------------------------------------------------

_BEDRAG_RE = re.compile(
    r"(?<![\d,.])(?P<v>[-−]?\s?(?:€\s?)?(?:\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+[.,]\d{2}))(?!\d)"
)
_DATUM_RE = re.compile(
    r"(?<![\d])(?P<v>\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4})(?![\d])"
)
_REFERENTIE_RE = re.compile(r"(?<![A-Za-z0-9])(?P<v>[A-Za-z0-9][A-Za-z0-9._/\-]*[A-Za-z0-9])(?![A-Za-z0-9])")
_MAANDEN = {
    "januari": 1, "jan": 1, "january": 1,
    "februari": 2, "feb": 2, "february": 2,
    "maart": 3, "mrt": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6,
    "juli": 7, "jul": 7, "july": 7,
    "augustus": 8, "aug": 8, "august": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}  # fmt: skip


def parse_bedrag_tekst(ruw: str) -> Decimal | None:
    """Bedrag zoals het óp de factuur staat → Decimal met 2 decimalen: NL ("1.234,56", "1234,56"),
    EN ("1,234.56", "1234.56"), optioneel €/spaties/minteken. Alles anders = None — nooit gokken."""
    schoon = ruw.replace("€", "").replace(" ", "").replace("−", "-").strip()
    # Altijd twee decimalen: "1.234" is ambigu (1234 of 1,234) — zonder centen géén bedrag.
    if not re.search(r"[.,]\d{2}$", schoon):
        return None
    if "," in schoon and "." in schoon:
        if schoon.rfind(",") > schoon.rfind("."):
            schoon = schoon.replace(".", "").replace(",", ".")
        else:
            schoon = schoon.replace(",", "")
    elif "," in schoon:
        schoon = schoon.replace(",", ".")
    try:
        bedrag = Decimal(schoon)
    except InvalidOperation:
        return None
    if bedrag != bedrag.quantize(_CENT) or abs(bedrag) >= Decimal("100000000"):
        return None
    return bedrag


def parse_datum_tekst(ruw: str) -> date | None:
    """Datum zoals op de factuur: ISO, dd-mm-jjjj (NL-volgorde; ook / en .), of "1 augustus 2026"
    (NL + EN maandnamen). Plausibiliteitsvenster 2000–2100."""
    tekst = ruw.strip()
    datum: date | None = None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tekst):
            datum = date.fromisoformat(tekst)
        elif (m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", tekst)) is not None:
            datum = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif (m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", tekst)) is not None:
            maand = _MAANDEN.get(m.group(2).lower())
            if maand is None:
                return None
            datum = date(int(m.group(3)), maand, int(m.group(1)))
    except ValueError:
        return None
    if datum is None or not (2000 <= datum.year <= 2100):
        return None
    return datum


def _waarde_re(veld: str) -> re.Pattern[str]:
    if veld in _BEDRAG_VELDEN:
        return _BEDRAG_RE
    if veld in _DATUM_VELDEN:
        return _DATUM_RE
    return _REFERENTIE_RE


def _parse(veld: str, ruw: str) -> Any:
    if veld in _BEDRAG_VELDEN:
        return parse_bedrag_tekst(ruw)
    if veld in _DATUM_VELDEN:
        return parse_datum_tekst(ruw)
    return ruw.strip()


# --- Ankers ----------------------------------------------------------------------------------------

_WOORD_RE = re.compile(r"\S+")
_RAND_TEKENS = ":#.,;€$-–—()[]|*"
_TUSSEN = r"[^A-Za-z0-9]{0,4}"  # tussen ankerwoorden: leestekens/spaties (".", ":", "€")
_NA_ANKER = r"[^A-Za-z0-9]*?"  # tussen anker en waarde: alleen leestekens/valuta/spaties


def _ankerwoord(woord: str) -> str:
    return woord.strip(_RAND_TEKENS)


def _ankerwoorden(tekst: str) -> list[str]:
    return [w for w in (_ankerwoord(w) for w in _WOORD_RE.findall(tekst)) if w]


def _heeft_letters(woorden: tuple[str, ...]) -> bool:
    return sum(ch.isalpha() for w in woorden for ch in w) >= 2


def _staarten(woorden: list[str]) -> list[tuple[str, ...]]:
    """Alle achtervoegsels (laatste k woorden, k = 1..MAX) mét minstens twee letters — het korte
    label ("Factuurnummer") én de langere context ("Totaal incl BTW") zijn beide kandidaat."""
    uit: list[tuple[str, ...]] = []
    for k in range(1, min(len(woorden), _MAX_ANKER_WOORDEN) + 1):
        staart = tuple(woorden[-k:])
        if _heeft_letters(staart):
            uit.append(staart)
    return uit


def _anker_regex(woorden: tuple[str, ...]) -> str:
    return r"(?<![A-Za-z0-9])" + _TUSSEN.join(re.escape(w) for w in woorden)


@dataclass(frozen=True)
class Anker:
    """Eén ankerregel voor één kopveld. soort: "prefix" (label vóór de waarde op dezelfde regel),
    "vorige_regel" (de regel erboven is precies het label, waarde begint de regel), "kolomkop" (kolomkop in de
    regel erboven die dezelfde kolom overlapt — alleen layout-modus)."""

    soort: str
    woorden: tuple[str, ...]

    def als_dict(self) -> dict[str, Any]:
        return {"soort": self.soort, "anker": list(self.woorden)}

    @staticmethod
    def uit_dict(d: dict[str, Any]) -> Anker:
        return Anker(soort=str(d["soort"]), woorden=tuple(str(w) for w in d["anker"]))


def _vorige_index(regels: tuple[str, ...], index: int) -> int | None:
    return index - 1 if index > 0 else None


def _kandidaten_voor_treffer(regels: tuple[str, ...], index: int, start: int, eind: int, *, layout: bool) -> set[Anker]:
    """Alle ankerkandidaten die deze ene waarde-treffer beschrijven."""
    regel = regels[index]
    kandidaten: set[Anker] = set()
    prefix = regel[:start]
    prefix_woorden = _ankerwoorden(prefix)
    if prefix_woorden:
        for staart in _staarten(prefix_woorden):
            kandidaten.add(Anker("prefix", staart))
    vorige = _vorige_index(regels, index)
    if vorige is None:
        return kandidaten
    vorige_regel = regels[vorige]
    if not any(ch.isalnum() for ch in prefix):
        # Label op de regel erboven: de VOLLEDIGE regel is het anker (een staart als "btw" zou ook
        # "Excl. btw" raken en de verkeerde waarde als eerste treffer geven).
        label = tuple(_ankerwoorden(vorige_regel))
        if 0 < len(label) <= _MAX_ANKER_WOORDEN and _heeft_letters(label):
            kandidaten.add(Anker("vorige_regel", label))
    if layout:
        kop = _kolomkop_boven(vorige_regel, start, eind)
        if kop is not None:
            kandidaten.add(kop)
    return kandidaten


def _overlapt(kop_start: int, kop_eind: int, start: int, eind: int) -> bool:
    """Kolomtoets: de kolomkop en de waarde delen (ruwweg) dezelfde kolom. pypdf's layout-modus
    schaalt posities per teken, waardoor koppen en waarden enkele tekens kunnen verschuiven —
    daarom een overlap-toets mét tolerantie i.p.v. exacte uitlijning."""
    return start <= kop_eind + _KOLOM_TOLERANTIE and eind >= kop_start - _KOLOM_TOLERANTIE


def _kolomkop_boven(vorige_regel: str, start: int, eind: int) -> Anker | None:
    """Kolomkop: de aaneengesloten woorden in de regel erboven die de kolom van de waarde overlappen
    (koppen als "Totaal incl. btw" bestaan uit meerdere woorden met één spatie ertussen)."""
    woorden = [(m.start(), m.end(), m.group()) for m in _WOORD_RE.finditer(vorige_regel)]
    overlappend = [w for w in woorden if _overlapt(w[0], w[1], start, eind)]
    if not overlappend:
        return None
    reeks = [overlappend[0]]
    for w in overlappend[1:]:
        if w[0] - reeks[-1][1] <= 1:
            reeks.append(w)
        else:
            break
    ankerwoorden = tuple(w for w in (_ankerwoord(x[2]) for x in reeks) if w)
    if not ankerwoorden or not _heeft_letters(ankerwoorden):
        return None
    return Anker("kolomkop", ankerwoorden)


def _treffers(veld: str, regels: tuple[str, ...], waarde: Any) -> list[tuple[int, int, int]]:
    """(regelindex, start, eind) van elke plek waar de bevestigde waarde letterlijk in de tekst staat."""
    patroon = _waarde_re(veld)
    uit = []
    for index, regel in enumerate(regels):
        for m in patroon.finditer(regel):
            if _parse(veld, m.group("v")) == waarde:
                uit.append((index, m.start("v"), m.end("v")))
    return uit


def pas_anker_toe(anker: Anker, veld: str, regels: tuple[str, ...]) -> list[Any]:
    """Alle geparste waarden die dit anker in documentvolgorde oplevert (onparseerbare treffers
    worden overgeslagen). De aanroeper gebruikt de eerste."""
    waarde_re = _waarde_re(veld).pattern
    uit: list[Any] = []
    if anker.soort == "prefix":
        patroon = re.compile(_anker_regex(anker.woorden) + _NA_ANKER + waarde_re, re.IGNORECASE)
        for regel in regels:
            for m in patroon.finditer(regel):
                geparst = _parse(veld, m.group("v"))
                if geparst is not None:
                    uit.append(geparst)
        return uit
    if anker.soort == "vorige_regel":
        einde = re.compile(r"^[^A-Za-z0-9]*" + _anker_regex(anker.woorden) + r"[^A-Za-z0-9]*$", re.IGNORECASE)
        begin = re.compile(r"^[^A-Za-z0-9]*?" + waarde_re, re.IGNORECASE)
        for index in range(len(regels) - 1):
            if einde.search(regels[index]) is None:
                continue
            m = begin.match(regels[index + 1])
            if m is not None:
                geparst = _parse(veld, m.group("v"))
                if geparst is not None:
                    uit.append(geparst)
        return uit
    if anker.soort == "kolomkop":
        kop = re.compile(_anker_regex(anker.woorden) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        waarde_patroon = _waarde_re(veld)
        for index in range(len(regels) - 1):
            for k in kop.finditer(regels[index]):
                for m in waarde_patroon.finditer(regels[index + 1]):
                    if _overlapt(k.start(), k.end(), m.start("v"), m.end("v")):
                        geparst = _parse(veld, m.group("v"))
                        if geparst is not None:
                            uit.append(geparst)
        return uit
    return uit


# --- Referentie-vormpatroon ----------------------------------------------------------------------

_GENERIEKE_VORM = r"[A-Za-z0-9][A-Za-z0-9._/\-]*"


def _runs(waarde: str) -> list[tuple[str, str]]:
    """Runs van cijfers ("d"), letters ("a") en losse scheidingstekens (letterlijk)."""
    uit: list[tuple[str, str]] = []
    for m in re.finditer(r"\d+|[A-Za-z]+|[^A-Za-z0-9]", waarde):
        tok = m.group()
        soort = "d" if tok[0].isdigit() else ("a" if tok[0].isalpha() else tok)
        uit.append((soort, tok))
    return uit


def leer_vorm(waarden: list[str]) -> str:
    """Regex voor de referentievorm uit N bevestigde nummers: gelijke run-structuur → per run een
    klasse mét vaste lengte (als die overal gelijk is) of `+`; verschillende structuren → generiek.
    Voorbeeld: F-2026-042 / F-2026-051 → `[A-Za-z]{1}\\-\\d{4}\\-\\d{3}`."""
    structuren = [_runs(w) for w in waarden]
    if not structuren or any(len(s) != len(structuren[0]) for s in structuren):
        return _GENERIEKE_VORM
    delen: list[str] = []
    for positie in range(len(structuren[0])):
        soorten = {s[positie][0] for s in structuren}
        if len(soorten) != 1:
            return _GENERIEKE_VORM
        soort = next(iter(soorten))
        lengtes = {len(s[positie][1]) for s in structuren}
        lengte = f"{{{next(iter(lengtes))}}}" if len(lengtes) == 1 else "+"
        if soort == "d":
            delen.append(r"\d" + lengte)
        elif soort == "a":
            delen.append("[A-Za-z]" + lengte)
        else:
            delen.append(re.escape(soort))
    return "".join(delen)


# --- Leren -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BevestigdeRegel:
    netto: Decimal
    btw: Decimal
    omschrijving: str | None


@dataclass(frozen=True)
class Leerdocument:
    """Eén mens-bevestigd document: tekstlaag + de bevestigde (geboekte) kopwaarden + regels."""

    document_id: str
    tekst: Tekstlaag
    factuurnummer: str
    factuurdatum: date
    vervaldatum: date | None
    totaal_excl: Decimal
    btw_bedrag: Decimal
    totaal_incl: Decimal
    regels: tuple[BevestigdeRegel, ...] = ()

    def waarde(self, veld: str) -> Any:
        return getattr(self, veld)


@dataclass(frozen=True)
class Leerresultaat:
    definitie: dict[str, Any] | None
    reden: str | None = None


def _bevestigd_percentage(doc: Leerdocument) -> str:
    """Btw-percentage dat code uit de bevestigde totalen afleidt: 0, 21, 9 of "gemengd"."""
    if doc.btw_bedrag == 0:
        return "0"
    for label, fractie in _BEKENDE_PERCENTAGES:
        if abs(doc.totaal_excl * fractie - doc.btw_bedrag) <= _CENT:
            return str(label)
    return "gemengd"


def _sorteersleutel(anker: Anker, uniek: bool) -> tuple:
    soort_orde = {"prefix": 0, "kolomkop": 1, "vorige_regel": 2}[anker.soort]
    return (0 if uniek else 1, soort_orde, -len(anker.woorden), -sum(len(w) for w in anker.woorden), anker.woorden)


def _leer_veld(veld: str, documenten: list[Leerdocument], *, layout: bool) -> Anker | None:
    """Het beste anker dat in ÉLK document voorkomt en als eerste treffer exact de bevestigde waarde
    geeft; None als er zo geen anker is. Voorkeur: uniek in alle docs, dan prefix > kolomkop >
    vorige regel (het label direct erboven in dezelfde kolom is specifieker dan "de regel erboven
    eindigt op …"), dan het langste anker — deterministisch."""
    gedeeld: set[Anker] | None = None
    for doc in documenten:
        kandidaten: set[Anker] = set()
        for index, start, eind in _treffers(veld, doc.tekst.regels, doc.waarde(veld)):
            kandidaten |= _kandidaten_voor_treffer(doc.tekst.regels, index, start, eind, layout=layout)
        gedeeld = kandidaten if gedeeld is None else gedeeld & kandidaten
        if not gedeeld:
            return None
    assert gedeeld is not None
    geldig: list[tuple[tuple, Anker]] = []
    for anker in gedeeld:
        uniek = True
        klopt = True
        for doc in documenten:
            uitkomsten = pas_anker_toe(anker, veld, doc.tekst.regels)
            if not uitkomsten or uitkomsten[0] != doc.waarde(veld):
                klopt = False
                break
            if len(uitkomsten) != 1:
                uniek = False
        if klopt:
            geldig.append((_sorteersleutel(anker, uniek), anker))
    if not geldig:
        return None
    geldig.sort(key=lambda item: item[0])
    return geldig[0][1]


def leer_template(documenten: list[Leerdocument], *, minimum: int = 3) -> Leerresultaat:
    """Template uit N ≥ `minimum` bevestigde documenten van één crediteur. Alles-of-niets: elk
    verplicht kopveld krijgt een anker dat in álle documenten exact reproduceert, of er komt géén
    template (mét reden). Optioneel: vervaldatum "afwezig" (overal leeg), btw "nul" (overal 0 én
    incl == excl). Alle documenten moeten dezelfde tekstmodus hebben."""
    if len(documenten) < minimum:
        return Leerresultaat(None, f"te weinig bevestigde documenten ({len(documenten)} < {minimum})")
    modi = {doc.tekst.modus for doc in documenten}
    if len(modi) != 1:
        return Leerresultaat(None, "tekstlagen met verschillende extractiemodus")
    modus = next(iter(modi))
    for doc in documenten:
        if doc.totaal_excl + doc.btw_bedrag != doc.totaal_incl:
            return Leerresultaat(
                None, f"bevestigde totalen van document {doc.document_id} sluiten niet (excl + btw ≠ incl)"
            )
    layout = modus == "layout"
    velden: dict[str, dict[str, Any]] = {}
    for veld in KOPVELDEN:
        if veld == "vervaldatum" and all(doc.vervaldatum is None for doc in documenten):
            velden[veld] = {"soort": "afwezig"}
            continue
        if veld == "vervaldatum" and any(doc.vervaldatum is None for doc in documenten):
            return Leerresultaat(None, "vervaldatum wisselt tussen aanwezig en afwezig")
        if veld == "btw_bedrag" and all(doc.btw_bedrag == 0 for doc in documenten):
            velden[veld] = {"soort": "nul"}
            continue
        anker = _leer_veld(veld, documenten, layout=layout)
        if anker is None:
            return Leerresultaat(None, f"geen reproduceerbaar anker voor {veld}")
        velden[veld] = anker.als_dict()
    velden["factuurnummer"]["vorm"] = leer_vorm([doc.factuurnummer for doc in documenten])
    percentages = sorted({_bevestigd_percentage(doc) for doc in documenten})

    enkel = all(
        len(doc.regels) == 1 and doc.regels[0].netto == doc.totaal_excl and doc.regels[0].btw == doc.btw_bedrag
        for doc in documenten
    )
    omschrijvingen = {doc.regels[0].omschrijving for doc in documenten} if enkel else set()
    regel_omschrijving = next(iter(omschrijvingen)) if len(omschrijvingen) == 1 else None
    return Leerresultaat(
        {
            "versie": TEMPLATE_VERSIE,
            "tekst_modus": modus,
            "velden": velden,
            "btw_percentages": percentages,
            "regels_modus": "enkel" if enkel else "geen",
            "regel_omschrijving": regel_omschrijving,
        }
    )


# --- Toepassen -------------------------------------------------------------------------------------


class TemplateVerworpen(Exception):
    """Eén interne validatie rood → de héle template-uitkomst wordt verworpen (nooit half). De
    aanroeper markeert het template ongeldig (mét deze reden) en gaat door naar het AI-pad."""


@dataclass(frozen=True)
class TemplateRegel:
    netto: Decimal
    btw: Decimal
    omschrijving: str | None


@dataclass(frozen=True)
class TemplateUitkomst:
    factuurnummer: str
    factuurdatum: date
    vervaldatum: date | None
    totaal_excl: Decimal
    btw_bedrag: Decimal
    totaal_incl: Decimal
    btw_percentage: str
    regels: tuple[TemplateRegel, ...] = ()
    velden_bron: dict[str, str] = field(default_factory=dict)


def pas_template_toe(definitie: dict[str, Any], tekst: Tekstlaag) -> TemplateUitkomst:
    """Template op een nieuwe tekstlaag: elk veld via zijn anker (eerste treffer), dan de harde
    interne validaties. Eén rood = TemplateVerworpen mét reden."""
    if tekst.modus != definitie.get("tekst_modus"):
        raise TemplateVerworpen(f"tekstlaag in modus {tekst.modus}, template verwacht {definitie.get('tekst_modus')}")
    velden: dict[str, Any] = definitie.get("velden") or {}
    waarden: dict[str, Any] = {}
    bron: dict[str, str] = {}
    for veld in KOPVELDEN:
        regel = velden.get(veld)
        if regel is None:
            raise TemplateVerworpen(f"template kent geen regel voor {veld}")
        soort = regel.get("soort")
        if soort == "afwezig":
            waarden[veld] = None
            continue
        if soort == "nul":
            waarden[veld] = Decimal("0.00")
            bron[veld] = "template_nul"
            continue
        uitkomsten = pas_anker_toe(Anker.uit_dict(regel), veld, tekst.regels)
        if not uitkomsten:
            raise TemplateVerworpen(f"{veld} niet gevonden achter het geleerde anker")
        waarden[veld] = uitkomsten[0]
        bron[veld] = "template"

    factuurnummer = str(waarden["factuurnummer"])
    vorm = velden["factuurnummer"].get("vorm") or _GENERIEKE_VORM
    if re.fullmatch(vorm, factuurnummer) is None:
        raise TemplateVerworpen(f"factuurnummer '{factuurnummer}' voldoet niet aan het geleerde patroon")
    excl: Decimal = waarden["totaal_excl"]
    btw: Decimal = waarden["btw_bedrag"]
    incl: Decimal = waarden["totaal_incl"]
    if excl + btw != incl:
        raise TemplateVerworpen(f"excl {excl} + btw {btw} ≠ incl {incl}")
    if excl == 0 and incl == 0:
        raise TemplateVerworpen("totalen zijn nul")
    factuurdatum: date = waarden["factuurdatum"]
    vervaldatum: date | None = waarden["vervaldatum"]
    if vervaldatum is not None and vervaldatum < factuurdatum:
        raise TemplateVerworpen("vervaldatum ligt vóór de factuurdatum")
    percentage = _bevestigd_percentage(
        Leerdocument("", tekst, factuurnummer, factuurdatum, vervaldatum, excl, btw, incl)
    )
    toegestaan = [str(p) for p in definitie.get("btw_percentages") or []]
    if "gemengd" not in toegestaan and percentage not in toegestaan:
        raise TemplateVerworpen(f"btw-percentage {percentage} valt buiten de geleerde set {toegestaan}")

    regels: tuple[TemplateRegel, ...] = ()
    if definitie.get("regels_modus") == "enkel":
        regels = (TemplateRegel(netto=excl, btw=btw, omschrijving=definitie.get("regel_omschrijving")),)
    return TemplateUitkomst(
        factuurnummer=factuurnummer,
        factuurdatum=factuurdatum,
        vervaldatum=vervaldatum,
        totaal_excl=excl,
        btw_bedrag=btw,
        totaal_incl=incl,
        btw_percentage=percentage,
        regels=regels,
        velden_bron=bron,
    )


def reproduceert(definitie: dict[str, Any], doc: Leerdocument) -> bool:
    """Toets of een bestaand template de bevestigde waarden van een document exact oplevert (de
    geldigheidseis, ook ná het leren: een bevestigd document dat afwijkt maakt het template ongeldig)."""
    try:
        uitkomst = pas_template_toe(definitie, doc.tekst)
    except TemplateVerworpen:
        return False
    return (
        uitkomst.factuurnummer == doc.factuurnummer
        and uitkomst.factuurdatum == doc.factuurdatum
        and uitkomst.vervaldatum == doc.vervaldatum
        and uitkomst.totaal_excl == doc.totaal_excl
        and uitkomst.btw_bedrag == doc.btw_bedrag
        and uitkomst.totaal_incl == doc.totaal_incl
    )


# --- Crediteur-herkenning zonder AI ---------------------------------------------------------------

_BTW_IN_TEKST_RE = re.compile(r"NL\s?\d{9}\s?B\s?\d{2}", re.IGNORECASE)
_KVK_IN_TEKST_RE = re.compile(r"(?<!\d)\d{8}(?!\d)")
_IBAN_IN_TEKST_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")


@dataclass(frozen=True)
class Herkenning:
    vendor_id: Any
    soort: str  # "btw_nummer" | "kvk_nummer" | "iban" | "naam"
    waarde: str


def herken_crediteur(
    tekst: Tekstlaag,
    kandidaten: list[VendorKandidaat],
    *,
    ibans: dict[str, Any] | None = None,
) -> Herkenning | None:
    """Crediteur uit de tekstlaag met uitsluitend eigen caches: btw-nummer → KvK-nummer → IBAN →
    exacte (genormaliseerde) naam. Precies één kandidaat per stap, anders door naar de volgende stap;
    niets eenduidig = None (dan geen template, het document gaat het AI-pad)."""
    volledig = "\n".join(tekst.regels)
    btw_in_tekst = {
        g.genormaliseerd for m in _BTW_IN_TEKST_RE.finditer(volledig) if (g := valideer_btw_nummer(m.group()))
    }
    if btw_in_tekst:
        treffers = [k for k in kandidaten if k.btw_nummer and k.btw_nummer in btw_in_tekst]
        if len({k.id for k in treffers}) == 1:
            return Herkenning(treffers[0].id, "btw_nummer", treffers[0].btw_nummer or "")
    kvk_in_tekst = {n for n in (normaliseer_kvk_nummer(m.group()) for m in _KVK_IN_TEKST_RE.finditer(volledig)) if n}
    if kvk_in_tekst:
        treffers = [k for k in kandidaten if k.kvk_nummer and k.kvk_nummer in kvk_in_tekst]
        if len({k.id for k in treffers}) == 1:
            return Herkenning(treffers[0].id, "kvk_nummer", treffers[0].kvk_nummer or "")
    if ibans:
        gevonden = {
            normaliseer_iban(m.group()) for m in _IBAN_IN_TEKST_RE.finditer(volledig) if is_geldig_iban(m.group())
        }
        vendor_ids = {ibans[i] for i in gevonden if i in ibans}
        if len(vendor_ids) == 1:
            vendor_id = next(iter(vendor_ids))
            return Herkenning(vendor_id, "iban", next(i for i in gevonden if ibans.get(i) == vendor_id))
    genormaliseerd = f" {_genormaliseerd(volledig)} "
    op_naam = [
        k for k in kandidaten if k.naam and len(naam := _genormaliseerd(k.naam)) >= 5 and f" {naam} " in genormaliseerd
    ]
    if len({k.id for k in op_naam}) == 1:
        return Herkenning(op_naam[0].id, "naam", op_naam[0].naam)
    return None
