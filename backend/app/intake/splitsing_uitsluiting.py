""" "Nooit splitsen" per afzender (blok B medewerker-wensen 04-09, migratie 0106).

Casus Universal Nederland / Delta: één factuur MÉT bijlagen (werkbonnen, urenstaten, pakbonnen) die
de splitsings-AI toch in delen wil knippen — élke mail opnieuw. De mens corrigeert dat één keer via
"Is één factuur" mét de vink "Onthoud: mails van ‹afzender› voor ‹administratie› nooit splitsen";
daarna slaat de intake voor dat afzenderadres de splitsings-AI over (géén AI-call, kostenmeter
onaangeroerd) en gaat het document als één geheel door de bestaande keten.

Twee sleutels, bewust gescheiden (beslispunt Peter in BESLISSINGEN):
- BEHEER per administratie (`administratie_id`) — de regel staat op de detailpagina van de BV waar
  de mens 'm koppelde en wordt dáár verwijderd (= gedeactiveerd, nooit hard weg).
- MATCH bij de intake KANTOORBREED op `afzender_adres` — op dat moment is de administratie nog
  onbekend (zelfde reden als het toewijzings-geheugen, `toewijzing_regel`). Wijst precies één
  administratie een regel voor de afzender, dan gaat die als SUGGESTIE mee (nooit auto-toewijzing;
  tenaamstelling/afzender-regel blijven leidend).

Kantoor-/doorstuurdomeinen (`intake_afzender_uitgesloten_domeinen`) krijgen géén regel: zo'n adres
is per definitie meerduidig (diagnose 02-09 punt 3). Alle mutaties geauditeerd."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker
from app.db.session import scoped_session
from app.intake.models import IntakeSplitsingUitsluiting
from app.intake.toewijzing import afzender_uitgesloten, normaliseer_afzender

#: Technische intake-reden (prefix) — vertaald in `app/intake/redenen.py`.
REDEN_PREFIX = "splitsing_overgeslagen_nooit_splitsen:"


class SplitsingUitsluitingFout(Exception):
    pass


class GeenAfzenderBekend(SplitsingUitsluitingFout):
    """Een upload zonder mail heeft geen afzender — er is niets om te onthouden."""


class AfzenderDomeinUitgesloten(SplitsingUitsluitingFout):
    """Kantoor-/doorstuurdomein: meerduidig, nooit een regel."""


class AdministratieVerplicht(SplitsingUitsluitingFout):
    pass


class OnbekendeAdministratie(SplitsingUitsluitingFout):
    pass


class RegelNietGevonden(SplitsingUitsluitingFout):
    pass


@dataclass(frozen=True)
class UitsluitingTreffer:
    """Uitkomst van de kantoorbrede intake-toets: welke actieve regels dit afzenderadres dragen."""

    afzender_adres: str
    regel_ids: tuple[uuid.UUID, ...]
    administratie_ids: tuple[uuid.UUID, ...]

    @property
    def enige_administratie_id(self) -> uuid.UUID | None:
        """Suggestie voor de verzamelbak: alleen als exact één administratie de afzender uitsluit."""
        uniek = set(self.administratie_ids)
        return next(iter(uniek)) if len(uniek) == 1 else None


def actieve_regels_voor_afzender(session: Session, afzender: str | None) -> list[IntakeSplitsingUitsluiting]:
    sleutel = normaliseer_afzender(afzender)
    if not sleutel:
        return []
    return list(
        session.scalars(
            select(IntakeSplitsingUitsluiting)
            .where(
                IntakeSplitsingUitsluiting.afzender_adres == sleutel,
                IntakeSplitsingUitsluiting.actief.is_(True),
            )
            .order_by(IntakeSplitsingUitsluiting.aangemaakt_op)
        ).all()
    )


def vind_uitsluiting(afzender: str | None) -> UitsluitingTreffer | None:
    """Intake-toets (kantoorbreed, `scoped_session(None)` — er is nog geen administratie): None =
    gewoon de splitsings-AI draaien. Uitgesloten domeinen kunnen geen regel dragen, maar de toets
    weigert er ook op — een oude regel van vóór een config-uitbreiding mag nooit stil doorwerken."""
    sleutel = normaliseer_afzender(afzender)
    if not sleutel or afzender_uitgesloten(sleutel):
        return None
    with scoped_session(None) as session:
        regels = actieve_regels_voor_afzender(session, sleutel)
        if not regels:
            return None
        return UitsluitingTreffer(
            afzender_adres=sleutel,
            regel_ids=tuple(r.id for r in regels),
            administratie_ids=tuple(r.administratie_id for r in regels),
        )


def maak_regel(
    session: Session,
    *,
    administratie_id: uuid.UUID | None,
    afzender: str | None,
    leverancier_naam: str | None,
    reden: str | None,
    actor_id: uuid.UUID,
    bron_splitsing_id: uuid.UUID | None = None,
) -> IntakeSplitsingUitsluiting:
    """Legt de regel vast (idempotent: een bestaande actieve regel op dezelfde sleutel wordt
    teruggegeven, geen tweede rij) mét audit `splitsing_uitsluiting_aangemaakt`. De sessie mag
    administratie-loos gescoped zijn (afwijs-route) — het audit-feit is dan platform-breed
    (`administratie_id=None`, doel in `nieuwe_waarde`; audit_event-RLS eist anders scope = doel)."""
    if administratie_id is None:
        raise AdministratieVerplicht("Kies de administratie waarvoor deze afzender nooit gesplitst mag worden.")
    sleutel = normaliseer_afzender(afzender)
    if not sleutel:
        raise GeenAfzenderBekend(
            "Dit document heeft geen afzenderadres (upload zonder e-mail) — er is niets om te onthouden."
        )
    if afzender_uitgesloten(sleutel):
        raise AfzenderDomeinUitgesloten(
            f"Het afzenderadres {sleutel} hoort bij een kantoor-/doorstuurdomein en is daarmee meerduidig — "
            "daarvoor wordt geen 'nooit splitsen'-regel vastgelegd."
        )
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.actief:
        raise OnbekendeAdministratie("Onbekende of gearchiveerde administratie.")

    bestaand = session.scalars(
        select(IntakeSplitsingUitsluiting).where(
            IntakeSplitsingUitsluiting.administratie_id == administratie_id,
            IntakeSplitsingUitsluiting.afzender_adres == sleutel,
            IntakeSplitsingUitsluiting.actief.is_(True),
        )
    ).first()
    if bestaand is not None:
        return bestaand

    regel = IntakeSplitsingUitsluiting(
        administratie_id=administratie_id,
        afzender_adres=sleutel,
        leverancier_naam=(leverancier_naam or "").strip() or None,
        reden=(reden or "").strip() or None,
        aangemaakt_door=actor_id,
    )
    session.add(regel)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="intake_splitsing_uitsluiting",
        record_id=regel.id,
        actie="splitsing_uitsluiting_aangemaakt",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "administratie_id": str(administratie_id),
            "afzender_adres": sleutel,
            "leverancier_naam": regel.leverancier_naam,
            "reden": regel.reden,
            "bron_splitsing_id": str(bron_splitsing_id) if bron_splitsing_id else None,
        },
        administratie_id=None,
    )
    return regel


@dataclass(frozen=True)
class RegelRij:
    id: uuid.UUID
    administratie_id: uuid.UUID
    afzender_adres: str
    leverancier_naam: str | None
    reden: str | None
    aangemaakt_op: datetime
    aangemaakt_door: uuid.UUID
    aangemaakt_door_naam: str | None


def lijst_regels(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> list[RegelRij]:
    """Actieve regels van één administratie (beheerplek op de detailpagina)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rijen = session.execute(
            select(IntakeSplitsingUitsluiting, Gebruiker.naam)
            .join(Gebruiker, Gebruiker.id == IntakeSplitsingUitsluiting.aangemaakt_door, isouter=True)
            .where(
                IntakeSplitsingUitsluiting.administratie_id == administratie_id,
                IntakeSplitsingUitsluiting.actief.is_(True),
            )
            .order_by(IntakeSplitsingUitsluiting.aangemaakt_op.desc())
        ).all()
        return [
            RegelRij(
                id=regel.id,
                administratie_id=regel.administratie_id,
                afzender_adres=regel.afzender_adres,
                leverancier_naam=regel.leverancier_naam,
                reden=regel.reden,
                aangemaakt_op=regel.aangemaakt_op,
                aangemaakt_door=regel.aangemaakt_door,
                aangemaakt_door_naam=naam,
            )
            for regel, naam in rijen
        ]


def deactiveer_regel(*, administratie_id: uuid.UUID, regel_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """ "Verwijderen" in de UI = deactiveren mét audit `splitsing_uitsluiting_verwijderd`; de rij blijft
    (historie). Een regel van een andere administratie is hier onvindbaar (404) — scope server-side."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        regel = session.get(IntakeSplitsingUitsluiting, regel_id)
        if regel is None or regel.administratie_id != administratie_id or not regel.actief:
            raise RegelNietGevonden("Onbekende of al verwijderde 'nooit splitsen'-regel.")
        regel.actief = False
        regel.verwijderd_op = datetime.now(UTC)
        regel.verwijderd_door = actor_id
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="intake_splitsing_uitsluiting",
            record_id=regel.id,
            actie="splitsing_uitsluiting_verwijderd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": True, "afzender_adres": regel.afzender_adres},
            nieuwe_waarde={"actief": False, "afzender_adres": regel.afzender_adres},
            administratie_id=administratie_id,
        )
