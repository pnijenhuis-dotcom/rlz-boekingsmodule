from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie, BoekenInstelling
from app.db.session import scoped_session


class BeheerFout(Exception):
    """Domeinfout in de beheer-servicelaag (bv. onbekende administratie)."""


# platform.boeken_instelling is een singleton (PK is een boolean, geen UUID) — audit_event vereist
# wél een record_id; de nil-UUID is hier een vaste, herkenbare placeholder voor "de ene globale
# instelling-rij", nooit een echte entiteit.
_BOEKEN_INSTELLING_RECORD_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def haal_boeken_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.boeken_ingeschakeld


def zet_boeken_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Boeken-failsafe (a), per-administratie deel (CLAUDE.md-taak 2.4) — Beheerder-only,
    afgedwongen door de router-dependency, niet hier. Elke wijziging in het audit_event, ook als
    de nieuwe waarde toevallig gelijk is aan de oude (geen stille no-op-detectie: een Beheerder
    die 'm bewust opnieuw bevestigt, mag daarvan ook een spoor verwachten). Sessie gescoped op
    None (platformbreed) — dit is een Beheerder-only beheerhandeling, geen document-/administratie-
    gescopede actie; audit_event.administratie_id blijft daarom bewust NULL (zelfde patroon als
    credentialstore/service.py::zet_credential — de RLS WITH CHECK op audit_event kent geen
    beheerder-bypass, alleen `administratie_id IS NULL OR administratie_id = current_administratie_id()`)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.boeken_ingeschakeld
        administratie.boeken_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="boeken_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"boeken_ingeschakeld": oud},
            nieuwe_waarde={"boeken_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


@dataclass(frozen=True)
class AdministratieBoekenStatus:
    administratie_id: uuid.UUID
    naam: str
    boeken_ingeschakeld: bool


def overzicht_boeken_status() -> list[AdministratieBoekenStatus]:
    """Voor `make boeken-status` (CLI-overzicht, geen endpoint — dit is een beheerhandeling
    zonder ingelogde gebruiker) — de globale kill switch zelf haalt de aanroeper apart op via
    haal_globale_kill_switch_op(), 'effectief aan' is beide tegelijk."""
    with scoped_session(None) as session:
        rijen = session.scalars(select(Administratie).order_by(Administratie.naam))
        return [
            AdministratieBoekenStatus(administratie_id=r.id, naam=r.naam, boeken_ingeschakeld=r.boeken_ingeschakeld)
            for r in rijen
        ]


@dataclass(frozen=True)
class AdministratieInstellingen:
    administratie_id: uuid.UUID
    naam: str
    boeken_ingeschakeld: bool
    project_verplicht: bool


def overzicht_administratie_instellingen() -> list[AdministratieInstellingen]:
    """Voor het instellingen-scherm (design-pass taak 3): beide schakelaars per administratie in
    één keer, i.p.v. de losse per-administratie GET-endpoints hierboven N keer aan te roepen.
    Los van `overzicht_boeken_status()` (CLI, alleen boeken_ingeschakeld) gehouden — dat commando
    hoeft niet mee te veranderen als deze lijst een derde kolom krijgt."""
    with scoped_session(None) as session:
        rijen = session.scalars(select(Administratie).order_by(Administratie.naam))
        return [
            AdministratieInstellingen(
                administratie_id=r.id,
                naam=r.naam,
                boeken_ingeschakeld=r.boeken_ingeschakeld,
                project_verplicht=r.project_verplicht,
            )
            for r in rijen
        ]


def haal_project_verplicht_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.project_verplicht


def zet_project_verplicht(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, verplicht: bool) -> bool:
    """Design-pass taak 4: bepaalt of de Project-kolom in het controlescherm zichtbaar/verplicht
    is voor deze administratie — Beheerder-only (router), audit als bij boeken_ingeschakeld."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.project_verplicht
        administratie.project_verplicht = verplicht
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="project_verplicht_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"project_verplicht": oud},
            nieuwe_waarde={"project_verplicht": verplicht},
        )
        return verplicht


def haal_globale_kill_switch_op() -> bool:
    with scoped_session(None) as session:
        instelling = session.get(BoekenInstelling, True)
        return instelling is not None and instelling.globaal_ingeschakeld


def zet_globale_kill_switch(*, actor_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Boeken-failsafe (a), globale deel — de platformbrede noodstop. Beheerder-only (router)."""
    with scoped_session(None, actor_id=actor_id) as session:
        instelling = session.get(BoekenInstelling, True)
        if instelling is None:
            raise BeheerFout("platform.boeken_instelling heeft geen rij — migratie 0008 niet toegepast?")
        oud = instelling.globaal_ingeschakeld
        instelling.globaal_ingeschakeld = ingeschakeld
        instelling.gewijzigd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="boeken_instelling",
            record_id=_BOEKEN_INSTELLING_RECORD_ID,
            actie="globale_kill_switch_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"globaal_ingeschakeld": oud},
            nieuwe_waarde={"globaal_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld
