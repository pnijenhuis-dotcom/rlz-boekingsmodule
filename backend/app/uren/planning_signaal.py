"""Kantoor-signaal "geplande week zonder weekstaat" (mini-run 06-09 blok A, migratie 0115).

De veld-app toont geplande weken maar `overzichten.OPEN_WEKEN_VENSTER` (6) weken terug (venster-besluit
A2 04-09). Een geplande week zónder ingediende weekstaat die uit dat venster valt verdween daardoor stil
uit élke werklijst. Dit signaal maakt dat kantoorzijde zichtbaar — deterministisch, geen AI, geen
RLZ-/Odoo-calls:

    per (administratie mét uren-opt-in, veldwerker, project, ISO-week):
        planning_toewijzing-rijen in die week  (≥ 1 dag gepland)
        én de week is OUDER dan het app-venster (week < oudste week in _weken_terug(vandaag, VENSTER))
        én er is géén weekstaat  → soort 'geen_staat'
            óf de staat staat nog op concept/corrigeren (niet ingediend) → soort 'concept'
        (ingediend/goedgekeurd = afgehandeld, geen signaal)

Afhandeling (tabel planning_signaal_afhandeling): "Herinnering sturen" via het bestaande push-anders-
mail-kanaal (dossier-patroon: dagrij claimen vóór verzenden, max 1/dag per combinatie) of "Afmelden mét
reden" (één actuele afmelding, intrekbaar — nooit delete). Afgemelde combinaties tellen niet mee maar
blijven zichtbaar onder het filter "afgemeld". Alles geauditeerd. Geen blokkade: het signaal draagt
alleen een handeling (kernprincipe 7 — signalering zonder handeling is niet af).

Kantoorbreed (kernprincipe 7): scope = de administraties van de actor mét opt-in, urgentste (oudste
week) eerst, server-side paginering 25, tellers "N signalen over M administraties"; administratie is een
filter, nooit een poort. Poort = het module-recht 'Meerwerk & urenstaten' (zelfde poort als de
keurings-/dossier-routes) + klantscope.

Veld-app: een HERINNERDE week wordt in de app weer zichtbaar tot hij is ingediend (anders zou de
herinnering "open de app" naar een week wijzen die de app niet toont) — zie
`herinnerde_weken_buiten_venster` + `overzichten._planning_stand`. Het venster-besluit zelf blijft: een
niet-herinnerde oude week blijft buiten de app.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.berichten import verzending
from app.berichten.models import HerinneringStatus
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerStatus
from app.db.session import scoped_session
from app.sync.models import ProjectCache
from app.uren import overzichten
from app.uren.dossier import AlHerinnerdVandaag, HerinneringMislukt
from app.uren.models import (
    PlanningDagdeel,
    PlanningSignaalAfhandeling,
    PlanningSignaalSoort,
    PlanningToewijzing,
    Weekstaat,
    WeekstaatStatus,
)
from app.uren.service import (
    MODULE,
    GeenToegang,
    OngeldigeInvoer,
    OngeldigeOvergang,
    RedenVerplicht,
    _administratie_met_opt_in,
    _gebruiker,
    _vereis_meerwerk_recht,
    heeft_meerwerk_urenstaten_recht,
    week_grenzen,
)

TIJDZONE = ZoneInfo("Europe/Amsterdam")
PER_PAGINA = 25
REDEN_MINIMUM = 5
# Soorten van het signaal (afgeleid, geen kolom): geen enkele staat vs. een niet-ingediende staat.
SOORT_GEEN_STAAT = "geen_staat"
SOORT_CONCEPT = "concept"
# Afgehandeld = ingediend of goedgekeurd (spiegel van overzichten.OPEN_STATUSSEN).
_AFGEHANDELD = frozenset({WeekstaatStatus.INGEDIEND.value, WeekstaatStatus.GOEDGEKEURD.value})
_HALF = Decimal("0.5")
_HEEL = Decimal("1")


def _vandaag() -> date:
    return datetime.now(TIJDZONE).date()


def oudste_vensterweek(vandaag: date) -> tuple[int, int]:
    """De oudste (jaar, week) die de veld-app nog toont — één bron: overzichten.OPEN_WEKEN_VENSTER."""
    return overzichten._weken_terug(vandaag, overzichten.OPEN_WEKEN_VENSTER)[-1]


def _week_sleutel(d: date) -> tuple[int, int]:
    c = d.isocalendar()
    return (c[0], c[1])


# --- data --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Herinnering:
    op: datetime
    kanaal: str | None
    door_naam: str | None


@dataclass(frozen=True)
class Afmelding:
    reden: str
    op: datetime
    door_naam: str | None


@dataclass
class Signaal:
    administratie_id: uuid.UUID
    administratie_naam: str
    gebruiker_id: uuid.UUID
    gebruiker_naam: str
    gebruiker_actief: bool
    project_id: uuid.UUID
    project_naam: str | None
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    geplande_dagen: Decimal
    soort: str  # geen_staat | concept
    weekstaat_status: str | None
    herinneringen: int
    laatste_herinnering: Herinnering | None
    herinnerd_vandaag: bool  # dagrem-stand: vandaag al een verzonden herinnering (knop uit in de UI)
    afmelding: Afmelding | None

    @property
    def status(self) -> str:
        return "afgemeld" if self.afmelding is not None else "open"

    @property
    def sleutel(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, int, int]:
        return (self.administratie_id, self.gebruiker_id, self.project_id, self.jaar, self.weeknummer)


@dataclass(frozen=True)
class SignalenPagina:
    rijen: list[Signaal]
    totaal: int
    pagina: int
    per_pagina: int
    open: int
    afgemeld: int
    administraties: int  # administraties mét ≥ 1 OPEN signaal (binnen de selectie)
    administraties_in_selectie: int  # administraties met ≥ 1 rij in de selectie (filter)
    facet_administraties: list[tuple[uuid.UUID, str, int]]  # (id, naam, open-aantal)
    venster_weken: int


# --- berekening --------------------------------------------------------------------------------------


def signalen_in_sessie(session: Session, administratie: Administratie, *, vandaag: date | None = None) -> list[Signaal]:
    """Alle signalen (open én afgemeld) van één administratie in een al gescoopte sessie. Geen
    opt-in-toets hier — de aanroeper bepaalt of de administratie meedoet."""
    vandaag = vandaag or _vandaag()
    grens_week = oudste_vensterweek(vandaag)
    grens_datum = week_grenzen(*grens_week)[0]  # maandag van de oudste vensterweek: alles dáárvoor telt
    aid = administratie.id

    planning = session.execute(
        select(
            PlanningToewijzing.gebruiker_id,
            PlanningToewijzing.project_id,
            PlanningToewijzing.datum,
            PlanningToewijzing.dagdeel,
        ).where(PlanningToewijzing.administratie_id == aid, PlanningToewijzing.datum < grens_datum)
    ).all()
    if not planning:
        return []

    dagen: dict[tuple[uuid.UUID, uuid.UUID, int, int], Decimal] = {}
    for gebruiker_id, project_id, datum, dagdeel in planning:
        jaar, week = _week_sleutel(datum)
        if (jaar, week) >= grens_week:  # randgeval: datum vóór de grens-maandag valt per definitie in een oudere week
            continue
        sleutel = (gebruiker_id, project_id, jaar, week)
        dagen[sleutel] = dagen.get(sleutel, Decimal("0")) + (_HALF if dagdeel == PlanningDagdeel.HALF.value else _HEEL)
    if not dagen:
        return []

    gebruiker_ids = {s[0] for s in dagen}
    project_ids = {s[1] for s in dagen}
    staten = {
        (s.gebruiker_id, s.project_id, s.jaar, s.weeknummer): s.status
        for s in session.scalars(
            select(Weekstaat).where(
                Weekstaat.administratie_id == aid,
                Weekstaat.gebruiker_id.in_(gebruiker_ids),
                Weekstaat.project_id.in_(project_ids),
            )
        )
    }
    afhandelingen = list(
        session.scalars(
            select(PlanningSignaalAfhandeling)
            .where(
                PlanningSignaalAfhandeling.administratie_id == aid,
                PlanningSignaalAfhandeling.gebruiker_id.in_(gebruiker_ids),
            )
            .order_by(PlanningSignaalAfhandeling.op)
        )
    )
    gebruikers = {g.id: g for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(gebruiker_ids)))}
    projecten = {
        p.id: p
        for p in session.scalars(
            select(ProjectCache).where(ProjectCache.administratie_id == aid, ProjectCache.id.in_(project_ids))
        )
    }
    actor_ids = {a.door for a in afhandelingen}
    actor_namen = (
        {g.id: g.naam for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(actor_ids)))}
        if actor_ids
        else {}
    )

    herinnerd: dict[tuple, list[PlanningSignaalAfhandeling]] = {}
    afgemeld: dict[tuple, PlanningSignaalAfhandeling] = {}
    for a in afhandelingen:
        sleutel = (a.gebruiker_id, a.project_id, a.jaar, a.weeknummer)
        if a.soort == PlanningSignaalSoort.HERINNERD.value and a.status == HerinneringStatus.VERZONDEN.value:
            herinnerd.setdefault(sleutel, []).append(a)
        elif a.soort == PlanningSignaalSoort.AFGEMELD.value and a.ingetrokken_op is None:
            afgemeld[sleutel] = a

    signalen: list[Signaal] = []
    for sleutel, aantal in dagen.items():
        gebruiker_id, project_id, jaar, week = sleutel
        status = staten.get(sleutel)
        if status in _AFGEHANDELD:
            continue
        gebruiker = gebruikers.get(gebruiker_id)
        project = projecten.get(project_id)
        maandag, zondag = week_grenzen(jaar, week)
        herinneringen = herinnerd.get(sleutel, [])
        laatste = herinneringen[-1] if herinneringen else None
        afm = afgemeld.get(sleutel)
        signalen.append(
            Signaal(
                administratie_id=aid,
                administratie_naam=administratie.naam,
                gebruiker_id=gebruiker_id,
                gebruiker_naam=gebruiker.naam if gebruiker else "?",
                gebruiker_actief=gebruiker is not None and gebruiker.status == GebruikerStatus.ACTIEF,
                project_id=project_id,
                project_naam=project.naam if project else None,
                jaar=jaar,
                weeknummer=week,
                maandag=maandag,
                zondag=zondag,
                geplande_dagen=aantal,
                soort=SOORT_CONCEPT if status is not None else SOORT_GEEN_STAAT,
                weekstaat_status=status,
                herinneringen=len(herinneringen),
                laatste_herinnering=Herinnering(
                    op=laatste.verzonden_op or laatste.op,
                    kanaal=laatste.kanaal,
                    door_naam=actor_namen.get(laatste.door),
                )
                if laatste
                else None,
                herinnerd_vandaag=laatste is not None and laatste.datum == vandaag,
                afmelding=Afmelding(reden=afm.reden or "", op=afm.op, door_naam=actor_namen.get(afm.door))
                if afm
                else None,
            )
        )
    signalen.sort(key=lambda s: (s.jaar, s.weeknummer, s.administratie_naam, s.gebruiker_naam, s.project_naam or ""))
    return signalen


def tel_signalen(session: Session, administratie_id: uuid.UUID, *, vandaag: date | None = None) -> int:
    """Werkvoorraad-teller (signaal-patroon, toon-regel > 0): OPEN signalen van één administratie —
    0 zonder de uren-opt-in. Zelfde definitie als de kantoorbrede lijst (één bron)."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.uren_meerwerk_ingeschakeld:
        return 0
    return sum(1 for s in signalen_in_sessie(session, administratie, vandaag=vandaag) if s.afmelding is None)


def herinnerde_weken_buiten_venster(
    session: Session, *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, grens_week: tuple[int, int]
) -> set[tuple[int, int]]:
    """Veld-app-verlengstuk: (jaar, week) ouder dan het venster waarvoor het kantoor een herinnering
    heeft VERZONDEN en die nog niet is ingediend/goedgekeurd — die weken toont de app weer, zodat de
    herinnering een reikbaar doel heeft. Een afmelding of een ingediende staat sluit de week weer.
    `grens_week` = de oudste week die de app nog toont (alles dáárvoor is "buiten het venster")."""
    grens = grens_week
    rijen = session.execute(
        select(
            PlanningSignaalAfhandeling.project_id,
            PlanningSignaalAfhandeling.jaar,
            PlanningSignaalAfhandeling.weeknummer,
        ).where(
            PlanningSignaalAfhandeling.administratie_id == administratie_id,
            PlanningSignaalAfhandeling.gebruiker_id == gebruiker_id,
            PlanningSignaalAfhandeling.soort == PlanningSignaalSoort.HERINNERD.value,
            PlanningSignaalAfhandeling.status == HerinneringStatus.VERZONDEN.value,
        )
    ).all()
    kandidaten = {(int(j), int(w)) for _p, j, w in rijen if (int(j), int(w)) < grens}
    if not kandidaten:
        return set()
    afgemeld = {
        (int(j), int(w))
        for j, w in session.execute(
            select(PlanningSignaalAfhandeling.jaar, PlanningSignaalAfhandeling.weeknummer).where(
                PlanningSignaalAfhandeling.administratie_id == administratie_id,
                PlanningSignaalAfhandeling.gebruiker_id == gebruiker_id,
                PlanningSignaalAfhandeling.soort == PlanningSignaalSoort.AFGEMELD.value,
                PlanningSignaalAfhandeling.ingetrokken_op.is_(None),
            )
        ).all()
    }
    return kandidaten - afgemeld


# --- kantoorbrede lijst ------------------------------------------------------------------------------


def _administraties_in_scope(actor_id: uuid.UUID) -> tuple[Gebruiker, list[Administratie]]:
    with scoped_session(None, actor_id=actor_id) as session:
        actor = _gebruiker(session, actor_id)
        if not heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol):
            raise GeenToegang("Vereist het module-recht 'Meerwerk & urenstaten'")
        session.expunge(actor)
    administraties = [
        a for a in auth_service.mijn_administraties(actor_id=actor_id, rol=actor.rol) if a.uren_meerwerk_ingeschakeld
    ]
    return actor, administraties


def _vereis_scope(actor_id: uuid.UUID, administratie_id: uuid.UUID) -> Administratie:
    _actor, administraties = _administraties_in_scope(actor_id)
    for a in administraties:
        if a.id == administratie_id:
            return a
    raise GeenToegang("Geen toegang tot deze administratie (of de uren-opt-in staat uit)")


def signalen_kantoorbreed(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID | None = None,
    filter: str = "open",
    pagina: int = 1,
    vandaag: date | None = None,
) -> SignalenPagina:
    """Kantoorbrede lijst (kernprincipe 7): alle administraties mét opt-in in de scope, oudste week
    eerst, 25/pagina. `filter` = open (default) | afgemeld | alle; administratie = filter, geen poort."""
    if filter not in ("open", "afgemeld", "alle"):
        raise OngeldigeInvoer("filter moet open, afgemeld of alle zijn")
    if pagina < 1:
        raise OngeldigeInvoer("pagina begint bij 1")
    vandaag = vandaag or _vandaag()
    _actor, administraties = _administraties_in_scope(actor_id)
    if administratie_id is not None and administratie_id not in {a.id for a in administraties}:
        raise GeenToegang("Geen toegang tot deze administratie (of de uren-opt-in staat uit)")

    # Altijd over de hele scope rekenen: de administratie-facet blijft kantoorbreed (filter, geen poort).
    alle: list[Signaal] = []
    for administratie in administraties:
        with scoped_session(administratie.id, actor_id=actor_id) as session:
            alle.extend(signalen_in_sessie(session, administratie, vandaag=vandaag))
    alle.sort(key=lambda s: (s.jaar, s.weeknummer, s.administratie_naam, s.gebruiker_naam, s.project_naam or ""))

    facet: dict[uuid.UUID, tuple[str, int]] = {}
    for s in alle:
        if s.afmelding is None:
            naam, n = facet.get(s.administratie_id, (s.administratie_naam, 0))
            facet[s.administratie_id] = (naam, n + 1)
    if administratie_id is not None:
        alle = [s for s in alle if s.administratie_id == administratie_id]
    open_ = [s for s in alle if s.afmelding is None]
    afgemeld = [s for s in alle if s.afmelding is not None]
    selectie = open_ if filter == "open" else afgemeld if filter == "afgemeld" else alle
    start = (pagina - 1) * PER_PAGINA
    return SignalenPagina(
        rijen=selectie[start : start + PER_PAGINA],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=PER_PAGINA,
        open=len(open_),
        afgemeld=len(afgemeld),
        administraties=len({s.administratie_id for s in open_}),
        administraties_in_selectie=len({s.administratie_id for s in selectie}),
        facet_administraties=sorted(((aid, naam, n) for aid, (naam, n) in facet.items()), key=lambda f: f[1]),
        venster_weken=overzichten.OPEN_WEKEN_VENSTER,
    )


# --- acties --------------------------------------------------------------------------------------------


def _signaal_in_sessie(
    session: Session,
    administratie: Administratie,
    *,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    vandaag: date,
) -> Signaal:
    for s in signalen_in_sessie(session, administratie, vandaag=vandaag):
        if s.sleutel == (administratie.id, gebruiker_id, project_id, jaar, weeknummer):
            return s
    raise OngeldigeOvergang(
        f"Geen signaal voor week {weeknummer}: de week is ingediend, valt nog binnen het app-venster "
        "of was niet gepland"
    )


def _bericht_teksten(signaal: Signaal) -> tuple[str, str, str, str]:
    pad = "/accordeur"
    link = f"{settings.app_basis_url.rstrip('/')}{pad}"
    project = signaal.project_naam or "een project"
    dagen = f"{signaal.geplande_dagen.normalize():f}".replace(".", ",")
    onderwerp = f"Herinnering: weekstaat week {signaal.weeknummer} ontbreekt nog"
    pushtekst = f"Je stond in week {signaal.weeknummer} ingepland op {project}, maar er is geen weekstaat ingediend."
    mailtekst = (
        f"Beste {signaal.gebruiker_naam},\n\n"
        f"Je stond in week {signaal.weeknummer} ({signaal.maandag:%d-%m} t/m {signaal.zondag:%d-%m-%Y}) voor {dagen} "
        f"dag(en) ingepland op project {project}, maar er is voor die week geen weekstaat ingediend.\n\n"
        f"Open de app om de weekstaat in te vullen en in te dienen — de week staat weer in je lijst:\n{link}\n\n"
        "Heb je die week niet gewerkt? Laat het dan even aan het kantoor weten.\n\n"
        "Administratiekantoor Nijenhuis"
    )
    return onderwerp, pushtekst, mailtekst, pad


@dataclass(frozen=True)
class HerinneringResultaat:
    gebruiker_id: uuid.UUID
    kanaal: str
    verzonden_op: datetime
    herinneringen: int


def stuur_herinnering(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    actor_id: uuid.UUID,
    vandaag: date | None = None,
) -> HerinneringResultaat:
    """Herinnering aan de veldwerker via push-anders-mail (dossier-patroon in drie transacties: dagrij
    claimen → verzenden buiten de transactie → uitkomst vastleggen). Max 1 per dag per combinatie (409)."""
    vandaag = vandaag or _vandaag()
    _vereis_scope(actor_id, administratie_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        signaal = _signaal_in_sessie(
            session,
            administratie,
            gebruiker_id=gebruiker_id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
            vandaag=vandaag,
        )
        if signaal.afmelding is not None:
            raise OngeldigeOvergang("Dit signaal is afgemeld — trek de afmelding eerst in")
        veldwerker = _gebruiker(session, gebruiker_id)
        if veldwerker.status != GebruikerStatus.ACTIEF:
            raise OngeldigeInvoer("De veldwerker is niet actief — herinneren heeft geen zin")
        bestaande = session.scalars(
            select(PlanningSignaalAfhandeling).where(
                PlanningSignaalAfhandeling.administratie_id == administratie_id,
                PlanningSignaalAfhandeling.gebruiker_id == gebruiker_id,
                PlanningSignaalAfhandeling.project_id == project_id,
                PlanningSignaalAfhandeling.jaar == jaar,
                PlanningSignaalAfhandeling.weeknummer == weeknummer,
                PlanningSignaalAfhandeling.soort == PlanningSignaalSoort.HERINNERD.value,
                PlanningSignaalAfhandeling.datum == vandaag,
            )
        ).first()
        if bestaande is not None:
            if bestaande.status in (HerinneringStatus.VERZONDEN.value, HerinneringStatus.BEZIG.value):
                raise AlHerinnerdVandaag(
                    "Vandaag is er al een herinnering voor deze week aan deze veldwerker verstuurd"
                )
            bestaande.status = HerinneringStatus.BEZIG.value
            bestaande.door = actor_id
            rij_id = bestaande.id
        else:
            rij = PlanningSignaalAfhandeling(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                project_id=project_id,
                jaar=jaar,
                weeknummer=weeknummer,
                soort=PlanningSignaalSoort.HERINNERD.value,
                datum=vandaag,
                status=HerinneringStatus.BEZIG.value,
                door=actor_id,
            )
            session.add(rij)
            try:
                session.flush()
            except IntegrityError as exc:
                raise AlHerinnerdVandaag(
                    "Vandaag is er al een herinnering voor deze week aan deze veldwerker verstuurd"
                ) from exc
            rij_id = rij.id
        session.expunge(veldwerker)

    onderwerp, pushtekst, mailtekst, pad = _bericht_teksten(signaal)
    uitkomst = verzending.verstuur_push_anders_mail(
        veldwerker, onderwerp=onderwerp, pushtekst=pushtekst, mailtekst=mailtekst, url=pad
    )

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(PlanningSignaalAfhandeling, rij_id)
        assert rij is not None
        rij.status = uitkomst.status.value
        rij.kanaal = uitkomst.kanaal.value if uitkomst.kanaal else None
        rij.detail = uitkomst.detail
        mislukt = uitkomst.status != HerinneringStatus.VERZONDEN
        if not mislukt:
            rij.verzonden_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_signaal_afhandeling",
            record_id=rij.id,
            actie="planning_signaal_herinnering_mislukt" if mislukt else "planning_signaal_herinnerd",
            correlatie_id=gebruiker_id,
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker_id),
                "project_id": str(project_id),
                "jaar": jaar,
                "weeknummer": weeknummer,
                "soort_signaal": signaal.soort,
                "status": rij.status,
                "kanaal": rij.kanaal,
                "detail": rij.detail,
                "herinneringen": signaal.herinneringen + (0 if mislukt else 1),
            },
            administratie_id=administratie_id,
        )
        verzonden_op = rij.verzonden_op
        kanaal = rij.kanaal
    if mislukt:
        raise HerinneringMislukt(
            "Herinnering niet bezorgd: "
            + str((uitkomst.detail or {}).get("fout") or (uitkomst.detail or {}).get("reden") or uitkomst.status.value)
        )
    assert verzonden_op is not None
    return HerinneringResultaat(
        gebruiker_id=gebruiker_id,
        kanaal=kanaal or "",
        verzonden_op=verzonden_op,
        herinneringen=signaal.herinneringen + 1,
    )


def meld_af(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    reden: str,
    actor_id: uuid.UUID,
    vandaag: date | None = None,
) -> uuid.UUID:
    """Afmelden mét verplichte reden (≥ 5 tekens): het signaal telt niet meer mee maar blijft zichtbaar
    onder 'afgemeld'; één actuele afmelding per combinatie (409 bij een tweede)."""
    reden = (reden or "").strip()
    if len(reden) < REDEN_MINIMUM:
        raise RedenVerplicht(f"Afmelden vereist een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens)")
    vandaag = vandaag or _vandaag()
    _vereis_scope(actor_id, administratie_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        signaal = _signaal_in_sessie(
            session,
            administratie,
            gebruiker_id=gebruiker_id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
            vandaag=vandaag,
        )
        if signaal.afmelding is not None:
            raise OngeldigeOvergang("Dit signaal is al afgemeld")
        rij = PlanningSignaalAfhandeling(
            administratie_id=administratie_id,
            gebruiker_id=gebruiker_id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
            soort=PlanningSignaalSoort.AFGEMELD.value,
            reden=reden,
            door=actor_id,
        )
        session.add(rij)
        try:
            session.flush()
        except IntegrityError as exc:
            raise OngeldigeOvergang("Dit signaal is al afgemeld") from exc
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_signaal_afhandeling",
            record_id=rij.id,
            actie="planning_signaal_afgemeld",
            correlatie_id=gebruiker_id,
            oude_waarde={"status": "open", "soort_signaal": signaal.soort},
            nieuwe_waarde={
                "status": "afgemeld",
                "reden": reden,
                "gebruiker_id": str(gebruiker_id),
                "project_id": str(project_id),
                "jaar": jaar,
                "weeknummer": weeknummer,
            },
            administratie_id=administratie_id,
        )
        return rij.id


def afmelding_intrekken(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    actor_id: uuid.UUID,
) -> uuid.UUID:
    """ "Toch tonen": de actuele afmelding wordt ingetrokken (kolom, nooit delete); het signaal telt weer."""
    _vereis_scope(actor_id, administratie_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        rij = session.scalars(
            select(PlanningSignaalAfhandeling).where(
                PlanningSignaalAfhandeling.administratie_id == administratie_id,
                PlanningSignaalAfhandeling.gebruiker_id == gebruiker_id,
                PlanningSignaalAfhandeling.project_id == project_id,
                PlanningSignaalAfhandeling.jaar == jaar,
                PlanningSignaalAfhandeling.weeknummer == weeknummer,
                PlanningSignaalAfhandeling.soort == PlanningSignaalSoort.AFGEMELD.value,
                PlanningSignaalAfhandeling.ingetrokken_op.is_(None),
            )
        ).first()
        if rij is None:
            raise OngeldigeOvergang("Dit signaal is niet afgemeld")
        rij.ingetrokken_door = actor_id
        rij.ingetrokken_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="planning_signaal_afhandeling",
            record_id=rij.id,
            actie="planning_signaal_afmelding_ingetrokken",
            correlatie_id=gebruiker_id,
            oude_waarde={"status": "afgemeld", "reden": rij.reden},
            nieuwe_waarde={"status": "open"},
            administratie_id=administratie_id,
        )
        return rij.id
