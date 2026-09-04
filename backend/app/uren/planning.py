"""Planning-agenda steigerbouw — geldlogica (mockup planning-steigerbouw.html, definitief
akkoord Peter 2026-08-22; BESLISSINGEN "PLANNING-AGENDA STEIGERBOUW").

Kern: het kantoor plant ZZP'ers/uitvoerders per dag op ACTIEVE projecten (weekgrid, sleepbare
kaartjes; dagdeel heel/half). Besluiten 22-08:
- A — plannen maakt de projectkoppeling (uren_project_toewijzing) automatisch aan: planning ís
  de koppeling. Geaudit, mét bron 'planning'.
- B — de veldwerker ziet zijn eigen planning ALLEEN-LEZEN in de app, de hele week vooruit
  ("waar moet ik heen"); de detacheerder in de namens-flow idem. Geen mutaties via de veld-API.
- C — > 5 geplande dagen per persoon per week = zacht signaal (teller hier, kleur in de UI).
- FAILSAFE — dezelfde persoon nooit 2× op dezelfde dag op hetzélfde project: de samengestelde
  PK van planning_toewijzing; de service vertaalt de botsing naar een duidelijke fout.
- Koppeling met de weekstaten (toetsbron): uren op een gepland project/dag = groen; uren
  buiten de planning = oranje bij de keuring (géén blokkade — invallen/omplannen blijft
  mogelijk); twee projecten op één dag zónder volledige planning-dekking = interne melding +
  teller per ZZP'er, uitsluitend zichtbaar voor kantoor (vlagpatroon, geen enum-status).

Toegang: kantoor-kant onder het module-recht 'Meerwerk & urenstaten' + klantscope (router) én
de opt-in per administratie (uren_meerwerk_ingeschakeld) — allemaal ook hier server-side."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select

from app.db.audit import record_audit_event
from app.db.models import DetacheerderKoppeling, Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.sync.models import ProjectCache
from app.uren.models import (
    PlanningDagdeel,
    PlanningToewijzing,
    ProjectSpecificatie,
    Weekstaat,
    WeekstaatDag,
)
from app.uren.service import (
    MODULE,
    GeenToegang,
    NietGevonden,
    OngeldigeInvoer,
    _administratie_met_opt_in,
    _gebruiker,
    _vereis_meerwerk_recht,
    week_grenzen,
    zorg_voor_projectkoppeling,
)

DUBBELE_DAG_VENSTER_DAGEN = 30  # teller-venster (mockup: "3× / 30 dgn")
ZACHT_SIGNAAL_DAGEN = Decimal("5")  # besluit C: > 5 geplande dagen p.p. per week

_PLANBARE_ROLLEN = (GebruikerRol.ZZPER, GebruikerRol.UITVOERDER)

_DAGDEEL_WAARDE = {PlanningDagdeel.HEEL.value: Decimal("1"), PlanningDagdeel.HALF.value: Decimal("0.5")}


# --- data ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanningKaartData:
    """Eén gepland kaartje in een grid-cel (persoon × project × dag)."""

    gebruiker_id: uuid.UUID
    naam: str | None
    rol: str
    dagdeel: str


@dataclass(frozen=True)
class ProjectRijData:
    """Eén projectrij in het weekgrid. V3-besluit Peter 23-08 (vervángt het 22-08-grid-filter
    "alleen mét planning"): ÁLLE actieve projecten zijn een rij — de UI splitst op planning
    (vol bovenaan, compact eronder) zodat plannen direct kan starten. is_actief is False voor
    een intussen gedeactiveerd project mét planning (blijft zichtbaar om kaartjes weg te
    halen; telt in de UI niet mee als actief project)."""

    project_id: uuid.UUID
    project_naam: str | None
    opdrachtgever: str | None
    soort_werk: str | None
    looptijd_tot: date | None
    is_actief: bool
    week_man: int  # "deze week: N man" — unieke personen met ≥ 1 toewijzing deze week
    # ISO-datum → kaartjes (alleen datums mét toewijzingen; de UI rendert de kolommen).
    per_datum: dict[str, list[PlanningKaartData]]
    # Werkopdrachten (31-08): actuele opdrachten die de week raken (chip in de rijkop) en de
    # dag-overrides binnen de week (blok in de dagcel; ISO-datum → afwijkende teksten).
    werkopdrachten: list = field(default_factory=list)
    werkopdracht_overrides: dict[str, list] = field(default_factory=dict)


@dataclass(frozen=True)
class PoolPersoonData:
    """Persoon in de zijbalk-pool: alle (niet-geblokkeerde) ZZP'ers en uitvoerders, met het
    aantal geplande dagen deze week (heel = 1, half = 0,5 — besluit C kleurt > 5)."""

    gebruiker_id: uuid.UUID
    naam: str
    rol: str
    geplande_dagen: Decimal


@dataclass(frozen=True)
class BuitenPlanningMelding:
    """Uren ingediend op een dag/project zonder planning-dekking (oranje — geen blokkade)."""

    gebruiker_id: uuid.UUID
    naam: str | None
    datum: date
    project_naam: str | None
    uren: Decimal


@dataclass(frozen=True)
class DubbeleDagMelding:
    """Twee (of meer) projecten op één dag zónder volledige planning-dekking — interne
    melding, uitsluitend zichtbaar voor kantoor (vlagpatroon, geen enum-status)."""

    gebruiker_id: uuid.UUID
    naam: str | None
    datum: date
    project_namen: list[str]
    ongedekte_project_namen: list[str]


@dataclass(frozen=True)
class DubbeleDagTeller:
    gebruiker_id: uuid.UUID
    naam: str | None
    aantal: int  # dagen met een ongedekte dubbele dag in de laatste 30 dagen


@dataclass(frozen=True)
class PlanningWeekData:
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    projecten: list[ProjectRijData]
    pool: list[PoolPersoonData]
    buiten_planning: list[BuitenPlanningMelding]
    dubbele_dagen: list[DubbeleDagMelding]
    dubbele_dag_tellers: list[DubbeleDagTeller]
    # Wachtrisico-kruissignaal (steigerbouw-run D5): personeel gepland zonder bevestigde levering.
    wachtrisico: list = field(default_factory=list)


@dataclass(frozen=True)
class MijnPlanningDag:
    """Eén regel in de alleen-lezen veld-weergave (besluit B): waar moet ik heen."""

    datum: date
    administratie_id: uuid.UUID
    administratie_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None
    dagdeel: str
    # Geldende werkopdracht(en) op deze dag (31-08): override wint per opdracht — alleen-lezen.
    werkopdrachten: list = field(default_factory=list)


# --- helpers ---------------------------------------------------------------------------------


def _vereis_planbare_gebruiker(session, gebruiker_id: uuid.UUID) -> Gebruiker:
    gebruiker = _gebruiker(session, gebruiker_id)
    if gebruiker.rol not in _PLANBARE_ROLLEN:
        raise OngeldigeInvoer("Alleen ZZP'ers en uitvoerders worden op projecten gepland")
    return gebruiker


def _vereis_actief_project(session, administratie_id: uuid.UUID, project_id: uuid.UUID) -> ProjectCache:
    project = session.get(ProjectCache, (project_id, administratie_id))
    if project is None:
        raise NietGevonden("Onbekend project voor deze administratie")
    if project.is_actief is not True or project.verdwenen_uit_bron_op is not None:
        raise OngeldigeInvoer("Alleen actieve projecten staan in de planning (mockup-norm)")
    return project


def _vereis_dagdeel(dagdeel: str) -> str:
    if dagdeel not in {d.value for d in PlanningDagdeel}:
        raise OngeldigeInvoer(f"Onbekend dagdeel: {dagdeel!r} (heel of half)")
    return dagdeel


def _zorg_voor_projectkoppeling(
    session, *, administratie_id: uuid.UUID, gebruiker: Gebruiker, project_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """Besluit A (22-08): slepen/toewijzen maakt de ZZP↔project-koppeling automatisch aan als
    die nog niet bestaat — planning ís de koppeling. Geaudit mét bron 'planning' (één helper mét
    het weekstaat-pad, addendum 04-09: `service.zorg_voor_projectkoppeling`)."""
    zorg_voor_projectkoppeling(
        session,
        administratie_id=administratie_id,
        gebruiker=gebruiker,
        project_id=project_id,
        actor_id=actor_id,
        bron="planning",
    )


def ongeplande_datums(
    session,
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    datums: list[date],
) -> set[date]:
    """Datums uit `datums` zónder planningstoewijzing voor (persoon, project) — de
    dekking-toets voor de weekstaat-keuring ('buiten planning', oranje, geen blokkade)."""
    if not datums:
        return set()
    gepland = set(
        session.scalars(
            select(PlanningToewijzing.datum).where(
                PlanningToewijzing.administratie_id == administratie_id,
                PlanningToewijzing.gebruiker_id == gebruiker_id,
                PlanningToewijzing.project_id == project_id,
                PlanningToewijzing.datum.in_(datums),
            )
        )
    )
    return {d for d in datums if d not in gepland}


# --- kantoor: plannen (module-recht, server-side) ----------------------------------------------


def plan_toewijzing(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    datum: date,
    dagdeel: str = PlanningDagdeel.HEEL.value,
    actor_id: uuid.UUID,
) -> None:
    """Persoon op project × dag plannen (kaartje in het grid). FAILSAFE (besluit 22-08):
    dezelfde persoon 2× op dezelfde dag op hetzélfde project = expliciete fout — de cel
    weigert. Maakt de projectkoppeling automatisch aan (besluit A)."""
    _vereis_dagdeel(dagdeel)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        _vereis_actief_project(session, administratie_id, project_id)
        gebruiker = _vereis_planbare_gebruiker(session, gebruiker_id)
        if session.get(PlanningToewijzing, (administratie_id, gebruiker_id, project_id, datum)) is not None:
            raise OngeldigeInvoer(
                f"{gebruiker.naam} staat op {datum} al op dit project gepland — "
                "één kaartje per persoon per project per dag"
            )
        _zorg_voor_projectkoppeling(
            session, administratie_id=administratie_id, gebruiker=gebruiker, project_id=project_id, actor_id=actor_id
        )
        session.add(
            PlanningToewijzing(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                project_id=project_id,
                datum=datum,
                dagdeel=dagdeel,
                toegevoegd_door=actor_id,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_toewijzing",
            record_id=gebruiker_id,
            actie="planning_gepland",
            correlatie_id=project_id,
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker_id),
                "project_id": str(project_id),
                "datum": datum.isoformat(),
                "dagdeel": dagdeel,
            },
            administratie_id=administratie_id,
        )


def verwijder_toewijzing(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    datum: date,
    actor_id: uuid.UUID,
) -> None:
    """Kaartje uit het grid halen. Idempotent; de projectkoppeling blijft staan (weekstaten
    kunnen er al op bestaan — koppelingen beheert het kantoor apart)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        rij = session.get(PlanningToewijzing, (administratie_id, gebruiker_id, project_id, datum))
        if rij is None:
            return  # idempotent
        oude_waarde = {
            "gebruiker_id": str(gebruiker_id),
            "project_id": str(project_id),
            "datum": datum.isoformat(),
            "dagdeel": rij.dagdeel,
        }
        session.delete(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_toewijzing",
            record_id=gebruiker_id,
            actie="planning_verwijderd",
            correlatie_id=project_id,
            oude_waarde=oude_waarde,
            administratie_id=administratie_id,
        )


def verplaats_toewijzing(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    van_project_id: uuid.UUID,
    van_datum: date,
    naar_project_id: uuid.UUID,
    naar_datum: date,
    actor_id: uuid.UUID,
) -> None:
    """Kaartje slepen tussen cellen — atomair (verwijderen + plannen in één transactie, nooit
    half). Zelfde failsafe op de doelcel; het dagdeel verhuist mee; auto-koppeling op het
    doelproject (besluit A)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        bron = session.get(PlanningToewijzing, (administratie_id, gebruiker_id, van_project_id, van_datum))
        if bron is None:
            raise NietGevonden("Deze planningstoewijzing bestaat niet (mogelijk al verplaatst — ververs het grid)")
        if van_project_id == naar_project_id and van_datum == naar_datum:
            return  # niets te doen
        _vereis_actief_project(session, administratie_id, naar_project_id)
        gebruiker = _vereis_planbare_gebruiker(session, gebruiker_id)
        if session.get(PlanningToewijzing, (administratie_id, gebruiker_id, naar_project_id, naar_datum)) is not None:
            raise OngeldigeInvoer(
                f"{gebruiker.naam} staat op {naar_datum} al op het doelproject gepland — de cel weigert"
            )
        dagdeel = bron.dagdeel
        _zorg_voor_projectkoppeling(
            session,
            administratie_id=administratie_id,
            gebruiker=gebruiker,
            project_id=naar_project_id,
            actor_id=actor_id,
        )
        session.delete(bron)
        session.flush()
        session.add(
            PlanningToewijzing(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                project_id=naar_project_id,
                datum=naar_datum,
                dagdeel=dagdeel,
                toegevoegd_door=actor_id,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_toewijzing",
            record_id=gebruiker_id,
            actie="planning_verplaatst",
            correlatie_id=naar_project_id,
            oude_waarde={"project_id": str(van_project_id), "datum": van_datum.isoformat()},
            nieuwe_waarde={
                "project_id": str(naar_project_id),
                "datum": naar_datum.isoformat(),
                "dagdeel": dagdeel,
            },
            administratie_id=administratie_id,
        )


def zet_dagdeel(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    datum: date,
    dagdeel: str,
    actor_id: uuid.UUID,
) -> None:
    """Dagdeel (heel ↔ half) van een bestaand kaartje wijzigen (het ½-label, mockup)."""
    _vereis_dagdeel(dagdeel)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        rij = session.get(PlanningToewijzing, (administratie_id, gebruiker_id, project_id, datum))
        if rij is None:
            raise NietGevonden("Deze planningstoewijzing bestaat niet")
        if rij.dagdeel == dagdeel:
            return  # idempotent
        oud = rij.dagdeel
        rij.dagdeel = dagdeel
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_toewijzing",
            record_id=gebruiker_id,
            actie="planning_dagdeel_gezet",
            correlatie_id=project_id,
            oude_waarde={"dagdeel": oud, "datum": datum.isoformat()},
            nieuwe_waarde={"dagdeel": dagdeel, "datum": datum.isoformat()},
            administratie_id=administratie_id,
        )


# --- kantoor: weekoverzicht + signalen ----------------------------------------------------------


def _dekking_signalen(
    session,
    *,
    administratie_id: uuid.UUID,
    van: date,
    tot_en_met: date,
) -> tuple[list[BuitenPlanningMelding], list[DubbeleDagMelding]]:
    """Weekstaat-uren in het venster toetsen tegen de planning: (buiten-planning-meldingen,
    ongedekte dubbele dagen). Alle weekstaat-statussen tellen mee — het is signalering."""
    dag_rijen = session.execute(
        select(WeekstaatDag, Weekstaat.gebruiker_id, Weekstaat.project_id)
        .join(Weekstaat, Weekstaat.id == WeekstaatDag.weekstaat_id)
        .where(
            WeekstaatDag.administratie_id == administratie_id,
            WeekstaatDag.datum >= van,
            WeekstaatDag.datum <= tot_en_met,
            WeekstaatDag.uren > 0,
        )
    ).all()
    if not dag_rijen:
        return [], []

    gepland = {
        (r.gebruiker_id, r.project_id, r.datum)
        for r in session.scalars(
            select(PlanningToewijzing).where(
                PlanningToewijzing.administratie_id == administratie_id,
                PlanningToewijzing.datum >= van,
                PlanningToewijzing.datum <= tot_en_met,
            )
        )
    }

    gebruiker_ids = {gid for _, gid, _ in dag_rijen}
    project_ids = {pid for _, _, pid in dag_rijen}
    namen = {g.id: g.naam for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(gebruiker_ids))).all()}
    project_namen = {
        p.id: p.naam
        for p in session.scalars(
            select(ProjectCache).where(
                ProjectCache.administratie_id == administratie_id, ProjectCache.id.in_(project_ids)
            )
        ).all()
    }

    buiten: list[BuitenPlanningMelding] = []
    per_persoon_dag: dict[tuple[uuid.UUID, date], list[tuple[uuid.UUID, bool]]] = {}
    for dag, gebruiker_id, project_id in dag_rijen:
        gedekt = (gebruiker_id, project_id, dag.datum) in gepland
        per_persoon_dag.setdefault((gebruiker_id, dag.datum), []).append((project_id, gedekt))
        if not gedekt:
            buiten.append(
                BuitenPlanningMelding(
                    gebruiker_id=gebruiker_id,
                    naam=namen.get(gebruiker_id),
                    datum=dag.datum,
                    project_naam=project_namen.get(project_id),
                    uren=dag.uren,
                )
            )

    dubbel: list[DubbeleDagMelding] = []
    for (gebruiker_id, datum), projecten in per_persoon_dag.items():
        if len(projecten) < 2:
            continue
        ongedekt = [pid for pid, gedekt in projecten if not gedekt]
        if not ongedekt:
            continue  # dubbele dag volledig gedekt door de planning (dagdelen) — geen melding
        dubbel.append(
            DubbeleDagMelding(
                gebruiker_id=gebruiker_id,
                naam=namen.get(gebruiker_id),
                datum=datum,
                project_namen=sorted(project_namen.get(pid) or str(pid) for pid, _ in projecten),
                ongedekte_project_namen=sorted(project_namen.get(pid) or str(pid) for pid in ongedekt),
            )
        )
    buiten.sort(key=lambda m: (m.datum, m.naam or ""))
    dubbel.sort(key=lambda m: (m.datum, m.naam or ""))
    return buiten, dubbel


def planning_overzicht(
    *,
    administratie_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    actor_id: uuid.UUID,
    vandaag: date | None = None,
) -> PlanningWeekData:
    """Het weekgrid (mockup v3, besluit Peter 23-08): ÁLLE actieve projecten als rijen (de UI
    splitst op planning — vol bovenaan, compact eronder), kaartjes per dag, de mensen-pool met
    geplande dagen (besluit C) en de controle-meldingen + dubbele-dag-teller (uitsluitend
    kantoor). Eén request levert alles incl. specs-metadata voor de rijkoppen — geen aparte
    zoekroute meer. `vandaag` is injecteerbaar voor deterministische tests."""
    vandaag = vandaag or date.today()
    maandag, zondag = week_grenzen(jaar, weeknummer)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)

        toewijzingen = list(
            session.scalars(
                select(PlanningToewijzing).where(
                    PlanningToewijzing.administratie_id == administratie_id,
                    PlanningToewijzing.datum >= maandag,
                    PlanningToewijzing.datum <= zondag,
                )
            )
        )

        # Pool: alle niet-geblokkeerde, niet-gearchiveerde ZZP'ers en uitvoerders (kantoor-breed —
        # een nieuwe veldwerker zonder koppeling moet juist sleepbaar zijn, besluit A). Bewust
        # een expliciete uitsluitlijst (0075: gearchiveerd hoort in géén default-lijst).
        pool_gebruikers = list(
            session.scalars(
                select(Gebruiker)
                .where(
                    Gebruiker.rol.in_(_PLANBARE_ROLLEN),
                    Gebruiker.status.not_in((GebruikerStatus.GEBLOKKEERD, GebruikerStatus.GEARCHIVEERD)),
                )
                .order_by(Gebruiker.naam)
            )
        )
        namen = {g.id: g.naam for g in pool_gebruikers}
        rollen = {g.id: g.rol.value for g in pool_gebruikers}
        # Kaartjes van personen die intussen geblokkeerd zijn blijven zichtbaar (naam erbij).
        onbekend = {t.gebruiker_id for t in toewijzingen} - set(namen)
        if onbekend:
            for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(onbekend))).all():
                namen[g.id] = g.naam
                rollen[g.id] = g.rol.value

        # Projectrijen (v3-besluit Peter 23-08, vervángt het 22-08-filter "alleen mét
        # planning" — dat gaf een leeg grid waarin je niet kon beginnen): ÁLLE actieve
        # projecten als rij, plus een intussen gedeactiveerd project mét planning (blijft
        # zichtbaar zodat kantoor de kaartjes kan weghalen/verplaatsen; is_actief=False).
        per_project: dict[uuid.UUID, list[PlanningToewijzing]] = {}
        for t in toewijzingen:
            per_project.setdefault(t.project_id, []).append(t)

        projecten = list(
            session.scalars(
                select(ProjectCache)
                .where(
                    ProjectCache.administratie_id == administratie_id,
                    or_(
                        and_(
                            ProjectCache.is_actief.is_(True),
                            ProjectCache.verdwenen_uit_bron_op.is_(None),
                        ),
                        ProjectCache.id.in_(per_project.keys()),
                    ),
                )
                .order_by(ProjectCache.naam)
            )
        )
        # Specs-metadata voor de rijkoppen in één batch over álle rijen (batch-les 22-08 —
        # nooit per rij; Universal heeft 68 actieve projecten).
        specs = {
            s.project_id: s
            for s in session.scalars(
                select(ProjectSpecificatie).where(
                    ProjectSpecificatie.administratie_id == administratie_id,
                    ProjectSpecificatie.project_id.in_([p.id for p in projecten]),
                )
            )
        }

        # Werkopdrachten (31-08): actuele versies + dag-overrides voor de week, in één batch.
        from app.uren.werkopdracht import werkopdrachten_voor_grid

        wo_per_project, wo_per_dag = werkopdrachten_voor_grid(
            session, administratie_id=administratie_id, maandag=maandag, zondag=zondag
        )

        rijen: list[ProjectRijData] = []
        for project in projecten:
            spec = specs.get(project.id)
            eigen = per_project.get(project.id, [])
            per_datum: dict[str, list[PlanningKaartData]] = {}
            for t in sorted(eigen, key=lambda t: (t.datum, namen.get(t.gebruiker_id) or "")):
                per_datum.setdefault(t.datum.isoformat(), []).append(
                    PlanningKaartData(
                        gebruiker_id=t.gebruiker_id,
                        naam=namen.get(t.gebruiker_id),
                        rol=rollen.get(t.gebruiker_id, "zzper"),
                        dagdeel=t.dagdeel,
                    )
                )
            rijen.append(
                ProjectRijData(
                    project_id=project.id,
                    project_naam=project.naam,
                    opdrachtgever=spec.opdrachtgever if spec else None,
                    soort_werk=spec.soort_werk if spec else None,
                    looptijd_tot=spec.looptijd_tot if spec else None,
                    is_actief=project.is_actief is True and project.verdwenen_uit_bron_op is None,
                    week_man=len({t.gebruiker_id for t in eigen}),
                    per_datum=per_datum,
                    werkopdrachten=wo_per_project.get(project.id, []),
                    werkopdracht_overrides={
                        datum.isoformat(): teksten
                        for (pid, datum), teksten in wo_per_dag.items()
                        if pid == project.id
                    },
                )
            )

        geplande_dagen: dict[uuid.UUID, Decimal] = {}
        for t in toewijzingen:
            geplande_dagen[t.gebruiker_id] = geplande_dagen.get(t.gebruiker_id, Decimal("0")) + _DAGDEEL_WAARDE.get(
                t.dagdeel, Decimal("1")
            )
        pool = [
            PoolPersoonData(
                gebruiker_id=g.id,
                naam=g.naam,
                rol=g.rol.value,
                geplande_dagen=geplande_dagen.get(g.id, Decimal("0")),
            )
            for g in pool_gebruikers
        ]

        buiten, dubbel = _dekking_signalen(session, administratie_id=administratie_id, van=maandag, tot_en_met=zondag)

        # Dubbele-dag-teller per ZZP'er over de laatste 30 dagen (mockup "3× / 30 dgn") —
        # uitsluitend kantoor; de veld-API exposeert dit nergens.
        _, dubbel_venster = _dekking_signalen(
            session,
            administratie_id=administratie_id,
            van=vandaag - timedelta(days=DUBBELE_DAG_VENSTER_DAGEN - 1),
            tot_en_met=vandaag,
        )
        teller_per_gebruiker: dict[uuid.UUID, int] = {}
        teller_namen: dict[uuid.UUID, str | None] = {}
        for melding in dubbel_venster:
            teller_per_gebruiker[melding.gebruiker_id] = teller_per_gebruiker.get(melding.gebruiker_id, 0) + 1
            teller_namen[melding.gebruiker_id] = melding.naam
        tellers = sorted(
            (
                DubbeleDagTeller(gebruiker_id=gid, naam=teller_namen.get(gid), aantal=aantal)
                for gid, aantal in teller_per_gebruiker.items()
            ),
            key=lambda t: (-t.aantal, t.naam or ""),
        )

        # Wachtrisico (D5): personeel × transport — rood op beide tabs (kaart + zijbalk).
        from app.materiaal.service import wachtrisico_in_sessie

        personeel: dict[tuple[uuid.UUID, date], int] = {}
        for tw in toewijzingen:
            personeel[(tw.project_id, tw.datum)] = personeel.get((tw.project_id, tw.datum), 0) + 1
        wachtrisico = wachtrisico_in_sessie(session, administratie_id=administratie_id, personeel=personeel)
        return PlanningWeekData(
            jaar=jaar,
            weeknummer=weeknummer,
            maandag=maandag,
            zondag=zondag,
            projecten=rijen,
            pool=pool,
            buiten_planning=buiten,
            dubbele_dagen=dubbel,
            dubbele_dag_tellers=tellers,
            wachtrisico=wachtrisico,
        )


# --- veld: eigen planning alleen-lezen (besluit B) ----------------------------------------------


def mijn_planning(
    *, veldwerker_id: uuid.UUID, actor_id: uuid.UUID, jaar: int, weeknummer: int
) -> list[MijnPlanningDag]:
    """De eigen planning voor één ISO-week, alleen-lezen ("waar moet ik heen") — over alle
    administraties mét de opt-in. Toegestaan: de veldwerker zelf (ZZP'er of uitvoerder — een
    uitvoerder is óók planbaar, mockup-pool) of een detacheerder namens een gekoppelde ZZP'er.
    Bewust géén mutatiepad: plannen doet uitsluitend het kantoor (besluit B)."""
    from app.uren.overzichten import _administraties_met_opt_in

    maandag, zondag = week_grenzen(jaar, weeknummer)
    with scoped_session(None, actor_id=actor_id) as session:
        actor = _gebruiker(session, actor_id)
        if actor_id == veldwerker_id:
            if actor.rol not in _PLANBARE_ROLLEN:
                raise GeenToegang("Alleen ZZP'ers en uitvoerders hebben een eigen planning")
        else:
            if actor.rol != GebruikerRol.DETACHEERDER:
                raise GeenToegang("Alleen de veldwerker zelf of een gekoppelde detacheerder mag dit")
            if session.get(DetacheerderKoppeling, (actor_id, veldwerker_id)) is None:
                raise GeenToegang("Deze detacheerder is niet aan deze ZZP'er gekoppeld")
        scope_rol = actor.rol

    dagen: list[MijnPlanningDag] = []
    for administratie in _administraties_met_opt_in(actor_id, scope_rol):
        with scoped_session(administratie.id) as session:
            rijen = list(
                session.scalars(
                    select(PlanningToewijzing).where(
                        PlanningToewijzing.administratie_id == administratie.id,
                        PlanningToewijzing.gebruiker_id == veldwerker_id,
                        PlanningToewijzing.datum >= maandag,
                        PlanningToewijzing.datum <= zondag,
                    )
                )
            )
            from app.uren.werkopdracht import teksten_voor_dag

            for rij in rijen:
                project = session.get(ProjectCache, (rij.project_id, administratie.id))
                dagen.append(
                    MijnPlanningDag(
                        datum=rij.datum,
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        project_id=rij.project_id,
                        project_naam=project.naam if project else None,
                        dagdeel=rij.dagdeel,
                        # Werkopdracht(en) alleen-lezen bij de geplande dag (31-08); bewust
                        # geen pushmelding bij een tekstwijziging.
                        werkopdrachten=teksten_voor_dag(
                            session, administratie_id=administratie.id, project_id=rij.project_id, datum=rij.datum
                        ),
                    )
                )
    dagen.sort(key=lambda d: (d.datum, d.project_naam or ""))
    return dagen
