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
    periode: date | None
    nieuwe_verdeling: list[VerdeelDeel]
    signaal: bool


@dataclass(frozen=True)
class ProjectverdelingData:
    """Wat het boekvoorstel over de verdeling weet — voor UI, checks én de backend-adapters."""

    status: str
    basisbedrag: Decimal | None
    vaste_regels: list[VasteRegel]
    pro_rato: bool
    pro_rato_periode: date | None
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

    @property
    def actief(self) -> bool:
        """Draagt het document een verdeling die bij het boeken meegaat (voorstel óf bevroren)?"""
        return self.status in (STATUS_VOORSTEL, STATUS_GEBOEKT) and (bool(self.vaste_regels) or self.pro_rato)

    @property
    def dekt_regels_zonder_project(self) -> bool:
        """Een COMPLETE verdeling geeft élke regel zonder eigen project een project — de harde check
        "project verplicht" telt zo'n regel dan als 'heeft project'."""
        return self.actief and self.compleet


def default_periode(vandaag: date) -> date:
    """Vorige afgesloten kalendermaand: de eerste dag ervan (①)."""
    eerste = vandaag.replace(day=1)
    vorige_laatste = eerste.fromordinal(eerste.toordinal() - 1)
    return vorige_laatste.replace(day=1)


def periode_eind(periode: date) -> date:
    """Exclusieve bovengrens: de eerste dag van de volgende maand."""
    if periode.month == 12:
        return date(periode.year + 1, 1, 1)
    return date(periode.year, periode.month + 1, 1)


def periode_label(periode: date) -> str:
    maanden = (
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
    return f"{maanden[periode.month - 1]} {periode.year}"


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
    periode: date | None,
    omzetstanden: list[Omzetstand],
    omzet_cache_leeg: bool = False,
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
    if periode is None:
        return Berekening(restant, vast, False, "Kies de omzetmaand voor de pro-rato-verdeling")
    standen = [s for s in omzetstanden if s.omzet > 0]
    if not standen:
        if omzet_cache_leeg:
            reden = (
                f"Geen omzetcijfers bekend voor {periode_label(periode)} — ververs de projectcijfers (⟳) of vul "
                "vaste regels in"
            )
        else:
            reden = f"Geen omzet in {periode_label(periode)} — vul vaste regels in of kies een andere maand"
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
