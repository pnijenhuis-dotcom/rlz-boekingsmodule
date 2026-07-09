from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel


class SyncTellingResponse(BaseModel):
    aangemaakt: int
    bijgewerkt: int
    verdwenen: int


class GrootboekOptieResponse(BaseModel):
    ledger_id: uuid.UUID
    code: str
    naam: str
    soort: int


class GrootboekLijstResponse(BaseModel):
    rekeningen: list[GrootboekOptieResponse]


class TaxrateOptieResponse(BaseModel):
    id: uuid.UUID
    naam: str | None
    percentage: Decimal | None


class TaxrateLijstResponse(BaseModel):
    btw_codes: list[TaxrateOptieResponse]


class VendorOptieResponse(BaseModel):
    id: uuid.UUID
    naam: str | None


class VendorLijstResponse(BaseModel):
    crediteuren: list[VendorOptieResponse]


class ProjectOptieResponse(BaseModel):
    id: uuid.UUID
    naam: str | None


class ProjectLijstResponse(BaseModel):
    projecten: list[ProjectOptieResponse]
