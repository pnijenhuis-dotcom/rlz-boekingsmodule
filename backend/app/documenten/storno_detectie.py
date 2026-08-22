"""Detectie van RLZ-UI-storno's op geboekte inkoopfacturen → `factuur_gestorneerd`-event
(koppelcontract §3 v1.14, kostenflow-randvraag c — harde eis vóór vastgoeds auto-bevestiging S2).

Een geboekte inkoopfactuur heeft in deze module géén storno-knop (GEBOEKT is lokaal terminaal,
statusmachine): een storno gebeurt dáár uitsluitend via actie 19 in de RLZ-UI. Dit is dus de
detectie-bron met LATENTIE — het event ontstaat pas bij de eerstvolgende run (nu de dagelijkse
reconciliatie-cadans via `make reconciliatie`; frequenter zodra de GCP-schedulers draaien).
Die latentie staat expliciet in het contract; de module-storno's (doorbelasting-spiegel) vuren
wél direct bij de actie (app/doorbelasting/boeken.py::_meld_spiegel_gestorneerd).

Idempotentie = de boekstand-reeks zelf (app/documenten/boekstand.py, zelfde anker als het
afgeletterd-event): een event ontstaat alleen als de laatste gemelde stand een
factuur_geboekt is — een tweede detectie-run over dezelfde storno ziet als laatste stand het
eigen gestorneerd-event en doet niets. Geen geboekt-event (niet-vastgoed, of geboekt vóór de
webhook bestond én nooit gemeld) = geen storno-event: vastgoed kreeg dan ook nooit een
geboekt-melding om te corrigeren.

Zelfde patroon als app/bank/vastly.py (afgeletterd-detectie): alleen vastgoed-administraties,
één GET per kandidaat-document, één kapot document stopt de rest niet.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.boekstand import laatste_boekstand_rij, stand_van_rij
from app.documenten.models import Boekvoorstel, Document, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.webhook import (
    FACTUUR_GEBOEKT_EVENT,
    GESTORNEERD_BRON_RLZ_UI,
    bouw_factuur_gestorneerd_payload,
)
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

# RLZ's DocumentStatuses (geverifieerd 2026-07-13): 1 = Tentative/Concept — de staat waarin
# actie 19 een document terugzet. 2/3 = geboekt (open/gesloten), geen storno.
_RLZ_CONCEPT_STATUS = 1


def detecteer_en_meld_gestorneerd(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> int:
    """Eén detectie-run voor één administratie; retourneert het aantal nieuwe events."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.is_vastgoed:
            return 0
    rlz_admin_id = rlz_admin_id_voor(administratie_id)

    with scoped_session(administratie_id) as session:
        # boek_cyclus bepaalt het actuele RLZ-GUID (tegenboek-pad): na "tegenboeken én opnieuw
        # boeken" leeft de actieve boeking op het herboeking-GUID, niet op het origineel.
        kandidaten = [
            (document_id, boek_cyclus or 0)
            for document_id, boek_cyclus in session.execute(
                select(Document.id, Boekvoorstel.boek_cyclus)
                .join(Boekvoorstel, Boekvoorstel.document_id == Document.id, isouter=True)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.soort == "inkoopfactuur",
                    Document.status == DocumentStatus.GEBOEKT,
                )
            )
        ]
    if not kandidaten:
        return 0

    eigen_client = client is None
    if client is None:
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    gemeld = 0
    try:
        for document_id, boek_cyclus in kandidaten:
            rlz_document_id = rlz_herboeking_id(document_id, boek_cyclus)
            with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                rij = laatste_boekstand_rij(
                    session, document_id=document_id, rlz_document_id=rlz_document_id
                )
                if rij is None or rij.event != FACTUUR_GEBOEKT_EVENT:
                    continue  # nooit gemeld, of de storno is al gemeld — niets te doen
            try:
                factuur = client.get(f"PurchaseInvoices/{rlz_document_id}")
            except RlzApiError as exc:
                # Ook een 404 is hier géén storno-bewijs (actie 19 laat het document als
                # concept bestaan) — de documenten-reconciliatie rapporteert 404's al apart.
                logger.warning(
                    "Storno-detectie: RLZ-factuur %s (document %s) niet leesbaar: %s",
                    rlz_document_id,
                    document_id,
                    exc,
                )
                continue
            if factuur.get("Status") != _RLZ_CONCEPT_STATUS:
                continue

            with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                # Herlees binnen de schrijftransactie: twee gelijktijdige runs maken anders
                # allebei een event (zelfde herleeslogica als de afgeletterd-detectie).
                rij = laatste_boekstand_rij(
                    session, document_id=document_id, rlz_document_id=rlz_document_id
                )
                if rij is None or rij.event != FACTUUR_GEBOEKT_EVENT:
                    continue
                data = (rij.payload or {}).get("data") or {}
                volgnummer = stand_van_rij(rij) + 1
                payload = bouw_factuur_gestorneerd_payload(
                    administratie_id=administratie_id,
                    rlz_admin_id=rlz_admin_id,
                    rlz_document_id=rlz_document_id,
                    rlz_boekstuknummer=data.get("rlz_boekstuknummer"),
                    referentie=data.get("referentie"),
                    volgnummer=volgnummer,
                    bron=GESTORNEERD_BRON_RLZ_UI,
                    reden=None,
                    gestorneerd_op=datetime.now(UTC),
                )
                session.add(
                    WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload)
                )
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="document",
                    record_id=document_id,
                    actie="factuur_gestorneerd_gedetecteerd",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "rlz_document_id": str(rlz_document_id),
                        "event": payload["event"],
                        "volgnummer": volgnummer,
                        "bron": GESTORNEERD_BRON_RLZ_UI,
                    },
                    administratie_id=administratie_id,
                )
            gemeld += 1
    finally:
        if eigen_client:
            client.close()
    return gemeld


def detecteer_en_meld_gestorneerd_alle() -> dict[uuid.UUID, int | str]:
    """Alle administraties; één zonder werkende credentials stopt de rest niet (zelfde patroon
    als reconcilieer_alle_administraties). Draait ná de documenten-reconciliatie in het
    CLI-commando `reconciliatie` — dezelfde cadans is dus ook de contract-latentie."""
    with scoped_session(None) as session:
        administratie_ids = [
            row.id for row in session.scalars(select(Administratie).where(Administratie.is_vastgoed))
        ]
    resultaten: dict[uuid.UUID, int | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = detecteer_en_meld_gestorneerd(administratie_id=administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie reconcilieer_alle_administraties
            resultaten[administratie_id] = str(exc)
    return resultaten
