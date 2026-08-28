"""Voorraad-aansluiting (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html; migratie 0086) —
eerste bewoner van het `mi`-schema. Controle-laag, géén tweede voorraadadministratie: instroom =
regel-niveau feiten uit AI-gescande inkoopfacturen (externe documenten), uitstroom = geregistreerde
verkoopfactuurregels; theoretische stand vs systeemstand = verschil-signaal. Nooit geboekt in RLZ."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

SCHEMA = "mi"
# Vendor-sentinel voor normalisatieregels zonder herkende leverancier (unique-constraint kent
# geen NULL-gelijkheid).
ONBEKENDE_LEVERANCIER = uuid.UUID(int=0)


class Artikelgroep(Base):
    """Genormaliseerde artikelgroep ("Koppelingen 48mm") per administratie; tolerantie-% per groep
    (default 1 — mockup-beslispunt 4). Actief/inactief, nooit verwijderen."""

    __tablename__ = "artikelgroep"
    __table_args__ = (
        Index("ix_artikelgroep_administratie_id", "administratie_id"),
        CheckConstraint("tolerantie_pct >= 0 AND tolerantie_pct <= 100", name="ck_artikelgroep_tolerantie"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    naam: Mapped[str]
    eenheid: Mapped[str] = mapped_column(default="st", server_default="st")
    tolerantie_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("1.00"), server_default="1.00")
    actief: Mapped[bool] = mapped_column(default=True, server_default="true")
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class NormalisatieRegel(Base):
    """Deterministische normalisatieregel per (administratie, leverancier, genormaliseerde
    artikeltekst): → artikelgroep, of `uitgesloten` (dienst/transport). Bron 'regel' = de vaste
    dienst-/transportregel, 'ai' = eerste match (direct toegepast, zekerheid erbij), 'handmatig' =
    correctie door de mens (geldt vanaf dan voor álle regels met dezelfde tekst; historie herrekend).
    Daarna nooit meer een AI-call voor dezelfde tekst."""

    __tablename__ = "normalisatie_regel"
    __table_args__ = (
        UniqueConstraint("administratie_id", "vendor_id", "artikeltekst_norm", name="uq_normalisatie_regel_tekst"),
        CheckConstraint("bron IN ('ai', 'handmatig', 'regel')", name="ck_normalisatie_regel_bron"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    artikeltekst_norm: Mapped[str]
    artikelgroep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"), default=None
    )
    uitgesloten: Mapped[bool] = mapped_column(default=False, server_default="false")
    zekerheid: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=None)
    bron: Mapped[str]
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VoorraadRegel(Base):
    """Eén feit op regelniveau: in (inkoopfactuur, extern document) of uit (verkoopfactuurregel),
    op DAGNIVEAU (`datum`), mét de normalisatie-uitkomst. Afgeleide, herrekenbare feitenlaag
    (upsert per (document, richting, regelvolgnummer); verwijderen = herrekenen, geen bron)."""

    __tablename__ = "voorraad_regel"
    __table_args__ = (
        UniqueConstraint("document_id", "richting", "regel_volgnummer", name="uq_voorraad_regel_document_regel"),
        Index("ix_voorraad_regel_administratie_datum", "administratie_id", "datum"),
        Index("ix_voorraad_regel_artikelgroep_id", "artikelgroep_id"),
        CheckConstraint("richting IN ('in', 'uit')", name="ck_voorraad_regel_richting"),
        CheckConstraint(
            "normalisatie_status IN ('genormaliseerd', 'onzeker', 'uitgesloten', 'niet_genormaliseerd')",
            name="ck_voorraad_regel_status",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    richting: Mapped[str]
    bron: Mapped[str]
    datum: Mapped[date]
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    relatie_naam: Mapped[str | None] = mapped_column(default=None)
    regel_volgnummer: Mapped[int]
    artikeltekst: Mapped[str]
    aantal: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    eenheid: Mapped[str | None] = mapped_column(default=None)
    prijs: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), default=None)
    netto_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    artikelgroep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"), default=None
    )
    normalisatie_status: Mapped[str]
    normalisatie_zekerheid: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=None)
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VoorraadTelling(Base):
    """Systeemstand fase 1: handmatige telling per artikelgroep per datum (later: Odoo-stand via de
    JSON-2-leesroute — zelfde tabelvorm, andere bron)."""

    __tablename__ = "voorraad_telling"
    __table_args__ = (
        UniqueConstraint("artikelgroep_id", "datum", name="uq_voorraad_telling_groep_datum"),
        Index("ix_voorraad_telling_administratie_id", "administratie_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    artikelgroep_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"))
    datum: Mapped[date]
    aantal: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    opmerking: Mapped[str | None] = mapped_column(default=None)
    ingevoerd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    ingevoerd_op: Mapped[datetime] = mapped_column(server_default=func.now())
