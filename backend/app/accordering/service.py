"""Klant-accorderingsflow — geldlogica (mockup #autorisatie; BESLISSINGEN "Mobiele bouwstenen
accordeur-PWA" punten 1/5/6; migratie 0033).

Flow: kantoor biedt een boekklaar document "ter accordering" aan → stappen worden bevroren uit
de actieve lagen (bedragdrempel geëvalueerd op het totaalbedrag; onbekend bedrag = laag
vereist, fail-closed) → accordeurs besluiten SEQUENTIEEL (laag n pas na laag n-1) → na het
laatste akkoord zet de flow het document terug op klaar_om_te_boeken en draait de bestaande
boekmotor MET ALLE HARDE CHECKS opnieuw (CLAUDE.md, hard — een akkoord is nooit een bypass).

Staande goedkeuring (besluit Peter 2026-08-08): een accordeur kan bij zijn akkoord "voortaan
automatisch bij exact dit bedrag" vastleggen — per accordeur + leverancier (vendor_id) + exact
bedrag. Bij het aanbieden van een volgend document wordt de regel toegepast als automatisch
akkoord in de betreffende laag, mét audit-spoor + tijdlijn-vermelding; afwijkend bedrag =
gewoon ter accordering; de regel is zichtbaar + intrekbaar en gaat NOOIT over de harde checks
heen (die draaien bij het boeken).

Afwijzen door de accordeur = verplichte reden en hergebruikt het bestaande
afwijzen-met-reden-patroon (app/documenten/afwijzen.py): het document gaat eerst zichtbaar
terug naar klaar_om_te_boeken ("terug uit accordering") en wordt dan afgewezen — heropenen
brengt het gewoon terug in de kantoorbak.

Autorisatie: alle leesroutes zijn scope-gecontroleerd (RLS + dependency); accordeur-besluiten
worden bovendien hard op de stap-eigenaar getoetst (alleen de accordeur van de eerstvolgende
open vereiste stap), kantoor-acties (aanbieden/intrekken/instellingen) weigeren de rol
klant-accordeur."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accordering.models import (
    AccorderingLaag,
    AccorderingStap,
    AccorderingStatus,
    DocumentAccordering,
    StaandeGoedkeuring,
    StapBesluit,
    StapBesluitBron,
)
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import afwijzen as afwijzen_service
from app.documenten import boeken as boeken_service
from app.documenten.models import Boekvoorstel, Document, DocumentStatus
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)


class AccorderingFout(Exception):
    """Basis voor domeinfouten in de accorderingsflow."""


class AccorderingUitgeschakeld(AccorderingFout):
    pass


class GeenLagenIngesteld(AccorderingFout):
    pass


class OngeldigeAanbieding(AccorderingFout):
    pass


class NietAanDeBeurt(AccorderingFout):
    """De actor is niet de accordeur van de eerstvolgende open vereiste stap."""


class RedenVerplicht(AccorderingFout):
    pass


class GeenOpenAccordering(AccorderingFout):
    pass


class StaandeRegelNietMogelijk(AccorderingFout):
    """Zonder leverancier (vendor_id) of totaalbedrag valt er geen exacte regel vast te leggen."""


class KantoorActieVereist(AccorderingFout):
    """Aanbieden/intrekken/instellingen zijn kantoor-acties — niet voor de rol klant-accordeur."""


class ChecksNietGroen(AccorderingFout):
    """Aanbieden vanaf te_controleren/handmatig_afmaken vereist dezelfde groene harde checks als
    boeken — een document met blokkerende checks gaat nooit naar de klant."""

    def __init__(self, rapport) -> None:
        self.rapport = rapport
        super().__init__("Ter accordering geblokkeerd door harde checks")


@dataclass(frozen=True)
class StapData:
    id: uuid.UUID
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    bedrag_drempel: Decimal | None
    vereist: bool
    besluit: str | None
    besluit_bron: str | None
    reden: str | None
    besloten_op: datetime | None
    aan_de_beurt: bool


@dataclass(frozen=True)
class AccorderingData:
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    aangeboden_op: datetime
    afgerond_op: datetime | None
    stappen: list[StapData]


@dataclass(frozen=True)
class AkkoordResultaat:
    accordering: AccorderingData
    alles_akkoord: bool
    geboekt: bool
    boek_fout: str | None
    staande_regel_id: uuid.UUID | None


def _gebruikersnamen(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rijen = session.scalars(select(Gebruiker).where(Gebruiker.id.in_(ids))).all()
    return {g.id: g.naam for g in rijen}


def _eerstvolgende_open_stap(stappen: list[AccorderingStap]) -> AccorderingStap | None:
    for stap in sorted(stappen, key=lambda s: s.volgnummer):
        if stap.vereist and stap.besluit is None:
            return stap
    return None


def _naar_data(
    session: Session, accordering: DocumentAccordering, stappen: list[AccorderingStap]
) -> AccorderingData:
    namen = _gebruikersnamen(session, {s.accordeur_gebruiker_id for s in stappen})
    volgende = _eerstvolgende_open_stap(stappen) if accordering.status == AccorderingStatus.OPEN.value else None
    return AccorderingData(
        id=accordering.id,
        document_id=accordering.document_id,
        status=accordering.status,
        aangeboden_op=accordering.aangeboden_op,
        afgerond_op=accordering.afgerond_op,
        stappen=[
            StapData(
                id=s.id,
                volgnummer=s.volgnummer,
                accordeur_gebruiker_id=s.accordeur_gebruiker_id,
                accordeur_naam=namen.get(s.accordeur_gebruiker_id),
                bedrag_drempel=s.bedrag_drempel,
                vereist=s.vereist,
                besluit=s.besluit,
                besluit_bron=s.besluit_bron,
                reden=s.reden,
                besloten_op=s.besloten_op,
                aan_de_beurt=volgende is not None and s.id == volgende.id,
            )
            for s in sorted(stappen, key=lambda s: s.volgnummer)
        ],
    )


def _stappen_van(session: Session, accordering_id: uuid.UUID) -> list[AccorderingStap]:
    return list(
        session.scalars(select(AccorderingStap).where(AccorderingStap.accordering_id == accordering_id))
    )


def _open_accordering(session: Session, document_id: uuid.UUID) -> DocumentAccordering | None:
    return session.scalars(
        select(DocumentAccordering).where(
            DocumentAccordering.document_id == document_id,
            DocumentAccordering.status == AccorderingStatus.OPEN.value,
        )
    ).first()


def heeft_afgeronde_accordering(session: Session, *, document_id: uuid.UUID) -> bool:
    """Poort voor de boekmotor: bij accordering-aan mag er alleen geboekt worden mét een
    afgeronde ronde (app/documenten/boeken.py roept dit aan — nooit de client vertrouwen)."""
    return (
        session.scalars(
            select(DocumentAccordering).where(
                DocumentAccordering.document_id == document_id,
                DocumentAccordering.status == AccorderingStatus.AFGEROND.value,
            )
        ).first()
        is not None
    )


def is_accordering_ingeschakeld(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie is not None and administratie.accordering_ingeschakeld


def _vereis_kantoor(actor_rol: str) -> None:
    if actor_rol == GebruikerRol.KLANT_ACCORDEUR.value:
        raise KantoorActieVereist("Deze actie is voorbehouden aan het kantoor")


# --- instellingen (toggle + lagen) ---------------------------------------------------------------


def instellingen_ophalen(*, administratie_id: uuid.UUID) -> tuple[bool, list[AccorderingLaag], dict[uuid.UUID, str]]:
    with scoped_session(administratie_id) as session:
        lagen = list(
            session.scalars(
                select(AccorderingLaag)
                .where(AccorderingLaag.administratie_id == administratie_id, AccorderingLaag.actief.is_(True))
                .order_by(AccorderingLaag.volgnummer)
            )
        )
        namen = _gebruikersnamen(session, {laag.accordeur_gebruiker_id for laag in lagen})
        session.expunge_all()
    return is_accordering_ingeschakeld(administratie_id=administratie_id), lagen, namen


@dataclass(frozen=True)
class LaagInput:
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None


def instellingen_opslaan(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_rol: str,
    ingeschakeld: bool,
    lagen: list[LaagInput],
) -> None:
    """Beheerder-only (router-dependency) + nooit door een accordeur. Lagen zijn append-only:
    de bestaande actieve lagen worden gedeactiveerd, de nieuwe set aangemaakt. Aanzetten zonder
    lagen is geweigerd (een toggle zonder schema zou elke boeking stil blokkeren)."""
    _vereis_kantoor(actor_rol)
    if ingeschakeld and not lagen:
        raise GeenLagenIngesteld("Accordering aanzetten vereist minstens één accorderingslaag")
    volgnummers = [laag.volgnummer for laag in lagen]
    if len(volgnummers) != len(set(volgnummers)):
        raise OngeldigeAanbieding("Volgnummers van de lagen moeten uniek zijn")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaande = list(
            session.scalars(
                select(AccorderingLaag).where(
                    AccorderingLaag.administratie_id == administratie_id, AccorderingLaag.actief.is_(True)
                )
            )
        )
        nu = datetime.now(UTC)
        for laag in bestaande:
            laag.actief = False
            laag.gedeactiveerd_door = actor_id
            laag.gedeactiveerd_op = nu
        for invoer in lagen:
            session.add(
                AccorderingLaag(
                    administratie_id=administratie_id,
                    volgnummer=invoer.volgnummer,
                    accordeur_gebruiker_id=invoer.accordeur_gebruiker_id,
                    bedrag_drempel=invoer.bedrag_drempel,
                    aangemaakt_door=actor_id,
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_laag",
            record_id=administratie_id,
            actie="accordering_schema_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={
                "lagen": [
                    {"volgnummer": b.volgnummer, "accordeur": str(b.accordeur_gebruiker_id)} for b in bestaande
                ]
            },
            nieuwe_waarde={
                "ingeschakeld": ingeschakeld,
                "lagen": [
                    {
                        "volgnummer": laag.volgnummer,
                        "accordeur": str(laag.accordeur_gebruiker_id),
                        "bedrag_drempel": str(laag.bedrag_drempel) if laag.bedrag_drempel is not None else None,
                    }
                    for laag in lagen
                ],
            },
            administratie_id=administratie_id,
        )

    # Zelfde patroon als beheer/service.py::zet_boeken_ingeschakeld: platformbrede
    # Beheerder-handeling, sessie gescoped op None en audit_event.administratie_id bewust NULL
    # (de RLS WITH CHECK op audit_event kent geen beheerder-bypass).
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise DocumentNietGevonden(f"Onbekende administratie: {administratie_id}")
        oud = administratie.accordering_ingeschakeld
        administratie.accordering_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="accordering_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"accordering_ingeschakeld": oud},
            nieuwe_waarde={"accordering_ingeschakeld": ingeschakeld},
        )


# --- aanbieden -----------------------------------------------------------------------------------


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def bied_ter_accordering_aan(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, actor_rol: str
) -> AkkoordResultaat:
    """De "Ter accordering"-knop (kantoor): bevriest de actieve lagen tot stappen (drempel op
    het totaalbedrag; onbekend bedrag = vereist, fail-closed), zet het document op
    ter_accordering en past daarna staande goedkeuringen toe — zijn álle stappen daarmee al
    akkoord, dan boekt de motor direct (met alle harde checks)."""
    _vereis_kantoor(actor_rol)
    if not is_accordering_ingeschakeld(administratie_id=administratie_id):
        raise AccorderingUitgeschakeld("Accordering staat uit voor deze administratie")

    # De "Ter accordering"-knop vervangt de boekknop op het controlescherm — dus ook vanaf
    # te_controleren/handmatig_afmaken, mét exact dezelfde checks-poort als boek_document:
    # een document met blokkerende checks gaat nooit naar de klant.
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        status_vooraf = document.status
    if status_vooraf in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN):
        from app.documenten.boeken import _rlz_client_voor
        from app.documenten.boekvoorstel import voer_checks_uit

        with _rlz_client_voor(administratie_id) as client:
            rapport = voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=client)
        if rapport.geblokkeerd:
            raise ChecksNietGroen(rapport)
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                    actor_id=actor_id,
                    detail={"harde_checks": "doorstaan"},
                )

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
            raise OngeldigeAanbieding(
                f"Document staat op {document.status.value} — alleen een boekklaar document kan ter accordering"
            )
        if _open_accordering(session, document_id) is not None:
            raise OngeldigeAanbieding("Er loopt al een accorderingsronde voor dit document")

        lagen = list(
            session.scalars(
                select(AccorderingLaag)
                .where(AccorderingLaag.administratie_id == administratie_id, AccorderingLaag.actief.is_(True))
                .order_by(AccorderingLaag.volgnummer)
            )
        )
        if not lagen:
            raise GeenLagenIngesteld("Geen accorderingslagen ingesteld voor deze administratie")

        voorstel = session.get(Boekvoorstel, document_id)
        totaalbedrag = _als_decimal(voorstel.totaalbedrag) if voorstel else None
        vendor_id = voorstel.vendor_id if voorstel else None

        accordering = DocumentAccordering(
            administratie_id=administratie_id,
            document_id=document_id,
            aangeboden_door=actor_id,
            detail={
                "totaalbedrag": str(totaalbedrag) if totaalbedrag is not None else None,
                "vendor_id": str(vendor_id) if vendor_id else None,
            },
        )
        session.add(accordering)
        session.flush()
        for laag in lagen:
            # Drempel: laag geldt alleen bóven het bedrag; onbekend totaalbedrag = vereist
            # (fail-closed — bij twijfel wél een mens laten kijken).
            vereist = (
                laag.bedrag_drempel is None or totaalbedrag is None or abs(totaalbedrag) > laag.bedrag_drempel
            )
            session.add(
                AccorderingStap(
                    administratie_id=administratie_id,
                    accordering_id=accordering.id,
                    volgnummer=laag.volgnummer,
                    accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                    bedrag_drempel=laag.bedrag_drempel,
                    vereist=vereist,
                )
            )
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.TER_ACCORDERING,
            actor_id=actor_id,
            detail={
                "accordering_id": str(accordering.id),
                "lagen": len(lagen),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering.id,
            actie="ter_accordering_aangeboden",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id), "lagen": len(lagen)},
            administratie_id=administratie_id,
        )
        accordering_id = accordering.id

    # Staande goedkeuringen toepassen (autonoom, ná de aanbied-transactie): elke vereiste stap
    # waarvoor een actieve regel (accordeur + vendor + exact bedrag) bestaat krijgt automatisch
    # akkoord — mét audit + tijdlijn. Alles akkoord → direct boeken.
    return _pas_staande_regels_toe_en_rond_af(
        administratie_id=administratie_id, accordering_id=accordering_id, document_id=document_id
    )


def _pas_staande_regels_toe_en_rond_af(
    *, administratie_id: uuid.UUID, accordering_id: uuid.UUID, document_id: uuid.UUID
) -> AkkoordResultaat:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        detail = accordering.detail or {}
        vendor_id = detail.get("vendor_id")
        totaalbedrag = _als_decimal(detail.get("totaalbedrag"))
        stappen = _stappen_van(session, accordering_id)

        if vendor_id and totaalbedrag is not None:
            document = session.get(Document, document_id)
            for stap in sorted(stappen, key=lambda s: s.volgnummer):
                if not stap.vereist or stap.besluit is not None:
                    continue
                regel = session.scalars(
                    select(StaandeGoedkeuring).where(
                        StaandeGoedkeuring.administratie_id == administratie_id,
                        StaandeGoedkeuring.accordeur_gebruiker_id == stap.accordeur_gebruiker_id,
                        StaandeGoedkeuring.vendor_id == uuid.UUID(vendor_id),
                        StaandeGoedkeuring.bedrag == totaalbedrag,
                        StaandeGoedkeuring.actief.is_(True),
                    )
                ).first()
                if regel is None:
                    break  # sequentieel: zonder automatisch akkoord stopt de keten hier
                stap.besluit = StapBesluit.AKKOORD.value
                stap.besluit_bron = StapBesluitBron.STAANDE_REGEL.value
                stap.staande_regel_id = regel.id
                stap.besloten_op = datetime.now(UTC)
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="accordering_stap",
                    record_id=stap.id,
                    actie="accordering_automatisch_akkoord_staande_regel",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "document_id": str(document_id),
                        "laag": stap.volgnummer,
                        "staande_regel_id": str(regel.id),
                        "accordeur": str(stap.accordeur_gebruiker_id),
                        "bedrag": str(totaalbedrag),
                    },
                    administratie_id=administratie_id,
                )
                # Tijdlijn-vermelding zonder statusovergang (zelfde patroon als afwijs-historie).
                if document is not None:
                    from app.documenten.models import DocumentGebeurtenis

                    session.add(
                        DocumentGebeurtenis(
                            id=uuid.uuid4(),
                            document_id=document_id,
                            van_status=document.status,
                            naar_status=document.status,
                            actor_id=SYSTEEM_ACTOR_ID,
                            detail={
                                "accordering_automatisch_akkoord": {
                                    "laag": stap.volgnummer,
                                    "staande_regel_id": str(regel.id),
                                    "accordeur": str(stap.accordeur_gebruiker_id),
                                }
                            },
                        )
                    )

        alles_akkoord = _eerstvolgende_open_stap(stappen) is None
        data = _naar_data(session, accordering, stappen)

    if not alles_akkoord:
        return AkkoordResultaat(
            accordering=data, alles_akkoord=False, geboekt=False, boek_fout=None, staande_regel_id=None
        )
    return _rond_af_en_boek(administratie_id=administratie_id, accordering_id=accordering_id)


# --- besluiten (accordeur) -----------------------------------------------------------------------


def _stap_aan_de_beurt_voor(
    session: Session, *, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[DocumentAccordering, AccorderingStap, list[AccorderingStap]]:
    accordering = _open_accordering(session, document_id)
    if accordering is None:
        raise GeenOpenAccordering("Er loopt geen accorderingsronde voor dit document")
    stappen = _stappen_van(session, accordering.id)
    volgende = _eerstvolgende_open_stap(stappen)
    if volgende is None:
        raise GeenOpenAccordering("Alle lagen zijn al besloten")
    if volgende.accordeur_gebruiker_id != actor_id:
        raise NietAanDeBeurt("Deze factuur wacht op een andere accordeur (sequentiële lagen)")
    return accordering, volgende, stappen


def geef_akkoord(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    staande_regel_aanmaken: bool = False,
) -> AkkoordResultaat:
    """Akkoord van de accordeur die aan de beurt is. `staande_regel_aanmaken` legt het besluit
    2026-08-08 vast: akkoord voor toekomstige facturen van deze leverancier bij exact dit
    bedrag (zichtbaar + intrekbaar; harde checks blijven onverkort)."""
    staande_regel_id: uuid.UUID | None = None
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        accordering, stap, stappen = _stap_aan_de_beurt_voor(
            session, document_id=document_id, actor_id=actor_id
        )
        stap.besluit = StapBesluit.AKKOORD.value
        stap.besluit_bron = StapBesluitBron.HANDMATIG.value
        stap.besloten_op = datetime.now(UTC)

        detail = accordering.detail or {}
        if staande_regel_aanmaken:
            vendor_id = detail.get("vendor_id")
            totaalbedrag = _als_decimal(detail.get("totaalbedrag"))
            if not vendor_id or totaalbedrag is None:
                raise StaandeRegelNietMogelijk(
                    "Zonder leverancier of totaalbedrag kan er geen staande goedkeuring vastgelegd worden"
                )
            vendor = session.get(VendorCache, (uuid.UUID(vendor_id), administratie_id))
            regel = StaandeGoedkeuring(
                administratie_id=administratie_id,
                accordeur_gebruiker_id=actor_id,
                vendor_id=uuid.UUID(vendor_id),
                leverancier_naam=vendor.naam if vendor else None,
                bedrag=totaalbedrag,
                bron_document_id=document_id,
            )
            session.add(regel)
            session.flush()
            staande_regel_id = regel.id
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="staande_goedkeuring",
                record_id=regel.id,
                actie="staande_goedkeuring_aangemaakt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "vendor_id": vendor_id,
                    "leverancier": regel.leverancier_naam,
                    "bedrag": str(totaalbedrag),
                    "bron_document_id": str(document_id),
                },
                administratie_id=administratie_id,
            )

        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_stap",
            record_id=stap.id,
            actie="accordering_akkoord",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "document_id": str(document_id),
                "laag": stap.volgnummer,
                "staande_regel_id": str(staande_regel_id) if staande_regel_id else None,
            },
            administratie_id=administratie_id,
        )
        # Tijdlijn-vermelding zonder statusovergang.
        document = session.get(Document, document_id)
        if document is not None:
            from app.documenten.models import DocumentGebeurtenis

            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={"accordering_akkoord": {"laag": stap.volgnummer}},
                )
            )
        alles_akkoord = _eerstvolgende_open_stap(stappen) is None
        accordering_id = accordering.id
        data = _naar_data(session, accordering, stappen)

    if not alles_akkoord:
        return AkkoordResultaat(
            accordering=data, alles_akkoord=False, geboekt=False, boek_fout=None, staande_regel_id=staande_regel_id
        )
    resultaat = _rond_af_en_boek(administratie_id=administratie_id, accordering_id=accordering_id)
    return AkkoordResultaat(
        accordering=resultaat.accordering,
        alles_akkoord=True,
        geboekt=resultaat.geboekt,
        boek_fout=resultaat.boek_fout,
        staande_regel_id=staande_regel_id,
    )


def _rond_af_en_boek(*, administratie_id: uuid.UUID, accordering_id: uuid.UUID) -> AkkoordResultaat:
    """Ná het laatste akkoord: ronde afronden, document terug naar klaar_om_te_boeken (tijdlijn
    "alle lagen akkoord") en de bestaande boekmotor draaien — MET alle harde checks (CLAUDE.md,
    hard). Een geblokkeerde check of RLZ-fout is zichtbaar (boek_fout + documentstatus), nooit
    stil."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        accordering.status = AccorderingStatus.AFGEROND.value
        accordering.afgerond_op = datetime.now(UTC)
        document_id = accordering.document_id
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={"accordering_id": str(accordering_id), "alle_lagen_akkoord": True},
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering_id,
            actie="accordering_afgerond",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id)},
            administratie_id=administratie_id,
        )

    geboekt = False
    boek_fout: str | None = None
    try:
        boeken_service.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=SYSTEEM_ACTOR_ID
        )
        geboekt = True
    except boeken_service.BoekenGeblokkeerdDoorChecks as exc:
        boek_fout = "Boeken geblokkeerd door harde checks: " + "; ".join(
            r.melding for r in exc.rapport.resultaten if not r.ok
        )
        logger.warning("Accordering %s afgerond maar boeken geblokkeerd: %s", accordering_id, boek_fout)
    except boeken_service.BoekenFout as exc:
        boek_fout = str(exc)
        logger.warning("Accordering %s afgerond maar boeken mislukt: %s", accordering_id, boek_fout)

    with scoped_session(administratie_id) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        stappen = _stappen_van(session, accordering_id)
        data = _naar_data(session, accordering, stappen)
    return AkkoordResultaat(
        accordering=data, alles_akkoord=True, geboekt=geboekt, boek_fout=boek_fout, staande_regel_id=None
    )


def wijs_af(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> AccorderingData:
    """Afwijzen door de accordeur: verplichte reden (popup-principe), hergebruikt het bestaande
    afwijzen-met-reden-patroon — document eerst zichtbaar terug uit de accordering, dan
    afgewezen (status in de werkvoorraad, met reden; heropenen = kantoorbak)."""
    reden_tekst = reden.strip()
    if not reden_tekst:
        raise RedenVerplicht("Afwijzen zonder reden is niet toegestaan")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        accordering, stap, stappen = _stap_aan_de_beurt_voor(
            session, document_id=document_id, actor_id=actor_id
        )
        stap.besluit = StapBesluit.AFGEWEZEN.value
        stap.besluit_bron = StapBesluitBron.HANDMATIG.value
        stap.reden = reden_tekst
        stap.besloten_op = datetime.now(UTC)
        accordering.status = AccorderingStatus.AFGEWEZEN.value
        accordering.afgerond_op = datetime.now(UTC)
        aangeboden_door = accordering.aangeboden_door
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={
                "accordering_id": str(accordering.id),
                "accordering_afgewezen": {"laag": stap.volgnummer, "reden": reden_tekst},
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="accordering_stap",
            record_id=stap.id,
            actie="accordering_afgewezen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id), "laag": stap.volgnummer, "reden": reden_tekst},
            administratie_id=administratie_id,
        )
        accordering_id = accordering.id

    # Bestaand patroon: afwijzen-met-verplichte-reden — zichtbaar in de werkvoorraad, heropenen
    # herstelt de (zojuist teruggezette) klaar_om_te_boeken-herkomst. Toegewezen aan wie het
    # document aanbood (die kent de casus) — het afwijzen-default (administratie-eigenaar)
    # blijft de fallback via toegewezen_aan=None-gedrag als de aanbieder ontbreekt.
    afwijzen_service.wijs_af(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        reden=f"Afgewezen door accordeur: {reden_tekst}",
        toegewezen_aan=aangeboden_door,
    )

    with scoped_session(administratie_id) as session:
        accordering = session.get(DocumentAccordering, accordering_id)
        assert accordering is not None
        stappen = _stappen_van(session, accordering_id)
        return _naar_data(session, accordering, stappen)


def trek_accordering_in(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, actor_rol: str
) -> AccorderingData:
    """Kantoor haalt een document terug uit de accordering (bv. verkeerd aangeboden)."""
    _vereis_kantoor(actor_rol)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        accordering = _open_accordering(session, document_id)
        if accordering is None:
            raise GeenOpenAccordering("Er loopt geen accorderingsronde voor dit document")
        accordering.status = AccorderingStatus.INGETROKKEN.value
        accordering.afgerond_op = datetime.now(UTC)
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=actor_id,
            detail={"accordering_id": str(accordering.id), "accordering_ingetrokken": True},
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document_accordering",
            record_id=accordering.id,
            actie="accordering_ingetrokken",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"document_id": str(document_id)},
            administratie_id=administratie_id,
        )
        stappen = _stappen_van(session, accordering.id)
        return _naar_data(session, accordering, stappen)


# --- lezen ---------------------------------------------------------------------------------------


def accordering_van_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> AccorderingData | None:
    """Meest recente accorderingsronde van een document (accorderingshistorie op het
    controlescherm)."""
    with scoped_session(administratie_id) as session:
        accordering = session.scalars(
            select(DocumentAccordering)
            .where(DocumentAccordering.document_id == document_id)
            .order_by(DocumentAccordering.aangeboden_op.desc())
        ).first()
        if accordering is None:
            return None
        stappen = _stappen_van(session, accordering.id)
        return _naar_data(session, accordering, stappen)


@dataclass(frozen=True)
class WachtrijItem:
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    leverancier_naam: str | None
    referentie: str | None
    factuurdatum: object
    totaalbedrag: Decimal | None
    aangeboden_op: datetime
    laag_volgnummer: int
    # PWA-review (mockup accordeur.html): compacte weergave van de voorgestelde boeking
    # ("Inkopen Headshop · btw 21%") — géén volledige regelweergave, scope bewust smal.
    boeking_omschrijving: str | None = None
    # Mockup-flow "staande goedkeuring na 2e identieke factuur": déze accordeur gaf eerder
    # handmatig akkoord op zelfde leverancier + exact bedrag, en er is nog geen actieve regel.
    staande_regel_kandidaat: bool = False


def _boeking_omschrijving(session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
    """Eerste boekingsregel als leesbare samenvatting: grootboeknaam + btw-naam, met een
    "+n regels"-suffix bij meer regels (de accordeur beoordeelt de factuur, niet de codering —
    besluit scope-aanscherping 2026-08-08)."""
    from app.db.models import Grootboekrekening
    from app.documenten.models import BoekvoorstelRegel
    from app.sync.models import TaxRateCache

    regels = list(
        session.scalars(
            select(BoekvoorstelRegel)
            .where(BoekvoorstelRegel.document_id == document_id)
            .order_by(BoekvoorstelRegel.volgnummer)
        )
    )
    if not regels:
        return None
    eerste = regels[0]
    delen: list[str] = []
    if eerste.ledger_id is not None:
        grootboek = session.get(Grootboekrekening, (eerste.ledger_id, administratie_id))
        if grootboek is not None:
            delen.append(grootboek.naam)
    if eerste.taxrate_id is not None:
        taxrate = session.get(TaxRateCache, (eerste.taxrate_id, administratie_id))
        if taxrate is not None and taxrate.naam:
            delen.append(taxrate.naam)
    if not delen:
        return None
    samenvatting = " · ".join(delen)
    if len(regels) > 1:
        samenvatting += f" · +{len(regels) - 1} regels"
    return samenvatting


def _is_staande_regel_kandidaat(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    accordeur_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    totaalbedrag: Decimal | None,
) -> bool:
    """True als déze accordeur eerder HANDMATIG akkoord gaf op een ander document van dezelfde
    leverancier met exact hetzelfde bedrag, en er nog geen actieve staande regel voor die
    combinatie bestaat — dan stelt de PWA ná het akkoord de staande goedkeuring voor."""
    if vendor_id is None or totaalbedrag is None:
        return False
    bestaande_regel = session.scalars(
        select(StaandeGoedkeuring.id).where(
            StaandeGoedkeuring.administratie_id == administratie_id,
            StaandeGoedkeuring.accordeur_gebruiker_id == accordeur_id,
            StaandeGoedkeuring.vendor_id == vendor_id,
            StaandeGoedkeuring.bedrag == totaalbedrag,
            StaandeGoedkeuring.actief.is_(True),
        )
    ).first()
    if bestaande_regel is not None:
        return False
    eerdere = session.scalars(
        select(DocumentAccordering).where(
            DocumentAccordering.administratie_id == administratie_id,
            DocumentAccordering.document_id != document_id,
        )
    ).all()
    for accordering in eerdere:
        detail = accordering.detail or {}
        if detail.get("vendor_id") != str(vendor_id):
            continue
        eerder_bedrag = _als_decimal(detail.get("totaalbedrag"))
        if eerder_bedrag is None or eerder_bedrag != totaalbedrag:
            continue
        for stap in _stappen_van(session, accordering.id):
            if (
                stap.accordeur_gebruiker_id == accordeur_id
                and stap.besluit == StapBesluit.AKKOORD.value
                and stap.besluit_bron == StapBesluitBron.HANDMATIG.value
            ):
                return True
    return False


def wachtrij_voor_accordeur(*, actor_id: uuid.UUID, administratie_ids: list[uuid.UUID]) -> list[WachtrijItem]:
    """De accordeer-wachtrij (PWA-endpoint, scope-aanscherping 2026-08-08: uitsluitend de
    wachtrij): documenten in ter_accordering waar déze accordeur aan de beurt is — per
    administratie binnen de scope (RLS dwingt dat af; de lijst komt uit de scope-bron)."""
    items: list[WachtrijItem] = []
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id) as session:
            administratie = session.get(Administratie, administratie_id)
            open_rondes = list(
                session.scalars(
                    select(DocumentAccordering).where(
                        DocumentAccordering.administratie_id == administratie_id,
                        DocumentAccordering.status == AccorderingStatus.OPEN.value,
                    )
                )
            )
            for accordering in open_rondes:
                stappen = _stappen_van(session, accordering.id)
                volgende = _eerstvolgende_open_stap(stappen)
                if volgende is None or volgende.accordeur_gebruiker_id != actor_id:
                    continue
                voorstel = session.get(Boekvoorstel, accordering.document_id)
                leverancier = None
                if voorstel is not None and voorstel.vendor_id is not None:
                    vendor = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
                    leverancier = vendor.naam if vendor else None
                items.append(
                    WachtrijItem(
                        document_id=accordering.document_id,
                        administratie_id=administratie_id,
                        administratie_naam=administratie.naam if administratie else None,
                        leverancier_naam=leverancier,
                        referentie=voorstel.referentie if voorstel else None,
                        factuurdatum=voorstel.factuurdatum if voorstel else None,
                        totaalbedrag=voorstel.totaalbedrag if voorstel else None,
                        aangeboden_op=accordering.aangeboden_op,
                        laag_volgnummer=volgende.volgnummer,
                        boeking_omschrijving=_boeking_omschrijving(
                            session, administratie_id=administratie_id, document_id=accordering.document_id
                        ),
                        staande_regel_kandidaat=_is_staande_regel_kandidaat(
                            session,
                            administratie_id=administratie_id,
                            accordeur_id=actor_id,
                            document_id=accordering.document_id,
                            vendor_id=voorstel.vendor_id if voorstel else None,
                            totaalbedrag=voorstel.totaalbedrag if voorstel else None,
                        ),
                    )
                )
    items.sort(key=lambda i: i.aangeboden_op)
    return items


def aantallen_aan_de_beurt(*, administratie_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Per accordeur het aantal open documenten waar híj/zij nu aan de beurt is, voor één
    administratie — de selectiebron van de dagelijkse herinnering (berichten-bouwsteen):
    exact dezelfde aan-de-beurt-definitie als de wachtrij (eerstvolgende open vereiste stap),
    zodat teller en wachtrij nooit uiteenlopen. Bewust zonder de zware per-item-verrijking
    van wachtrij_voor_accordeur (de herinnering heeft alleen het aantal nodig)."""
    aantallen: dict[uuid.UUID, int] = {}
    with scoped_session(administratie_id) as session:
        open_rondes = list(
            session.scalars(
                select(DocumentAccordering).where(
                    DocumentAccordering.administratie_id == administratie_id,
                    DocumentAccordering.status == AccorderingStatus.OPEN.value,
                )
            )
        )
        for accordering in open_rondes:
            volgende = _eerstvolgende_open_stap(_stappen_van(session, accordering.id))
            if volgende is not None:
                aantallen[volgende.accordeur_gebruiker_id] = (
                    aantallen.get(volgende.accordeur_gebruiker_id, 0) + 1
                )
    return aantallen


@dataclass(frozen=True)
class AccordeurKandidaat:
    id: uuid.UUID
    naam: str


def accordeur_kandidaten(*, administratie_id: uuid.UUID) -> list[AccordeurKandidaat]:
    """Actieve gebruikers met rol klant-accordeur en scope op deze administratie — de keuzelijst
    voor het lagen-beheer (Instellingen). Alleen id + naam (dataminimalisatie, zelfde afweging
    als beheer/service.py::lijst_medewerkers)."""
    from app.db.models import GebruikerAdministratie, GebruikerStatus

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Gebruiker.id, Gebruiker.naam)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(
                GebruikerAdministratie.administratie_id == administratie_id,
                Gebruiker.status == GebruikerStatus.ACTIEF,
                Gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR,
            )
        ).all()
    return sorted(
        (AccordeurKandidaat(id=rij.id, naam=rij.naam) for rij in rijen), key=lambda k: k.naam.lower()
    )


def staande_regels(*, administratie_id: uuid.UUID) -> tuple[list[StaandeGoedkeuring], dict[uuid.UUID, str]]:
    with scoped_session(administratie_id) as session:
        regels = list(
            session.scalars(
                select(StaandeGoedkeuring)
                .where(StaandeGoedkeuring.administratie_id == administratie_id)
                .order_by(StaandeGoedkeuring.aangemaakt_op.desc())
            )
        )
        namen = _gebruikersnamen(session, {r.accordeur_gebruiker_id for r in regels})
        session.expunge_all()
    return regels, namen


def trek_staande_regel_in(*, administratie_id: uuid.UUID, regel_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Intrekbaar door kantoor én door de accordeur zelf (besluit 2026-08-08: zichtbaar +
    intrekbaar) — nooit een DELETE."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        regel = session.get(StaandeGoedkeuring, regel_id)
        if regel is None or regel.administratie_id != administratie_id:
            raise DocumentNietGevonden(f"Onbekende staande goedkeuring: {regel_id}")
        if not regel.actief:
            raise AccorderingFout("Deze staande goedkeuring is al ingetrokken")
        regel.actief = False
        regel.ingetrokken_door = actor_id
        regel.ingetrokken_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="staande_goedkeuring",
            record_id=regel.id,
            actie="staande_goedkeuring_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": True},
            nieuwe_waarde={"actief": False},
            administratie_id=administratie_id,
        )
