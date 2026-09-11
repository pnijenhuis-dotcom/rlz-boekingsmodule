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
    #: Blok 3 run 11-09 middag: RLZ weigert (403) een route die de rechten-probe net groen had — RLZ zet de rechten van
    #: een verse koppeling met vertraging door. De run wacht op de wekker (`volgende_poging_op`) en wordt herprobeerd.
    RECHTEN_ONDERWEG = "rechten_onderweg"


class AdministratieSyncRun(Base):
    """Eerste sync van een nieuw aangesloten administratie als achtergrondrun (bank-sync-run-
    patroon, 0071): status per onderdeel in `onderdelen` ({naam: {status, aangemaakt, bijgewerkt,
    fout}}) zodat de wizard live per collectie kan tonen wat lukte en wat niet. Een stille dood
    van het voertuig wordt via `laatst_actief_op` als zichtbare fout vertaald.

    Blok 3 run 11-09 middag (migratie 0133): status `rechten_onderweg` + `pogingen`/`volgende_poging_op` — een 403 op
    een route die de rechten-probe groen had wordt herprobeerd (5/15/60 min, daarna elk uur, max 24 u) door de wekker in
    de kwartier-job rlz-bewaking; pas daarna `fout` mét het letterlijke RLZ-antwoord."""

    __tablename__ = "administratie_sync_run"
    __table_args__ = (
        Index("ix_administratie_sync_run_administratie_id", "administratie_id"),
        Index("ix_administratie_sync_run_administratie_status", "administratie_id", "status"),
        Index("ix_administratie_sync_run_volgende_poging", "status", "volgende_poging_op"),
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
    # Blok 3 run 11-09 middag (migratie 0133): herproberen ná een 403 op een probe-groene route.
    pogingen: Mapped[int] = mapped_column(default=0, server_default="0")
    volgende_poging_op: Mapped[datetime | None] = mapped_column(default=None)
