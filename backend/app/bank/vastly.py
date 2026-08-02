"""Vastly-terugkoppeling "factuur afgeletterd" (tier-model, bankmodule 2026-08-02).

Detectie op RLZ-documentstatus: een lokaal GEBOEKT document van een vastgoed-administratie dat
in RLZ status 3 (Gesloten — volledig betaald/afgeletterd, DocumentStatuses-enumeratie
2026-07-13) bereikt, krijgt precies één "factuur_afgeletterd"-outbox-rij. De bestaande
webhook-afleveraar (HMAC per verzendpoging, retry/backoff, dead-letter, toggle default UIT)
doet de rest — geen nieuw kanaal.

Omdat de detectie op de documentstatus toetst werkt hij onafhankelijk van hóé er is
afgeletterd: in de RLZ-UI (assist-model), via een toekomstige API-route, of door RLZ's eigen
bankverwerking. Idempotent: de bestaande outbox-rij (document + event) ís de marker — geen
extra kolom, geen dubbele meldingen."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, Document, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.documenten.webhook import FACTUUR_AFGELETTERD_EVENT, bouw_factuur_afgeletterd_payload
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import rlz_admin_id_voor

logger = logging.getLogger(__name__)

# RLZ-documentstatus 3 = Gesloten (volledig betaald/afgeletterd, BaseRemainingAmount 0) —
# geverifieerde enumeratie, zie CLAUDE.md "Reeleezee API".
_STATUS_GESLOTEN = 3


def detecteer_en_meld_afgeletterd(*, administratie_id: uuid.UUID, client: RlzClient) -> int:
    """Draait in elke bank-sync. Alleen vastgoed-administraties (`is_vastgoed`, zelfde scope als
    het geboekt-event); per kandidaat-document één GET op de RLZ-factuur. Eén kapot document
    stopt de rest niet (zichtbaar gelogd, volgende sync opnieuw)."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.is_vastgoed:
            return 0
    rlz_admin_id = rlz_admin_id_voor(administratie_id)

    with scoped_session(administratie_id) as session:
        al_gemeld = set(
            session.scalars(
                select(WebhookUitgaand.document_id).where(
                    WebhookUitgaand.event == FACTUUR_AFGELETTERD_EVENT
                )
            )
        )
        kandidaten = [
            (document.id, voorstel.rlz_boekstuknummer, voorstel.referentie)
            for document, voorstel in session.execute(
                select(Document, Boekvoorstel)
                .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.status == DocumentStatus.GEBOEKT,
                )
            )
            if document.id not in al_gemeld
        ]

    gemeld = 0
    for document_id, boekstuknummer, referentie in kandidaten:
        rlz_document_id = rlz_purchase_invoice_id(document_id)
        try:
            factuur = client.get(f"PurchaseInvoices/{rlz_document_id}")
        except RlzApiError as exc:
            logger.warning(
                "Afgeletterd-detectie: RLZ-factuur %s (document %s) niet leesbaar: %s",
                rlz_document_id,
                document_id,
                exc,
            )
            continue
        if factuur.get("Status") != _STATUS_GESLOTEN:
            continue

        nu = datetime.now(UTC)
        payload = bouw_factuur_afgeletterd_payload(
            administratie_id=administratie_id,
            rlz_admin_id=rlz_admin_id,
            rlz_document_id=rlz_document_id,
            rlz_boekstuknummer=boekstuknummer,
            referentie=referentie,
            geconstateerd_op=nu,
        )
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            # Race-vangnet: intussen (parallelle sync) al gemeld → overslaan.
            bestaat = session.scalars(
                select(WebhookUitgaand.id).where(
                    WebhookUitgaand.document_id == document_id,
                    WebhookUitgaand.event == FACTUUR_AFGELETTERD_EVENT,
                )
            ).first()
            if bestaat is not None:
                continue
            session.add(
                WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload)
            )
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie="factuur_afgeletterd_gedetecteerd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "rlz_document_id": str(rlz_document_id),
                    "rlz_boekstuknummer": boekstuknummer,
                    "event": FACTUUR_AFGELETTERD_EVENT,
                },
                administratie_id=administratie_id,
            )
        gemeld += 1
    return gemeld
