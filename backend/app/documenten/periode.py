"""Factuurperiode op weekniveau (blok 11 vervolgrun 07-09; vraag Peter: kosten op weekniveau voor
projectadministraties — ALLEEN de datalaag).

Een inkoopfactuur van een onderaannemer/verhuurder vermeldt vrijwel altijd op welke periode hij betrekking heeft
("week 34", "wk 34-35 2026", "18-08-2026 t/m 22-08-2026", "augustus 2026"). De AI leest die tekst LETTERLIJK voor
(extractieveld `periode`, sentinel-string — bugfix 31-08); deze module maakt er deterministisch ISO-weken van.
Code voor cijfers: er wordt hier niets geraden — een onherkenbare tekst is `None`, de terugval is de ISO-week van
de factuurdatum mét eigen herkomst, zodat het onderscheid "stond op de factuur" / "afgeleid" nooit verloren gaat.

Uitkomst per document: `FactuurPeriode(jaar, week_van, week_tot, herkomst, tekst)` — gepersisteerd op
`boekhouding.boekvoorstel` (migratie 0120) via het A10-prefill-/autosave-pad en de gewone PUT (mens wint, herkomst
`mens`). De ruwe tekst blijft altijd bewaard (`periode_tekst`) — niets verdwijnt stil.

Herkende vormen (hoofdletter-ongevoelig, witruimte-tolerant):
- weeknummer: "week 34", "wk 34", "wk. 34", "wk34", "weeknummer 34", "W34";
- weekbereik: "wk 34-35", "week 34 t/m 35", "weken 34 en 35", "week 34 tot 35", "week 34 tot en met 35";
- mét jaar: "week 34 2026", "week 34 van 2026", "wk 34 (2026)", "week 34, 2026", "34/2026", "2026-W34",
  "2026W34", "W34 2026", "wk 34-35 2026", "wk 34-35/2026";
- datumbereik: "18-08-2026 t/m 22-08-2026", "18/08/2026 - 22/08/2026", "2026-08-18 tot 2026-08-22",
  "18-08 t/m 22-08-2026" (begindatum zonder jaar → jaar van de einddatum); één datum → de week van die datum;
- maand: "augustus 2026", "aug 2026", "aug. 2026", "augustus" (jaar → factuurjaar) — herkomst `factuur_maand`
  (weekbereik van de maand; de aggregatie kan zo een maandfactuur anders wegen dan een weekfactuur).

Jaar-afleiding zonder jaar in de tekst (gemotiveerd): het anker is de FACTUURDATUM, niet "vandaag" — een factuur
kan alleen al gewerkte weken in rekening brengen, en een document dat pas weken later verwerkt wordt mag niet van
jaar wisselen door het verwerkingsmoment. Regel: jaar = ISO-jaar van de factuurdatum; is het weeknummer GROTER dan
de ISO-week van de factuurdatum (bv. factuur 05-01-2026 voor "week 52"), dan het vorige jaar. Zonder factuurdatum
geldt hetzelfde met vandaag als anker.

Jaargrens: een bereik dat over een ISO-jaargrens loopt (december/januari) is in één (jaar, van, tot) niet te
vangen — we houden het ISO-jaar van de BEGINDATUM (resp. de maand) en kappen `week_tot` op de laatste week van dat
jaar (resp. `week_van` op 1 als de eerste dagen nog in het vorige ISO-jaar vallen). De ruwe tekst blijft bewaard;
beslispunt Peter in BESLISSINGEN "FACTUURPERIODE WEEKNIVEAU".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

HERKOMST_FACTUUR = "factuur"
HERKOMST_FACTUUR_MAAND = "factuur_maand"
HERKOMST_AFGELEID_FACTUURDATUM = "afgeleid_van_factuurdatum"
HERKOMST_MENS = "mens"
HERKOMSTEN = (HERKOMST_FACTUUR, HERKOMST_FACTUUR_MAAND, HERKOMST_AFGELEID_FACTUURDATUM, HERKOMST_MENS)
# Herkomsten die "de factuur zegt het zelf" betekenen — triggeren de A10-autosave en het factuurmatch-signaal.
HERKOMSTEN_UIT_FACTUUR = frozenset({HERKOMST_FACTUUR, HERKOMST_FACTUUR_MAAND})


class OngeldigePeriode(ValueError):
    """Weeknummer/jaar-combinatie die niet bestaat (bv. week 53 in een 52-wekenjaar) of een leeg bereik."""


@dataclass(frozen=True)
class FactuurPeriode:
    jaar: int
    week_van: int
    week_tot: int
    herkomst: str
    # De letterlijk voorgelezen tekst van de factuur (None bij terugval/mens zonder gelezen tekst).
    tekst: str | None = None

    @property
    def weken(self) -> tuple[tuple[int, int], ...]:
        return tuple((self.jaar, w) for w in range(self.week_van, self.week_tot + 1))

    @property
    def sleutel(self) -> tuple[int, int, int]:
        return (self.jaar, self.week_van, self.week_tot)


# --- ISO-weekhulpen ---------------------------------------------------------------------------------------------


def laatste_week_van_jaar(jaar: int) -> int:
    """52 of 53 — de ISO-week waarin 28 december valt is per definitie de laatste week van het jaar."""
    return date(jaar, 12, 28).isocalendar().week


def is_geldige_week(jaar: int, week: int) -> bool:
    """Hergebruikt dezelfde ISO-logica als `app.uren.service.week_grenzen` (date.fromisocalendar)."""
    try:
        date.fromisocalendar(jaar, week, 1)
    except ValueError:
        return False
    return True


def week_van_datum(dag: date) -> tuple[int, int]:
    iso = dag.isocalendar()
    return iso.year, iso.week


def maak_periode(jaar: int, week_van: int, week_tot: int | None, *, herkomst: str, tekst: str | None) -> FactuurPeriode:
    """Gevalideerde constructie: bestaande weken, van ≤ tot (omgekeerd bereik wordt rechtgezet)."""
    if week_tot is None:
        week_tot = week_van
    if week_van > week_tot:
        week_van, week_tot = week_tot, week_van
    if not (is_geldige_week(jaar, week_van) and is_geldige_week(jaar, week_tot)):
        raise OngeldigePeriode(f"Week {week_van}–{week_tot} bestaat niet in {jaar}")
    if herkomst not in HERKOMSTEN:
        raise OngeldigePeriode(f"Onbekende herkomst {herkomst!r}")
    return FactuurPeriode(jaar=jaar, week_van=week_van, week_tot=week_tot, herkomst=herkomst, tekst=tekst)


def periode_van_datumbereik(begin: date, eind: date, *, herkomst: str, tekst: str | None) -> FactuurPeriode:
    """Weken van begin- t/m einddatum; over een ISO-jaargrens heen gekapt op het jaar van de begindatum."""
    if eind < begin:
        begin, eind = eind, begin
    jaar, week_van = week_van_datum(begin)
    eind_jaar, week_tot = week_van_datum(eind)
    if eind_jaar > jaar:
        week_tot = laatste_week_van_jaar(jaar)
    return maak_periode(jaar, week_van, week_tot, herkomst=herkomst, tekst=tekst)


def periode_van_maand(jaar: int, maand: int, *, tekst: str | None) -> FactuurPeriode:
    """Weekbereik van een kalendermaand, gekapt op het ISO-jaar `jaar` (december verliest de dagen die al in
    week 1 van het volgende jaar vallen; januari begint op week 1 ook als 1 januari nog in week 52/53 valt)."""
    eerste = date(jaar, maand, 1)
    laatste = (date(jaar + 1, 1, 1) if maand == 12 else date(jaar, maand + 1, 1)) - timedelta(days=1)
    begin_jaar, week_van = week_van_datum(eerste)
    eind_jaar, week_tot = week_van_datum(laatste)
    if begin_jaar < jaar:
        week_van = 1
    if eind_jaar > jaar:
        week_tot = laatste_week_van_jaar(jaar)
    return maak_periode(jaar, week_van, week_tot, herkomst=HERKOMST_FACTUUR_MAAND, tekst=tekst)


# --- tekst → periode ---------------------------------------------------------------------------------------------

_MAANDEN: dict[str, int] = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2,
    "maart": 3, "mrt": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "augustus": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}  # fmt: skip

_JAAR = r"(?P<jaar>20\d{2})"
_WEEK = r"(?P<van>[1-9]|[1-4]\d|5[0-3])"
_WEEK_TOT = r"(?P<tot>[1-9]|[1-4]\d|5[0-3])"
_BEREIK_SCHEIDER = r"(?:\s*(?:-|–|—|/|t/m|tm|tot en met|tot|en)\s*)"
_WEEK_LABEL = r"(?:week|weken|wk\.?|weeknummers?|weeknr\.?|w)"

# "week 34", "wk 34-35", "week 34 t/m 35 2026", "wk 34 (2026)", "week 34 van 2026", "weken 34 en 35 van 2026"
_RE_WEEK = re.compile(
    rf"^{_WEEK_LABEL}\s*{_WEEK}(?:{_BEREIK_SCHEIDER}{_WEEK_TOT})?"
    rf"(?:\s*(?:,|/|van|in|-)?\s*\(?{_JAAR}\)?)?$",
    re.IGNORECASE,
)
# "2026-W34", "2026W34", "2026-W34-35", "2026 week 34"
_RE_JAAR_WEEK = re.compile(
    rf"^{_JAAR}\s*(?:-|\s)?\s*{_WEEK_LABEL}\s*{_WEEK}(?:{_BEREIK_SCHEIDER}{_WEEK_TOT})?$",
    re.IGNORECASE,
)
# "34/2026", "34-35/2026"
_RE_WEEK_SLASH_JAAR = re.compile(rf"^{_WEEK}(?:\s*-\s*{_WEEK_TOT})?\s*/\s*{_JAAR}$")

_DATUM = (
    r"(?:(?P<{p}d>\d{{1,2}})[-/.](?P<{p}m>\d{{1,2}})(?:[-/.](?P<{p}j>\d{{4}}))?"
    r"|(?P<{p}iso>\d{{4}}-\d{{2}}-\d{{2}}))"
)
_RE_DATUMBEREIK = re.compile(
    rf"^{_DATUM.format(p='b')}(?:\s*(?:-|–|—|t/m|tm|tot en met|tot)\s*{_DATUM.format(p='e')})?$",
    re.IGNORECASE,
)
_RE_MAAND = re.compile(rf"^(?P<maand>[a-z]+)\.?(?:\s*,?\s*{_JAAR})?$", re.IGNORECASE)


def _schoon(tekst: str) -> str:
    t = " ".join(tekst.split())
    # Veelvoorkomende labels vóór de waarde zelf ("Periode: week 34", "Betreft periode wk 34").
    t = re.sub(r"^(?:betreft\s+)?(?:periode|werkperiode|factuurperiode|huurperiode)\s*[:\-]?\s*", "", t, flags=re.I)
    return t.strip(" .;,")


def _jaar_zonder_opgave(week_van: int, anker: date) -> int:
    """Jaar-afleiding (zie module-docstring): ISO-jaar van het anker; weeknummer ná de ankerweek → vorig jaar."""
    anker_jaar, anker_week = week_van_datum(anker)
    return anker_jaar - 1 if week_van > anker_week else anker_jaar


def _parse_datum(m: re.Match[str], p: str, *, jaar_terugval: int | None) -> date | None:
    iso = m.group(f"{p}iso")
    if iso:
        try:
            return date.fromisoformat(iso)
        except ValueError:
            return None
    d, mnd, j = m.group(f"{p}d"), m.group(f"{p}m"), m.group(f"{p}j")
    if d is None or mnd is None:
        return None
    jaar = int(j) if j else jaar_terugval
    if jaar is None:
        return None
    try:
        return date(jaar, int(mnd), int(d))
    except ValueError:
        return None


def normaliseer_periode(
    tekst: str | None, *, factuurdatum: date | None, vandaag: date | None = None
) -> FactuurPeriode | None:
    """Letterlijke factuurtekst → FactuurPeriode (herkomst `factuur`/`factuur_maand`), of None als de tekst
    niet eenduidig te herkennen is — dan kiest de aanroeper de terugval (`bepaal_periode`). Puur."""
    if not tekst or not tekst.strip():
        return None
    anker = factuurdatum or vandaag or date.today()
    schoon = _schoon(tekst)
    if not schoon:
        return None
    ruw = " ".join(tekst.split())
    try:
        m = _RE_WEEK.match(schoon) or _RE_JAAR_WEEK.match(schoon) or _RE_WEEK_SLASH_JAAR.match(schoon)
        if m:
            van = int(m.group("van"))
            tot = int(m.group("tot")) if m.groupdict().get("tot") else None
            jaar = int(m.group("jaar")) if m.groupdict().get("jaar") else _jaar_zonder_opgave(van, anker)
            return maak_periode(jaar, van, tot, herkomst=HERKOMST_FACTUUR, tekst=ruw)
        m = _RE_DATUMBEREIK.match(schoon)
        if m:
            eind_jaar_opgave = m.group("ej") or (m.group("eiso")[:4] if m.group("eiso") else None)
            # Begindatum zonder jaar → jaar van de einddatum, anders het factuurjaar.
            jaar_terugval = int(eind_jaar_opgave) if eind_jaar_opgave else anker.year
            begin = _parse_datum(m, "b", jaar_terugval=jaar_terugval)
            heeft_eind = bool(m.group("ed") or m.group("eiso"))
            eind = _parse_datum(m, "e", jaar_terugval=begin.year if begin else anker.year) if heeft_eind else begin
            if begin is None or eind is None:
                return None
            return periode_van_datumbereik(begin, eind, herkomst=HERKOMST_FACTUUR, tekst=ruw)
        m = _RE_MAAND.match(schoon)
        if m:
            maand = _MAANDEN.get(m.group("maand").lower())
            if maand is None:
                return None
            jaar = int(m.group("jaar")) if m.group("jaar") else anker.year
            if not m.group("jaar") and maand > anker.month:
                jaar -= 1  # zelfde motivering als bij weken: een factuur gaat over al verstreken werk
            return periode_van_maand(jaar, maand, tekst=ruw)
    except OngeldigePeriode:
        return None
    return None


def terugval_van_factuurdatum(factuurdatum: date | None, *, tekst: str | None = None) -> FactuurPeriode | None:
    """Zonder (herkenbare) periode op de factuur: de ISO-week van de factuurdatum, herkomst afgeleid — de ruwe
    tekst (indien gelezen maar onherkenbaar) blijft zichtbaar."""
    if factuurdatum is None:
        return None
    jaar, week = week_van_datum(factuurdatum)
    return FactuurPeriode(jaar=jaar, week_van=week, week_tot=week, herkomst=HERKOMST_AFGELEID_FACTUURDATUM, tekst=tekst)


def bepaal_periode(
    tekst: str | None, *, factuurdatum: date | None, vandaag: date | None = None
) -> FactuurPeriode | None:
    """De automatische stand voor een document: voorgelezen tekst herkend → die; anders de factuurdatum-week;
    zonder factuurdatum → None (geen gok)."""
    herkend = normaliseer_periode(tekst, factuurdatum=factuurdatum, vandaag=vandaag)
    if herkend is not None:
        return herkend
    return terugval_van_factuurdatum(factuurdatum, tekst=(" ".join(tekst.split()) if tekst and tekst.strip() else None))


def label(periode: FactuurPeriode) -> str:
    """Weergavetekst, identiek aan de frontend-chip: "wk 34 · 2026" / "wk 34–35 · 2026"."""
    if periode.week_van == periode.week_tot:
        return f"wk {periode.week_van} · {periode.jaar}"
    return f"wk {periode.week_van}–{periode.week_tot} · {periode.jaar}"
