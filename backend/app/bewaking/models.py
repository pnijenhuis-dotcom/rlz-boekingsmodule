"""Synthetische bewaking (best-practice-besluit 1, 31-08 — aanleiding: twee stille
productie-incidenten dit weekend: de AI-extractie ruim een dag plat op de schema-limiet en
een leeg Anthropic-tegoed, beide toevallig ontdekt).

Twee tabellen, platform-breed (systeem-infrastructuur, niet administratie-gebonden — geen RLS,
conform migratie 0003/0040-categorie):
- `bewaking_probe_run`: één rij per kwartierrun mét de uitkomst per probesoort (de "eigen
  statusrij" uit de opdracht; nooit RLZ-writes).
- `bewaking_storing`: de open/gesloten storing per probesoort — draagt de alert-idempotentie
  (kolom-is-None-patroon, zelfde mechaniek als ai_kosten_maandstatus): alert pas bij de 2e
  opeenvolgende fout, herstelmelding éénmalig zodra de probe weer groen is."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class BewakingProbeRun(Base):
    __tablename__ = "bewaking_probe_run"
    __table_args__ = (
        Index("ix_bewaking_probe_run_gestart_op", "gestart_op"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gestart_op: Mapped[datetime] = mapped_column(server_default=func.now())
    beeindigd_op: Mapped[datetime | None] = mapped_column(default=None)
    # True als deze run de uur-probes (echte AI-call + extractie-foutratio) meenam — het
    # kwartierritme slaat ze over zolang de vorige AI-run jonger is dan het uurvenster.
    met_ai: Mapped[bool] = mapped_column(default=False)
    # {soort: {"status": "ok"|"fout"|"overgeslagen", "detail": str|None, "duur_ms": int}}
    uitkomsten: Mapped[dict] = mapped_column(JSONB)
    alles_ok: Mapped[bool] = mapped_column(default=True)


class BewakingStoring(Base):
    __tablename__ = "bewaking_storing"
    __table_args__ = (
        # Hooguit één OPEN storing per probesoort (partial unique — zie migratie 0092).
        Index(
            "uq_bewaking_storing_open_soort",
            "soort",
            unique=True,
            postgresql_where=text("hersteld_op IS NULL"),
        ),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    soort: Mapped[str]
    begonnen_op: Mapped[datetime] = mapped_column(server_default=func.now())
    opeenvolgende_fouten: Mapped[int] = mapped_column(default=1)
    laatste_fout_op: Mapped[datetime | None] = mapped_column(default=None)
    laatste_detail: Mapped[str | None] = mapped_column(default=None)
    # Kolom-is-None = nog niet gemeld (idempotentie, aikosten-patroon): de alert gaat pas bij
    # de 2e opeenvolgende fout (geen ruis bij één hik) en daarna nooit opnieuw voor dezelfde
    # storing; de herstelmelding alleen als er ook echt een alert uit is gegaan.
    alert_verzonden_op: Mapped[datetime | None] = mapped_column(default=None)
    hersteld_op: Mapped[datetime | None] = mapped_column(default=None)
    herstel_gemeld_op: Mapped[datetime | None] = mapped_column(default=None)
