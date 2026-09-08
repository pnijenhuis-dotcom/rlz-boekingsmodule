"""Beheerder-instelling "Intercompany-leveranciers" per administratie (nachtrun 08/09-09, blok 1).

Schrijft en leest DEZELFDE tabel als de doorbelasting-mapping en de leesbron `intercompany.py`
(`boekhouding.intercompany_tegenpartij`, migratie 0045) — geen tweede bron. Twee herkomsten:
- `bron = 'doorbelasting_mapping'` (default van de tabel): onderhouden door de doorbelasting-service, hier
  ALLEEN-LEZEN (verwijderen kan alleen via de mapping);
- `bron = 'handmatig'`: gezet door een Beheerder via Instellingen › Administraties › ‹BV› › Klant-accordering of de CLI
  `intercompany-leverancier-markeren` (blok 2: eenmalige rij Universal Nederland → Universal Steigerbouw).

Verwijderen = `actief=False` (nooit delete — kernprincipe 4/niets verdwijnt stil; de leesbron kijkt alleen naar actieve
rijen). Elke mutatie: audit `intercompany_leverancier_gewijzigd` oud→nieuw op de administratie; de GET levert de
recente audit-regels als tijdlijn van de instelling. Geen AI, geen RLZ-calls — de naam komt uit de vendor-cache.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import AuditEvent, Gebruiker
from app.db.session import scoped_session
from app.doorbelasting.models import IntercompanyTegenpartij
from app.sync.models import VendorCache

BRON_HANDMATIG = "handmatig"
BRON_DOORBELASTING = "doorbelasting_mapping"
AUDIT_ACTIE = "intercompany_leverancier_gewijzigd"
_TABEL = "intercompany_tegenpartij"
_MODULE = "boekhouding"
_HISTORIE_MAX = 25


class IntercompanyBeheerFout(Exception):
    """Basisfout — de router vertaalt naar 404/409 met de melding als detail."""


class CrediteurOnbekend(IntercompanyBeheerFout):
    pass


class RijUitDoorbelasting(IntercompanyBeheerFout):
    """Een mapping-rij is hier alleen-lezen: aan/uit volgt de doorbelasting-mapping."""


@dataclass(frozen=True)
class IntercompanyLeverancier:
    vendor_id: uuid.UUID
    naam: str
    bron: str  # 'handmatig' | 'doorbelasting_mapping'
    actief: bool
    gewijzigd_op: datetime | None

    @property
    def verwijderbaar(self) -> bool:
        return self.bron == BRON_HANDMATIG


@dataclass(frozen=True)
class IntercompanyHistorieRegel:
    tijdstip: datetime
    actor_naam: str | None
    actie: str  # 'gemarkeerd' | 'verwijderd'
    vendor_id: uuid.UUID | None
    naam: str | None
    reden: str | None
    bron: str | None


def _naar_dto(rij: IntercompanyTegenpartij) -> IntercompanyLeverancier:
    return IntercompanyLeverancier(
        vendor_id=rij.entity_guid, naam=rij.naam, bron=rij.bron, actief=rij.actief, gewijzigd_op=rij.gewijzigd_op
    )


def _snapshot(rij: IntercompanyTegenpartij | None) -> dict | None:
    if rij is None:
        return None
    return {"entity_guid": str(rij.entity_guid), "naam": rij.naam, "bron": rij.bron, "actief": rij.actief}


def lijst_intercompany_leveranciers(session: Session, *, administratie_id: uuid.UUID) -> list[IntercompanyLeverancier]:
    """Alle ACTIEVE IC-rijen van deze administratie (beide herkomsten), gesorteerd op naam."""
    rijen = session.scalars(
        select(IntercompanyTegenpartij)
        .where(IntercompanyTegenpartij.administratie_id == administratie_id, IntercompanyTegenpartij.actief.is_(True))
        .order_by(IntercompanyTegenpartij.naam, IntercompanyTegenpartij.entity_guid)
    ).all()
    return [_naar_dto(r) for r in rijen]


def historie_intercompany_leveranciers(
    session: Session, *, administratie_id: uuid.UUID, limiet: int = _HISTORIE_MAX
) -> list[IntercompanyHistorieRegel]:
    """Recente mutaties van de instelling (audit-spoor van deze tabel op deze administratie) — de tijdlijn van de
    instelling; nieuwste eerst."""
    rijen = session.execute(
        select(AuditEvent, Gebruiker.naam)
        .join(Gebruiker, Gebruiker.id == AuditEvent.actor_id, isouter=True)
        .where(
            AuditEvent.administratie_id == administratie_id,
            AuditEvent.tabel == _TABEL,
            AuditEvent.actie == AUDIT_ACTIE,
        )
        .order_by(AuditEvent.tijdstip.desc(), AuditEvent.id.desc())
        .limit(limiet)
    ).all()
    uit: list[IntercompanyHistorieRegel] = []
    for event, actor_naam in rijen:
        nieuw = event.nieuwe_waarde or {}
        oud = event.oude_waarde or {}
        stand = nieuw if nieuw else oud
        uit.append(
            IntercompanyHistorieRegel(
                tijdstip=event.tijdstip,
                actor_naam=actor_naam,
                actie="gemarkeerd" if nieuw.get("actief") else "verwijderd",
                vendor_id=uuid.UUID(stand["entity_guid"]) if stand.get("entity_guid") else None,
                naam=stand.get("naam"),
                reden=nieuw.get("reden") if isinstance(nieuw, dict) else None,
                bron=stand.get("bron"),
            )
        )
    return uit


def markeer_intercompany_leverancier(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID, reden: str | None = None
) -> IntercompanyLeverancier:
    """Zet (of heractiveert) de handmatige IC-vlag voor deze crediteur in deze administratie. Idempotent: een al
    actieve rij blijft staan (wel een audit-regel — zelfde bewuste conventie als de beheer-toggles). Een bestaande
    mapping-rij wordt niet overschreven (die is al actief óf volgt de mapping) — heractiveren van een inactieve
    mapping-rij gebeurt hier bewust als handmatige rij (bron wisselt naar 'handmatig', zichtbaar in de audit).
    Beheerder-only wordt in de router/CLI afgedwongen."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vendor = session.get(VendorCache, (vendor_id, administratie_id))
        if vendor is None or not vendor.naam:
            raise CrediteurOnbekend("Deze crediteur staat niet in de crediteuren van deze administratie")
        bestaand = session.scalars(
            select(IntercompanyTegenpartij).where(
                IntercompanyTegenpartij.administratie_id == administratie_id,
                IntercompanyTegenpartij.entity_guid == vendor_id,
            )
        ).one_or_none()
        oud = _snapshot(bestaand)
        if bestaand is None:
            bestaand = IntercompanyTegenpartij(
                administratie_id=administratie_id,
                entity_guid=vendor_id,
                naam=vendor.naam,
                bron=BRON_HANDMATIG,
                actief=True,
            )
            session.add(bestaand)
        elif not bestaand.actief:
            bestaand.actief = True
            bestaand.bron = BRON_HANDMATIG
            bestaand.naam = vendor.naam
        nieuw = _snapshot(bestaand)
        assert nieuw is not None
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel=_TABEL,
            record_id=vendor_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={**nieuw, "reden": reden},
            administratie_id=administratie_id,
        )
        session.flush()
        session.refresh(bestaand)
        return _naar_dto(bestaand)


def verwijder_intercompany_leverancier(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID, reden: str | None = None
) -> None:
    """Handmatige IC-vlag weg = `actief=False` (nooit delete). Een rij uit de doorbelasting-mapping is alleen-lezen
    (409 in de router). Onbekende of al inactieve rij = 404."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.scalars(
            select(IntercompanyTegenpartij).where(
                IntercompanyTegenpartij.administratie_id == administratie_id,
                IntercompanyTegenpartij.entity_guid == vendor_id,
                IntercompanyTegenpartij.actief.is_(True),
            )
        ).one_or_none()
        if rij is None:
            raise CrediteurOnbekend("Deze leverancier is in deze administratie niet als intercompany gemarkeerd")
        if rij.bron != BRON_HANDMATIG:
            raise RijUitDoorbelasting(
                "Deze leverancier komt uit de doorbelasting-mapping — de vlag volgt die mapping (tab Doorbelasting)"
            )
        oud = _snapshot(rij)
        rij.actief = False
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel=_TABEL,
            record_id=vendor_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={**(_snapshot(rij) or {}), "reden": reden},
            administratie_id=administratie_id,
        )
