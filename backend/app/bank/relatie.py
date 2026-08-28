"""Bankmutatie koppelen aan een RELATIE zonder factuur — het aanbetalingsdocument (besluit Peter
25-08, feedbackronde deel 4 punt 3; STAP-0 api-verkenning "Bankmutatie op een RELATIE + mutatie
SPLITSEN" is canoniek voor de RLZ-feiten).

RLZ kent géén "boek op relatie zonder document" (Entity op BankMutationDirectBooking/ManualJournal/
OpenBalance = 500 of stil genegeerd). De bewezen vorm:

  1. AANBETALINGSDOCUMENT: crediteur → `PUT PurchaseInvoices/{guid}` op de Entity met ÉÉN regel op
     systeemrekening 1403 "Vooruit betaalde inkoopfacturen" en het 0%-"Nul tarief" (⚠️ zonder
     expliciet TaxRate rekent RLZ het crediteur-default 21% — probe I); debiteur = spiegelbeeld
     `PUT SalesInvoices` met een regel op 1806 "Vooruitbetaalde verkoopfacturen" (niet live bewezen:
     de API kan geen positieve test-mutatie aanmaken — eerste echte casus verifiëren, storno klaar).
     Actie 17 → open PaymentItem op de relatie. Journaal: D 1403 / C 1600 (crediteur).
  2. AFLETTEREN: de bewezen actie 15 op de PaymentTransaction (`RlzClient.link_payment_item`) —
     mutatie OpenAmount → 0, aanbetalingsdocument Status 3.
  3. VERREKENING met de latere factuur = tegenregel −bedrag op dezelfde vooruitbetalingsrekening
     ín die factuur (STAP-0 H3; actie 34 blijft dood) — het controlescherm biedt die regel aan bij
     het aanbetaling-open-signaal; `markeer_verrekend_bij_boeking` sluit de aanbetaling ín de
     boek-transactie van de factuur.
  4. STORNO = actie 19 op het aanbetalingsdocument (mutatie komt volledig terug, H4), reden
     verplicht, aangifte-poort ervoor. Herboeken ná storno = NIEUW GUID (H5) — elke registratie-
     rij heeft haar eigen GUID (rlz_ids.rlz_bank_aanbetaling_id), dus dat volgt vanzelf.

Na stap 2 kent RLZ de aanbetaling alleen nog als GB-saldo op 1403/1806 — de open post per
relatie leeft in `bank_relatie_boeking` (status geboekt = open). Failsafes identiek aan het
direct-op-grootboek-pad: schrijfpoort (toggle + kill switch), volumerem (gedeelde dagteller met
de directe boekingen), verse RLZ-staat vóór elke write, verificatie ná elke write, audit op alles.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bank.boeken import (
    BankBoekenUitgeschakeld,
    BankMutatieNietGevonden,
    BankVolumeremBereikt,
    MutatieAlAfgeletterd,
    _bankboekingen_vandaag,
    _is_boeken_toegestaan,
)
from app.bank.models import (
    BankMutatie,
    BankRelatieBoeking,
    BankRelatieBoekingStatus,
    RelatieSoort,
)
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_bank_aanbetaling_id
from app.rlz.aangifte import AangiftePoort, blokkeer_bij_ingediende_aangifte
from app.rlz.client import RlzApiError, RlzClient
from app.sync.models import TaxRateCache, VendorCache

logger = logging.getLogger(__name__)

# RLZ-systeemrekeningen voor vooruitbetalingen (STAP-0 25-08 recon: aanwezig in het RLZ-sjabloon,
# `UseForPurchaseInvoiceDetails=false` is voor de API geen blokkade). Per administratie via de
# grootboek-cache op CODE opgezocht — nooit een GUID hardcoden (GUID's verschillen per administratie).
VOORUIT_CODE_PER_SOORT: dict[str, str] = {
    RelatieSoort.CREDITEUR.value: "1403",  # Vooruit betaalde inkoopfacturen (activa)
    RelatieSoort.DEBITEUR.value: "1806",  # Vooruitbetaalde verkoopfacturen (passiva)
}


class RelatieBoekenFout(Exception):
    """Basis voor domeinfouten van het relatie-koppelpad."""


class RelatieInstellingOntbreekt(RelatieBoekenFout):
    """Vooruitbetalingsrekening of 0%-tarief niet eenduidig uit de caches af te leiden — fail-closed,
    zichtbaar; sync de referentiedata of laat de Beheerder de grootboekinrichting nakijken."""


class RelatieNietGevonden(RelatieBoekenFout):
    pass


class RelatieBoekingBestaatAl(RelatieBoekenFout):
    def __init__(self, boeking_id: uuid.UUID) -> None:
        self.boeking_id = boeking_id
        super().__init__("Deze mutatie is al aan een relatie gekoppeld")


class RelatieBoekingNietGevonden(RelatieBoekenFout):
    pass


class BedragPastNiet(RelatieBoekenFout):
    """Het te koppelen bedrag heeft een ander teken dan de mutatie of overschrijdt het open bedrag."""


class RlzRelatieBoekingMislukt(RelatieBoekenFout):
    pass


@dataclass(frozen=True)
class RelatieInstelling:
    vooruit_ledger_id: uuid.UUID
    vooruit_code: str
    taxrate_id: uuid.UUID


@dataclass(frozen=True)
class RelatieBoekResultaat:
    boeking_id: uuid.UUID
    rlz_document_id: uuid.UUID
    rlz_boekstuknummer: str | None
    open_restant: Decimal | None


def bepaal_instelling(session: Session, *, administratie_id: uuid.UUID, relatie_soort: str) -> RelatieInstelling:
    """Deterministische keuze uit de caches (code rekent, nooit gokken):
    - vooruitbetalingsrekening = de grootboekrekening met code 1403 (crediteur) / 1806 (debiteur);
    - 0%-tarief = het ene nationale 0%-tarief dat NIET verlegd, NIET vrijgesteld en NIET
      'zelf specificeren' is ("NL, Nul tarief" — TaxKind 1, IsRelayed/IsExcempt/IsMixed false).
    Nul of meer dan één kandidaat = RelatieInstellingOntbreekt (fail-closed, zichtbaar)."""
    code = VOORUIT_CODE_PER_SOORT.get(relatie_soort)
    if code is None:
        raise RelatieBoekenFout(f"Onbekende relatiesoort {relatie_soort!r}")
    rekening = session.scalars(
        select(Grootboekrekening).where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.code == code,
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
        )
    ).first()
    if rekening is None:
        raise RelatieInstellingOntbreekt(
            f"Vooruitbetalingsrekening {code} ontbreekt in de grootboek-cache van deze administratie — "
            "synchroniseer het grootboek of laat de inrichting nakijken"
        )
    kandidaten = [
        rij
        for rij in session.scalars(
            select(TaxRateCache).where(
                TaxRateCache.administratie_id == administratie_id,
                TaxRateCache.verdwenen_uit_bron_op.is_(None),
            )
        )
        if _is_nul_tarief(rij)
    ]
    if len(kandidaten) != 1:
        raise RelatieInstellingOntbreekt(
            f"Geen eenduidig 0%-tarief ('Nul tarief', niet verlegd/vrijgesteld) in de btw-cache "
            f"({len(kandidaten)} kandidaten) — synchroniseer de btw-codes of laat de inrichting nakijken"
        )
    return RelatieInstelling(vooruit_ledger_id=rekening.ledger_id, vooruit_code=code, taxrate_id=kandidaten[0].id)


def _is_nul_tarief(rij: TaxRateCache) -> bool:
    data = rij.brondata or {}
    if rij.percentage is None or Decimal(rij.percentage) != 0:
        return False
    if data.get("IsRelayed") or data.get("IsExcempt") or data.get("IsMixed"):
        return False
    return data.get("TaxKind", 1) == 1


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    return Decimal(str(waarde)).quantize(Decimal("0.01"))


def _relatie_naam(session: Session, *, administratie_id: uuid.UUID, relatie_soort: str, entity_id: uuid.UUID,
                  client: RlzClient) -> str | None:
    if relatie_soort == RelatieSoort.CREDITEUR.value:
        vendor = session.get(VendorCache, (entity_id, administratie_id))
        if vendor is None:
            raise RelatieNietGevonden("Crediteur niet gevonden in de sync-cache — synchroniseer de crediteuren")
        return vendor.naam
    # Debiteuren hebben geen lokale cache (verkoop maakt ze ad hoc aan): bestaan toetsen bij RLZ.
    try:
        klant = client.get(f"Customers/{entity_id}")
    except RlzApiError as exc:
        raise RelatieNietGevonden(f"Debiteur niet gevonden in Reeleezee: {exc}") from exc
    return klant.get("Name") or klant.get("SearchName")


def boek_mutatie_op_relatie(
    *,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    relatie_soort: str,
    entity_id: uuid.UUID,
    actor_id: uuid.UUID,
    client: RlzClient,
    bedrag: Decimal | None = None,
    omschrijving: str | None = None,
    deel_id: uuid.UUID | None = None,
) -> RelatieBoekResultaat:
    """Volledige cyclus aanbetalingsdocument → boeken → afletteren, mét registratie. `bedrag`
    (teken van de mutatie) = het te koppelen deel; None = het volledige open bedrag. `deel_id`
    gevuld = onderdeel van een splitsing (dan géén één-per-mutatie-regel)."""
    if relatie_soort not in VOORUIT_CODE_PER_SOORT:
        raise RelatieBoekenFout(f"Onbekende relatiesoort {relatie_soort!r}")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
        if mutatie is None or mutatie.bedrag is None:
            raise BankMutatieNietGevonden("Bankmutatie niet gevonden in de cache — draai eerst de bank-sync")
        if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
            raise BankBoekenUitgeschakeld(
                "Boeken staat uit voor deze administratie of platformbreed — geen wijziging in Reeleezee"
            )
        if _bankboekingen_vandaag(session, administratie_id=administratie_id) + _relatieboekingen_vandaag(
            session, administratie_id=administratie_id
        ) >= settings.max_boekingen_per_dag_per_administratie:
            raise BankVolumeremBereikt(
                f"Volumerem: al {settings.max_boekingen_per_dag_per_administratie} bankboekingen vandaag"
            )
        if deel_id is None:
            bestaand = session.scalars(
                select(BankRelatieBoeking).where(
                    BankRelatieBoeking.administratie_id == administratie_id,
                    BankRelatieBoeking.payment_transaction_id == payment_transaction_id,
                    BankRelatieBoeking.deel_id.is_(None),
                    BankRelatieBoeking.status.in_(
                        (BankRelatieBoekingStatus.GEBOEKT.value, BankRelatieBoekingStatus.VERREKEND.value)
                    ),
                )
            ).first()
            if bestaand is not None:
                raise RelatieBoekingBestaatAl(bestaand.id)
        instelling = bepaal_instelling(session, administratie_id=administratie_id, relatie_soort=relatie_soort)
        entity_naam = _relatie_naam(
            session, administratie_id=administratie_id, relatie_soort=relatie_soort, entity_id=entity_id, client=client
        )
        mutatie_bedrag = Decimal(mutatie.bedrag)
        # Punt 15 (28-08): het aanbetalingsdocument krijgt de mutatiedatum als Date + BookDate (was:
        # RLZ-serverdatum) — boekingsdatum = documentdatum, ook hier.
        mutatie_datum_iso = f"{mutatie.boekdatum.isoformat()}T00:00:00" if mutatie.boekdatum else None

    # Verse RLZ-staat is leidend (kliktest-les 09-08: de cache kan achterlopen).
    try:
        vers = client.get_payment_transaction(payment_transaction_id, expand="PaymentReferenceList($expand=Document)")
    except RlzApiError as exc:
        raise RlzRelatieBoekingMislukt(f"RLZ-staat opvragen mislukt: {exc}") from exc
    open_vooraf = _als_decimal(vers.get("OpenAmount"))
    if open_vooraf is None or open_vooraf == 0:
        raise MutatieAlAfgeletterd("De mutatie staat in Reeleezee niet (meer) open — niets te koppelen")
    te_koppelen = _als_decimal(bedrag) if bedrag is not None else open_vooraf
    assert te_koppelen is not None
    if te_koppelen == 0 or (te_koppelen > 0) != (open_vooraf > 0) or abs(te_koppelen) > abs(open_vooraf):
        raise BedragPastNiet(
            f"Te koppelen bedrag {te_koppelen} past niet op het open bedrag {open_vooraf} van de mutatie "
            "(zelfde teken, niet groter)"
        )

    boeking_id = uuid.uuid4()
    rlz_document_id = rlz_bank_aanbetaling_id(boeking_id)
    is_crediteur = relatie_soort == RelatieSoort.CREDITEUR.value
    # Documentbedrag = |deel|, positief op de relatiekaart (crediteur: te betalen; debiteur: te ontvangen).
    regel = {
        "Account": {"id": str(instelling.vooruit_ledger_id)},
        "TaxRate": {"id": str(instelling.taxrate_id)},
        "NetAmount": float(abs(te_koppelen)),
        "TaxAmount": 0.0,
        "Description": omschrijving
        or f"Aanbetaling zonder factuur — bankmutatie {mutatie_bedrag} ({mutatie.tegenpartij_naam or ''})".strip(),
    }
    referentie = f"AANBETALING-{str(payment_transaction_id)[:8].upper()}"
    datum_extra: dict = {"Date": mutatie_datum_iso, "BookDate": mutatie_datum_iso} if mutatie_datum_iso else {}
    try:
        if is_crediteur:
            client.put_purchase_invoice(
                rlz_document_id, vendor_id=entity_id, lines=[regel], reference=referentie, **datum_extra
            )
            client.book_purchase_invoice(rlz_document_id)
            document = client.get(f"PurchaseInvoices/{rlz_document_id}")
        else:
            client.put_sales_invoice(rlz_document_id, customer_id=entity_id, lines=[regel], **datum_extra)
            client.book_sales_invoice(rlz_document_id)
            document = client.get_sales_invoice(rlz_document_id)
        items = client.list_payment_items(params={"$filter": f"Document/id eq {rlz_document_id}"})
    except RlzApiError as exc:
        raise RlzRelatieBoekingMislukt(f"Aanbetalingsdocument aanmaken/boeken mislukt: {exc}") from exc
    if not items:
        raise RlzRelatieBoekingMislukt(
            "Aanbetalingsdocument geboekt maar zonder open post (PaymentItem) — niet gekoppeld; "
            f"document {document.get('ReceiptNumber')} staat in Reeleezee, storneer 'm handmatig of probeer opnieuw"
        )
    item_id = uuid.UUID(str(items[0]["id"]))
    try:
        client.link_payment_item(payment_transaction_id, payment_item_id=item_id, linked_amount=float(te_koppelen))
        na = client.get_payment_transaction(payment_transaction_id, expand="PaymentReferenceList($expand=Document)")
    except RlzApiError as exc:
        _probeer_terugdraaien(client, rlz_document_id, is_crediteur=is_crediteur)
        raise RlzRelatieBoekingMislukt(f"Afletteren tegen het aanbetalingsdocument mislukt: {exc}") from exc
    open_na = _als_decimal(na.get("OpenAmount"))
    verwacht = (open_vooraf - te_koppelen).quantize(Decimal("0.01"))
    if open_na is None or open_na != verwacht:
        _probeer_terugdraaien(client, rlz_document_id, is_crediteur=is_crediteur)
        raise RlzRelatieBoekingMislukt(
            f"Koppeling niet zichtbaar in Reeleezee (open {open_vooraf} → {open_na}, verwacht {verwacht}) — "
            "aanbetalingsdocument teruggedraaid, niets geregistreerd"
        )

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.add(
            BankRelatieBoeking(
                id=boeking_id,
                administratie_id=administratie_id,
                payment_transaction_id=payment_transaction_id,
                deel_id=deel_id,
                relatie_soort=relatie_soort,
                entity_id=entity_id,
                entity_naam=entity_naam,
                bedrag=te_koppelen,
                vooruit_ledger_id=instelling.vooruit_ledger_id,
                taxrate_id=instelling.taxrate_id,
                rlz_document_id=rlz_document_id,
                rlz_boekstuknummer=document.get("ReceiptNumber"),
                rlz_payment_item_id=item_id,
                omschrijving=omschrijving,
                status=BankRelatieBoekingStatus.GEBOEKT.value,
                geboekt_door=actor_id,
            )
        )
        mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
        if mutatie is not None:
            mutatie.open_bedrag = open_na
            mutatie.laatst_gesynchroniseerd = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_relatie_boeking",
            record_id=boeking_id,
            actie="bank_mutatie_op_relatie_geboekt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "payment_transaction_id": str(payment_transaction_id),
                "deel_id": str(deel_id) if deel_id else None,
                "relatie_soort": relatie_soort,
                "entity_id": str(entity_id),
                "entity_naam": entity_naam,
                "bedrag": str(te_koppelen),
                "vooruit_code": instelling.vooruit_code,
                "rlz_document_id": str(rlz_document_id),
                "rlz_boekstuknummer": document.get("ReceiptNumber"),
                "open_restant": str(open_na),
            },
            administratie_id=administratie_id,
        )
    return RelatieBoekResultaat(
        boeking_id=boeking_id,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=document.get("ReceiptNumber"),
        open_restant=open_na,
    )


def _probeer_terugdraaien(client: RlzClient, rlz_document_id: uuid.UUID, *, is_crediteur: bool) -> None:
    """Best-effort storno van een net aangemaakt aanbetalingsdocument dat niet gekoppeld raakte —
    nooit stil: de aanroeper gooit hoe dan ook een zichtbare fout; dit voorkomt alleen een los
    geboekt document zonder registratie."""
    try:
        if is_crediteur:
            client.correct_purchase_invoice(rlz_document_id)
        else:
            client.correct_sales_invoice(rlz_document_id)
    except RlzApiError:
        logger.exception("Aanbetalingsdocument %s terugdraaien mislukt — handmatig storneren", rlz_document_id)


def _relatieboekingen_vandaag(session: Session, *, administratie_id: uuid.UUID) -> int:
    from datetime import time

    from sqlalchemy import func

    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(BankRelatieBoeking)
            .where(
                BankRelatieBoeking.administratie_id == administratie_id,
                BankRelatieBoeking.geboekt_op >= vandaag_begin,
            )
        )
        or 0
    )


def storno_relatie_boeking(
    *,
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    client: RlzClient,
) -> None:
    """Actie 19 op het aanbetalingsdocument (STAP-0 H4: mutatie komt volledig terug). Reden
    verplicht, aangifte-poort ervoor (fail-closed), verificatie op de verse OpenAmount, audit."""
    if not reden or not reden.strip():
        raise RelatieBoekenFout("Een storno-reden is verplicht")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(BankRelatieBoeking, boeking_id)
        if boeking is None or boeking.administratie_id != administratie_id:
            raise RelatieBoekingNietGevonden("Relatie-koppeling niet gevonden")
        if boeking.status == BankRelatieBoekingStatus.GESTORNEERD.value:
            raise RelatieBoekenFout("Deze koppeling is al gestorneerd")
        if boeking.status == BankRelatieBoekingStatus.VERREKEND.value:
            raise RelatieBoekenFout(
                "Deze aanbetaling is al verrekend met een geboekte factuur — storneer eerst die factuur "
                "(tegenboeken/storno) voordat de aanbetaling terug kan"
            )
        rlz_document_id = boeking.rlz_document_id
        is_crediteur = boeking.relatie_soort == RelatieSoort.CREDITEUR.value
        tx_id = boeking.payment_transaction_id

    ophalen = (
        (lambda: client.get(f"PurchaseInvoices/{rlz_document_id}"))
        if is_crediteur
        else (lambda: client.get_sales_invoice(rlz_document_id))
    )
    poort = AangiftePoort(client)
    blokkeer_bij_ingediende_aangifte([poort.toets_document(ophalen, kant="aanbetaling")])
    try:
        if is_crediteur:
            client.correct_purchase_invoice(rlz_document_id)
        else:
            client.correct_sales_invoice(rlz_document_id)
        vers = client.get_payment_transaction(tx_id, expand="PaymentReferenceList($expand=Document)")
    except RlzApiError as exc:
        raise RlzRelatieBoekingMislukt(f"Storno in Reeleezee mislukt: {exc}") from exc
    open_na = _als_decimal(vers.get("OpenAmount"))

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        boeking = session.get(BankRelatieBoeking, boeking_id)
        assert boeking is not None
        oud = boeking.status
        boeking.status = BankRelatieBoekingStatus.GESTORNEERD.value
        boeking.gestorneerd_door = actor_id
        boeking.gestorneerd_op = datetime.now(UTC)
        boeking.storno_reden = reden.strip()
        mutatie = session.get(BankMutatie, (tx_id, administratie_id))
        if mutatie is not None:
            mutatie.open_bedrag = open_na if open_na is not None else mutatie.bedrag
            mutatie.laatst_gesynchroniseerd = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_relatie_boeking",
            record_id=boeking_id,
            actie="bank_relatie_boeking_gestorneerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": oud},
            nieuwe_waarde={
                "status": boeking.status,
                "reden": boeking.storno_reden,
                "rlz_document_id": str(rlz_document_id),
                "open_na": str(open_na) if open_na is not None else None,
            },
            administratie_id=administratie_id,
        )


@dataclass(frozen=True)
class OpenAanbetaling:
    boeking_id: uuid.UUID
    payment_transaction_id: uuid.UUID
    relatie_soort: str
    entity_id: uuid.UUID
    entity_naam: str | None
    bedrag: Decimal
    boekdatum: object  # date | None
    rlz_boekstuknummer: str | None
    geboekt_op: datetime
    status: str


def open_aanbetalingen(
    *, administratie_id: uuid.UUID, entity_id: uuid.UUID | None = None, alleen_open: bool = True
) -> list[OpenAanbetaling]:
    """Leeslijst voor de open-posten-weergave (bankscherm-paneel) en het aanbetaling-signaal."""
    with scoped_session(administratie_id) as session:
        q = select(BankRelatieBoeking, BankMutatie.boekdatum).outerjoin(
            BankMutatie,
            (BankMutatie.id == BankRelatieBoeking.payment_transaction_id)
            & (BankMutatie.administratie_id == BankRelatieBoeking.administratie_id),
        ).where(BankRelatieBoeking.administratie_id == administratie_id)
        if alleen_open:
            q = q.where(BankRelatieBoeking.status == BankRelatieBoekingStatus.GEBOEKT.value)
        if entity_id is not None:
            q = q.where(BankRelatieBoeking.entity_id == entity_id)
        q = q.order_by(BankRelatieBoeking.geboekt_op.desc())
        return [
            OpenAanbetaling(
                boeking_id=rij.id,
                payment_transaction_id=rij.payment_transaction_id,
                relatie_soort=rij.relatie_soort,
                entity_id=rij.entity_id,
                entity_naam=rij.entity_naam,
                bedrag=Decimal(rij.bedrag),
                boekdatum=boekdatum,
                rlz_boekstuknummer=rij.rlz_boekstuknummer,
                geboekt_op=rij.geboekt_op,
                status=rij.status,
            )
            for rij, boekdatum in session.execute(q).all()
        ]


def markeer_verrekend_bij_boeking(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID,
    regels: list,
    actor_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Hook ín de boek-transactie van een inkoopfactuur: draagt het boekvoorstel een NEGATIEVE
    regel op de vooruitbetalingsrekening (de tegenregel uit het aanbetaling-signaal), dan wordt
    de oudste open aanbetaling van dezelfde crediteur met exact dat bedrag op `verrekend` gezet
    (append-only spoor: verrekend_met_document_id + audit). Geen match = niets (de mens kan de
    tegenregel ook uit een ander motief geboekt hebben) — nooit gokken op afwijkende bedragen."""
    open_rijen = list(
        session.scalars(
            select(BankRelatieBoeking)
            .where(
                BankRelatieBoeking.administratie_id == administratie_id,
                BankRelatieBoeking.entity_id == vendor_id,
                BankRelatieBoeking.relatie_soort == RelatieSoort.CREDITEUR.value,
                BankRelatieBoeking.status == BankRelatieBoekingStatus.GEBOEKT.value,
            )
            .order_by(BankRelatieBoeking.geboekt_op.asc())
        )
    )
    if not open_rijen:
        return []
    verrekend: list[uuid.UUID] = []
    for regel in regels:
        netto = getattr(regel, "netto_bedrag", None)
        ledger = getattr(regel, "ledger_id", None)
        if netto is None or ledger is None or Decimal(netto) >= 0:
            continue
        for rij in open_rijen:
            if rij.id in verrekend or rij.vooruit_ledger_id != ledger:
                continue
            if abs(Decimal(rij.bedrag)) != abs(Decimal(netto)):
                continue
            rij.status = BankRelatieBoekingStatus.VERREKEND.value
            rij.verrekend_met_document_id = document_id
            rij.verrekend_op = datetime.now(UTC)
            verrekend.append(rij.id)
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="bank_relatie_boeking",
                record_id=rij.id,
                actie="bank_aanbetaling_verrekend",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"status": BankRelatieBoekingStatus.GEBOEKT.value},
                nieuwe_waarde={"status": rij.status, "document_id": str(document_id), "bedrag": str(rij.bedrag)},
                administratie_id=administratie_id,
            )
            break
    return verrekend
