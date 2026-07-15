"""Afwijzen-met-verplichte-reden (CLAUDE.md domeinbeslissing "Afwijzen = verplichte reden,
blijft zichtbaar", mockup #afwijsmodal): afwijzen zet het document op DocumentStatus.AFGEWEZEN —
zichtbaar in de werkvoorraad als "Afgewezen — ter controle" mét reden en wie afwees, en boeken
is geblokkeerd (boeken.py::_KAN_BOEKPOGING_STARTEN_VANUIT bevat afgewezen niet). Heropenen zet
het document terug naar exact de status van vóór de afwijzing (afwijzing.status_voor_afwijzing)
— zelfde status_voor_*-patroon als de vragenworkflow (app/documenten/vragen.py), waarvan ook de
toewijzings-default (administratie-eigenaar) en de scope-afdwinging hergebruikt worden."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Afwijzing, AfwijzingStatus, Document, DocumentStatus
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.vragen import (
    GeenToewijzingMogelijk,
    _controleer_toegewezene_scope,
)


class AfwijzingFout(Exception):
    """Basis voor domeinfouten in de afwijzen-workflow."""


class RedenVerplicht(AfwijzingFout):
    """Een afwijzing zonder reden wordt geweigerd — de kern van de domeinbeslissing; ook op
    DB-niveau afgedwongen (CHECK afwijzing_reden_niet_leeg, migratie 0023)."""


class GeenOpenAfwijzing(AfwijzingFout):
    """Heropenen kan alleen een document met een open afwijzing — een document dat via een
    ander pad op afgewezen belandde (zonder afwijzing-rij) heeft geen vastgelegde herkomst om
    naar terug te keren."""


# Zelfde herstelbare herkomsten als de vragenworkflow (vragen._HERSTELBARE_HERKOMSTEN), om
# dezelfde reden: heropenen moet de herkomst exact kunnen herstellen, dus élke toegestane
# herkomst heeft een afgewezen -> herkomst-overgang in de statusmachine. De statusmachine kent
# daarnaast bredere ingangen naar afgewezen (ontvangen/wachtrij/bezig/vraag_open/
# niet_toegewezen — o.a. gereserveerd voor de verzamelbak- en tenaamstellings-flows); die
# hebben geen herstel-terugweg en worden hier bewust geweigerd, fail-closed. Een vraag_open-
# document eerst beantwoorden of intrekken, dan afwijzen.
_HERSTELBARE_HERKOMSTEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
    }
)


@dataclass(frozen=True)
class AfwijzingData:
    """Detached snapshot van een afwijzing-rij (de sessie sluit bij het verlaten van de
    service)."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_status: DocumentStatus
    reden: str
    status: str
    status_voor_afwijzing: str
    afgewezen_door: uuid.UUID
    afgewezen_op: datetime
    toegewezen_aan: uuid.UUID
    heropend_door: uuid.UUID | None
    heropend_op: datetime | None


def _naar_data(afwijzing: Afwijzing, document: Document) -> AfwijzingData:
    return AfwijzingData(
        id=afwijzing.id,
        document_id=afwijzing.document_id,
        document_status=document.status,
        reden=afwijzing.reden,
        status=afwijzing.status,
        status_voor_afwijzing=afwijzing.status_voor_afwijzing,
        afgewezen_door=afwijzing.afgewezen_door,
        afgewezen_op=afwijzing.afgewezen_op,
        toegewezen_aan=afwijzing.toegewezen_aan,
        heropend_door=afwijzing.heropend_door,
        heropend_op=afwijzing.heropend_op,
    )


def wijs_af(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    reden: str,
    toegewezen_aan: uuid.UUID | None = None,
) -> AfwijzingData:
    """Wijst een document af: reden verplicht, document -> afgewezen (blijft zichtbaar in de
    werkvoorraad, boeken geblokkeerd), toewijzing ("Ter controle naar", mockup #afwijsmodal)
    default naar de administratie-eigenaar. Document.toegewezen_aan volgt mee (werkvoorraad-
    kolom "Toegewezen") — zelfde gedrag als een vraag."""
    reden_tekst = reden.strip()
    if not reden_tekst:
        raise RedenVerplicht("Een afwijzing zonder reden is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status not in _HERSTELBARE_HERKOMSTEN:
            raise OngeldigeStatusovergang(
                f"Vanuit status {document.status.value} kan niet afgewezen worden"
            )

        toegewezene = toegewezen_aan
        if toegewezene is None:
            administratie = session.get(Administratie, administratie_id)
            toegewezene = administratie.eigenaar_gebruiker_id if administratie else None
        if toegewezene is None:
            raise GeenToewijzingMogelijk(
                "Deze administratie heeft geen eigenaar — wijs de controle expliciet toe of stel een eigenaar in"
            )
        _controleer_toegewezene_scope(session, gebruiker_id=toegewezene, administratie_id=administratie_id)

        afwijzing = Afwijzing(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            document_id=document_id,
            afgewezen_door=actor_id,
            reden=reden_tekst,
            toegewezen_aan=toegewezene,
            status_voor_afwijzing=document.status.value,
        )
        session.add(afwijzing)
        # De overgang valideert tegen de statusmachine vóór er iets persisteert — een afwijzing
        # op bv. een geboekt document rolt de hele transactie (incl. de afwijzing-rij) terug.
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.AFGEWEZEN,
            actor_id=actor_id,
            detail={
                "afwijzing_id": str(afwijzing.id),
                "reden": reden_tekst,
                "toegewezen_aan": str(toegewezene),
                "status_voor_afwijzing": afwijzing.status_voor_afwijzing,
            },
        )
        document.toegewezen_aan = toegewezene
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="afwijzing",
            record_id=afwijzing.id,
            actie="document_afgewezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "reden": reden_tekst,
                "toegewezen_aan": str(toegewezene),
                "status_voor_afwijzing": afwijzing.status_voor_afwijzing,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(afwijzing, document)


def heropen(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> AfwijzingData:
    """Heropent een afgewezen document: de afwijzing-rij gaat naar heropend (nooit een delete)
    en het document terug naar exact de herkomst-status van vóór de afwijzing
    (afwijzing.status_voor_afwijzing) — een klaar_om_te_boeken- of handmatig_afmaken-document
    verliest zijn context dus niet. Document.toegewezen_aan gaat terug naar leeg (de toewijzing
    hoorde bij de open afwijzing) — zelfde gedrag als beantwoorden/intrekken van een vraag."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        afwijzing = session.scalars(
            select(Afwijzing).where(
                Afwijzing.document_id == document_id, Afwijzing.status == AfwijzingStatus.OPEN.value
            )
        ).first()
        if afwijzing is None:
            raise GeenOpenAfwijzing("Dit document heeft geen open afwijzing om te heropenen")

        afwijzing.status = AfwijzingStatus.HEROPEND.value
        afwijzing.heropend_door = actor_id
        afwijzing.heropend_op = datetime.now(UTC)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus(afwijzing.status_voor_afwijzing),
            actor_id=actor_id,
            detail={"afwijzing_id": str(afwijzing.id), "afwijzing_heropend": True},
        )
        document.toegewezen_aan = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="afwijzing",
            record_id=afwijzing.id,
            actie="document_heropend",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": AfwijzingStatus.OPEN.value},
            nieuwe_waarde={
                "status": AfwijzingStatus.HEROPEND.value,
                "heropend_door": str(actor_id),
                "document_hersteld_naar": afwijzing.status_voor_afwijzing,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(afwijzing, document)


def open_afwijzingen(*, administratie_id: uuid.UUID) -> dict[uuid.UUID, AfwijzingData]:
    """Open afwijzingen per document-id — voedt de werkvoorraad-chip "Afgewezen — ter controle"
    met reden + wie afwees (mockup-klantpagina) zonder N+1-verkeer vanuit de lijst."""
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Afwijzing, Document)
            .join(Document, Afwijzing.document_id == Document.id)
            .where(
                Afwijzing.administratie_id == administratie_id,
                Afwijzing.status == AfwijzingStatus.OPEN.value,
            )
        )
        return {afwijzing.document_id: _naar_data(afwijzing, document) for afwijzing, document in rijen}


def open_afwijzing_van(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> AfwijzingData | None:
    """De open afwijzing van één document, of None — voedt de afgewezen-banner + heropenen-knop
    op het controlescherm."""
    with scoped_session(administratie_id) as session:
        rij = session.execute(
            select(Afwijzing, Document)
            .join(Document, Afwijzing.document_id == Document.id)
            .where(
                Afwijzing.document_id == document_id,
                Afwijzing.status == AfwijzingStatus.OPEN.value,
            )
        ).first()
        if rij is None:
            return None
        afwijzing, document = rij
        return _naar_data(afwijzing, document)
