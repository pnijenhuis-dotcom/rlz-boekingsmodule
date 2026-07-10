from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentBron, DocumentGebeurtenis, DocumentStatus
from app.documenten.statusmachine import OngeldigeStatusovergang, valideer_overgang
from app.documenten.storage import DocumentOpslag, LokaleBestandsopslag
from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur
from app.extractie import controle as extractie_controle
from app.extractie import service as extractie_service
from app.sync.models import TaxRateCache, VendorCache

logger = logging.getLogger(__name__)

_UBL_SUFFIX = ".xml"
_PDF_SUFFIX = ".pdf"


def _standaard_opslag() -> DocumentOpslag:
    return LokaleBestandsopslag(Path(settings.document_opslag_basismap))


def _hash(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


@dataclass(frozen=True)
class DuplicaatReferentie:
    """Genoeg om in de UI een klikbare link te tonen (design-pass taak 5) — nooit een kale UUID:
    bestandsnaam + uploaddatum van het vermoedelijke origineel."""

    document_id: uuid.UUID
    bestandsnaam: str
    aangemaakt_op: datetime


def _duplicaat_referenties_op(session: Session, document_ids: set[uuid.UUID]) -> dict[uuid.UUID, DuplicaatReferentie]:
    """Eén query voor alle duplicaat-verwijzingen in een lijst/detail-response i.p.v. per document
    een losse lookup."""
    if not document_ids:
        return {}
    rijen = session.execute(
        select(Document.id, Document.bestandsnaam, Document.aangemaakt_op).where(Document.id.in_(document_ids))
    ).all()
    return {
        rij.id: DuplicaatReferentie(document_id=rij.id, bestandsnaam=rij.bestandsnaam, aangemaakt_op=rij.aangemaakt_op)
        for rij in rijen
    }


@dataclass(frozen=True)
class UploadResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    mogelijk_duplicaat_van_id: uuid.UUID | None
    mogelijk_duplicaat_van: DuplicaatReferentie | None


class DocumentNietGevonden(Exception):
    """Onbekend document, of het bestaat wel maar valt buiten de scope van de huidige sessie —
    RLS maakt dat onderscheid hier bewust niet zichtbaar (geen cross-tenant-signaal via een ander
    foutbeeld dan 'niet gevonden')."""


class VerwijderenNietToegestaan(Exception):
    """Design-pass taak 4: blokkerende regel bij het verwijderen — in de praktijk altijd omdat
    het document al geboekt is (bewaarplicht). De statusmachine blokkeert dit zelf al (GEBOEKT
    heeft geen uitgaande overgangen), maar deze klasse geeft er een specifieke, uitlegbare fout
    voor i.p.v. de generieke OngeldigeStatusovergang-tekst."""


class DocumentNietVerwijderd(Exception):
    """Herstellen kan alleen een document dat daadwerkelijk op status verwijderd staat."""


class HerextractieNietToegestaan(Exception):
    """Opnieuw extraheren kan alleen voor een PDF die op te_controleren staat — de status waar
    een (mislukte) extractie het document achterlaat. Alles daarna is mensenwerk."""


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
    """Draait synchroon binnen dezelfde transactie als de upload (paar seconden voor de AI-route
    — bewust: een échte async-worker + systeem-actor is uitgesteld, zie docs/BOUWPLAN.md en de
    docstring bij DocumentGebeurtenis). UBL/XML blijft de deterministische bron en gaat NOOIT
    naar de AI; PDF's gaan via de Claude-route (app/extractie/), mits de AVG-gate van de
    administratie aan staat. Elke uitkomst — voorstel, overgeslagen, fout — komt herkenbaar in de
    tijdlijn terecht; een AI-fout laat de upload nooit falen ("niets verdwijnt stil", maar ook:
    de mens kan altijd handmatig verder)."""
    _schrijf_overgang(session, document=document, naar=DocumentStatus.EXTRACTIE_BEZIG, actor_id=actor_id)

    detail: dict | None = None
    doel_status = DocumentStatus.TE_CONTROLEREN
    suffix = Path(document.bestandsnaam).suffix.lower()
    if suffix == _UBL_SUFFIX:
        inhoud = opslag.lezen(pad=document.opslag_pad)
        try:
            voorstel = parseer_ubl_factuur(inhoud)
            detail = {"veldvoorstel": voorstel.als_dict()}
        except GeenGeldigeUbl as exc:
            detail = {"ubl_parse_fout": str(exc)}
    elif suffix == _PDF_SUFFIX:
        detail, blokkeer = _ai_extractie_detail(session, document=document, opslag=opslag)
        if blokkeer:
            # Waarborg projectadministratie (migratie 0015): regelset niet aantoonbaar compleet
            # bij projectplicht — blokkerende status, bewust GEEN (totalen-only) voorstel.
            doel_status = DocumentStatus.HANDMATIG_AFMAKEN

    _schrijf_overgang(session, document=document, naar=doel_status, actor_id=actor_id, detail=detail)


def _ai_extractie_detail(session: Session, *, document: Document, opslag: DocumentOpslag) -> tuple[dict, bool]:
    """AI-route voor PDF's: AVG-gate → Claude-extractie (adaptieve chunking bij afkap) →
    deterministische controlelaag. De AI levert uitsluitend een voorstel (veld-suggesties met
    zekerheidsscores); boeken blijft altijd een menselijke actie via het controlescherm + harde
    checks. Vendor-/btw-suggesties komen alléén uit de eigen sync-caches, nooit uit de AI zelf.

    Retourneert (tijdlijn-detail, blokkeer): blokkeer=True is de harde waarborg voor
    projectadministraties — de regelset is niet aantoonbaar compleet en er wordt géén voorstel
    opgeslagen dat regeldetail/projecttoerekening zou laten wegvallen; het document eindigt op
    handmatig_afmaken (de aanroeper zet die status)."""
    if document.administratie_id is None:
        return {"ai_extractie_overgeslagen": "geen_administratie"}, False
    administratie = session.get(Administratie, document.administratie_id)
    if administratie is None or not administratie.ai_extractie_ingeschakeld:
        # AVG-gate (migratie 0014): default UIT — dit document gaat niet naar de Claude API.
        return {"ai_extractie_overgeslagen": "ai_extractie_uitgeschakeld"}, False
    if not settings.anthropic_api_key:
        return {"ai_extractie_overgeslagen": "geen_api_key"}, False

    inhoud = opslag.lezen(pad=document.opslag_pad)
    try:
        extractie = extractie_service.extraheer_inkoopfactuur(inhoud)
    except Exception as exc:  # noqa: BLE001 — bewust breed: een AI-fout mag de upload nooit laten falen
        logger.exception("AI-extractie mislukt voor document %s", document.id)
        return {"ai_extractie_fout": str(exc)}, False

    metriek = {
        **(extractie.metriek.als_dict() if extractie.metriek else {}),
        "regels": len(extractie.regels),
    }

    if not extractie.volledig and administratie.project_verplicht:
        # Waarborg projectadministratie: hier eindigt de AI-route hard — geen voorstel, wel een
        # uitlegbare melding + metriek in de tijdlijn (audit loopt mee via de statusovergang).
        logger.warning(
            "AI-extractie onvolledig voor document %s bij projectplicht-administratie %s — handmatig afmaken",
            document.id,
            document.administratie_id,
        )
        return {
            "ai_extractie_onvolledig": (
                "De AI-extractie kreeg de factuurregels niet aantoonbaar compleet (ook niet in "
                "delen). Deze administratie vereist projecttoerekening per regel — het voorstel is "
                "daarom niet overgenomen. Vul de boekingsregels handmatig in of probeer de "
                "extractie opnieuw."
            ),
            "ai_metriek": metriek,
        }, True

    vendors = [
        extractie_controle.VendorKandidaat(id=rij.id, naam=rij.naam or "")
        for rij in session.scalars(
            select(VendorCache).where(
                VendorCache.administratie_id == document.administratie_id,
                VendorCache.verdwenen_uit_bron_op.is_(None),
                VendorCache.is_gearchiveerd.isnot(True),
            )
        )
    ]
    taxrates = [
        extractie_controle.TaxRateKandidaat(id=rij.id, percentage=rij.percentage)
        for rij in session.scalars(
            select(TaxRateCache).where(
                TaxRateCache.administratie_id == document.administratie_id,
                TaxRateCache.verdwenen_uit_bron_op.is_(None),
            )
        )
    ]
    voorstel = extractie_controle.bouw_veldvoorstel(
        extractie,
        vendors=vendors,
        taxrates=taxrates,
        zekerheid_drempel=settings.ai_extractie_zekerheid_drempel,
    )
    return {"veldvoorstel": voorstel, "ai_metriek": metriek}, False


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
        mogelijk_duplicaat_van = (
            DuplicaatReferentie(
                document_id=bestaand.id, bestandsnaam=bestaand.bestandsnaam, aangemaakt_op=bestaand.aangemaakt_op
            )
            if bestaand
            else None
        )

    return UploadResultaat(
        document_id=document_id,
        status=eind_status,
        mogelijk_duplicaat_van_id=mogelijk_duplicaat_van_id,
        mogelijk_duplicaat_van=mogelijk_duplicaat_van,
    )


@dataclass(frozen=True)
class DocumentMetDuplicaat:
    document: Document
    duplicaat_referentie: DuplicaatReferentie | None


def lijst_documenten(*, administratie_id: uuid.UUID, toon_verwijderd: bool = False) -> list[DocumentMetDuplicaat]:
    """`toon_verwijderd=False` (default) verbergt zachtgewiste documenten uit de normale
    werkvoorraad — de "toon verwijderde"-filter (design-pass taak 4) zet dit aan om ze er weer
    naast te zien (voor het herstelpad), nooit een apart, exclusief lijstje."""
    with scoped_session(administratie_id) as session:
        voorwaarden = [Document.administratie_id == administratie_id]
        if not toon_verwijderd:
            voorwaarden.append(Document.status != DocumentStatus.VERWIJDERD)
        documenten = list(
            session.scalars(select(Document).where(*voorwaarden).order_by(Document.aangemaakt_op.desc()))
        )
        referenties = _duplicaat_referenties_op(
            session, {d.mogelijk_duplicaat_van_id for d in documenten if d.mogelijk_duplicaat_van_id}
        )
        return [
            DocumentMetDuplicaat(
                document=d,
                duplicaat_referentie=referenties.get(d.mogelijk_duplicaat_van_id)
                if d.mogelijk_duplicaat_van_id
                else None,
            )
            for d in documenten
        ]


@dataclass(frozen=True)
class DocumentDetail:
    document: Document
    gebeurtenissen: list[DocumentGebeurtenis]
    veldvoorstel: dict | None
    duplicaat_referentie: DuplicaatReferentie | None


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
        # Nieuwste voorstel wint: na "opnieuw extraheren" kunnen er meerdere veldvoorstel-
        # gebeurtenissen in de tijdlijn staan — de laatste extractie is de actuele.
        veldvoorstel = next(
            (g.detail["veldvoorstel"] for g in reversed(gebeurtenissen) if g.detail and "veldvoorstel" in g.detail),
            None,
        )
        duplicaat_referentie = (
            _duplicaat_referenties_op(session, {document.mogelijk_duplicaat_van_id}).get(
                document.mogelijk_duplicaat_van_id
            )
            if document.mogelijk_duplicaat_van_id
            else None
        )

    return DocumentDetail(
        document=document,
        gebeurtenissen=gebeurtenissen,
        veldvoorstel=veldvoorstel,
        duplicaat_referentie=duplicaat_referentie,
    )


def verwijder_document(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str | None = None
) -> DocumentStatus:
    """Soft-delete (design-pass taak 4): status -> verwijderd, bestand en record blijven bestaan.
    Bewaart de status van vóór de verwijdering in de tijdlijn (`detail.vorige_status`) — dat is
    waar herstel_document() naar teruggaat. Reden is optioneel, maar staat áltijd (ook als None)
    in de tijdlijn/audit_event, net als bij een reguliere overgang."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status == DocumentStatus.GEBOEKT:
            raise VerwijderenNietToegestaan("Geboekte documenten kunnen niet verwijderd worden (bewaarplicht).")

        vorige_status = document.status
        try:
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.VERWIJDERD,
                actor_id=actor_id,
                detail={"reden": reden, "vorige_status": vorige_status.value},
            )
        except OngeldigeStatusovergang as exc:
            raise VerwijderenNietToegestaan(str(exc)) from exc
        return document.status


def herstel_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> DocumentStatus:
    """Zet een zachtgewist document terug op de status van vóór de verwijdering (uit de tijdlijn,
    `detail.vorige_status` — zie verwijder_document) — nooit een vast startpunt (bv. altijd
    te_controleren), anders verliest een herstel van bv. boeken_mislukt zijn context."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status != DocumentStatus.VERWIJDERD:
            raise DocumentNietVerwijderd(f"Document staat niet op verwijderd (status: {document.status.value})")

        laatste_verwijdering = session.scalars(
            select(DocumentGebeurtenis)
            .where(
                DocumentGebeurtenis.document_id == document_id,
                DocumentGebeurtenis.naar_status == DocumentStatus.VERWIJDERD,
            )
            .order_by(DocumentGebeurtenis.tijdstip.desc())
        ).first()
        if (
            laatste_verwijdering is None
            or not laatste_verwijdering.detail
            or "vorige_status" not in laatste_verwijdering.detail
        ):
            raise DocumentNietVerwijderd("Kan de vorige status niet terugvinden in de tijdlijn")

        vorige_status = DocumentStatus(laatste_verwijdering.detail["vorige_status"])
        _schrijf_overgang(
            session, document=document, naar=vorige_status, actor_id=actor_id, detail={"herstel_van": "verwijderd"}
        )
        return document.status


def herextraheer_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
) -> DocumentStatus:
    """"Opnieuw extraheren" (timeout-fix 2026-07-10): een transiënte AI-fout (timeout, 529) laat
    het document met een lege prefill op te_controleren achter — deze actie draait de extractie
    opnieuw zonder her-upload. Zelfde route als de upload (_start_extractie): statusovergangen
    te_controleren -> extractie_bezig -> te_controleren, met tijdlijn + audit_event per stap;
    ook de AVG-gate en de key-check gelden onverkort opnieuw. Alleen voor PDF's (UBL is
    deterministisch — opnieuw parsen levert per definitie hetzelfde op) en alleen vanaf
    te_controleren of handmatig_afmaken (daarna is het voorstel mensenwerk)."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if Path(document.bestandsnaam).suffix.lower() != _PDF_SUFFIX:
            raise HerextractieNietToegestaan("Opnieuw extraheren kan alleen voor PDF's (UBL is deterministisch).")
        if document.status not in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN):
            raise HerextractieNietToegestaan(
                "Opnieuw extraheren kan alleen vanaf te_controleren of handmatig_afmaken "
                f"(status: {document.status.value})."
            )
        _start_extractie(session, document=document, actor_id=actor_id, opslag=opslag)
        return document.status


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
