"""IBAN-wissel vier-ogen-accordering (docs/ontwerp/iban-wissel-accordering.md — goedgekeurde
flow Cowork-mockup 2026-07-15; geen mockup-bestand, de ontwerpnotitie is canoniek).

Aanbieden zet het document op DocumentStatus.WACHT_OP_IBAN_ACCORDERING (boeken geblokkeerd —
boeken.py::_KAN_BOEKPOGING_STARTEN_VANUIT bevat die status niet) en onthoudt de herkomst
(status_voor_accordering, zelfde patroon als vragen/afwijzen). Accorderen mag uitsluitend door
een accordeur uit de instelling per administratie (lege instelling → actieve beheerders) die
níét de aanvrager is — vier-ogen, server-side afgedwongen én met een DB-CHECK. Accorderen
voegt het IBAN toe aan de vertrouwde set (leverancier_iban, bron=bevestigd) en herstelt de
herkomst-status; afwijzen (verplichte reden) laat het document geblokkeerd staan — gemarkeerd
verdacht via de afgewezen accordering, geen automatische vervolgactie."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Gebruiker, GebruikerAdministratie, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.documenten.leverancier_iban import OngeldigIban, vertrouwde_ibans
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentStatus,
    IbanAccordering,
    IbanAccorderingStatus,
    IbanAccordeur,
    IbanSoort,
    LeverancierIban,
    LeverancierIbanBron,
)
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.extractie.iban import is_geldig_iban, normaliseer_iban

__all__ = [
    "AccorderingData",
    "AccordeurBuitenScope",
    "AfwijsRedenVerplicht",
    "ErIsAlEenOpenAccordering",
    "GeenBevoegdeAccordeur",
    "GeenCrediteurOpVoorstel",
    "GeenOpenAccordering",
    "IbanAccorderingFout",
    "IbanAlVertrouwd",
    "VierOgenGeschonden",
    "accordeer",
    "bied_aan",
    "haal_accordeurs_op",
    "lijst_accorderingen",
    "wijs_af",
    "zet_accordeurs",
]


class IbanAccorderingFout(Exception):
    """Basis voor domeinfouten in de IBAN-accorderingsflow."""


class GeenCrediteurOpVoorstel(IbanAccorderingFout):
    """Zonder crediteur op het boekvoorstel is er geen vertrouwde set om tegen te toetsen —
    eerst de crediteur kiezen, dan pas een IBAN aanbieden."""


class IbanAlVertrouwd(IbanAccorderingFout):
    """Het aangeboden IBAN zit al in de vertrouwde set — een accordering zou ruis zijn."""


class ErIsAlEenOpenAccordering(IbanAccorderingFout):
    """Eén open accordering per document tegelijk (ook op DB-niveau afgedwongen, migratie 0024)."""


class GeenOpenAccordering(IbanAccorderingFout):
    """Accorderen/afwijzen kan alleen op een open accordering."""


class GeenBevoegdeAccordeur(IbanAccorderingFout):
    """De besluter zit niet in de ingestelde accordeur-set (of is geen actieve beheerder bij
    een lege instelling)."""


class VierOgenGeschonden(IbanAccorderingFout):
    """De aanvrager mag zijn eigen aanvraag nooit zelf accorderen of afwijzen."""


class AfwijsRedenVerplicht(IbanAccorderingFout):
    """Een afwijzing zonder reden wordt geweigerd — ook op DB-niveau (CHECK, migratie 0024)."""


class AccordeurBuitenScope(IbanAccorderingFout):
    """Een accordeur in de instelling moet een actieve gebruiker mét toegang tot deze
    administratie zijn (Beheerder is platform-breed en telt altijd als binnen scope)."""


# Zelfde herstelbare herkomsten als vragen/afwijzen, om dezelfde reden: accorderen moet de
# herkomst exact kunnen herstellen, dus élke toegestane herkomst heeft een terugweg in de
# statusmachine. Plus WACHT_OP_IBAN_ACCORDERING zelf als her-aanvraag-herkomst: na een
# afwijzing blijft het document op die status en is een nieuwe aanvraag de enige weg vooruit
# (docs/ontwerp/iban-wissel-accordering.md, bewuste keuze 2) — de herkomst reist dan mee van
# de vorige accordering.
_HERSTELBARE_HERKOMSTEN = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
    }
)


@dataclass(frozen=True)
class AccorderingData:
    """Detached snapshot van een accordering-rij (de sessie sluit bij het verlaten van de
    service)."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_status: DocumentStatus
    vendor_id: uuid.UUID
    nieuw_iban: str
    soort: str
    status: str
    status_voor_accordering: str
    aangevraagd_door: uuid.UUID
    aangevraagd_op: datetime
    besloten_door: uuid.UUID | None
    besloten_op: datetime | None
    afwijs_reden: str | None


def _naar_data(accordering: IbanAccordering, document: Document) -> AccorderingData:
    return AccorderingData(
        id=accordering.id,
        document_id=accordering.document_id,
        document_status=document.status,
        vendor_id=accordering.vendor_id,
        nieuw_iban=accordering.nieuw_iban,
        soort=accordering.soort,
        status=accordering.status,
        status_voor_accordering=accordering.status_voor_accordering,
        aangevraagd_door=accordering.aangevraagd_door,
        aangevraagd_op=accordering.aangevraagd_op,
        besloten_door=accordering.besloten_door,
        besloten_op=accordering.besloten_op,
        afwijs_reden=accordering.afwijs_reden,
    )


# --- Instelling: accordeur-set per administratie -----------------------------------------


def _controleer_accordeur_scope(session: Session, *, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    """Zelfde scope-eis als toewijzen bij vragen/afwijzen: alleen actieve gebruikers mét
    toegang tot deze administratie (Beheerder platform-breed)."""
    gebruiker = session.get(Gebruiker, gebruiker_id)
    if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
        raise AccordeurBuitenScope(f"Accordeur is geen actieve gebruiker: {gebruiker_id}")
    if gebruiker.rol == GebruikerRol.BEHEERDER:
        return
    if session.get(GebruikerAdministratie, (gebruiker_id, administratie_id)) is None:
        raise AccordeurBuitenScope("Accordeur heeft geen toegang tot deze administratie")


def haal_accordeurs_op(*, administratie_id: uuid.UUID) -> list[uuid.UUID]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(IbanAccordeur.gebruiker_id)
                .where(IbanAccordeur.administratie_id == administratie_id)
                .order_by(IbanAccordeur.aangemaakt_op)
            )
        )


def zet_accordeurs(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, accordeurs: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Vervangt de accordeur-set (Beheerder-only, afgedwongen door de router-dependency).
    Lege lijst is geldig: de flow valt dan terug op de actieve beheerder(s). Elke wijziging in
    het audit_event, oud → nieuw."""
    ontdubbeld = list(dict.fromkeys(accordeurs))
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        for gebruiker_id in ontdubbeld:
            _controleer_accordeur_scope(session, gebruiker_id=gebruiker_id, administratie_id=administratie_id)
        huidig = list(
            session.scalars(
                select(IbanAccordeur).where(IbanAccordeur.administratie_id == administratie_id)
            )
        )
        oud = sorted(str(rij.gebruiker_id) for rij in huidig)
        for rij in huidig:
            if rij.gebruiker_id not in ontdubbeld:
                session.delete(rij)
        bestaand = {rij.gebruiker_id for rij in huidig}
        for gebruiker_id in ontdubbeld:
            if gebruiker_id not in bestaand:
                session.add(IbanAccordeur(administratie_id=administratie_id, gebruiker_id=gebruiker_id))
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="iban_accordeur",
            record_id=administratie_id,
            actie="iban_accordeurs_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"accordeurs": oud},
            nieuwe_waarde={"accordeurs": sorted(str(g) for g in ontdubbeld)},
            administratie_id=administratie_id,
        )
        session.flush()
        return ontdubbeld


def _is_bevoegde_accordeur(session: Session, *, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> bool:
    """Bevoegd = in de ingestelde set; bij een lege set (geen instelling) vallen we terug op de
    actieve beheerder(s). Bij een niet-lege set telt uitsluitend de set — ook een beheerder
    buiten de set is dan niet bevoegd (de instelling is expliciet)."""
    ingestelde_set = set(
        session.scalars(
            select(IbanAccordeur.gebruiker_id).where(IbanAccordeur.administratie_id == administratie_id)
        )
    )
    if ingestelde_set:
        return gebruiker_id in ingestelde_set
    gebruiker = session.get(Gebruiker, gebruiker_id)
    return (
        gebruiker is not None
        and gebruiker.status == GebruikerStatus.ACTIEF
        and gebruiker.rol == GebruikerRol.BEHEERDER
    )


# --- De flow: aanbieden → accorderen | afwijzen ------------------------------------------


def bied_aan(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    nieuw_iban: str,
    soort: IbanSoort,
) -> AccorderingData:
    """Biedt een afwijkend IBAN aan ter vier-ogen-accordering: open accordering + document →
    wacht_op_iban_accordering (boeken geblokkeerd). De crediteur komt van het boekvoorstel.
    Vanuit wacht_op_iban_accordering zelf mag een níéuwe aanvraag (na een afwijzing) — de
    herkomst reist dan mee van de vorige accordering."""
    if not is_geldig_iban(nieuw_iban):
        raise OngeldigIban("IBAN doorstaat de mod-97-proef niet")
    genormaliseerd = normaliseer_iban(nieuw_iban)
    assert genormaliseerd is not None

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        open_accordering = session.scalars(
            select(IbanAccordering).where(
                IbanAccordering.document_id == document_id,
                IbanAccordering.status == IbanAccorderingStatus.OPEN.value,
            )
        ).first()
        if open_accordering is not None:
            raise ErIsAlEenOpenAccordering("Er staat al een open IBAN-accordering op dit document")

        if document.status in _HERSTELBARE_HERKOMSTEN:
            herkomst = document.status.value
        elif document.status == DocumentStatus.WACHT_OP_IBAN_ACCORDERING:
            # Her-aanvraag na een afwijzing: herkomst van de laatst besliste accordering.
            vorige = session.scalars(
                select(IbanAccordering)
                .where(IbanAccordering.document_id == document_id)
                .order_by(IbanAccordering.aangevraagd_op.desc())
            ).first()
            if vorige is None:
                raise OngeldigeStatusovergang(
                    "Document wacht op IBAN-accordering zonder accordering-historie — handmatig herstellen"
                )
            herkomst = vorige.status_voor_accordering
        else:
            raise OngeldigeStatusovergang(
                f"Vanuit status {document.status.value} kan geen IBAN ter accordering aangeboden worden"
            )

        voorstel = session.get(Boekvoorstel, document_id)
        if voorstel is None or voorstel.vendor_id is None:
            raise GeenCrediteurOpVoorstel(
                "Het boekvoorstel heeft nog geen crediteur — kies eerst de crediteur, daarna het IBAN aanbieden"
            )
        vendor_id = voorstel.vendor_id

        if genormaliseerd in vertrouwde_ibans(administratie_id=administratie_id, vendor_id=vendor_id):
            raise IbanAlVertrouwd("Dit IBAN staat al in de vertrouwde set van deze crediteur")

        accordering = IbanAccordering(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            document_id=document_id,
            nieuw_iban=genormaliseerd,
            soort=soort.value,
            aangevraagd_door=actor_id,
            status_voor_accordering=herkomst,
        )
        session.add(accordering)
        if document.status != DocumentStatus.WACHT_OP_IBAN_ACCORDERING:
            _schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
                actor_id=actor_id,
                detail={
                    "iban_accordering_id": str(accordering.id),
                    "soort": soort.value,
                    "status_voor_accordering": herkomst,
                },
            )
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="iban_accordering",
            record_id=accordering.id,
            actie="iban_accordering_aangeboden",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "vendor_id": str(vendor_id),
                "iban": genormaliseerd,
                "soort": soort.value,
                "aangevraagd_door": str(actor_id),
                "status_voor_accordering": herkomst,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(accordering, document)


def _open_accordering_met_document(
    session: Session, *, administratie_id: uuid.UUID, accordering_id: uuid.UUID
) -> tuple[IbanAccordering, Document]:
    accordering = session.get(IbanAccordering, accordering_id)
    if accordering is None or accordering.administratie_id != administratie_id:
        raise GeenOpenAccordering(f"Onbekende IBAN-accordering: {accordering_id}")
    if accordering.status != IbanAccorderingStatus.OPEN.value:
        raise GeenOpenAccordering(f"Deze IBAN-accordering is al {accordering.status}")
    document = session.get(Document, accordering.document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {accordering.document_id}")
    return accordering, document


def _controleer_vier_ogen(
    session: Session, *, accordering: IbanAccordering, actor_id: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Volgorde bewust: eerst de vier-ogen-eis (aanvrager-zelf is de gevaarlijkste weigering,
    verdient de specifieke melding), dan de bevoegdheid."""
    if actor_id == accordering.aangevraagd_door:
        raise VierOgenGeschonden("De aanvrager kan zijn eigen IBAN-aanvraag niet zelf beoordelen (vier ogen)")
    if not _is_bevoegde_accordeur(session, gebruiker_id=actor_id, administratie_id=administratie_id):
        raise GeenBevoegdeAccordeur(
            "Alleen een ingestelde IBAN-accordeur (of een beheerder, als er geen accordeurs zijn "
            "ingesteld) kan deze aanvraag beoordelen"
        )


def accordeer(*, administratie_id: uuid.UUID, accordering_id: uuid.UUID, actor_id: uuid.UUID) -> AccorderingData:
    """Vier-ogen-akkoord: IBAN naar de vertrouwde set (bron=bevestigd, besluter als
    bevestiger), document terug naar exact de herkomst-status — boeken weer bereikbaar via de
    normale route (de harde checks draaien bij de boekactie sowieso opnieuw)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        accordering, document = _open_accordering_met_document(
            session, administratie_id=administratie_id, accordering_id=accordering_id
        )
        _controleer_vier_ogen(
            session, accordering=accordering, actor_id=actor_id, administratie_id=administratie_id
        )

        accordering.status = IbanAccorderingStatus.GEACCORDEERD.value
        accordering.besloten_door = actor_id
        accordering.besloten_op = datetime.now(UTC)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus(accordering.status_voor_accordering),
            actor_id=actor_id,
            detail={"iban_accordering_id": str(accordering.id), "iban_geaccordeerd": True},
        )
        # Vertrouwde set in dezelfde transactie (alles-of-niets: nooit een geaccordeerde
        # aanvraag zonder vertrouwd IBAN of andersom) — zelfde vorm als
        # leverancier_iban._voeg_toe, hier inline vanwege de gedeelde sessie. Idempotent op
        # de PK; een bestaande rij kan hier niet voorkomen (bied_aan weigert een al-vertrouwd
        # IBAN), maar dubbel toevoegen zou hoe dan ook op de PK stuklopen — zichtbaar, geen
        # stille overschrijving.
        session.add(
            LeverancierIban(
                administratie_id=administratie_id,
                vendor_id=accordering.vendor_id,
                iban=accordering.nieuw_iban,
                bron=LeverancierIbanBron.BEVESTIGD.value,
                bevestigd_door=actor_id,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_iban",
            record_id=accordering.vendor_id,
            actie="leverancier_iban_toegevoegd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "iban": accordering.nieuw_iban,
                "bron": LeverancierIbanBron.BEVESTIGD.value,
                "via_accordering": str(accordering.id),
            },
            administratie_id=administratie_id,
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="iban_accordering",
            record_id=accordering.id,
            actie="iban_accordering_geaccordeerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": IbanAccorderingStatus.OPEN.value},
            nieuwe_waarde={
                "status": IbanAccorderingStatus.GEACCORDEERD.value,
                "iban": accordering.nieuw_iban,
                "aangevraagd_door": str(accordering.aangevraagd_door),
                "besloten_door": str(actor_id),
                "document_hersteld_naar": accordering.status_voor_accordering,
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(accordering, document)


def wijs_af(
    *, administratie_id: uuid.UUID, accordering_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> AccorderingData:
    """Vier-ogen-afwijzing: reden verplicht; de accordering gaat naar afgewezen en het document
    blíjft op wacht_op_iban_accordering — geblokkeerd en via de afgewezen accordering (mét
    reden) gemarkeerd als verdacht. Geen automatische vervolgactie; een nieuwe aanvraag
    (bied_aan) is de enige weg vooruit."""
    reden_tekst = reden.strip()
    if not reden_tekst:
        raise AfwijsRedenVerplicht("Een IBAN-afwijzing zonder reden is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        accordering, document = _open_accordering_met_document(
            session, administratie_id=administratie_id, accordering_id=accordering_id
        )
        _controleer_vier_ogen(
            session, accordering=accordering, actor_id=actor_id, administratie_id=administratie_id
        )

        accordering.status = IbanAccorderingStatus.AFGEWEZEN.value
        accordering.besloten_door = actor_id
        accordering.besloten_op = datetime.now(UTC)
        accordering.afwijs_reden = reden_tekst
        # Bewust géén statusovergang: het document blijft geblokkeerd op
        # wacht_op_iban_accordering (docs/ontwerp/iban-wissel-accordering.md).
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="iban_accordering",
            record_id=accordering.id,
            actie="iban_accordering_afgewezen",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": IbanAccorderingStatus.OPEN.value},
            nieuwe_waarde={
                "status": IbanAccorderingStatus.AFGEWEZEN.value,
                "iban": accordering.nieuw_iban,
                "reden": reden_tekst,
                "aangevraagd_door": str(accordering.aangevraagd_door),
                "besloten_door": str(actor_id),
            },
            administratie_id=administratie_id,
        )
        session.flush()
        return _naar_data(accordering, document)


def lijst_accorderingen(
    *,
    administratie_id: uuid.UUID,
    status: IbanAccorderingStatus | None = None,
    document_id: uuid.UUID | None = None,
) -> list[AccorderingData]:
    """Accorderingen van één administratie, nieuwste eerst (voedt straks de PART B-UI; nu al
    nodig voor de werkvoorraad-/detailweergave van een wachtend document)."""
    with scoped_session(administratie_id) as session:
        query = (
            select(IbanAccordering, Document)
            .join(Document, IbanAccordering.document_id == Document.id)
            .where(IbanAccordering.administratie_id == administratie_id)
        )
        if status is not None:
            query = query.where(IbanAccordering.status == status.value)
        if document_id is not None:
            query = query.where(IbanAccordering.document_id == document_id)
        query = query.order_by(IbanAccordering.aangevraagd_op.desc())
        return [_naar_data(accordering, document) for accordering, document in session.execute(query)]
