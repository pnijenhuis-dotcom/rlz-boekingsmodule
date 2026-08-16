"""Handmatige accordeur-herinnering per document (beheer-mini 2026-08-16, migratie 0053).

Kantoor stuurt vanaf de klantpagina/het controlescherm per direct een extra herinnering aan de
accordeur die aan de beurt is voor dát document — push, anders mail (gedeelde kanaalkeuze in
app/berichten/verzending.py). Remmen: max één handmatige herinnering per document per dag
(Europe/Amsterdam; DB-uniek + claim-vóór-verzenden — een mislukte of overgeslagen poging mag
dezelfde dag wél opnieuw, er is dan aantoonbaar niets bezorgd), audit + tijdlijnvermelding op
elke verzending, "laatst herinnerd" zichtbaar in de UI.

HARD PRINCIPE: de link is een deep-link naar de PWA (/accordeur?document=<id>) — goedkeuren
zonder inloggen bestaat bewust niet."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.accordering.models import (
    AccorderingStap,
    AccorderingStatus,
    DocumentAccordering,
    DocumentHerinnering,
)
from app.accordering.service import (
    AccorderingFout,
    GeenOpenAccordering,
    KantoorActieVereist,
    _eerstvolgende_open_stap,
)
from app.berichten import verzending
from app.berichten.models import HerinneringStatus
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session

TIJDZONE = ZoneInfo("Europe/Amsterdam")


class AlHerinnerdVandaag(AccorderingFout):
    """Dagrem: er is vandaag al een handmatige herinnering voor dit document verzonden."""


class GeenActieveAccordeur(AccorderingFout):
    """De accordeur die aan de beurt is, is geen actieve klant-accordeur (meer)."""


class HerinneringVerzendingMislukt(AccorderingFout):
    """Verzenden is aantoonbaar mislukt — zichtbaar voor het kantoor, opnieuw proberen mag."""


@dataclass(frozen=True)
class HerinneringResultaat:
    document_id: uuid.UUID
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str
    verzonden_op: datetime
    kanaal: str


def _vandaag() -> date:
    return datetime.now(TIJDZONE).date()


def bericht_teksten(document_id: uuid.UUID) -> tuple[str, str, str, str]:
    """(onderwerp, pushtekst, mailtekst, push_url) — zelfde toon als de dagelijkse herinnering,
    maar met deep-link naar het specifieke document."""
    pad = f"/accordeur?document={document_id}"
    onderwerp = "Herinnering: er wacht een factuur op je akkoord"
    pushtekst = "Herinnering: er wacht een factuur op je akkoord."
    link = f"{settings.app_basis_url.rstrip('/')}{pad}"
    mailtekst = (
        "Beste,\n\n"
        "Er wacht nog een factuur op je akkoord.\n\n"
        f"Open de app om te beoordelen:\n{link}\n\n"
        "Deze link opent alleen de app — goedkeuren gebeurt altijd ín de app, na ontgrendelen.\n\n"
        "Administratiekantoor Nijenhuis"
    )
    return onderwerp, pushtekst, mailtekst, pad


def stuur_handmatige_herinnering(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, actor_rol: str
) -> HerinneringResultaat:
    if actor_rol == GebruikerRol.KLANT_ACCORDEUR.value:
        raise KantoorActieVereist("Herinneren is een kantooractie")

    vandaag = _vandaag()

    # Stap 1 — valideren + dagrij claimen (eigen transactie: een crash tijdens het verzenden
    # laat de claim op 'bezig' staan en de dagrem intact — nooit dubbel).
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        accordering = session.scalars(
            select(DocumentAccordering).where(
                DocumentAccordering.document_id == document_id,
                DocumentAccordering.status == AccorderingStatus.OPEN.value,
            )
        ).first()
        if accordering is None:
            raise GeenOpenAccordering("Er loopt geen accorderingsronde voor dit document")
        stappen = list(
            session.scalars(select(AccorderingStap).where(AccorderingStap.accordering_id == accordering.id))
        )
        stap = _eerstvolgende_open_stap(stappen)
        if stap is None:
            raise GeenOpenAccordering("Alle lagen zijn al besloten")
        accordeur = session.get(Gebruiker, stap.accordeur_gebruiker_id)
        if (
            accordeur is None
            or accordeur.rol != GebruikerRol.KLANT_ACCORDEUR
            or accordeur.status != GebruikerStatus.ACTIEF
            or accordeur.gepseudonimiseerd_op is not None
        ):
            raise GeenActieveAccordeur(
                "De accordeur die aan de beurt is, is geen actieve klant-accordeur — controleer het account"
            )
        session.expunge(accordeur)

        bestaande = session.scalars(
            select(DocumentHerinnering).where(
                DocumentHerinnering.document_id == document_id,
                DocumentHerinnering.datum == vandaag,
            )
        ).first()
        if bestaande is not None:
            if bestaande.status == HerinneringStatus.VERZONDEN.value:
                raise AlHerinnerdVandaag("Vandaag is er al een herinnering voor dit document verstuurd")
            if bestaande.status == HerinneringStatus.BEZIG.value:
                raise AlHerinnerdVandaag(
                    "Er staat een onafgemaakte herinnering voor vandaag (afgebroken poging) — "
                    "morgen kan het opnieuw"
                )
            # mislukt/overgeslagen: aantoonbaar niets bezorgd — opnieuw claimen mag.
            bestaande.status = HerinneringStatus.BEZIG.value
            bestaande.accordeur_gebruiker_id = accordeur.id
            bestaande.verzonden_door = actor_id
            herinnering_id = bestaande.id
        else:
            rij = DocumentHerinnering(
                administratie_id=administratie_id,
                document_id=document_id,
                accordeur_gebruiker_id=accordeur.id,
                datum=vandaag,
                verzonden_door=actor_id,
            )
            session.add(rij)
            try:
                session.flush()
            except IntegrityError as exc:
                raise AlHerinnerdVandaag(
                    "Vandaag is er al een herinnering voor dit document verstuurd"
                ) from exc
            herinnering_id = rij.id

    # Stap 2 — verzenden (geen DB-werk).
    onderwerp, pushtekst, mailtekst, pad = bericht_teksten(document_id)
    uitkomst = verzending.verstuur_push_anders_mail(
        accordeur, onderwerp=onderwerp, pushtekst=pushtekst, mailtekst=mailtekst, url=pad
    )

    # Stap 3 — afronden + audit + tijdlijn.
    now = datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(DocumentHerinnering, herinnering_id)
        if rij is not None:
            rij.status = uitkomst.status.value
            rij.kanaal = uitkomst.kanaal.value if uitkomst.kanaal else None
            rij.detail = uitkomst.detail
            if uitkomst.status == HerinneringStatus.VERZONDEN:
                rij.verzonden_op = now
        if uitkomst.status == HerinneringStatus.VERZONDEN:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document_herinnering",
                record_id=herinnering_id,
                actie="accordering_herinnering_verstuurd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "document_id": str(document_id),
                    "accordeur": str(accordeur.id),
                    "kanaal": uitkomst.kanaal.value if uitkomst.kanaal else None,
                },
                administratie_id=administratie_id,
            )
            # Tijdlijn-vermelding zonder statusovergang (patroon staande-regel-akkoord).
            from app.documenten.models import Document, DocumentGebeurtenis

            document = session.get(Document, document_id)
            if document is not None:
                session.add(
                    DocumentGebeurtenis(
                        id=uuid.uuid4(),
                        document_id=document_id,
                        van_status=document.status,
                        naar_status=document.status,
                        actor_id=actor_id,
                        detail={
                            "accordering_herinnering": {
                                "accordeur": str(accordeur.id),
                                "kanaal": uitkomst.kanaal.value if uitkomst.kanaal else None,
                            }
                        },
                    )
                )

    if uitkomst.status != HerinneringStatus.VERZONDEN:
        detail = uitkomst.detail or {}
        raise HerinneringVerzendingMislukt(
            f"Herinnering niet bezorgd: {detail.get('reden') or detail.get('fout') or 'onbekende fout'} — "
            f"opnieuw proberen mag"
        )

    return HerinneringResultaat(
        document_id=document_id,
        accordeur_gebruiker_id=accordeur.id,
        accordeur_naam=accordeur.naam,
        verzonden_op=now,
        kanaal=uitkomst.kanaal.value if uitkomst.kanaal else "",
    )


def laatst_herinnerd_per_document(*, administratie_id: uuid.UUID) -> dict[uuid.UUID, datetime]:
    """document_id -> laatste geslaagde handmatige herinnering — voedt "laatst herinnerd" op de
    klantpagina en in de accorderingssectie."""
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(DocumentHerinnering.document_id, func.max(DocumentHerinnering.verzonden_op))
            .where(
                DocumentHerinnering.administratie_id == administratie_id,
                DocumentHerinnering.status == HerinneringStatus.VERZONDEN.value,
            )
            .group_by(DocumentHerinnering.document_id)
        ).all()
    return {document_id: verzonden_op for document_id, verzonden_op in rijen if verzonden_op is not None}
