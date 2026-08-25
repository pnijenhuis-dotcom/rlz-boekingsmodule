"""Uren & meerwerk — leesroutes voor de native app (fase 2, mockup uren-uitvoerder.html).

Multi-administratie volgens het accordeur-wachtrij-patroon: de scope komt uit
auth_service.mijn_administraties, per administratie een eigen scoped_session (RLS dwingt de
grens af), resultaten samengevoegd. Administraties zónder de uren-&-meerwerk-opt-in worden
stil overgeslagen (de module bestaat daar niet).

"Open weken" (mockup: chip "2 weken open" / "nog invullen") is deterministisch gedefinieerd:
de ISO-weken in het venster [max(koppelingsweek, huidige week − (VENSTER−1)) … huidige week]
waarvoor geen weekstaat bestaat of de staat nog in concept/corrigeren staat, plus élke staat
in corrigeren buiten dat venster (een afgekeurde week moet altijd terugkomen, hoe oud ook).
De indien-deadline (ma 09:00) is een zichtbare afspraak in de app, geen berekening hier."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.auth import service as auth_service
from app.db.models import Administratie, DetacheerderKoppeling, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.sync.models import ProjectCache, VendorCache
from app.uren import service
from app.uren.models import (
    Meerwerk,
    MeerwerkStatus,
    ProjectDocument,
    ProjectSpecificatie,
    UrenProjectToewijzing,
    VeldwerkerCrediteur,
    Weekstaat,
    WeekstaatCorrectie,
    WeekstaatDag,
    WeekstaatStatus,
)
from app.uren.service import (
    GeenToegang,
    MeerwerkData,
    NietGevonden,
    WeekstaatData,
    _gebruiker,
    _heeft_toewijzing,
    _meerwerk,
    _meerwerk_data,
    _vereis_invuller,
    _weekstaat,
    _weekstaat_data,
)

OPEN_WEKEN_VENSTER = 6  # huidige week + 5 ervoor

OPEN_STATUSSEN = (WeekstaatStatus.CONCEPT.value, WeekstaatStatus.CORRIGEREN.value)


# --- data ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectKaart:
    administratie_id: uuid.UUID
    administratie_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None
    soort_werk: str | None
    open_weken: int
    laatste_invoer: date | None


@dataclass(frozen=True)
class WeekKaart:
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    status: str  # 'nieuw' = nog geen staat
    weekstaat_id: uuid.UUID | None
    dagen_ingevuld: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: object | None
    goedgekeurd_door_naam: str | None
    afgekeurd_door_naam: str | None
    afkeur_reden: str | None


@dataclass(frozen=True)
class IngediendeWeek:
    weekstaat_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None
    jaar: int
    weeknummer: int
    status: str
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: object | None
    ingediend_namens: bool
    goedgekeurd_door_naam: str | None
    afgekeurd_door_naam: str | None
    afkeur_reden: str | None


@dataclass(frozen=True)
class ZzperKaart:
    gebruiker_id: uuid.UUID
    naam: str
    aantal_projecten: int
    open_weken: int
    laatste_invoer: date | None


@dataclass(frozen=True)
class TeKeurenItem:
    weekstaat_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    zzper_id: uuid.UUID
    zzper_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None
    jaar: int
    weeknummer: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: object | None
    ingediend_namens: bool
    ingediend_door_naam: str | None


@dataclass(frozen=True)
class ProjectDocumentKaart:
    id: uuid.UUID
    soort: str
    titel: str
    versie_omschrijving: str | None
    bestandsnaam: str


@dataclass(frozen=True)
class UitvoerderProjectKaart:
    administratie_id: uuid.UUID
    administratie_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None
    soort_werk: str | None
    contract_m2: Decimal | None
    gebouwd_m2: Decimal
    looptijd_tot: date | None
    huurtijd_omschrijving: str | None
    meerwerk_gemeld: int
    te_keuren: int


@dataclass(frozen=True)
class ProjectDetail:
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None
    opdrachtgever: str | None
    werknummer_opdrachtgever: str | None
    soort_werk: str | None
    contract_m2: Decimal | None
    gebouwd_m2: Decimal
    looptijd_van: date | None
    looptijd_tot: date | None
    huurtijd_omschrijving: str | None
    doorlopende_huur_omschrijving: str | None
    documenten: list[ProjectDocumentKaart]
    meerwerk: list[MeerwerkData]


# --- helpers ---------------------------------------------------------------------------------


def _administraties_met_opt_in(actor_id: uuid.UUID, rol: GebruikerRol) -> list[Administratie]:
    return [a for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol) if a.uren_meerwerk_ingeschakeld]


def _weken_terug(vandaag: date, aantal: int) -> list[tuple[int, int]]:
    """(jaar, week) van de huidige ISO-week en de `aantal-1` weken ervoor, nieuwste eerst."""
    iso = vandaag.isocalendar()
    maandag = date.fromisocalendar(iso[0], iso[1], 1)
    weken: list[tuple[int, int]] = []
    for i in range(aantal):
        c = (maandag - timedelta(weeks=i)).isocalendar()
        weken.append((c[0], c[1]))
    return weken


def _week_sleutel(d: date) -> tuple[int, int]:
    c = d.isocalendar()
    return (c[0], c[1])


def _dag_sommen(session, weekstaat_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, Decimal, Decimal, date | None]]:
    """Per weekstaat: (aantal dagen, som uren, som m², laatste dag-datum) in één query."""
    if not weekstaat_ids:
        return {}
    rijen = session.execute(
        select(
            WeekstaatDag.weekstaat_id,
            func.count(),
            func.coalesce(func.sum(WeekstaatDag.uren), 0),
            func.coalesce(func.sum(WeekstaatDag.m2), 0),
            func.max(WeekstaatDag.datum),
        )
        .where(WeekstaatDag.weekstaat_id.in_(weekstaat_ids))
        .group_by(WeekstaatDag.weekstaat_id)
    ).all()
    return {r[0]: (r[1], Decimal(r[2]), Decimal(r[3]), r[4]) for r in rijen}


def _open_weken_voor(staten: list[Weekstaat], koppeling_op: date, vandaag: date) -> int:
    """Zie module-docstring voor de definitie."""
    venster = set(_weken_terug(vandaag, OPEN_WEKEN_VENSTER))
    koppelweek = _week_sleutel(koppeling_op)
    venster = {w for w in venster if w >= koppelweek}
    per_week = {(s.jaar, s.weeknummer): s for s in staten}
    open_teller = 0
    for week in venster:
        staat = per_week.get(week)
        if staat is None or staat.status in OPEN_STATUSSEN:
            open_teller += 1
    # afgekeurde weken buiten het venster tellen altijd mee
    open_teller += sum(
        1 for s in staten if s.status == WeekstaatStatus.CORRIGEREN.value and (s.jaar, s.weeknummer) not in venster
    )
    return open_teller


def _gebouwd_m2(session, administratie_id: uuid.UUID, project_id: uuid.UUID) -> Decimal:
    """Som van de m² uit GOEDGEKEURDE weekstaten (de getekende staten) — de m²-voortgang die
    ook de generieke projectenmodule voedt."""
    waarde = session.execute(
        select(func.coalesce(func.sum(WeekstaatDag.m2), 0))
        .join(Weekstaat, Weekstaat.id == WeekstaatDag.weekstaat_id)
        .where(
            Weekstaat.administratie_id == administratie_id,
            Weekstaat.project_id == project_id,
            Weekstaat.status == WeekstaatStatus.GOEDGEKEURD.value,
        )
    ).scalar_one()
    return Decimal(waarde)


# --- ZZP'er (en detacheerder-namens) -----------------------------------------------------------


def _vereis_namens_of_zelf(actor_id: uuid.UUID, zzper_id: uuid.UUID) -> tuple[GebruikerRol, uuid.UUID]:
    """Bepaal wiens scope geldt: de ZZP'er zelf, of een detacheerder (gekoppeld) namens hem.
    Geeft (actor_rol, scope_actor) terug — de administratie-scope is die van de ACTOR."""
    with scoped_session(None, actor_id=actor_id) as session:
        actor = _gebruiker(session, actor_id)
        if actor_id == zzper_id:
            if actor.rol != GebruikerRol.ZZPER:
                raise GeenToegang("Alleen een ZZP'er heeft eigen weekstaten")
            return actor.rol, actor_id
        if actor.rol != GebruikerRol.DETACHEERDER:
            raise GeenToegang("Alleen de ZZP'er zelf of een gekoppelde detacheerder mag dit")
        if session.get(DetacheerderKoppeling, (actor_id, zzper_id)) is None:
            raise GeenToegang("Deze detacheerder is niet aan deze ZZP'er gekoppeld")
        return actor.rol, actor_id


def mijn_projecten_zzp(*, zzper_id: uuid.UUID, actor_id: uuid.UUID, vandaag: date | None = None) -> list[ProjectKaart]:
    """Mijn-projectenlijst (mockup zzpProjecten / detaWeken): toewijzingen van de ZZP'er over
    alle administraties in de scope van de actor, met open-week-teller en laatste invoer."""
    vandaag = vandaag or date.today()
    rol, scope_actor = _vereis_namens_of_zelf(actor_id, zzper_id)
    kaarten: list[ProjectKaart] = []
    for administratie in _administraties_met_opt_in(scope_actor, rol):
        with scoped_session(administratie.id) as session:
            toewijzingen = list(
                session.scalars(
                    select(UrenProjectToewijzing).where(
                        UrenProjectToewijzing.administratie_id == administratie.id,
                        UrenProjectToewijzing.gebruiker_id == zzper_id,
                    )
                )
            )
            for toewijzing in toewijzingen:
                staten = list(
                    session.scalars(
                        select(Weekstaat).where(
                            Weekstaat.administratie_id == administratie.id,
                            Weekstaat.gebruiker_id == zzper_id,
                            Weekstaat.project_id == toewijzing.project_id,
                        )
                    )
                )
                sommen = _dag_sommen(session, [s.id for s in staten])
                laatste = max((v[3] for v in sommen.values() if v[3] is not None), default=None)
                project = session.get(ProjectCache, (toewijzing.project_id, administratie.id))
                spec = session.get(ProjectSpecificatie, (toewijzing.project_id, administratie.id))
                kaarten.append(
                    ProjectKaart(
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        project_id=toewijzing.project_id,
                        project_naam=project.naam if project else None,
                        soort_werk=spec.soort_werk if spec else None,
                        open_weken=_open_weken_voor(staten, toewijzing.aangemaakt_op.date(), vandaag),
                        laatste_invoer=laatste,
                    )
                )
    kaarten.sort(key=lambda k: (-(k.open_weken), k.project_naam or ""))
    return kaarten


def weken_overzicht_zzp(
    *,
    administratie_id: uuid.UUID,
    zzper_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    vandaag: date | None = None,
) -> list[WeekKaart]:
    """Weken van één project (mockup zzpProject): venster-weken (nieuwste eerst) aangevuld met
    álle bestaande staten daarbuiten (bv. een oude corrigeren-week of goedgekeurde historie)."""
    vandaag = vandaag or date.today()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        service._administratie_met_opt_in(session, administratie_id)
        zzper = _gebruiker(session, zzper_id)
        _vereis_invuller(session, zzper=zzper, actor_id=actor_id)
        toewijzing = session.get(UrenProjectToewijzing, (administratie_id, zzper_id, project_id))
        if toewijzing is None:
            raise GeenToegang("Deze ZZP'er is niet aan dit project gekoppeld")

        staten = list(
            session.scalars(
                select(Weekstaat).where(
                    Weekstaat.administratie_id == administratie_id,
                    Weekstaat.gebruiker_id == zzper_id,
                    Weekstaat.project_id == project_id,
                )
            )
        )
        sommen = _dag_sommen(session, [s.id for s in staten])
        namen = service._namen(session, {s.goedgekeurd_door for s in staten} | {s.afgekeurd_door for s in staten})

        per_week: dict[tuple[int, int], Weekstaat] = {(s.jaar, s.weeknummer): s for s in staten}
        koppelweek = _week_sleutel(toewijzing.aangemaakt_op.date())
        venster = [w for w in _weken_terug(vandaag, OPEN_WEKEN_VENSTER) if w >= koppelweek]
        alle_weken = sorted(set(venster) | set(per_week), reverse=True)

        kaarten: list[WeekKaart] = []
        for jaar, week in alle_weken:
            maandag, zondag = service.week_grenzen(jaar, week)
            staat = per_week.get((jaar, week))
            if staat is None:
                kaarten.append(
                    WeekKaart(
                        jaar=jaar,
                        weeknummer=week,
                        maandag=maandag,
                        zondag=zondag,
                        status="nieuw",
                        weekstaat_id=None,
                        dagen_ingevuld=0,
                        totaal_uren=Decimal("0"),
                        totaal_m2=Decimal("0"),
                        ingediend_op=None,
                        goedgekeurd_door_naam=None,
                        afgekeurd_door_naam=None,
                        afkeur_reden=None,
                    )
                )
                continue
            aantal, uren, m2, _ = sommen.get(staat.id, (0, Decimal("0"), Decimal("0"), None))
            kaarten.append(
                WeekKaart(
                    jaar=jaar,
                    weeknummer=week,
                    maandag=maandag,
                    zondag=zondag,
                    status=staat.status,
                    weekstaat_id=staat.id,
                    dagen_ingevuld=aantal,
                    totaal_uren=uren,
                    totaal_m2=m2,
                    ingediend_op=staat.ingediend_op,
                    goedgekeurd_door_naam=namen.get(staat.goedgekeurd_door) if staat.goedgekeurd_door else None,
                    afgekeurd_door_naam=namen.get(staat.afgekeurd_door) if staat.afgekeurd_door else None,
                    afkeur_reden=staat.afkeur_reden if staat.status == WeekstaatStatus.CORRIGEREN.value else None,
                )
            )
        return kaarten


def ingediende_weken(*, zzper_id: uuid.UUID, actor_id: uuid.UUID) -> list[IngediendeWeek]:
    """Historie-tab (mockup #historie): alle niet-concept-staten over alle projecten en
    administraties, nieuwste indiening eerst."""
    rol, scope_actor = _vereis_namens_of_zelf(actor_id, zzper_id)
    items: list[IngediendeWeek] = []
    for administratie in _administraties_met_opt_in(scope_actor, rol):
        with scoped_session(administratie.id) as session:
            staten = list(
                session.scalars(
                    select(Weekstaat).where(
                        Weekstaat.administratie_id == administratie.id,
                        Weekstaat.gebruiker_id == zzper_id,
                        Weekstaat.status != WeekstaatStatus.CONCEPT.value,
                    )
                )
            )
            sommen = _dag_sommen(session, [s.id for s in staten])
            namen = service._namen(session, {s.goedgekeurd_door for s in staten} | {s.afgekeurd_door for s in staten})
            for staat in staten:
                aantal, uren, m2, _ = sommen.get(staat.id, (0, Decimal("0"), Decimal("0"), None))
                project = session.get(ProjectCache, (staat.project_id, administratie.id))
                items.append(
                    IngediendeWeek(
                        weekstaat_id=staat.id,
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        project_id=staat.project_id,
                        project_naam=project.naam if project else None,
                        jaar=staat.jaar,
                        weeknummer=staat.weeknummer,
                        status=staat.status,
                        totaal_uren=uren,
                        totaal_m2=m2,
                        ingediend_op=staat.ingediend_op,
                        ingediend_namens=staat.ingediend_door is not None
                        and staat.ingediend_door != staat.gebruiker_id,
                        goedgekeurd_door_naam=namen.get(staat.goedgekeurd_door) if staat.goedgekeurd_door else None,
                        afgekeurd_door_naam=namen.get(staat.afgekeurd_door) if staat.afgekeurd_door else None,
                        afkeur_reden=staat.afkeur_reden if staat.status == WeekstaatStatus.CORRIGEREN.value else None,
                    )
                )
    items.sort(key=lambda i: (i.ingediend_op is None, i.ingediend_op), reverse=True)
    return items


def weekstaat_detail_voor(
    *, administratie_id: uuid.UUID, weekstaat_id: uuid.UUID, actor_id: uuid.UUID
) -> WeekstaatData:
    """Detail mét toegangs-guard: de ZZP'er zelf, een gekoppelde detacheerder, een uitvoerder
    met toewijzing op het project, of kantoor mét module-recht."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        staat = _weekstaat(session, weekstaat_id)
        actor = _gebruiker(session, actor_id)
        toegestaan = False
        if actor_id == staat.gebruiker_id:
            toegestaan = True
        elif actor.rol == GebruikerRol.DETACHEERDER:
            toegestaan = session.get(DetacheerderKoppeling, (actor_id, staat.gebruiker_id)) is not None
        elif actor.rol == GebruikerRol.UITVOERDER:
            toegestaan = _heeft_toewijzing(session, administratie_id, actor_id, staat.project_id)
        else:
            toegestaan = service.heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol)
        if not toegestaan:
            raise GeenToegang("Geen toegang tot deze weekstaat")
        return _weekstaat_data(session, staat)


# --- detacheerder ------------------------------------------------------------------------------


def mijn_zzpers(*, detacheerder_id: uuid.UUID, vandaag: date | None = None) -> list[ZzperKaart]:
    """Mijn-ZZP'ers-lijst (mockup detaZzpers): gekoppelde ZZP'ers met project-/open-tellers,
    berekend binnen de administratie-scope van de detacheerder."""
    vandaag = vandaag or date.today()
    with scoped_session(None, actor_id=detacheerder_id) as session:
        actor = _gebruiker(session, detacheerder_id)
        if actor.rol != GebruikerRol.DETACHEERDER:
            raise GeenToegang("Alleen voor de rol detacheerder")
        koppelingen = list(
            session.scalars(
                select(DetacheerderKoppeling).where(DetacheerderKoppeling.detacheerder_gebruiker_id == detacheerder_id)
            )
        )
        zzper_ids = [k.zzper_gebruiker_id for k in koppelingen]
        namen = (
            {g.id: g.naam for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(zzper_ids))).all()}
            if zzper_ids
            else {}
        )

    kaarten: list[ZzperKaart] = []
    administraties = _administraties_met_opt_in(detacheerder_id, GebruikerRol.DETACHEERDER)
    for zzper_id in zzper_ids:
        aantal_projecten = 0
        open_weken = 0
        laatste: date | None = None
        for administratie in administraties:
            with scoped_session(administratie.id) as session:
                toewijzingen = list(
                    session.scalars(
                        select(UrenProjectToewijzing).where(
                            UrenProjectToewijzing.administratie_id == administratie.id,
                            UrenProjectToewijzing.gebruiker_id == zzper_id,
                        )
                    )
                )
                aantal_projecten += len(toewijzingen)
                for toewijzing in toewijzingen:
                    staten = list(
                        session.scalars(
                            select(Weekstaat).where(
                                Weekstaat.administratie_id == administratie.id,
                                Weekstaat.gebruiker_id == zzper_id,
                                Weekstaat.project_id == toewijzing.project_id,
                            )
                        )
                    )
                    open_weken += _open_weken_voor(staten, toewijzing.aangemaakt_op.date(), vandaag)
                    sommen = _dag_sommen(session, [s.id for s in staten])
                    week_laatste = max((v[3] for v in sommen.values() if v[3] is not None), default=None)
                    if week_laatste is not None and (laatste is None or week_laatste > laatste):
                        laatste = week_laatste
        kaarten.append(
            ZzperKaart(
                gebruiker_id=zzper_id,
                naam=namen.get(zzper_id, "?"),
                aantal_projecten=aantal_projecten,
                open_weken=open_weken,
                laatste_invoer=laatste,
            )
        )
    kaarten.sort(key=lambda k: (-(k.open_weken), k.naam))
    return kaarten


# --- uitvoerder --------------------------------------------------------------------------------


def _vereis_uitvoerder(actor_id: uuid.UUID) -> None:
    with scoped_session(None) as session:
        actor = _gebruiker(session, actor_id)
        if actor.rol != GebruikerRol.UITVOERDER:
            raise GeenToegang("Alleen voor de rol uitvoerder")


def te_keuren(*, uitvoerder_id: uuid.UUID) -> list[TeKeurenItem]:
    """Te-keuren-lijst (mockup keurlijst): ingediende weekstaten op de projecten waar deze
    uitvoerder aan gekoppeld is, oudste indiening eerst."""
    _vereis_uitvoerder(uitvoerder_id)
    items: list[TeKeurenItem] = []
    for administratie in _administraties_met_opt_in(uitvoerder_id, GebruikerRol.UITVOERDER):
        with scoped_session(administratie.id) as session:
            project_ids = list(
                session.scalars(
                    select(UrenProjectToewijzing.project_id).where(
                        UrenProjectToewijzing.administratie_id == administratie.id,
                        UrenProjectToewijzing.gebruiker_id == uitvoerder_id,
                    )
                )
            )
            if not project_ids:
                continue
            staten = list(
                session.scalars(
                    select(Weekstaat).where(
                        Weekstaat.administratie_id == administratie.id,
                        Weekstaat.project_id.in_(project_ids),
                        Weekstaat.status == WeekstaatStatus.INGEDIEND.value,
                    )
                )
            )
            sommen = _dag_sommen(session, [s.id for s in staten])
            namen = service._namen(session, {s.gebruiker_id for s in staten} | {s.ingediend_door for s in staten})
            for staat in staten:
                aantal, uren, m2, _ = sommen.get(staat.id, (0, Decimal("0"), Decimal("0"), None))
                project = session.get(ProjectCache, (staat.project_id, administratie.id))
                items.append(
                    TeKeurenItem(
                        weekstaat_id=staat.id,
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        zzper_id=staat.gebruiker_id,
                        zzper_naam=namen.get(staat.gebruiker_id),
                        project_id=staat.project_id,
                        project_naam=project.naam if project else None,
                        jaar=staat.jaar,
                        weeknummer=staat.weeknummer,
                        totaal_uren=uren,
                        totaal_m2=m2,
                        ingediend_op=staat.ingediend_op,
                        ingediend_namens=staat.ingediend_door is not None
                        and staat.ingediend_door != staat.gebruiker_id,
                        ingediend_door_naam=namen.get(staat.ingediend_door) if staat.ingediend_door else None,
                    )
                )
    items.sort(key=lambda i: (i.ingediend_op is None, i.ingediend_op))
    return items


def uitvoerder_projecten(*, uitvoerder_id: uuid.UUID) -> list[UitvoerderProjectKaart]:
    """Projectenlijst (mockup projecten): toewijzingen mét spec-samenvatting, m²-voortgang uit
    de goedgekeurde staten en meerwerk-/keur-tellers."""
    _vereis_uitvoerder(uitvoerder_id)
    kaarten: list[UitvoerderProjectKaart] = []
    for administratie in _administraties_met_opt_in(uitvoerder_id, GebruikerRol.UITVOERDER):
        with scoped_session(administratie.id) as session:
            toewijzingen = list(
                session.scalars(
                    select(UrenProjectToewijzing).where(
                        UrenProjectToewijzing.administratie_id == administratie.id,
                        UrenProjectToewijzing.gebruiker_id == uitvoerder_id,
                    )
                )
            )
            for toewijzing in toewijzingen:
                project = session.get(ProjectCache, (toewijzing.project_id, administratie.id))
                spec = session.get(ProjectSpecificatie, (toewijzing.project_id, administratie.id))
                meerwerk_gemeld = session.execute(
                    select(func.count()).where(
                        Meerwerk.administratie_id == administratie.id,
                        Meerwerk.project_id == toewijzing.project_id,
                        Meerwerk.status == MeerwerkStatus.GEMELD.value,
                    )
                ).scalar_one()
                te_keuren_aantal = session.execute(
                    select(func.count()).where(
                        Weekstaat.administratie_id == administratie.id,
                        Weekstaat.project_id == toewijzing.project_id,
                        Weekstaat.status == WeekstaatStatus.INGEDIEND.value,
                    )
                ).scalar_one()
                kaarten.append(
                    UitvoerderProjectKaart(
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        project_id=toewijzing.project_id,
                        project_naam=project.naam if project else None,
                        soort_werk=spec.soort_werk if spec else None,
                        contract_m2=spec.contract_m2 if spec else None,
                        gebouwd_m2=_gebouwd_m2(session, administratie.id, toewijzing.project_id),
                        looptijd_tot=spec.looptijd_tot if spec else None,
                        huurtijd_omschrijving=spec.huurtijd_omschrijving if spec else None,
                        meerwerk_gemeld=meerwerk_gemeld,
                        te_keuren=te_keuren_aantal,
                    )
                )
    kaarten.sort(key=lambda k: k.project_naam or "")
    return kaarten


def projectdetail_uitvoerder(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID
) -> ProjectDetail:
    """Projectdetail (mockup projectdetail): specs + documenten + meerwerklijst — alleen voor
    een uitvoerder met toewijzing (de detacheerder ziet dit bewust nooit, besluit 21-08)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        service._administratie_met_opt_in(session, administratie_id)
        actor = _gebruiker(session, actor_id)
        if actor.rol != GebruikerRol.UITVOERDER or not _heeft_toewijzing(
            session, administratie_id, actor_id, project_id
        ):
            raise GeenToegang("Alleen een uitvoerder van dit project ziet de projectinhoud")
        project = session.get(ProjectCache, (project_id, administratie_id))
        spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
        documenten = list(
            session.scalars(
                select(ProjectDocument)
                .where(
                    ProjectDocument.administratie_id == administratie_id,
                    ProjectDocument.project_id == project_id,
                )
                .order_by(ProjectDocument.soort, ProjectDocument.aangemaakt_op.desc())
            )
        )
        meerwerk = list(
            session.scalars(
                select(Meerwerk)
                .where(Meerwerk.administratie_id == administratie_id, Meerwerk.project_id == project_id)
                .order_by(Meerwerk.gemeld_op.desc())
            )
        )
        return ProjectDetail(
            administratie_id=administratie_id,
            project_id=project_id,
            project_naam=project.naam if project else None,
            opdrachtgever=spec.opdrachtgever if spec else None,
            werknummer_opdrachtgever=spec.werknummer_opdrachtgever if spec else None,
            soort_werk=spec.soort_werk if spec else None,
            contract_m2=spec.contract_m2 if spec else None,
            gebouwd_m2=_gebouwd_m2(session, administratie_id, project_id),
            looptijd_van=spec.looptijd_van if spec else None,
            looptijd_tot=spec.looptijd_tot if spec else None,
            huurtijd_omschrijving=spec.huurtijd_omschrijving if spec else None,
            doorlopende_huur_omschrijving=spec.doorlopende_huur_omschrijving if spec else None,
            documenten=[
                ProjectDocumentKaart(
                    id=d.id,
                    soort=d.soort,
                    titel=d.titel,
                    versie_omschrijving=d.versie_omschrijving,
                    bestandsnaam=d.bestandsnaam,
                )
                for d in documenten
            ],
            meerwerk=[_meerwerk_data(session, m) for m in meerwerk],
        )


# --- kantoor-beheer (Beheerder-only via de router) -----------------------------------------------


@dataclass(frozen=True)
class ToewijzingKaart:
    administratie_id: uuid.UUID
    administratie_naam: str | None
    project_id: uuid.UUID
    project_naam: str | None


@dataclass(frozen=True)
class CrediteurKoppelingKaart:
    """Veldwerker↔crediteur-koppeling per administratie (factuurmatch fase 3): vendor uit de
    cache + het losse ZZP-uurtarief (bureau-tarieven staan per detacheerder↔zzp'er-rij)."""

    administratie_id: uuid.UUID
    administratie_naam: str | None
    vendor_id: uuid.UUID
    vendor_naam: str | None
    uurtarief: Decimal | None
    # Autoboek-opt-in per koppeling (factuurmatch fase 4, besluit 4 — default UIT).
    autoboeken_ingeschakeld: bool


@dataclass(frozen=True)
class VeldgebruikerKaart:
    gebruiker_id: uuid.UUID
    naam: str
    e_mail: str
    rol: str
    status: str
    projecten: list[ToewijzingKaart]
    zzpers: list[dict]  # detacheerder: [{gebruiker_id, naam, uurtarief}] — uurtarief = bureau-tarief
    crediteuren: list[CrediteurKoppelingKaart]
    # Afwijkings-logging (besluit 22-08, kantoor-only): afkeuringen mét correctievoorstel +
    # de opgetelde delta (ingediend − uiteindelijk goedgekeurd, of − voorgesteld zolang de
    # week nog niet opnieuw goedgekeurd is). Alleen gevuld voor ZZP'ers.
    uren_afwijking_aantal: int
    uren_afwijking_som: Decimal
    # ZZP-dossier (A1): stand per administratie mét scope (teller + signalen + blokkade).
    dossiers: list = field(default_factory=list)


def veldgebruikers_overzicht(*, actor_id: uuid.UUID) -> list[VeldgebruikerKaart]:
    """Beheerscherm Gebruikers & toegang: alle veldrol-gebruikers mét hun project-toewijzingen
    (over alle uren-administraties), voor detacheerders de gekoppelde ZZP'ers, en per ZZP'er
    de opgetelde uren-afwijking uit de correctie-registratie (nooit zichtbaar in de veld-API)."""
    from app.auth.rollen import VELD_ROLLEN

    with scoped_session(None, actor_id=actor_id) as session:
        gebruikers = list(
            session.scalars(select(Gebruiker).where(Gebruiker.rol.in_(list(VELD_ROLLEN))).order_by(Gebruiker.naam))
        )
        koppelingen = list(session.scalars(select(DetacheerderKoppeling)))
        zzper_namen = {g.id: g.naam for g in gebruikers}

    toewijzingen_per_gebruiker: dict[uuid.UUID, list[ToewijzingKaart]] = {}
    afwijking_per_gebruiker: dict[uuid.UUID, tuple[int, Decimal]] = {}
    crediteuren_per_gebruiker: dict[uuid.UUID, list[CrediteurKoppelingKaart]] = {}
    dossiers_per_gebruiker: dict[uuid.UUID, list] = {}
    from app.uren import dossier as dossier_service

    for administratie in _administraties_met_opt_in(actor_id, GebruikerRol.BEHEERDER):
        with scoped_session(administratie.id, actor_id=actor_id) as session:
            # ZZP-dossier (A1): veldwerkers mét scope op deze administratie — de scope-tabel heeft
            # RLS, dus binnen de administratie-sessie mét actor (RLS-les 25-08).
            for gid in dossier_service.veldwerkers_van(session, administratie.id):
                dossiers_per_gebruiker.setdefault(gid, []).append(
                    dossier_service.samenvatting_in_sessie(session, administratie=administratie, gebruiker_id=gid)
                )
            # Crediteur-koppelingen + ZZP-uurtarief (factuurmatch fase 3) — vendor-naam uit de cache.
            for koppel in session.scalars(
                select(VeldwerkerCrediteur).where(VeldwerkerCrediteur.administratie_id == administratie.id)
            ):
                vendor = session.get(VendorCache, (koppel.vendor_id, administratie.id))
                crediteuren_per_gebruiker.setdefault(koppel.gebruiker_id, []).append(
                    CrediteurKoppelingKaart(
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        vendor_id=koppel.vendor_id,
                        vendor_naam=vendor.naam if vendor else None,
                        uurtarief=koppel.uurtarief,
                        autoboeken_ingeschakeld=koppel.autoboeken_ingeschakeld,
                    )
                )
            rijen = list(
                session.scalars(
                    select(UrenProjectToewijzing).where(UrenProjectToewijzing.administratie_id == administratie.id)
                )
            )
            for rij in rijen:
                project = session.get(ProjectCache, (rij.project_id, administratie.id))
                toewijzingen_per_gebruiker.setdefault(rij.gebruiker_id, []).append(
                    ToewijzingKaart(
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        project_id=rij.project_id,
                        project_naam=project.naam if project else None,
                    )
                )
            # Delta per registratie: ingediend − goedgekeurd zodra de week definitief is
            # goedgekeurd (dé toetsbron), anders ingediend − voorgesteld.
            afwijkingen = session.execute(
                select(
                    WeekstaatCorrectie.zzper_gebruiker_id,
                    func.count(),
                    func.sum(
                        WeekstaatCorrectie.ingediend_uren
                        - func.coalesce(WeekstaatCorrectie.goedgekeurd_uren, WeekstaatCorrectie.voorgesteld_uren)
                    ),
                )
                .where(WeekstaatCorrectie.administratie_id == administratie.id)
                .group_by(WeekstaatCorrectie.zzper_gebruiker_id)
            ).all()
            for zzper_id, aantal, som in afwijkingen:
                oud_aantal, oud_som = afwijking_per_gebruiker.get(zzper_id, (0, Decimal("0")))
                afwijking_per_gebruiker[zzper_id] = (oud_aantal + aantal, oud_som + (som or Decimal("0")))

    return [
        VeldgebruikerKaart(
            gebruiker_id=g.id,
            naam=g.naam,
            e_mail=g.e_mail,
            rol=g.rol.value,
            status=g.status.value,
            projecten=sorted(toewijzingen_per_gebruiker.get(g.id, []), key=lambda t: t.project_naam or ""),
            zzpers=[
                {
                    "gebruiker_id": k.zzper_gebruiker_id,
                    "naam": zzper_namen.get(k.zzper_gebruiker_id, "?"),
                    "uurtarief": k.uurtarief,
                }
                for k in koppelingen
                if k.detacheerder_gebruiker_id == g.id
            ],
            crediteuren=sorted(crediteuren_per_gebruiker.get(g.id, []), key=lambda c: c.administratie_naam or ""),
            uren_afwijking_aantal=afwijking_per_gebruiker.get(g.id, (0, Decimal("0")))[0],
            uren_afwijking_som=afwijking_per_gebruiker.get(g.id, (0, Decimal("0")))[1],
            dossiers=dossiers_per_gebruiker.get(g.id, []),
        )
        for g in gebruikers
    ]


def project_document_inhoud(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[str, bytes]:
    """Contract-/offerte-PDF (alleen-lezen, mét prijzen — aanname aanvaard 21-08): uitvoerder
    met toewijzing op het project, of kantoor mét module-recht."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        doc = session.get(ProjectDocument, document_id)
        if doc is None or doc.administratie_id != administratie_id:
            raise NietGevonden("Onbekend projectdocument")
        actor = _gebruiker(session, actor_id)
        if actor.rol == GebruikerRol.UITVOERDER:
            if not _heeft_toewijzing(session, administratie_id, actor_id, doc.project_id):
                raise GeenToegang("Deze uitvoerder is niet aan dit project gekoppeld")
        elif not service.heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol):
            raise GeenToegang("Geen toegang tot dit projectdocument")
        opslag_pad, bestandsnaam = doc.opslag_pad, doc.bestandsnaam
    from app.documenten.storage import standaard_opslag

    return bestandsnaam, standaard_opslag().lezen(pad=opslag_pad)


def meerwerk_foto_inhoud(
    *, administratie_id: uuid.UUID, meerwerk_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[str, str, bytes]:
    """Foto bij een meerwerkmelding: (bestandsnaam, content_type, bytes) — uitvoerder met
    toewijzing of kantoor mét module-recht."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        melding = _meerwerk(session, meerwerk_id)
        if melding.foto_opslag_pad is None:
            raise NietGevonden("Deze melding heeft geen foto")
        actor = _gebruiker(session, actor_id)
        if actor.rol == GebruikerRol.UITVOERDER:
            if not _heeft_toewijzing(session, administratie_id, actor_id, melding.project_id):
                raise GeenToegang("Deze uitvoerder is niet aan dit project gekoppeld")
        elif not service.heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol):
            raise GeenToegang("Geen toegang tot deze foto")
        pad = melding.foto_opslag_pad
        naam = melding.foto_bestandsnaam or "foto"
        content_type = melding.foto_content_type or "application/octet-stream"
    from app.documenten.storage import standaard_opslag

    return naam, content_type, standaard_opslag().lezen(pad=pad)
