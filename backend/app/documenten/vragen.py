"""Vragenworkflow (CLAUDE.md domeinbeslissing, mockup #vragen + #vraagmodal): een vraag blokkeert
het boeken van het document (DocumentStatus.VRAAG_OPEN — boeken.py laat een boekpoging vanuit die
status niet toe), is toegewezen aan één medewerker (default: de administratie-eigenaar, mockup
Instellingen "Eigenaar (krijgt vragen)") en beantwoorden of intrekken zet het document terug naar
exact de status van vóór de vraag (vraag.status_voor_vraag: te_controleren, handmatig_afmaken of
klaar_om_te_boeken), waarna de normale route naar boeken weer open is. Intrekken en stellen vanuit
klaar_om_te_boeken zijn bewuste uitbreidingen op de goedgekeurde mockup — zie docs/BESLISSINGEN.md.

"Antwoord voedt het geheugen" loopt in v1 via de bestaande boek-leerlus (app/geheugen/leerlus.py):
het antwoord leidt tot een correctie in het boekvoorstel + boeken, en dát legt de gekozen GB/btw
als app-observatie vast — geen apart leer-pad hier. Een doorzoekbare Q&A-kennisbank per crediteur
is een genoteerde latere verrijking (docs/BESLISSINGEN.md).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerAdministratie, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentStatus, Vraag, VraagStatus
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.statusmachine import OngeldigeStatusovergang


class VraagFout(Exception):
    """Basis voor domeinfouten in de vragenworkflow."""


class VraagTekstVerplicht(VraagFout):
    """Een vraag zonder tekst wordt geweigerd — zelfde principe als afwijzen-met-verplichte-reden."""


class AntwoordTekstVerplicht(VraagFout):
    """Beantwoorden zonder antwoordtekst wordt geweigerd."""


class ErIsAlEenOpenVraag(VraagFout):
    """Eén open vraag per document tegelijk (ook op DB-niveau afgedwongen, migratie 0022)."""


class GeenToewijzingMogelijk(VraagFout):
    """Geen expliciete toewijzing én geen administratie-eigenaar — zichtbare fout, geen stille
    default of onbeheerde vraag."""


class ToegewezeneBuitenScope(VraagFout):
    """De beoogde toegewezene is geen actieve gebruiker met toegang tot deze administratie
    (Beheerder is platform-breed en telt altijd als binnen scope)."""


class VraagNietGevonden(VraagFout):
    pass


class VraagNietOpen(VraagFout):
    """De vraag is al beantwoord of ingetrokken — alleen een open vraag kan beantwoord of
    ingetrokken worden."""


# De enige herkomsten waarvandaan een vraag gesteld kan worden: beantwoorden/intrekken moet de
# herkomst exact kunnen herstellen, dus élke toegestane herkomst heeft een vraag_open -> herkomst-
# overgang in de statusmachine. De statusmachine kent daarnaast extractie_bezig -> vraag_open
# (gereserveerd voor een extractie die zelf een vraag opwerpt, geen route hierlangs) — dat pad
# heeft geen herstel-overgang en wordt hier dus bewust geweigerd, fail-closed.
_HERSTELBARE_HERKOMSTEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
    }
)


@dataclass(frozen=True)
class VraagData:
    """Detached snapshot van een vraag-rij (de sessie sluit bij het verlaten van de service)."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_bestandsnaam: str
    document_status: DocumentStatus
    vraag_tekst: str
    status: str
    status_voor_vraag: str
    gesteld_door: uuid.UUID
    gesteld_op: datetime
    toegewezen_aan: uuid.UUID
    antwoord_tekst: str | None
    beantwoord_door: uuid.UUID | None
    beantwoord_op: datetime | None
    ingetrokken_door: uuid.UUID | None
    ingetrokken_op: datetime | None
    ingetrokken_reden: str | None


def _naar_data(vraag: Vraag, document: Document) -> VraagData:
    return VraagData(
        id=vraag.id,
        document_id=vraag.document_id,
        document_bestandsnaam=document.bestandsnaam,
        document_status=document.status,
        vraag_tekst=vraag.vraag_tekst,
        status=vraag.status,
        status_voor_vraag=vraag.status_voor_vraag,
        gesteld_door=vraag.gesteld_door,
        gesteld_op=vraag.gesteld_op,
        toegewezen_aan=vraag.toegewezen_aan,
        antwoord_tekst=vraag.antwoord_tekst,
        beantwoord_door=vraag.beantwoord_door,
        beantwoord_op=vraag.beantwoord_op,
        ingetrokken_door=vraag.ingetrokken_door,
        ingetrokken_op=vraag.ingetrokken_op,
        ingetrokken_reden=vraag.ingetrokken_reden,
    )


def _controleer_toegewezene_scope(session: Session, *, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    """Toewijzen kan alleen aan een actieve gebruiker mét toegang tot deze administratie
    (CLAUDE.md autorisatie: geen scope = geen data — een vraag toewijzen aan iemand die de
    administratie niet mag zien is per definitie fout). Beheerder is platform-breed, zelfde
    bypass als deps.vereis_administratie_scope. Geldt ook voor de default (de administratie-
    eigenaar): een eigenaar wiens scope later is ingetrokken geeft een zichtbare fout, geen
    stille toewijzing aan iemand die er niet meer bij kan."""
    gebruiker = session.get(Gebruiker, gebruiker_id)
    if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
        raise ToegewezeneBuitenScope(f"Toegewezene is geen actieve gebruiker: {gebruiker_id}")
    if gebruiker.rol == GebruikerRol.BEHEERDER:
        return
    if session.get(GebruikerAdministratie, (gebruiker_id, administratie_id)) is None:
        raise ToegewezeneBuitenScope("Toegewezene heeft geen toegang tot deze administratie")


def stel_vraag(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vraag_tekst: str,
    toegewezen_aan: uuid.UUID | None = None,
) -> VraagData:
    """Stelt een vraag over een document: document -> vraag_open (statusmachine bepaalt vanuit
    welke statussen dat mag; boeken is vanuit vraag_open geblokkeerd), toewijzing default naar de
    administratie-eigenaar. Document.toegewezen_aan volgt mee (werkvoorraad-kolom "Toegewezen")."""
    tekst = vraag_tekst.strip()
    if not tekst:
        raise VraagTekstVerplicht("Een vraag zonder tekst is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        # Eerst de open-vraag-check: een tweede vraag op een vraag_open-document verdient de
        # specifieke melding, niet de generieke statusfout.
        open_vraag = session.scalars(
            select(Vraag).where(Vraag.document_id == document_id, Vraag.status == VraagStatus.OPEN.value)
        ).first()
        if open_vraag is not None:
            raise ErIsAlEenOpenVraag("Er staat al een open vraag op dit document")

        if document.status not in _HERSTELBARE_HERKOMSTEN:
            # Zelfde foutsoort als de statusmachine zelf zou geven — de extra poort hier dekt
            # uitsluitend herkomsten mét een toegestane heenweg maar zonder herstel-terugweg
            # (extractie_bezig), zodat een vraag nooit onbeantwoordbaar/onintrekbaar wordt.
            raise OngeldigeStatusovergang(
                f"Vanuit status {document.status.value} kan geen vraag gesteld worden"
            )

        toegewezene = toegewezen_aan
        if toegewezene is None:
            administratie = session.get(Administratie, administratie_id)
            toegewezene = administratie.eigenaar_gebruiker_id if administratie else None
        if toegewezene is None:
            raise GeenToewijzingMogelijk(
                "Deze administratie heeft geen eigenaar — wijs de vraag expliciet toe of stel een eigenaar in"
            )
        _controleer_toegewezene_scope(session, gebruiker_id=toegewezene, administratie_id=administratie_id)

        vraag = Vraag(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            document_id=document_id,
            gesteld_door=actor_id,
            vraag_tekst=tekst,
            toegewezen_aan=toegewezene,
            status_voor_vraag=document.status.value,
        )
        session.add(vraag)
        # De overgang valideert tegen de statusmachine vóór er iets persisteert — een vraag op
        # bv. een geboekt document rolt de hele transactie (incl. de vraag-rij) terug.
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.VRAAG_OPEN,
            actor_id=actor_id,
            detail={
                "vraag_id": str(vraag.id),
                "toegewezen_aan": str(toegewezene),
                "status_voor_vraag": vraag.status_voor_vraag,
            },
        )
        document.toegewezen_aan = toegewezene
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_gesteld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "vraag_tekst": tekst,
                "toegewezen_aan": str(toegewezene),
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(vraag, document)


def _open_vraag_met_document(session, *, administratie_id: uuid.UUID, vraag_id: uuid.UUID) -> tuple[Vraag, Document]:
    """Gedeelde poort van beantwoorden en intrekken: de vraag moet bestaan, van deze
    administratie zijn en nog open staan."""
    vraag = session.get(Vraag, vraag_id)
    if vraag is None or vraag.administratie_id != administratie_id:
        raise VraagNietGevonden(f"Onbekende vraag: {vraag_id}")
    if vraag.status != VraagStatus.OPEN.value:
        raise VraagNietOpen(f"Deze vraag is al {vraag.status}")
    document = session.get(Document, vraag.document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {vraag.document_id}")
    return vraag, document


def beantwoord_vraag(
    *, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, antwoord_tekst: str
) -> VraagData:
    """Legt het antwoord vast op dezelfde vraag-rij (status open -> beantwoord, nooit een delete)
    en zet het document terug naar exact de herkomst-status van vóór de vraag
    (vraag.status_voor_vraag) — een handmatig_afmaken- of klaar_om_te_boeken-document verliest
    zijn context dus niet; boeken is daarna weer bereikbaar via de normale route.
    Document.toegewezen_aan gaat terug naar leeg (de toewijzing hoorde bij de open vraag)."""
    antwoord = antwoord_tekst.strip()
    if not antwoord:
        raise AntwoordTekstVerplicht("Een antwoord zonder tekst is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag, document = _open_vraag_met_document(session, administratie_id=administratie_id, vraag_id=vraag_id)

        vraag.status = VraagStatus.BEANTWOORD.value
        vraag.antwoord_tekst = antwoord
        vraag.beantwoord_door = actor_id
        vraag.beantwoord_op = datetime.now(UTC)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus(vraag.status_voor_vraag),
            actor_id=actor_id,
            detail={"vraag_id": str(vraag.id), "vraag_beantwoord": True},
        )
        document.toegewezen_aan = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_beantwoord",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": VraagStatus.OPEN.value},
            nieuwe_waarde={
                "status": VraagStatus.BEANTWOORD.value,
                "antwoord_tekst": antwoord,
                "beantwoord_door": str(actor_id),
                "document_hersteld_naar": vraag.status_voor_vraag,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(vraag, document)


def trek_vraag_in(
    *, administratie_id: uuid.UUID, vraag_id: uuid.UUID, actor_id: uuid.UUID, reden: str | None = None
) -> VraagData:
    """Trekt een open vraag in (status open -> ingetrokken, nooit een delete) en zet het document
    terug naar de herkomst-status — bewuste uitbreiding op de mockup (docs/BESLISSINGEN.md):
    zonder intrekken dwingt een per ongeluk gestelde vraag een pro-forma nep-antwoord af, dat
    daarna als échte kennis in de historie zou staan. Reden optioneel, maar altijd in het
    audit_event (ook als None — zelfde patroon als verwijderen). De één-open-vraag-regel blijft:
    na intrekken kan er gewoon weer een nieuwe vraag gesteld worden."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vraag, document = _open_vraag_met_document(session, administratie_id=administratie_id, vraag_id=vraag_id)

        vraag.status = VraagStatus.INGETROKKEN.value
        vraag.ingetrokken_door = actor_id
        vraag.ingetrokken_op = datetime.now(UTC)
        vraag.ingetrokken_reden = reden.strip() if reden and reden.strip() else None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus(vraag.status_voor_vraag),
            actor_id=actor_id,
            detail={"vraag_id": str(vraag.id), "vraag_ingetrokken": True, "reden": vraag.ingetrokken_reden},
        )
        document.toegewezen_aan = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="vraag",
            record_id=vraag.id,
            actie="vraag_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": VraagStatus.OPEN.value},
            nieuwe_waarde={
                "status": VraagStatus.INGETROKKEN.value,
                "reden": vraag.ingetrokken_reden,
                "ingetrokken_door": str(actor_id),
                "document_hersteld_naar": vraag.status_voor_vraag,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(vraag, document)


def lijst_vragen(
    *,
    administratie_id: uuid.UUID,
    status: VraagStatus | None = None,
    document_id: uuid.UUID | None = None,
) -> list[VraagData]:
    """Vragen van één administratie, nieuwste eerst (voedt de #vragen-view en de vraag-weergave
    in het controlescherm; PART B). Optioneel gefilterd op status en/of document."""
    with scoped_session(administratie_id) as session:
        query = select(Vraag, Document).join(Document, Vraag.document_id == Document.id)
        query = query.where(Vraag.administratie_id == administratie_id)
        if status is not None:
            query = query.where(Vraag.status == status.value)
        if document_id is not None:
            query = query.where(Vraag.document_id == document_id)
        query = query.order_by(Vraag.gesteld_op.desc())
        return [_naar_data(vraag, document) for vraag, document in session.execute(query)]
