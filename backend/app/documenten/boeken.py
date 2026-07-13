from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, BoekenInstelling, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.boekvoorstel import BoekvoorstelData, haal_boekvoorstel_op, voer_checks_uit
from app.documenten.checks import CheckRapport
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_purchase_invoice_id, rlz_upload_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, _standaard_opslag
from app.documenten.webhook import WebhookRegel, bouw_factuur_geboekt_payload, webhook_secret
from app.geheugen.leerlus import leg_boeking_vast
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

_KAN_BOEKPOGING_STARTEN_VANUIT = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.BOEKEN_MISLUKT,
        # Handmatig afmaken (migratie 0015): de controleur heeft alles zelf ingevuld — de harde
        # checks (project verplicht per regel, regelsom) blijven onverkort de poort.
        DocumentStatus.HANDMATIG_AFMAKEN,
    }
)


class BoekenFout(Exception):
    """Basis voor alle domeinfouten in de boek-actie."""


class OngeldigeBoekpoging(BoekenFout):
    """Het document staat niet in een status waaruit geboekt kan worden."""


class BoekenGeblokkeerdDoorChecks(BoekenFout):
    def __init__(self, rapport: CheckRapport) -> None:
        self.rapport = rapport
        super().__init__("Boeken geblokkeerd door harde checks")


class BoekenUitgeschakeld(BoekenFout):
    """Failsafe (a): boeken staat uit voor deze administratie, of de globale kill switch staat
    uit — CLAUDE.md: 'boeken-toggle per administratie + globale kill switch'."""


class VolumeremBereikt(BoekenFout):
    """Failsafe (c): de dagelijkse boekingslimiet voor deze administratie is bereikt."""


class RlzBoekingMislukt(BoekenFout):
    """RLZ gaf een fout terug tijdens de boekpoging — het document staat op boeken_mislukt met de
    échte foutmelding; een volgende poging is idempotent (zelfde client-GUID's)."""


@dataclass(frozen=True)
class BoekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    rlz_document_id: uuid.UUID
    rlz_boekstuknummer: str | None


def _is_boeken_toegestaan(session: Session, *, administratie_id: uuid.UUID) -> bool:
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.boeken_ingeschakeld:
        return False
    instelling = session.get(BoekenInstelling, True)
    return instelling is not None and instelling.globaal_ingeschakeld


def _boekingen_vandaag(session: Session, *, administratie_id: uuid.UUID) -> int:
    vandaag_begin = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        session.scalar(
            select(func.count())
            .select_from(DocumentGebeurtenis)
            .join(Document, DocumentGebeurtenis.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                DocumentGebeurtenis.tijdstip >= vandaag_begin,
            )
        )
        or 0
    )


def _zorg_voor_klaar_om_te_boeken(session: Session, *, document: Document, actor_id: uuid.UUID) -> None:
    if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={"harde_checks": "doorstaan"},
        )


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _regels_naar_rlz_lines(voorstel: BoekvoorstelData) -> list[dict]:
    lines: list[dict] = []
    for regel in voorstel.regels:
        # btw_bedrag mag None zijn (de harde checks eisen 'm niet af, zie
        # checks.py::check_verplichte_velden) — een geldige case bij bv. verlegde btw of een
        # vrijgestelde regel, niet alleen een ontbrekend-veld-bug. netto_bedrag ís altijd gevuld
        # op dit punt (dat check wél af, en boek_document() draait de checks eerst).
        line: dict = {
            "Account": {"id": str(regel.ledger_id)},
            "TaxRate": {"id": str(regel.taxrate_id)},
            "NetAmount": float(regel.netto_bedrag),
            "TaxAmount": float(regel.btw_bedrag or 0),
        }
        if regel.project_id is not None:
            line["Project"] = {"id": str(regel.project_id)}
        if regel.omschrijving:
            line["Description"] = regel.omschrijving
        lines.append(line)
    return lines


def _boek_bij_rlz(
    *, client: RlzClient, document_id: uuid.UUID, voorstel: BoekvoorstelData, bestand: bytes, bestandsnaam: str
) -> tuple[uuid.UUID, str | None]:
    """PUT + /Uploads + actie 17, in die volgorde (RLZ berekent zelf totalen uit de regels — geen
    eigen bedragberekening hier). Retourneert (rlz_document_id, rlz_boekstuknummer)."""
    rlz_document_id = rlz_purchase_invoice_id(document_id)
    assert voorstel.vendor_id is not None and voorstel.factuurdatum is not None  # afgedwongen door de harde checks

    client.put_purchase_invoice(
        rlz_document_id,
        vendor_id=voorstel.vendor_id,
        lines=_regels_naar_rlz_lines(voorstel),
        reference=voorstel.referentie,
        # Volledige ISO-datetime, niet alleen de datum — exact de vorm die geverifieerd is tegen
        # de RLZ-test-administratie (verkenning/api-verkenning.md, "Boekstuknummer, factuurdatum
        # en /Uploads"); een kale datumstring is nooit tegen de live API getest.
        Date=f"{voorstel.factuurdatum.isoformat()}T00:00:00",
    )
    client.upload_bijlage(
        "PurchaseInvoices",
        rlz_document_id,
        upload_id=rlz_upload_id(document_id),
        filename=bestandsnaam,
        content_base64=base64.b64encode(bestand).decode(),
    )
    client.book_purchase_invoice(rlz_document_id)
    geboekt = client.get(f"PurchaseInvoices/{rlz_document_id}")
    return rlz_document_id, geboekt.get("ReceiptNumber")


def _zet_boeken_mislukt(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.BOEKEN_MISLUKT, actor_id=actor_id, detail={"fout": reden}
        )


def _sla_webhook_op(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    document_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
) -> None:
    """Webhook-stub (koppelcontract §3, CLAUDE.md-taak 2.5): payload bouwen + ondertekenen en in
    de outbox leggen — aflevering (HTTP-push) is een fase-vervolg, zie app/documenten/webhook.py.

    Scope (hardening-audit 2026-07-13): het koppelcontract beperkt de push tot inkoopfacturen
    van vastgoed-administraties — de outbox-rij ontstaat dus alleen als `is_vastgoed` aan staat
    (migratie 0018). Filteren gebeurt bewust hier bij het aanmaken, niet pas in de afleveraar:
    een rij die er nooit had mogen zijn kan dan ook nooit per ongeluk afgeleverd worden."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.is_vastgoed:
        return

    vendor_naam = None
    if voorstel.vendor_id is not None:
        vendor = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
        vendor_naam = vendor.naam if vendor else None

    webhook_regels = []
    for regel in voorstel.regels:
        grootboek = session.get(Grootboekrekening, (regel.ledger_id, administratie_id))
        webhook_regels.append(
            WebhookRegel(
                ledger_id=regel.ledger_id,
                grootboek_code=grootboek.code if grootboek else "",
                project_id=regel.project_id,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving=regel.omschrijving,
            )
        )

    payload = bouw_factuur_geboekt_payload(
        secret=webhook_secret(),
        administratie_id=administratie_id,
        rlz_admin_id=rlz_admin_id,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=rlz_boekstuknummer,
        factuurdatum=voorstel.factuurdatum,
        vendor_id=voorstel.vendor_id,
        vendor_naam=vendor_naam,
        referentie=voorstel.referentie or "",
        regels=webhook_regels,
        nu=datetime.now(UTC),
    )
    session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))


def boek_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> BoekResultaat:
    """De boekactie (CLAUDE.md-taak 2.3): harde checks herhalen (nooit de client-kant vertrouwen),
    dan de twee resterende failsafes (toggle+kill switch, volumerem), dan pas de echte RLZ-
    schrijfacties. Een blokkerende check/failsafe laat de status ongewijzigd, bùiten het
    klaarzetten op klaar_om_te_boeken zodra de checks zelf doorstaan — dat wordt in zijn eigen,
    los gecommitte transactie gedaan (vóór de failsafe-checks), zodat een falende failsafe die
    winst niet weer terugdraait: een latere retry hoeft de checks dan niet opnieuw te doorstaan."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status not in _KAN_BOEKPOGING_STARTEN_VANUIT:
            raise OngeldigeBoekpoging(f"Document staat op status {document.status.value}, kan niet boeken")
        bestandsnaam = document.bestandsnaam
        opslag_pad = document.opslag_pad
        rlz_admin_id = rlz_admin_id_voor(administratie_id)

    with _rlz_client_voor(administratie_id) as client:
        rapport = voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=client)
        if rapport.geblokkeerd:
            raise BoekenGeblokkeerdDoorChecks(rapport)

        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            _zorg_voor_klaar_om_te_boeken(session, document=document, actor_id=actor_id)

        with scoped_session(administratie_id) as session:
            if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
                raise BoekenUitgeschakeld(
                    "Boeken staat uit voor deze administratie of via de globale kill switch"
                )
            limiet = settings.max_boekingen_per_dag_per_administratie
            if _boekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
                raise VolumeremBereikt(f"Dagelijkse limiet van {limiet} boekingen bereikt voor deze administratie")

        try:
            voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
            bestand = _standaard_opslag().lezen(pad=opslag_pad)
            rlz_document_id, rlz_boekstuknummer = _boek_bij_rlz(
                client=client, document_id=document_id, voorstel=voorstel, bestand=bestand, bestandsnaam=bestandsnaam
            )
        except RlzApiError as exc:
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise RlzBoekingMislukt(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            # Elke andere fout tijdens de boekpoging (netwerkfout die alle retries overleeft,
            # opslagfout bij het lezen van de bijlage, bug) mag het document nooit in limbo
            # laten staan — dezelfde blokkerende afhandeling als een RlzApiError, alleen zonder
            # aanname dat het per se een RLZ-fout is. De oorspronkelijke fout gaat door naar de
            # globale exception-handler (app/main.py), die 'm loggen en er een nette melding +
            # correlatie-id van maakt.
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        boekvoorstel = session.get(Boekvoorstel, document_id)
        assert boekvoorstel is not None
        boekvoorstel.rlz_boekstuknummer = rlz_boekstuknummer

        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEBOEKT,
            actor_id=actor_id,
            detail={"rlz_document_id": str(rlz_document_id), "rlz_boekstuknummer": rlz_boekstuknummer},
        )
        _sla_webhook_op(
            session,
            administratie_id=administratie_id,
            rlz_admin_id=rlz_admin_id,
            document_id=document_id,
            voorstel=voorstel,
            rlz_document_id=rlz_document_id,
            rlz_boekstuknummer=rlz_boekstuknummer,
        )
        # Leerlus boekingsgeheugen (B5): de zojuist bevestigde boeking als bron='app'-observaties,
        # in dezelfde transactie als de GEBOEKT-overgang — vendor is hier altijd gevuld
        # (afgedwongen door de harde checks die deze functie zelf herhaalde). bron_datum =
        # boekdatum: het moment van menselijke bevestiging, zodat een latere correctie
        # (actie 19 -> opnieuw boeken) via recency wint van de oorspronkelijke boeking.
        assert voorstel.vendor_id is not None
        leg_boeking_vast(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            vendor_id=voorstel.vendor_id,
            boekdatum=datetime.now(UTC).date(),
            boekstuk_ref=rlz_boekstuknummer,
            regels=voorstel.regels,
            regels_samenvoegen=voorstel.regels_samenvoegen,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boekvoorstel",
            record_id=document_id,
            actie="geboekt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"rlz_document_id": str(rlz_document_id), "rlz_boekstuknummer": rlz_boekstuknummer},
            administratie_id=administratie_id,
        )

    return BoekResultaat(
        document_id=document_id,
        status=DocumentStatus.GEBOEKT,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=rlz_boekstuknummer,
    )
