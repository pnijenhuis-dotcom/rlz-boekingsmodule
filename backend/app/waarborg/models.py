from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class WaarborgStatus(enum.StrEnum):
    OPEN = "open"
    GEBOEKT = "geboekt"


class WaarborgBericht(Base):
    """Eén VASTLY-WAARBORG-bericht per document (§2d-waarborgroute DEFINITIEF v1.11, migratie
    0039): de contractvelden zoals uit het bericht gelezen — brongegeven, niet muteerbaar door
    de controleur — plus de éne menselijke keuze (de tegenrekening van het saldo-0-memoriaal;
    de balansrekening zelf komt als `balans_gb_code` uit het bericht) en de RLZ-registratie na
    het boeken. `bericht_id` is de idempotentiesleutel (UUIDv5 door vastgoed gegenereerd,
    DB-uniek): een tweede aflevering van hetzelfde bericht wordt in de intake herkend en maakt
    nooit een tweede document/boeking."""

    __tablename__ = "waarborg_bericht"
    __table_args__ = {"schema": "boekhouding"}

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    bericht_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    schema_versie: Mapped[str | None] = mapped_column(default=None)
    verhuurder_entiteit: Mapped[str] = mapped_column()
    rlz_admin_id_hint: Mapped[str | None] = mapped_column(default=None)
    contract_referentie: Mapped[str] = mapped_column()
    huurder: Mapped[str] = mapped_column()
    bedrag: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    richting: Mapped[str] = mapped_column()
    datum: Mapped[date] = mapped_column()
    balans_gb_code: Mapped[str] = mapped_column()
    # De éne keuze van de controleur: waartegen het memoriaal sluit (saldo 0). Bewust géén
    # brongegeven — het bericht draagt alleen de waarborg-balansrekening.
    tegenrekening_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    status: Mapped[str] = mapped_column(default=WaarborgStatus.OPEN.value)
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    geboekt_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    geboekt_op: Mapped[datetime | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
