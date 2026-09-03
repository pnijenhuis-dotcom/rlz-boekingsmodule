"""Tegenboek-pad voor geboekte inkoopfacturen (mockup tegenboek-mockup.html, akkoord Peter
22-08; STAP-0 "Tegenboek-pad STAP 0" in verkenning/api-verkenning.md; besluit Peter 22-08:
géén suppletie-signaal — correcties lopen mee in het lopende tijdvak).

De route wanneer storno door de aangifte-poort geblokkeerd is (app/rlz/aangifte.py): het
origineel blijft geboekt staan, de correctie is een NIEUWE PurchaseInvoice met gespiegelde
negatieve regels op dezelfde Entity (zelfde GB/TaxRate per regel), boekdatum vandaag — de
btw telt dan als negatieve voorbelasting mee in de eerstvolgende open aangifte (live
geverifieerd 22-08). Twee smaken (mockup):

- `volledig`  — de boeking hoort er niet te zijn: document blijft GEBOEKT, chip
  "TEGENGEBOEKT" mét kruisverwijzing (tijdlijn + audit, beide kanten).
- `vervang`   — tegenboeken én opnieuw boeken: document terug naar te_controleren,
  boekvoorstel.boek_cyclus +1 — de herboeking krijgt een eigen RLZ-GUID (nooit een her-PUT
  op het origineel) en de duplicaatcheck zondert de eigen correctieketen uit (dezelfde
  Entity+Referentie+bedrag is dáár bewust; zichtbaar in de tijdlijn).

Waarborgen: verplichte reden (audit + tijdlijn), harde checks onverkort op de tegenboeking
(verplichte velden, regeltelling, duplicaatcheck op de tegenboeking zelf), idempotente
RLZ-writes (deterministisch GUID + lookup-vóór-PUT: een retry na een halve mislukking raakt
dezelfde tegenboeking, nooit een tweede), betaalstatus-waarschuwing (een (deels) afgeletterd
origineel laat een open creditpost achter — RLZ verrekent die niet zelf, STAP-0 punt 3).

Webhook (koppelcontract §3): een tegenboeking in een vastgoed-administratie vuurt een
`factuur_geboekt`-event met NEGATIEVE regelbedragen en een eigen rlz_document_id — exact de
creditnota-norm van §3a (v1.14); GEEN `factuur_gestorneerd` voor het origineel: dat document
blijft in RLZ gewoon geboekt staan (er is op dat rlz_document_id niets teruggedraaid), de
ontvanger telt origineel + tegenboeking netto op nul. De herboeking (vervang) vuurt bij het
boeken zijn eigen geboekt-event op zijn eigen rlz_document_id (boekstand-reeks per
rlz_document_id, §3b)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.backends import BackendBoekFout, inkoop_port_voor
from app.backends.port import InkoopPort
from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.boekstand import volgend_volgnummer
from app.documenten.boekvoorstel import BoekvoorstelData, haal_boekvoorstel_op
from app.documenten.checks import CheckRapport, CheckRegel, voer_harde_checks_uit
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
    Tegenboeking,
    TegenboekingSoort,
    WebhookUitgaand,
)
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, _standaard_opslag
from app.documenten.webhook import WebhookRegel, bouw_factuur_geboekt_payload
from app.rlz.aangifte import KantToets
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

MIN_REDEN_LENGTE = 5  # zelfde ondergrens als de storno-redenen (en de DB-CHECK op de tabel)

# RLZ-documentstatussen (geverifieerd 2026-07-13): geboekt = 2 óf 3, concept = 1.


class TegenboekenFout(Exception):
    """Basis voor alle domeinfouten in het tegenboek-pad."""


class OngeldigeTegenboeking(TegenboekenFout):
    """Ongeldige invoer of documentstaat (422/409 in de router)."""


class TegenboekenNietToegestaan(TegenboekenFout):
    """Storno is NIET door de aangifte-poort geblokkeerd — tegenboeken is dan niet de route
    (mockup: de knop verschijnt alléén bij een geblokkeerde storno)."""


class TegenboekingBestaatAl(TegenboekenFout):
    """Er bestaat al een tegenboeking voor de huidige boek_cyclus van dit document."""


class TegenboekenGeblokkeerdDoorChecks(TegenboekenFout):
    def __init__(self, rapport: CheckRapport) -> None:
        self.rapport = rapport
        super().__init__("Tegenboeken geblokkeerd door harde checks")


class RlzTegenboekingMislukt(TegenboekenFout):
    """RLZ gaf een fout tijdens de tegenboekpoging — er is lokaal niets gewijzigd; een volgende
    poging is idempotent (deterministisch GUID + lookup-vóór-PUT)."""


@dataclass(frozen=True)
class BetaalStatus:
    """Betaalstatus van het origineel (mockup: de waarschuwing verschijnt alléén als het
    origineel (deels) afgeletterd is; bij deelbetaling openstaand vs. betaald tonen)."""

    betaald_bedrag: Decimal
    open_bedrag: Decimal
    volledig_afgeletterd: bool


@dataclass(frozen=True)
class VoorbeeldRegel:
    """Eén regel van het tegenboek-voorbeeld (mockup-tabel: grootboek, omschrijving, negatieve
    netto/btw)."""

    grootboek_code: str | None
    grootboek_naam: str | None
    omschrijving: str
    netto_bedrag: Decimal
    btw_bedrag: Decimal


@dataclass(frozen=True)
class TegenboekingInfo:
    soort: str
    reden: str
    boek_cyclus: int
    rlz_tegenboeking_id: uuid.UUID
    rlz_boekstuknummer: str | None
    origineel_betaald_bedrag: Decimal | None
    aangemaakt_door: uuid.UUID
    aangemaakt_op: datetime


@dataclass(frozen=True)
class TegenboekToets:
    """Leesroute voor de UI: mag hier tegengeboekt worden, en wat wordt het dan? De knop
    "Tegenboeken…" verschijnt alléén als `storno_geblokkeerd` (en er nog geen tegenboeking
    voor de huidige cyclus bestaat)."""

    document_id: uuid.UUID
    storno_geblokkeerd: bool
    blokkade_melding: str | None
    kant: KantToets | None
    tegenboeking: TegenboekingInfo | None  # bestaande tegenboeking voor de huidige cyclus
    betaalstatus: BetaalStatus | None  # None = origineel niet leesbaar in RLZ
    voorbeeld: list[VoorbeeldRegel]
    referentie: str | None
    tegenboek_referentie: str
    leverancier_naam: str | None
    totaal_netto: Decimal
    totaal_btw: Decimal


@dataclass(frozen=True)
class TegenboekResultaat:
    document_id: uuid.UUID
    soort: str
    status: DocumentStatus
    rlz_tegenboeking_id: uuid.UUID
    rlz_boekstuknummer: str | None


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _port_voor(administratie_id: uuid.UUID) -> InkoopPort:
    """Boekhoud-backend-port (0016): RLZ = nieuwe PurchaseInvoice met gespiegelde regels; Odoo = reversal
    (creditnota) mét kruisverwijzing — pakketkennis leeft in de adapter."""
    return inkoop_port_voor(administratie_id, rlz_client_factory=lambda: _rlz_client_voor(administratie_id))


def tegenboek_referentie(referentie: str | None) -> str:
    """Referentie van de tegenboeking: herkenbaar gekoppeld aan het origineel, binnen RLZ's
    30-tekens-afkap (find_purchase_invoices_by_reference)."""
    return f"TB {referentie or ''}".strip()[:30]


def _tegenboek_omschrijving(voorstel: BoekvoorstelData, leverancier_naam: str | None) -> str:
    """Mockup-regel: "TEGENBOEKING 2026-0841 · Bouwmaat Eindhoven"."""
    delen = ["TEGENBOEKING", voorstel.referentie or ""]
    tekst = " ".join(d for d in delen if d)
    return f"{tekst} · {leverancier_naam}" if leverancier_naam else tekst


def _als_decimal(waarde: object) -> Decimal:
    try:
        return Decimal(str(waarde))
    except Exception:  # noqa: BLE001 — RLZ-velden zijn niet ons schema; onleesbaar = 0
        return Decimal("0")


def _leverancier_naam(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> str | None:
    if vendor_id is None:
        return None
    vendor = session.get(VendorCache, (vendor_id, administratie_id))
    return vendor.naam if vendor else None


def _voorbeeld_regels(
    session: Session, *, administratie_id: uuid.UUID, voorstel: BoekvoorstelData, omschrijving: str
) -> list[VoorbeeldRegel]:
    regels: list[VoorbeeldRegel] = []
    for regel in voorstel.regels:
        grootboek = (
            session.get(Grootboekrekening, (regel.ledger_id, administratie_id)) if regel.ledger_id else None
        )
        regels.append(
            VoorbeeldRegel(
                grootboek_code=grootboek.code if grootboek else None,
                grootboek_naam=grootboek.naam if grootboek else None,
                omschrijving=omschrijving,
                netto_bedrag=-(regel.netto_bedrag or Decimal("0")),
                btw_bedrag=-(regel.btw_bedrag or Decimal("0")),
            )
        )
    return regels


def _bestaande_tegenboeking(session: Session, *, document_id: uuid.UUID, boek_cyclus: int) -> TegenboekingInfo | None:
    rij = session.get(Tegenboeking, (document_id, boek_cyclus))
    if rij is None:
        return None
    return TegenboekingInfo(
        soort=rij.soort,
        reden=rij.reden,
        boek_cyclus=rij.boek_cyclus,
        rlz_tegenboeking_id=rij.rlz_tegenboeking_id,
        rlz_boekstuknummer=rij.rlz_boekstuknummer,
        origineel_betaald_bedrag=rij.origineel_betaald_bedrag,
        aangemaakt_door=rij.aangemaakt_door,
        aangemaakt_op=rij.aangemaakt_op,
    )


def _laad_geboekt_document(session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None or document.administratie_id != administratie_id:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort != "inkoopfactuur":
        raise OngeldigeTegenboeking(
            f"Document heeft soort {document.soort} — tegenboeken is alleen voor inkoopfacturen"
        )
    if document.status != DocumentStatus.GEBOEKT:
        raise OngeldigeTegenboeking(
            f"Document staat op status {document.status.value} — alleen een geboekt document kan tegengeboekt worden"
        )
    return document


def _betaalstatus_van(stand) -> BetaalStatus | None:
    if stand.betaald_bedrag is None and stand.open_bedrag is None:
        return None
    return BetaalStatus(
        betaald_bedrag=stand.betaald_bedrag or Decimal("0"),
        open_bedrag=stand.open_bedrag or Decimal("0"),
        volledig_afgeletterd=stand.volledig_afgeletterd,
    )


def toets(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> TegenboekToets:
    """De leesroute voor de UI (controlescherm-sectie + archief-⋯-menu): is storno geblokkeerd
    (dan verschijnt "Tegenboeken…"), bestaat er al een tegenboeking (chip TEGENGEBOEKT), en het
    voorbeeld van de tegenboeking (mockup-tabel) + de betaalstatus-waarschuwing."""
    with scoped_session(administratie_id) as session:
        document = _laad_geboekt_document(session, administratie_id=administratie_id, document_id=document_id)
        del document

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    with scoped_session(administratie_id) as session:
        leverancier = _leverancier_naam(session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
        omschrijving = _tegenboek_omschrijving(voorstel, leverancier)
        voorbeeld = _voorbeeld_regels(
            session, administratie_id=administratie_id, voorstel=voorstel, omschrijving=omschrijving
        )
        bestaande = _bestaande_tegenboeking(session, document_id=document_id, boek_cyclus=voorstel.boek_cyclus)

    with _port_voor(administratie_id) as port:
        stand = port.origineel_stand(document_id=document_id, boek_cyclus=voorstel.boek_cyclus)
    kant = stand.kant
    betaalstatus = _betaalstatus_van(stand)

    return TegenboekToets(
        document_id=document_id,
        storno_geblokkeerd=not kant.toegestaan,
        blokkade_melding=kant.reden,
        kant=kant,
        tegenboeking=bestaande,
        betaalstatus=betaalstatus,
        voorbeeld=voorbeeld,
        referentie=voorstel.referentie,
        tegenboek_referentie=tegenboek_referentie(voorstel.referentie),
        leverancier_naam=leverancier,
        totaal_netto=sum((r.netto_bedrag for r in voorbeeld), Decimal("0")),
        totaal_btw=sum((r.btw_bedrag for r in voorbeeld), Decimal("0")),
    )


def _harde_checks_op_tegenboeking(
    *,
    client: RlzClient,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    referentie: str,
) -> CheckRapport:
    """Mockup: "de harde checks draaien onverkort op de tegenboeking" — dezelfde vier checks als
    het boekpad, met de gespiegelde (negatieve) bedragen en de eigen tegenboek-referentie. De
    eigen correctieketen (alle (her)boekings- en tegenboekings-GUID's van dit document) telt
    niet als duplicaat; élk ander RLZ-document met dezelfde crediteur/referentie/bedrag wél."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        project_verplicht = administratie.project_verplicht if administratie else False
    keten = frozenset(
        {rlz_herboeking_id(document_id, c) for c in range(voorstel.boek_cyclus + 1)}
        | {rlz_tegenboeking_id(document_id, c) for c in range(voorstel.boek_cyclus + 1)}
    )
    regels = [
        CheckRegel(
            ledger_id=regel.ledger_id,
            taxrate_id=regel.taxrate_id,
            project_id=regel.project_id,
            netto_bedrag=-(regel.netto_bedrag or Decimal("0")),
            btw_bedrag=-(regel.btw_bedrag or Decimal("0")),
        )
        for regel in voorstel.regels
    ]
    return voer_harde_checks_uit(
        client=client,
        vendor_id=voorstel.vendor_id,
        referentie=referentie,
        factuurdatum=date.today(),
        totaalbedrag=-(voorstel.totaalbedrag or Decimal("0")),
        regels=regels,
        eigen_rlz_document_id=rlz_tegenboeking_id(document_id, voorstel.boek_cyclus),
        uitgezonderde_rlz_document_ids=keten,
        project_verplicht=project_verplicht,
    )


def _tijdlijn(session: Session, *, document: Document, actor_id: uuid.UUID, detail: dict) -> None:
    """Tijdlijnregel zónder statusovergang (zelfde patroon als de doorbelasting): de UI toont
    "Status blijft geboekt" met het detail eronder."""
    session.add(
        DocumentGebeurtenis(
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail=detail,
        )
    )


def _sla_tegenboek_webhook_op(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    rlz_tegenboeking_id_: uuid.UUID,
    rlz_boekstuknummer: str | None,
    referentie: str,
    leverancier_naam: str | None,
) -> None:
    """Vastgoed-terugkoppeling: `factuur_geboekt` met NEGATIEVE regelbedragen en een eigen
    rlz_document_id — de creditnota-norm van koppelcontract §3a (v1.14). Bewust GEEN
    `factuur_gestorneerd` voor het origineel: dat blijft in RLZ geboekt staan (er is op dát
    rlz_document_id niets teruggedraaid) — de ontvanger telt origineel + tegenboeking netto op
    nul, met elk hun eigen volgnummer-reeks per rlz_document_id (§3b).

    `corrigeert_document_id` (schema 1.2, v1.17 — akkoord Vastly 23-08): het RLZ-GUID van het
    origineel dat deze tegenboeking corrigeert, deterministisch uit de kruisverwijzing
    (document_id + boek_cyclus, migratie 0061) — zo legt Vastly het verband
    origineel↔tegenboeking zonder referentie-heuristiek. Alléén hier; de herboeking bij
    'vervang' is een gewoon nieuw document en draagt het veld níét."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.is_vastgoed:
        return
    webhook_regels = []
    for regel in voorstel.regels:
        grootboek = (
            session.get(Grootboekrekening, (regel.ledger_id, administratie_id)) if regel.ledger_id else None
        )
        webhook_regels.append(
            WebhookRegel(
                ledger_id=regel.ledger_id,
                grootboek_code=grootboek.code if grootboek else "",
                project_id=regel.project_id,
                netto_bedrag=-(regel.netto_bedrag or Decimal("0")),
                btw_bedrag=-(regel.btw_bedrag or Decimal("0")) if regel.btw_bedrag is not None else None,
                omschrijving=None,
            )
        )
    payload = bouw_factuur_geboekt_payload(
        administratie_id=administratie_id,
        rlz_admin_id=rlz_admin_id_voor(administratie_id),
        rlz_document_id=rlz_tegenboeking_id_,
        rlz_boekstuknummer=rlz_boekstuknummer,
        factuurdatum=date.today(),
        vendor_id=voorstel.vendor_id,
        vendor_naam=leverancier_naam,
        referentie=referentie,
        volgnummer=volgend_volgnummer(session, document_id=document_id, rlz_document_id=rlz_tegenboeking_id_),
        regels=webhook_regels,
        corrigeert_document_id=rlz_herboeking_id(document_id, voorstel.boek_cyclus),
    )
    session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))


def voer_tegenboeking_uit(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    soort: str,
    reden: str,
) -> TegenboekResultaat:
    """De tegenboek-actie (mockup: één scherm — keuze, voorbeeld, reden, boeken):

    1. poorten: geboekt inkoopdocument, verplichte reden, geldige soort, storno-geblokkeerd
       (de aangifte-poort — tegenboeken is uitsluitend de route als storno niet kan), geen
       bestaande tegenboeking voor deze cyclus, origineel in RLZ nog geboekt;
    2. harde checks onverkort op de tegenboeking (incl. duplicaatcheck met keten-uitzondering);
    3. RLZ, idempotent: lookup-vóór-PUT op het deterministische tegenboek-GUID → PUT
       (gespiegelde negatieve regels, zelfde Entity, boekdatum vandaag) → bijlage (het
       originele document) → actie 17 → ReceiptNumber;
    4. lokaal in één transactie: tegenboeking-rij + tijdlijn + audit + webhook; bij `vervang`
       óók boek_cyclus +1 en de overgang naar te_controleren (opnieuw boeken via het gewone
       boekpad, dat dan automatisch het nieuwe herboeking-GUID gebruikt)."""
    if soort not in (TegenboekingSoort.VOLLEDIG.value, TegenboekingSoort.VERVANG.value):
        raise OngeldigeTegenboeking(f"Onbekende tegenboek-soort: {soort}")
    if len(reden.strip()) < MIN_REDEN_LENGTE:
        raise OngeldigeTegenboeking(f"Reden is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)")

    with scoped_session(administratie_id) as session:
        document = _laad_geboekt_document(session, administratie_id=administratie_id, document_id=document_id)
        bestandsnaam = document.bestandsnaam
        opslag_pad = document.opslag_pad

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    if not voorstel.regels or voorstel.vendor_id is None:
        raise OngeldigeTegenboeking("Het geboekte voorstel mist crediteur of regels — tegenboeken kan niet")

    with scoped_session(administratie_id) as session:
        if _bestaande_tegenboeking(session, document_id=document_id, boek_cyclus=voorstel.boek_cyclus) is not None:
            raise TegenboekingBestaatAl("Deze boeking is al tegengeboekt")
        leverancier = _leverancier_naam(session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id)

    referentie = tegenboek_referentie(voorstel.referentie)
    omschrijving = _tegenboek_omschrijving(voorstel, leverancier)

    with _port_voor(administratie_id) as port:
        stand = port.origineel_stand(document_id=document_id, boek_cyclus=voorstel.boek_cyclus)
        kant = stand.kant
        betaalstatus = _betaalstatus_van(stand)
        # Eerst de concept-check: een al gestorneerd origineel telt in de aangifte-poort als "vrij"
        # (geen btw-effect meer) — dat zou hieronder een misleidende melding geven.
        if not stand.nog_geboekt:
            raise OngeldigeTegenboeking(
                "Het origineel staat in de boekhouding al op concept of is al teruggedraaid (gestorneerd) — een "
                "tegenboeking zou dubbel corrigeren"
            )
        if kant.toegestaan:
            raise TegenboekenNietToegestaan(
                "Storno is niet door de btw-aangifte geblokkeerd — corrigeer via stornering "
                "(actie 19) in Reeleezee in plaats van een tegenboeking"
            )

        rapport = _harde_checks_op_tegenboeking(
            client=port.leesclient(),
            administratie_id=administratie_id,
            document_id=document_id,
            voorstel=voorstel,
            referentie=referentie,
        )
        if rapport.geblokkeerd:
            raise TegenboekenGeblokkeerdDoorChecks(rapport)

        # Schrijfactie via de adapter, idempotent per (document, boek_cyclus): RLZ = lookup-vóór-PUT op het
        # deterministische tegenboek-GUID; Odoo = reversal mét kruisverwijzing + gespiegelde btw-override.
        try:
            uitkomst = port.boek_tegenboeking(
                document_id=document_id,
                voorstel=voorstel,
                referentie=referentie,
                omschrijving=omschrijving,
                reden=reden.strip(),
                bestand=_standaard_opslag().lezen(pad=opslag_pad),
                bestandsnaam=bestandsnaam,
            )
        except BackendBoekFout as exc:
            # Niets lokaal gewijzigd — het document blijft gewoon GEBOEKT; de fout is zichtbaar (502 in de
            # router) en een volgende poging raakt hetzelfde externe document.
            raise RlzTegenboekingMislukt(str(exc)) from exc
        rlz_tegenboeking_id_ = uitkomst.extern_document_id
        rlz_boekstuknummer = uitkomst.boekstuknummer

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        boekvoorstel_rij = session.get(Boekvoorstel, document_id)
        assert boekvoorstel_rij is not None

        session.add(
            Tegenboeking(
                document_id=document_id,
                boek_cyclus=voorstel.boek_cyclus,
                administratie_id=administratie_id,
                soort=soort,
                reden=reden.strip(),
                rlz_tegenboeking_id=rlz_tegenboeking_id_,
                rlz_boekstuknummer=rlz_boekstuknummer,
                origineel_betaald_bedrag=betaalstatus.betaald_bedrag if betaalstatus else None,
                aangemaakt_door=actor_id,
            )
        )
        detail = {
            "tegenboeking": {
                "soort": soort,
                "reden": reden.strip(),
                "rlz_tegenboeking_id": str(rlz_tegenboeking_id_),
                "rlz_boekstuknummer": rlz_boekstuknummer,
                **uitkomst.detail,
                "referentie": referentie,
                "origineel_betaald_bedrag": str(betaalstatus.betaald_bedrag) if betaalstatus else None,
            }
        }
        if soort == TegenboekingSoort.VERVANG.value:
            # De herboeking is via de nieuwe boek_cyclus gekoppeld aan deze tegenboeking en
            # uitgezonderd van het duplicaatsignaal (mockup) — zichtbaar in dit tijdlijn-detail.
            boekvoorstel_rij.boek_cyclus = voorstel.boek_cyclus + 1
            detail["tegenboeking"]["herboeking_cyclus"] = boekvoorstel_rij.boek_cyclus
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.TE_CONTROLEREN,
                actor_id=actor_id,
                detail=detail,
            )
            nieuwe_status = DocumentStatus.TE_CONTROLEREN
        else:
            _tijdlijn(session, document=document, actor_id=actor_id, detail=detail)
            nieuwe_status = DocumentStatus.GEBOEKT

        _sla_tegenboek_webhook_op(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            voorstel=voorstel,
            rlz_tegenboeking_id_=rlz_tegenboeking_id_,
            rlz_boekstuknummer=rlz_boekstuknummer,
            referentie=referentie,
            leverancier_naam=leverancier,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="tegenboeking",
            record_id=document_id,
            actie="tegengeboekt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=detail["tegenboeking"],
            administratie_id=administratie_id,
        )

    return TegenboekResultaat(
        document_id=document_id,
        soort=soort,
        status=nieuwe_status,
        rlz_tegenboeking_id=rlz_tegenboeking_id_,
        rlz_boekstuknummer=rlz_boekstuknummer,
    )
