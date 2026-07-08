from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

# Deze caches zijn NIET gedeeld met vastgoed (alleen platform.grootboekrekening is dat, zie
# app/db/models.py::Grootboekrekening) — puur intern aan de boekingsmodule, voor het eigen
# controlescherm (crediteurkeuze, btw-code, project-koppeling). `brondata` bewaart de volledige
# ruwe RLZ-respons per record: een aantal velden zijn wel bevestigd tegen Reeleezee's officiële
# API-documentatie (Vendor.Name/IsArchived, Project.Name/IsActive) en apart gemodelleerd, maar
# TaxRate's officiële resource-model-pagina gaf herhaaldelijk een serverfout — vandaar geen
# aparte kolom voor btw-percentage/omschrijving totdat dat wél geverifieerd is; brondata is het
# vangnet zodat niets verloren gaat.


class TaxRateCache(Base):
    __tablename__ = "taxrate_cache"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    naam: Mapped[str | None] = mapped_column(default=None)
    brondata: Mapped[dict] = mapped_column(JSONB)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class VendorCache(Base):
    __tablename__ = "vendor_cache"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    naam: Mapped[str | None] = mapped_column(default=None)
    is_gearchiveerd: Mapped[bool | None] = mapped_column(default=None)
    brondata: Mapped[dict] = mapped_column(JSONB)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class ProjectCache(Base):
    __tablename__ = "project_cache"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    naam: Mapped[str | None] = mapped_column(default=None)
    is_actief: Mapped[bool | None] = mapped_column(default=None)
    brondata: Mapped[dict] = mapped_column(JSONB)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)
