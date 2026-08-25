"""Afletteren-tegen-open-post — GEKRAAKT via de betaal-kant (seam-swap 2026-08-09).

Feitelijke stand: de koppeling wordt gelegd met `POST PaymentTransactions/{tx}/Actions`
`{Type: 15, PaymentItemList: [{id}], LinkedAmount, IsCompletelyPaid, PaymentCorrectionMethod}`
— de UI-body die Peter op 2026-08-09 via DevTools ving en die de STAP-0-replay met Basic Auth
bevestigde (api-verkenning "Afletteren betaal-kant — REPLAY GESLAAGD"): 204, OpenAmount → 0
op mutatie én post, leesspoor naar de échte factuur; deelbetaling via een deel-LinkedAmount
(G-rekening-case) klopt exact aan beide kanten. ⚠️ Twee harde randfeiten: ná een deelkoppeling
krijgt het restant een NIEUW PaymentItem-id, en Type 16 ontkoppelt in géén enkele vorm —
terugdraaien blijft storno (actie 19) van het document, gevangen door de bank-reconciliatie.

DE SEAM: `voer_afletter_actie_uit` blijft het enige punt waar "wat er gebeurt bij afletteren"
besloten wordt — nu de echte API-koppeling mét directe verificatie (OpenAmount-hertoets +
PaymentReferenceList-leesspoor, zelfde leespatroon als het assist-model). Het assist-pad is de
EXPLICIETE FALLBACK bij een API-fout: de opdracht blijft dan zichtbaar "klaargezet" staan mét
de foutmelding (nooit stil), de mens kan alsnog in de RLZ-UI koppelen of het later opnieuw
proberen; `verifieer_openstaande_opdrachten` (elke sync) bevestigt die route zoals voorheen.

Voorstel-volgorde nu écht: stap 1 (exacte match) lettert AUTOMATISCH af tijdens de bank-sync,
maar uitsluitend achter de bestaande opt-in per administratie (`bank_autoboeken_ingeschakeld`)
en een eigen volumerem-teller (zelfde daglimiet als boekingen); zonder opt-in — en voor stap 2
(deelmatch) áltijd — is het een één-klik-uitvoering vanuit de module."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from app.bank.models import AfletterOpdrachtStatus, BankAfletterOpdracht, BankMutatie, PaymentItemCache
from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.rlz.client import RlzApiError, RlzClient

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


class IntercompanyPostUitgesloten(AfletterFout):
    """De doel-post is van een intercompany-tegenpartij (doorbelasting-mapping, blok 2):
    afhandeling loopt via de rekening-courant, aflettering is uitgesloten — óók handmatig."""


class OpdrachtNietGevonden(AfletterFout):
    pass


@dataclass(frozen=True)
class AfletterUitvoering:
    """Uitkomst van de seam. `afgeletterd_via_api` = koppeling gelegd én direct geverifieerd;
    `al_afgeletterd_in_rlz` = de vooraf-toets zag de mutatie al dicht in RLZ (kliktest
    2026-08-09) — geverifieerd zonder nieuwe koppeling, geen fout; `wacht_op_mens_in_rlz` =
    de assist-fallback (API-fout — zie `fout`, nooit stil): de opdracht blijft klaargezet,
    de mens koppelt in de RLZ-UI óf probeert het later opnieuw."""

    uitkomst: str  # "wacht_op_mens_in_rlz" | "afgeletterd_via_api" | "al_afgeletterd_in_rlz"
    opdracht_id: uuid.UUID
    fout: str | None = None


def bereken_linked_amount(open_mutatie: Decimal, post_bedrag: Decimal | None) -> Decimal:
    """LinkedAmount draagt het TEKEN van de mutatie (capture + replay: afschrijving negatief);
    de grootte is nooit meer dan wat er aan beide kanten open staat — een verzamelbetaling
    (|mutatie| > |post|) koppelt het postbedrag (deel van de mutatie blijft open), een
    G-rekening-deelbetaling (|mutatie| < |post|) koppelt het mutatiebedrag (post blijft deels
    open, het restant krijgt bij RLZ een nieuw PaymentItem-id)."""
    teken = Decimal(1) if open_mutatie > 0 else Decimal(-1)
    grootte = abs(open_mutatie)
    if post_bedrag is not None:
        grootte = min(grootte, abs(post_bedrag))
    return teken * grootte


def _open_eigen_client(administratie_id: uuid.UUID) -> RlzClient:
    from app.sync.service import _open_client_indien_nodig

    client, _ = _open_client_indien_nodig(administratie_id, None)
    return client


def zet_klaar_voor_afletteren(
    *,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    payment_item_id: uuid.UUID,
    actor_id: uuid.UUID,
    voorstel_detail: dict[str, Any] | None = None,
    client: RlzClient | None = None,
    deelbedrag: Decimal | None = None,
) -> AfletterUitvoering:
    """Publieke ingang voor de afletter-actie (router, autoflow, matchvoorstel-akkoord).
    Valideert deterministisch en delegeert de uitvoering aan de seam."""
    eigen_client = client is None
    if client is None:
        client = _open_eigen_client(administratie_id)
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
            if mutatie is None:
                raise MutatieNietGevonden(f"Onbekende bankmutatie: {payment_transaction_id}")
            if mutatie.open_bedrag is None or mutatie.open_bedrag == 0:
                raise MutatieNietOpen("Deze mutatie heeft geen open bedrag meer — er valt niets af te letteren")

            item = session.get(PaymentItemCache, (payment_item_id, administratie_id))
            if item is None or item.verdwenen_uit_bron_op is not None:
                raise OpenPostNietGevonden(f"Open post {payment_item_id} staat niet (meer) in de cache")
            # Fail-closed vangrail (blok 2 doorbelasting, verkenning/16 §2b): een
            # intercompany-post loopt via de rekening-courant en mag óók bij een handmatige
            # poging nooit afgeletterd worden — de matchcontext filtert 'm al uit elk
            # voorstel, dit vangt de rechtstreekse API-route.
            from app.bank.voorstellen import intercompany_entity_guids

            if item.entity_guid is not None and item.entity_guid in intercompany_entity_guids(
                session, administratie_id=administratie_id
            ):
                raise IntercompanyPostUitgesloten(
                    f"Open post {payment_item_id} is van een intercompany-tegenpartij "
                    f"({item.entity_naam or item.entity_guid}) — afhandeling loopt via de "
                    "rekening-courant, niet via aflettering"
                )

            bestaande = session.scalars(
                select(BankAfletterOpdracht).where(
                    BankAfletterOpdracht.administratie_id == administratie_id,
                    BankAfletterOpdracht.payment_transaction_id == payment_transaction_id,
                    BankAfletterOpdracht.status == AfletterOpdrachtStatus.KLAARGEZET.value,
                )
            ).first()
            if bestaande is not None:
                raise OpdrachtBestaatAl("Er staat al een klaargezette afletter-opdracht voor deze mutatie")

            if deelbedrag is not None:
                # Splitsen (deel 4 punt 4): expliciet deelbedrag i.p.v. min(open mutatie, post);
                # reist mee in voorstel_detail zodat ook 'nu afletteren' op een assist-opdracht
                # hetzelfde deel koppelt.
                voorstel_detail = {**(voorstel_detail or {}), "deelbedrag": str(deelbedrag)}
            return voer_afletter_actie_uit(
                session=session,
                administratie_id=administratie_id,
                payment_transaction_id=payment_transaction_id,
                payment_item_id=payment_item_id,
                rlz_document_id=item.rlz_document_id,
                actor_id=actor_id,
                voorstel_detail=voorstel_detail,
                client=client,
            )
    finally:
        if eigen_client:
            client.close()


def voer_afletter_actie_uit(
    *,
    session,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    payment_item_id: uuid.UUID,
    rlz_document_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    voorstel_detail: dict[str, Any] | None,
    client: RlzClient,
) -> AfletterUitvoering:
    """DE SEAM (zie moduledocstring): registreert de opdracht en legt de koppeling via de
    échte API (actie 15 op de PaymentTransaction, capture-replay 2026-08-09) mét directe
    verificatie. Faalt de API-call, dan blijft de opdracht als assist-fallback zichtbaar
    'klaargezet' staan mét de foutmelding — nooit stil."""
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
            "uitvoering": "api_koppeling",
        },
        administratie_id=administratie_id,
    )
    return _probeer_api_koppeling(
        session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id, client=client
    )


def _als_decimal(waarde: Any) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _probeer_api_koppeling(
    *,
    session,
    administratie_id: uuid.UUID,
    opdracht: BankAfletterOpdracht,
    actor_id: uuid.UUID,
    client: RlzClient,
) -> AfletterUitvoering:
    """De API-koppeling + directe verificatie voor één (bestaande, klaargezette) opdracht —
    gedeeld door de seam en de 'nu afletteren'-actie op oudere assist-opdrachten."""
    mutatie = session.get(BankMutatie, (opdracht.payment_transaction_id, administratie_id))
    item = (
        session.get(PaymentItemCache, (opdracht.payment_item_id, administratie_id))
        if opdracht.payment_item_id
        else None
    )
    if mutatie is None or mutatie.open_bedrag in (None, 0) or opdracht.payment_item_id is None:
        return _api_fout(
            session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
            fout="mutatie heeft lokaal geen open bedrag (meer) of de opdracht mist een doel-post",
        )

    # Vooraf-toets tegen de ACTUELE RLZ-staat (kliktest Peter 2026-08-09: "Nu afletteren" op een
    # mutatie die intussen al in RLZ was afgeletterd gaf een kale 404 _NotFound): de lokale cache
    # kan achterlopen op RLZ. Al dicht → "geverifieerd — al afgeletterd in RLZ", geen fout.
    try:
        vers_vooraf = client.get_payment_transaction(
            opdracht.payment_transaction_id, expand="PaymentReferenceList($expand=Document)"
        )
    except RlzApiError as exc:
        return _api_fout(
            session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
            fout=f"RLZ-staat opvragen mislukt: {exc}",
        )
    open_vooraf = _als_decimal(vers_vooraf.get("OpenAmount"))
    if open_vooraf == 0:
        return _markeer_al_afgeletterd(
            session=session, administratie_id=administratie_id, opdracht=opdracht,
            actor_id=actor_id, mutatie=mutatie, vers=vers_vooraf,
        )
    # Tweede deel van de vooraf-toets: bestaat de aangewezen post nog als open item in RLZ?
    # (Een gekoppeld item verdwijnt uit de open-items-collectie en het restant van een
    # deelkoppeling krijgt een NIEUW id — replay-STAP-0; de link-call zou anders kaal 404'en.)
    try:
        open_item_ids = {str(rij.get("id")) for rij in client.list_payment_items()}
    except RlzApiError as exc:
        return _api_fout(
            session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
            fout=f"open posten opvragen mislukt: {exc}",
        )
    if str(opdracht.payment_item_id) not in open_item_ids:
        return _api_fout(
            session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
            fout="de aangewezen open post bestaat niet (meer) als open item in RLZ — mogelijk "
            "elders (deels) betaald of na een deelkoppeling vervangen door een nieuw item-id; "
            "draai de bank-sync en zet het voorstel opnieuw klaar",
        )

    # De verse RLZ-stand is leidend voor het te koppelen bedrag (de lokale cache kan een
    # tussentijdse deelkoppeling gemist hebben).
    linked = bereken_linked_amount(open_vooraf if open_vooraf is not None else mutatie.open_bedrag,
                                   item.bedrag if item else None)
    deel = _als_decimal((opdracht.voorstel_detail or {}).get("deelbedrag"))
    if deel is not None:
        basis = open_vooraf if open_vooraf is not None else mutatie.open_bedrag
        if deel == 0 or (deel > 0) != (basis > 0) or abs(deel) > abs(basis):
            return _api_fout(
                session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
                fout=f"deelbedrag {deel} past niet op het open bedrag {basis} van de mutatie",
            )
        linked = deel
    try:
        client.link_payment_item(
            opdracht.payment_transaction_id,
            payment_item_id=opdracht.payment_item_id,
            linked_amount=float(linked),
        )
        vers = client.get_payment_transaction(
            opdracht.payment_transaction_id, expand="PaymentReferenceList($expand=Document)"
        )
    except RlzApiError as exc:
        # Race-vangnet: de vooraf-toets dekt de bekende 404-oorzaken (al afgeletterd,
        # verouderd item-id), maar tussen toets en call kan RLZ alsnog veranderen.
        return _api_fout(
            session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
            fout=f"RLZ-koppeling mislukt: {exc}",
        )

    open_na = _als_decimal(vers.get("OpenAmount"))
    koppelingen = _lees_koppelingen(vers)
    doel_gekoppeld = opdracht.rlz_document_id is not None and any(
        k["rlz_document_id"] == str(opdracht.rlz_document_id) for k in koppelingen
    )
    verwacht_open = (
        (open_vooraf - linked).quantize(Decimal("0.01")) if open_vooraf is not None else Decimal("0")
    )
    if not doel_gekoppeld and (open_na is None or open_na != verwacht_open):
        # 204-zonder-effect (bekend RLZ-gedrag bij een niet-passende body) — nooit stil.
        return _api_fout(
            session=session, administratie_id=administratie_id, opdracht=opdracht, actor_id=actor_id,
            fout="RLZ accepteerde de koppel-actie (204) maar de koppeling is niet zichtbaar — "
            "opdracht blijft klaargezet (assist-fallback)",
        )

    nu = datetime.now(UTC)
    opdracht.status = AfletterOpdrachtStatus.GEVERIFIEERD.value
    opdracht.laatste_verificatie_poging_op = nu
    opdracht.geverifieerd_op = nu
    opdracht.verificatie_detail = {
        "koppelingen": koppelingen,
        "voorstel_gevolgd": doel_gekoppeld,
        "uitvoering": "api",
        "linked_amount": str(linked),
        "open_restant": str(open_na) if open_na is not None else None,
    }
    mutatie.open_bedrag = open_na
    mutatie.laatst_gesynchroniseerd = nu
    if item is not None and open_na == 0 and abs(linked) == abs(item.bedrag or linked):
        # Volledige koppeling: de post is dicht — cache direct bijwerken (de sync bevestigt).
        item.verdwenen_uit_bron_op = nu
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="bank_afletter_opdracht",
        record_id=opdracht.id,
        actie="afgeletterd_via_api",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "payment_transaction_id": str(opdracht.payment_transaction_id),
            "payment_item_id": str(opdracht.payment_item_id),
            "linked_amount": str(linked),
            "open_restant": str(open_na) if open_na is not None else None,
            "koppelingen": koppelingen,
        },
        administratie_id=administratie_id,
    )
    return AfletterUitvoering(uitkomst="afgeletterd_via_api", opdracht_id=opdracht.id)


def _lees_koppelingen(vers: dict[str, Any]) -> list[dict[str, Any]]:
    """Het PaymentReferenceList-leesspoor ("waartegen wérkelijk afgeletterd"), hulzen
    uitgefilterd — gedeeld door de directe verificatie, de vooraf-toets en de sync-verificatie."""
    return [
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


def _markeer_al_afgeletterd(
    *,
    session,
    administratie_id: uuid.UUID,
    opdracht: BankAfletterOpdracht,
    actor_id: uuid.UUID,
    mutatie: BankMutatie,
    vers: dict[str, Any],
) -> AfletterUitvoering:
    """De vooraf-toets zag de mutatie al dicht in RLZ (kliktest Peter 2026-08-09): geen fout,
    geen nieuwe koppeling — de opdracht wordt "geverifieerd — al afgeletterd in RLZ" mét het
    leesspoor als bewijs en de tijdlijn-stempel (klaargezet → geverifieerd). Wijkt de werkelijke
    koppeling af van het voorstel, dan is dat zichtbaar via voorstel_gevolgd=false."""
    koppelingen = _lees_koppelingen(vers)
    voorstel_gevolgd = opdracht.rlz_document_id is not None and any(
        k["rlz_document_id"] == str(opdracht.rlz_document_id) for k in koppelingen
    )
    nu = datetime.now(UTC)
    opdracht.status = AfletterOpdrachtStatus.GEVERIFIEERD.value
    opdracht.laatste_verificatie_poging_op = nu
    opdracht.geverifieerd_op = nu
    opdracht.verificatie_detail = {
        "koppelingen": koppelingen,
        "voorstel_gevolgd": voorstel_gevolgd,
        "uitvoering": "al_afgeletterd_in_rlz",
    }
    mutatie.open_bedrag = Decimal(0)
    mutatie.laatst_gesynchroniseerd = nu
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="bank_afletter_opdracht",
        record_id=opdracht.id,
        actie="afletteren_geverifieerd",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "payment_transaction_id": str(opdracht.payment_transaction_id),
            "koppelingen": koppelingen,
            "voorstel_gevolgd": voorstel_gevolgd,
            "uitvoering": "al_afgeletterd_in_rlz",
        },
        administratie_id=administratie_id,
    )
    return AfletterUitvoering(uitkomst="al_afgeletterd_in_rlz", opdracht_id=opdracht.id)


def _api_fout(
    *, session, administratie_id: uuid.UUID, opdracht: BankAfletterOpdracht, actor_id: uuid.UUID, fout: str
) -> AfletterUitvoering:
    """Assist-fallback: opdracht blijft klaargezet, fout zichtbaar in audit + response."""
    logger.warning("Afletter-API-koppeling niet gelukt voor opdracht %s: %s", opdracht.id, fout)
    opdracht.laatste_verificatie_poging_op = datetime.now(UTC)
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="bank_afletter_opdracht",
        record_id=opdracht.id,
        actie="afletteren_api_fout",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"fout": fout[:500]},
        administratie_id=administratie_id,
    )
    return AfletterUitvoering(uitkomst="wacht_op_mens_in_rlz", opdracht_id=opdracht.id, fout=fout)


def voer_bestaande_opdracht_uit(
    *, administratie_id: uuid.UUID, opdracht_id: uuid.UUID, actor_id: uuid.UUID, client: RlzClient | None = None
) -> AfletterUitvoering:
    """'Nu afletteren' op een eerder (assist-tijdperk of na een API-fout) klaargezette
    opdracht: dezelfde API-koppeling + directe verificatie als de seam."""
    eigen_client = client is None
    if client is None:
        client = _open_eigen_client(administratie_id)
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            opdracht = session.get(BankAfletterOpdracht, opdracht_id)
            if opdracht is None or opdracht.administratie_id != administratie_id:
                raise OpdrachtNietGevonden(f"Onbekende afletter-opdracht: {opdracht_id}")
            if opdracht.status != AfletterOpdrachtStatus.KLAARGEZET.value:
                raise AfletterFout(f"Opdracht staat op {opdracht.status!r} — alleen klaargezette opdrachten")
            return _probeer_api_koppeling(
                session=session, administratie_id=administratie_id, opdracht=opdracht,
                actor_id=actor_id, client=client,
            )
    finally:
        if eigen_client:
            client.close()


def _api_afletteringen_vandaag(session, *, administratie_id: uuid.UUID) -> int:
    """Eigen volumerem-teller voor de automatische afletter-stap (zelfde daglimiet als
    boekingen; elke geldstroom-actie zijn eigen teller — zelfde afweging als de bank-boekingen)."""
    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(BankAfletterOpdracht)
            .where(
                BankAfletterOpdracht.administratie_id == administratie_id,
                BankAfletterOpdracht.klaargezet_door == SYSTEEM_ACTOR_ID,
                BankAfletterOpdracht.klaargezet_op >= vandaag_begin,
            )
        )
        or 0
    )


def verwerk_exacte_matches_automatisch(
    *, administratie_id: uuid.UUID, client: RlzClient
) -> tuple[int, list[str]]:
    """Voorstel-volgorde stap 1, nu écht automatisch (achter `bank_autoboeken_ingeschakeld`,
    gecontroleerd door de aanroeper in de sync): alle open mutaties met een EXACTE match
    (referentie + bedrag — groen) worden via de API afgeletterd, systeem-actor, mét de eigen
    volumerem. Stap 2 (deelmatch) blijft bewust één-klik-bevestigen — nooit automatisch.
    Fouten per mutatie worden verzameld, één kapotte mutatie stopt de rest niet."""
    from app.bank import voorstellen
    from app.bank.matchmotor import VoorstelSoort

    limiet = settings.max_boekingen_per_dag_per_administratie
    gedaan = 0
    fouten: list[str] = []
    for kandidaat in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id):
        if kandidaat.voorstel.soort != VoorstelSoort.EXACTE_MATCH:
            continue
        if kandidaat.voorstel.payment_item_id is None or kandidaat.afletter_opdracht is not None:
            continue
        with scoped_session(administratie_id) as session:
            if _api_afletteringen_vandaag(session, administratie_id=administratie_id) >= limiet:
                fouten.append(
                    f"volumerem: dagelijkse limiet van {limiet} automatische afletteringen bereikt"
                )
                break
        try:
            uitvoering = zet_klaar_voor_afletteren(
                administratie_id=administratie_id,
                payment_transaction_id=kandidaat.mutatie.id,
                payment_item_id=kandidaat.voorstel.payment_item_id,
                actor_id=SYSTEEM_ACTOR_ID,
                voorstel_detail={"soort": kandidaat.voorstel.soort.value, "bron": kandidaat.voorstel.bron},
                client=client,
            )
        except AfletterFout as exc:
            fouten.append(f"mutatie {kandidaat.mutatie.id}: {exc}")
            continue
        # "al afgeletterd in RLZ" (vooraf-toets) is óók een geslaagde uitkomst — de opdracht is
        # geverifieerd, alleen zonder nieuwe koppeling.
        if uitvoering.uitkomst in ("afgeletterd_via_api", "al_afgeletterd_in_rlz"):
            gedaan += 1
        else:
            fouten.append(f"mutatie {kandidaat.mutatie.id}: {uitvoering.fout or 'niet gelukt'}")
    return gedaan, fouten


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


def verifieer_openstaande_opdrachten(
    *, administratie_id: uuid.UUID, client: RlzClient, payment_account_id: uuid.UUID | None = None
) -> int:
    """Verificatiestap van het assist-model (draait in elke bank-sync; met `payment_account_id`
    ook on-demand per rekening — de "nu verifiëren"-knop): voor elke klaargezette opdracht de
    mutatie vers bij RLZ ophalen; OpenAmount == 0 → geverifieerd, mét het
    PaymentReferenceList-leesspoor ("waartegen wérkelijk afgeletterd", hulzen uitgefilterd) in
    verificatie_detail. Nog open → blijft klaargezet staan, mét een zichtbare
    laatste_verificatie_poging_op-stempel (UI-chip "wacht op verificatie", kliktest 2026-08-08).
    Systeem-actor: dit is achtergrondverwerking, niet de gebruiker die toevallig synct."""
    with scoped_session(administratie_id) as session:
        query = select(BankAfletterOpdracht.id).where(
            BankAfletterOpdracht.administratie_id == administratie_id,
            BankAfletterOpdracht.status == AfletterOpdrachtStatus.KLAARGEZET.value,
        )
        if payment_account_id is not None:
            query = query.join(
                BankMutatie,
                (BankMutatie.id == BankAfletterOpdracht.payment_transaction_id)
                & (BankMutatie.administratie_id == BankAfletterOpdracht.administratie_id),
            ).where(BankMutatie.payment_account_id == payment_account_id)
        opdracht_ids = list(session.scalars(query))

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
                # Mens is nog niet in RLZ geweest — volgende ronde opnieuw; wél de poging
                # zichtbaar stempelen (chip "wacht op verificatie — laatst gecontroleerd …").
                opdracht.laatste_verificatie_poging_op = datetime.now(UTC)
                continue

            koppelingen = _lees_koppelingen(vers)
            voorstel_gevolgd = (
                opdracht.rlz_document_id is not None
                and any(k["rlz_document_id"] == str(opdracht.rlz_document_id) for k in koppelingen)
            )
            nu = datetime.now(UTC)
            opdracht.status = AfletterOpdrachtStatus.GEVERIFIEERD.value
            opdracht.laatste_verificatie_poging_op = nu
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


def verifieer_voor_rekening(*, administratie_id: uuid.UUID, payment_account_id: uuid.UUID) -> int:
    """De "nu verifiëren"-knop (kliktest 2026-08-08): draait alléén de verificatieronde voor de
    klaargezette opdrachten van één rekening — geen volledige bank-sync, geen RLZ-writes (puur
    GET's + lokale statusovergang). Opent zelf een client, zelfde resolutie als de sync."""
    from app.sync.service import _open_client_indien_nodig

    client, eigen_client = _open_client_indien_nodig(administratie_id, None)
    try:
        return verifieer_openstaande_opdrachten(
            administratie_id=administratie_id, client=client, payment_account_id=payment_account_id
        )
    finally:
        if eigen_client:
            client.close()


@dataclass(frozen=True)
class AfletterOpdrachtOverzicht:
    """Eén opdracht mét de mutatie-context voor de UI-levenscyclus (chips + resultaat)."""

    opdracht: BankAfletterOpdracht
    boekdatum: Any
    tegenpartij_naam: str | None
    bedrag: Any


def afletter_opdrachten_voor_rekening(
    *, administratie_id: uuid.UUID, payment_account_id: uuid.UUID, limiet: int = 25
) -> list[AfletterOpdrachtOverzicht]:
    """Levenscyclus-lijst per rekening (kliktest 2026-08-08 "lijkt niets te doen"): ook
    geverifieerde en ingetrokken opdrachten blijven zichtbaar — een geverifieerde mutatie is
    niet meer "open" en verdween daardoor stil uit de mutatielijst. Recentste eerst."""
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(BankAfletterOpdracht, BankMutatie)
            .join(
                BankMutatie,
                (BankMutatie.id == BankAfletterOpdracht.payment_transaction_id)
                & (BankMutatie.administratie_id == BankAfletterOpdracht.administratie_id),
            )
            .where(
                BankAfletterOpdracht.administratie_id == administratie_id,
                BankMutatie.payment_account_id == payment_account_id,
            )
            .order_by(BankAfletterOpdracht.klaargezet_op.desc())
            .limit(limiet)
        ).all()
        resultaat = [
            AfletterOpdrachtOverzicht(
                opdracht=opdracht,
                boekdatum=mutatie.boekdatum,
                tegenpartij_naam=mutatie.tegenpartij_naam,
                bedrag=mutatie.bedrag,
            )
            for opdracht, mutatie in rijen
        ]
        session.expunge_all()
        return resultaat
