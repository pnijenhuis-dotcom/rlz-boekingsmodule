"""Klant-accorderingsflow (fase 3-kern, mockup #autorisatie + BESLISSINGEN "Mobiele bouwstenen
accordeur-PWA" punten 1/5/6, migratie 0033).

Sequentiële lagen per administratie (optionele bedragdrempel), één open accorderingsronde per
document met bevroren stappen, en de staande goedkeuring (besluit Peter 2026-08-08): per
accordeur + leverancier + exact bedrag — vervangt alleen de menselijke akkoord-klik, nooit de
harde checks (die draaien bij het uiteindelijke boeken onverkort opnieuw)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class AccorderingStatus(enum.StrEnum):
    """OPEN = wacht op één of meer lagen; AFGEROND = alle vereiste lagen akkoord (document gaat
    door naar de boekmotor mét alle harde checks); AFGEWEZEN = een accordeur wees af met
    verplichte reden (document → afgewezen, zichtbaar in de werkvoorraad); INGETROKKEN = het
    kantoor haalde het document terug uit de accordering; VERVALLEN = de ronde is door het
    systeem beëindigd omdat de accorderingsconfiguratie (lagen/toggle) van de administratie
    wijzigde — de bevroren stappen kloppen dan niet meer, het document gaat terug naar
    klaar_om_te_boeken en moet opnieuw aangeboden worden (werkstroom-run 27/28-08, punt 2a)."""

    OPEN = "open"
    AFGEROND = "afgerond"
    AFGEWEZEN = "afgewezen"
    INGETROKKEN = "ingetrokken"
    VERVALLEN = "vervallen"


class StapBesluit(enum.StrEnum):
    """VERVALLEN (bundel 09-09 blok 2): de stap is bij een herberekening van de ronde niet voortgezet (akkoord past
    niet meer in de nieuwe lagen, of de laag verdween). De rij blijft staan als historie (geen DELETE-recht op
    accordering_stap, en niets verdwijnt stil) maar telt nergens meer mee: `vereist` staat dan op False en
    `service._stappen_van` filtert 'm uit de ronde-weergave."""

    AKKOORD = "akkoord"
    AFGEWEZEN = "afgewezen"
    VERVALLEN = "vervallen"


class DocumentHerinnering(Base):
    """Handmatige herinnering per document (migratie 0053, beheer-mini 2026-08-16): kantoor
    stuurt de accordeur die aan de beurt is per direct een extra bericht (push, anders mail).
    Dagrem via de unieke index (document_id, datum) — datum is de Europe/Amsterdam-kalenderdag;
    claim-vóór-verzenden zoals platform.accordeur_herinnering."""

    __tablename__ = "document_herinnering"
    __table_args__ = (
        Index("ix_document_herinnering_document_id", "document_id"),
        Index("ix_document_herinnering_administratie_id", "administratie_id"),
        Index("uq_document_herinnering_dag", "document_id", "datum", unique=True),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    accordeur_gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    datum: Mapped[date] = mapped_column()
    status: Mapped[str] = mapped_column(default="bezig")
    kanaal: Mapped[str | None] = mapped_column(default=None)
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    verzonden_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verzonden_op: Mapped[datetime | None] = mapped_column(default=None)


class StapBesluitBron(enum.StrEnum):
    """HANDMATIG = de accordeur klikte zelf; STAANDE_REGEL = automatisch akkoord door een
    actieve staande goedkeuring (zelfde leverancier + exact bedrag) — mét audit + tijdlijn."""

    HANDMATIG = "handmatig"
    STAANDE_REGEL = "staande_regel"


class AccorderingLaag(Base):
    """Eén laag in het accorderingsschema van een administratie. Sequentieel op volgnummer;
    `bedrag_drempel` = laag geldt alleen voor facturen bóven dit bedrag (mockup: "Alleen
    > € 1.000"). Append-only: deactiveren i.p.v. verwijderen."""

    __tablename__ = "accordering_laag"
    __table_args__ = (
        Index("ix_accordering_laag_administratie_id", "administratie_id"),
        Index("ix_accordering_laag_afdeling_id", "afdeling_id"),
        Index("ix_accordering_laag_leverancier_route_id", "leverancier_route_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    volgnummer: Mapped[int]
    accordeur_gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bedrag_drempel: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    # Afdelingen (migratie 0084): NULL = de administratie-route (bestaand); gevuld = de route van
    # díe afdeling, die de administratie-route vervángt zodra een document die afdeling draagt.
    afdeling_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.afdeling.id"), default=None
    )
    #: Peter 17-09 (migratie 0156): gevuld = laag van een LEVERANCIERSroute (vervangt de administratieroute voor de
    #: aangevinkte leveranciers); NULL = administratie-/afdelingsroute.
    leverancier_route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.accordering_leverancier_route.id"), default=None
    )
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gedeactiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedeactiveerd_op: Mapped[datetime | None] = mapped_column(default=None)


class AccorderingLeverancierRoute(Base):
    """Peter 17-09 (migratie 0156): één accorderingsroute voor één of meer LEVERANCIERS — vervangt de
    administratieroute voor documenten van die leveranciers (zelfde patroon als de afdelingsroute, 0084). Voorrang:
    afdelingsroute > leveranciersroute > administratieroute (beslispunt). Append-only: deactiveren, nooit verwijderen."""

    __tablename__ = "accordering_leverancier_route"
    __table_args__ = (
        Index("ix_accordering_leverancier_route_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    naam: Mapped[str] = mapped_column(Text)
    #: Peter 18-09 (migratie 0164): 'vervangt' = de route vervangt de administratieroute (17-09-gedrag); 'bovenop' = de
    #: gewone lagen van de administratie op het moment van de ronde + de extra lagen van deze route op `positie`
    #: ('voor' = vóór laag 1, 'na' = ná de laatste gewone laag). Zo hoeft Bouwadvies Oost Nederland haar drie gewone
    #: lagen niet te kopiëren in een route die stil uit de pas zou lopen.
    modus: Mapped[str] = mapped_column(Text, default="vervangt", server_default="vervangt")
    positie: Mapped[str | None] = mapped_column(Text, default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gedeactiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedeactiveerd_op: Mapped[datetime | None] = mapped_column(default=None)


class AccorderingLeverancierRouteVendor(Base):
    """De aangevinkte leveranciers van een leveranciersroute (crediteurrecords; de match bij het aanbieden loopt over de
    crediteur-IDENTITEIT via `crediteuren/voorkeur.py`). Eén leverancier in hooguit één ACTIEVE route (partiële unieke
    index `ux_accordering_leverancier_route_vendor_actief`) — de service vertaalt dat naar een 409 mét reden."""

    __tablename__ = "accordering_leverancier_route_vendor"
    __table_args__ = (
        Index("ix_accordering_leverancier_route_vendor_route_id", "route_id"),
        Index(
            "ux_accordering_leverancier_route_vendor_actief",
            "administratie_id",
            "vendor_id",
            unique=True,
            postgresql_where=text("actief"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.accordering_leverancier_route.id")
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    herkomst: Mapped[str] = mapped_column(Text, default="handmatig")
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gedeactiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedeactiveerd_op: Mapped[datetime | None] = mapped_column(default=None)


class DocumentAccordering(Base):
    """Eén accorderingsronde per aangeboden document (hooguit één open — partiële unique
    index). `detail` draagt vrije context (bv. totaalbedrag/leverancier op aanbied-moment)."""

    __tablename__ = "document_accordering"
    __table_args__ = (
        Index("ix_document_accordering_document_id", "document_id"),
        Index(
            "uq_document_accordering_open",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    status: Mapped[str] = mapped_column(default=AccorderingStatus.OPEN.value)
    aangeboden_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangeboden_op: Mapped[datetime] = mapped_column(server_default=func.now())
    afgerond_op: Mapped[datetime | None] = mapped_column(default=None)
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)


class AccorderingStap(Base):
    """De bevroren evaluatie van één laag op het aanbied-moment: `vereist` is de
    drempel-uitkomst (totaalbedrag onbekend = vereist, fail-closed). Besluit + bron + evt.
    staande-regel-verwijzing en afwijsreden."""

    __tablename__ = "accordering_stap"
    __table_args__ = (
        Index("ix_accordering_stap_accordering_id", "accordering_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    accordering_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document_accordering.id")
    )
    volgnummer: Mapped[int]
    accordeur_gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bedrag_drempel: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    vereist: Mapped[bool] = mapped_column(default=True)
    besluit: Mapped[str | None] = mapped_column(default=None)
    besluit_bron: Mapped[str | None] = mapped_column(default=None)
    staande_regel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    reden: Mapped[str | None] = mapped_column(default=None)
    besloten_op: Mapped[datetime | None] = mapped_column(default=None)


class StaandeGoedkeuring(Base):
    """Staande goedkeuring (besluit Peter 2026-08-08): "akkoord voor deze en alle toekomstige
    facturen van deze leverancier mits exact hetzelfde bedrag". Per accordeur + vendor + bedrag;
    zichtbaar + intrekbaar (kantoor-UI nu, accordeur-app later); harde checks blijven onverkort
    blokkerend — de regel vervangt alleen de akkoord-klik."""

    __tablename__ = "staande_goedkeuring"
    __table_args__ = (
        Index("ix_staande_goedkeuring_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    accordeur_gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    leverancier_naam: Mapped[str | None] = mapped_column(default=None)
    bedrag: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    # Afdelingen (migratie 0084): de regel telt alleen binnen de afdeling waar ze is afgegeven
    # (NULL = afgegeven op een document zonder afdeling — geldt dan ook alleen dáárvoor).
    afdeling_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.afdeling.id"), default=None
    )
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bron_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)


class VoorstelStilSoort(enum.StrEnum):
    """STIL_TOT = "nee"/"niet nu" van de accordeur → het voorstel zwijgt tot `stil_tot` (90 dagen); NOOIT =
    uitzondering per leverancier (accordeur zelf in de app, of de Beheerder administratiebreed)."""

    STIL_TOT = "stil_tot"
    NOOIT = "nooit"


class StaandeGoedkeuringVoorstelStil(Base):
    """Stilte/uitzondering op het staande-goedkeuring-VOORSTEL (blok 7 run 11-09 middag, migratie 0134; casus
    Lusso). Raakt de staande goedkeuring zelf niet — alleen of de app de vraag "voortaan automatisch akkoord?"
    stelt. `accordeur_gebruiker_id` NULL = geldt voor álle accordeurs van de administratie (Beheerder-uitzondering
    vanuit de kantoor-web). Opheffen = `actief=False` mét wie/wanneer — nooit een DELETE; elke zetting geauditeerd
    oud→nieuw."""

    __tablename__ = "staande_goedkeuring_voorstel_stil"
    __table_args__ = (
        Index("ix_staande_goedkeuring_voorstel_stil_administratie_id", "administratie_id"),
        Index("ix_staande_goedkeuring_voorstel_stil_vendor", "administratie_id", "vendor_id"),
        CheckConstraint("soort IN ('stil_tot', 'nooit')", name="ck_staande_goedkeuring_voorstel_stil_soort"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    accordeur_gebruiker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    leverancier_naam: Mapped[str | None] = mapped_column(default=None)
    soort: Mapped[str]
    stil_tot: Mapped[date | None] = mapped_column(default=None)
    reden: Mapped[str | None] = mapped_column(default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    opgeheven_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    opgeheven_op: Mapped[datetime | None] = mapped_column(default=None)
