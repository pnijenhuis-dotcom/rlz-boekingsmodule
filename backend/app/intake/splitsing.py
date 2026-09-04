"""Multi-factuur-splitsing: bevestigen of afwijzen van het AI-voorstel — ALTIJD een menselijke
handeling (mockup: "de voorgestelde splitsing zie je altijd eerst ter controle"). Bevestigen
splitst de PDF deterministisch (pypdf, per bevestigd paginabereik — de mens kan de bereiken
aanpassen), maakt per deel een kind-document dat de normale intake-toewijzing doorloopt
(eenduidig → werkvoorraad, anders → verzamelbak) en zet het bron-document op de terminale
status 'gesplitst' — het origineel blijft bestaan en terugvindbaar."""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pypdf import PdfReader, PdfWriter

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.pdf import tel_paginas
from app.documenten.service import _schrijf_overgang, _standaard_opslag
from app.documenten.storage import DocumentOpslag
from app.extractie.splitsing import FactuurSegment, valideer_segmenten
from app.intake import splitsing_uitsluiting
from app.intake.models import IntakeBericht, IntakeSplitsing, IntakeSplitsingStatus
from app.intake.toewijzing import bepaal_toewijzing


class SplitsingFout(Exception):
    pass


class SplitsingNietGevonden(SplitsingFout):
    pass


class SplitsingNietOpen(SplitsingFout):
    """Alleen een voorgesteld (nog niet besloten) splitsingsvoorstel kan bevestigd/afgewezen."""


class OngeldigeSplitsing(SplitsingFout):
    """De (aangepaste) paginabereiken doorstaan de deterministische validatie niet."""


@dataclass(frozen=True)
class SplitsDeelInput:
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None


@dataclass(frozen=True)
class SplitsDeelResultaat:
    document_id: uuid.UUID
    bestandsnaam: str
    uitkomst: str  # 'toegewezen' | 'verzamelbak'
    administratie_id: uuid.UUID | None


def _pdf_deel(inhoud: bytes, *, start: int, eind: int) -> bytes:
    """Deterministische pagina-extractie (1-gebaseerd, inclusief)."""
    lezer = PdfReader(io.BytesIO(inhoud))
    schrijver = PdfWriter()
    for index in range(start - 1, eind):
        schrijver.add_page(lezer.pages[index])
    buffer = io.BytesIO()
    schrijver.write(buffer)
    return buffer.getvalue()


def _open_splitsing(session, splitsing_id: uuid.UUID) -> IntakeSplitsing:
    splitsing = session.get(IntakeSplitsing, splitsing_id)
    if splitsing is None:
        raise SplitsingNietGevonden(f"Onbekend splitsingsvoorstel: {splitsing_id}")
    if splitsing.status != IntakeSplitsingStatus.VOORGESTELD.value:
        raise SplitsingNietOpen(f"Dit splitsingsvoorstel is al {splitsing.status}")
    return splitsing


def bevestig_splitsing(
    *,
    splitsing_id: uuid.UUID,
    actor_id: uuid.UUID,
    delen: list[SplitsDeelInput],
    opslag: DocumentOpslag | None = None,
) -> list[SplitsDeelResultaat]:
    """Bevestigt de splitsing met de (eventueel aangepaste) paginabereiken. Elk deel doorloopt
    dezelfde toewijzingsregels als een verse intake-bijlage — nooit auto-toewijzen bij twijfel."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(None) as session:
        splitsing = _open_splitsing(session, splitsing_id)
        bron_document = session.get(Document, splitsing.bron_document_id)
        assert bron_document is not None
        if bron_document.status != DocumentStatus.NIET_TOEGEWEZEN or bron_document.administratie_id is not None:
            raise SplitsingNietOpen(
                f"Bron-document staat niet (meer) in de verzamelbak (status: {bron_document.status.value})"
            )
        bron_pad = bron_document.opslag_pad
        bron_naam = bron_document.bestandsnaam
        bron_id = bron_document.id
        bron_kanaal = bron_document.bron
        intake_bericht_id = bron_document.intake_bericht_id
        afzender = bron_document.afzender_hint
        # Mail-body als toewijzingshint voor de delen (punt 1c) — dezelfde body als het bron-document.
        body_hint = (
            session.get(IntakeBericht, intake_bericht_id).body_tekst if intake_bericht_id is not None else None
        )

    inhoud = opslag.lezen(pad=bron_pad)
    paginas = tel_paginas(inhoud) or 1
    segmenten = [
        FactuurSegment(
            start_pagina=deel.start_pagina,
            eind_pagina=deel.eind_pagina,
            tenaamstelling=deel.tenaamstelling,
            leverancier=None,
            factuurnummer=None,
            zekerheid=1.0,  # menselijk bevestigd
        )
        for deel in delen
    ]
    reden = valideer_segmenten(segmenten, paginas=paginas)
    if reden is not None:
        raise OngeldigeSplitsing(f"Splitsing ongeldig: {reden}")
    if len(segmenten) < 2:
        raise OngeldigeSplitsing("Een splitsing vereist minstens twee delen — wijs anders het voorstel af")

    stam = bron_naam.removesuffix(".pdf").removesuffix(".PDF")
    resultaten: list[SplitsDeelResultaat] = []
    for volgnummer, segment in enumerate(segmenten, start=1):
        deel_bytes = _pdf_deel(inhoud, start=segment.start_pagina, eind=segment.eind_pagina)
        deel_naam = f"{stam}-deel{volgnummer}.pdf"
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(
                session, tenaamstelling=segment.tenaamstelling, afzender=afzender, body_hint=body_hint
            )
        if besluit.administratie_id is not None:
            upload = documenten_service.upload_document(
                administratie_id=besluit.administratie_id,
                bestandsnaam=deel_naam,
                inhoud=deel_bytes,
                actor_id=actor_id,
                opslag=opslag,
                bron=bron_kanaal,
                intake_bericht_id=intake_bericht_id,
                afzender_hint=afzender,
                tenaamstelling=segment.tenaamstelling,
                gesplitst_uit_id=bron_id,
            )
            resultaten.append(
                SplitsDeelResultaat(
                    document_id=upload.document_id,
                    bestandsnaam=deel_naam,
                    uitkomst="toegewezen",
                    administratie_id=besluit.administratie_id,
                )
            )
        else:
            document_id = documenten_service.registreer_niet_toegewezen_document(
                bestandsnaam=deel_naam,
                inhoud=deel_bytes,
                actor_id=actor_id,
                reden="tenaamstelling_niet_eenduidig_na_splitsing",
                bron=bron_kanaal,
                opslag=opslag,
                intake_bericht_id=intake_bericht_id,
                afzender_hint=afzender,
                tenaamstelling=segment.tenaamstelling,
                gesplitst_uit_id=bron_id,
                suggestie_administratie_id=besluit.suggestie_administratie_id,
                suggestie_bron=besluit.suggestie_bron,
            )
            resultaten.append(
                SplitsDeelResultaat(
                    document_id=document_id, bestandsnaam=deel_naam, uitkomst="verzamelbak", administratie_id=None
                )
            )

    with scoped_session(None, actor_id=actor_id) as session:
        splitsing = session.get(IntakeSplitsing, splitsing_id)
        assert splitsing is not None
        splitsing.status = IntakeSplitsingStatus.BEVESTIGD.value
        splitsing.besloten_door = actor_id
        splitsing.besloten_op = datetime.now(UTC)
        splitsing.besluit_detail = {
            "delen": [
                {
                    "document_id": str(r.document_id),
                    "bestandsnaam": r.bestandsnaam,
                    "uitkomst": r.uitkomst,
                    "administratie_id": str(r.administratie_id) if r.administratie_id else None,
                }
                for r in resultaten
            ]
        }
        bron = session.get(Document, bron_id)
        assert bron is not None
        _schrijf_overgang(
            session,
            document=bron,
            naar=DocumentStatus.GESPLITST,
            actor_id=actor_id,
            detail={"splitsing_id": str(splitsing_id), "delen": len(resultaten)},
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="intake_splitsing",
            record_id=splitsing_id,
            actie="splitsing_bevestigd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=splitsing.besluit_detail,
            administratie_id=None,
        )
    return resultaten


def wijs_splitsing_af(
    *,
    splitsing_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str | None = None,
    onthoud_niet_splitsen: bool = False,
    administratie_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Wijst het splitsingsvoorstel af — het bron-document blijft als één geheel in de
    verzamelbak (kan alsnog handmatig aan één administratie toegewezen worden).

    `onthoud_niet_splitsen` (blok B 04-09): legt daarnaast de regel "mails van ‹afzender van het
    intake-bericht› voor ‹administratie_id› nooit splitsen" vast (`splitsing_uitsluiting.maak_regel`,
    idempotent, geauditeerd) — de leverancier uit het voorstel gaat informatief mee. Geen afzender
    (upload), uitgesloten domein of ontbrekende administratie = fout VÓÓR het afwijzen (alles-of-niets,
    de mens ziet waarom). Geeft het regel-id terug (None zonder vink)."""
    with scoped_session(None, actor_id=actor_id) as session:
        splitsing = _open_splitsing(session, splitsing_id)
        regel_id: uuid.UUID | None = None
        if onthoud_niet_splitsen:
            bron_document = session.get(Document, splitsing.bron_document_id)
            assert bron_document is not None
            leveranciers = [
                s.get("leverancier")
                for s in (splitsing.voorstel or {}).get("facturen", [])
                if isinstance(s, dict) and s.get("leverancier")
            ]
            regel = splitsing_uitsluiting.maak_regel(
                session,
                administratie_id=administratie_id,
                afzender=bron_document.afzender_hint,
                leverancier_naam=leveranciers[0] if leveranciers else None,
                reden=reden,
                actor_id=actor_id,
                bron_splitsing_id=splitsing_id,
            )
            regel_id = regel.id
        splitsing.status = IntakeSplitsingStatus.AFGEWEZEN.value
        splitsing.besloten_door = actor_id
        splitsing.besloten_op = datetime.now(UTC)
        splitsing.besluit_detail = {
            "reden": reden.strip() if reden and reden.strip() else None,
            "nooit_splitsen_regel_id": str(regel_id) if regel_id else None,
        }
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="intake_splitsing",
            record_id=splitsing_id,
            actie="splitsing_afgewezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=splitsing.besluit_detail,
            administratie_id=None,
        )
        return regel_id
