"""Verkoopfactuur-boekmotor (Vastly VASTLY-VERKOOP, koppelcontract §2d v1.10/v1.11): boekt het
document als SalesInvoice MÉT Entity = de échte huurder als RLZ-debiteur (besluit Peter
2026-08-08 — idempotente debiteur-aanmaak, géén verzameldebiteur), op de gedeelde
SalesInvoice-motor van de omzetmodule (app/omzet/boeken.py::_boek_verkoopfactuur: retry-inhaal
via GET-op-eigen-GUID + deterministisch nummer-herstel).

Een creditnota (381, §2d-creditnota's v1.11) boekt als tegenboeking op dezelfde debiteur:
zelfde motor, regelbedragen genegeerd — bewezen vorm voor de verkoopkant (api-verkenning:
verkoopcreditnota's zijn negatieve SalesInvoices, geen apart documenttype; STAP-0
poc_verkoop_schrijf.py verifieert de creditvariant tegen de test-administratie).

Anders dan de omzetmodule is er maar één RLZ-document per boeking — geen memoriaal, dus geen
half_geboekt-pad: elke fout vóór of tijdens boeken eindigt zichtbaar op boeken_mislukt en de
retry is idempotent (zelfde client-GUID's).

Failsafes: identiek aan inkoop/omzet — checks server-side herhalen, toggle per administratie +
globale kill switch, volumerem (gedeeld geteld over álle boekingen van de administratie).
Webhook: `factuur_geboekt` met referentie = het Vastly-factuurnummer (§3 v1.10), alleen voor
vastgoed-administraties — zelfde outbox/afleveraar, aflevering default UIT."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.documenten.boeken import (
    _KAN_BOEKPOGING_STARTEN_VANUIT,
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
    _boekingen_vandaag,
    _is_boeken_toegestaan,
    _rlz_client_voor,
    _zet_boeken_mislukt,
)
from app.documenten.boekstand import volgend_volgnummer
from app.documenten.models import Document, DocumentSoort, DocumentStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_sales_invoice_id, rlz_upload_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, _standaard_opslag
from app.documenten.webhook import WebhookRegel, bouw_factuur_geboekt_verkoop_payload
from app.omzet.boeken import _boek_verkoopfactuur, _lokaal_max_invoice_number
from app.rlz.client import RlzApiError
from app.rlz.credentials import rlz_admin_id_voor
from app.verkoop.debiteur import DebiteurAanmakenMislukt, zorg_voor_debiteur
from app.verkoop.models import VerkoopBoeking, VerkoopBoekingStatus, VerkoopVoorstel
from app.verkoop.voorstel import (
    VerkoopVoorstelData,
    haal_verkoop_voorstel_op,
    verkoop_omschrijving_vastly,
    voer_verkoop_checks_uit,
)


@dataclass(frozen=True)
class VerkoopBoekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    verkoop_rlz_id: uuid.UUID
    verkoop_referentie: str | None
    verkoop_boekstuknummer: str | None


def _verkoop_lines(voorstel: VerkoopVoorstelData, *, marker: str) -> list[dict]:
    """Verkoopregels 1-op-1 uit het bevestigde voorstel (bedragen komen gescheiden netto/btw uit
    de UBL — geen splitsing nodig). Creditnota (381): tegenboeking = dezelfde regels met
    negatief teken, op dezelfde debiteur (bewezen creditvorm: negatieve SalesInvoice).

    De deterministische duplicaat-marker staat als PREFIX in de Description van regel 1:
    RLZ negeert de document-Description en leidt 'm af uit de éérste regel (verkoop-STAP-0
    2026-08-09) — de Receipts-duplicaatcheck filtert op startswith(marker)."""
    teken = Decimal(-1) if voorstel.is_creditnota else Decimal(1)
    lines: list[dict] = []
    for i, regel in enumerate(voorstel.regels):
        assert regel.ledger_id is not None and regel.taxrate_id is not None  # checks draaiden al
        assert regel.netto_bedrag is not None
        omschrijving = regel.omschrijving or ""
        if i == 0:
            # De marker eindigt zelf al op "·" (zie verkoop_omschrijving_vastly).
            omschrijving = f"{marker} {omschrijving}".strip()
        lines.append(
            {
                "Account": {"id": str(regel.ledger_id)},
                "TaxRate": {"id": str(regel.taxrate_id)},
                "NetAmount": float(regel.netto_bedrag * teken),
                "TaxAmount": float((regel.btw_bedrag or Decimal(0)) * teken),
                "Description": omschrijving,
            }
        )
    return lines


def _lokaal_max_verkoop_invoice_number(administratie_id: uuid.UUID) -> int:
    """Het lokale deel van het nummer-herstel, over ÁLLE eigen SalesInvoice-boekingen van deze
    administratie: de omzet-Receipts (omzet_boeking) én de Vastly-verkoopboekingen hier —
    de RLZ-collectie ziet geen van beide (omzet-STAP-0)."""
    from app.doorbelasting.models import DoorbelastingBoeking

    with scoped_session(administratie_id) as session:
        eigen_max = session.scalar(
            select(VerkoopBoeking.verkoop_invoice_number)
            .where(
                VerkoopBoeking.administratie_id == administratie_id,
                VerkoopBoeking.verkoop_invoice_number.isnot(None),
            )
            .order_by(VerkoopBoeking.verkoop_invoice_number.desc())
            .limit(1)
        )
        # sinds 0044 telt óók de doorbelastingsmotor eigen SalesInvoice-nummers uit —
        # zonder deze tak kan het nummer-herstel hier botsen met een doorbelastingsfactuur
        doorbelasting_max = session.scalar(
            select(DoorbelastingBoeking.verkoop_invoice_number)
            .where(
                DoorbelastingBoeking.administratie_id == administratie_id,
                DoorbelastingBoeking.verkoop_invoice_number.isnot(None),
            )
            .order_by(DoorbelastingBoeking.verkoop_invoice_number.desc())
            .limit(1)
        )
    return max(eigen_max or 0, doorbelasting_max or 0, _lokaal_max_invoice_number(administratie_id))


def _sla_verkoop_webhook_op(
    session,
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    document_id: uuid.UUID,
    voorstel: VerkoopVoorstelData,
    customer_id: uuid.UUID,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
) -> None:
    """Zelfde scope-regel als de inkoopvariant (documenten/boeken.py::_sla_webhook_op): de
    outbox-rij ontstaat alleen voor vastgoed-administraties — filteren bij aanmaken, de
    afleveraar assert het nogmaals."""
    administratie = session.get(Administratie, administratie_id)
    if administratie is None or not administratie.is_vastgoed:
        return
    assert voorstel.factuurdatum is not None and voorstel.factuurnummer is not None

    webhook_regels = []
    for regel in voorstel.regels:
        grootboek = session.get(Grootboekrekening, (regel.ledger_id, administratie_id))
        webhook_regels.append(
            WebhookRegel(
                ledger_id=regel.ledger_id,
                grootboek_code=grootboek.code if grootboek else (regel.gb_code or ""),
                project_id=None,
                netto_bedrag=regel.netto_bedrag or Decimal(0),
                btw_bedrag=regel.btw_bedrag or Decimal(0),
                omschrijving=regel.omschrijving,
            )
        )
    payload = bouw_factuur_geboekt_verkoop_payload(
        administratie_id=administratie_id,
        rlz_admin_id=rlz_admin_id,
        rlz_document_id=rlz_document_id,
        rlz_boekstuknummer=rlz_boekstuknummer,
        factuurdatum=voorstel.factuurdatum,
        customer_id=customer_id,
        debiteur_naam=voorstel.debiteur_naam,
        referentie=voorstel.factuurnummer,
        is_creditnota=voorstel.is_creditnota,
        volgnummer=volgend_volgnummer(session, document_id=document_id, rlz_document_id=rlz_document_id),
        regels=webhook_regels,
    )
    session.add(WebhookUitgaand(document_id=document_id, event=payload["event"], payload=payload))


def boek_verkoop_document(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> VerkoopBoekResultaat:
    """De verkoop-boekactie: zelfde poortvolgorde als inkoop/omzet — statuspoort + soortpoort,
    harde checks server-side herhalen, klaar_om_te_boeken in eigen transactie, failsafes
    (toggle/kill switch + volumerem), dan pas RLZ: debiteur borgen → SalesInvoice-motor →
    registratie + webhook + GEBOEKT in één transactie."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status not in _KAN_BOEKPOGING_STARTEN_VANUIT:
            raise OngeldigeBoekpoging(f"Document staat op status {document.status.value}, kan niet boeken")
        if document.soort != DocumentSoort.VERKOOPFACTUUR.value:
            raise OngeldigeBoekpoging(
                f"Document heeft soort {document.soort} — deze boekactie is alleen voor verkoopfacturen"
            )
        bestandsnaam = document.bestandsnaam
        opslag_pad = document.opslag_pad
        rlz_admin_id = rlz_admin_id_voor(administratie_id)

    with _rlz_client_voor(administratie_id) as client:
        rapport = voer_verkoop_checks_uit(administratie_id=administratie_id, document_id=document_id, client=client)
        if rapport.geblokkeerd:
            raise BoekenGeblokkeerdDoorChecks(rapport)

        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                    actor_id=actor_id,
                    detail={"harde_checks": "doorstaan"},
                )

        with scoped_session(administratie_id) as session:
            if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
                raise BoekenUitgeschakeld("Boeken staat uit voor deze administratie of via de globale kill switch")
            limiet = settings.max_boekingen_per_dag_per_administratie
            if _boekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
                raise VolumeremBereikt(f"Dagelijkse limiet van {limiet} boekingen bereikt voor deze administratie")

        voorstel = haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert voorstel.debiteur_naam is not None and voorstel.factuurnummer is not None  # checks draaiden al
        assert voorstel.factuurdatum is not None
        verkoop_rlz_id = rlz_sales_invoice_id(document_id)
        try:
            customer_id = zorg_voor_debiteur(
                client=client,
                administratie_id=administratie_id,
                actor_id=actor_id,
                naam=voorstel.debiteur_naam,
            )
            bestand = _standaard_opslag().lezen(pad=opslag_pad)
            marker = verkoop_omschrijving_vastly(voorstel.factuurnummer, is_creditnota=voorstel.is_creditnota)
            invoice_number, referentie, boekstuknummer = _boek_verkoopfactuur(
                client=client,
                rlz_id=verkoop_rlz_id,
                customer_id=customer_id,
                lines=_verkoop_lines(voorstel, marker=marker),
                datum_iso=f"{voorstel.factuurdatum.isoformat()}T00:00:00",
                upload_id=rlz_upload_id(document_id),
                bestandsnaam=bestandsnaam,
                bestand=bestand,
                lokaal_max_invoice_number=_lokaal_max_verkoop_invoice_number(administratie_id),
                # NB de document-Description wordt door RLZ genegeerd/afgeleid van regel 1
                # (verkoop-STAP-0) — de marker zit dáárom in regel 1; deze parameter blijft
                # gezet voor het geval RLZ dit gedrag ooit herstelt (onschadelijk).
                omschrijving=marker,
            )
        except (RlzApiError, DebiteurAanmakenMislukt) as exc:
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise RlzBoekingMislukt(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — nooit in limbo: zelfde vangnet als inkoop
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        kop = session.get(VerkoopVoorstel, document_id)
        if kop is not None:
            kop.rlz_boekstuknummer = boekstuknummer

        bestaande_registratie = session.scalars(
            select(VerkoopBoeking).where(VerkoopBoeking.document_id == document_id)
        ).first()
        if bestaande_registratie is None:
            session.add(
                VerkoopBoeking(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    factuurnummer=voorstel.factuurnummer,
                    is_creditnota=voorstel.is_creditnota,
                    totaalbedrag_incl=voorstel.totaalbedrag_incl or Decimal(0),
                    debiteur_customer_id=customer_id,
                    debiteur_naam=voorstel.debiteur_naam,
                    verkoop_rlz_id=verkoop_rlz_id,
                    verkoop_invoice_number=invoice_number,
                    verkoop_referentie=referentie,
                    verkoop_boekstuknummer=boekstuknummer,
                    status=VerkoopBoekingStatus.GEBOEKT.value,
                    geboekt_door=actor_id,
                )
            )
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEBOEKT,
            actor_id=actor_id,
            detail={
                "rlz_document_id": str(verkoop_rlz_id),
                "rlz_boekstuknummer": boekstuknummer,
                "soort": "verkoopfactuur",
                "is_creditnota": voorstel.is_creditnota,
            },
        )
        _sla_verkoop_webhook_op(
            session,
            administratie_id=administratie_id,
            rlz_admin_id=rlz_admin_id,
            document_id=document_id,
            voorstel=voorstel,
            customer_id=customer_id,
            rlz_document_id=verkoop_rlz_id,
            rlz_boekstuknummer=boekstuknummer,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="verkoop_boeking",
            record_id=document_id,
            actie="verkoop_geboekt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "rlz_document_id": str(verkoop_rlz_id),
                "rlz_boekstuknummer": boekstuknummer,
                "factuurnummer": voorstel.factuurnummer,
                "is_creditnota": voorstel.is_creditnota,
                "debiteur": voorstel.debiteur_naam,
            },
            administratie_id=administratie_id,
        )

    return VerkoopBoekResultaat(
        document_id=document_id,
        status=DocumentStatus.GEBOEKT,
        verkoop_rlz_id=verkoop_rlz_id,
        verkoop_referentie=referentie,
        verkoop_boekstuknummer=boekstuknummer,
    )
