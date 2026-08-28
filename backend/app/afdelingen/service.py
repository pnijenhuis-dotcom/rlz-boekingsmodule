"""Afdelingen-beheer (bouwrun 28-08 blok A, mockup afdelingen.html §1 = bouwnorm).

Toggle per administratie (project_verplicht-patroon, Beheerder-only, audit): AAN maakt automatisch
de terugval-afdeling "Algemeen" aan (volgt de administratie-accorderingsconfig — de toggle breekt
niets aan lopende routes en er is altijd een geldige keuze). Afdelingen worden gearchiveerd, nooit
verwijderd (documenten verwijzen ernaar). De accorderingsroute per afdeling leeft in
app/accordering/service.py (zelfde lagen-bouwstenen, `AccorderingLaag.afdeling_id`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accordering.models import AccorderingLaag, StaandeGoedkeuring
from app.afdelingen.models import Afdeling, LeverancierAfdeling
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.sync.models import VendorCache

TERUGVAL_NAAM = "Algemeen"


class AfdelingFout(Exception):
    """Leesbare beheerfout (router → 409/404)."""


class AfdelingNietGevonden(AfdelingFout):
    pass


@dataclass(frozen=True)
class RouteLaag:
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    bedrag_drempel: Decimal | None


@dataclass(frozen=True)
class AfdelingOverzicht:
    id: uuid.UUID
    naam: str
    is_terugval: bool
    actief: bool
    # Route van déze afdeling (eigen lagen). Terugval = leeg: die volgt de administratie-route.
    route: tuple[RouteLaag, ...]
    staande_goedkeuringen: int
    gearchiveerd_op: datetime | None


def is_ingeschakeld(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie is not None and administratie.afdelingen_ingeschakeld


def afdelingen_ingeschakeld_in_sessie(session: Session, administratie_id: uuid.UUID) -> bool:
    administratie = session.get(Administratie, administratie_id)
    return administratie is not None and administratie.afdelingen_ingeschakeld


def zet_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Beheerder-only (router). AAN = terugval-afdeling "Algemeen" garanderen. UIT laat de
    afdelingen en de per-document-keuzes staan (niets verdwijnt) — het veld is dan onzichtbaar
    en de check zwijgt; de accorderingsroute valt terug op de administratie-route."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise AfdelingNietGevonden(f"Onbekende administratie: {administratie_id}")
        oud = administratie.afdelingen_ingeschakeld
        administratie.afdelingen_ingeschakeld = ingeschakeld
        naam = administratie.naam
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="afdelingen_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"afdelingen_ingeschakeld": oud},
            nieuwe_waarde={"afdelingen_ingeschakeld": ingeschakeld},
        )
    if ingeschakeld:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            zorg_voor_terugval(session, administratie_id=administratie_id, actor_id=actor_id)
    del naam
    return ingeschakeld


def zorg_voor_terugval(session: Session, *, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> Afdeling:
    """Precies één terugval-afdeling per administratie (partiële unique index 0084); bestaat ze
    (ook gearchiveerd — kan niet, maar defensief), dan wordt ze hergebruikt en geactiveerd."""
    bestaande = session.scalars(
        select(Afdeling).where(Afdeling.administratie_id == administratie_id, Afdeling.is_terugval.is_(True))
    ).first()
    if bestaande is not None:
        if not bestaande.actief:
            bestaande.actief = True
            bestaande.gearchiveerd_door = None
            bestaande.gearchiveerd_op = None
        return bestaande
    terugval = Afdeling(
        administratie_id=administratie_id, naam=TERUGVAL_NAAM, is_terugval=True, aangemaakt_door=actor_id
    )
    session.add(terugval)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="afdeling",
        record_id=terugval.id,
        actie="afdeling_aangemaakt",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"naam": TERUGVAL_NAAM, "is_terugval": True},
        administratie_id=administratie_id,
    )
    return terugval


def actieve_afdelingen(session: Session, administratie_id: uuid.UUID) -> dict[uuid.UUID, Afdeling]:
    return {
        a.id: a
        for a in session.scalars(
            select(Afdeling).where(Afdeling.administratie_id == administratie_id, Afdeling.actief.is_(True))
        )
    }


def afdeling_namen(session: Session, administratie_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Álle afdelingen (ook gearchiveerd) — voor weergave van historische keuzes."""
    return dict(
        session.execute(select(Afdeling.id, Afdeling.naam).where(Afdeling.administratie_id == administratie_id)).all()
    )


def terugval_id(session: Session, administratie_id: uuid.UUID) -> uuid.UUID | None:
    return session.scalars(
        select(Afdeling.id).where(Afdeling.administratie_id == administratie_id, Afdeling.is_terugval.is_(True))
    ).first()


def lijst(*, administratie_id: uuid.UUID) -> list[AfdelingOverzicht]:
    from app.accordering.service import _gebruikersnamen

    with scoped_session(administratie_id) as session:
        afdelingen = list(
            session.scalars(
                select(Afdeling)
                .where(Afdeling.administratie_id == administratie_id)
                .order_by(Afdeling.is_terugval, Afdeling.actief.desc(), Afdeling.naam)
            )
        )
        lagen = list(
            session.scalars(
                select(AccorderingLaag)
                .where(
                    AccorderingLaag.administratie_id == administratie_id,
                    AccorderingLaag.actief.is_(True),
                    AccorderingLaag.afdeling_id.is_not(None),
                )
                .order_by(AccorderingLaag.volgnummer)
            )
        )
        namen = _gebruikersnamen(session, {laag.accordeur_gebruiker_id for laag in lagen})
        staande = dict(
            session.execute(
                select(StaandeGoedkeuring.afdeling_id, func.count())
                .where(
                    StaandeGoedkeuring.administratie_id == administratie_id,
                    StaandeGoedkeuring.actief.is_(True),
                    StaandeGoedkeuring.afdeling_id.is_not(None),
                )
                .group_by(StaandeGoedkeuring.afdeling_id)
            ).all()
        )
        session.expunge_all()
    return [
        AfdelingOverzicht(
            id=a.id,
            naam=a.naam,
            is_terugval=a.is_terugval,
            actief=a.actief,
            route=tuple(
                RouteLaag(
                    volgnummer=laag.volgnummer,
                    accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                    accordeur_naam=namen.get(laag.accordeur_gebruiker_id),
                    bedrag_drempel=laag.bedrag_drempel,
                )
                for laag in lagen
                if laag.afdeling_id == a.id
            ),
            staande_goedkeuringen=staande.get(a.id, 0),
            gearchiveerd_op=a.gearchiveerd_op,
        )
        for a in afdelingen
    ]


def maak_aan(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, naam: str) -> AfdelingOverzicht:
    """Beheerder-only. Vereist de toggle aan (het beheer verschijnt pas dan — fail-closed ook
    server-side). Naam uniek onder de actieve afdelingen (case-insensitief, index 0084)."""
    schoon = " ".join(naam.split())
    if not schoon:
        raise AfdelingFout("Naam van de afdeling ontbreekt")
    if len(schoon) > 80:
        raise AfdelingFout("Naam van de afdeling is te lang (max 80 tekens)")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        if not afdelingen_ingeschakeld_in_sessie(session, administratie_id):
            raise AfdelingFout("Afdelingen staan uit voor deze administratie — zet eerst de toggle aan")
        bestaat = session.scalars(
            select(Afdeling.id).where(
                Afdeling.administratie_id == administratie_id,
                Afdeling.actief.is_(True),
                func.lower(Afdeling.naam) == schoon.lower(),
            )
        ).first()
        if bestaat is not None:
            raise AfdelingFout(f"Er bestaat al een actieve afdeling '{schoon}'")
        afdeling = Afdeling(administratie_id=administratie_id, naam=schoon, aangemaakt_door=actor_id)
        session.add(afdeling)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="afdeling",
            record_id=afdeling.id,
            actie="afdeling_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"naam": schoon, "is_terugval": False},
            administratie_id=administratie_id,
        )
        afdeling_id = afdeling.id
    return next(a for a in lijst(administratie_id=administratie_id) if a.id == afdeling_id)


def archiveer(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, afdeling_id: uuid.UUID) -> None:
    """Archiveren, nooit verwijderen. De terugval is niet archiveerbaar (er moet altijd een
    geldige keuze zijn). Documenten die nog naar deze afdeling wijzen houden de verwijzing; de
    harde check "Afdeling" blokkeert ze tot een actieve afdeling gekozen is — zichtbaar, niet stil.
    De eigen lagen worden mee gedeactiveerd (route hoort bij een levende afdeling)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        afdeling = session.get(Afdeling, afdeling_id)
        if afdeling is None or afdeling.administratie_id != administratie_id:
            raise AfdelingNietGevonden(f"Onbekende afdeling: {afdeling_id}")
        if afdeling.is_terugval:
            raise AfdelingFout("De terugval-afdeling 'Algemeen' kan niet gearchiveerd worden")
        if not afdeling.actief:
            raise AfdelingFout("Deze afdeling is al gearchiveerd")
        nu = datetime.now(UTC)
        afdeling.actief = False
        afdeling.gearchiveerd_door = actor_id
        afdeling.gearchiveerd_op = nu
        lagen = list(
            session.scalars(
                select(AccorderingLaag).where(
                    AccorderingLaag.afdeling_id == afdeling_id, AccorderingLaag.actief.is_(True)
                )
            )
        )
        for laag in lagen:
            laag.actief = False
            laag.gedeactiveerd_door = actor_id
            laag.gedeactiveerd_op = nu
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="afdeling",
            record_id=afdeling_id,
            actie="afdeling_gearchiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": True},
            nieuwe_waarde={"actief": False, "lagen_gedeactiveerd": len(lagen)},
            administratie_id=administratie_id,
        )


@dataclass(frozen=True)
class AfdelingPrefill:
    afdeling_id: uuid.UUID
    leverancier_naam: str | None


def prefill_voor_vendor(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None
) -> AfdelingPrefill | None:
    """Vorige keuze voor deze leverancier — alleen als die afdeling nog actief is (een gearchiveerde
    afdeling wordt nooit voorgesteld). Voorstel, geen invulling: het scherm toont de herkomst-chip."""
    if vendor_id is None:
        return None
    rij = session.get(LeverancierAfdeling, (administratie_id, vendor_id))
    if rij is None:
        return None
    afdeling = session.get(Afdeling, rij.afdeling_id)
    if afdeling is None or not afdeling.actief:
        return None
    vendor = session.get(VendorCache, (vendor_id, administratie_id))
    return AfdelingPrefill(afdeling_id=rij.afdeling_id, leverancier_naam=vendor.naam if vendor else None)


def onthoud_keuze(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    afdeling_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """Laatste keuze wint (mockup-beslispunt 3). Alleen een échte wijziging krijgt een audit_event —
    elke opslaan-actie herhaalt anders dezelfde stand."""
    rij = session.get(LeverancierAfdeling, (administratie_id, vendor_id))
    oud = rij.afdeling_id if rij else None
    if oud == afdeling_id:
        return
    if rij is None:
        session.add(
            LeverancierAfdeling(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                afdeling_id=afdeling_id,
                laatste_document_id=document_id,
                gewijzigd_door=actor_id,
            )
        )
    else:
        rij.afdeling_id = afdeling_id
        rij.laatste_document_id = document_id
        rij.gewijzigd_door = actor_id
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="leverancier_afdeling",
        record_id=vendor_id,
        actie="leverancier_afdeling_onthouden",
        correlatie_id=document_id,
        oude_waarde={"afdeling_id": str(oud)} if oud is not None else None,
        nieuwe_waarde={"afdeling_id": str(afdeling_id)},
        administratie_id=administratie_id,
    )
