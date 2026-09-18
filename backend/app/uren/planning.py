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

from sqlalchemy import and_, func, or_, select

from app.db.audit import record_audit_event
from app.db.models import DetacheerderKoppeling, Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.sync.models import ProjectCache
from app.tijd import kalenderdag_nl, vandaag_nl
from app.uren.models import (
    PlanningDagdeel,
    PlanningReservering,
    PlanningToewijzing,
    PlanningWijzigingMelding,
    ProjectSpecificatie,
    VeldwerkerAfwezigheid,
    Weekstaat,
    WeekstaatDag,
    WeekstaatStatus,
)
from app.uren.service import (
    MODULE,
    GeenToegang,
    NietGevonden,
    OngeldigeInvoer,
    OngeldigeOvergang,
    _administratie_met_opt_in,
    _gebruiker,
    _vereis_meerwerk_recht,
    heeft_meerwerk_urenstaten_recht,
    heeft_veldwerkerbeheer_recht,
    week_grenzen,
    zorg_voor_projectkoppeling,
)

#: Bulkroute (v3 18-09): hoogstens zoveel items per aanroep — 5 dagen × 40 man past ruim; erboven 422.
BULK_MAX_ITEMS = 200
BULK_BRONNEN = ("vulhandvat", "ploeg", "ongedaan")

DUBBELE_DAG_VENSTER_DAGEN = 30  # teller-venster (mockup: "3× / 30 dgn")
ZACHT_SIGNAAL_DAGEN = Decimal("5")  # besluit C: > 5 geplande dagen p.p. per week

_PLANBARE_ROLLEN = (GebruikerRol.ZZPER, GebruikerRol.UITVOERDER)

_DAGDEEL_WAARDE = {PlanningDagdeel.HEEL.value: Decimal("1"), PlanningDagdeel.HALF.value: Decimal("0.5")}


# --- data ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanningKaartData:
    """Eén gepland kaartje in een grid-cel (persoon × project × dag). Sinds 15-09 (Peter/Haci) mét de urenstatus uit
    de weekstaat van die persoon × project × week (één leesbron, geen nieuwe berekening): `uren_status` 'geen' (grijs) |
    'ingevuld' (blauw: dag mét uren, staat concept/ingediend) | 'gekeurd' (groen) | 'vraag' (oranje: afgekeurd/te
    corrigeren); `uren`/`m2` van die dag, `uren_detail` = tooltip-tekst; `achteraf` = gepland ná de dag zelf (chip
    "achteraf gepland")."""

    gebruiker_id: uuid.UUID
    naam: str | None
    rol: str
    dagdeel: str
    uren_status: str = "geen"
    uren: Decimal | None = None
    m2: Decimal | None = None
    uren_detail: str | None = None
    weekstaat_id: uuid.UUID | None = None
    achteraf: bool = False


@dataclass(frozen=True)
class WeekUrenData:
    """Weektotaal per projectrij (15-09): "24 u ingevuld · 16 u gekeurd · 2 open" — uit dezelfde weekstaat-rijen."""

    ingevuld_uren: Decimal = Decimal("0")
    gekeurd_uren: Decimal = Decimal("0")
    open_aantal: int = 0  # kaartjes mét status 'vraag' (afgekeurd / te corrigeren)
    zonder_uren_aantal: int = 0  # geplande kaartjes zonder uren (t/m gisteren)


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
    # 15-09: weektotaal van de urenstatus over de kaartjes van deze rij.
    week_uren: WeekUrenData = field(default_factory=WeekUrenData)


@dataclass(frozen=True)
class PoolPersoonData:
    """Persoon in de zijbalk-pool: alle (niet-geblokkeerde) ZZP'ers en uitvoerders, met het
    aantal geplande dagen deze week (heel = 1, half = 0,5 — besluit C kleurt > 5)."""

    gebruiker_id: uuid.UUID
    naam: str
    rol: str
    geplande_dagen: Decimal
    # v3 (18-09): einddatum van een afwezigheid die de getoonde week overlapt ("afwezig t/m …"), anders None.
    afwezig_tot: date | None = None


@dataclass(frozen=True)
class ReserveringData:
    """Kaart zonder ploeg (v3 18-09): project × dag "gereserveerd"."""

    id: uuid.UUID
    project_id: uuid.UUID
    projectnaam: str | None
    datum: date


@dataclass(frozen=True)
class AfwezigheidData:
    id: uuid.UUID
    gebruiker_id: uuid.UUID
    van: date
    tot: date
    reden: str | None
    beeindigd_op: object = None  # datetime | None


@dataclass(frozen=True)
class BulkItemResultaat:
    """Uitkomst per bulk-item: gedaan | overgeslagen (idempotent/onbestaand) | conflict (WEL gepland, gemarkeerd)."""

    gebruiker_id: uuid.UUID
    project_id: uuid.UUID
    datum: date
    dagdeel: str
    uitkomst: str
    reden: str | None = None
    conflict: str | None = None  # 'project' | 'afwezig'
    conflict_projectnaam: str | None = None


@dataclass(frozen=True)
class BulkResultaat:
    correlatie_id: uuid.UUID
    aangemaakt: list[BulkItemResultaat]
    resultaten: list[BulkItemResultaat]


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
    # v3 (18-09): reserveringen (kaart zonder ploeg) en afwezigheid die de week overlapt.
    reserveringen: list[ReserveringData] = field(default_factory=list)
    afwezigheid: list[AfwezigheidData] = field(default_factory=list)


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


# --- urenstatus in het grid (Peter/Haci 15-09) ------------------------------------------------------

UREN_STATUS_GEEN = "geen"
UREN_STATUS_INGEVULD = "ingevuld"
UREN_STATUS_GEKEURD = "gekeurd"
UREN_STATUS_VRAAG = "vraag"


@dataclass(frozen=True)
class _UrenStand:
    status: str
    uren: Decimal | None
    m2: Decimal | None
    detail: str | None
    weekstaat_id: uuid.UUID | None


def _fmt_moment(moment) -> str:  # noqa: ANN001 — datetime | None
    return f"{kalenderdag_nl(moment).strftime('%d-%m')} {moment.astimezone().strftime('%H:%M')}" if moment else "—"


def _urenstanden_voor_week(
    session, *, administratie_id: uuid.UUID, maandag: date, zondag: date, namen: dict[uuid.UUID, str | None]
) -> dict[tuple[uuid.UUID, uuid.UUID, date], _UrenStand]:
    """ÉÉN statement over WeekstaatDag × Weekstaat voor de week (set-based; het grid blijft op een constant aantal
    statements, meetlat `tests/uren/test_planning_urenstatus.py`) → per (persoon, project, dag) de stand. Namen van
    keurders in één batch. Deterministische afleiding: goedgekeurd → 'gekeurd'; corrigeren → 'vraag'; concept/ingediend
    mét uren > 0 → 'ingevuld'; anders geen rij → 'geen'."""
    rijen = session.execute(
        select(WeekstaatDag, Weekstaat)
        .join(Weekstaat, Weekstaat.id == WeekstaatDag.weekstaat_id)
        .where(
            WeekstaatDag.administratie_id == administratie_id,
            WeekstaatDag.datum >= maandag,
            WeekstaatDag.datum <= zondag,
        )
    ).all()
    if not rijen:
        return {}
    keurders = {s.goedgekeurd_door for _, s in rijen if s.goedgekeurd_door} | {
        s.afgekeurd_door for _, s in rijen if s.afgekeurd_door
    }
    keurders -= set(namen)
    if keurders:
        for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(keurders))).all():
            namen[g.id] = g.naam
    uit: dict[tuple[uuid.UUID, uuid.UUID, date], _UrenStand] = {}
    for dag, staat in rijen:
        uren = Decimal(dag.uren or 0)
        if staat.status == WeekstaatStatus.GOEDGEKEURD.value:
            status = UREN_STATUS_GEKEURD
            keurder = namen.get(staat.goedgekeurd_door) or "uitvoerder"
            detail = f"gekeurd door {keurder} op {_fmt_moment(staat.goedgekeurd_op)}"
        elif staat.status == WeekstaatStatus.CORRIGEREN.value:
            status = UREN_STATUS_VRAAG
            detail = (
                f"afgekeurd door {namen.get(staat.afgekeurd_door) or 'uitvoerder'} op {_fmt_moment(staat.afgekeurd_op)}"
                + (f": {staat.afkeur_reden}" if staat.afkeur_reden else "")
            )
        elif uren > 0:
            status = UREN_STATUS_INGEVULD
            detail = (
                f"ingediend {_fmt_moment(staat.ingediend_op)}"
                if staat.status == WeekstaatStatus.INGEDIEND.value
                else f"ingevuld (concept) {_fmt_moment(staat.bijgewerkt_op)}"
            )
        else:
            continue  # dagrij zonder uren = alsof er geen uren zijn
        uit[(staat.gebruiker_id, staat.project_id, dag.datum)] = _UrenStand(
            status=status, uren=uren, m2=dag.m2, detail=detail, weekstaat_id=staat.id
        )
    return uit


def _uren_kort(stand: _UrenStand | None) -> str:
    if stand is None:
        return "geen uren"
    delen = [f"{stand.uren.normalize():f} u".replace(".", ",")] if stand.uren is not None else []
    if stand.m2:
        delen.append(f"{stand.m2.normalize():f} m²".replace(".", ","))
    return " · ".join(delen) or stand.status


# --- terugwerkende kracht (Peter/Haci 15-09): achteraf-vlag + bundelmelding aan de veldwerker -------------


def _is_achteraf(aangemaakt_op, datum: date) -> bool:  # noqa: ANN001 — datetime
    """Gepland ná de dag zelf (NL-kalenderdag van het planmoment > geplande datum) — chip "achteraf gepland"."""
    return aangemaakt_op is not None and kalenderdag_nl(aangemaakt_op) > datum


def week_is_verstreken_of_lopend(datum: date, vandaag: date) -> bool:
    """De ISO-week van `datum` ligt vóór of ís de huidige week — een wijziging daar is 'met terugwerkende kracht'
    (verstreken) of 'in de lopende week' en verdient een melding aan de veldwerker; een toekomstige week niet."""
    return datum.isocalendar()[:2] <= vandaag.isocalendar()[:2]


def _registreer_wijziging_in_week(
    session,
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    datum: date,
    actor_id: uuid.UUID,
    soort: str,
    vandaag: date | None = None,
) -> bool:
    """Bij een planningwijziging in een verstreken/lopende week: één OPEN melding-rij per (administratie, veldwerker,
    week) bijhouden (aantal_wijzigingen++) — de job bundelt en verstuurt. Toekomstige week = niets (False). Nooit een
    blokkade (besluit minimale mens); de audit-rij van de mutatie draagt `achteraf`/`week_status`."""
    vandaag = vandaag or vandaag_nl()
    if not week_is_verstreken_of_lopend(datum, vandaag):
        return False
    jaar, week, _ = datum.isocalendar()
    open_rij = session.scalars(
        select(PlanningWijzigingMelding).where(
            PlanningWijzigingMelding.administratie_id == administratie_id,
            PlanningWijzigingMelding.gebruiker_id == gebruiker_id,
            PlanningWijzigingMelding.jaar == jaar,
            PlanningWijzigingMelding.weeknummer == week,
            PlanningWijzigingMelding.gemeld_op.is_(None),
        )
    ).first()
    if open_rij is None:
        session.add(
            PlanningWijzigingMelding(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                jaar=jaar,
                weeknummer=week,
                aangemaakt_door=actor_id,
                detail={"soorten": [soort]},
            )
        )
    else:
        open_rij.aantal_wijzigingen = int(open_rij.aantal_wijzigingen or 0) + 1
        soorten = list((open_rij.detail or {}).get("soorten") or [])
        soorten.append(soort)
        open_rij.detail = {**(open_rij.detail or {}), "soorten": soorten[-20:]}
    return True


def _week_status(datum: date, vandaag: date) -> str:
    if datum.isocalendar()[:2] < vandaag.isocalendar()[:2]:
        return "verstreken"
    if datum.isocalendar()[:2] == vandaag.isocalendar()[:2]:
        return "lopend"
    return "toekomst"


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


def _plan_in_sessie(
    session,
    *,
    administratie_id: uuid.UUID,
    gebruiker: Gebruiker,
    project_id: uuid.UUID,
    datum: date,
    dagdeel: str,
    actor_id: uuid.UUID,
    vandaag: date,
    correlatie_id: uuid.UUID | None = None,
    bron: str | None = None,
    extra_audit: dict | None = None,
    al_getoetst: bool = False,
    koppeling_al_gedaan: bool = False,
) -> None:
    """Eén kaartje in een bestaande sessie (gedeeld door de losse route en de bulkroute 18-09): failsafe op de PK, auto-
    projectkoppeling (besluit A), melding-rij per veldwerker × week (15-09) en de audit-rij per (persoon, dag). De bulk
    zet `al_getoetst`/`koppeling_al_gedaan` omdat hij de bestaande toewijzingen in één query heeft gelezen en de
    koppeling per (persoon, project) één keer doet — zo blijft het leeswerk onafhankelijk van het aantal items."""
    bestaat = (
        not al_getoetst
        and session.get(PlanningToewijzing, (administratie_id, gebruiker.id, project_id, datum)) is not None
    )
    if bestaat:
        raise OngeldigeInvoer(
            f"{gebruiker.naam} staat op {datum} al op dit project gepland — "
            "één kaartje per persoon per project per dag"
        )
    if not koppeling_al_gedaan:
        _zorg_voor_projectkoppeling(
            session, administratie_id=administratie_id, gebruiker=gebruiker, project_id=project_id, actor_id=actor_id
        )
    session.add(
        PlanningToewijzing(
            administratie_id=administratie_id,
            gebruiker_id=gebruiker.id,
            project_id=project_id,
            datum=datum,
            dagdeel=dagdeel,
            toegevoegd_door=actor_id,
        )
    )
    gemeld = _registreer_wijziging_in_week(
        session, administratie_id=administratie_id, gebruiker_id=gebruiker.id, datum=datum, actor_id=actor_id,
        soort="gepland", vandaag=vandaag,
    )
    nieuwe_waarde = {
        "gebruiker_id": str(gebruiker.id),
        "project_id": str(project_id),
        "datum": datum.isoformat(),
        "dagdeel": dagdeel,
        # 15-09: terugwerkende kracht zichtbaar in de audit (geen blokkade).
        "achteraf": datum < vandaag,
        "week_status": _week_status(datum, vandaag),
        "veldwerker_gemeld": gemeld,
    }
    if correlatie_id is not None:
        nieuwe_waarde["bulk_correlatie_id"] = str(correlatie_id)
    if bron is not None:
        nieuwe_waarde["bron"] = bron
    if extra_audit:
        nieuwe_waarde.update(extra_audit)
    record_audit_event(
        session,
        actor_id=actor_id,
        module=MODULE,
        tabel="planning_toewijzing",
        record_id=gebruiker.id,
        actie="planning_gepland",
        correlatie_id=project_id,
        nieuwe_waarde=nieuwe_waarde,
        administratie_id=administratie_id,
    )


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
        _plan_in_sessie(
            session,
            administratie_id=administratie_id,
            gebruiker=gebruiker,
            project_id=project_id,
            datum=datum,
            dagdeel=dagdeel,
            actor_id=actor_id,
            vandaag=vandaag_nl(),
        )


def _verwijder_in_sessie(
    session,
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    datum: date,
    actor_id: uuid.UUID,
    vandaag: date,
    correlatie_id: uuid.UUID | None = None,
    bron: str | None = None,
) -> bool:
    """Eén kaartje weghalen in een bestaande sessie (losse route + bulk). False = bestond niet (idempotent)."""
    rij = session.get(PlanningToewijzing, (administratie_id, gebruiker_id, project_id, datum))
    if rij is None:
        return False
    oude_waarde = {
        "gebruiker_id": str(gebruiker_id),
        "project_id": str(project_id),
        "datum": datum.isoformat(),
        "dagdeel": rij.dagdeel,
    }
    session.delete(rij)
    gemeld = _registreer_wijziging_in_week(
        session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, datum=datum, actor_id=actor_id,
        soort="verwijderd", vandaag=vandaag,
    )
    nieuwe_waarde = {
        "achteraf": datum < vandaag,
        "week_status": _week_status(datum, vandaag),
        "veldwerker_gemeld": gemeld,
    }
    if correlatie_id is not None:
        nieuwe_waarde["bulk_correlatie_id"] = str(correlatie_id)
    if bron is not None:
        nieuwe_waarde["bron"] = bron
    record_audit_event(
        session,
        actor_id=actor_id,
        module=MODULE,
        tabel="planning_toewijzing",
        record_id=gebruiker_id,
        actie="planning_verwijderd",
        correlatie_id=project_id,
        oude_waarde=oude_waarde,
        nieuwe_waarde=nieuwe_waarde,
        administratie_id=administratie_id,
    )
    return True


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
        _verwijder_in_sessie(
            session,
            administratie_id=administratie_id,
            gebruiker_id=gebruiker_id,
            project_id=project_id,
            datum=datum,
            actor_id=actor_id,
            vandaag=vandaag_nl(),
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
        vandaag = vandaag_nl()
        gemeld_van = _registreer_wijziging_in_week(
            session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, datum=van_datum, actor_id=actor_id,
            soort="verplaatst", vandaag=vandaag,
        )
        gemeld_naar = (
            _registreer_wijziging_in_week(
                session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, datum=naar_datum,
                actor_id=actor_id, soort="verplaatst", vandaag=vandaag,
            )
            if naar_datum.isocalendar()[:2] != van_datum.isocalendar()[:2]
            else gemeld_van
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
                "achteraf": naar_datum < vandaag or van_datum < vandaag,
                "week_status": _week_status(naar_datum, vandaag),
                "veldwerker_gemeld": gemeld_van or gemeld_naar,
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


# --- kantoor: bulk (vulhandvat / ploeg / ongedaan) — planning v3 dag-eerst (Peter 18-09) -----------


def _afwezigheid_in_venster(
    session, *, administratie_id: uuid.UUID, van: date, tot: date, gebruiker_ids: set[uuid.UUID] | None = None
) -> list[VeldwerkerAfwezigheid]:
    """Alle afwezigheidsrijen die [van, tot] overlappen — één statement (set-based)."""
    q = select(VeldwerkerAfwezigheid).where(
        VeldwerkerAfwezigheid.administratie_id == administratie_id,
        VeldwerkerAfwezigheid.van <= tot,
        VeldwerkerAfwezigheid.tot >= van,
    )
    if gebruiker_ids is not None:
        if not gebruiker_ids:
            return []
        q = q.where(VeldwerkerAfwezigheid.gebruiker_id.in_(gebruiker_ids))
    return list(session.scalars(q.order_by(VeldwerkerAfwezigheid.van)))


def _is_afwezig(
    afwezigheid: list[VeldwerkerAfwezigheid], gebruiker_id: uuid.UUID, datum: date
) -> VeldwerkerAfwezigheid | None:
    for a in afwezigheid:
        if a.gebruiker_id == gebruiker_id and a.van <= datum <= a.tot:
            return a
    return None


def plan_bulk(
    *,
    administratie_id: uuid.UUID,
    items: list[tuple[uuid.UUID, uuid.UUID, date, str]],
    bron: str,
    verwijderen: bool = False,
    correlatie_id: uuid.UUID | None = None,
    actor_id: uuid.UUID,
    vandaag: date | None = None,
) -> BulkResultaat:
    """Vulhandvat, ploeg-paneel en "Ongedaan maken" (mockup v3 ② + ③, Peter 18-09) in ÉÉN transactie — 16 persoon-dagen
    in 16 losse requests met tussenstanden was onaanvaardbaar (half gelukt = half-planning zichtbaar).

    Per item `(gebruiker_id, project_id, datum, dagdeel)`:
    - `gedaan` — geplaatst (of verwijderd bij `verwijderen=True`);
    - `overgeslagen` — bestond al (idempotent: dezelfde set twee keer indienen = alles overgeslagen) of, bij
      verwijderen, bestond niet;
    - `conflict` — WEL geplaatst, maar gemarkeerd: de persoon staat die dag al op een ánder project
      (`conflict='project'`, mét projectnaam) of is afwezig (`conflict='afwezig'`). Kantoor beslist — nooit blokkerend
      (mockup-notitie).
    Een échte fout (onbekend/inactief project, niet-planbare persoon, geen opt-in, geen recht) rolt ALLES terug
    (UrenFout → 4xx). Limiet `BULK_MAX_ITEMS`; lege lijst = 422. Elke audit-rij per (persoon, dag) draagt
    `bulk_correlatie_id` + `bron`; één extra audit-rij `planning_bulk` vat de aanroep samen (tellers per uitkomst).
    Set-based: één query voor de bestaande toewijzingen, één voor afwezigheid, één per uniek project, één per unieke
    persoon, de projectkoppeling één keer per (persoon, project) — onafhankelijk van het aantal items."""
    if bron not in BULK_BRONNEN:
        raise OngeldigeInvoer(f"Onbekende bron {bron!r} (vulhandvat, ploeg of ongedaan)")
    if not items:
        raise OngeldigeInvoer("Geen items om te plannen")
    if len(items) > BULK_MAX_ITEMS:
        raise OngeldigeInvoer(f"Hoogstens {BULK_MAX_ITEMS} items per aanroep ({len(items)} aangeboden)")
    for _, _, _, dagdeel in items:
        _vereis_dagdeel(dagdeel)
    correlatie_id = correlatie_id or uuid.uuid4()
    vandaag = vandaag or vandaag_nl()
    # Dubbele items binnen één aanroep: de eerste telt, de rest is overgeslagen (idempotent binnen de set).
    gezien: set[tuple[uuid.UUID, uuid.UUID, date]] = set()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        project_ids = {p for _, p, _, _ in items}
        gebruiker_ids = {g for g, _, _, _ in items}
        datums = {d for _, _, d, _ in items}
        projecten: dict[uuid.UUID, ProjectCache] = {}
        if not verwijderen:
            for pid in project_ids:
                projecten[pid] = _vereis_actief_project(session, administratie_id, pid)
        gebruikers: dict[uuid.UUID, Gebruiker] = {}
        for gid in gebruiker_ids:
            gebruikers[gid] = _vereis_planbare_gebruiker(session, gid) if not verwijderen else _gebruiker(session, gid)
        # Bestaande toewijzingen van deze personen op deze datums — één statement; voedt idempotentie én de
        # conflict-toets.
        bestaand = list(
            session.scalars(
                select(PlanningToewijzing).where(
                    PlanningToewijzing.administratie_id == administratie_id,
                    PlanningToewijzing.gebruiker_id.in_(gebruiker_ids),
                    PlanningToewijzing.datum.in_(datums),
                )
            )
        )
        bestaand_sleutels = {(t.gebruiker_id, t.project_id, t.datum) for t in bestaand}
        elders: dict[tuple[uuid.UUID, date], list[uuid.UUID]] = {}
        for t in bestaand:
            elders.setdefault((t.gebruiker_id, t.datum), []).append(t.project_id)
        andere_projecten = {pid for lijst in elders.values() for pid in lijst} - set(projecten)
        projectnamen = {pid: p.naam for pid, p in projecten.items()}
        if andere_projecten:
            for p in session.scalars(select(ProjectCache).where(ProjectCache.id.in_(andere_projecten))).all():
                projectnamen[p.id] = p.naam
        afwezigheid = (
            _afwezigheid_in_venster(
                session,
                administratie_id=administratie_id,
                van=min(datums),
                tot=max(datums),
                gebruiker_ids=gebruiker_ids,
            )
            if not verwijderen
            else []
        )

        resultaten: list[BulkItemResultaat] = []
        aangemaakt: list[BulkItemResultaat] = []
        gekoppeld: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for gid, pid, datum, dagdeel in items:
            sleutel = (gid, pid, datum)
            if sleutel in gezien:
                resultaten.append(
                    BulkItemResultaat(gid, pid, datum, dagdeel, "overgeslagen", reden="dubbel in dezelfde aanroep")
                )
                continue
            gezien.add(sleutel)
            if verwijderen:
                if sleutel not in bestaand_sleutels:
                    resultaten.append(
                        BulkItemResultaat(gid, pid, datum, dagdeel, "overgeslagen", reden="stond niet gepland")
                    )
                    continue
                _verwijder_in_sessie(
                    session, administratie_id=administratie_id, gebruiker_id=gid, project_id=pid, datum=datum,
                    actor_id=actor_id, vandaag=vandaag, correlatie_id=correlatie_id, bron=bron,
                )
                r = BulkItemResultaat(gid, pid, datum, dagdeel, "gedaan")
                resultaten.append(r)
                aangemaakt.append(r)
                continue
            if sleutel in bestaand_sleutels:
                resultaten.append(
                    BulkItemResultaat(gid, pid, datum, dagdeel, "overgeslagen", reden="stond al op dit project gepland")
                )
                continue
            conflict: str | None = None
            conflict_naam: str | None = None
            reden: str | None = None
            afw = _is_afwezig(afwezigheid, gid, datum)
            elders_pids = [x for x in elders.get((gid, datum), []) if x != pid]
            if afw is not None:
                conflict = "afwezig"
                reden = f"{gebruikers[gid].naam} is afwezig t/m {afw.tot.isoformat()}"
                if afw.reden:
                    reden += f" ({afw.reden})"
            elif elders_pids:
                conflict = "project"
                conflict_naam = projectnamen.get(elders_pids[0])
                elders_naam = conflict_naam or "een ander project"
                reden = f"{gebruikers[gid].naam} staat op {datum.isoformat()} al op {elders_naam}"
            _plan_in_sessie(
                session,
                administratie_id=administratie_id,
                gebruiker=gebruikers[gid],
                project_id=pid,
                datum=datum,
                dagdeel=dagdeel,
                actor_id=actor_id,
                vandaag=vandaag,
                correlatie_id=correlatie_id,
                bron=bron,
                extra_audit={"conflict": conflict} if conflict else None,
                al_getoetst=True,
                koppeling_al_gedaan=(gid, pid) in gekoppeld,
            )
            gekoppeld.add((gid, pid))
            # Na het plaatsen telt dit kaartje mee als "elders" voor volgende items van dezelfde persoon × dag.
            elders.setdefault((gid, datum), []).append(pid)
            bestaand_sleutels.add(sleutel)
            r = BulkItemResultaat(
                gid, pid, datum, dagdeel, "conflict" if conflict else "gedaan",
                reden=reden, conflict=conflict, conflict_projectnaam=conflict_naam,
            )
            resultaten.append(r)
            aangemaakt.append(r)

        tellers = {u: sum(1 for r in resultaten if r.uitkomst == u) for u in ("gedaan", "overgeslagen", "conflict")}
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_toewijzing",
            record_id=correlatie_id,
            actie="planning_bulk",
            correlatie_id=correlatie_id,
            nieuwe_waarde={
                "bron": bron,
                "verwijderen": verwijderen,
                "aantal_items": len(items),
                **tellers,
                "datums": sorted(d.isoformat() for d in datums),
            },
            administratie_id=administratie_id,
        )
        return BulkResultaat(correlatie_id=correlatie_id, aangemaakt=aangemaakt, resultaten=resultaten)


# --- kantoor: reservering (kaart zonder ploeg) — v3 -------------------------------------------------


def _reservering_data(r: PlanningReservering, projectnaam: str | None) -> ReserveringData:
    return ReserveringData(id=r.id, project_id=r.project_id, projectnaam=projectnaam, datum=r.datum)


def maak_reservering(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, datum: date, actor_id: uuid.UUID
) -> tuple[ReserveringData, bool]:
    """Projecttegel → dag = lege kaart "gereserveerd". Idempotent: bestaat al → (rij, False). Geaudit."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        project = _vereis_actief_project(session, administratie_id, project_id)
        bestaand = session.scalars(
            select(PlanningReservering).where(
                PlanningReservering.administratie_id == administratie_id,
                PlanningReservering.project_id == project_id,
                PlanningReservering.datum == datum,
            )
        ).first()
        if bestaand is not None:
            return _reservering_data(bestaand, project.naam), False
        rij = PlanningReservering(
            administratie_id=administratie_id, project_id=project_id, datum=datum, aangemaakt_door=actor_id
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_reservering",
            record_id=rij.id,
            actie="planning_gereserveerd",
            correlatie_id=project_id,
            nieuwe_waarde={"project_id": str(project_id), "datum": datum.isoformat(), "projectnaam": project.naam},
            administratie_id=administratie_id,
        )
        return _reservering_data(rij, project.naam), True


def verwijder_reservering(*, administratie_id: uuid.UUID, reservering_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Idempotent; geaudit (oude waarde in de audit — niets verdwijnt stil)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        rij = session.get(PlanningReservering, reservering_id)
        if rij is None or rij.administratie_id != administratie_id:
            return
        oude = {"project_id": str(rij.project_id), "datum": rij.datum.isoformat()}
        session.delete(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_reservering",
            record_id=reservering_id,
            actie="planning_reservering_verwijderd",
            correlatie_id=uuid.UUID(oude["project_id"]),
            oude_waarde=oude,
            administratie_id=administratie_id,
        )


# --- kantoor: afwezigheid (minimaal — "op deze dagen niet plannen") — v3 slice 5 -------------------


def _vereis_afwezigheid_recht(session, actor_id: uuid.UUID) -> None:
    """Module-recht 'Meerwerk & urenstaten' ÓF 'veldwerkerbeheer' (spiegel van
    `require_veldwerkerbeheer_of_meerwerk_recht`)."""
    actor = _gebruiker(session, actor_id)
    if heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol) or heeft_veldwerkerbeheer_recht(
        gebruiker_id=actor_id, rol=actor.rol
    ):
        return
    raise GeenToegang("Afwezigheid beheren vereist het recht 'Meerwerk & urenstaten' of 'veldwerkerbeheer'")


def _afwezigheid_data(a: VeldwerkerAfwezigheid) -> AfwezigheidData:
    return AfwezigheidData(
        id=a.id, gebruiker_id=a.gebruiker_id, van=a.van, tot=a.tot, reden=a.reden, beeindigd_op=a.beeindigd_op
    )


def afwezigheid_overzicht(
    *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID | None, actor_id: uuid.UUID
) -> list[AfwezigheidData]:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_afwezigheid_recht(session, actor_id)
        q = select(VeldwerkerAfwezigheid).where(VeldwerkerAfwezigheid.administratie_id == administratie_id)
        if gebruiker_id is not None:
            q = q.where(VeldwerkerAfwezigheid.gebruiker_id == gebruiker_id)
        return [_afwezigheid_data(a) for a in session.scalars(q.order_by(VeldwerkerAfwezigheid.van.desc()))]


def voeg_afwezigheid_toe(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    van: date,
    tot: date,
    reden: str | None,
    actor_id: uuid.UUID,
) -> AfwezigheidData:
    """Nieuwe periode; overlap met een bestaande periode van dezelfde persoon = OngeldigeOvergang (409, leesbaar)."""
    if tot < van:
        raise OngeldigeInvoer("De einddatum ligt vóór de begindatum")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_afwezigheid_recht(session, actor_id)
        gebruiker = _vereis_planbare_gebruiker(session, gebruiker_id)
        overlap = _afwezigheid_in_venster(
            session, administratie_id=administratie_id, van=van, tot=tot, gebruiker_ids={gebruiker_id}
        )
        if overlap:
            o = overlap[0]
            raise OngeldigeOvergang(
                f"{gebruiker.naam} is al afwezig gemeld van {o.van.isoformat()} t/m {o.tot.isoformat()} — "
                "beëindig of verkort die periode eerst"
            )
        rij = VeldwerkerAfwezigheid(
            administratie_id=administratie_id,
            gebruiker_id=gebruiker_id,
            van=van,
            tot=tot,
            reden=(reden or "").strip() or None,
            aangemaakt_door=actor_id,
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="veldwerker_afwezigheid",
            record_id=rij.id,
            actie="afwezigheid_toegevoegd",
            correlatie_id=gebruiker_id,
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker_id),
                "van": van.isoformat(),
                "tot": tot.isoformat(),
                "reden": rij.reden,
            },
            administratie_id=administratie_id,
        )
        return _afwezigheid_data(rij)


def beeindig_afwezigheid(
    *, administratie_id: uuid.UUID, afwezigheid_id: uuid.UUID, tot: date, actor_id: uuid.UUID
) -> AfwezigheidData:
    """Nooit verwijderen: `tot` vervroegen (≥ van) + `beeindigd_op`; audit oud→nieuw. Verlengen hoort hier niet (nieuwe
    periode)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_afwezigheid_recht(session, actor_id)
        rij = session.get(VeldwerkerAfwezigheid, afwezigheid_id)
        if rij is None or rij.administratie_id != administratie_id:
            raise NietGevonden("Deze afwezigheid bestaat niet")
        if tot < rij.van:
            raise OngeldigeInvoer("De nieuwe einddatum ligt vóór de begindatum — kies minimaal de begindatum")
        if tot > rij.tot:
            raise OngeldigeInvoer("Beëindigen kan alleen vervroegen; een langere afwezigheid = nieuwe periode")
        oud = rij.tot
        rij.tot = tot
        rij.beeindigd_op = func.now()
        session.flush()
        session.refresh(rij)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="veldwerker_afwezigheid",
            record_id=rij.id,
            actie="afwezigheid_beeindigd",
            correlatie_id=rij.gebruiker_id,
            oude_waarde={"tot": oud.isoformat()},
            nieuwe_waarde={"tot": tot.isoformat()},
            administratie_id=administratie_id,
        )
        return _afwezigheid_data(rij)


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
    vandaag = vandaag or vandaag_nl()
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

        # 15-09: urenstatus per kaartje uit de weekstaten van deze week — één statement voor het hele grid.
        urenstanden = _urenstanden_voor_week(
            session, administratie_id=administratie_id, maandag=maandag, zondag=zondag, namen=namen
        )

        rijen: list[ProjectRijData] = []
        for project in projecten:
            spec = specs.get(project.id)
            eigen = per_project.get(project.id, [])
            per_datum: dict[str, list[PlanningKaartData]] = {}
            week_uren = WeekUrenData()
            ingevuld = gekeurd = Decimal("0")
            open_aantal = zonder_uren = 0
            for t in sorted(eigen, key=lambda t: (t.datum, namen.get(t.gebruiker_id) or "")):
                stand = urenstanden.get((t.gebruiker_id, project.id, t.datum))
                if stand is None and t.datum < vandaag:
                    zonder_uren += 1
                if stand is not None:
                    ingevuld += stand.uren or 0
                    if stand.status == UREN_STATUS_GEKEURD:
                        gekeurd += stand.uren or 0
                    if stand.status == UREN_STATUS_VRAAG:
                        open_aantal += 1
                per_datum.setdefault(t.datum.isoformat(), []).append(
                    PlanningKaartData(
                        gebruiker_id=t.gebruiker_id,
                        naam=namen.get(t.gebruiker_id),
                        rol=rollen.get(t.gebruiker_id, "zzper"),
                        dagdeel=t.dagdeel,
                        uren_status=stand.status if stand else UREN_STATUS_GEEN,
                        uren=stand.uren if stand else None,
                        m2=stand.m2 if stand else None,
                        uren_detail=(f"{_uren_kort(stand)} · {stand.detail}" if stand else "geen uren ingevuld"),
                        weekstaat_id=stand.weekstaat_id if stand else None,
                        achteraf=_is_achteraf(t.aangemaakt_op, t.datum),
                    )
                )
            week_uren = WeekUrenData(
                ingevuld_uren=ingevuld, gekeurd_uren=gekeurd, open_aantal=open_aantal, zonder_uren_aantal=zonder_uren
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
                    week_uren=week_uren,
                )
            )

        geplande_dagen: dict[uuid.UUID, Decimal] = {}
        for t in toewijzingen:
            geplande_dagen[t.gebruiker_id] = geplande_dagen.get(t.gebruiker_id, Decimal("0")) + _DAGDEEL_WAARDE.get(
                t.dagdeel, Decimal("1")
            )
        # v3 (18-09): afwezigheid die de week overlapt (één statement) → pool "afwezig t/m …" + lijst voor het paneel.
        afwezig_rijen = _afwezigheid_in_venster(session, administratie_id=administratie_id, van=maandag, tot=zondag)
        afwezig_tot: dict[uuid.UUID, date] = {}
        for a in afwezig_rijen:
            if a.gebruiker_id not in afwezig_tot or a.tot > afwezig_tot[a.gebruiker_id]:
                afwezig_tot[a.gebruiker_id] = a.tot
        pool = [
            PoolPersoonData(
                gebruiker_id=g.id,
                naam=g.naam,
                rol=g.rol.value,
                geplande_dagen=geplande_dagen.get(g.id, Decimal("0")),
                afwezig_tot=afwezig_tot.get(g.id),
            )
            for g in pool_gebruikers
        ]
        # v3 (18-09): reserveringen (kaart zonder ploeg) deze week — één statement; projectnaam uit de al geladen rijen.
        projectnaam_per_id = {p.id: p.naam for p in projecten}
        reserveringen = [
            _reservering_data(r, projectnaam_per_id.get(r.project_id))
            for r in session.scalars(
                select(PlanningReservering)
                .where(
                    PlanningReservering.administratie_id == administratie_id,
                    PlanningReservering.datum >= maandag,
                    PlanningReservering.datum <= zondag,
                )
                .order_by(PlanningReservering.datum)
            )
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
            reserveringen=reserveringen,
            afwezigheid=[_afwezigheid_data(a) for a in afwezig_rijen],
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
