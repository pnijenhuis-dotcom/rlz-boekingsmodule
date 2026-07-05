from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record_audit_event(
    session: Session,
    *,
    actor_id: uuid.UUID,
    module: str,
    tabel: str,
    record_id: uuid.UUID,
    actie: str,
    correlatie_id: uuid.UUID,
    oude_waarde: dict | None = None,
    nieuwe_waarde: dict | None = None,
    administratie_id: uuid.UUID | None = None,
) -> AuditEvent:
    """Leg één handeling append-only vast. Nooit los SQL schrijven — altijd via deze functie,
    zodat het schema (koppelcontract v1.5) op één plek blijft.
    """
    event = AuditEvent(
        id=uuid.uuid4(),
        actor_id=actor_id,
        module=module,
        tabel=tabel,
        record_id=record_id,
        actie=actie,
        correlatie_id=correlatie_id,
        oude_waarde=oude_waarde,
        nieuwe_waarde=nieuwe_waarde,
        administratie_id=administratie_id,
    )
    session.add(event)
    session.flush()
    return event
