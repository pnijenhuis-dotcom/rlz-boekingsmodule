from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class RegistersyncLevering(Base):
    """Eén geleverde registersnapshot aan Vastly (koppelcontract §8 v1.18; migratie 0081).
    Twee functies in één append-only rij: (1) `nonce` is DB-uniek = de replay-verdediging bovenop
    het timestamp-venster — over álle Cloud Run-instanties heen (een in-process set zou per
    instantie gelden); (2) leveringslog: wanneer, hoeveel rijen per registerdeel en hoe lang de
    opbouw duurde — "niets verdwijnt stil" geldt ook voor wat we uitleveren. Geen
    administratie-scope: een levering omvat per definitie álle administraties, daarom geen RLS
    op administratie (platformbrede tabel, patroon ai_gebruik/0047)."""

    __tablename__ = "registersync_levering"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nonce: Mapped[str] = mapped_column(unique=True)
    ontvangen_op: Mapped[datetime] = mapped_column(server_default=func.now())
    generated_at: Mapped[datetime] = mapped_column()
    aantal_administraties: Mapped[int] = mapped_column(Integer)
    aantal_grootboekrekeningen: Mapped[int] = mapped_column(Integer)
    duur_ms: Mapped[int] = mapped_column(Integer)
