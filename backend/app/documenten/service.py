from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.aikosten.service import AiKostenLimietBereikt, AiVerbruikReferentie
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import storage
from app.documenten.beeld import BestandenSnapshot, beeld_is_bron, bepaal_beeld
from app.documenten.mime import content_type_voor
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentBron,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    DuplicaatSignaal,
    DuplicaatSignaalUitkomst,
    Vraag,
    VraagStatus,
)
from app.documenten.pdf import tel_paginas
from app.documenten.statusmachine import OngeldigeStatusovergang, valideer_overgang
from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur
from app.documenten.wachtrij import (
    CloudRunJobExtractieWachtrij,
    DirecteExtractieWachtrij,
    ExtractieWachtrij,
    InProcessExtractieWachtrij,
)
from app.extractie import controle as extractie_controle
from app.extractie import service as extractie_service
from app.extractie import template_service
from app.sync.btw import taxrate_vlaggen
from app.sync.models import TaxRateCache, VendorCache

logger = logging.getLogger(__name__)

_UBL_SUFFIX = ".xml"
_PDF_SUFFIX = ".pdf"


def _standaard_opslag() -> DocumentOpslag:
    # Config-gedreven (GCS in productie, bestandssysteem in dev) — zie storage.standaard_opslag.
    return storage.standaard_opslag()


# Procesbrede default-wachtrij, lazy aangemaakt (na de eerste grote upload) — tests injecteren
# hun eigen instantie via de `wachtrij`-parameter op upload/herextractie en raken deze nooit.
_wachtrij: ExtractieWachtrij | None = None


def _standaard_wachtrij() -> ExtractieWachtrij:
    """Dev: in-process threadpool. Cloud (settings.extractie_wachtrij_job_resource gezet): elke
    enqueue triggert de on-demand job rlz-extractie-wachtrij — zie wachtrij.py (punt 4, 26-08)."""
    global _wachtrij
    if _wachtrij is None:
        if settings.extractie_wachtrij_job_resource:
            _wachtrij = CloudRunJobExtractieWachtrij(job_resource=settings.extractie_wachtrij_job_resource)
        else:
            _wachtrij = InProcessExtractieWachtrij(taak=verwerk_extractie_taak)
    return _wachtrij


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


class SysteemOvergangZonderReden(ValueError):
    """Bugfix-run 28-08 (kernprincipe 4 "niets verdwijnt stil"): een statusovergang door de
    systeem-actor (⚙) zónder leesbare `reden` in het detail. In dev/test een harde fout (vangnet
    `tests/documenten/test_systeem_overgang_reden.py`); in productie wordt de overgang wél
    geschreven — mét een placeholder-reden en een ERROR in de server-log — zodat een gemiste
    aanroepplek nooit een boeking of statuswijziging blokkeert, maar ook nooit onzichtbaar blijft."""


SYSTEEM_REDEN_ONTBREEKT = "systeemovergang zonder opgegeven reden (defect — zie server-log)"


def _borg_systeem_reden(
    *, actor_id: uuid.UUID, document_id: uuid.UUID, van: DocumentStatus, naar: DocumentStatus, detail: dict | None
) -> dict | None:
    if actor_id != SYSTEEM_ACTOR_ID:
        return detail
    reden = (detail or {}).get("reden")
    if isinstance(reden, str) and reden.strip():
        return detail
    melding = (
        f"Systeem-statusovergang {van.value} -> {naar.value} zonder reden (document {document_id}, detail {detail!r})"
    )
    if settings.environment != "production":
        raise SysteemOvergangZonderReden(melding)
    logger.error(melding)
    return {**(detail or {}), "reden": SYSTEEM_REDEN_ONTBREEKT}


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
    (document_gebeurtenis) als het platformbrede audit_event, in dezelfde transactie.

    Systeem-actor (bugfix-run 28-08): élke ⚙-overgang draagt een leesbare `detail["reden"]` —
    de tijdlijn toont die regel generiek. Zie `_borg_systeem_reden`."""
    van = document.status
    valideer_overgang(van, naar)
    detail = _borg_systeem_reden(actor_id=actor_id, document_id=document.id, van=van, naar=naar, detail=detail)
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
    """Synchrone extractieroute (kleine documenten — de snelle happy-path binnen de
    upload-/herextractie-request; grote documenten gaan via de wachtrij, zie
    verwerk_extractie_taak). UBL/XML blijft de deterministische bron en gaat NOOIT naar de AI;
    PDF's gaan via de Claude-route (app/extractie/), mits de AVG-gate van de administratie aan
    staat. Elke uitkomst — voorstel, overgeslagen, fout — komt herkenbaar in de tijdlijn terecht;
    een AI-fout laat de upload nooit falen ("niets verdwijnt stil", maar ook: de mens kan altijd
    handmatig verder)."""
    _schrijf_overgang(
        session,
        document=document,
        naar=DocumentStatus.EXTRACTIE_BEZIG,
        actor_id=actor_id,
        detail={"reden": "extractie gestart"},
    )
    _rond_extractie_af(session, document=document, actor_id=actor_id, opslag=opslag)


def _rond_extractie_af(session: Session, *, document: Document, actor_id: uuid.UUID, opslag: DocumentOpslag) -> None:
    """Tweede helft van elke extractie (synchroon én worker): bepaal het veldvoorstel/detail en
    schrijf de eindovergang vanaf extractie_bezig."""
    detail: dict | None = None
    doel_status = DocumentStatus.TE_CONTROLEREN
    suffix = Path(document.bestandsnaam).suffix.lower()
    if document.soort == DocumentSoort.KASSARAPPORT.value:
        # Omzetmodule (fase 2): kassarapporten krijgen de rapport-extractie
        # (app/extractie/rapport.py) — zelfde AVG-gate, eigen schema/controlelaag; de
        # projectplicht-waarborg is hier niet van toepassing (geen regels met projecttoerekening).
        detail = _rapport_extractie_detail(session, document=document, opslag=opslag)
    elif document.soort == DocumentSoort.WAARBORG.value:
        # §2d-waarborgroute (v1.11): het bericht is deterministische XML — de velden komen als
        # veldvoorstel in de tijdlijn (zoeken/archief), de werkstaat leeft in waarborg_bericht.
        from app.documenten.waarborg_xml import OngeldigWaarborgBericht, parseer_waarborg_bericht

        inhoud = opslag.lezen(pad=document.opslag_pad)
        try:
            bericht = parseer_waarborg_bericht(inhoud)
            detail = {
                "veldvoorstel": {
                    "waarborg_bericht_id": str(bericht.bericht_id) if bericht.bericht_id else None,
                    "verhuurder_entiteit": bericht.verhuurder_entiteit,
                    "contract_referentie": bericht.contract_referentie,
                    "huurder": bericht.huurder,
                    "bedrag": str(bericht.bedrag) if bericht.bedrag is not None else None,
                    "richting": bericht.richting,
                    "datum": bericht.datum.isoformat() if bericht.datum else None,
                    "balans_gb_code": bericht.balans_gb_code,
                }
            }
        except OngeldigWaarborgBericht as exc:
            detail = {"waarborg_parse_fout": str(exc)}
    elif suffix == _UBL_SUFFIX:
        inhoud = opslag.lezen(pad=document.opslag_pad)
        try:
            voorstel = parseer_ubl_factuur(inhoud)
            detail = {"veldvoorstel": voorstel.als_dict()}
        except GeenGeldigeUbl as exc:
            detail = {"ubl_parse_fout": str(exc)}
    elif suffix == _PDF_SUFFIX:
        detail, blokkeer = _pdf_extractie_detail(session, document=document, opslag=opslag)
        if blokkeer:
            # Waarborg projectadministratie (migratie 0015): regelset niet aantoonbaar compleet
            # bij projectplicht — blokkerende status, bewust GEEN (totalen-only) voorstel.
            doel_status = DocumentStatus.HANDMATIG_AFMAKEN

    if actor_id == SYSTEEM_ACTOR_ID:
        detail = {**(detail or {}), "reden": _extractie_reden(detail, doel_status)}
    _schrijf_overgang(session, document=document, naar=doel_status, actor_id=actor_id, detail=detail)
    _herstel_open_vraag_na_extractie(session, document=document, actor_id=actor_id)


def _extractie_reden(detail: dict | None, doel_status: DocumentStatus) -> str:
    """Leesbare reden voor de systeem-eindovergang van een extractie (vangnet 28-08)."""
    d = detail or {}
    if d.get("extractie_bron") == "template":
        return "extractie afgerond via template van de leverancier (deterministisch, geen AI) — ter controle"
    if "ai_extractie_overgeslagen" in d:
        return f"extractie overgeslagen: {d['ai_extractie_overgeslagen']}"
    if "ai_extractie_onvolledig" in d:
        return "extractie afgerond — regelset niet aantoonbaar compleet, handmatig afmaken"
    if "ubl_parse_fout" in d:
        return "UBL onleesbaar — handmatig invullen"
    if "waarborg_parse_fout" in d:
        return "waarborgbericht onleesbaar — handmatig beoordelen"
    if doel_status == DocumentStatus.HANDMATIG_AFMAKEN:
        return "extractie afgerond — handmatig afmaken vereist"
    return "extractie afgerond — ter controle"


def _herstel_open_vraag_na_extractie(session: Session, *, document: Document, actor_id: uuid.UUID) -> None:
    """Verplaatsen naar een andere administratie (27-08 punt 5): een open vraag verhuist mee, maar de
    her-extractie in het doel zet het document eerst op te_controleren/handmatig_afmaken. Zonder
    deze stap zou de vraag niet meer blokkeren (boeken toetst op de documentstatus). Daarom: staat er
    ná de eindovergang nog een open vraag, dan gaat het document direct weer op vraag_open, mét de
    verse herkomst als terugweg (vraag.status_voor_vraag) en een eigen tijdlijnregel. In elke andere
    flow bestaat er op dit moment geen open vraag (vraag_open is dan de documentstatus zelf) — dan
    is dit een no-op."""
    if document.status not in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN):
        return
    open_vraag = session.scalars(
        select(Vraag).where(Vraag.document_id == document.id, Vraag.status == VraagStatus.OPEN.value)
    ).first()
    if open_vraag is None:
        return
    open_vraag.status_voor_vraag = document.status.value
    _schrijf_overgang(
        session,
        document=document,
        naar=DocumentStatus.VRAAG_OPEN,
        actor_id=actor_id,
        detail={
            "vraag_id": str(open_vraag.id),
            "vraag_hersteld_na_extractie": True,
            "reden": "open vraag blokkeert boeken weer ná de nieuwe extractie",
        },
    )
    document.toegewezen_aan = open_vraag.aan_de_beurt or open_vraag.toegewezen_aan


def _groot_document_detail(session: Session, *, document: Document, inhoud: bytes) -> dict | None:
    """Klein-vs-groot-routing (async extractie, 2026-07-10): geeft het tijdlijn-detail voor de
    wachtrij-overgang als dit document de async-route in moet, anders None (synchroon, zoals
    altijd). Alleen PDF's die daadwerkelijk de AI-route in gaan (AVG-gate aan + key aanwezig)
    tellen mee — voor een overgeslagen extractie is "achtergrond" alleen maar een tragere no-op.
    Drempels configureerbaar (settings.ai_extractie_sync_max_paginas/_bytes); lukt de
    paginatelling niet, dan beslist bestandsgrootte alleen."""
    if Path(document.bestandsnaam).suffix.lower() != _PDF_SUFFIX:
        return None
    if document.administratie_id is None:
        return None
    administratie = session.get(Administratie, document.administratie_id)
    if administratie is None or not administratie.ai_extractie_ingeschakeld:
        return None
    if not settings.anthropic_api_key:
        return None

    paginas = tel_paginas(inhoud)
    te_groot = len(inhoud) > settings.ai_extractie_sync_max_bytes or (
        paginas is not None and paginas > settings.ai_extractie_sync_max_paginas
    )
    if not te_groot:
        return None
    # "reden" hoort erbij: de heraanbied-lus (31-08) draait deze overgang met de systeem-actor,
    # en élke ⚙-overgang draagt een leesbare reden (_borg_systeem_reden).
    return {
        "extractie_wachtrij": "groot_document",
        "paginas": paginas,
        "bytes": len(inhoud),
        "reden": "groot document — extractie via de wachtrij",
    }


def verwerk_extractie_taak(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, opslag: DocumentOpslag | None = None
) -> None:
    """Worker-taak voor de extractie-wachtrij (async extractie, 2026-07-10). Elke statusovergang
    hier draagt de SYSTEEM-actor (app/db/systeem_actor.py) — zichtbaar in tijdlijn én audit_event,
    nooit de gebruiker die toevallig uploadde. Twee losse transacties, bewust: de
    wachtrij→bezig-overgang commit meteen (de UI ziet "bezig" live), daarna pas de langdurige
    extractie + eindovergang. Idempotent via de statusmachine: staat het document niet (meer) op
    extractie_wachtrij — intussen verwijderd, of een dubbele/verouderde taak — dan is dit een
    gelogde no-op. Faalt de afronding onverwacht (bv. opslag onbereikbaar), dan eindigt het
    document zichtbaar op te_controleren met de fout in de tijdlijn — nooit stil blijven hangen
    op bezig."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("Extractie-wachtrijtaak: onbekend document %s — overgeslagen", document_id)
            return
        if document.status != DocumentStatus.EXTRACTIE_WACHTRIJ:
            logger.info(
                "Extractie-wachtrijtaak: document %s staat op %s (niet extractie_wachtrij) — overgeslagen",
                document_id,
                document.status.value,
            )
            return
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.EXTRACTIE_BEZIG,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={"reden": "extractie gestart"},
        )

    try:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, document_id)
            if document is None:  # pragma: no cover — kan alleen bij een parallelle harde delete
                return
            _rond_extractie_af(session, document=document, actor_id=SYSTEEM_ACTOR_ID, opslag=opslag)
            soort = document.soort
        _na_extractie_hook(administratie_id=administratie_id, document_id=document_id, soort=soort)
    except Exception as exc:  # noqa: BLE001 — vangnet: het document mag nooit stil op 'bezig' blijven hangen
        logger.exception("Extractie-worker faalde voor document %s", document_id)
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, document_id)
            if document is not None and document.status == DocumentStatus.EXTRACTIE_BEZIG:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.TE_CONTROLEREN,
                    actor_id=SYSTEEM_ACTOR_ID,
                    detail={"ai_extractie_fout": str(exc), "reden": f"AI-extractie mislukt: {exc}"},
                )


def herstel_achtergebleven_extracties(*, wachtrij: ExtractieWachtrij | None = None) -> int:
    """Startup-vangnet ("niets verdwijnt stil"): de in-process wachtrij overleeft een
    proces-herstart niet. Documenten die in extractie_wachtrij achterbleven worden opnieuw
    ge-enqueued; documenten die midden in een worker-run op extractie_bezig strandden gaan eerst
    terug naar de wachtrij (systeem-actor + herkenbaar detail in de tijdlijn). Retourneert het
    aantal opnieuw ingeplande documenten. Synchrone extracties kunnen hier nooit tussen zitten:
    die committen hun bezig- en eindovergang in één transactie — een crash rolt de hele upload
    terug."""
    with scoped_session(None) as session:
        administratie_ids = [rij.id for rij in session.scalars(select(Administratie))]

    hersteld = 0
    for administratie_id in administratie_ids:
        te_enqueuen: list[uuid.UUID] = []
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            achtergebleven = session.scalars(
                select(Document).where(
                    Document.administratie_id == administratie_id,
                    Document.status.in_((DocumentStatus.EXTRACTIE_WACHTRIJ, DocumentStatus.EXTRACTIE_BEZIG)),
                )
            )
            for document in achtergebleven:
                if document.status == DocumentStatus.EXTRACTIE_BEZIG:
                    _schrijf_overgang(
                        session,
                        document=document,
                        naar=DocumentStatus.EXTRACTIE_WACHTRIJ,
                        actor_id=SYSTEEM_ACTOR_ID,
                        detail={
                            "herstel": "achtergebleven_na_herstart",
                            "reden": "opnieuw ingepland na een herstart van de verwerking",
                        },
                    )
                te_enqueuen.append(document.id)
        for document_id in te_enqueuen:
            (wachtrij or _standaard_wachtrij()).enqueue(administratie_id=administratie_id, document_id=document_id)
        hersteld += len(te_enqueuen)

    if hersteld:
        logger.info("Achtergebleven extracties opnieuw ingepland na herstart: %s document(en)", hersteld)
    return hersteld


def verwerk_extractie_wachtrij(*, stale_na: timedelta = timedelta(minutes=15)) -> int:
    """Job-/CLI-entrypoint (punt 4, 26-08): werk álle documenten op `extractie_wachtrij` synchroon
    af, plus documenten die langer dan `stale_na` op `extractie_bezig` staan (gestrande worker —
    een lopende synchrone extractie is nooit zichtbaar op bezig: die commit bezig én eind in één
    transactie). Bewust NIET elke bezig-rij (zoals het startup-vangnet): twee job-uitvoeringen
    kunnen elkaar overlappen (on-demand trigger + scheduler-vangnet) en mogen elkaars werk niet
    terugzetten. Idempotent via de statusmachine; retourneert het aantal verwerkte documenten."""
    grens = datetime.now(UTC) - stale_na
    with scoped_session(None) as session:
        administratie_ids = [rij.id for rij in session.scalars(select(Administratie))]

    directe = DirecteExtractieWachtrij(taak=verwerk_extractie_taak)
    for administratie_id in administratie_ids:
        te_verwerken: list[uuid.UUID] = []
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            kandidaten = session.scalars(
                select(Document).where(
                    Document.administratie_id == administratie_id,
                    Document.status.in_((DocumentStatus.EXTRACTIE_WACHTRIJ, DocumentStatus.EXTRACTIE_BEZIG)),
                )
            )
            for document in kandidaten:
                if document.status == DocumentStatus.EXTRACTIE_BEZIG:
                    laatste = session.scalar(
                        select(func.max(DocumentGebeurtenis.tijdstip)).where(
                            DocumentGebeurtenis.document_id == document.id
                        )
                    )
                    if laatste is not None and laatste > grens:
                        continue  # verse bezig-run van een andere verwerker — laten staan
                    _schrijf_overgang(
                        session,
                        document=document,
                        naar=DocumentStatus.EXTRACTIE_WACHTRIJ,
                        actor_id=SYSTEEM_ACTOR_ID,
                        detail={
                            "herstel": "gestrand_op_bezig",
                            "reden": "extractie strandde op 'bezig' — opnieuw ingepland",
                        },
                    )
                te_verwerken.append(document.id)
        for document_id in te_verwerken:
            directe.enqueue(administratie_id=administratie_id, document_id=document_id)

    if directe.verwerkt:
        logger.info("Extractie-wachtrij verwerkt: %s document(en)", len(directe.verwerkt))
    return len(directe.verwerkt)


# De detail-sleutels waarmee een extractie-uitkomst in de tijdlijn landt (zie
# _ai_extractie_detail/_rond_extractie_af): de jongste hiervan bepaalt of de laatste
# extractiepoging van een document faalde.
_AI_UITKOMST_KEYS = ("veldvoorstel", "ai_extractie_fout", "ai_extractie_overgeslagen", "ai_extractie_onvolledig")


def heraanbied_gefaalde_extracties(
    *,
    sinds: datetime,
    fout_filter: str | None = None,
    dry_run: bool = False,
    opslag: DocumentOpslag | None = None,
    wachtrij: ExtractieWachtrij | None = None,
) -> dict[str, int]:
    """Bulk-nazorg (union-limiet-bugfix 31-08): biedt documenten waarvan de LAATSTE
    extractiepoging sinds `sinds` faalde (tijdlijn-detail `ai_extractie_fout`) opnieuw aan via
    de bestaande opnieuw-route (herextraheer_document) — géén nieuwe motor, dezelfde poorten
    (PDF-only, status te_controleren/handmatig_afmaken, AVG-gate, klein-vs-groot-routing).
    `fout_filter` beperkt tot fouten waarvan de tekst de substring bevat (case-insensitief,
    bv. "union types"). `dry_run` telt alleen. Systeem-actor; elke stap zichtbaar in tijdlijn
    en audit zoals elke herextractie. Retourneert tellingen: kandidaten / heraangeboden /
    naar_wachtrij / overgeslagen."""
    with scoped_session(None) as session:
        administratie_ids = [rij.id for rij in session.scalars(select(Administratie))]

    telling = {"kandidaten": 0, "heraangeboden": 0, "naar_wachtrij": 0, "overgeslagen": 0}
    for administratie_id in administratie_ids:
        kandidaten: list[uuid.UUID] = []
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            recent_gefaald = session.scalars(
                select(DocumentGebeurtenis.document_id)
                .join(Document, Document.id == DocumentGebeurtenis.document_id)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.status.in_((DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN)),
                    DocumentGebeurtenis.tijdstip >= sinds,
                    DocumentGebeurtenis.detail.has_key("ai_extractie_fout"),
                )
                .distinct()
            ).all()
            for document_id in recent_gefaald:
                # Alleen als de jóngste extractie-uitkomst de fout is — een document dat na de
                # fout alsnog een voorstel kreeg (handmatige "opnieuw"-klik) blijft met rust.
                laatste_uitkomst = session.scalars(
                    select(DocumentGebeurtenis)
                    .where(DocumentGebeurtenis.document_id == document_id)
                    .order_by(DocumentGebeurtenis.tijdstip.desc())
                ).all()
                uitkomst = next(
                    (g for g in laatste_uitkomst if any(key in (g.detail or {}) for key in _AI_UITKOMST_KEYS)),
                    None,
                )
                if uitkomst is None or "ai_extractie_fout" not in (uitkomst.detail or {}):
                    continue
                fout_tekst = str((uitkomst.detail or {}).get("ai_extractie_fout", ""))
                if fout_filter and fout_filter.lower() not in fout_tekst.lower():
                    continue
                kandidaten.append(document_id)

        telling["kandidaten"] += len(kandidaten)
        if dry_run:
            continue
        for document_id in kandidaten:
            try:
                eind_status = herextraheer_document(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    actor_id=SYSTEEM_ACTOR_ID,
                    opslag=opslag,
                    wachtrij=wachtrij,
                )
            except (DocumentNietGevonden, HerextractieNietToegestaan) as exc:
                logger.warning("Heraanbieden overgeslagen voor document %s: %s", document_id, exc)
                telling["overgeslagen"] += 1
                continue
            telling["heraangeboden"] += 1
            if eind_status == DocumentStatus.EXTRACTIE_WACHTRIJ:
                telling["naar_wachtrij"] += 1

    logger.info(
        "Heraanbieden gefaalde extracties: %s kandidaat/kandidaten, %s heraangeboden "
        "(waarvan %s via de wachtrij), %s overgeslagen%s",
        telling["kandidaten"],
        telling["heraangeboden"],
        telling["naar_wachtrij"],
        telling["overgeslagen"],
        " [dry-run]" if dry_run else "",
    )
    return telling


def _taxrate_kandidaat(rij: TaxRateCache) -> extractie_controle.TaxRateKandidaat:
    """TaxRate-kandidaat mét RLZ-vlaggen uit brondata (punt 3, 26-08): verlegd/vrijgesteld/
    gemengd doen niet mee in de bedrag-afleiding, `IsFavorite` is de tiebreak bij een gelijk
    percentage. Zelfde vlag-lezing als app/sync/btw.py (`taxrate_vlaggen`)."""
    is_verlegd, is_vrijgesteld = taxrate_vlaggen(rij.brondata)
    brondata = rij.brondata or {}
    return extractie_controle.TaxRateKandidaat(
        id=rij.id,
        percentage=rij.percentage,
        is_favoriet=bool(brondata.get("IsFavorite")),
        is_verlegd=is_verlegd,
        is_vrijgesteld=is_vrijgesteld,
        is_gemengd=bool(brondata.get("IsMixed")),
    )


def _pdf_extractie_detail(session: Session, *, document: Document, opslag: DocumentOpslag) -> tuple[dict, bool]:
    """Extractievolgorde voor PDF's (best-practice-besluit 2, 31-08 — deterministische terugval):
    a. geldig template van de herkende crediteur + tekstlaag → template-parse (alle interne validaties
       groen; één rood = héle uitkomst verworpen + template ongeldig, door naar b). Dit pad staat NIET
       achter de AI-AVG-gate: lokale code, er gaat niets naar buiten — werkt dus óók voor
       administraties met AI-extractie uit;
    b. het AI-pad exact zoals het was (gates, kostengrens, schema-poort ongewijzigd);
    c. AI niet beschikbaar + geen template → het bestaande handmatige pad (overgeslagen-detail).
    Gevolg: het template bespaart AI-kosten op de bulk én is de terugval bij AI-uitval."""
    inhoud = opslag.lezen(pad=document.opslag_pad)
    notitie: str | None = None
    if document.administratie_id is not None and document.soort == DocumentSoort.INKOOPFACTUUR.value:
        from app.documenten.crediteur_kenmerk import kandidaten_met_kenmerken

        vendors = kandidaten_met_kenmerken(session, administratie_id=document.administratie_id)
        taxrates = _taxrate_kandidaten(session, administratie_id=document.administratie_id)
        try:
            detail, notitie = template_service.template_extractie_detail(
                session, document=document, inhoud=inhoud, vendors=vendors, taxrates=taxrates
            )
        except Exception:  # noqa: BLE001 — de terugval mag de extractie nooit laten falen: dan gewoon het AI-pad
            logger.exception("Template-terugval mislukt voor document %s — AI-pad gevolgd", document.id)
            detail, notitie = None, "template-terugval gaf een fout — AI-pad gevolgd"
        if detail is not None:
            return detail, False
    detail, blokkeer = _ai_extractie_detail(session, document=document, opslag=opslag, inhoud=inhoud)
    if notitie:
        detail = {**detail, "template_terugval": notitie}
    return detail, blokkeer


def _taxrate_kandidaten(session: Session, *, administratie_id: uuid.UUID) -> list[extractie_controle.TaxRateKandidaat]:
    return [
        _taxrate_kandidaat(rij)
        for rij in session.scalars(
            select(TaxRateCache).where(
                TaxRateCache.administratie_id == administratie_id,
                TaxRateCache.verdwenen_uit_bron_op.is_(None),
            )
        )
    ]


def _ai_extractie_detail(
    session: Session, *, document: Document, opslag: DocumentOpslag, inhoud: bytes | None = None
) -> tuple[dict, bool]:
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

    if inhoud is None:
        inhoud = opslag.lezen(pad=document.opslag_pad)
    try:
        extractie = extractie_service.extraheer_inkoopfactuur(
            inhoud,
            verbruik_referentie=AiVerbruikReferentie(bron="inkoop_extractie", document_id=document.id),
            # Begeleidende mailtekst als hint (punt 1c) — zelfde AVG-gate als het document zelf.
            mail_context=_mail_body_van(session, document),
        )
    except AiKostenLimietBereikt:
        # AI-kostengrens (besluit 2026-08-14): zelfde zichtbare pad als de AVG-gate-uit — het
        # document valt niet stil weg maar gaat het handmatige spoor in, met eigen chip.
        logger.warning("AI-maandlimiet bereikt — extractie overgeslagen voor document %s", document.id)
        return {"ai_extractie_overgeslagen": "ai_limiet_bereikt"}, False
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

    # Punt 14 (28-08): kandidaten mét bekende btw-/KvK-nummers — nummer-match wint vóór de naam.
    from app.documenten.crediteur_kenmerk import kandidaten_met_kenmerken

    vendors = kandidaten_met_kenmerken(session, administratie_id=document.administratie_id)
    taxrates = _taxrate_kandidaten(session, administratie_id=document.administratie_id)
    voorstel = extractie_controle.bouw_veldvoorstel(
        extractie,
        vendors=vendors,
        taxrates=taxrates,
        zekerheid_drempel=settings.ai_extractie_zekerheid_drempel,
    )
    return {"veldvoorstel": voorstel, "ai_metriek": metriek}, False


def _rapport_extractie_detail(session: Session, *, document: Document, opslag: DocumentOpslag) -> dict:
    """AI-route voor kassarapporten (omzetmodule): AVG-gate → rapport-extractie →
    deterministische controlelaag (app/extractie/rapport.py). Zelfde uitkomst-conventie als
    _ai_extractie_detail: voorstel, overgeslagen of fout — altijd herkenbaar in de tijdlijn,
    een AI-fout laat de upload nooit falen."""
    from app.extractie import rapport as rapport_extractie  # lokaal: houdt de importgraaf klein

    if document.administratie_id is None:
        return {"ai_extractie_overgeslagen": "geen_administratie"}
    administratie = session.get(Administratie, document.administratie_id)
    if administratie is None or not administratie.ai_extractie_ingeschakeld:
        return {"ai_extractie_overgeslagen": "ai_extractie_uitgeschakeld"}
    if not settings.anthropic_api_key:
        return {"ai_extractie_overgeslagen": "geen_api_key"}

    inhoud = opslag.lezen(pad=document.opslag_pad)
    try:
        extractie = rapport_extractie.extraheer_kassarapport(
            inhoud,
            verbruik_referentie=AiVerbruikReferentie(bron="rapport_extractie", document_id=document.id),
        )
    except AiKostenLimietBereikt:
        # AI-kostengrens (besluit 2026-08-14): zelfde zichtbare pad als de AVG-gate-uit.
        logger.warning("AI-maandlimiet bereikt — rapport-extractie overgeslagen voor document %s", document.id)
        return {"ai_extractie_overgeslagen": "ai_limiet_bereikt"}
    except Exception as exc:  # noqa: BLE001 — bewust breed: een AI-fout mag de upload nooit laten falen
        logger.exception("Rapport-extractie mislukt voor document %s", document.id)
        return {"ai_extractie_fout": str(exc)}

    voorstel = rapport_extractie.bouw_rapport_veldvoorstel(
        extractie, zekerheid_drempel=settings.ai_extractie_zekerheid_drempel
    )
    return {"veldvoorstel": voorstel}


def _na_extractie_hook(*, administratie_id: uuid.UUID | None, document_id: uuid.UUID, soort: str) -> None:
    """Ná de commit van een afgeronde extractie (upload, her-extractie én worker): voor
    kassarapporten de automatische mapping-vraag ("nieuwe categorie zonder mapping → regel
    blokkerend + automatische vraag", CLAUDE.md-omzetbesluit). Bewust post-commit: de vraag-
    service opent zijn eigen transactie en moet de zojuist geschreven status/tijdlijn zien.
    Faalt de hook, dan is dat een gelogde waarschuwing — de blokkerende mapping-check op het
    reviewscherm blijft de harde poort, de vraag is de signalering eromheen."""
    if administratie_id is None:
        return
    if soort == DocumentSoort.INKOOPFACTUUR.value:
        # Duplicaatsignaal (besluit Peter 25-08, deel 2 punt 6): de RLZ-duplicaatquery éénmaal
        # ná extractie draaien en cachen, zodat de werkvoorraad de chip direct toont. Puur
        # signalering (de live check op het boekmoment blijft bindend); fouten zichtbaar als
        # 'onbekend' + gelogd, nooit een blokkade.
        from app.documenten import duplicaatsignaal  # lokaal: houdt de importgraaf klein

        duplicaatsignaal.bereken_duplicaatsignaal_stil(administratie_id=administratie_id, document_id=document_id)

        # Factuurmatch (fase 2, akkoord Peter 2026-08-21): éérst de match-run — vóór de
        # autoboek-poging, zodat het autoboek-slot (fase 4) en de weigering hieronder de
        # actuele matchstand zien, en de werkvoorraad-teller/chip direct ná extractie klopt.
        # Post-commit, systeem-actor; een fout is een gelogde waarschuwing (de match is een
        # signaal bovenop de normale flow, nooit een blokkade van de verwerking zelf).
        from app.uren import factuurmatch_pipeline  # lokaal: houdt de importgraaf klein

        try:
            factuurmatch_pipeline.draai_match_voor_document(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — de match is signalering, nooit een blokkade
            logger.exception("Factuurmatch-run mislukt voor document %s", document_id)
        # Materiaalmatch (steigerbouw-run D6): verhuur-crediteuren vs geregistreerde leveringen.
        from app.materiaal import match as materiaalmatch

        try:
            materiaalmatch.draai_materiaalmatch(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — signalering, nooit een blokkade
            logger.exception("Materiaalmatch-run mislukt voor document %s", document_id)

        # Autoboeken-opt-in per leverancier (blok 2, 2026-08-09): post-commit, systeem-actor;
        # elke uitkomst geauditeerd zodra de opt-in aanstaat. Een fout hier mag de
        # upload/worker nooit laten falen — het document blijft dan gewoon mensenwerk.
        from app.voorraad import service as voorraad_service  # lokaal: houdt de importgraaf klein

        try:
            # Blok D 28-08: instroom-feiten (regel-niveau) voor de voorraad-aansluiting — alleen bij
            # de opt-in van de administratie; signalering, nooit een blokkade.
            voorraad_service.registreer_inkoopregels(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — MI-laag, nooit een blokkade
            logger.exception("Voorraad-registratie (inkoop) mislukt voor document %s", document_id)

        from app.documenten import autoboeken  # lokaal: houdt de importgraaf klein

        try:
            autoboeken.probeer_autoboeken_na_extractie(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — autoboeken is een optimalisatie, nooit een blokkade
            logger.exception("Autoboeken-poging mislukt voor document %s", document_id)
    elif soort == DocumentSoort.KASSARAPPORT.value:
        # Omzet-autoboeken-opt-in (GO Peter 01-09, migratie 0096): éérst de autoboek-poging (post-commit,
        # systeem-actor; elke uitkomst geauditeerd zodra de opt-in aanstaat), daarná de mapping-autovraag —
        # zelfde volgorde als het verkoop-pad (andersom zou de vraag-status de weigering onzichtbaar maken).
        from app.omzet import autoboeken as omzet_autoboeken  # lokaal: importcyclus omzet ↔ documenten

        try:
            omzet_autoboeken.probeer_omzet_autoboeken_na_extractie(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — autoboeken is een optimalisatie, nooit een blokkade
            logger.exception("Omzet-autoboeken-poging mislukt voor document %s", document_id)

        from app.omzet import autovraag  # lokaal: voorkomt een importcyclus omzet ↔ documenten

        try:
            autovraag.stel_mapping_vraag_indien_nodig(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — signalering mag de upload/worker nooit laten falen
            logger.exception("Automatische mapping-vraag mislukt voor document %s", document_id)
    elif soort == DocumentSoort.VERKOOPFACTUUR.value:
        # Verkoop-autoboeken-opt-in (besluit Peter 2026-08-15, migratie 0051): éérst de
        # autoboek-poging (post-commit, systeem-actor; elke uitkomst geauditeerd zodra de
        # opt-in aanstaat) — een weigering laat het document gewoon in de werkvoorraad en
        # daarná stelt de autovraag zo nodig alsnog de onbekende-GB-code-vraag. Andersom zou
        # de vraag de status verzetten en de weigering onzichtbaar (None) maken.
        from app.verkoop import autoboeken as verkoop_autoboeken  # lokaal: importcyclus vermijden

        try:
            verkoop_autoboeken.probeer_verkoop_autoboeken_na_intake(
                administratie_id=administratie_id, document_id=document_id
            )
        except Exception:  # noqa: BLE001 — autoboeken is een optimalisatie, nooit een blokkade
            logger.exception("Verkoop-autoboeken-poging mislukt voor document %s", document_id)

        # §2d-GB-uitbreiding (v1.10): onbekende AccountingCost-code → blokkerende check +
        # automatische vraag; zelfde no-op-vangnet als de omzet-mappingvraag.
        from app.verkoop import autovraag as verkoop_autovraag  # lokaal: importcyclus vermijden

        try:
            verkoop_autovraag.stel_gb_code_vraag_indien_nodig(
                administratie_id=administratie_id, document_id=document_id
            )
        except Exception:  # noqa: BLE001 — signalering mag de upload/worker nooit laten falen
            logger.exception("Automatische GB-code-vraag mislukt voor document %s", document_id)


@dataclass(frozen=True)
class BronBestand:
    """Aangeleverd origineel dat naast het (omgezette) documentbestand bewaard blijft — punt 2
    feedbackronde 25-08 deel 3: foto.jpg → foto.pdf als document, foto.jpg als brondocument."""

    bestandsnaam: str
    inhoud: bytes
    content_type: str


def _sla_bronbestand_op(opslag: DocumentOpslag, *, opslag_pad: str, bron: BronBestand | None) -> str | None:
    if bron is None:
        return None
    bron_pad = f"{opslag_pad}.bron{Path(bron.bestandsnaam).suffix.lower()}"
    opslag.opslaan(pad=bron_pad, inhoud=bron.inhoud)
    return bron_pad


def upload_document(
    *,
    administratie_id: uuid.UUID,
    bestandsnaam: str,
    inhoud: bytes,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
    bron: DocumentBron = DocumentBron.UPLOAD,
    soort: DocumentSoort = DocumentSoort.INKOOPFACTUUR,
    wachtrij: ExtractieWachtrij | None = None,
    # E-mail-intake-herkomst (migratie 0028) — alleen gevuld voor documenten uit de intake.
    intake_bericht_id: uuid.UUID | None = None,
    afzender_hint: str | None = None,
    tenaamstelling: str | None = None,
    gesplitst_uit_id: uuid.UUID | None = None,
    bron_bestand: BronBestand | None = None,
) -> UploadResultaat:
    """Slaat het bestand op, detecteert mogelijke duplicaten (sha256, binnen dezelfde
    administratie) en start de extractie: klein = synchroon binnen deze request (snelle
    happy-path), groot = direct de achtergrondwachtrij in (status extractie_wachtrij — de
    response keert meteen terug, de worker doet de rest met de systeem-actor).
    `mogelijk_duplicaat_van_id` is een losse vlag op het document — het doorloopt gewoon de
    normale statusmachine, met dit signaal erbovenop voor de controleur (mockup: chip 'Mogelijk
    duplicaat van ... — beoordelen')."""
    opslag = opslag or _standaard_opslag()
    document_id = uuid.uuid4()
    sha256_hash = _hash(inhoud)

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        if intake_bericht_id is not None:
            # Intake-herverwerking (afgebroken "bezig"-run wordt opnieuw aangeboden): dezelfde
            # bijlage van hetzélfde bericht is al een document — teruggeven, niet dupliceren.
            # Bewust alleen binnen één intake_bericht_id: dezelfde bytes uit een ánder bericht
            # blijven een nieuw document (met de gewone mogelijk-duplicaat-vlag hieronder).
            al_geregistreerd = session.scalars(
                select(Document).where(
                    Document.intake_bericht_id == intake_bericht_id,
                    Document.sha256_hash == sha256_hash,
                    Document.administratie_id == administratie_id,
                )
            ).first()
            if al_geregistreerd is not None:
                return UploadResultaat(
                    document_id=al_geregistreerd.id,
                    status=al_geregistreerd.status,
                    mogelijk_duplicaat_van_id=al_geregistreerd.mogelijk_duplicaat_van_id,
                    mogelijk_duplicaat_van=None,
                )

        bestaand = session.scalars(
            select(Document)
            .where(Document.administratie_id == administratie_id, Document.sha256_hash == sha256_hash)
            .order_by(Document.aangemaakt_op)
        ).first()

        opslag_pad = f"{administratie_id}/{document_id}{Path(bestandsnaam).suffix.lower()}"
        opslag.opslaan(pad=opslag_pad, inhoud=inhoud)
        bron_pad = _sla_bronbestand_op(opslag, opslag_pad=opslag_pad, bron=bron_bestand)

        document = Document(
            id=document_id,
            administratie_id=administratie_id,
            bron=bron,
            soort=soort.value,
            bestandsnaam=bestandsnaam,
            sha256_hash=sha256_hash,
            status=DocumentStatus.ONTVANGEN,
            mogelijk_duplicaat_van_id=bestaand.id if bestaand else None,
            opslag_pad=opslag_pad,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender_hint,
            tenaamstelling=tenaamstelling,
            gesplitst_uit_id=gesplitst_uit_id,
            bron_opslag_pad=bron_pad,
            bron_bestandsnaam=bron_bestand.bestandsnaam if bron_bestand else None,
            bron_content_type=bron_bestand.content_type if bron_bestand else None,
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

        wachtrij_detail = _groot_document_detail(session, document=document, inhoud=inhoud)
        if wachtrij_detail is not None:
            # De wachtrij-overgang zelf draagt nog de menselijke actor (de upload is een
            # menselijke handeling); vanaf het oppakken door de worker is alles systeem-actor.
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_WACHTRIJ,
                actor_id=actor_id,
                detail=wachtrij_detail,
            )
        else:
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

    if wachtrij_detail is not None:
        # Ná de commit — de worker mag het document pas zien als de wachtrij-status vaststaat.
        (wachtrij or _standaard_wachtrij()).enqueue(administratie_id=administratie_id, document_id=document_id)
    else:
        _na_extractie_hook(administratie_id=administratie_id, document_id=document_id, soort=soort.value)

    return UploadResultaat(
        document_id=document_id,
        status=eind_status,
        mogelijk_duplicaat_van_id=mogelijk_duplicaat_van_id,
        mogelijk_duplicaat_van=mogelijk_duplicaat_van,
    )


def registreer_niet_toegewezen_document(
    *,
    bestandsnaam: str,
    inhoud: bytes,
    actor_id: uuid.UUID,
    reden: str,
    bron: DocumentBron = DocumentBron.EMAIL,
    soort: DocumentSoort = DocumentSoort.INKOOPFACTUUR,
    opslag: DocumentOpslag | None = None,
    intake_bericht_id: uuid.UUID | None = None,
    afzender_hint: str | None = None,
    tenaamstelling: str | None = None,
    gesplitst_uit_id: uuid.UUID | None = None,
    suggestie_administratie_id: uuid.UUID | None = None,
    suggestie_bron: str | None = None,
    bron_bestand: BronBestand | None = None,
) -> uuid.UUID:
    """Verzamelbak-intake (e-mail-intake, migratie 0028): een document dat niet eenduidig aan een
    administratie te koppelen is — administratie_id NULL, status niet_toegewezen, mét de reden en
    de beste suggestie zichtbaar. "Niets verdwijnt stil": élk niet-toewijsbaar document wordt een
    rij die een mens in de verzamelbak ziet. Extractie start hier bewust NIET — die draait pas na
    toewijzing, onder de AVG-gate van de gekozen administratie."""
    opslag = opslag or _standaard_opslag()
    document_id = uuid.uuid4()
    sha256_hash = _hash(inhoud)

    if intake_bericht_id is not None:
        # Zelfde intake-herverwerkings-idempotentie als upload_document: dezelfde bijlage van
        # hetzelfde bericht die al in de verzamelbak ligt niet nogmaals registreren.
        with scoped_session(None) as session:
            al_geregistreerd = session.scalars(
                select(Document).where(
                    Document.intake_bericht_id == intake_bericht_id,
                    Document.sha256_hash == sha256_hash,
                    Document.administratie_id.is_(None),
                )
            ).first()
            if al_geregistreerd is not None:
                return al_geregistreerd.id

    opslag_pad = f"niet_toegewezen/{document_id}{Path(bestandsnaam).suffix.lower()}"
    opslag.opslaan(pad=opslag_pad, inhoud=inhoud)
    bron_pad = _sla_bronbestand_op(opslag, opslag_pad=opslag_pad, bron=bron_bestand)

    with scoped_session(None, actor_id=actor_id) as session:
        document = Document(
            id=document_id,
            administratie_id=None,
            bron=bron,
            soort=soort.value,
            bestandsnaam=bestandsnaam,
            sha256_hash=sha256_hash,
            status=DocumentStatus.ONTVANGEN,
            opslag_pad=opslag_pad,
            intake_bericht_id=intake_bericht_id,
            afzender_hint=afzender_hint,
            tenaamstelling=tenaamstelling,
            gesplitst_uit_id=gesplitst_uit_id,
            toewijzing_suggestie_administratie_id=suggestie_administratie_id,
            toewijzing_suggestie_bron=suggestie_bron,
            bron_opslag_pad=bron_pad,
            bron_bestandsnaam=bron_bestand.bestandsnaam if bron_bestand else None,
            bron_content_type=bron_bestand.content_type if bron_bestand else None,
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
                detail={"intake": reden},
            )
        )
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.NIET_TOEGEWEZEN,
            actor_id=actor_id,
            detail={"reden": reden, "tenaamstelling": tenaamstelling, "afzender": afzender_hint},
        )
    return document_id


def start_extractie_na_toewijzing(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
    wachtrij: ExtractieWachtrij | None = None,
) -> DocumentStatus:
    """Tweede helft van een verzamelbak-toewijzing: het document staat inmiddels op ONTVANGEN
    mét administratie — vanaf hier exact dezelfde klein-vs-groot-extractieroute als een verse
    upload (incl. AVG-gate van de gekozen administratie en de kassarapport-hook)."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        inhoud = opslag.lezen(pad=document.opslag_pad)
        wachtrij_detail = _groot_document_detail(session, document=document, inhoud=inhoud)
        if wachtrij_detail is not None:
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_WACHTRIJ,
                actor_id=actor_id,
                detail=wachtrij_detail,
            )
        else:
            _start_extractie(session, document=document, actor_id=actor_id, opslag=opslag)
        eind_status = document.status
        soort = document.soort

    if wachtrij_detail is not None:
        (wachtrij or _standaard_wachtrij()).enqueue(administratie_id=administratie_id, document_id=document_id)
    else:
        _na_extractie_hook(administratie_id=administratie_id, document_id=document_id, soort=soort)
    return eind_status


def _als_decimal_of_none(waarde: object) -> Decimal | None:
    """Veldvoorstel-waarden komen als string/None uit de JSONB-tijdlijn — nooit gokken bij
    onbruikbare invoer, de kolom blijft dan gewoon leeg (weergave, geen geldlogica)."""
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except (ArithmeticError, ValueError):
        return None


def _als_datum_of_none(waarde: object) -> date | None:
    if not isinstance(waarde, str):
        return None
    try:
        return date.fromisoformat(waarde)
    except ValueError:
        return None


from app.documenten.duplicaatsignaal import DuplicaatSignaalKort  # noqa: E402 — lichte dataclass, geen kringimport


@dataclass(frozen=True)
class FactuurmatchKort:
    """Compacte matchstand voor de documentenlijst-chip (factuurmatch fase 2, besluit 3 —
    duplicaat-patroon: losse vlag bovenop de normale flow, geen status)."""

    uitkomst: str
    verschil_bedrag: Decimal | None
    verschil_uren: Decimal | None
    tarief_ontbreekt: bool


@dataclass(frozen=True)
class AccordeurAanDeBeurt:
    gebruiker_id: uuid.UUID
    naam: str
    laag: int


@dataclass(frozen=True)
class DocumentMetDuplicaat:
    document: Document
    duplicaat_referentie: DuplicaatReferentie | None
    # Kopgegevens voor de werkvoorraad-documentenlijst (mockup #klantpagina: kolommen
    # Leverancier + Bedrag): uit het opgeslagen boekvoorstel, of anders het laatste
    # extractie-veldvoorstel — None zolang er nog geen van beide is.
    leverancier: str | None = None
    totaalbedrag: Decimal | None = None
    factuurdatum: date | None = None
    # Autoboeken-opt-in (blok 2, 2026-08-09): True wanneer de GEBOEKT-overgang het
    # `automatisch_geboekt`-detail draagt — voedt de werkvoorraad-chip en het filter.
    automatisch_geboekt: bool = False
    # Factuurmatch (fase 2): de actuele matchstand van een veldwerker-factuur — None zolang
    # er geen match berekend is (crediteur niet gekoppeld / nog geen voorstel).
    factuurmatch: FactuurmatchKort | None = None
    # Accordeur aan de beurt (C2 26-08): bij status ter_accordering wie (naam + laag) nu aan zet
    # is — de kolom "Toegewezen" toont dát in plaats van "—". None bij elke andere status.
    accordeur_aan_de_beurt: AccordeurAanDeBeurt | None = None
    # Bugfix-run 28-08: boekfout ná het laatste klant-akkoord (laatste ronde afgerond, document
    # niet geboekt) — zichtbaar in de lijst, nooit stil.
    accordering_boek_fout: str | None = None
    # Blok A 28-08: (id, naam) van de afdeling op het boekvoorstel — ook een gearchiveerde naam
    # blijft leesbaar (historie).
    afdeling: tuple[uuid.UUID, str] | None = None
    # Punt 24 (opruimrun 28-08): laatste ronde afgerond, bedrag ongewijzigd, nog niet geboekt —
    # aanbieden geweigerd, boeken kan wél.
    klant_akkoord_compleet: bool = False
    # Duplicaatsignaal (25-08, deel 2 punt 6): gecachete RLZ-duplicaatuitkomst — None zolang er
    # nog niet getoetst is.
    duplicaatsignaal: DuplicaatSignaalKort | None = None


def lijst_documenten(*, administratie_id: uuid.UUID, toon_verwijderd: bool = False) -> list[DocumentMetDuplicaat]:
    """`toon_verwijderd=False` (default) verbergt zachtgewiste documenten uit de normale
    werkvoorraad — de "toon verwijderde"-filter (design-pass taak 4) zet dit aan om ze er weer
    naast te zien (voor het herstelpad), nooit een apart, exclusief lijstje."""
    with scoped_session(administratie_id) as session:
        voorwaarden = [Document.administratie_id == administratie_id]
        if not toon_verwijderd:
            voorwaarden.append(Document.status != DocumentStatus.VERWIJDERD)
        documenten = list(session.scalars(select(Document).where(*voorwaarden).order_by(Document.aangemaakt_op.desc())))
        referenties = _duplicaat_referenties_op(
            session, {d.mogelijk_duplicaat_van_id for d in documenten if d.mogelijk_duplicaat_van_id}
        )
        # Kopgegevens per document in drie bulk-queries (geen N+1): opgeslagen boekvoorstellen,
        # de vendornamen uit de cache, en — voor documenten zónder opgeslagen voorstel — het
        # laatste extractie-veldvoorstel uit de tijdlijn (zelfde bron als de controlescherm-
        # prefill in boekvoorstel.py::_laatste_veldvoorstel).
        document_ids = [d.id for d in documenten]
        voorstellen: dict[uuid.UUID, Boekvoorstel] = (
            {
                v.document_id: v
                for v in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(document_ids)))
            }
            if document_ids
            else {}
        )
        vendor_ids = {v.vendor_id for v in voorstellen.values() if v.vendor_id is not None}
        vendor_namen: dict[uuid.UUID, str | None] = (
            dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(
                        VendorCache.administratie_id == administratie_id, VendorCache.id.in_(vendor_ids)
                    )
                ).all()
            )
            if vendor_ids
            else {}
        )
        # Automatisch-geboekt-markering (bulk): documenten met een GEBOEKT-overgang die het
        # autoboeken-detail draagt (app/documenten/autoboeken.py via boek_document).
        automatisch_geboekt_ids: set[uuid.UUID] = set()
        if document_ids:
            automatisch_geboekt_ids = set(
                session.scalars(
                    select(DocumentGebeurtenis.document_id).where(
                        DocumentGebeurtenis.document_id.in_(document_ids),
                        DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                        DocumentGebeurtenis.detail.has_key("automatisch_geboekt"),
                    )
                )
            )
        # Factuurmatch-chipdata (fase 2, bulk — zelfde geen-N+1-regel). Lazy import: app.uren
        # gebruikt de documenten-modellen, geen kringimport op moduleniveau.
        from app.uren.models import Factuurmatch

        matches: dict[uuid.UUID, FactuurmatchKort] = {}
        if document_ids:
            matches = {
                m.document_id: FactuurmatchKort(
                    uitkomst=m.uitkomst,
                    verschil_bedrag=m.verschil_bedrag,
                    verschil_uren=m.verschil_uren,
                    tarief_ontbreekt=m.tarief_ontbreekt,
                )
                for m in session.scalars(select(Factuurmatch).where(Factuurmatch.document_id.in_(document_ids)))
            }
        # Duplicaatsignaal-chipdata (25-08, deel 2 punt 6; bulk, zelfde geen-N+1-regel).
        from app.documenten.duplicaatsignaal import signalen_voor_documenten

        signalen = signalen_voor_documenten(session, document_ids)
        # Accordeur aan de beurt (C2 26-08, bulk): alleen voor documenten die bij de klant liggen.
        from app.accordering.service import (
            aan_de_beurt_per_document,
            boek_fout_per_document,
            klant_akkoord_compleet_per_document,
        )

        beurt = aan_de_beurt_per_document(
            session, [d.id for d in documenten if d.status == DocumentStatus.TER_ACCORDERING]
        )
        # Boekfout ná het laatste akkoord (bugfix-run 28-08, bulk): alle niet-geboekte documenten.
        boek_fouten = boek_fout_per_document(session, [d.id for d in documenten if d.status != DocumentStatus.GEBOEKT])
        # Punt 24 (opruimrun 28-08, bulk): compleet-maar-onverzilverd klant-akkoord op boekklare rijen.
        akkoord_compleet = klant_akkoord_compleet_per_document(
            session, [d.id for d in documenten if d.status == DocumentStatus.KLAAR_OM_TE_BOEKEN]
        )
        from app.afdelingen.service import afdeling_namen

        afdelingen = (
            afdeling_namen(session, administratie_id)
            if any(v.afdeling_id is not None for v in voorstellen.values())
            else {}
        )
        veldvoorstellen: dict[uuid.UUID, dict] = {}
        zonder_voorstel = [d_id for d_id in document_ids if d_id not in voorstellen]
        if zonder_voorstel:
            # Oplopend op tijdstip; de laatste schrijver per document wint ("opnieuw extraheren"
            # = nieuwste extractie is de actuele — zelfde regel als het controlescherm).
            for gebeurtenis in session.scalars(
                select(DocumentGebeurtenis)
                .where(
                    DocumentGebeurtenis.document_id.in_(zonder_voorstel),
                    DocumentGebeurtenis.detail.has_key("veldvoorstel"),
                )
                .order_by(DocumentGebeurtenis.tijdstip)
            ):
                veldvoorstellen[gebeurtenis.document_id] = gebeurtenis.detail["veldvoorstel"]

        def _kop(document_id: uuid.UUID) -> tuple[str | None, Decimal | None, date | None]:
            voorstel = voorstellen.get(document_id)
            if voorstel is not None:
                naam = vendor_namen.get(voorstel.vendor_id) if voorstel.vendor_id else None
                return naam, voorstel.totaalbedrag, voorstel.factuurdatum
            veldvoorstel = veldvoorstellen.get(document_id)
            if veldvoorstel is None:
                return None, None, None
            return (
                veldvoorstel.get("leverancier_naam") or None,
                _als_decimal_of_none(veldvoorstel.get("totaal_incl")),
                _als_datum_of_none(veldvoorstel.get("factuurdatum")),
            )

        resultaat = []
        for d in documenten:
            leverancier, totaalbedrag, factuurdatum = _kop(d.id)
            resultaat.append(
                DocumentMetDuplicaat(
                    document=d,
                    duplicaat_referentie=referenties.get(d.mogelijk_duplicaat_van_id)
                    if d.mogelijk_duplicaat_van_id
                    else None,
                    leverancier=leverancier,
                    totaalbedrag=totaalbedrag,
                    factuurdatum=factuurdatum,
                    automatisch_geboekt=d.id in automatisch_geboekt_ids,
                    factuurmatch=matches.get(d.id),
                    duplicaatsignaal=signalen.get(d.id),
                    accordeur_aan_de_beurt=beurt.get(d.id),
                    accordering_boek_fout=boek_fouten.get(d.id),
                    klant_akkoord_compleet=d.id in akkoord_compleet,
                    afdeling=(
                        (voorstellen[d.id].afdeling_id, afdelingen[voorstellen[d.id].afdeling_id])
                        if d.id in voorstellen
                        and voorstellen[d.id].afdeling_id is not None
                        and voorstellen[d.id].afdeling_id in afdelingen
                        else None
                    ),
                )
            )
        return resultaat


# Statusbuckets voor de werkvoorraad-klantenlijst (mockup #werkvoorraad "Overzicht per klant").
# boeken_mislukt telt bewust mee als "te controleren": het vraagt om menselijke actie en mag
# nooit stil in een verborgen bucket vallen.
_TE_CONTROLEREN_STATUSSEN = {
    DocumentStatus.ONTVANGEN,
    DocumentStatus.EXTRACTIE_WACHTRIJ,
    DocumentStatus.EXTRACTIE_BEZIG,
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.BOEKEN_MISLUKT,
}


@dataclass(frozen=True)
class WerkvoorraadKlant:
    administratie_id: uuid.UUID
    naam: str
    te_controleren: int
    klaar_om_te_boeken: int
    vragen: int
    afgewezen: int
    bij_klant: int
    iban_wachtend: int
    # Factuurmatch (fase 2, besluit 3): open documenten met matchuitkomst `afwijking`. Een
    # SIGNAAL-teller bovenop de status-tellers (de documenten zelf zitten al in een bucket
    # hierboven) — telt daarom bewust niet mee in heeft_openstaand_werk.
    match_afwijkingen: int = 0
    # Duplicaatsignaal (25-08, deel 2 punt 6): open documenten met gecachete uitkomst
    # `mogelijk_duplicaat` — zelfde signaal-patroon, telt niet mee in heeft_openstaand_werk.
    duplicaat_signalen: int = 0
    # Terugkerende facturen (blok B 30-08): leveranciers met een actief "verwachte factuur
    # ontbreekt"-signaal — zelfde signaal-patroon (oranje, geen blokkade, geen document erachter).
    terugkerend_signalen: int = 0

    @property
    def heeft_openstaand_werk(self) -> bool:
        return (
            self.te_controleren
            + self.klaar_om_te_boeken
            + self.vragen
            + self.afgewezen
            + self.bij_klant
            + self.iban_wachtend
        ) > 0


def werkvoorraad_overzicht(*, administratie_ids_met_naam: list[tuple[uuid.UUID, str]]) -> list[WerkvoorraadKlant]:
    """Tellers per administratie voor de werkvoorraad-klantenlijst (mockup #werkvoorraad). De
    aanroeper (router) levert uitsluitend administraties binnen de scope van de gebruiker aan —
    zelfde patroon als bank_overzicht. Alle administraties komen mee (ook zonder openstaand
    werk); de frontend verbergt de lege en toont alleen het aantal verborgen klanten."""
    from app.uren.models import Factuurmatch  # lazy: geen kringimport op moduleniveau

    klanten: list[WerkvoorraadKlant] = []
    for administratie_id, naam in administratie_ids_met_naam:
        with scoped_session(administratie_id) as session:
            per_status = dict(
                session.execute(
                    select(Document.status, func.count())
                    .where(
                        Document.administratie_id == administratie_id,
                        # Terminale statussen tellen niet als openstaand werk: geboekt,
                        # verwijderd en gesplitst (de kinderen van een splitsing tellen zelf).
                        Document.status.notin_(
                            [DocumentStatus.VERWIJDERD, DocumentStatus.GEBOEKT, DocumentStatus.GESPLITST]
                        ),
                    )
                    .group_by(Document.status)
                ).all()
            )
            # Factuurmatch-signaalteller (fase 2, besluit 3): afwijkingen op nog-open
            # documenten — géén status (de documenten tellen hierboven al mee), wel een
            # eigen teller/chip volgens het duplicaat-patroon.
            match_afwijkingen = (
                session.scalar(
                    select(func.count())
                    .select_from(Factuurmatch)
                    .join(Document, Document.id == Factuurmatch.document_id)
                    .where(
                        Factuurmatch.administratie_id == administratie_id,
                        Factuurmatch.uitkomst == "afwijking",
                        Document.status.notin_(
                            [DocumentStatus.VERWIJDERD, DocumentStatus.GEBOEKT, DocumentStatus.GESPLITST]
                        ),
                    )
                )
                or 0
            )
            duplicaat_signalen = (
                session.scalar(
                    select(func.count())
                    .select_from(DuplicaatSignaal)
                    .join(Document, Document.id == DuplicaatSignaal.document_id)
                    .where(
                        DuplicaatSignaal.administratie_id == administratie_id,
                        DuplicaatSignaal.uitkomst == DuplicaatSignaalUitkomst.MOGELIJK_DUPLICAAT.value,
                        Document.status.notin_(
                            [DocumentStatus.VERWIJDERD, DocumentStatus.GEBOEKT, DocumentStatus.GESPLITST]
                        ),
                    )
                )
                or 0
            )
            from app.terugkerend import service as terugkerend_service

            terugkerend_signalen = terugkerend_service.tel_ontbrekend(session, administratie_id)
        klanten.append(
            WerkvoorraadKlant(
                administratie_id=administratie_id,
                naam=naam,
                te_controleren=sum(per_status.get(s, 0) for s in _TE_CONTROLEREN_STATUSSEN),
                klaar_om_te_boeken=per_status.get(DocumentStatus.KLAAR_OM_TE_BOEKEN, 0),
                vragen=per_status.get(DocumentStatus.VRAAG_OPEN, 0),
                afgewezen=per_status.get(DocumentStatus.AFGEWEZEN, 0),
                # Klant-accordering (migratie 0033): "Bij klant" = documenten die op één of
                # meer accorderingslagen wachten.
                bij_klant=per_status.get(DocumentStatus.TER_ACCORDERING, 0),
                iban_wachtend=per_status.get(DocumentStatus.WACHT_OP_IBAN_ACCORDERING, 0),
                match_afwijkingen=match_afwijkingen,
                duplicaat_signalen=duplicaat_signalen,
                terugkerend_signalen=terugkerend_signalen,
            )
        )
    return klanten


def haal_bronbestand_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> tuple[bytes, str, str]:
    """Origineel brondocument (migratie 0070) van een naar PDF omgezette afbeelding."""
    opslag = _standaard_opslag()
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.bron_opslag_pad is None or document.bron_bestandsnaam is None:
            raise DocumentNietGevonden(f"Geen brondocument voor: {document_id}")
        pad, naam = document.bron_opslag_pad, document.bron_bestandsnaam
        content_type = document.bron_content_type or content_type_voor(naam)
    return opslag.lezen(pad=pad), naam, content_type


def _mail_body_van(session: Session, document: Document) -> str | None:
    """Platte mail-body van het intake-bericht waaruit dit document komt (migratie 0069), of None
    (upload zonder mail, of bericht van vóór 0069)."""
    if document.intake_bericht_id is None:
        return None
    from app.intake.models import IntakeBericht

    bericht = session.get(IntakeBericht, document.intake_bericht_id)
    return bericht.body_tekst if bericht is not None else None


@dataclass(frozen=True)
class HerkomstMail:
    """Blok "Uit de e-mail" op het controlescherm (feedbackronde 25-08 deel 3 punt 1b)."""

    afzender: str | None
    onderwerp: str | None
    ontvangen_op: datetime | None
    body_tekst: str | None
    bron: str


@dataclass(frozen=True)
class DocumentDetail:
    document: Document
    gebeurtenissen: list[DocumentGebeurtenis]
    veldvoorstel: dict | None
    duplicaat_referentie: DuplicaatReferentie | None
    herkomst_mail: HerkomstMail | None = None


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
        herkomst_mail = None
        if document.intake_bericht_id is not None:
            from app.intake.models import IntakeBericht

            bericht = session.get(IntakeBericht, document.intake_bericht_id)
            if bericht is not None:
                herkomst_mail = HerkomstMail(
                    afzender=bericht.afzender,
                    onderwerp=bericht.onderwerp,
                    ontvangen_op=bericht.ontvangen_op,
                    body_tekst=bericht.body_tekst,
                    bron=bericht.bron,
                )

    return DocumentDetail(
        document=document,
        gebeurtenissen=gebeurtenissen,
        veldvoorstel=veldvoorstel,
        duplicaat_referentie=duplicaat_referentie,
        herkomst_mail=herkomst_mail,
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
    wachtrij: ExtractieWachtrij | None = None,
) -> DocumentStatus:
    """ "Opnieuw extraheren" (timeout-fix 2026-07-10): een transiënte AI-fout (timeout, 529) laat
    het document met een lege prefill op te_controleren achter — deze actie draait de extractie
    opnieuw zonder her-upload. Zelfde klein-vs-groot-routing als de upload: klein synchroon
    (te_controleren -> extractie_bezig -> te_controleren), groot via de wachtrij — juist de
    her-extractie van een monsterfactuur was de aanleiding voor de async-route. Tijdlijn +
    audit_event per stap; AVG-gate en key-check gelden onverkort opnieuw. Alleen voor PDF's (UBL
    is deterministisch — opnieuw parsen levert per definitie hetzelfde op) en alleen vanaf
    te_controleren of handmatig_afmaken (daarna is het voorstel mensenwerk)."""
    opslag = opslag or _standaard_opslag()
    naar_wachtrij = False
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
        inhoud = opslag.lezen(pad=document.opslag_pad)
        wachtrij_detail = _groot_document_detail(session, document=document, inhoud=inhoud)
        if wachtrij_detail is not None:
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_WACHTRIJ,
                actor_id=actor_id,
                detail=wachtrij_detail,
            )
            naar_wachtrij = True
        else:
            _start_extractie(session, document=document, actor_id=actor_id, opslag=opslag)
        eind_status = document.status
        soort = document.soort

    if naar_wachtrij:
        (wachtrij or _standaard_wachtrij()).enqueue(administratie_id=administratie_id, document_id=document_id)
    else:
        _na_extractie_hook(administratie_id=administratie_id, document_id=document_id, soort=soort)
    return eind_status


def haal_bijlage_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
    vorm: str = "beeld",
) -> tuple[bytes, str, str]:
    """Retourneert (inhoud, bestandsnaam, content_type). `vorm="beeld"` (default) = wat een mens
    moet zien (`documenten/beeld.py`: bron-PDF naast een UBL, anders de in de UBL ingesloten PDF,
    anders het hoofdbestand); `vorm="data"` = altijd het opgeslagen hoofdbestand (de UBL)."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        bestanden = BestandenSnapshot.van(document)

    if vorm == "data":
        return opslag.lezen(pad=bestanden.opslag_pad), bestanden.bestandsnaam, content_type_voor(bestanden.bestandsnaam)
    beeld = bepaal_beeld(bestanden, opslag=opslag)
    return beeld.inhoud, beeld.bestandsnaam, beeld.content_type


__all__ = ["beeld_is_bron"]  # her-export voor bestaande aanroepers (intake/verzamelbak.py e.a.)
