from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class TerugkerendSignaalDto(BaseModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier: str | None = None
    patroon: str
    interval_dagen: int
    aantal_facturen: int
    laatste_datum: date
    laatste_bedrag: Decimal | None = None
    laatste_document_id: uuid.UUID | None = None
    vorige_datum: date | None = None
    vorige_bedrag: Decimal | None = None
    verwacht_op: date
    uiterlijk_op: date
    ontbreekt_sinds: date | None = None
    dagen_te_laat: int | None = None
    prijsstijging_pct: Decimal | None = None
    snooze_tot: date | None = None
    afgemeld_op: datetime | None = None
    status: str
    berekend_op: datetime


class TerugkerendOverzichtDto(BaseModel):
    administratie_id: uuid.UUID
    prijsstijging_drempel_pct: Decimal
    signalen: list[TerugkerendSignaalDto]


class DocumentTerugkerendSignaalDto(BaseModel):
    """Prijsstijging-chip op het controlescherm (signaal, geen blokkade); `signaal` None = niets."""

    prijsstijging_pct: Decimal | None = None
    vorige_bedrag: Decimal | None = None
    vorige_datum: date | None = None
    laatste_bedrag: Decimal | None = None
    patroon: str | None = None
    leverancier: str | None = None


class SnoozeDto(StrikteInvoer):
    tot: date | None = None


class AfmeldenDto(StrikteInvoer):
    afgemeld: bool


class DrempelDto(StrikteInvoer):
    prijsstijging_pct: Decimal = Field(gt=0, le=1000)


class DrempelResultaatDto(BaseModel):
    prijsstijging_pct: Decimal


class HerberekenResultaatDto(BaseModel):
    terugkerend: int
    ontbreekt: int
    prijsstijging: int
    vervallen: int
