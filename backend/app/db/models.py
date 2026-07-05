from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="platform")


class Administratie(Base):
    """RLZ-administratie (tenant-scope). Vastgoed- en kantoorklant-administraties gemengd."""

    __tablename__ = "administratie"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    naam: Mapped[str]
    rlz_admin_id: Mapped[str] = mapped_column(unique=True)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class Gebruiker(Base):
    """Platform-gebruiker. Bevat PII (naam, e-mail) — bewust gescheiden van financiële data,
    die uitsluitend in het `boekhouding`-schema leeft. AVG-verwijderverzoek = `gepseudonimiseerd_op`
    zetten (nooit hard verwijderen), pas na relatie-einde + 7 jaar fiscale bewaarplicht.
    """

    __tablename__ = "gebruiker"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    naam: Mapped[str]
    e_mail: Mapped[str] = mapped_column(unique=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gepseudonimiseerd_op: Mapped[datetime | None] = mapped_column(default=None)


class AuditEvent(Base):
    """Uniform, append-only audit-schema (koppelcontract v1.5, platformbrede afspraken) —
    bron voor de WORM-export. UPDATE/DELETE zijn niet gegrant aan de app-rol (zie migratie 0001).
    """

    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tijdstip: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    module: Mapped[str]
    tabel: Mapped[str]
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actie: Mapped[str]
    oude_waarde: Mapped[dict | None] = mapped_column(JSONB, default=None)
    nieuwe_waarde: Mapped[dict | None] = mapped_column(JSONB, default=None)
    correlatie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
