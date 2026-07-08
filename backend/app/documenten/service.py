from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentBron, DocumentGebeurtenis, DocumentStatus
from app.documenten.statusmachine import valideer_overgang
from app.documenten.storage import DocumentOpslag, LokaleBestandsopslag
from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur

_UBL_SUFFIX = ".xml"


def _standaard_opslag() -> DocumentOpslag:
    return LokaleBestandsopslag(Path(settings.document_opslag_basismap))


def _hash(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


@dataclass(frozen=True)
class UploadResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    mogelijk_duplicaat_van_id: uuid.UUID | None


class DocumentNietGevonden(Exception):
    """Onbekend document, of het bestaat wel maar valt buiten de scope van de huidige sessie —
    RLS maakt dat onderscheid hier bewust niet zichtbaar (geen cross-tenant-signaal via een ander
    foutbeeld dan 'niet gevonden')."""


def _schrijf_overgang(
    session: Session,
    *,
    document: Document,
    naar: DocumentStatus,
    actor_id: uuid.UUID,
    detail: dict | None = None,
) -> None:
    """De ENIGE plek die document.status muteert: valideert eerst tegen de statusmachine
    (app/documenten/statusmachine.py), schrijft dan zowel de append-only tijdlijn
    (document_gebeurtenis) als het platformbrede audit_event, in dezelfde transactie."""
    van = document.status
    valideer_overgang(van, naar)
    document.status = naar
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=van,
            naar_status=naar,
            actor_id=actor_id,
            detail=detail,
        )
    )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="document",
        record_id=document.id,
        actie=f"status_{naar.value}",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"status": van.value},
        nieuwe_waarde={"status": naar.value, **(detail or {})},
        administratie_id=document.administratie_id,
    )


def _start_extractie(session: Session, *, document: Document, actor_id: uuid.UUID, opslag: DocumentOpslag) -> None:
    """Stub: draait synchroon binnen dezelfde transactie als de upload — er is deze fase nog geen
    echte achtergrondtaak/queue (zie de docstring bij DocumentGebeurtenis over de ontbrekende
    systeem-actor voor een latere, écht-asynchrone worker). UBL/XML wordt deterministisch geparst
    naar veldvoorstellen; andere bestandstypen (PDF) krijgen alleen de statusovergang — de
    eigenlijke AI-extractie haakt hier in een fase-vervolg in, zonder dat deze functiesignatuur
    hoeft te veranderen."""
    _schrijf_overgang(session, document=document, naar=DocumentStatus.EXTRACTIE_BEZIG, actor_id=actor_id)

    detail: dict | None = None
    if Path(document.bestandsnaam).suffix.lower() == _UBL_SUFFIX:
        inhoud = opslag.lezen(pad=document.opslag_pad)
        try:
            voorstel = parseer_ubl_factuur(inhoud)
            detail = {"veldvoorstel": voorstel.als_dict()}
        except GeenGeldigeUbl as exc:
            detail = {"ubl_parse_fout": str(exc)}

    _schrijf_overgang(session, document=document, naar=DocumentStatus.TE_CONTROLEREN, actor_id=actor_id, detail=detail)


def upload_document(
    *,
    administratie_id: uuid.UUID,
    bestandsnaam: str,
    inhoud: bytes,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
    bron: DocumentBron = DocumentBron.UPLOAD,
) -> UploadResultaat:
    """Slaat het bestand op, detecteert mogelijke duplicaten (sha256, binnen dezelfde
    administratie) en start meteen de (stub-)extractie. `mogelijk_duplicaat_van_id` is een losse
    vlag op het document — het doorloopt gewoon de normale statusmachine, met dit signaal
    erbovenop voor de controleur (mockup: chip 'Mogelijk duplicaat van ... — beoordelen')."""
    opslag = opslag or _standaard_opslag()
    document_id = uuid.uuid4()
    sha256_hash = _hash(inhoud)

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaand = session.scalars(
            select(Document)
            .where(Document.administratie_id == administratie_id, Document.sha256_hash == sha256_hash)
            .order_by(Document.aangemaakt_op)
        ).first()

        opslag_pad = f"{administratie_id}/{document_id}{Path(bestandsnaam).suffix.lower()}"
        opslag.opslaan(pad=opslag_pad, inhoud=inhoud)

        document = Document(
            id=document_id,
            administratie_id=administratie_id,
            bron=bron,
            bestandsnaam=bestandsnaam,
            sha256_hash=sha256_hash,
            status=DocumentStatus.ONTVANGEN,
            mogelijk_duplicaat_van_id=bestaand.id if bestaand else None,
            opslag_pad=opslag_pad,
        )
        session.add(document)
        session.flush()

        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=None,
                naar_status=DocumentStatus.ONTVANGEN,
                actor_id=actor_id,
                detail={"mogelijk_duplicaat_van": str(bestaand.id)} if bestaand else None,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="document_ontvangen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"bestandsnaam": bestandsnaam, "bron": bron.value},
            administratie_id=administratie_id,
        )

        _start_extractie(session, document=document, actor_id=actor_id, opslag=opslag)

        eind_status = document.status
        mogelijk_duplicaat_van_id = document.mogelijk_duplicaat_van_id

    return UploadResultaat(
        document_id=document_id, status=eind_status, mogelijk_duplicaat_van_id=mogelijk_duplicaat_van_id
    )


def lijst_documenten(*, administratie_id: uuid.UUID) -> list[Document]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(Document)
                .where(Document.administratie_id == administratie_id)
                .order_by(Document.aangemaakt_op.desc())
            )
        )


@dataclass(frozen=True)
class DocumentDetail:
    document: Document
    gebeurtenissen: list[DocumentGebeurtenis]
    veldvoorstel: dict | None


def haal_document_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> DocumentDetail:
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")

        gebeurtenissen = list(
            session.scalars(
                select(DocumentGebeurtenis)
                .where(DocumentGebeurtenis.document_id == document_id)
                .order_by(DocumentGebeurtenis.tijdstip)
            )
        )
        veldvoorstel = next(
            (g.detail["veldvoorstel"] for g in gebeurtenissen if g.detail and "veldvoorstel" in g.detail), None
        )

    return DocumentDetail(document=document, gebeurtenissen=gebeurtenissen, veldvoorstel=veldvoorstel)


def haal_bijlage_op(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, opslag: DocumentOpslag | None = None
) -> tuple[bytes, str, str]:
    """Retourneert (inhoud, bestandsnaam, content_type)."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        opslag_pad = document.opslag_pad
        bestandsnaam = document.bestandsnaam

    inhoud = opslag.lezen(pad=opslag_pad)
    content_type = "application/pdf" if bestandsnaam.lower().endswith(".pdf") else "application/xml"
    return inhoud, bestandsnaam, content_type
