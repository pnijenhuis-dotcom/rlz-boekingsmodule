"""Afdelingen binnen een administratie (bouwrun 28-08 blok A, mockup afdelingen.html; migratie
0084). Casus Kempen Facilities: buitendienst-facturen → beheerder-accordeur, receptie-facturen →
backoffice. De afdeling wordt handmatig door kantoor gekozen per inkoopdocument (prefill uit het
geheugen per leverancier is een voorstel — de mens beslist), de toggle staat op
`platform.administratie.afdelingen_ingeschakeld` (project_verplicht-patroon)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Afdeling(Base):
    """Eén afdeling. `is_terugval` = de automatische terugval-afdeling "Algemeen" die bij het
    aanzetten van de toggle ontstaat en de administratie-accorderingsconfig volgt (zo breekt de
    toggle niets aan lopende routes en is er altijd een geldige keuze). Archiveren i.p.v.
    verwijderen — documenten verwijzen ernaar; de terugval is niet archiveerbaar."""

    __tablename__ = "afdeling"
    __table_args__ = (
        Index("ix_afdeling_administratie_id", "administratie_id"),
        # Gespiegeld uit migratie 0084 (alembic check als signaal — hygiëne-run 16-08): naam uniek onder
        # actieve afdelingen (case-insensitief) en precies één terugval-afdeling per administratie.
        Index(
            "uq_afdeling_actieve_naam",
            "administratie_id",
            text("lower(naam)"),
            unique=True,
            postgresql_where=text("actief"),
        ),
        Index("uq_afdeling_terugval", "administratie_id", unique=True, postgresql_where=text("is_terugval")),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    naam: Mapped[str]
    is_terugval: Mapped[bool] = mapped_column(default=False, server_default="false")
    actief: Mapped[bool] = mapped_column(default=True, server_default="true")
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gearchiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gearchiveerd_op: Mapped[datetime | None] = mapped_column(default=None)


class LeverancierAfdeling(Base):
    """Prefill-geheugen: laatste afdelingskeuze per (administratie, crediteur) — laatste keuze wint,
    geschreven bij boekvoorstel-opslaan mét crediteur én afdeling. Bewust geen FK naar
    vendor_cache (overleeft sync-verdwijning, patroon leverancier_voorkeur). Puur een voorstel
    voor het controlescherm (herkomst-chip "vorige keuze bij <leverancier>"), nooit een
    automatische toewijzing (mockup-beslispunt 3)."""

    __tablename__ = "leverancier_afdeling"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    afdeling_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.afdeling.id"))
    laatste_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
