"""Direct-op-grootboek boeken van een bankmutatie (schrijf-PoC §3, volledig geverifieerd):
`PUT BankMutationDirectBookings/{client-guid}` met PaymentTransaction + regels boekt in één
klap (Status 3) én lettert de mutatie af (OpenAmount 0). Storno = actie 19 op dat document.

Failsafes en waarborgen (zelfde lat als het documenten-boeken):
- schrijf-poort: administratie.boeken_ingeschakeld + globale kill switch — beide aan, anders
  geen byte richting de klantboekhouding;
- volumerem: max. `settings.max_boekingen_per_dag_per_administratie` directe bankboekingen per
  administratie per dag (eigen teller op bank_boeking, los van de documentboekingen);
- geldlogica hard in code: de regels (netto + btw, mét het teken van de mutatie — PoC:
  NetAmount = Amount van de transactie) moeten samen EXACT het mutatiebedrag dekken;
- idempotentie: deterministisch client-GUID (rlz_ids.rlz_bank_boeking_id) + eigen
  duplicaatcheck vóór de PUT — lokaal (één GEBOEKTE boeking per mutatie) én tegen RLZ (verse
  OpenAmount-check; wijst de PaymentReferenceList al naar óns GUID, dan was een eerdere poging
  geslaagd en wordt alleen de lokale registratie ingehaald);
- audit_event op boeken én storno; niets verdwijnt stil.

Volautomatisch (opt-in per administratie, `bank_autoboeken_ingeschakeld`, default UIT):
verwerk_vaste_regels_automatisch() past vaste regels toe op open mutaties — uitsluitend waar
de matchmotor stap 3 (vaste regel) als voorstel geeft, dus nooit óver een open-post-match heen."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bank import matchmotor
from app.bank.models import (
    BankBoeking,
    BankBoekingBron,
    BankBoekingRegel,
    BankBoekingStatus,
    BankMutatie,
    BankRegel,
)
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, BoekenInstelling
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.rlz_ids import rlz_bank_boeking_id
from app.rlz.client import RlzApiError, RlzClient

logger = logging.getLogger(__name__)


class BankBoekenFout(Exception):
    """Basis voor domeinfouten bij het direct boeken van bankmutaties."""


class BankMutatieNietGevonden(BankBoekenFout):
    pass


class BankBoekenUitgeschakeld(BankBoekenFout):
    """Schrijf-failsafe: boeken staat uit voor deze administratie of via de kill switch."""


class BankVolumeremBereikt(BankBoekenFout):
    pass


class RegelsDekkenMutatieNiet(BankBoekenFout):
    """De som van de regelbedragen (netto + btw) wijkt af van het mutatiebedrag."""


class BankBoekingBestaatAl(BankBoekenFout):
    def __init__(self, boeking_id: uuid.UUID) -> None:
        self.boeking_id = boeking_id
        super().__init__("Deze mutatie heeft al een geboekte directe boeking")


class MutatieAlAfgeletterd(BankBoekenFout):
    """RLZ meldt OpenAmount 0 zonder dat óns document de koppeling draagt — iemand heeft de
    mutatie intussen in RLZ zelf verwerkt. Nooit overheen boeken."""


class RlzBankBoekingMislukt(BankBoekenFout):
    pass


class BankBoekingNietGevonden(BankBoekenFout):
    pass


@dataclass(frozen=True)
class BankBoekRegelInput:
    ledger_id: uuid.UUID
    netto_bedrag: Decimal
    btw_bedrag: Decimal | None = None
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    omschrijving: str | None = None


@dataclass(frozen=True)
class BankBoekResultaat:
    boeking_id: uuid.UUID  # lokale registratie-rij
    rlz_document_id: uuid.UUID  # deterministisch RLZ-client-GUID
    payment_transaction_id: uuid.UUID
    rlz_boekstuknummer: str | None
    al_eerder_geboekt: bool = False


def _is_boeken_toegestaan(session: Session, *, administratie_id: uuid.UUID) -> bool:
    """Zelfde poort als documenten-boeken (bewust gedupliceerd i.p.v. de private helper daar te
    importeren): toggle per administratie ÉN globale kill switch."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.boeken_ingeschakeld:
        return False
    instelling = session.get(BoekenInstelling, True)
    return instelling is not None and instelling.globaal_ingeschakeld


def _bankboekingen_vandaag(session: Session, *, administratie_id: uuid.UUID) -> int:
    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(BankBoeking)
            .where(
                BankBoeking.administratie_id == administratie_id,
                BankBoeking.geboekt_op >= vandaag_begin,
            )
        )
        or 0
    )


def _controleer_regels(regels: list[BankBoekRegelInput], *, mutatie_bedrag: Decimal) -> None:
    if not regels:
        raise RegelsDekkenMutatieNiet("Minstens één boekingsregel is verplicht")
    som = sum((regel.netto_bedrag + (regel.btw_bedrag or Decimal("0")) for regel in regels), Decimal("0"))
    if som != mutatie_bedrag:
        raise RegelsDekkenMutatieNiet(
            f"Regels (netto + btw) tellen op tot {som}, maar de mutatie is {mutatie_bedrag} — "
            "de boeking moet het mutatiebedrag exact dekken (regelbedragen dragen het teken van de mutatie)"
        )


def _naar_rlz_lines(regels: list[BankBoekRegelInput]) -> list[dict]:
    lines: list[dict] = []
    for regel in regels:
        line: dict = {"Account": {"id": str(regel.ledger_id)}, "NetAmount": float(regel.netto_bedrag)}
        if regel.btw_bedrag is not None and regel.btw_bedrag != 0:
            line["TaxAmount"] = float(regel.btw_bedrag)
        if regel.taxrate_id is not None:
            line["TaxRate"] = {"id": str(regel.taxrate_id)}
        if regel.project_id is not None:
            line["Project"] = {"id": str(regel.project_id)}
        if regel.omschrijving:
            line["Description"] = regel.omschrijving
        lines.append(line)
    return lines


def _registreer_boeking(
    session: Session,
    *,
    rlz_document_id: uuid.UUID,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    regels: list[BankBoekRegelInput],
    omschrijving: str | None,
    rlz_boekstuknummer: str | None,
    bron: BankBoekingBron,
    actor_id: uuid.UUID,
    detail_actie: str,
) -> uuid.UUID:
    boeking_id = uuid.uuid4()
    session.add(
        BankBoeking(
            id=boeking_id,
            administratie_id=administratie_id,
            payment_transaction_id=payment_transaction_id,
            rlz_document_id=rlz_document_id,
            omschrijving=omschrijving,
            rlz_boekstuknummer=rlz_boekstuknummer,
            bron=bron.value,
            status=BankBoekingStatus.GEBOEKT.value,
            geboekt_door=actor_id,
        )
    )
    for volgnummer, regel in enumerate(regels, start=1):
        session.add(
            BankBoekingRegel(
                bank_boeking_id=boeking_id,
                volgnummer=volgnummer,
                ledger_id=regel.ledger_id,
                taxrate_id=regel.taxrate_id,
                project_id=regel.project_id,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving=regel.omschrijving,
            )
        )
    mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
    if mutatie is not None:
        mutatie.open_bedrag = Decimal("0")
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="bank_boeking",
        record_id=boeking_id,
        actie=detail_actie,
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "payment_transaction_id": str(payment_transaction_id),
            "rlz_document_id": str(rlz_document_id),
            "rlz_boekstuknummer": rlz_boekstuknummer,
            "bron": bron.value,
            "regels": [
                {
                    "ledger_id": str(regel.ledger_id),
                    "netto_bedrag": str(regel.netto_bedrag),
                    "btw_bedrag": str(regel.btw_bedrag) if regel.btw_bedrag is not None else None,
                }
                for regel in regels
            ],
        },
        administratie_id=administratie_id,
    )
    return boeking_id


def boek_mutatie_direct(
    *,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    regels: list[BankBoekRegelInput],
    actor_id: uuid.UUID,
    omschrijving: str | None = None,
    bron: BankBoekingBron = BankBoekingBron.HANDMATIG,
    client: RlzClient,
) -> BankBoekResultaat:
    """De volledige direct-op-grootboek-flow: checks → failsafes → duplicaatchecks → PUT →
    lokale registratie + audit. Idempotent: een retry raakt hetzelfde RLZ-document."""
    with scoped_session(administratie_id) as session:
        mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
        if mutatie is None:
            raise BankMutatieNietGevonden(f"Onbekende bankmutatie: {payment_transaction_id}")
        if mutatie.bedrag is None:
            raise BankBoekenFout("Mutatie zonder bedrag kan niet geboekt worden")
        mutatie_bedrag = mutatie.bedrag

        _controleer_regels(regels, mutatie_bedrag=mutatie_bedrag)

        if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
            raise BankBoekenUitgeschakeld(
                "Boeken staat uit voor deze administratie of via de globale kill switch"
            )
        limiet = settings.max_boekingen_per_dag_per_administratie
        if _bankboekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
            raise BankVolumeremBereikt(
                f"Dagelijkse limiet van {limiet} bankboekingen bereikt voor deze administratie"
            )

        bestaande = session.scalars(
            select(BankBoeking).where(
                BankBoeking.administratie_id == administratie_id,
                BankBoeking.payment_transaction_id == payment_transaction_id,
                BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
            )
        ).first()
        if bestaande is not None:
            raise BankBoekingBestaatAl(bestaande.id)

    rlz_document_id = rlz_bank_boeking_id(payment_transaction_id)

    # Eigen duplicaatcheck tegen RLZ (kernprincipe 5): verse staat van de mutatie ophalen. Is hij
    # daar al dicht, dan alleen doorgaan als ÓNS deterministische document de koppeling draagt
    # (eerdere poging geslaagd, lokale registratie inhalen) — anders is er in RLZ zelf verwerkt.
    vers = client.get_payment_transaction(
        payment_transaction_id, expand="PaymentReferenceList($expand=Document)"
    )
    open_amount = vers.get("OpenAmount")
    if open_amount is not None and float(open_amount) == 0.0:
        onze_koppeling = any(
            (ref.get("Document") or {}).get("id") == str(rlz_document_id)
            and (ref.get("Document") or {}).get("Status") != 1
            for ref in vers.get("PaymentReferenceList") or []
        )
        if not onze_koppeling:
            raise MutatieAlAfgeletterd(
                "De mutatie is intussen in Reeleezee zelf afgeletterd — niet nogmaals boeken"
            )
        document = client.get_bank_mutation_direct_booking(rlz_document_id)
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            boeking_id = _registreer_boeking(
                session,
                rlz_document_id=rlz_document_id,
                administratie_id=administratie_id,
                payment_transaction_id=payment_transaction_id,
                regels=regels,
                omschrijving=omschrijving,
                rlz_boekstuknummer=document.get("ReceiptNumber"),
                bron=bron,
                actor_id=actor_id,
                detail_actie="bank_mutatie_direct_geboekt_ingehaald",
            )
        return BankBoekResultaat(
            boeking_id=boeking_id,
            rlz_document_id=rlz_document_id,
            payment_transaction_id=payment_transaction_id,
            rlz_boekstuknummer=document.get("ReceiptNumber"),
            al_eerder_geboekt=True,
        )

    try:
        client.put_bank_mutation_direct_booking(
            rlz_document_id,
            payment_transaction_id=payment_transaction_id,
            lines=_naar_rlz_lines(regels),
            description=omschrijving,
        )
        document = client.get_bank_mutation_direct_booking(rlz_document_id)
    except RlzApiError as exc:
        raise RlzBankBoekingMislukt(str(exc)) from exc

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking_id = _registreer_boeking(
            session,
            rlz_document_id=rlz_document_id,
            administratie_id=administratie_id,
            payment_transaction_id=payment_transaction_id,
            regels=regels,
            omschrijving=omschrijving,
            rlz_boekstuknummer=document.get("ReceiptNumber"),
            bron=bron,
            actor_id=actor_id,
            detail_actie="bank_mutatie_direct_geboekt",
        )

    return BankBoekResultaat(
        boeking_id=boeking_id,
        rlz_document_id=rlz_document_id,
        payment_transaction_id=payment_transaction_id,
        rlz_boekstuknummer=document.get("ReceiptNumber"),
    )


def storno_bank_boeking(
    *,
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    client: RlzClient,
) -> None:
    """Storno via actie 19 (nooit verwijderen — kernprincipe 3): document terug naar concept,
    mutatie weer open. Reden verplicht ("niets verdwijnt stil"). Het verse open bedrag komt uit
    RLZ zelf (⚠️ IsComplete is daarna stale — daarom alleen OpenAmount)."""
    reden = reden.strip()
    if not reden:
        raise BankBoekenFout("Een storno vereist een reden")

    with scoped_session(administratie_id) as session:
        boeking = session.get(BankBoeking, boeking_id)
        if boeking is None or boeking.administratie_id != administratie_id:
            raise BankBoekingNietGevonden(f"Onbekende bankboeking: {boeking_id}")
        if boeking.status != BankBoekingStatus.GEBOEKT.value:
            raise BankBoekenFout(f"Boeking staat op {boeking.status!r} en kan niet gestorneerd worden")
        payment_transaction_id = boeking.payment_transaction_id
        rlz_document_id = boeking.rlz_document_id

    try:
        client.correct_bank_mutation_direct_booking(rlz_document_id)
        vers = client.get_payment_transaction(payment_transaction_id)
    except RlzApiError as exc:
        raise RlzBankBoekingMislukt(str(exc)) from exc

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(BankBoeking, boeking_id)
        assert boeking is not None
        boeking.status = BankBoekingStatus.GESTORNEERD.value
        boeking.gestorneerd_door = actor_id
        boeking.gestorneerd_op = datetime.now(UTC)
        boeking.storno_reden = reden
        mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
        if mutatie is not None and vers.get("OpenAmount") is not None:
            mutatie.open_bedrag = Decimal(str(vers["OpenAmount"]))
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_boeking",
            record_id=boeking_id,
            actie="bank_boeking_gestorneerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": BankBoekingStatus.GEBOEKT.value},
            nieuwe_waarde={"status": BankBoekingStatus.GESTORNEERD.value, "reden": reden},
            administratie_id=administratie_id,
        )


# --- volautomatische verwerking (opt-in per administratie) --------------------------------------


def regel_naar_boekregels(
    *, regel: BankRegel, mutatie_bedrag: Decimal, btw_percentage: Decimal | None
) -> list[BankBoekRegelInput]:
    """Vaste regel → concrete boekingsregels: btw-splitsing in code (splits_incl_bedrag — de som
    is per constructie exact het mutatiebedrag)."""
    netto, btw = matchmotor.splits_incl_bedrag(mutatie_bedrag, btw_percentage)
    return [
        BankBoekRegelInput(
            ledger_id=regel.ledger_id,
            netto_bedrag=netto,
            btw_bedrag=btw if btw != 0 else None,
            taxrate_id=regel.taxrate_id,
            project_id=regel.project_id,
            omschrijving=regel.omschrijving,
        )
    ]


def verwerk_vaste_regels_automatisch(
    *, administratie_id: uuid.UUID, client: RlzClient
) -> tuple[int, list[str]]:
    """Volautomatische stap (opt-in `bank_autoboeken_ingeschakeld`, default UIT): boek open
    mutaties waarvoor de matchmotor een vaste regel voorstelt, met de systeem-actor. De
    matchmotor-volgorde garandeert dat een open-post-match (afletteren, mensenwerk) altijd
    vóór een vaste regel gaat — automatisch boeken kan een afletterkandidaat dus nooit
    wegkapen. Fouten per mutatie stoppen de rest niet en worden zichtbaar gerapporteerd."""
    from app.bank.voorstellen import laad_matchcontext  # lokale import: voorstellen leest sync-stand

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.bank_autoboeken_ingeschakeld:
            return 0, []

    context = laad_matchcontext(administratie_id=administratie_id)
    geboekt = 0
    fouten: list[str] = []
    for mutatie in context.open_mutaties:
        voorstel = matchmotor.bepaal_voorstel(
            mutatie, open_posten=context.open_posten, vaste_regels=context.vaste_regels
        )
        if voorstel.soort != matchmotor.VoorstelSoort.VASTE_REGEL or voorstel.regel_id is None:
            continue
        regel = context.regel_per_id[voorstel.regel_id]
        if mutatie.bedrag is None:
            continue
        regels = regel_naar_boekregels(
            regel=regel,
            mutatie_bedrag=mutatie.bedrag,
            btw_percentage=context.btw_percentage_per_taxrate.get(regel.taxrate_id),
        )
        try:
            boek_mutatie_direct(
                administratie_id=administratie_id,
                payment_transaction_id=mutatie.id,
                regels=regels,
                actor_id=SYSTEEM_ACTOR_ID,
                omschrijving=regel.omschrijving or f"Vaste regel: {mutatie.tegenpartij_naam or ''}".strip(),
                bron=BankBoekingBron.AUTOMATISCH,
                client=client,
            )
            geboekt += 1
        except BankBoekenFout as exc:
            fouten.append(f"{mutatie.id}: {exc}")
            logger.warning("Automatische bankboeking voor mutatie %s mislukt: %s", mutatie.id, exc)
    return geboekt, fouten
