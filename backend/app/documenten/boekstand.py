"""Boekstand-reeks van een RLZ-document in de webhook-outbox (koppelcontract §3 v1.14).

`factuur_geboekt` en `factuur_gestorneerd` delen per rlz_document_id één monotoon oplopende
volgnummer-reeks (boeken=1, storno=2, herboeken=3 …), zodat de ontvanger de boekstand kan
ordenen ongeacht afleveringsvolgorde. De stand leeft in de outbox-rijen zelf (payload.data —
zelfde idempotentie-anker als het afgeletterd-event, app/bank/vastly.py): geen extra tabel.

Het filter loopt op payload.data.rlz_document_id, niet alleen op de document_id-kolom: één
bron-document kan meerdere RLZ-documenten voortbrengen (doorbelasting-spiegels per
doelentiteit dragen allemaal het bron-document als document_id) en elke spiegel heeft zijn
eigen reeks. Scope is de verantwoordelijkheid van de aanroeper: de meegegeven session bepaalt
via RLS welke rijen zichtbaar zijn (inkoop/verkoop: eigen administratie via het document;
spiegel: de doel-administratie via de administratie_id-kolom, migratie 0046).

Events in het 1.0-formaat (zonder volgnummer) tellen als volgnummer 0 mét hun event-naam:
een vóór de 1.1-bump geboekt document heeft dan stand (0, factuur_geboekt) — een latere
storno krijgt volgnummer 1 en wint bij de ontvanger (1.0-events gelden daar ook als 0).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documenten.models import WebhookUitgaand
from app.documenten.webhook import FACTUUR_GEBOEKT_EVENT, FACTUUR_GESTORNEERD_EVENT

_BOEKSTAND_EVENTS = (FACTUUR_GEBOEKT_EVENT, FACTUUR_GESTORNEERD_EVENT)


def stand_van_rij(rij: WebhookUitgaand) -> int:
    """Volgnummer van één outbox-rij; 1.0-formaat (zonder volgnummer) telt als stand 0."""
    volgnummer = ((rij.payload or {}).get("data") or {}).get("volgnummer")
    return volgnummer if isinstance(volgnummer, int) else 0


def laatste_boekstand_rij(
    session: Session, *, document_id: uuid.UUID, rlz_document_id: uuid.UUID
) -> WebhookUitgaand | None:
    """De outbox-rij met de hoogste boekstand van dit RLZ-document; None als er nog geen enkel
    boekstand-event bestaat. Bij een gelijk volgnummer (hoort niet voor te komen) wint de
    laatst aangemaakte rij."""
    rijen = session.scalars(
        select(WebhookUitgaand)
        .where(
            WebhookUitgaand.document_id == document_id,
            WebhookUitgaand.event.in_(_BOEKSTAND_EVENTS),
        )
        .order_by(WebhookUitgaand.aangemaakt_op.asc().nulls_last())
    ).all()
    hoogste: WebhookUitgaand | None = None
    for rij in rijen:
        data = (rij.payload or {}).get("data") or {}
        if data.get("rlz_document_id") != str(rlz_document_id):
            continue
        if hoogste is None or stand_van_rij(rij) >= stand_van_rij(hoogste):
            hoogste = rij
    return hoogste


def laatste_boekstand(
    session: Session, *, document_id: uuid.UUID, rlz_document_id: uuid.UUID
) -> tuple[int, str | None]:
    """(hoogste volgnummer, event van die hoogste stand); (0, None) zonder events."""
    rij = laatste_boekstand_rij(session, document_id=document_id, rlz_document_id=rlz_document_id)
    if rij is None:
        return 0, None
    return stand_van_rij(rij), rij.event


def volgend_volgnummer(session: Session, *, document_id: uuid.UUID, rlz_document_id: uuid.UUID) -> int:
    hoogste, _ = laatste_boekstand(session, document_id=document_id, rlz_document_id=rlz_document_id)
    return hoogste + 1
