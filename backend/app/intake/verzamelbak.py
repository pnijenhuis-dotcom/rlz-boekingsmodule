"""Verzamelbak "Niet toegewezen" (mockup werkvoorraad-paneel): alles wat niet eenduidig aan een
administratie koppelt, zichtbaar tot een mens beslist. Toewijzen leert het toewijzings-geheugen
en start de normale extractieflow onder de AVG-gate van de gekozen administratie; "hoort niet
bij ons" vergt een verplichte reden en blijft terugvindbaar (status afgewezen) — nooit een
delete."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.mime import content_type_voor
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import (
    DocumentNietGevonden,
    _schrijf_overgang,
    _standaard_opslag,
    start_extractie_na_toewijzing,
)
from app.documenten.storage import DocumentOpslag
from app.intake.models import IntakeSplitsing, IntakeSplitsingStatus
from app.intake.toewijzing import leer_toewijzing


class VerzamelbakFout(Exception):
    pass


class DocumentNietInVerzamelbak(VerzamelbakFout):
    """De actie kan alleen op een document met status niet_toegewezen zonder administratie."""


class RedenVerplicht(VerzamelbakFout):
    """ "Hoort niet bij ons" zonder reden wordt geweigerd (mockup: verplichte reden)."""


class OnbekendeAdministratie(VerzamelbakFout):
    pass


@dataclass(frozen=True)
class VerzamelbakItem:
    document_id: uuid.UUID
    bestandsnaam: str
    soort: str
    bron: str
    afzender_hint: str | None
    tenaamstelling: str | None
    suggestie_administratie_id: uuid.UUID | None
    suggestie_bron: str | None
    reden: str | None
    aangemaakt_op: datetime
    splitsing_id: uuid.UUID | None
    splitsing_voorstel: dict | None


def haal_bijlage_op(*, document_id: uuid.UUID, opslag: DocumentOpslag | None = None) -> tuple[bytes, str, str]:
    """Bestand van een VERZAMELBAK-document (besluit Peter 25-08, punt D1: preview-popup in de
    verzamelbak). Verzamelbak-documenten hebben geen administratie (RLS-scope NULL), dus de
    administratie-gescoopte bestand-route past niet; deze leesroute is fail-closed beperkt tot
    documenten die écht nog in de verzamelbak staan (administratie NULL + status
    niet_toegewezen) — een al toegewezen document loopt via zijn administratie-route.
    Retourneert (inhoud, bestandsnaam, content_type)."""
    opslag = opslag or _standaard_opslag()
    with scoped_session(None) as session:
        document = session.get(Document, document_id)
        if (
            document is None
            or document.administratie_id is not None
            or document.status != DocumentStatus.NIET_TOEGEWEZEN
        ):
            raise DocumentNietGevonden(f"Geen verzamelbak-document: {document_id}")
        opslag_pad = document.opslag_pad
        bestandsnaam = document.bestandsnaam
    inhoud = opslag.lezen(pad=opslag_pad)
    content_type = content_type_voor(bestandsnaam)
    return inhoud, bestandsnaam, content_type


def lijst_verzamelbak() -> list[VerzamelbakItem]:
    """Alle open verzamelbak-documenten (administratie NULL, status niet_toegewezen), incl. een
    eventueel openstaand splitsingsvoorstel — nieuwste eerst."""
    with scoped_session(None) as session:
        documenten = session.scalars(
            select(Document)
            .where(Document.administratie_id.is_(None), Document.status == DocumentStatus.NIET_TOEGEWEZEN)
            .order_by(Document.aangemaakt_op.desc())
        ).all()
        splitsingen = {
            s.bron_document_id: s
            for s in session.scalars(
                select(IntakeSplitsing).where(
                    IntakeSplitsing.bron_document_id.in_([d.id for d in documenten]),
                    IntakeSplitsing.status == IntakeSplitsingStatus.VOORGESTELD.value,
                )
            )
        }
        items = []
        for document in documenten:
            # De intake-reden staat in de niet_toegewezen-overgang in de tijdlijn; hier volstaat
            # het meest recente detail via een lichte lookup per document (verzamelbak is klein).
            splitsing = splitsingen.get(document.id)
            items.append(
                VerzamelbakItem(
                    document_id=document.id,
                    bestandsnaam=document.bestandsnaam,
                    soort=document.soort,
                    bron=document.bron.value,
                    afzender_hint=document.afzender_hint,
                    tenaamstelling=document.tenaamstelling,
                    suggestie_administratie_id=document.toewijzing_suggestie_administratie_id,
                    suggestie_bron=document.toewijzing_suggestie_bron,
                    reden=None,
                    aangemaakt_op=document.aangemaakt_op,
                    splitsing_id=splitsing.id if splitsing else None,
                    splitsing_voorstel=splitsing.voorstel if splitsing else None,
                )
            )
        return items


@dataclass(frozen=True)
class VerzamelbakActieResultaat:
    """Uitkomst van toewijzen / hoort-niet-bij-ons (avondrun 26-08, optimistisch paneel):
    `al_verwerkt` = de actie was al eerder gedaan (tweede klik, collega, retry ná time-out) —
    géén fout, niets opnieuw gedaan, rustig gemeld; de DB blijft de bron van waarheid."""

    status: DocumentStatus
    al_verwerkt: bool = False
    melding: str | None = None


def _menselijke_toestand(document: Document) -> str:
    """Geen enum-jargon in een melding aan de gebruiker (de oude tekst "staat niet (meer) in de
    verzamelbak (status: ontvangen)" toonde een geslaagde actie als fout)."""
    if document.status == DocumentStatus.AFGEWEZEN and document.administratie_id is None:
        return "is al afgehandeld als 'hoort niet bij ons'"
    if document.status == DocumentStatus.GESPLITST:
        return "is intussen gesplitst in losse facturen"
    if document.administratie_id is not None:
        return "is intussen al toegewezen aan een administratie"
    return f"is intussen al verwerkt ({document.status.value.replace('_', ' ')})"


NIET_MEER_ZICHTBAAR_MELDING = (
    "Dit document staat niet (meer) in de verzamelbak — waarschijnlijk heeft een collega het "
    "intussen aan een andere administratie toegewezen. Ververs de lijst."
)


def _laad_verzamelbak_document(session, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(NIET_MEER_ZICHTBAAR_MELDING)
    if document.administratie_id is not None or document.status != DocumentStatus.NIET_TOEGEWEZEN:
        raise DocumentNietInVerzamelbak(f"Dit document {_menselijke_toestand(document)} — er is niets gewijzigd.")
    return document


def wijs_toe(
    *, document_id: uuid.UUID, administratie_id: uuid.UUID, actor_id: uuid.UUID
) -> VerzamelbakActieResultaat:
    """Handmatige toewijzing vanuit de verzamelbak: administratie zetten, toewijzings-geheugen
    leren (mockup: "wordt onthouden"), terug naar ontvangen en de normale extractieflow starten
    (AVG-gate van de gekozen administratie geldt vanaf hier).

    Idempotent (avondrun 26-08): is het document al aan DEZE administratie toegewezen (tweede
    klik, retry ná een time-out, collega), dan gebeurt er niets en komt `al_verwerkt=True` terug —
    geen fout. Toegewezen aan een ándere administratie = onzichtbaar onder RLS →
    DocumentNietGevonden met een leesbare melding (router: 404)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OnbekendeAdministratie(f"Onbekende administratie: {administratie_id}")
        bestaand = session.get(Document, document_id)
        if (
            bestaand is not None
            and bestaand.administratie_id == administratie_id
            and bestaand.status != DocumentStatus.NIET_TOEGEWEZEN
        ):
            return VerzamelbakActieResultaat(
                status=bestaand.status,
                al_verwerkt=True,
                melding=f"Was al toegewezen aan {administratie.naam} — niets opnieuw gedaan.",
            )
        document = _laad_verzamelbak_document(session, document_id)
        document.administratie_id = administratie_id
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.ONTVANGEN,
            actor_id=actor_id,
            detail={"toegewezen_aan_administratie": str(administratie_id), "vanuit": "verzamelbak"},
        )
        leer_toewijzing(
            session,
            administratie_id=administratie_id,
            actor_id=actor_id,
            tenaamstelling=document.tenaamstelling,
            afzender=document.afzender_hint,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="verzamelbak_toegewezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"administratie_id": str(administratie_id)},
            administratie_id=administratie_id,
        )

    eind_status = start_extractie_na_toewijzing(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
    )
    return VerzamelbakActieResultaat(status=eind_status)


def hoort_niet_bij_ons(*, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str) -> VerzamelbakActieResultaat:
    """ "Hoort niet bij ons" — verplichte reden, document blijft terugvindbaar als afgewezen
    (mockup: "blijft in het archief terugvindbaar"). Het toewijzings-geheugen leert hier bewust
    níéts (een verkeerd geadresseerd document is geen betrouwbare hint).

    Idempotent (avondrun 26-08): al afgewezen-zonder-administratie (= eerder "hoort niet bij
    ons") → `al_verwerkt=True`, niets opnieuw vastgelegd — de eerste reden blijft de reden."""
    schone_reden = reden.strip() if reden else ""
    if not schone_reden:
        raise RedenVerplicht("'Hoort niet bij ons' vereist een reden")
    with scoped_session(None, actor_id=actor_id) as session:
        bestaand = session.get(Document, document_id)
        if bestaand is not None and bestaand.administratie_id is None and bestaand.status == DocumentStatus.AFGEWEZEN:
            return VerzamelbakActieResultaat(
                status=bestaand.status,
                al_verwerkt=True,
                melding="Was al vastgelegd als 'hoort niet bij ons' — niets opnieuw gedaan.",
            )
        document = _laad_verzamelbak_document(session, document_id)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.AFGEWEZEN,
            actor_id=actor_id,
            detail={"hoort_niet_bij_ons": True, "reden": schone_reden},
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="verzamelbak_hoort_niet_bij_ons",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": schone_reden},
            administratie_id=None,
        )
        return VerzamelbakActieResultaat(status=document.status)
