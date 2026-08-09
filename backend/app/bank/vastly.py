"""Vastly-terugkoppeling "factuur afgeletterd" — velddefinitie DEFINITIEF (koppelcontract §3
v1.11, omgebouwd blok 3 grote opdracht 2026-08-09; event blijft UIT tot vastgoeds verwerker).

Detectie per bank-sync op de wérkelijke RLZ-bedragstand (BaseRemainingAmount — nooit
IsComplete, bewezen stale): elke STANDWIJZIGING van een lokaal GEBOEKT document van een
tier-administratie (vlag `afgeletterd_event_ingeschakeld`, besluit 0018 — naast `is_vastgoed`)
levert één outbox-rij met cumulatief betaald_bedrag + open_bedrag, een per document monotoon
oplopend volgnummer en het scenario:

- `afgeletterd`       — open_bedrag 0 (volledig betaald/afgeletterd);
- `deel_afgeletterd`  — betaald nam toe, open_bedrag > 0 (G-rekening-split = standaardcase);
- `ont_afgeletterd`   — betaald nam áf (in de RLZ-UI teruggedraaid) — expliciet, nooit stil.

De laatst gemelde stand + het volgnummer leven in de outbox-rijen zelf (payload.data —
idempotentie-anker, geen extra tabel): geen standwijziging = geen nieuwe rij. Outbox-rijen in
het oude v1.10-formaat (zonder volgnummer/bedragen) tellen bewust NIET als gemelde stand — een
document dat alleen zo'n oude rij heeft krijgt bij de eerstvolgende wijzigingloze sync alsnog
één v2.0-rij met de actuele stand (de definitieve vorm vervangt de vervallen binaire melding).
De bestaande webhook-afleveraar (HMAC per verzendpoging, retry/backoff, dead-letter, toggle
default UIT) doet de aflevering — geen nieuw kanaal."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, Document, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.documenten.webhook import (
    AFGELETTERD_SCENARIO_DEEL,
    AFGELETTERD_SCENARIO_ONT,
    AFGELETTERD_SCENARIO_VOLLEDIG,
    FACTUUR_AFGELETTERD_EVENT,
    bouw_factuur_afgeletterd_payload,
)
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import rlz_admin_id_voor

logger = logging.getLogger(__name__)


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _laatste_gemelde_stand(
    session, *, document_id: uuid.UUID
) -> tuple[int, Decimal | None]:
    """(hoogste volgnummer, laatst gemeld cumulatief betaald) uit de outbox-rijen van dit
    document. Oude v1.10-rijen zonder volgnummer tellen niet mee (zie module-docstring)."""
    rijen = session.scalars(
        select(WebhookUitgaand).where(
            WebhookUitgaand.document_id == document_id,
            WebhookUitgaand.event == FACTUUR_AFGELETTERD_EVENT,
        )
    ).all()
    hoogste = 0
    laatst_betaald: Decimal | None = None
    for rij in rijen:
        data = (rij.payload or {}).get("data") or {}
        volgnummer = data.get("volgnummer")
        if not isinstance(volgnummer, int):
            continue
        if volgnummer > hoogste:
            hoogste = volgnummer
            laatst_betaald = _als_decimal(data.get("betaald_bedrag"))
    return hoogste, laatst_betaald


def detecteer_en_meld_afgeletterd(*, administratie_id: uuid.UUID, client: RlzClient) -> int:
    """Draait in elke bank-sync. Alleen tier-administraties (vlag
    `afgeletterd_event_ingeschakeld` én `is_vastgoed` — de afleveraar assert die laatste ook);
    per kandidaat-document één GET op de RLZ-factuur. Eén kapot document stopt de rest niet
    (zichtbaar gelogd, volgende sync opnieuw). Retourneert het aantal nieuwe meldingen."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if (
            administratie is None
            or not administratie.is_vastgoed
            or not administratie.afgeletterd_event_ingeschakeld
        ):
            return 0
    rlz_admin_id = rlz_admin_id_voor(administratie_id)

    with scoped_session(administratie_id) as session:
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

        totaal = _als_decimal(factuur.get("BaseInvoiceAmount"))
        open_bedrag = _als_decimal(factuur.get("BaseRemainingAmount"))
        if totaal is None or open_bedrag is None:
            logger.warning(
                "Afgeletterd-detectie: RLZ-factuur %s zonder bruikbare bedragvelden "
                "(BaseInvoiceAmount/BaseRemainingAmount) — overgeslagen",
                rlz_document_id,
            )
            continue
        betaald = totaal - open_bedrag

        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            volgnummer, laatst_betaald = _laatste_gemelde_stand(session, document_id=document_id)
            if laatst_betaald is None:
                # Nog nooit (in v2.0-vorm) gemeld: alleen melden zodra er iets betaald is —
                # "betaald 0, open alles" is de beginstand, geen standwijziging.
                if betaald == 0:
                    continue
                scenario = (
                    AFGELETTERD_SCENARIO_VOLLEDIG if open_bedrag == 0 else AFGELETTERD_SCENARIO_DEEL
                )
            elif betaald == laatst_betaald:
                continue  # geen standwijziging
            elif betaald < laatst_betaald:
                scenario = AFGELETTERD_SCENARIO_ONT
            else:
                scenario = (
                    AFGELETTERD_SCENARIO_VOLLEDIG if open_bedrag == 0 else AFGELETTERD_SCENARIO_DEEL
                )

            nu = datetime.now(UTC)
            payload = bouw_factuur_afgeletterd_payload(
                administratie_id=administratie_id,
                rlz_admin_id=rlz_admin_id,
                rlz_document_id=rlz_document_id,
                rlz_boekstuknummer=boekstuknummer,
                referentie=referentie,
                volgnummer=volgnummer + 1,
                betaald_bedrag=betaald,
                open_bedrag=open_bedrag,
                scenario=scenario,
                afgeletterd_op=nu,
            )
            session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))
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
                    "volgnummer": volgnummer + 1,
                    "scenario": scenario,
                    "betaald_bedrag": str(betaald),
                    "open_bedrag": str(open_bedrag),
                },
                administratie_id=administratie_id,
            )
        gemeld += 1
    return gemeld
