"""Inzicht › Projecten — KANTOORBREED lijstpatroon + projectdetail-verrijking (fixrun 07-09 blok C5;
mockup `inzicht-kantoorbreed.html` ①②⑨ = bouwnorm, kernprincipe 7).

Eén rij = één ACTIEF project (project_cache, niet verdwenen) mét vier status-chips, allemaal uit de
bestaande caches/tabellen — géén RLZ-/Odoo-calls, géén AI:

- resultaat      : verwachte marge-% = (baten geboekt + goedgekeurd meerwerk − kosten geboekt − uren
                   onderweg) / baten — exact de definitie van `cijfers.bereken_project_cijfers`, maar in
                   GEBATCHTE queries per administratie (grouped sums over project_regel_cache, meerwerk,
                   weekstaat/weekstaat_dag) i.p.v. per project; de cijfers sluiten dus op het detail;
- verplichtingen : Σ verbruikt / Σ goedgekeurd over de lopende (goedgekeurde, niet vervallen)
                   verplichtingen van het project + "overschreden" zodra één verplichting erboven zit;
- weekstaten     : geplande (persoon, week) in het VERLEDEN zonder ingediende/goedgekeurde weekstaat
                   ("wk N ontbreekt", actieve afmeldingen tellen niet) + ingediende staten die op keuring
                   wachten ("te keuren"); alleen voor administraties mét de uren-opt-in;
- m²             : Σ m² uit goedgekeurde weekstaten t.o.v. contract-m² (specificatie).

Scope = `mijn_administraties(actor)` (Beheerder = alle actieve), per administratie gelezen in
`scoped_session(aid, actor_id=…)` — RLS blijft de waarheid (RLS-les 25-08). Aggregeren, zoeken,
facetten (administratie + status — filter, nooit poort), urgentie-sortering (meeste/zwaarste signalen
bovenaan) en paginering (25) in Python. Klik = het bestaande projectdetail
(`/projecten/{administratie}/{project}`).

De detail-verrijking (`detail_verrijking`) hergebruikt dezelfde batch-helpers voor één project:
verplichtingen mét verbruiksstand (VerbruiksBalk-patroon) en de weekstaten-/planningstand per week
(laatste `WEKEN_IN_DETAIL` weken)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentStatus
from app.projecten.cijfers import _tarief_voor
from app.projecten.models import ProjectRegelCache, ProjectRegelSoort
from app.sync.models import ProjectCache, VendorCache
from app.uren.models import (
    Meerwerk,
    MeerwerkStatus,
    PlanningDagdeel,
    PlanningSignaalAfhandeling,
    PlanningSignaalSoort,
    PlanningToewijzing,
    ProjectSpecificatie,
    Weekstaat,
    WeekstaatDag,
    WeekstaatStatus,
)
from app.verplichting import match as match_motor
from app.verplichting.models import Verplichting
from app.verplichting.service import open_facturen_per_verplichting

PER_PAGINA = 25
#: Status-facet: 'alle' (default — het is een vindbaarheidslijst, de urgentie zit in de sortering),
#: 'signaal' (≥ 1 signaal), één facet per signaalsoort, 'op_schema' (geen enkel signaal).
STATUS_FACETTEN = (
    "alle",
    "signaal",
    "verplichting_overschreden",
    "marge_negatief",
    "weekstaat_ontbreekt",
    "te_keuren",
    "op_schema",
)
#: Aantal weken (huidige + voorgaande) in de detail-stand "Weekstaten & planning".
WEKEN_IN_DETAIL = 6
_INGEDIEND_OF_BETER = (WeekstaatStatus.INGEDIEND.value, WeekstaatStatus.GOEDGEKEURD.value)
_HEEL = Decimal("1")
_HALF = Decimal("0.5")


class ProjectenKantoorbreedFout(Exception):
    """Fail-loud richting de router (422)."""


# --- data --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultaatChip:
    baten: Decimal  # geboekt + goedgekeurd meerwerk (onderweg)
    kosten: Decimal  # geboekt + uren onderweg (mét tarief)
    marge: Decimal
    marge_pct: Decimal | None  # None zonder baten
    onbepaalbaar_uren: Decimal  # goedgekeurde onverrekende uren zónder tarief (oranje, nooit gokken)
    heeft_cijfers: bool  # False = nog geen regel, meerwerk of staat → chip "geen cijfers"


@dataclass(frozen=True)
class VerplichtingenChip:
    aantal: int  # lopende (goedgekeurde, niet vervallen) verplichtingen
    goedgekeurd_excl: Decimal
    verbruikt_excl: Decimal
    percentage: int | None
    overschreden: int  # aantal verplichtingen boven hun goedgekeurde bedrag


@dataclass(frozen=True)
class WeekstatenChip:
    van_toepassing: bool  # False = administratie zonder uren-opt-in
    ontbrekend: int  # geplande (persoon, week) in het verleden zonder ingediende staat
    oudste_ontbrekende_week: tuple[int, int] | None
    te_keuren: int  # ingediende staten die op keuring wachten
    concept: int  # nog niet ingediende staten (concept/corrigeren)


@dataclass(frozen=True)
class M2Chip:
    gebouwd_m2: Decimal
    contract_m2: Decimal | None
    percentage: int | None
    doorlopende_huur: bool


@dataclass(frozen=True)
class Rij:
    administratie_id: uuid.UUID
    administratie_naam: str
    project_id: uuid.UUID
    naam: str | None
    opdrachtgever: str | None
    werknummer_opdrachtgever: str | None
    looptijd_tot: date | None
    resultaat: ResultaatChip
    verplichtingen: VerplichtingenChip
    weekstaten: WeekstatenChip
    m2: M2Chip
    signalen: tuple[str, ...]  # subset van STATUS_FACETTEN[2:-1], zwaarste eerst
    urgentie: int  # hoger = urgenter (sorteersleutel)

    @property
    def zoektekst(self) -> str:
        return " ".join(
            filter(None, (self.naam, self.opdrachtgever, self.werknummer_opdrachtgever, self.administratie_naam))
        ).lower()


@dataclass(frozen=True)
class AdministratieFacet:
    administratie_id: uuid.UUID
    naam: str
    aantal: int


@dataclass(frozen=True)
class Tellers:
    projecten: int
    administraties: int  # administraties mét ≥ 1 actief project
    met_signaal: int
    verplichting_overschreden: int
    marge_negatief: int
    weekstaat_ontbreekt: int
    te_keuren: int


@dataclass(frozen=True)
class Lijst:
    rijen: list[Rij]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: Tellers
    facetten_status: dict[str, int]
    facetten_administraties: list[AdministratieFacet]


# --- detail-verrijking -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectVerplichting:
    document_id: uuid.UUID
    offertenummer: str | None
    soort_label: str | None
    leverancier_naam: str | None
    omschrijving: str | None
    goedgekeurd_excl: Decimal | None
    verbruikt_excl: Decimal
    percentage: int | None
    over_excl: Decimal | None
    geldig_tot: date | None
    status: str  # lopend | overschreden | vervallen
    open_facturen_aantal: int = 0
    open_facturen_excl: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class WeekStand:
    jaar: int
    weeknummer: int
    maandag: date
    gepland_personen: int
    gepland_dagen: Decimal
    concept: int
    ingediend: int
    goedgekeurd: int
    corrigeren: int
    ontbrekend: int  # geplande personen zonder ingediende/goedgekeurde staat (alleen verleden weken)
    afgemeld: int


@dataclass(frozen=True)
class WeekstatenStand:
    van_toepassing: bool
    weken: list[WeekStand] = field(default_factory=list)  # nieuwste eerst
    ontbrekend_totaal: int = 0  # over álle verleden weken (ook buiten de detail-weken)
    te_keuren_totaal: int = 0
    oudste_ontbrekende_week: tuple[int, int] | None = None


@dataclass(frozen=True)
class DetailVerrijking:
    verplichtingen: list[ProjectVerplichting]
    weekstaten: WeekstatenStand


# --- helpers -----------------------------------------------------------------------------------------


def _week_sleutel(d: date) -> tuple[int, int]:
    c = d.isocalendar()
    return (c[0], c[1])


def _maandag(jaar: int, week: int) -> date:
    return date.fromisocalendar(jaar, week, 1)


def _pct(deel: Decimal, totaal: Decimal | None) -> int | None:
    if totaal is None or totaal == 0:
        return None
    return int((deel / totaal * 100).to_integral_value(rounding="ROUND_HALF_UP"))


def _resultaat_per_project(
    session: Session, aid: uuid.UUID, project_ids: set[uuid.UUID]
) -> dict[uuid.UUID, ResultaatChip]:
    """Gebatchte tegenhanger van `cijfers.bereken_project_cijfers` (zelfde definitie van baten, kosten,
    onderweg en onbepaalbaar) — vier grouped queries per administratie i.p.v. N per project."""
    if not project_ids:
        return {}
    baten: dict[uuid.UUID, Decimal] = {}
    kosten: dict[uuid.UUID, Decimal] = {}
    for project_id, soort, som in session.execute(
        select(ProjectRegelCache.project_id, ProjectRegelCache.soort, func.sum(ProjectRegelCache.netto_bedrag))
        .where(
            ProjectRegelCache.administratie_id == aid,
            ProjectRegelCache.project_id.in_(project_ids),
            ProjectRegelCache.verdwenen_uit_bron_op.is_(None),
        )
        .group_by(ProjectRegelCache.project_id, ProjectRegelCache.soort)
    ):
        doel = baten if soort == ProjectRegelSoort.VERKOOP.value else kosten
        doel[project_id] = doel.get(project_id, Decimal("0")) + Decimal(som)
    meerwerk = {
        pid: Decimal(som)
        for pid, som in session.execute(
            select(Meerwerk.project_id, func.sum(Meerwerk.bedrag))
            .where(
                Meerwerk.administratie_id == aid,
                Meerwerk.project_id.in_(project_ids),
                Meerwerk.status == MeerwerkStatus.GOEDGEKEURD.value,
            )
            .group_by(Meerwerk.project_id)
        )
    }
    onderweg_bedrag: dict[uuid.UUID, Decimal] = {}
    onbepaalbaar: dict[uuid.UUID, Decimal] = {}
    tarief_cache: dict[uuid.UUID, Decimal | None] = {}
    for project_id, gebruiker_id, uren in session.execute(
        select(Weekstaat.project_id, Weekstaat.gebruiker_id, func.coalesce(func.sum(WeekstaatDag.uren), 0))
        .join(WeekstaatDag, WeekstaatDag.weekstaat_id == Weekstaat.id)
        .where(
            Weekstaat.administratie_id == aid,
            Weekstaat.project_id.in_(project_ids),
            Weekstaat.status == WeekstaatStatus.GOEDGEKEURD.value,
            Weekstaat.verrekend_met_document_id.is_(None),
        )
        .group_by(Weekstaat.project_id, Weekstaat.gebruiker_id)
    ):
        uren = Decimal(uren)
        if uren == 0:
            continue
        if gebruiker_id not in tarief_cache:
            tarief_cache[gebruiker_id] = _tarief_voor(session, administratie_id=aid, gebruiker_id=gebruiker_id)
        tarief = tarief_cache[gebruiker_id]
        if tarief is None:
            onbepaalbaar[project_id] = onbepaalbaar.get(project_id, Decimal("0")) + uren
        else:
            onderweg_bedrag[project_id] = onderweg_bedrag.get(project_id, Decimal("0")) + (uren * tarief).quantize(
                Decimal("0.01")
            )
    uit: dict[uuid.UUID, ResultaatChip] = {}
    for pid in project_ids:
        b = baten.get(pid, Decimal("0")) + meerwerk.get(pid, Decimal("0"))
        k = kosten.get(pid, Decimal("0")) + onderweg_bedrag.get(pid, Decimal("0"))
        marge = b - k
        heeft = pid in baten or pid in kosten or pid in meerwerk or pid in onderweg_bedrag or pid in onbepaalbaar
        uit[pid] = ResultaatChip(
            baten=b,
            kosten=k,
            marge=marge,
            marge_pct=(marge / b * 100).quantize(Decimal("0.1")) if b != 0 else None,
            onbepaalbaar_uren=onbepaalbaar.get(pid, Decimal("0")),
            heeft_cijfers=heeft,
        )
    return uit


def _lopende_verplichtingen(session: Session, aid: uuid.UUID, project_ids: set[uuid.UUID]) -> list[Verplichting]:
    """Goedgekeurde verplichtingen (document GEACCORDEERD) van deze projecten — incl. vervallen (het detail
    toont die als historie; de lijst-chip telt ze niet)."""
    if not project_ids:
        return []
    return list(
        session.scalars(
            select(Verplichting)
            .join(Document, Document.id == Verplichting.document_id)
            .where(
                Verplichting.administratie_id == aid,
                Verplichting.project_id.in_(project_ids),
                Document.status == DocumentStatus.GEACCORDEERD,
            )
            .order_by(Verplichting.goedgekeurd_op.desc().nulls_last())
        )
    )


def _verplichting_status(v: Verplichting) -> str:
    if v.vervallen_op is not None:
        return "vervallen"
    totaal = v.goedgekeurd_bedrag_excl
    if totaal is not None and Decimal(v.verbruikt_bedrag_excl or 0) > totaal:
        return "overschreden"
    return "lopend"


def _verplichtingen_per_project(
    session: Session, aid: uuid.UUID, project_ids: set[uuid.UUID]
) -> dict[uuid.UUID, VerplichtingenChip]:
    per: dict[uuid.UUID, list[Verplichting]] = {}
    for v in _lopende_verplichtingen(session, aid, project_ids):
        if v.vervallen_op is not None or v.project_id is None:
            continue
        per.setdefault(v.project_id, []).append(v)
    uit: dict[uuid.UUID, VerplichtingenChip] = {}
    for pid in project_ids:
        vs = per.get(pid, [])
        goedgekeurd = sum((v.goedgekeurd_bedrag_excl or Decimal("0") for v in vs), Decimal("0"))
        verbruikt = sum((Decimal(v.verbruikt_bedrag_excl or 0) for v in vs), Decimal("0"))
        uit[pid] = VerplichtingenChip(
            aantal=len(vs),
            goedgekeurd_excl=goedgekeurd,
            verbruikt_excl=verbruikt,
            percentage=_pct(verbruikt, goedgekeurd) if vs else None,
            overschreden=sum(1 for v in vs if _verplichting_status(v) == "overschreden"),
        )
    return uit


@dataclass
class _PlanningWeek:
    """Werkrecord per (project, jaar, week): geplande personen + dagen, staten per status, afmeldingen."""

    personen: set[uuid.UUID] = field(default_factory=set)
    dagen: Decimal = Decimal("0")
    staten: dict[uuid.UUID, str] = field(default_factory=dict)  # gebruiker → weekstaat-status
    afgemeld: set[uuid.UUID] = field(default_factory=set)


def _planning_per_project(
    session: Session, aid: uuid.UUID, project_ids: set[uuid.UUID], *, tot_en_met: date
) -> dict[uuid.UUID, dict[tuple[int, int], _PlanningWeek]]:
    """Alle planning-/weekstaat-/afmeldingsrijen van deze projecten t/m `tot_en_met`, gegroepeerd per
    project × ISO-week — drie queries per administratie."""
    uit: dict[uuid.UUID, dict[tuple[int, int], _PlanningWeek]] = {pid: {} for pid in project_ids}
    if not project_ids:
        return uit
    for project_id, gebruiker_id, datum, dagdeel in session.execute(
        select(
            PlanningToewijzing.project_id,
            PlanningToewijzing.gebruiker_id,
            PlanningToewijzing.datum,
            PlanningToewijzing.dagdeel,
        ).where(
            PlanningToewijzing.administratie_id == aid,
            PlanningToewijzing.project_id.in_(project_ids),
            PlanningToewijzing.datum <= tot_en_met,
        )
    ):
        w = uit[project_id].setdefault(_week_sleutel(datum), _PlanningWeek())
        w.personen.add(gebruiker_id)
        w.dagen += _HALF if dagdeel == PlanningDagdeel.HALF.value else _HEEL
    for project_id, gebruiker_id, jaar, week, status in session.execute(
        select(
            Weekstaat.project_id, Weekstaat.gebruiker_id, Weekstaat.jaar, Weekstaat.weeknummer, Weekstaat.status
        ).where(Weekstaat.administratie_id == aid, Weekstaat.project_id.in_(project_ids))
    ):
        uit[project_id].setdefault((jaar, week), _PlanningWeek()).staten[gebruiker_id] = status
    for project_id, gebruiker_id, jaar, week in session.execute(
        select(
            PlanningSignaalAfhandeling.project_id,
            PlanningSignaalAfhandeling.gebruiker_id,
            PlanningSignaalAfhandeling.jaar,
            PlanningSignaalAfhandeling.weeknummer,
        ).where(
            PlanningSignaalAfhandeling.administratie_id == aid,
            PlanningSignaalAfhandeling.project_id.in_(project_ids),
            PlanningSignaalAfhandeling.soort == PlanningSignaalSoort.AFGEMELD.value,
            PlanningSignaalAfhandeling.ingetrokken_op.is_(None),
        )
    ):
        uit[project_id].setdefault((jaar, week), _PlanningWeek()).afgemeld.add(gebruiker_id)
    return uit


def _ontbrekend_in_week(w: _PlanningWeek) -> int:
    """Geplande personen zonder ingediende/goedgekeurde staat, minus actieve afmeldingen."""
    return sum(1 for g in w.personen if w.staten.get(g) not in _INGEDIEND_OF_BETER and g not in w.afgemeld)


def _weekstaten_chip(weken: dict[tuple[int, int], _PlanningWeek], *, huidige_week: tuple[int, int]) -> WeekstatenChip:
    ontbrekend = 0
    oudste: tuple[int, int] | None = None
    te_keuren = 0
    concept = 0
    for sleutel, w in weken.items():
        te_keuren += sum(1 for s in w.staten.values() if s == WeekstaatStatus.INGEDIEND.value)
        concept += sum(
            1 for s in w.staten.values() if s in (WeekstaatStatus.CONCEPT.value, WeekstaatStatus.CORRIGEREN.value)
        )
        if sleutel >= huidige_week:
            continue  # de lopende week is nooit "ontbrekend"
        n = _ontbrekend_in_week(w)
        if n:
            ontbrekend += n
            if oudste is None or sleutel < oudste:
                oudste = sleutel
    return WeekstatenChip(
        van_toepassing=True, ontbrekend=ontbrekend, oudste_ontbrekende_week=oudste, te_keuren=te_keuren, concept=concept
    )


def _gebouwd_m2_per_project(session: Session, aid: uuid.UUID, project_ids: set[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not project_ids:
        return {}
    return {
        pid: Decimal(som)
        for pid, som in session.execute(
            select(Weekstaat.project_id, func.coalesce(func.sum(WeekstaatDag.m2), 0))
            .join(Weekstaat, Weekstaat.id == WeekstaatDag.weekstaat_id)
            .where(
                Weekstaat.administratie_id == aid,
                Weekstaat.project_id.in_(project_ids),
                Weekstaat.status == WeekstaatStatus.GOEDGEKEURD.value,
            )
            .group_by(Weekstaat.project_id)
        )
    }


#: Gewichten voor de urgentie-sortering: één verplichting over het budget weegt zwaarder dan een negatieve
#: marge (dáár staat een akkoord van de klant tegenover), die weer zwaarder dan een ontbrekende staat.
_GEWICHT = {"verplichting_overschreden": 8, "marge_negatief": 4, "weekstaat_ontbreekt": 2, "te_keuren": 1}


def _signalen(res: ResultaatChip, verp: VerplichtingenChip, ws: WeekstatenChip) -> tuple[str, ...]:
    uit: list[str] = []
    if verp.overschreden:
        uit.append("verplichting_overschreden")
    if res.heeft_cijfers and res.marge < 0:
        uit.append("marge_negatief")
    if ws.van_toepassing and ws.ontbrekend:
        uit.append("weekstaat_ontbreekt")
    if ws.van_toepassing and ws.te_keuren:
        uit.append("te_keuren")
    return tuple(uit)


def _rijen_voor_administratie(*, aid: uuid.UUID, naam: str, actor_id: uuid.UUID, vandaag: date) -> list[Rij]:
    huidige_week = _week_sleutel(vandaag)
    with scoped_session(aid, actor_id=actor_id) as session:
        administratie = session.get(Administratie, aid)
        if administratie is None:
            return []  # RLS: geen scope = geen rijen (Beheerder-bypass leest wél)
        projecten = list(
            session.scalars(
                select(ProjectCache)
                .where(
                    ProjectCache.administratie_id == aid,
                    ProjectCache.is_actief.is_(True),
                    ProjectCache.verdwenen_uit_bron_op.is_(None),
                )
                .order_by(ProjectCache.naam)
            )
        )
        if not projecten:
            return []
        project_ids = {p.id for p in projecten}
        specs = {
            s.project_id: s
            for s in session.scalars(
                select(ProjectSpecificatie).where(
                    ProjectSpecificatie.administratie_id == aid, ProjectSpecificatie.project_id.in_(project_ids)
                )
            )
        }
        resultaat = _resultaat_per_project(session, aid, project_ids)
        verplichtingen = _verplichtingen_per_project(session, aid, project_ids)
        gebouwd = _gebouwd_m2_per_project(session, aid, project_ids)
        uren_aan = bool(administratie.uren_meerwerk_ingeschakeld)
        planning = (
            _planning_per_project(session, aid, project_ids, tot_en_met=vandaag + timedelta(days=7)) if uren_aan else {}
        )
        uit: list[Rij] = []
        for p in projecten:
            spec = specs.get(p.id)
            res = resultaat[p.id]
            verp = verplichtingen[p.id]
            ws = (
                _weekstaten_chip(planning.get(p.id, {}), huidige_week=huidige_week)
                if uren_aan
                else WeekstatenChip(
                    van_toepassing=False, ontbrekend=0, oudste_ontbrekende_week=None, te_keuren=0, concept=0
                )
            )
            contract_m2 = spec.contract_m2 if spec else None
            g = gebouwd.get(p.id, Decimal("0"))
            signalen = _signalen(res, verp, ws)
            uit.append(
                Rij(
                    administratie_id=aid,
                    administratie_naam=naam,
                    project_id=p.id,
                    naam=p.naam,
                    opdrachtgever=spec.opdrachtgever if spec else None,
                    werknummer_opdrachtgever=spec.werknummer_opdrachtgever if spec else None,
                    looptijd_tot=spec.looptijd_tot if spec else None,
                    resultaat=res,
                    verplichtingen=verp,
                    weekstaten=ws,
                    m2=M2Chip(
                        gebouwd_m2=g,
                        contract_m2=contract_m2,
                        percentage=_pct(g, contract_m2),
                        doorlopende_huur=bool(spec and spec.doorlopende_huur_omschrijving),
                    ),
                    signalen=signalen,
                    urgentie=sum(_GEWICHT[s] for s in signalen),
                )
            )
        return uit


def _alle_rijen(*, actor_id: uuid.UUID, rol: GebruikerRol, vandaag: date) -> list[Rij]:
    uit: list[Rij] = []
    for administratie in auth_service.mijn_administraties(actor_id=actor_id, rol=rol):
        uit.extend(
            _rijen_voor_administratie(aid=administratie.id, naam=administratie.naam, actor_id=actor_id, vandaag=vandaag)
        )
    return uit


def _in_facet(rij: Rij, status: str) -> bool:
    if status == "alle":
        return True
    if status == "signaal":
        return bool(rij.signalen)
    if status == "op_schema":
        return not rij.signalen
    return status in rij.signalen


def _sorteer(rijen: list[Rij]) -> list[Rij]:
    return sorted(rijen, key=lambda r: (-r.urgentie, r.administratie_naam.lower(), (r.naam or "").lower()))


def lijst(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    pagina: int = 1,
    q: str = "",
    administratie_id: uuid.UUID | None = None,
    status: str = "alle",
    vandaag: date | None = None,
) -> Lijst:
    if status not in STATUS_FACETTEN:
        raise ProjectenKantoorbreedFout(f"Onbekend status-facet: {status}")
    vandaag = vandaag or date.today()
    alle = _alle_rijen(actor_id=actor_id, rol=rol, vandaag=vandaag)

    tellers = Tellers(
        projecten=len(alle),
        administraties=len({r.administratie_id for r in alle}),
        met_signaal=sum(1 for r in alle if r.signalen),
        verplichting_overschreden=sum(1 for r in alle if "verplichting_overschreden" in r.signalen),
        marge_negatief=sum(1 for r in alle if "marge_negatief" in r.signalen),
        weekstaat_ontbreekt=sum(1 for r in alle if "weekstaat_ontbreekt" in r.signalen),
        te_keuren=sum(1 for r in alle if "te_keuren" in r.signalen),
    )

    term = q.strip().lower()
    met_zoek = [r for r in alle if not term or term in r.zoektekst]
    binnen_admin = [r for r in met_zoek if administratie_id is None or r.administratie_id == administratie_id]
    facetten_status = {s: sum(1 for r in binnen_admin if _in_facet(r, s)) for s in STATUS_FACETTEN}
    binnen_status = [r for r in met_zoek if _in_facet(r, status)]
    per_admin: dict[uuid.UUID, tuple[str, int]] = {}
    for r in binnen_status:
        naam, n = per_admin.get(r.administratie_id, (r.administratie_naam, 0))
        per_admin[r.administratie_id] = (naam, n + 1)
    facetten_administraties = sorted(
        (AdministratieFacet(administratie_id=aid, naam=naam, aantal=n) for aid, (naam, n) in per_admin.items()),
        key=lambda f: (-f.aantal, f.naam),
    )

    selectie = _sorteer([r for r in binnen_admin if _in_facet(r, status)])
    start = (pagina - 1) * PER_PAGINA
    return Lijst(
        rijen=selectie[start : start + PER_PAGINA],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=PER_PAGINA,
        administraties_in_selectie=len({r.administratie_id for r in selectie}),
        tellers=tellers,
        facetten_status=facetten_status,
        facetten_administraties=facetten_administraties,
    )


# --- detail-verrijking -------------------------------------------------------------------------------


def detail_verrijking(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, vandaag: date | None = None
) -> DetailVerrijking:
    """Verplichtingen mét verbruiksstand + weekstaten-/planningstand per week voor één project — additief
    op het bestaande projectdetail (zelfde helpers als de kantoorbrede lijst, dus dezelfde cijfers)."""
    vandaag = vandaag or date.today()
    huidige_week = _week_sleutel(vandaag)
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        ids = {project_id}
        vs = _lopende_verplichtingen(session, administratie_id, ids)
        vendor_namen = (
            dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(
                        VendorCache.administratie_id == administratie_id,
                        VendorCache.id.in_({v.vendor_id for v in vs if v.vendor_id}),
                    )
                ).all()
            )
            if any(v.vendor_id for v in vs)
            else {}
        )
        open_per = open_facturen_per_verplichting(
            session, administratie_id=administratie_id, verplichting_ids=[v.document_id for v in vs]
        )
        verplichtingen: list[ProjectVerplichting] = []
        for v in vs:
            totaal = v.goedgekeurd_bedrag_excl
            verbruikt = Decimal(v.verbruikt_bedrag_excl or 0)
            over = (verbruikt - totaal).quantize(Decimal("0.01")) if totaal is not None else None
            aantal, som = open_per.get(v.document_id, (0, Decimal("0.00")))
            verplichtingen.append(
                ProjectVerplichting(
                    document_id=v.document_id,
                    offertenummer=v.offertenummer,
                    soort_label=v.soort_label,
                    leverancier_naam=vendor_namen.get(v.vendor_id) if v.vendor_id else None,
                    omschrijving=v.omschrijving,
                    goedgekeurd_excl=totaal,
                    verbruikt_excl=verbruikt,
                    percentage=match_motor.percentage(verbruikt, totaal),
                    over_excl=over if over is not None and over > 0 else None,
                    geldig_tot=v.geldig_tot,
                    status=_verplichting_status(v),
                    open_facturen_aantal=aantal,
                    open_facturen_excl=som,
                )
            )
        # Lopend/overschreden eerst (overschreden bovenaan), vervallen als historie onderaan.
        orde = {"overschreden": 0, "lopend": 1, "vervallen": 2}
        verplichtingen.sort(key=lambda v: (orde[v.status], -(v.percentage or 0)))

        if administratie is None or not administratie.uren_meerwerk_ingeschakeld:
            return DetailVerrijking(verplichtingen=verplichtingen, weekstaten=WeekstatenStand(van_toepassing=False))

        planning = _planning_per_project(session, administratie_id, ids, tot_en_met=vandaag + timedelta(days=7))
        weken = planning.get(project_id, {})
        chip = _weekstaten_chip(weken, huidige_week=huidige_week)
        # Detail-venster: de huidige week + de WEKEN_IN_DETAIL-1 weken ervoor, nieuwste eerst — ook lege weken
        # staan erin (een lege rij is informatie: niets gepland, niets ingediend).
        maandag_nu = _maandag(*huidige_week)
        stand: list[WeekStand] = []
        for i in range(WEKEN_IN_DETAIL):
            sleutel = _week_sleutel(maandag_nu - timedelta(weeks=i))
            w = weken.get(sleutel, _PlanningWeek())
            statussen = list(w.staten.values())
            stand.append(
                WeekStand(
                    jaar=sleutel[0],
                    weeknummer=sleutel[1],
                    maandag=_maandag(*sleutel),
                    gepland_personen=len(w.personen),
                    gepland_dagen=w.dagen,
                    concept=statussen.count(WeekstaatStatus.CONCEPT.value),
                    ingediend=statussen.count(WeekstaatStatus.INGEDIEND.value),
                    goedgekeurd=statussen.count(WeekstaatStatus.GOEDGEKEURD.value),
                    corrigeren=statussen.count(WeekstaatStatus.CORRIGEREN.value),
                    ontbrekend=_ontbrekend_in_week(w) if sleutel < huidige_week else 0,
                    afgemeld=len(w.afgemeld & w.personen),
                )
            )
        return DetailVerrijking(
            verplichtingen=verplichtingen,
            weekstaten=WeekstatenStand(
                van_toepassing=True,
                weken=stand,
                ontbrekend_totaal=chip.ontbrekend,
                te_keuren_totaal=chip.te_keuren,
                oudste_ontbrekende_week=chip.oudste_ontbrekende_week,
            ),
        )
