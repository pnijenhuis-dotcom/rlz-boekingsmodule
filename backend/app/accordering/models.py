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

from sqlalchemy import ForeignKey, Index, Numeric, func, text
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
    AKKOORD = "akkoord"
    AFGEWEZEN = "afgewezen"


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
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    volgnummer: Mapped[int]
    accordeur_gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bedrag_drempel: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
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
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bron_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)
