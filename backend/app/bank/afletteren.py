"""Afletteren-tegen-open-post — assist-model achter één uitvoerings-seam.

Feitelijke stand (fallback-PoC 2026-08-02, api-verkenning.md): de koppeling tussen een
bankmutatie en een bestaande open post kan via de publieke RLZ-API in GÉÉN enkele vorm gelegd
worden — acties 15/16 (Link/UnlinkPaymentItems), 34 (verrekenen) en 218 (betalen) zitten alle
achter een ongedocumenteerde-payload-muur of geven 500, en een memoriaal kan geen
crediteurenpost dragen. De supportvraag aan RLZ (verbreed) ligt klaar.

Daarom het assist-model (interim-ontwerplijn, ter review bij Peter):
1. de app zet het matchvoorstel klaar → mutatie gemarkeerd "af te letteren in Reeleezee";
2. de mens legt de koppeling in de RLZ-UI zelf (waar RLZ al pre-matcht);
3. de eerstvolgende sync VERIFIEERT op `OpenAmount == 0` en legt via het
   PaymentReferenceList-leesspoor vast waartegen er wérkelijk is afgeletterd — wijkt dat af van
   het voorstel, dan is dat zichtbaar in `verificatie_detail`, nooit stil.

DE SEAM: `voer_afletter_actie_uit` is het enige punt waar "wat er gebeurt bij afletteren"
besloten wordt. Vandaag markeert hij alleen (assist). Zodra RLZ het 15/16-antwoord levert kan
hier de echte API-write in — aanroepers (router, toekomstige autoflow) veranderen dan niet."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.bank.models import AfletterOpdrachtStatus, BankAfletterOpdracht, BankMutatie, PaymentItemCache
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.rlz.client import RlzClient

logger = logging.getLogger(__name__)


class AfletterFout(Exception):
    """Basis voor domeinfouten in de afletter-flow."""


class MutatieNietGevonden(AfletterFout):
    pass


class MutatieNietOpen(AfletterFout):
    """De mutatie heeft lokaal geen open bedrag (al afgeletterd of al direct geboekt)."""


class OpenPostNietGevonden(AfletterFout):
    """Het aangewezen betaal-item staat niet (meer) in de open-posten-cache."""


class OpdrachtBestaatAl(AfletterFout):
    """Er staat al een klaargezette afletter-opdracht voor deze mutatie."""


class OpdrachtNietGevonden(AfletterFout):
    pass


@dataclass(frozen=True)
class AfletterUitvoering:
    """Uitkomst van de seam: wat er met de afletter-actie is gebeurd. `wacht_op_mens_in_rlz`
    is de assist-uitkomst; een toekomstige API-write-implementatie retourneert
    `afgeletterd_via_api` en dan kan de aanroeper de verificatiestap overslaan."""

    uitkomst: str  # "wacht_op_mens_in_rlz" | "afgeletterd_via_api"
    opdracht_id: uuid.UUID


def zet_klaar_voor_afletteren(
    *,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    payment_item_id: uuid.UUID,
    actor_id: uuid.UUID,
    voorstel_detail: dict[str, Any] | None = None,
) -> AfletterUitvoering:
    """Publieke ingang voor de afletter-actie (router + matchvoorstel-akkoord). Valideert
    deterministisch en delegeert de uitvoering aan de seam."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
        if mutatie is None:
            raise MutatieNietGevonden(f"Onbekende bankmutatie: {payment_transaction_id}")
        if mutatie.open_bedrag is None or mutatie.open_bedrag == 0:
            raise MutatieNietOpen("Deze mutatie heeft geen open bedrag meer — er valt niets af te letteren")

        item = session.get(PaymentItemCache, (payment_item_id, administratie_id))
        if item is None or item.verdwenen_uit_bron_op is not None:
            raise OpenPostNietGevonden(f"Open post {payment_item_id} staat niet (meer) in de cache")

        bestaande = session.scalars(
            select(BankAfletterOpdracht).where(
                BankAfletterOpdracht.administratie_id == administratie_id,
                BankAfletterOpdracht.payment_transaction_id == payment_transaction_id,
                BankAfletterOpdracht.status == AfletterOpdrachtStatus.KLAARGEZET.value,
            )
        ).first()
        if bestaande is not None:
            raise OpdrachtBestaatAl("Er staat al een klaargezette afletter-opdracht voor deze mutatie")

        return voer_afletter_actie_uit(
            session=session,
            administratie_id=administratie_id,
            payment_transaction_id=payment_transaction_id,
            payment_item_id=payment_item_id,
            rlz_document_id=item.rlz_document_id,
            actor_id=actor_id,
            voorstel_detail=voorstel_detail,
        )


def voer_afletter_actie_uit(
    *,
    session,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    payment_item_id: uuid.UUID,
    rlz_document_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    voorstel_detail: dict[str, Any] | None,
) -> AfletterUitvoering:
    """DE SEAM (zie moduledocstring): vandaag assist-only — opdracht 'klaargezet' + audit; de
    mens lettert af in de RLZ-UI en verifieer_openstaande_opdrachten() bevestigt daarna. De
    toekomstige upgrade (RLZ beantwoordt de 15/16-supportvraag) vervangt uitsluitend deze
    functie-body door de API-write + directe verificatie."""
    opdracht = BankAfletterOpdracht(
        administratie_id=administratie_id,
        payment_transaction_id=payment_transaction_id,
        payment_item_id=payment_item_id,
        rlz_document_id=rlz_document_id,
        voorstel_detail=voorstel_detail,
        status=AfletterOpdrachtStatus.KLAARGEZET.value,
        klaargezet_door=actor_id,
    )
    session.add(opdracht)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="bank_afletter_opdracht",
        record_id=opdracht.id,
        actie="afletteren_klaargezet",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "payment_transaction_id": str(payment_transaction_id),
            "payment_item_id": str(payment_item_id),
            "rlz_document_id": str(rlz_document_id) if rlz_document_id else None,
            "uitvoering": "assist_in_rlz_ui",
        },
        administratie_id=administratie_id,
    )
    return AfletterUitvoering(uitkomst="wacht_op_mens_in_rlz", opdracht_id=opdracht.id)


def trek_afletter_opdracht_in(
    *, administratie_id: uuid.UUID, opdracht_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """Bewust annuleren van een klaargezette opdracht (bv. verkeerde post aangewezen) — status
    'ingetrokken' met actor en audit; nooit een DELETE."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        opdracht = session.get(BankAfletterOpdracht, opdracht_id)
        if opdracht is None or opdracht.administratie_id != administratie_id:
            raise OpdrachtNietGevonden(f"Onbekende afletter-opdracht: {opdracht_id}")
        if opdracht.status != AfletterOpdrachtStatus.KLAARGEZET.value:
            raise AfletterFout(f"Opdracht staat op {opdracht.status!r} en kan niet ingetrokken worden")
        opdracht.status = AfletterOpdrachtStatus.INGETROKKEN.value
        opdracht.ingetrokken_door = actor_id
        opdracht.ingetrokken_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_afletter_opdracht",
            record_id=opdracht.id,
            actie="afletteren_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": AfletterOpdrachtStatus.KLAARGEZET.value},
            nieuwe_waarde={"status": AfletterOpdrachtStatus.INGETROKKEN.value},
            administratie_id=administratie_id,
        )


def _is_systeemhuls(document: dict[str, Any] | None) -> bool:
    """Huls-onderscheid volgens de PoC-leesregels: een open mutatie heeft een PaymentReference
    naar een concept-BankMutationDirectBooking (DocumentType 19, Status 1) — en na een storno
    wordt het gestorneerde document zélf de huls. Daarom op DocumentType + Status toetsen,
    nooit op IsSystemGenerated alleen (fallback-PoC §5)."""
    if document is None:
        return True
    return document.get("DocumentType") == 19 and document.get("Status") == 1


def verifieer_openstaande_opdrachten(*, administratie_id: uuid.UUID, client: RlzClient) -> int:
    """Verificatiestap van het assist-model (draait in elke bank-sync): voor elke klaargezette
    opdracht de mutatie vers bij RLZ ophalen; OpenAmount == 0 → geverifieerd, mét het
    PaymentReferenceList-leesspoor ("waartegen wérkelijk afgeletterd", hulzen uitgefilterd) in
    verificatie_detail. Nog open → blijft gewoon klaargezet staan. Systeem-actor: dit is
    achtergrondverwerking, niet de gebruiker die toevallig synct."""
    with scoped_session(administratie_id) as session:
        opdracht_ids = list(
            session.scalars(
                select(BankAfletterOpdracht.id).where(
                    BankAfletterOpdracht.administratie_id == administratie_id,
                    BankAfletterOpdracht.status == AfletterOpdrachtStatus.KLAARGEZET.value,
                )
            )
        )

    geverifieerd = 0
    for opdracht_id in opdracht_ids:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            opdracht = session.get(BankAfletterOpdracht, opdracht_id)
            if opdracht is None or opdracht.status != AfletterOpdrachtStatus.KLAARGEZET.value:
                continue
            vers = client.get_payment_transaction(
                opdracht.payment_transaction_id, expand="PaymentReferenceList($expand=Document)"
            )
            open_amount = vers.get("OpenAmount")
            if open_amount is None or float(open_amount) != 0.0:
                continue  # mens is nog niet in RLZ geweest — volgende sync opnieuw

            koppelingen = [
                {
                    "rlz_document_id": (ref.get("Document") or {}).get("id"),
                    "boekstuknummer": (ref.get("Document") or {}).get("ReceiptNumber"),
                    "bedrag": ref.get("Amount"),
                    "volgorde": ref.get("Sequence"),
                    "bron": ref.get("PaymentReconciliationSource"),
                }
                for ref in vers.get("PaymentReferenceList") or []
                if not _is_systeemhuls(ref.get("Document"))
            ]
            voorstel_gevolgd = (
                opdracht.rlz_document_id is not None
                and any(k["rlz_document_id"] == str(opdracht.rlz_document_id) for k in koppelingen)
            )
            nu = datetime.now(UTC)
            opdracht.status = AfletterOpdrachtStatus.GEVERIFIEERD.value
            opdracht.geverifieerd_op = nu
            opdracht.verificatie_detail = {
                "koppelingen": koppelingen,
                "voorstel_gevolgd": voorstel_gevolgd,
            }
            mutatie = session.get(BankMutatie, (opdracht.payment_transaction_id, administratie_id))
            if mutatie is not None:
                mutatie.open_bedrag = 0
                mutatie.laatst_gesynchroniseerd = nu
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="bank_afletter_opdracht",
                record_id=opdracht.id,
                actie="afletteren_geverifieerd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "payment_transaction_id": str(opdracht.payment_transaction_id),
                    "koppelingen": koppelingen,
                    "voorstel_gevolgd": voorstel_gevolgd,
                },
                administratie_id=administratie_id,
            )
            geverifieerd += 1
            if not voorstel_gevolgd:
                logger.info(
                    "Afletter-opdracht %s geverifieerd maar de koppeling wijkt af van het voorstel "
                    "(zie verificatie_detail)",
                    opdracht.id,
                )
    return geverifieerd
