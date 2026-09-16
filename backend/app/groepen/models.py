"""Cache-tabel voor de groepssaldi (migratie 0149) — één rij per administratie per dag, gevuld door de nachtelijke
stap."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

STATUSSEN = ("ok", "geen_rekening", "ongeldig", "fout", "overgeslagen")


class GroepSaldoStand(Base):
    __tablename__ = "groep_saldo_stand"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'geen_rekening', 'ongeldig', 'fout', 'overgeslagen')", name="ck_groep_saldo_stand_status"
        ),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    datum: Mapped[date] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column()
    detail: Mapped[str | None] = mapped_column(default=None)
    debiteuren: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    crediteuren: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    ic_debiteuren: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    ic_crediteuren: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    debiteuren_rekening: Mapped[str | None] = mapped_column(default=None)
    crediteuren_rekening: Mapped[str | None] = mapped_column(default=None)
    gemeten_op: Mapped[datetime] = mapped_column(server_default=func.now())
