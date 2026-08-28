from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.accordering.schemas import LaagInputDto
from app.schemas_basis import StrikteInvoer


class AfdelingenInstellingDto(StrikteInvoer):
    ingeschakeld: bool


class RouteLaagDto(BaseModel):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None = None
    bedrag_drempel: Decimal | None = None


class AfdelingDto(BaseModel):
    id: uuid.UUID
    naam: str
    is_terugval: bool
    actief: bool
    # Eigen route (lagen); leeg bij de terugval — die volgt de administratie-route.
    route: list[RouteLaagDto]
    staande_goedkeuringen: int
    gearchiveerd_op: datetime | None = None


class AfdelingenLijstDto(BaseModel):
    ingeschakeld: bool
    afdelingen: list[AfdelingDto]


class AfdelingAanmakenDto(StrikteInvoer):
    naam: str = Field(min_length=1, max_length=80)


class AfdelingRouteInput(StrikteInvoer):
    lagen: list[LaagInputDto]


class AfdelingRouteResponse(BaseModel):
    afdeling_id: uuid.UUID
    lagen: list[RouteLaagDto]
    rondes_vervallen: int = 0
