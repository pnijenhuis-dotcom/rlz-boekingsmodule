from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.checks import CheckRapport, CheckRegel, voer_harde_checks_uit
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.documenten.service import DocumentNietGevonden
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

# Zodra het document GEBOEKT is, is het RLZ-boekstuk de bron van waarheid (CLAUDE.md, kernprincipe
# 1) — het boekvoorstel wordt dan bevroren, geen bewerking meer via deze service.
_BEVROREN_STATUSSEN = frozenset({DocumentStatus.GEBOEKT})


class BoekvoorstelFout(Exception):
    """Domeinfout in de boekvoorstel-servicelaag."""


@dataclass(frozen=True)
class BoekvoorstelRegelData:
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    omschrijving: str | None


@dataclass(frozen=True)
class BoekvoorstelData:
    document_id: uuid.UUID
    vendor_id: uuid.UUID | None
    referentie: str | None
    factuurdatum: date | None
    totaalbedrag: Decimal | None
    rlz_boekstuknummer: str | None
    opgeslagen: bool
    regels: list[BoekvoorstelRegelData]


def _als_decimal(waarde: str | None) -> Decimal | None:
    if not waarde:
        return None
    try:
        return Decimal(waarde)
    except InvalidOperation:
        return None


def _als_datum(waarde: str | None) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _raad_vendor_id(session: Session, *, administratie_id: uuid.UUID, leverancier_naam: str | None) -> uuid.UUID | None:
    """Best-effort suggestie op basis van een exacte (case-insensitive) naammatch tegen de
    vendor-cache — alleen bij precies één match, anders geen giswerk (consistent met CLAUDE.md's
    "nooit auto-toewijzen bij twijfel", hier toegepast op de crediteurkeuze i.p.v. de administratie-
    toewijzing)."""
    if not leverancier_naam:
        return None
    kandidaten = session.scalars(
        select(VendorCache).where(
            VendorCache.administratie_id == administratie_id,
            func.lower(VendorCache.naam) == leverancier_naam.strip().lower(),
        )
    ).all()
    if len(kandidaten) == 1:
        return kandidaten[0].id
    return None


def _regel_prefill_uit_ubl(veldvoorstel: dict) -> list[BoekvoorstelRegelData]:
    totaal_excl = _als_decimal(veldvoorstel.get("totaal_excl"))
    totaal_incl = _als_decimal(veldvoorstel.get("totaal_incl"))
    if totaal_excl is None or totaal_incl is None:
        return []
    return [
        BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=None,
            project_id=None,
            netto_bedrag=totaal_excl,
            btw_bedrag=totaal_incl - totaal_excl,
            omschrijving=None,
        )
    ]


def _laad_document(session: Session, *, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    return document


def haal_boekvoorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> BoekvoorstelData:
    """Het opgeslagen boekvoorstel, of — als er nog niets opgeslagen is — een niet-opgeslagen
    voorstel op basis van het UBL-veldvoorstel (CLAUDE.md-taak 2.1: "veldvoorstellen (UBL)
    vooringevuld waar aanwezig"). PDF-documenten hebben geen UBL-veldvoorstel en krijgen dus een
    volledig leeg voorstel — de controleur vult alles handmatig in."""
    with scoped_session(administratie_id) as session:
        _laad_document(session, document_id=document_id)

        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is not None:
            regels = session.scalars(
                select(BoekvoorstelRegel)
                .where(BoekvoorstelRegel.document_id == document_id)
                .order_by(BoekvoorstelRegel.volgnummer)
            ).all()
            return BoekvoorstelData(
                document_id=document_id,
                vendor_id=bestaand.vendor_id,
                referentie=bestaand.referentie,
                factuurdatum=bestaand.factuurdatum,
                totaalbedrag=bestaand.totaalbedrag,
                rlz_boekstuknummer=bestaand.rlz_boekstuknummer,
                opgeslagen=True,
                regels=[
                    BoekvoorstelRegelData(
                        ledger_id=r.ledger_id,
                        taxrate_id=r.taxrate_id,
                        project_id=r.project_id,
                        netto_bedrag=r.netto_bedrag,
                        btw_bedrag=r.btw_bedrag,
                        omschrijving=r.omschrijving,
                    )
                    for r in regels
                ],
            )

        # Geen opgeslagen voorstel: prefill uit het UBL-veldvoorstel, indien aanwezig.
        van_ubl = next(
            (
                g.detail["veldvoorstel"]
                for g in _gebeurtenissen_van(session, document_id)
                if g.detail and "veldvoorstel" in g.detail
            ),
            None,
        )
        if van_ubl is None:
            return BoekvoorstelData(
                document_id=document_id,
                vendor_id=None,
                referentie=None,
                factuurdatum=None,
                totaalbedrag=None,
                rlz_boekstuknummer=None,
                opgeslagen=False,
                regels=[],
            )

        vendor_id = _raad_vendor_id(
            session, administratie_id=administratie_id, leverancier_naam=van_ubl.get("leverancier_naam")
        )
        return BoekvoorstelData(
            document_id=document_id,
            vendor_id=vendor_id,
            referentie=van_ubl.get("factuurnummer"),
            factuurdatum=_als_datum(van_ubl.get("factuurdatum")),
            totaalbedrag=_als_decimal(van_ubl.get("totaal_incl")),
            rlz_boekstuknummer=None,
            opgeslagen=False,
            regels=_regel_prefill_uit_ubl(van_ubl),
        )


def _gebeurtenissen_van(session: Session, document_id: uuid.UUID) -> list[DocumentGebeurtenis]:
    return list(
        session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == document_id)
            .order_by(DocumentGebeurtenis.tijdstip)
        )
    )


def sla_boekvoorstel_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    regels: list[BoekvoorstelRegelData],
) -> BoekvoorstelData:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_document(session, document_id=document_id)
        if document.status in _BEVROREN_STATUSSEN:
            raise BoekvoorstelFout(f"Document {document_id} is al geboekt — het boekvoorstel is bevroren")

        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is None:
            bestaand = Boekvoorstel(document_id=document_id)
            session.add(bestaand)
        bestaand.vendor_id = vendor_id
        bestaand.referentie = referentie
        bestaand.factuurdatum = factuurdatum
        bestaand.totaalbedrag = totaalbedrag

        session.execute(delete(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
        for i, regel in enumerate(regels, start=1):
            session.add(
                BoekvoorstelRegel(
                    document_id=document_id,
                    volgnummer=i,
                    ledger_id=regel.ledger_id,
                    taxrate_id=regel.taxrate_id,
                    project_id=regel.project_id,
                    netto_bedrag=regel.netto_bedrag,
                    btw_bedrag=regel.btw_bedrag,
                    omschrijving=regel.omschrijving,
                )
            )

        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boekvoorstel",
            record_id=document_id,
            actie="boekvoorstel_opgeslagen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"referentie": referentie, "aantal_regels": len(regels)},
            administratie_id=administratie_id,
        )

    return haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def voer_checks_uit(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, client: RlzClient | None = None
) -> CheckRapport:
    """Herleest het OPGESLAGEN boekvoorstel (nooit het niet-opgeslagen UBL-voorstel — de checks
    gelden over wat de controleur daadwerkelijk heeft bevestigd) en toetst de drie harde checks
    (app/documenten/checks.py). `client=None` opent een eigen RlzClient voor deze administratie
    (store/`.env`-credential-resolutie, zie app/rlz/credentials.py) — een aanroeper met een al
    open verbinding (bv. de boek-actie zelf) geeft 'm door om niet twee keer in te loggen."""
    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)

    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    try:
        return voer_harde_checks_uit(
            client=client,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=[
                CheckRegel(
                    ledger_id=r.ledger_id, taxrate_id=r.taxrate_id, netto_bedrag=r.netto_bedrag, btw_bedrag=r.btw_bedrag
                )
                for r in voorstel.regels
            ],
            eigen_rlz_document_id=rlz_purchase_invoice_id(document_id),
        )
    finally:
        if eigen_client:
            client.close()
