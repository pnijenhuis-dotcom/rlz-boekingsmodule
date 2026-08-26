"""Nazorg blok A (26-08): `make doorbelasting-facturen-herstel` — voor bestaande GEBOEKTE
(en spiegel-open) doorbelastingen zónder factuur-PDF alsnog RLZ's factuur renderen, toetsen en
als bijlage op beide kanten zetten. GÉÉN herboeking: alleen bijlagen + de factuur-kolommen op de
boeking. Dry-run eerst (telt en toont kandidaten, raakt niets); per run geauditeerd
(`doorbelasting_factuur_hersteld` / `doorbelasting_factuur_herstel_mislukt`). Een fout per
boeking stopt de rest niet — alles zichtbaar in het rapport."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_doorbelasting_factuur_upload_id
from app.documenten.service import _standaard_opslag
from app.doorbelasting import factuur as factuur_pdf
from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus, DoorbelastingMapping
from app.rlz.client import RlzClient
from app.rlz.credentials import GeenRlzCredentials

logger = logging.getLogger(__name__)
_MODULE = "boekhouding"

HERSTELBARE_STATUSSEN = (DoorbelastingBoekingStatus.GEBOEKT.value, DoorbelastingBoekingStatus.SPIEGEL_OPEN.value)


@dataclass(frozen=True)
class HerstelKandidaat:
    administratie_id: uuid.UUID
    administratie_naam: str
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    doelentiteit_naam: str
    verkoop_referentie: str | None
    status: str
    huidige_factuur_status: str | None


@dataclass
class HerstelResultaat:
    dry_run: bool
    kandidaten: list[HerstelKandidaat] = field(default_factory=list)
    hersteld: list[uuid.UUID] = field(default_factory=list)
    mislukt: dict[uuid.UUID, str] = field(default_factory=dict)


def _kandidaten() -> list[HerstelKandidaat]:
    with scoped_session(None) as session:
        administraties = {a.id: a.naam for a in session.scalars(select(Administratie).where(Administratie.actief.is_(True)))}
    kandidaten: list[HerstelKandidaat] = []
    for administratie_id, naam in sorted(administraties.items(), key=lambda kv: kv[1]):
        with scoped_session(administratie_id) as session:
            rijen = session.scalars(
                select(DoorbelastingBoeking)
                .where(
                    DoorbelastingBoeking.administratie_id == administratie_id,
                    DoorbelastingBoeking.status.in_(HERSTELBARE_STATUSSEN),
                    (DoorbelastingBoeking.factuur_pdf_status.is_(None))
                    | (DoorbelastingBoeking.factuur_pdf_status == factuur_pdf.FACTUUR_STATUS_ONTBREEKT),
                )
                .order_by(DoorbelastingBoeking.aangemaakt_op)
            ).all()
            for b in rijen:
                mapping = session.get(DoorbelastingMapping, b.mapping_id)
                kandidaten.append(
                    HerstelKandidaat(
                        administratie_id=administratie_id,
                        administratie_naam=naam,
                        boeking_id=b.id,
                        document_id=b.document_id,
                        doelentiteit_naam=mapping.doelentiteit_naam if mapping else "?",
                        verkoop_referentie=b.verkoop_referentie,
                        status=b.status,
                        huidige_factuur_status=b.factuur_pdf_status,
                    )
                )
    return kandidaten


def _herstel_een(
    kandidaat: HerstelKandidaat,
    *,
    actor_id: uuid.UUID,
    client_factory: Callable[[uuid.UUID], RlzClient],
) -> None:
    with scoped_session(kandidaat.administratie_id) as session:
        boeking = session.get(DoorbelastingBoeking, kandidaat.boeking_id)
        mapping = session.get(DoorbelastingMapping, boeking.mapping_id)
        verwachting = factuur_pdf.FactuurVerwachting(
            referentie=boeking.verkoop_referentie or f"DOORB-{boeking.verkoop_invoice_number}",
            netto_totaal=boeking.netto_totaal,
            provisie=boeking.provisie_bedrag,
            btw_totaal=boeking.btw_bedrag,
        )
        verkoop_rlz_id, spiegel_rlz_id = boeking.verkoop_rlz_id, boeking.spiegel_rlz_id
        document_id, mapping_id = boeking.document_id, boeking.mapping_id
        doel_customer_guid = mapping.doel_customer_guid
        doelentiteit_naam = mapping.doelentiteit_naam
        doel_administratie_id = boeking.doel_administratie_id if boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value else None

    naam = factuur_pdf.factuur_bestandsnaam(verwachting.referentie, doelentiteit_naam)
    fouten: list[str] = []
    bron_client = client_factory(kandidaat.administratie_id)
    try:
        pdf, reden = factuur_pdf.haal_en_controleer_factuur(bron_client, verkoop_rlz_id=verkoop_rlz_id, verwachting=verwachting)
        if pdf is None:
            raise factuur_pdf.FactuurNietBeschikbaar(reden or "factuur-PDF ontbreekt")
        fout = factuur_pdf.voeg_factuur_als_bijlage_toe(
            bron_client,
            "SalesInvoices",
            verkoop_rlz_id,
            upload_id=rlz_doorbelasting_factuur_upload_id(document_id, doel_customer_guid, kant="verkoop"),
            bestandsnaam=naam,
            pdf=pdf,
        )
        if fout:
            fouten.append(f"bron: {fout}")
    finally:
        bron_client.close()

    if doel_administratie_id is not None:
        doel_client = client_factory(doel_administratie_id)
        try:
            fout = factuur_pdf.voeg_factuur_als_bijlage_toe(
                doel_client,
                "PurchaseInvoices",
                spiegel_rlz_id,
                upload_id=rlz_doorbelasting_factuur_upload_id(document_id, doel_customer_guid, kant="spiegel"),
                bestandsnaam=naam,
                pdf=pdf,
            )
            if fout:
                fouten.append(f"spiegel: {fout}")
        finally:
            doel_client.close()

    pad = factuur_pdf.factuur_opslag_pad(
        administratie_id=kandidaat.administratie_id, document_id=document_id, mapping_id=mapping_id
    )
    _standaard_opslag().opslaan(pad=pad, inhoud=pdf)
    if fouten:
        raise factuur_pdf.FactuurNietBeschikbaar("; ".join(fouten))

    with scoped_session(kandidaat.administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, kandidaat.boeking_id)
        oud = {"factuur_pdf_status": boeking.factuur_pdf_status, "factuur_pdf_reden": boeking.factuur_pdf_reden}
        boeking.factuur_pdf_status = factuur_pdf.FACTUUR_STATUS_AANWEZIG
        boeking.factuur_pdf_reden = None
        boeking.factuur_pdf_bestandsnaam = naam
        boeking.factuur_pdf_opslag_pad = pad
        boeking.factuur_pdf_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_boeking",
            record_id=boeking.id,
            actie="doorbelasting_factuur_hersteld",
            correlatie_id=boeking.document_id,
            oude_waarde=oud,
            nieuwe_waarde={"factuur_pdf_status": boeking.factuur_pdf_status, "bestandsnaam": naam, "pdf": pad},
            administratie_id=kandidaat.administratie_id,
        )


def _registreer_mislukt(kandidaat: HerstelKandidaat, *, actor_id: uuid.UUID, reden: str) -> None:
    with scoped_session(kandidaat.administratie_id, actor_id=actor_id) as session:
        boeking = session.get(DoorbelastingBoeking, kandidaat.boeking_id)
        oud = {"factuur_pdf_status": boeking.factuur_pdf_status, "factuur_pdf_reden": boeking.factuur_pdf_reden}
        boeking.factuur_pdf_status = factuur_pdf.FACTUUR_STATUS_ONTBREEKT
        boeking.factuur_pdf_reden = reden[:1000]
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="doorbelasting_boeking",
            record_id=boeking.id,
            actie="doorbelasting_factuur_herstel_mislukt",
            correlatie_id=boeking.document_id,
            oude_waarde=oud,
            nieuwe_waarde={"factuur_pdf_status": boeking.factuur_pdf_status, "reden": boeking.factuur_pdf_reden},
            administratie_id=kandidaat.administratie_id,
        )


def herstel_facturen(
    *,
    dry_run: bool,
    actor_id: uuid.UUID,
    client_factory: Callable[[uuid.UUID], RlzClient] | None = None,
) -> HerstelResultaat:
    """Alle kandidaten (GEBOEKT/spiegel_open zonder factuur) langs. `dry_run=True` = alleen
    tellen/tonen. `client_factory` is de test-seam (administratie_id → RlzClient), default de
    credential-store-client van de motor."""
    resultaat = HerstelResultaat(dry_run=dry_run, kandidaten=_kandidaten())
    if dry_run:
        return resultaat
    if client_factory is None:
        from app.documenten.boeken import _rlz_client_voor

        client_factory = _rlz_client_voor
    for kandidaat in resultaat.kandidaten:
        try:
            _herstel_een(kandidaat, actor_id=actor_id, client_factory=client_factory)
            resultaat.hersteld.append(kandidaat.boeking_id)
        except (factuur_pdf.FactuurNietBeschikbaar, GeenRlzCredentials) as exc:
            resultaat.mislukt[kandidaat.boeking_id] = str(exc)
            _registreer_mislukt(kandidaat, actor_id=actor_id, reden=str(exc))
        except Exception as exc:  # noqa: BLE001 — nazorgrun: doorgaan, fout zichtbaar + geauditeerd
            logger.exception("Factuur-herstel faalde voor boeking %s", kandidaat.boeking_id)
            reden = f"{exc.__class__.__name__}: {str(exc)[:300]}"
            resultaat.mislukt[kandidaat.boeking_id] = reden
            _registreer_mislukt(kandidaat, actor_id=actor_id, reden=reden)
    return resultaat
