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
- idempotentie: deterministisch client-GUID (rlz_ids.rlz_bank_boeking_cyclus_id — cyclus =
  aantal eerdere storno's op de mutatie; STAP-0 25-08 §2.6: een her-PUT op een gestorneerd
  BMDB-document is 204 zónder effect, dus herboeken ná storno vereist een NIEUW GUID) + eigen
  duplicaatcheck vóór de PUT — lokaal (één GEBOEKTE boeking per mutatie) én tegen RLZ (verse
  OpenAmount-check; wijst de PaymentReferenceList al naar óns GUID, dan was een eerdere poging
  geslaagd en wordt alleen de lokale registratie ingehaald);
- verificatie ná de PUT op de verse OpenAmount van de mutatie (een 204 is bij RLZ geen bewijs
  van effect) — afwijking = zichtbare fout, nooit een lokale "geboekt" zonder RLZ-effect;
- DEELMODUS (splitsen, deel 4 punt 4): `deel=` boekt een DEEL van de mutatie (RLZ accepteert
  een deelbedrag, STAP-0 §2.2) op een eigen deel-GUID; de dekkingscheck toetst dan het deel,
  de één-per-mutatie-regel geldt niet en het open bedrag wordt op de verse RLZ-stand gezet;
- audit_event op boeken én storno; niets verdwijnt stil.

Volautomatisch (opt-in per administratie, `bank_autoboeken_ingeschakeld`, default UIT):
verwerk_automatisch() past vaste regels (stap 3) én — sinds blok B bundel 10-09 — groene historie-regel-
voorstellen (stap 3b, 100 % dezelfde rekening/btw) toe op open mutaties, uitsluitend waar de matchmotor dat
als voorstel geeft, dus nooit óver een open-post-match heen. Vóór élke automatische boeking loopt de
AI-plausibiliteitstoets als POORT (app/aitoets/plausibiliteit.py): plausibel → boeken; twijfel → NIET boeken,
uitkomst + reden op de mutatie (chip in de werkvoorraad) en als regel in `overgeslagen`. **Blok 4 (10-09 avond,
besluit Peter): overgeslagen (technische uitval: AVG-gate, API-key, kostengrens, AI-fout) → WÉL boeken**, mét
`ai_toets_uitkomst = overgeslagen` + reden op de mutatie (chip "zonder AI-toets"), audit
`automatisch_geboekt_zonder_ai_toets` en een regel in `zonder_ai_toets` (teller + LET-OP in de reconciliatie)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
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
from app.documenten.rlz_ids import rlz_bank_boeking_cyclus_id, rlz_bank_deel_boeking_id
from app.rlz.aangifte import AangiftePoort, blokkeer_bij_ingediende_aangifte
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
class DeelBoeking:
    """Deelmodus: dit deel van een gesplitste mutatie (bedrag mét het teken van de mutatie)."""

    deel_id: uuid.UUID
    bedrag: Decimal
    cyclus: int = 0


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
    deel_id: uuid.UUID | None = None,
    open_na: Decimal | None = None,
) -> uuid.UUID:
    boeking_id = uuid.uuid4()
    session.add(
        BankBoeking(
            id=boeking_id,
            administratie_id=administratie_id,
            payment_transaction_id=payment_transaction_id,
            deel_id=deel_id,
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
        mutatie.open_bedrag = open_na if open_na is not None else Decimal("0")
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
            "deel_id": str(deel_id) if deel_id else None,
            "open_restant": str(open_na) if open_na is not None else "0",
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
    deel: DeelBoeking | None = None,
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

        # Dekking: volledig = de regels dekken het mutatiebedrag; deelmodus = ze dekken het deel
        # (zelfde teken als de mutatie, nooit groter dan de mutatie).
        te_dekken = mutatie_bedrag if deel is None else deel.bedrag
        if deel is not None and (
            deel.bedrag == 0 or (deel.bedrag > 0) != (mutatie_bedrag > 0) or abs(deel.bedrag) > abs(mutatie_bedrag)
        ):
            raise RegelsDekkenMutatieNiet(
                f"Deelbedrag {deel.bedrag} past niet op de mutatie {mutatie_bedrag} (zelfde teken, niet groter)"
            )
        _controleer_regels(regels, mutatie_bedrag=te_dekken)

        if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
            raise BankBoekenUitgeschakeld(
                "Boeken staat uit voor deze administratie of via de globale kill switch"
            )
        limiet = settings.max_boekingen_per_dag_per_administratie
        if _bankboekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
            raise BankVolumeremBereikt(
                f"Dagelijkse limiet van {limiet} bankboekingen bereikt voor deze administratie"
            )

        if deel is None:
            bestaande = session.scalars(
                select(BankBoeking).where(
                    BankBoeking.administratie_id == administratie_id,
                    BankBoeking.payment_transaction_id == payment_transaction_id,
                    BankBoeking.deel_id.is_(None),
                    BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
                )
            ).first()
            if bestaande is not None:
                raise BankBoekingBestaatAl(bestaande.id)
            # Cyclus = aantal eerdere storno's op deze mutatie: elke herboeking een NIEUW GUID
            # (STAP-0 25-08 §2.6 — her-PUT op een gestorneerd BMDB is 204 zonder effect).
            cyclus = session.scalar(
                select(func.count())
                .select_from(BankBoeking)
                .where(
                    BankBoeking.administratie_id == administratie_id,
                    BankBoeking.payment_transaction_id == payment_transaction_id,
                    BankBoeking.deel_id.is_(None),
                    BankBoeking.status == BankBoekingStatus.GESTORNEERD.value,
                )
            ) or 0
            rlz_document_id = rlz_bank_boeking_cyclus_id(payment_transaction_id, cyclus)
        else:
            bestaande = session.scalars(
                select(BankBoeking).where(
                    BankBoeking.administratie_id == administratie_id,
                    BankBoeking.deel_id == deel.deel_id,
                    BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
                )
            ).first()
            if bestaande is not None:
                raise BankBoekingBestaatAl(bestaande.id)
            rlz_document_id = rlz_bank_deel_boeking_id(payment_transaction_id, deel.deel_id, deel.cyclus)

    # Eigen duplicaatcheck tegen RLZ (kernprincipe 5): verse staat van de mutatie ophalen. Is hij
    # daar al dicht, dan alleen doorgaan als ÓNS deterministische document de koppeling draagt
    # (eerdere poging geslaagd, lokale registratie inhalen) — anders is er in RLZ zelf verwerkt.
    vers = client.get_payment_transaction(
        payment_transaction_id, expand="PaymentReferenceList($expand=Document)"
    )
    open_amount = vers.get("OpenAmount")
    open_vooraf = Decimal(str(open_amount)).quantize(Decimal("0.01")) if open_amount is not None else None
    onze_koppeling = any(
        (ref.get("Document") or {}).get("id") == str(rlz_document_id)
        and (ref.get("Document") or {}).get("Status") != 1
        for ref in vers.get("PaymentReferenceList") or []
    )
    if onze_koppeling:
        # Eerdere poging geslaagd (retry ná een halve mislukking): alleen lokaal inhalen.
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
                deel_id=deel.deel_id if deel else None,
                open_na=open_vooraf,
            )
        return BankBoekResultaat(
            boeking_id=boeking_id,
            rlz_document_id=rlz_document_id,
            payment_transaction_id=payment_transaction_id,
            rlz_boekstuknummer=document.get("ReceiptNumber"),
            al_eerder_geboekt=True,
        )
    if open_vooraf is not None and open_vooraf == 0:
        raise MutatieAlAfgeletterd(
            "De mutatie is intussen in Reeleezee zelf afgeletterd — niet nogmaals boeken"
        )
    if deel is not None and open_vooraf is not None and abs(open_vooraf) < abs(deel.bedrag):
        raise MutatieAlAfgeletterd(
            f"Open bedrag in Reeleezee ({open_vooraf}) is kleiner dan dit deel ({deel.bedrag}) — "
            "de mutatie is intussen deels verwerkt; ververs en pas de verdeling aan"
        )

    try:
        client.put_bank_mutation_direct_booking(
            rlz_document_id,
            payment_transaction_id=payment_transaction_id,
            lines=_naar_rlz_lines(regels),
            description=omschrijving,
        )
        document = client.get_bank_mutation_direct_booking(rlz_document_id)
        na = client.get_payment_transaction(payment_transaction_id, expand="PaymentReferenceList($expand=Document)")
    except RlzApiError as exc:
        raise RlzBankBoekingMislukt(str(exc)) from exc

    # Verificatie ná de PUT: een 204 is bij RLZ geen bewijs (her-PUT op een gestorneerd document =
    # 204 zonder effect). Verwacht open ná = 0 (volledig) of open vóór − deel.
    open_na_raw = na.get("OpenAmount")
    open_na = Decimal(str(open_na_raw)).quantize(Decimal("0.01")) if open_na_raw is not None else None
    verwacht = Decimal("0") if deel is None else (
        (open_vooraf - deel.bedrag).quantize(Decimal("0.01")) if open_vooraf is not None else None
    )
    if document.get("Status") == 1 or (verwacht is not None and open_na != verwacht):
        raise RlzBankBoekingMislukt(
            "Reeleezee accepteerde de boeking (204) maar het effect is niet zichtbaar "
            f"(documentstatus {document.get('Status')}, open {open_vooraf} → {open_na}, verwacht {verwacht}) — "
            "niets lokaal geregistreerd; ververs de bankmutaties en probeer opnieuw"
        )

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
            deel_id=deel.deel_id if deel else None,
            open_na=open_na,
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

    # Aangifte-poort (besluit Peter 2026-08-15): valt de boekdatum van het geboekte document
    # in een INGEDIENDE btw-aangifte, dan blokkeert de storno — RLZ zou 'm accepteren maar de
    # btw stil naar de volgende open aangifte schuiven (suppletie-effect); handmatige
    # tegenboeking is dan de route. Fail-closed, vóór de correct-call.
    toets = AangiftePoort(client).toets_document(
        lambda: client.get_bank_mutation_direct_booking(rlz_document_id), kant="bankboeking"
    )
    blokkeer_bij_ingediende_aangifte([toets])

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


def historie_naar_boekregels(
    *, voorstel: matchmotor.Voorstel, mutatie: matchmotor.MutatieGegevens, btw_percentage: Decimal | None
) -> list[BankBoekRegelInput]:
    """Historie-regel-voorstel (stap 3b) → concrete boekingsregels: zelfde btw-splitsing in code als de vaste
    regel; omschrijving "Historie-regel: ‹tegenpartij›"."""
    if voorstel.ledger_id is None or mutatie.bedrag is None:
        return []
    netto, btw = matchmotor.splits_incl_bedrag(mutatie.bedrag, btw_percentage)
    return [
        BankBoekRegelInput(
            ledger_id=voorstel.ledger_id,
            netto_bedrag=netto,
            btw_bedrag=btw if btw != 0 else None,
            taxrate_id=voorstel.taxrate_id,
            omschrijving=f"Historie-regel: {mutatie.tegenpartij_naam or ''}".strip(),
        )
    ]


@dataclass
class AutomatischResultaat:
    """Uitkomst van één automatische verwerkingsronde: geboekt, fouten (boekpad), overgeslagen (AI-poort: alleen nog
    "twijfel: …" — de reconciliatie-tellers categoriseren op die tekst) en — blok 4 (10-09 avond) — `zonder_ai_toets`:
    boekingen die doorliepen terwijl de toets technisch uitviel ("zonder AI-toets: ‹oorzaak› — …"); die tellen mee in
    `geboekt`."""

    geboekt: int = 0
    fouten: list[str] = field(default_factory=list)
    overgeslagen: list[str] = field(default_factory=list)
    zonder_ai_toets: list[str] = field(default_factory=list)


def ai_toets_invoer_hash(invoer) -> str:
    """Idempotentie-sleutel van de toets: verandert alleen als het voorstel (soort, rekening, btw, bedrag) verandert.
    Een twijfel-mutatie wordt dus niet elke nacht opnieuw getoetst."""
    basis = "|".join(
        str(deel)
        for deel in (invoer.soort, invoer.rekening_code, invoer.rekening_naam, invoer.btw_omschrijving, invoer.bedrag)
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def bouw_ai_invoer(context, mutatie: matchmotor.MutatieGegevens, voorstel: matchmotor.Voorstel):
    """Deterministische invoer voor de AI-plausibiliteitstoets uit de matchcontext (labels uit de caches, samenvatting
    uit de historie of de vaste regel). Puur — geen I/O."""
    from app.aitoets.plausibiliteit import SOORT_BANK_HISTORIE, SOORT_BANK_VASTE_REGEL, PlausibiliteitInvoer
    from app.bank import historie_regel

    if voorstel.soort == matchmotor.VoorstelSoort.VASTE_REGEL and voorstel.regel_id is not None:
        regel = context.regel_per_id[voorstel.regel_id]
        ledger_id, taxrate_id, soort = regel.ledger_id, regel.taxrate_id, SOORT_BANK_VASTE_REGEL
        samenvatting = "vaste regel, door een mens bevestigd voor deze tegenpartij"
    else:
        ledger_id, taxrate_id, soort = voorstel.ledger_id, voorstel.taxrate_id, SOORT_BANK_HISTORIE
        samenvatting = historie_regel.historie_samenvatting(
            context.historie,
            historie_regel.historie_sleutel(mutatie.tegenrekening_iban, mutatie.omschrijving),
            rekening_label=context.rekening_label,
        )
    code_naam = context.ledger_label_per_id.get(ledger_id) if ledger_id is not None else None
    return PlausibiliteitInvoer(
        administratie_id=context.administratie_id,
        soort=soort,
        omschrijving=mutatie.omschrijving,
        tegenpartij=mutatie.tegenpartij_naam,
        bedrag=mutatie.bedrag,
        rekening_code=code_naam[0] if code_naam else None,
        rekening_naam=code_naam[1] if code_naam else (str(ledger_id)[:8] if ledger_id else None),
        btw_omschrijving=context.taxrate_naam_per_id.get(taxrate_id) if taxrate_id is not None else None,
        historie_samenvatting=samenvatting,
        referentie_id=mutatie.id,
    )


def _schrijf_ai_toets(*, administratie_id: uuid.UUID, mutatie_id: uuid.UUID, uitkomst, invoer_hash: str) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(BankMutatie, (mutatie_id, administratie_id))
        if rij is None:
            return
        rij.ai_toets_uitkomst = uitkomst.uitkomst
        rij.ai_toets_reden = uitkomst.reden
        rij.ai_toets_op = datetime.now(UTC)
        rij.ai_toets_invoer_hash = invoer_hash


def voer_ai_toets_uit(
    context, mutatie: matchmotor.MutatieGegevens, voorstel: matchmotor.Voorstel, *, hergebruik: bool = True
):
    """De AI-poort voor één kandidaat: bouwt de invoer, hergebruikt een eerdere twijfel-uitkomst bij een ongewijzigd
    voorstel (hash), toetst anders live en schrijft uitkomst + hash op de mutatie. Geeft (uitkomst, hergebruikt)."""
    from app.aitoets.plausibiliteit import UITKOMST_TWIJFEL, toets_plausibiliteit

    invoer = bouw_ai_invoer(context, mutatie, voorstel)
    invoer_hash = ai_toets_invoer_hash(invoer)
    stand = context.ai_toets_per_mutatie.get(mutatie.id)
    if hergebruik and stand is not None and stand.uitkomst == UITKOMST_TWIJFEL and stand.invoer_hash == invoer_hash:
        from app.aitoets.plausibiliteit import PlausibiliteitUitkomst

        return PlausibiliteitUitkomst(UITKOMST_TWIJFEL, stand.reden or "eerder getoetst"), True
    uitkomst = toets_plausibiliteit(invoer)
    _schrijf_ai_toets(
        administratie_id=context.administratie_id, mutatie_id=mutatie.id, uitkomst=uitkomst, invoer_hash=invoer_hash
    )
    return uitkomst, False


def verwerk_automatisch(*, administratie_id: uuid.UUID, client: RlzClient) -> AutomatischResultaat:
    """Volautomatische stap (opt-in `bank_autoboeken_ingeschakeld`, default UIT): boek open mutaties waarvoor de
    matchmotor een vaste regel (stap 3) of een GROENE historie-regel (stap 3b, 100 %) voorstelt, met de
    systeem-actor — ná de AI-plausibiliteitstoets als poort. De matchmotor-volgorde garandeert dat een
    open-post-match (afletteren) altijd vóór gaat — automatisch boeken kan een afletterkandidaat dus nooit
    wegkapen. Fouten per mutatie stoppen de rest niet en worden zichtbaar gerapporteerd; twijfel =
    zichtbaar overgeslagen mét reden op de mutatie; technische uitval van de toets (blok 4) = boeken mét markering
    "zonder AI-toets" (nooit stil)."""
    from app.aitoets.plausibiliteit import (
        SOORT_BANK_HISTORIE,
        SOORT_BANK_VASTE_REGEL,
        registreer_geboekt_zonder_ai_toets,
    )
    from app.bank.voorstellen import bepaal_voorstel_in_context, laad_matchcontext  # lokale import

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.bank_autoboeken_ingeschakeld:
            return AutomatischResultaat()

    context = laad_matchcontext(administratie_id=administratie_id)
    resultaat = AutomatischResultaat()
    for mutatie in context.open_mutaties:
        voorstel = bepaal_voorstel_in_context(context, mutatie)
        if mutatie.bedrag is None:
            continue
        if voorstel.soort == matchmotor.VoorstelSoort.VASTE_REGEL and voorstel.regel_id is not None:
            regel = context.regel_per_id[voorstel.regel_id]
            regels = regel_naar_boekregels(
                regel=regel,
                mutatie_bedrag=mutatie.bedrag,
                btw_percentage=context.btw_percentage_per_taxrate.get(regel.taxrate_id),
            )
            omschrijving = regel.omschrijving or f"Vaste regel: {mutatie.tegenpartij_naam or ''}".strip()
        elif voorstel.soort == matchmotor.VoorstelSoort.HISTORIE_REGEL and voorstel.kleur == "groen":
            regels = historie_naar_boekregels(
                voorstel=voorstel,
                mutatie=mutatie,
                btw_percentage=context.btw_percentage_per_taxrate.get(voorstel.taxrate_id),
            )
            omschrijving = f"Historie-regel: {mutatie.tegenpartij_naam or ''}".strip()
        else:
            continue
        if not regels:
            continue

        # AI-plausibiliteitstoets als POORT — twijfel = niet boeken, zichtbaar. Technische uitval (`overgeslagen`,
        # blok 4 10-09 avond) = WÉL boeken: de deterministische poorten waren al groen; de mutatie draagt
        # `ai_toets_uitkomst = overgeslagen` + reden (chip "zonder AI-toets"), hieronder volgt de audit-rij.
        uitkomst, hergebruikt = voer_ai_toets_uit(context, mutatie, voorstel)
        if not uitkomst.boeken_toegestaan:
            resultaat.overgeslagen.append(
                f"twijfel: {mutatie.id} ({voorstel.soort.value}) — {uitkomst.reden}"
                + (" [eerder getoetst, voorstel ongewijzigd]" if hergebruikt else "")
            )
            continue
        try:
            boek_mutatie_direct(
                administratie_id=administratie_id,
                payment_transaction_id=mutatie.id,
                regels=regels,
                actor_id=SYSTEEM_ACTOR_ID,
                omschrijving=omschrijving,
                bron=BankBoekingBron.AUTOMATISCH,
                client=client,
            )
            resultaat.geboekt += 1
            if uitkomst.zonder_ai_toets:
                resultaat.zonder_ai_toets.append(
                    f"zonder AI-toets: {uitkomst.oorzaak} — {mutatie.id} ({voorstel.soort.value}) — {uitkomst.reden}"
                )
                registreer_geboekt_zonder_ai_toets(
                    administratie_id=administratie_id,
                    soort=(
                        SOORT_BANK_VASTE_REGEL
                        if voorstel.soort == matchmotor.VoorstelSoort.VASTE_REGEL
                        else SOORT_BANK_HISTORIE
                    ),
                    referentie_id=mutatie.id,
                    uitkomst=uitkomst,
                    bron="bank_autoboeken",
                )
        except BankBoekenFout as exc:
            resultaat.fouten.append(f"{mutatie.id}: {exc}")
            logger.warning("Automatische bankboeking voor mutatie %s mislukt: %s", mutatie.id, exc)
    return resultaat


def verwerk_vaste_regels_automatisch(
    *, administratie_id: uuid.UUID, client: RlzClient
) -> tuple[int, list[str]]:
    """Compatibele vorm van `verwerk_automatisch` (geboekt, fouten) voor bestaande aanroepers/tests; de
    overgeslagen-lijst van de AI-poort zit alleen in `verwerk_automatisch`."""
    resultaat = verwerk_automatisch(administratie_id=administratie_id, client=client)
    return resultaat.geboekt, resultaat.fouten
