"""IBAN-geheugen van de matchmotor (blok 2 bundel 08-09, migratie 0127).

Leren gebeurt op het bevestig-pad van een aflettering (afletteren.py): is de koppeling via de API
gelegd en geverifieerd — of zag de vooraf-toets de mutatie al in RLZ afgeletterd tegen precies de
voorgestelde post — dan hoort de tegenrekening-IBAN van de mutatie bij de RLZ-entity van de post.
Geen IBAN of geen entity op de post = niets leren (geen gok). Upsert: eerste keer = nieuwe rij +
audit, daarna alleen de tellers. Lezen doet voorstellen.laad_matchcontext (→ matchmotor.IbanRelatie)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.bank.matchmotor import IbanRelatie, normaliseer_iban
from app.bank.models import BankRelatieIban
from app.db.audit import record_audit_event

logger = logging.getLogger(__name__)


def leer_iban_relatie(
    session,
    *,
    administratie_id: uuid.UUID,
    iban: str | None,
    entity_guid: uuid.UUID | None,
    entity_naam: str | None,
    opdracht_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> BankRelatieIban | None:
    """Leg IBAN ↔ entity vast (of tel een bevestiging op). None = niets te leren."""
    genormaliseerd = normaliseer_iban(iban)
    if genormaliseerd is None or entity_guid is None:
        return None
    nu = datetime.now(UTC)
    rij = session.scalars(
        select(BankRelatieIban).where(
            BankRelatieIban.administratie_id == administratie_id,
            BankRelatieIban.iban == genormaliseerd,
            BankRelatieIban.entity_guid == entity_guid,
        )
    ).first()
    if rij is not None:
        rij.aantal_bevestigingen += 1
        rij.laatste_bevestiging_op = nu
        rij.laatste_opdracht_id = opdracht_id
        if entity_naam and not rij.entity_naam:
            rij.entity_naam = entity_naam
        return rij
    rij = BankRelatieIban(
        administratie_id=administratie_id,
        iban=genormaliseerd,
        entity_guid=entity_guid,
        entity_naam=entity_naam,
        aantal_bevestigingen=1,
        eerste_bevestiging_op=nu,
        laatste_bevestiging_op=nu,
        laatste_opdracht_id=opdracht_id,
    )
    session.add(rij)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="bank_relatie_iban",
        record_id=rij.id,
        actie="bank_iban_relatie_geleerd",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "iban": genormaliseerd,
            "entity_guid": str(entity_guid),
            "entity_naam": entity_naam,
            "opdracht_id": str(opdracht_id) if opdracht_id else None,
        },
        administratie_id=administratie_id,
    )
    logger.info("IBAN-relatie geleerd voor administratie %s: entity %s", administratie_id, entity_guid)
    return rij


def iban_relaties_voor(session, *, administratie_id: uuid.UUID) -> list[IbanRelatie]:
    return [
        IbanRelatie(iban=rij.iban, entity_guid=rij.entity_guid)
        for rij in session.scalars(
            select(BankRelatieIban).where(BankRelatieIban.administratie_id == administratie_id)
        )
    ]
