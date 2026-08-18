"""Globaal zoeken + archief (mockup #zoeken, CLAUDE.md "Zoeken"/"Archief" — blok 4 grote
opdracht 2026-08-09).

Zoeken doorzoekt per administratie in de scope van de gebruiker (RLS + server-side — géén
scope = géén data): documenten/boekingen incl. het geboekte archief (bestandsnaam, leverancier/
debiteur, referentie/Vastly-factuurnummer, RLZ-boekstuknummer, bedrag) én de lokaal aanwezige
extractietekst (het veldvoorstel in de tijdlijn — bewust GEEN nieuwe AI-calls: wat niet lokaal
ligt wordt niet doorzocht), plus vragen & antwoorden en audit-gebeurtenissen. Vraag- en
accorderingshistorie komen inline mee op de documenttreffers (mockup: "akkoord S. Bakker
(laag 1) 17-06 · automatisch geboekt").

Archief: geboekte documenten per administratie, terugvindbaar mét PDF (bewaarplicht 7 jaar) —
de bijlage zelf blijft via het bestaande scope-gecontroleerde bestand-endpoint bereikbaar.

Correctiespoor-kanttekening (koppelcontract §7.3): actie 19 laat in RLZ géén zichtbaar
credit-/stornodocument achter — het correctiespoor in deze schermen komt uit onze eigen
tijdlijn/audit_event, nooit uit RLZ's documentstatus."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import String, cast, exists, or_, select
from sqlalchemy.orm import Session

from app.accordering.models import AccorderingStap, DocumentAccordering
from app.auth import service as auth_service
from app.db.models import AuditEvent, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
    Vraag,
)
from app.sync.models import VendorCache
from app.verkoop.models import VerkoopVoorstel

_MAX_DOCUMENTEN_PER_ADMINISTRATIE = 50
_MAX_AUDIT_PER_ADMINISTRATIE = 25
_MIN_TERM_LENGTE = 2


@dataclass(frozen=True)
class VraagHit:
    vraag_tekst: str
    antwoord_tekst: str | None
    status: str


@dataclass(frozen=True)
class AccorderingHit:
    volgnummer: int
    accordeur_naam: str | None
    besluit: str | None
    besluit_bron: str | None
    besloten_op: datetime | None


@dataclass(frozen=True)
class DocumentHit:
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    soort: str
    status: str
    bestandsnaam: str
    leverancier: str | None
    referentie: str | None
    rlz_boekstuknummer: str | None
    totaalbedrag: Decimal | None
    factuurdatum: date | None
    aangemaakt_op: datetime
    automatisch_geboekt: bool
    vragen: list[VraagHit] = field(default_factory=list)
    accordering: list[AccorderingHit] = field(default_factory=list)


@dataclass(frozen=True)
class AuditHit:
    tijdstip: datetime
    actor_naam: str | None
    actie: str
    administratie_naam: str
    detail: dict | None


@dataclass(frozen=True)
class AdministratieHit:
    administratie_id: uuid.UUID
    naam: str


@dataclass(frozen=True)
class ZoekResultaat:
    term: str
    administraties: list[AdministratieHit]
    documenten: list[DocumentHit]
    audit: list[AuditHit]


def _als_bedrag(term: str) -> Decimal | None:
    try:
        return Decimal(term.replace("€", "").replace(".", "").replace(",", ".").strip()) \
            if ("," in term) else Decimal(term.replace("€", "").strip())
    except InvalidOperation:
        return None


def _document_voorwaarden(term: str):
    patroon = f"%{term}%"
    voorwaarden = [
        Document.bestandsnaam.ilike(patroon),
        Boekvoorstel.referentie.ilike(patroon),
        Boekvoorstel.rlz_boekstuknummer.ilike(patroon),
        VerkoopVoorstel.factuurnummer.ilike(patroon),
        VerkoopVoorstel.rlz_boekstuknummer.ilike(patroon),
        VerkoopVoorstel.debiteur_naam.ilike(patroon),
        # Lokaal aanwezige extractietekst (het veldvoorstel in de tijdlijn) — bewust geen
        # nieuwe AI-calls; documenten zonder lokaal veldvoorstel zijn hierop niet vindbaar.
        exists(
            select(DocumentGebeurtenis.id).where(
                DocumentGebeurtenis.document_id == Document.id,
                DocumentGebeurtenis.detail.has_key("veldvoorstel"),
                cast(DocumentGebeurtenis.detail["veldvoorstel"], String).ilike(patroon),
            )
        ),
        # Leverancier via de vendor-cache (crediteurnaam op het boekvoorstel).
        exists(
            select(VendorCache.id).where(
                VendorCache.id == Boekvoorstel.vendor_id,
                VendorCache.administratie_id == Document.administratie_id,
                VendorCache.naam.ilike(patroon),
            )
        ),
    ]
    bedrag = _als_bedrag(term)
    if bedrag is not None:
        voorwaarden.append(Boekvoorstel.totaalbedrag == bedrag)
        voorwaarden.append(VerkoopVoorstel.totaalbedrag_incl == bedrag)
    return or_(*voorwaarden)


def _vraag_hits(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[VraagHit]]:
    resultaat: dict[uuid.UUID, list[VraagHit]] = {}
    if not document_ids:
        return resultaat
    for vraag in session.scalars(
        select(Vraag).where(Vraag.document_id.in_(document_ids)).order_by(Vraag.gesteld_op)
    ):
        resultaat.setdefault(vraag.document_id, []).append(
            VraagHit(vraag_tekst=vraag.vraag_tekst, antwoord_tekst=vraag.antwoord_tekst, status=vraag.status)
        )
    return resultaat


def _accordering_hits(
    session: Session, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AccorderingHit]]:
    resultaat: dict[uuid.UUID, list[AccorderingHit]] = {}
    if not document_ids:
        return resultaat
    rijen = session.execute(
        select(DocumentAccordering.document_id, AccorderingStap, Gebruiker.naam)
        .join(AccorderingStap, AccorderingStap.accordering_id == DocumentAccordering.id)
        .join(Gebruiker, Gebruiker.id == AccorderingStap.accordeur_gebruiker_id, isouter=True)
        .where(DocumentAccordering.document_id.in_(document_ids))
        .order_by(DocumentAccordering.aangeboden_op, AccorderingStap.volgnummer)
    ).all()
    for document_id, stap, naam in rijen:
        resultaat.setdefault(document_id, []).append(
            AccorderingHit(
                volgnummer=stap.volgnummer,
                accordeur_naam=naam,
                besluit=stap.besluit,
                besluit_bron=stap.besluit_bron,
                besloten_op=stap.besloten_op,
            )
        )
    return resultaat


def _automatisch_geboekt_ids(session: Session, document_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not document_ids:
        return set()
    return set(
        session.scalars(
            select(DocumentGebeurtenis.document_id).where(
                DocumentGebeurtenis.document_id.in_(document_ids),
                DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                DocumentGebeurtenis.detail.has_key("automatisch_geboekt"),
            )
        )
    )


def _zoek_documenten_in_administratie(
    *, administratie_id: uuid.UUID, administratie_naam: str, term: str
) -> list[DocumentHit]:
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Document, Boekvoorstel, VerkoopVoorstel)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id, isouter=True)
            .join(VerkoopVoorstel, VerkoopVoorstel.document_id == Document.id, isouter=True)
            .where(
                Document.administratie_id == administratie_id,
                Document.status != DocumentStatus.VERWIJDERD,
                _document_voorwaarden(term),
            )
            .order_by(Document.aangemaakt_op.desc())
            .limit(_MAX_DOCUMENTEN_PER_ADMINISTRATIE)
        ).all()

        document_ids = [document.id for document, _, _ in rijen]
        vendor_namen: dict[uuid.UUID, str | None] = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(
                    VendorCache.administratie_id == administratie_id,
                    VendorCache.id.in_(
                        [bv.vendor_id for _, bv, _ in rijen if bv is not None and bv.vendor_id is not None]
                    ),
                )
            ).all()
        )
        vragen = _vraag_hits(session, document_ids)
        accorderingen = _accordering_hits(session, document_ids)
        automatisch = _automatisch_geboekt_ids(session, document_ids)

        hits: list[DocumentHit] = []
        for document, boekvoorstel, verkoopvoorstel in rijen:
            leverancier = None
            referentie = None
            boekstuk = None
            totaal = None
            datum = None
            if boekvoorstel is not None:
                leverancier = vendor_namen.get(boekvoorstel.vendor_id) if boekvoorstel.vendor_id else None
                referentie = boekvoorstel.referentie
                boekstuk = boekvoorstel.rlz_boekstuknummer
                totaal = boekvoorstel.totaalbedrag
                datum = boekvoorstel.factuurdatum
            if verkoopvoorstel is not None:
                leverancier = leverancier or verkoopvoorstel.debiteur_naam
                referentie = referentie or verkoopvoorstel.factuurnummer
                boekstuk = boekstuk or verkoopvoorstel.rlz_boekstuknummer
                totaal = totaal if totaal is not None else verkoopvoorstel.totaalbedrag_incl
                datum = datum or verkoopvoorstel.factuurdatum
            hits.append(
                DocumentHit(
                    document_id=document.id,
                    administratie_id=administratie_id,
                    administratie_naam=administratie_naam,
                    soort=document.soort,
                    status=document.status.value,
                    bestandsnaam=document.bestandsnaam,
                    leverancier=leverancier,
                    referentie=referentie,
                    rlz_boekstuknummer=boekstuk,
                    totaalbedrag=totaal,
                    factuurdatum=datum,
                    aangemaakt_op=document.aangemaakt_op,
                    automatisch_geboekt=document.id in automatisch,
                    vragen=vragen.get(document.id, []),
                    accordering=accorderingen.get(document.id, []),
                )
            )

        # Vraag-/antwoordtreffers horen er óók bij wanneer het document zelf niet matcht.
        patroon = f"%{term}%"
        vraag_document_ids = list(
            session.scalars(
                select(Vraag.document_id)
                .where(
                    Vraag.administratie_id == administratie_id,
                    or_(Vraag.vraag_tekst.ilike(patroon), Vraag.antwoord_tekst.ilike(patroon)),
                )
                .distinct()
            )
        )
        extra_ids = [d for d in vraag_document_ids if d not in document_ids]
        if extra_ids:
            extra_rijen = session.execute(
                select(Document, Boekvoorstel)
                .join(Boekvoorstel, Boekvoorstel.document_id == Document.id, isouter=True)
                .where(Document.id.in_(extra_ids), Document.status != DocumentStatus.VERWIJDERD)
            ).all()
            extra_vragen = _vraag_hits(session, extra_ids)
            extra_acc = _accordering_hits(session, extra_ids)
            extra_auto = _automatisch_geboekt_ids(session, extra_ids)
            for document, boekvoorstel in extra_rijen:
                hits.append(
                    DocumentHit(
                        document_id=document.id,
                        administratie_id=administratie_id,
                        administratie_naam=administratie_naam,
                        soort=document.soort,
                        status=document.status.value,
                        bestandsnaam=document.bestandsnaam,
                        leverancier=None,
                        referentie=boekvoorstel.referentie if boekvoorstel else None,
                        rlz_boekstuknummer=boekvoorstel.rlz_boekstuknummer if boekvoorstel else None,
                        totaalbedrag=boekvoorstel.totaalbedrag if boekvoorstel else None,
                        factuurdatum=boekvoorstel.factuurdatum if boekvoorstel else None,
                        aangemaakt_op=document.aangemaakt_op,
                        automatisch_geboekt=document.id in extra_auto,
                        vragen=extra_vragen.get(document.id, []),
                        accordering=extra_acc.get(document.id, []),
                    )
                )
        return hits


def _zoek_audit_in_administratie(
    *, administratie_id: uuid.UUID, administratie_naam: str, term: str
) -> list[AuditHit]:
    patroon = f"%{term}%"
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(AuditEvent, Gebruiker.naam)
            .join(Gebruiker, Gebruiker.id == AuditEvent.actor_id, isouter=True)
            .where(
                AuditEvent.administratie_id == administratie_id,
                or_(
                    AuditEvent.actie.ilike(patroon),
                    cast(AuditEvent.nieuwe_waarde, String).ilike(patroon),
                    cast(AuditEvent.oude_waarde, String).ilike(patroon),
                ),
            )
            .order_by(AuditEvent.tijdstip.desc())
            .limit(_MAX_AUDIT_PER_ADMINISTRATIE)
        ).all()
        return [
            AuditHit(
                tijdstip=event.tijdstip,
                actor_naam=naam,
                actie=event.actie,
                administratie_naam=administratie_naam,
                detail=event.nieuwe_waarde,
            )
            for event, naam in rijen
        ]


def zoek(*, actor_id: uuid.UUID, rol: GebruikerRol, term: str) -> ZoekResultaat:
    """Globaal zoeken over álle administraties in de scope van de gebruiker — per administratie
    een eigen gescopede sessie (RLS), zelfde patroon als het werkvoorraad-overzicht. Een te
    korte term geeft bewust een leeg resultaat (geen full-table-dumps)."""
    term = term.strip()
    if len(term) < _MIN_TERM_LENGTE:
        return ZoekResultaat(term=term, administraties=[], documenten=[], audit=[])
    administraties = auth_service.mijn_administraties(actor_id=actor_id, rol=rol)

    # Administratie-hits (veegrun 2026-08-18): klantnaam matcht → link naar de klantpagina.
    # Scope-veilig zonder extra query: de naam-match loopt uitsluitend over de eigen
    # scope-lijst die hierboven al is opgehaald (beheerder = alles, anders koppeltabel).
    administratie_hits = [
        AdministratieHit(administratie_id=a.id, naam=a.naam)
        for a in administraties
        if term.lower() in a.naam.lower()
    ]

    documenten: list[DocumentHit] = []
    audit: list[AuditHit] = []
    for administratie in administraties:
        documenten.extend(
            _zoek_documenten_in_administratie(
                administratie_id=administratie.id, administratie_naam=administratie.naam, term=term
            )
        )
        audit.extend(
            _zoek_audit_in_administratie(
                administratie_id=administratie.id, administratie_naam=administratie.naam, term=term
            )
        )
    documenten.sort(key=lambda hit: hit.aangemaakt_op, reverse=True)
    audit.sort(key=lambda hit: hit.tijdstip, reverse=True)
    return ZoekResultaat(term=term, administraties=administratie_hits, documenten=documenten, audit=audit)


@dataclass(frozen=True)
class ArchiefDocument:
    document_id: uuid.UUID
    soort: str
    bestandsnaam: str
    leverancier: str | None
    referentie: str | None
    rlz_boekstuknummer: str | None
    totaalbedrag: Decimal | None
    factuurdatum: date | None
    geboekt_op: datetime | None
    automatisch_geboekt: bool


def archief(*, administratie_id: uuid.UUID) -> list[ArchiefDocument]:
    """Het geboekte archief van één administratie (bewaarplicht 7 jaar): kopgegevens +
    RLZ-boekstuknummer + boekmoment; de PDF/UBL zelf via het bestaande bestand-endpoint."""
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Document, Boekvoorstel, VerkoopVoorstel)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id, isouter=True)
            .join(VerkoopVoorstel, VerkoopVoorstel.document_id == Document.id, isouter=True)
            .where(
                Document.administratie_id == administratie_id,
                Document.status == DocumentStatus.GEBOEKT,
            )
            .order_by(Document.aangemaakt_op.desc())
        ).all()
        document_ids = [document.id for document, _, _ in rijen]
        vendor_namen: dict[uuid.UUID, str | None] = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(
                    VendorCache.administratie_id == administratie_id,
                    VendorCache.id.in_(
                        [bv.vendor_id for _, bv, _ in rijen if bv is not None and bv.vendor_id is not None]
                    ),
                )
            ).all()
        )
        automatisch = _automatisch_geboekt_ids(session, document_ids)
        geboekt_momenten: dict[uuid.UUID, datetime] = {}
        if document_ids:
            for gebeurtenis in session.scalars(
                select(DocumentGebeurtenis)
                .where(
                    DocumentGebeurtenis.document_id.in_(document_ids),
                    DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
                )
                .order_by(DocumentGebeurtenis.tijdstip)
            ):
                geboekt_momenten[gebeurtenis.document_id] = gebeurtenis.tijdstip

        resultaat = []
        for document, boekvoorstel, verkoopvoorstel in rijen:
            leverancier = None
            referentie = None
            boekstuk = None
            totaal = None
            datum = None
            if boekvoorstel is not None:
                leverancier = vendor_namen.get(boekvoorstel.vendor_id) if boekvoorstel.vendor_id else None
                referentie = boekvoorstel.referentie
                boekstuk = boekvoorstel.rlz_boekstuknummer
                totaal = boekvoorstel.totaalbedrag
                datum = boekvoorstel.factuurdatum
            if verkoopvoorstel is not None:
                leverancier = leverancier or verkoopvoorstel.debiteur_naam
                referentie = referentie or verkoopvoorstel.factuurnummer
                boekstuk = boekstuk or verkoopvoorstel.rlz_boekstuknummer
                totaal = totaal if totaal is not None else verkoopvoorstel.totaalbedrag_incl
                datum = datum or verkoopvoorstel.factuurdatum
            resultaat.append(
                ArchiefDocument(
                    document_id=document.id,
                    soort=document.soort,
                    bestandsnaam=document.bestandsnaam,
                    leverancier=leverancier,
                    referentie=referentie,
                    rlz_boekstuknummer=boekstuk,
                    totaalbedrag=totaal,
                    factuurdatum=datum,
                    geboekt_op=geboekt_momenten.get(document.id),
                    automatisch_geboekt=document.id in automatisch,
                )
            )
        return resultaat
