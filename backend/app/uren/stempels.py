"""Geofence-werkstempels — BASIS (bouwrun 28-08 blok C, mockup geofence-stempels.html = bouwnorm).

Het OS wekt de app (later, eigen release-ronde) uitsluitend bij het binnenkomen/verlaten van een
projectzone → stempel {tijd, project, in/uit}. Hier: de append-only opslag + intake (fail-closed:
alleen de veldwerker zelf, nooit namens; alleen projecten mét een zone in scope), de eigen
stempels voor de veldwerker (transparantie) en de deterministische AANWEZIGHEIDSTOETS voor de
keuring: aanwezigheid per dag = som van in/uit-paren; een ontbrekende uit-stempel sluit het paar
op middernacht mét markering "onvolledig" (nooit gokken); afwijking > 1,0 u t.o.v. de opgegeven
uren = oranje vlag — informatie voor het gesprek, nooit automatische korting (DBA-grens). Geen
stempels ≠ verdacht: de toets zwijgt dan."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.auth.rollen import is_veldrol
from app.db.audit import record_audit_event
from app.db.models import Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.sync.models import ProjectCache
from app.uren.models import ProjectSpecificatie, Werkstempel
from app.uren.service import GeenToegang, OngeldigeInvoer, UrenFout

TIJDZONE = ZoneInfo("Europe/Amsterdam")
# Drempel voor de oranje vlag (mockup-beslispunt 3): kleiner verschil is ruis (parkeren, schaft
# buiten de zone). Nu vast; later per administratie instelbaar (uren_dagmax-patroon).
STEMPEL_AFWIJKING_DREMPEL_UREN = Decimal("1.0")
# Stempels ouder dan dit worden niet meer aangenomen (nabezorging ná een offline periode mag wél).
MAX_LEEFTIJD = timedelta(days=14)
MAX_TOEKOMST = timedelta(minutes=5)
_KWART = Decimal("0.01")


class StempelFout(UrenFout):
    pass


@dataclass(frozen=True)
class StempelInvoer:
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    tijdstip: datetime
    soort: str  # 'in' | 'uit'
    bron: str = "app"


@dataclass(frozen=True)
class StempelData:
    id: uuid.UUID
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None
    tijdstip: datetime
    soort: str
    bron: str


@dataclass(frozen=True)
class DagAanwezigheid:
    """Uitkomst van de toets voor één dag (mockup §3, kolom "Gestempeld aanwezig" + "Toets")."""

    gestempeld_uren: Decimal
    eerste_in: time | None
    laatste_uit: time | None
    onvolledig: bool  # ontbrekende uit- of in-stempel — paar op middernacht gesloten / genegeerd
    aantal_stempels: int


def bereken_aanwezigheid(stempels: list[tuple[datetime, str]], dag: date) -> DagAanwezigheid | None:
    """Pure toets (Code voor cijfers): in/uit-paren op tijdvolgorde binnen `dag` (lokale tijd).
    None = geen stempels (toets zwijgt). 'in' zonder 'uit' → paar sluit op middernacht,
    onvolledig=True; 'uit' zonder voorafgaande 'in' → genegeerd, onvolledig=True."""
    lokaal = sorted(
        ((t.astimezone(TIJDZONE), soort) for t, soort in stempels if t.astimezone(TIJDZONE).date() == dag),
        key=lambda x: x[0],
    )
    if not lokaal:
        return None
    middernacht = datetime.combine(dag + timedelta(days=1), time(0, 0), tzinfo=TIJDZONE)
    totaal = timedelta()
    open_in: datetime | None = None
    onvolledig = False
    eerste_in: time | None = None
    laatste_uit: time | None = None
    for t, soort in lokaal:
        if soort == "in":
            if open_in is not None:
                onvolledig = True  # dubbele 'in': de eerste blijft leidend, gemarkeerd
                continue
            open_in = t
            if eerste_in is None:
                eerste_in = t.time().replace(second=0, microsecond=0)
        else:
            if open_in is None:
                onvolledig = True
                continue
            totaal += t - open_in
            laatste_uit = t.time().replace(second=0, microsecond=0)
            open_in = None
    if open_in is not None:
        totaal += middernacht - open_in
        onvolledig = True
        laatste_uit = None
    uren = (Decimal(totaal.total_seconds()) / Decimal(3600)).quantize(_KWART, rounding=ROUND_HALF_UP)
    return DagAanwezigheid(
        gestempeld_uren=uren,
        eerste_in=eerste_in,
        laatste_uit=laatste_uit,
        onvolledig=onvolledig,
        aantal_stempels=len(lokaal),
    )


def afwijking_boven_drempel(opgegeven_uren: Decimal, aanwezigheid: DagAanwezigheid | None) -> bool:
    """Oranje vlag: |opgegeven − gestempeld| > drempel. Zonder stempels of bij 0 opgegeven uren
    zwijgt de toets (0-urendag = geen claim om te toetsen)."""
    if aanwezigheid is None or opgegeven_uren <= 0:
        return False
    return abs(opgegeven_uren - aanwezigheid.gestempeld_uren) > STEMPEL_AFWIJKING_DREMPEL_UREN


def stempels_per_dag(
    session: Session, *, gebruiker_id: uuid.UUID, project_id: uuid.UUID, dagen: list[date]
) -> dict[date, DagAanwezigheid | None]:
    """Toets per dag voor één (veldwerker, project) — voor de keuring. Leest binnen de al gescoopte
    sessie van de weekstaat (RLS per administratie)."""
    if not dagen:
        return {}
    van = datetime.combine(min(dagen), time(0, 0), tzinfo=TIJDZONE)
    tot = datetime.combine(max(dagen) + timedelta(days=1), time(0, 0), tzinfo=TIJDZONE)
    rijen = session.execute(
        select(Werkstempel.tijdstip, Werkstempel.soort).where(
            Werkstempel.gebruiker_id == gebruiker_id,
            Werkstempel.project_id == project_id,
            Werkstempel.tijdstip >= van,
            Werkstempel.tijdstip < tot,
        )
    ).all()
    paren = [(t, soort) for t, soort in rijen]
    return {dag: bereken_aanwezigheid(paren, dag) for dag in dagen}


def _vereis_stempelende_veldwerker(session: Session, actor_id: uuid.UUID) -> Gebruiker:
    actor = session.get(Gebruiker, actor_id)
    if actor is None or not is_veldrol(actor.rol) or actor.rol == GebruikerRol.DETACHEERDER:
        # Detacheerder-namens valt erbuiten (mockup): een stempel is altijd van de veldwerker zelf.
        raise GeenToegang("Stempels horen bij de veldwerker zelf (ZZP'er/uitvoerder) — nooit namens")
    return actor


def registreer_stempels(
    *, actor_id: uuid.UUID, apparaat_id: uuid.UUID | None, stempels: list[StempelInvoer]
) -> int:
    """Intake (fail-closed): alleen de veldwerker zelf, alleen administraties in scope mét de
    uren-&-meerwerk-opt-in, alleen actieve projecten mét een zone (locatie ingesteld), tijdstip
    niet in de toekomst en niet ouder dan MAX_LEEFTIJD. Idempotent op (gebruiker, project,
    tijdstip, soort) — een herhaalde aanlevering telt niet dubbel. Geeft het aantal NIEUWE
    stempels terug; één audit-event per aanlevering (append-only-spoor)."""
    if not stempels:
        return 0
    nu = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        actor = _vereis_stempelende_veldwerker(session, actor_id)
        toegestaan = {
            a.id
            for a in auth_service.mijn_administraties(actor_id=actor_id, rol=actor.rol)
            if a.uren_meerwerk_ingeschakeld
        }
    for s in stempels:
        if s.soort not in ("in", "uit"):
            raise OngeldigeInvoer("Stempel-soort moet 'in' of 'uit' zijn")
        if s.tijdstip.tzinfo is None:
            raise OngeldigeInvoer("Stempel-tijdstip zonder tijdzone")
        if s.tijdstip > nu + MAX_TOEKOMST:
            raise OngeldigeInvoer("Stempel-tijdstip ligt in de toekomst")
        if s.tijdstip < nu - MAX_LEEFTIJD:
            raise OngeldigeInvoer("Stempel is te oud om nog aan te nemen")
        if s.administratie_id not in toegestaan:
            raise GeenToegang("Geen toegang tot deze administratie (of uren & meerwerk staat uit)")
    nieuw = 0
    for administratie_id in {s.administratie_id for s in stempels}:
        eigen = [s for s in stempels if s.administratie_id == administratie_id]
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            for s in eigen:
                project = session.get(ProjectCache, (s.project_id, administratie_id))
                if project is None or not project.is_actief:
                    raise OngeldigeInvoer("Onbekend of inactief project voor deze stempel")
                spec = session.get(ProjectSpecificatie, (s.project_id, administratie_id))
                if spec is None or spec.locatie_lat is None or spec.locatie_lon is None:
                    raise StempelFout("Dit project heeft geen projectzone — stempels worden niet aangenomen")
                bestaat = session.scalars(
                    select(Werkstempel.id).where(
                        Werkstempel.gebruiker_id == actor_id,
                        Werkstempel.project_id == s.project_id,
                        Werkstempel.tijdstip == s.tijdstip,
                        Werkstempel.soort == s.soort,
                    )
                ).first()
                if bestaat is not None:
                    continue
                rij = Werkstempel(
                    administratie_id=administratie_id,
                    gebruiker_id=actor_id,
                    project_id=s.project_id,
                    tijdstip=s.tijdstip,
                    soort=s.soort,
                    bron=s.bron if s.bron in ("app", "os_geofence") else "app",
                    apparaat_id=apparaat_id,
                )
                session.add(rij)
                nieuw += 1
            if nieuw:
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="werkstempel",
                    record_id=actor_id,
                    actie="werkstempels_ontvangen",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={"aantal": nieuw, "projecten": sorted({str(s.project_id) for s in eigen})},
                    administratie_id=administratie_id,
                )
    return nieuw


def eigen_stempels(*, actor_id: uuid.UUID, dag: date) -> list[StempelData]:
    """De eigen stempels van één dag (mockup §1 "Vandaag"): alleen de veldwerker zelf ziet ze;
    de keurder ziet ze in de keuring; verder niemand, geen export."""
    with scoped_session(None, actor_id=actor_id) as session:
        actor = _vereis_stempelende_veldwerker(session, actor_id)
        administraties = [
            a
            for a in auth_service.mijn_administraties(actor_id=actor_id, rol=actor.rol)
            if a.uren_meerwerk_ingeschakeld
        ]
    van = datetime.combine(dag, time(0, 0), tzinfo=TIJDZONE)
    tot = van + timedelta(days=1)
    resultaat: list[StempelData] = []
    for administratie in administraties:
        with scoped_session(administratie.id) as session:
            rijen = list(
                session.scalars(
                    select(Werkstempel)
                    .where(
                        Werkstempel.gebruiker_id == actor_id,
                        Werkstempel.tijdstip >= van,
                        Werkstempel.tijdstip < tot,
                    )
                    .order_by(Werkstempel.tijdstip)
                )
            )
            for rij in rijen:
                project = session.get(ProjectCache, (rij.project_id, administratie.id))
                resultaat.append(
                    StempelData(
                        id=rij.id,
                        administratie_id=administratie.id,
                        project_id=rij.project_id,
                        project_naam=project.naam if project else None,
                        tijdstip=rij.tijdstip,
                        soort=rij.soort,
                        bron=rij.bron,
                    )
                )
    resultaat.sort(key=lambda s: s.tijdstip)
    return resultaat
