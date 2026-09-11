"""Tellers-cache van de werkvoorraad-klantenlijst (blok 6 run 11-09 middag; migratie 0136).

Eén rij per (administratie, teller). De cache is een CACHE: de waarheid blijft de telling over de brontabellen
(`tellers.tel_direct`). Bijgewerkt (a) incrementeel bij élke statusovergang van een document, (b) nachtelijk volledig
herrekend in `sync-alles`, (c) fail-safe bij ontbreken tijdens het lezen. Reconciliatie meldt afwijkingen cache ↔
telling als LET-OP (`werkvoorraad_tellers`)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class WerkvoorraadTellerCache(Base):
    __tablename__ = "werkvoorraad_teller_cache"
    __table_args__ = (
        CheckConstraint("waarde >= 0", name="ck_werkvoorraad_teller_cache_waarde"),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id", ondelete="CASCADE"), primary_key=True
    )
    teller: Mapped[str] = mapped_column(primary_key=True)
    waarde: Mapped[int] = mapped_column(server_default="0")
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now())
