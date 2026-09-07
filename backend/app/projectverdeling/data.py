"""Pure geldlogica van de projectverdeling — geen I/O, geen sessies, 1-op-1 unit-testbaar (werkwijze:
tests op geldlogica vóór al het andere; kernprincipe 2 "code voor cijfers").

Model (mockup blok 1, ontwerpnotities ②③⑤):
- basisbedrag = Σ netto van de boekvoorstelregels ZONDER eigen project (regels mét een project houden dat);
- vaste regels (project + bedrag excl.) gaan vóór; restant = basisbedrag − Σvast → pro rato over de
  projecten mét omzet in de gekozen kalendermaand (gewicht = omzet), grootste-rest-centen, som exact;
- restant met het verkeerde teken (meer vast verdeeld dan het basisbedrag) = blokkerend; restant 0 = geen
  pro rato nodig (alleen vaste regels);
- uitvoering per backend: RLZ splitst élke regel in N regels (netto én btw per deel via dezelfde motor,
  sluitend op de regel), Odoo krijgt één regel mét `analytic_distribution` = percentages op 2 decimalen die
  exact op 100 sommen.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.doorbelasting.verdeelhulp import VerdeelFout, verdeel_naar_gewicht

CENT = Decimal("0.01")
_AANDEEL = Decimal("0.000001")
_PCT = Decimal("0.01")

STATUS_VOORSTEL = "voorstel"
STATUS_GEBOEKT = "geboekt"
STATUS_VERVALLEN = "vervallen"

WIJZE_VAST = "vast"
WIJZE_PRO_RATO = "pro_rato"


class ProjectverdelingFout(ValueError):
    """Ongeldige invoer (dubbel project in de vaste regels, bedrag zonder cent-vorm, …)."""


@dataclass(frozen=True)
class VasteRegel:
    project_id: uuid.UUID
    bedrag: Decimal
    hint: str | None = None
    project_naam: str | None = None


@dataclass(frozen=True)
class Omzetstand:
    """Geboekte verkoopomzet van één project in de periode (snapshot-eenheid, ①)."""

    project_id: uuid.UUID
    omzet: Decimal
    project_naam: str | None = None


@dataclass(frozen=True)
class VerdeelDeel:
    project_id: uuid.UUID
    wijze: str  # vast | pro_rato
    bedrag: Decimal
    aandeel: Decimal | None = None  # fractie van het pro-rato-restant (6 dec), None bij vast
    omzet: Decimal | None = None  # de gebruikte omzetstand, None bij vast
    project_naam: str | None = None


@dataclass(frozen=True)
class HercontroleInfo:
    op: object  # datetime — bewust niet getypeerd op tz om de pure laag DB-vrij te houden
    afwijking_pct: Decimal | None
    drempel_pct: Decimal
    periode: Periode | None
    nieuwe_verdeling: list[VerdeelDeel]
    signaal: bool
    #: peildatum van de herberekening (voor het dekkingslabel van een jaarperiode: "2026 (t/m augustus)")
    peildatum: date | None = None


@dataclass(frozen=True)
class ProjectverdelingData:
    """Wat het boekvoorstel over de verdeling weet — voor UI, checks én de backend-adapters."""

    status: str
    basisbedrag: Decimal | None
    vaste_regels: list[VasteRegel]
    pro_rato: bool
    pro_rato_periode: Periode | None
    pro_rato_bedrag: Decimal | None
    delen: list[VerdeelDeel]
    omzetstanden: list[Omzetstand]
    compleet: bool
    blokkade: str | None
    opgeslagen: bool
    prefill: bool = False
    hercontrole: HercontroleInfo | None = None
    boek_cyclus: int | None = None
    omzet_cache_leeg: bool = False
    aantal_projecten_met_omzet: int = field(default=0)
    #: peildatum van de omzetstand (live = vandaag, bevroren = boekmoment) — bepaalt de dekking van een jaarperiode
    pro_rato_peildatum: date | None = None

    @property
    def pro_rato_periode_label(self) -> str | None:
        if self.pro_rato_periode is None:
            return None
        return periode_label(self.pro_rato_periode, self.pro_rato_peildatum)

    @property
    def actief(self) -> bool:
        """Draagt het document een verdeling die bij het boeken meegaat (voorstel óf bevroren)?"""
        return self.status in (STATUS_VOORSTEL, STATUS_GEBOEKT) and (bool(self.vaste_regels) or self.pro_rato)

    @property
    def dekt_regels_zonder_project(self) -> bool:
        """Een COMPLETE verdeling geeft élke regel zonder eigen project een project — de harde check
        "project verplicht" telt zo'n regel dan als 'heeft project'."""
        return self.actief and self.compleet


SOORT_MAAND = "maand"
SOORT_JAAR = "jaar"

_PERIODE_CODE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-01)?)?$")

MAANDEN = (
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
)


class PeriodeFout(ProjectverdelingFout):
    """Ongeldige omzetperiode (vorm, maand 13, jaar in de toekomst, jaar zonder afgesloten maand)."""


@dataclass(frozen=True, order=True)
class Periode:
    """De omzetperiode van de pro-rato-weging (①, uitgebreid met "heel jaar" — D4 07-09, notitie ⑩).

    - soort `maand`: één kalendermaand, `start` = de eerste dag ervan; code "YYYY-MM".
    - soort `jaar`: de AFGESLOTEN maanden van een kalenderjaar (huidig óf vorig jaar), `start` = 1 januari;
      code "YYYY". Afgesloten = volledig verstreken t.o.v. de peildatum (`vandaag`): voor het lopende jaar
      loopt de dekking t/m de vorige maand, voor een verstreken jaar alle twaalf. De hercontrole rekent tegen
      de dan actuele jaarstand — er komen maanden bij, de verschuiving wordt zichtbaar (zelfde drempel).
    Opslag: `pro_rato_periode` (date = start) + `pro_rato_soort` (migratie 0119)."""

    start: date
    soort: str = SOORT_MAAND

    @property
    def is_jaar(self) -> bool:
        return self.soort == SOORT_JAAR

    @property
    def code(self) -> str:
        return f"{self.start.year:04d}" if self.is_jaar else f"{self.start.year:04d}-{self.start.month:02d}"

    @classmethod
    def maand(cls, eerste_dag: date) -> Periode:
        return cls(start=eerste_dag.replace(day=1), soort=SOORT_MAAND)

    @classmethod
    def jaar(cls, jaar: int) -> Periode:
        return cls(start=date(jaar, 1, 1), soort=SOORT_JAAR)

    @classmethod
    def parse(cls, code: str) -> Periode:
        """"YYYY" → heel jaar, "YYYY-MM" (ook de oude vorm "YYYY-MM-01") → maand; anders PeriodeFout."""
        m = _PERIODE_CODE.match(code.strip()) if isinstance(code, str) else None
        if m is None:
            raise PeriodeFout("Omzetperiode hoort de vorm JJJJ-MM (maand) of JJJJ (heel jaar) te hebben")
        jaar = int(m.group(1))
        if m.group(2) is None:
            return cls.jaar(jaar)
        maand = int(m.group(2))
        if not 1 <= maand <= 12:
            raise PeriodeFout(f"Omzetmaand {code} bestaat niet (maand 01–12)")
        return cls.maand(date(jaar, maand, 1))

    @classmethod
    def uit_opslag(cls, start: date | None, soort: str | None) -> Periode | None:
        if start is None:
            return None
        return cls(start=start.replace(day=1), soort=SOORT_JAAR if soort == SOORT_JAAR else SOORT_MAAND)


def als_periode(waarde: Periode | date | str | None) -> Periode | None:
    """Normalisatie aan de servicegrens: een `date` (oude aanroepen/tests) = die kalendermaand, een string = code."""
    if waarde is None or isinstance(waarde, Periode):
        return waarde
    if isinstance(waarde, date):
        if waarde.day != 1:
            raise PeriodeFout("De omzetmaand hoort de eerste dag van een kalendermaand te zijn")
        return Periode.maand(waarde)
    return Periode.parse(waarde)


def default_periode(vandaag: date) -> Periode:
    """Vorige afgesloten kalendermaand (①)."""
    eerste = vandaag.replace(day=1)
    vorige_laatste = eerste.fromordinal(eerste.toordinal() - 1)
    return Periode.maand(vorige_laatste.replace(day=1))


def _volgende_maand(eerste_dag: date) -> date:
    if eerste_dag.month == 12:
        return date(eerste_dag.year + 1, 1, 1)
    return date(eerste_dag.year, eerste_dag.month + 1, 1)


def periode_eind(periode: Periode | date, vandaag: date | None = None) -> date:
    """Exclusieve bovengrens van de omzetselectie. Maand: de eerste dag van de volgende maand. Jaar: 1 januari
    van het volgende jaar, maar nooit verder dan de eerste dag van de lopende maand (alleen AFGESLOTEN maanden
    tellen) — voor het lopende jaar dus t/m de vorige maand."""
    periode = als_periode(periode)
    assert periode is not None
    if not periode.is_jaar:
        return _volgende_maand(periode.start)
    vandaag = vandaag or date.today()
    volledig = date(periode.start.year + 1, 1, 1)
    return min(volledig, max(vandaag.replace(day=1), periode.start))


def laatste_afgesloten_maand(periode: Periode, vandaag: date | None = None) -> int:
    """Voor een jaarperiode: nummer (1–12) van de laatste maand die meetelt; 0 = nog geen afgesloten maand."""
    eind = periode_eind(periode, vandaag)
    if eind <= periode.start:
        return 0
    laatste = eind.fromordinal(eind.toordinal() - 1)
    return laatste.month


def valideer_periode(periode: Periode, vandaag: date) -> None:
    """Server-side poort (422): een jaar in de toekomst óf zonder ook maar één afgesloten maand is geen bruikbare
    omzetperiode; een maand die nog niet begonnen is evenmin."""
    if periode.is_jaar:
        if periode.start.year > vandaag.year:
            raise PeriodeFout(f"Jaar {periode.start.year} ligt in de toekomst — kies het huidige of vorige jaar")
        if laatste_afgesloten_maand(periode, vandaag) == 0:
            raise PeriodeFout(f"Jaar {periode.start.year} heeft nog geen afgesloten maand — kies het vorige jaar")
        return
    if periode.start > vandaag:
        raise PeriodeFout(f"Omzetmaand {periode_label(periode)} ligt in de toekomst")


def periode_label(periode: Periode | date | None, vandaag: date | None = None) -> str:
    """"juli 2026" · jaar: "2026 (t/m augustus)" zolang het jaar loopt op de peildatum, anders "2025"."""
    periode = als_periode(periode)
    if periode is None:
        return ""
    if not periode.is_jaar:
        return f"{MAANDEN[periode.start.month - 1]} {periode.start.year}"
    jaar = periode.start.year
    if vandaag is None or vandaag.year != jaar:
        return f"{jaar}"
    laatste = laatste_afgesloten_maand(periode, vandaag)
    if laatste == 0:
        return f"{jaar} (nog geen afgesloten maand)"
    return f"{jaar} (t/m {MAANDEN[laatste - 1]})"


def _cent(bedrag: Decimal) -> Decimal:
    return bedrag.quantize(CENT, rounding=ROUND_HALF_UP)


def basisbedrag_van(regels: list[tuple[uuid.UUID | None, Decimal | None]]) -> Decimal | None:
    """Σ netto van de regels zonder eigen project; None zodra één van die regels geen bedrag heeft
    (nooit een gedeeltelijke som — zelfde regel als de samengevoegde regel in boekvoorstel.py)."""
    zonder_project = [netto for project_id, netto in regels if project_id is None]
    if not zonder_project:
        return Decimal("0.00")
    if any(netto is None for netto in zonder_project):
        return None
    return _cent(sum((n for n in zonder_project if n is not None), Decimal(0)))


def restant_van(basisbedrag: Decimal, vaste_regels: list[VasteRegel]) -> Decimal:
    return _cent(basisbedrag - sum((r.bedrag for r in vaste_regels), Decimal(0)))


def restant_ongeldig(basisbedrag: Decimal, restant: Decimal) -> bool:
    """Meer vast verdeeld dan het basisbedrag: bij een positief basisbedrag een negatief restant, bij een
    creditnota (negatief basisbedrag) een positief restant."""
    if basisbedrag >= 0:
        return restant < 0
    return restant > 0


def verdeel_pro_rato(restant: Decimal, omzetstanden: list[Omzetstand]) -> list[VerdeelDeel]:
    """Grootste-rest over de omzet als gewicht (②): som exact het restant, ook bij een negatief restant
    (creditnota). Alleen standen met omzet > 0 tellen mee."""
    standen = [s for s in omzetstanden if s.omzet > 0]
    if not standen:
        raise VerdeelFout("Geen projecten mét omzet in de periode")
    gewichten = [s.omzet for s in standen]
    totaal = sum(gewichten, Decimal(0))
    delen = verdeel_naar_gewicht(_cent(restant), gewichten)
    return [
        VerdeelDeel(
            project_id=s.project_id,
            wijze=WIJZE_PRO_RATO,
            bedrag=deel,
            aandeel=(s.omzet / totaal).quantize(_AANDEEL, rounding=ROUND_HALF_UP),
            omzet=s.omzet,
            project_naam=s.project_naam,
        )
        for s, deel in zip(standen, delen, strict=True)
    ]


def valideer_vaste_regels(vaste_regels: list[VasteRegel]) -> None:
    if len({r.project_id for r in vaste_regels}) != len(vaste_regels):
        raise ProjectverdelingFout("Een project staat twee keer als vaste regel — voeg de bedragen samen")
    for r in vaste_regels:
        if r.bedrag != _cent(r.bedrag):
            raise ProjectverdelingFout("Bedragen van vaste regels in hele centen")


@dataclass(frozen=True)
class Berekening:
    restant: Decimal | None
    delen: list[VerdeelDeel]
    compleet: bool
    blokkade: str | None


def bereken(
    *,
    basisbedrag: Decimal | None,
    vaste_regels: list[VasteRegel],
    pro_rato: bool,
    periode: Periode | date | None,
    omzetstanden: list[Omzetstand],
    omzet_cache_leeg: bool = False,
    vandaag: date | None = None,
) -> Berekening:
    """Eén deterministische berekening voor UI (preview), checks (blokkade) en adapters (delen).
    De blokkade is de ene zin onder de tabel (UX-norm); `compleet` = alle regels zonder project krijgen
    een project en de balk sluit op exact 100 %."""
    valideer_vaste_regels(vaste_regels)
    vast = [
        VerdeelDeel(project_id=r.project_id, wijze=WIJZE_VAST, bedrag=r.bedrag, project_naam=r.project_naam)
        for r in vaste_regels
    ]
    if basisbedrag is None:
        return Berekening(None, vast, False, "Regelbedragen ontbreken — vul eerst de boekingsregels in")
    restant = restant_van(basisbedrag, vaste_regels)
    if restant_ongeldig(basisbedrag, restant):
        te_veel = abs(restant)
        return Berekening(
            restant, vast, False, f"€ {te_veel:.2f} meer vast verdeeld dan het bedrag excl. — verlaag een vaste regel"
        )
    if restant == 0:
        return Berekening(restant, vast, True, None)
    if not pro_rato:
        return Berekening(
            restant,
            vast,
            False,
            f"€ {restant:.2f} nog niet verdeeld — voeg een vaste regel toe of zet 'pro rato omzet' aan",
        )
    periode = als_periode(periode)
    if periode is None:
        return Berekening(restant, vast, False, "Kies de omzetperiode (maand of heel jaar) voor de pro-rato-verdeling")
    standen = [s for s in omzetstanden if s.omzet > 0]
    if not standen:
        label = periode_label(periode, vandaag)
        if omzet_cache_leeg:
            reden = f"Geen omzetcijfers bekend voor {label} — ververs de projectcijfers (⟳) of vul vaste regels in"
        else:
            reden = f"Geen omzet in {label} — vul vaste regels in of kies een andere periode"
        return Berekening(restant, vast, False, reden)
    return Berekening(restant, [*vast, *verdeel_pro_rato(restant, standen)], True, None)


def gewichten_per_project(delen: list[VerdeelDeel]) -> list[tuple[uuid.UUID, Decimal]]:
    """Totaal per project (vast + pro rato samengevoegd), volgorde van eerste voorkomen; delen van € 0,00
    vallen weg (gewicht moet > 0 zijn). Gewicht = |bedrag| zodat een creditnota dezelfde verhouding houdt."""
    totalen: dict[uuid.UUID, Decimal] = {}
    for deel in delen:
        totalen[deel.project_id] = totalen.get(deel.project_id, Decimal(0)) + deel.bedrag
    return [(pid, abs(bedrag)) for pid, bedrag in totalen.items() if bedrag != 0]


@dataclass(frozen=True)
class RegelDeel:
    project_id: uuid.UUID
    netto: Decimal
    btw: Decimal


def splits_regel(netto: Decimal, btw: Decimal | None, gewichten: list[tuple[uuid.UUID, Decimal]]) -> list[RegelDeel]:
    """RLZ-vorm (⑤): één boekvoorstelregel → N regels met dezelfde GB/btw-code, netto én btw per deel via
    grootste-rest over de projectgewichten — beide sommen sluiten exact op de regel, er raakt nooit een
    cent kwijt."""
    if not gewichten:
        raise VerdeelFout("Geen projectgewichten om de regel over te splitsen")
    ids = [pid for pid, _ in gewichten]
    w = [g for _, g in gewichten]
    netto_delen = verdeel_naar_gewicht(_cent(netto), w)
    btw_delen = verdeel_naar_gewicht(_cent(btw or Decimal(0)), w) if btw else [Decimal("0.00")] * len(w)
    return [RegelDeel(pid, n, b) for pid, n, b in zip(ids, netto_delen, btw_delen, strict=True)]


def analytic_percentages(gewichten: list[tuple[uuid.UUID, Decimal]]) -> list[tuple[uuid.UUID, Decimal]]:
    """Odoo-vorm (⑤): percentages op 2 decimalen die EXACT op 100,00 sommen — grootste-rest op honderdsten
    van een procent (100,00 'centen' over de gewichten)."""
    if not gewichten:
        raise VerdeelFout("Geen projectgewichten voor de analytic distribution")
    delen = verdeel_naar_gewicht(Decimal("100.00"), [g for _, g in gewichten])
    return [(pid, pct.quantize(_PCT)) for (pid, _), pct in zip(gewichten, delen, strict=True)]


def afwijking_pct(oud: list[VerdeelDeel], nieuw: list[VerdeelDeel], restant: Decimal) -> Decimal:
    """Hercontrole (⑥): max |deel_nieuw − deel_oud| over de pro-rato-projecten, als % van het restant."""
    if restant == 0:
        return Decimal("0.00")
    oud_per = {d.project_id: d.bedrag for d in oud if d.wijze == WIJZE_PRO_RATO}
    nieuw_per = {d.project_id: d.bedrag for d in nieuw if d.wijze == WIJZE_PRO_RATO}
    grootste = Decimal(0)
    for pid in set(oud_per) | set(nieuw_per):
        verschil = abs(nieuw_per.get(pid, Decimal(0)) - oud_per.get(pid, Decimal(0)))
        grootste = max(grootste, verschil)
    return (grootste / abs(restant) * 100).quantize(_PCT, rounding=ROUND_HALF_UP)


# --- JSON (de JSONB-kolommen) ---------------------------------------------------------------------


def vaste_regels_naar_json(regels: list[VasteRegel]) -> list[dict]:
    return [{"project_id": str(r.project_id), "bedrag": str(r.bedrag), "hint": r.hint} for r in regels]


def vaste_regels_uit_json(rijen: object) -> list[VasteRegel]:
    if not isinstance(rijen, list):
        return []
    return [
        VasteRegel(project_id=uuid.UUID(r["project_id"]), bedrag=Decimal(r["bedrag"]), hint=r.get("hint"))
        for r in rijen
        if isinstance(r, dict) and r.get("project_id") and r.get("bedrag") is not None
    ]


def delen_naar_json(delen: list[VerdeelDeel]) -> list[dict]:
    return [
        {
            "project_id": str(d.project_id),
            "wijze": d.wijze,
            "bedrag": str(d.bedrag),
            "aandeel": str(d.aandeel) if d.aandeel is not None else None,
            "omzet": str(d.omzet) if d.omzet is not None else None,
        }
        for d in delen
    ]


def delen_uit_json(rijen: object) -> list[VerdeelDeel]:
    if not isinstance(rijen, list):
        return []
    return [
        VerdeelDeel(
            project_id=uuid.UUID(r["project_id"]),
            wijze=r.get("wijze") or WIJZE_PRO_RATO,
            bedrag=Decimal(r["bedrag"]),
            aandeel=Decimal(r["aandeel"]) if r.get("aandeel") is not None else None,
            omzet=Decimal(r["omzet"]) if r.get("omzet") is not None else None,
        )
        for r in rijen
        if isinstance(r, dict) and r.get("project_id") and r.get("bedrag") is not None
    ]


def omzetstanden_naar_json(standen: list[Omzetstand]) -> list[dict]:
    return [{"project_id": str(s.project_id), "omzet": str(s.omzet), "naam": s.project_naam} for s in standen]


def omzetstanden_uit_json(rijen: object) -> list[Omzetstand]:
    if not isinstance(rijen, list):
        return []
    return [
        Omzetstand(project_id=uuid.UUID(r["project_id"]), omzet=Decimal(r["omzet"]), project_naam=r.get("naam"))
        for r in rijen
        if isinstance(r, dict) and r.get("project_id") and r.get("omzet") is not None
    ]
