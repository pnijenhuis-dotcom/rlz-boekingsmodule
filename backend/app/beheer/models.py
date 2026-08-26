"""Beheer-modellen (schema boekhouding): de eerste-sync-run van de onboarding-wizard
(feedbackronde 26-08 punt 5, migratie 0076)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class AdministratieSyncRunStatus(enum.StrEnum):
    WACHTRIJ = "wachtrij"
    BEZIG = "bezig"
    KLAAR = "klaar"
    FOUT = "fout"


class AdministratieSyncRun(Base):
    """Eerste sync van een nieuw aangesloten administratie als achtergrondrun (bank-sync-run-
    patroon, 0071): status per onderdeel in `onderdelen` ({naam: {status, aangemaakt, bijgewerkt,
    fout}}) zodat de wizard live per collectie kan tonen wat lukte en wat niet. Een stille dood
    van het voertuig wordt via `laatst_actief_op` als zichtbare fout vertaald."""

    __tablename__ = "administratie_sync_run"
    __table_args__ = (
        Index("ix_administratie_sync_run_administratie_id", "administratie_id"),
        Index("ix_administratie_sync_run_administratie_status", "administratie_id", "status"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    status: Mapped[str] = mapped_column(default=AdministratieSyncRunStatus.WACHTRIJ.value)
    aangevraagd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangevraagd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestart_op: Mapped[datetime | None] = mapped_column(default=None)
    laatst_actief_op: Mapped[datetime | None] = mapped_column(default=None)
    beeindigd_op: Mapped[datetime | None] = mapped_column(default=None)
    onderdelen: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
    fout_reden: Mapped[str | None] = mapped_column(default=None)
