"""DTO's Autoboek-kandidaten (Instellingen › Autoboeken, Beheerder-only)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class KandidaatRijDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    reeks_ongewijzigd: int
    correcties: int
    open_vragen: int
    kwalificeert: bool
    actief: bool
    actief_sinds: datetime | None
    redenen: list[str]
    chips: list[str]
    heroverweeg_signalen: list[str]
    laatste_factuur_datum: date | None
    laatste_factuur_bedrag: Decimal | None
    laatste_document_id: uuid.UUID | None
    snooze_reden: str | None
    snooze_op: datetime | None
    berekend_op: datetime


class TellersDto(BaseModel):
    kandidaten: int
    actief: int
    heroverwegen: int
    verborgen: int
    administraties_met_kandidaten: int
    drempel: int
    laatste_run_op: datetime | None


class LijstDto(BaseModel):
    rijen: list[KandidaatRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: TellersDto


class SleutelDto(StrikteInvoer):
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID


class BulkAanzettenDto(StrikteInvoer):
    items: list[SleutelDto] = Field(min_length=1, max_length=200)


class AanzetUitkomstDto(BaseModel):
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str
    reden: str | None


class BulkAanzettenResultaatDto(BaseModel):
    uitkomsten: list[AanzetUitkomstDto]
    aangezet: int
    overgeslagen: int


class VerbergenDto(StrikteInvoer):
    reden: str = Field(min_length=1, max_length=500)


class DrempelDto(StrikteInvoer):
    drempel_op_rij: int = Field(ge=1, le=50)


class InstellingDto(BaseModel):
    drempel_op_rij: int
    laatste_run_op: datetime | None


class HerberekenResultaatDto(BaseModel):
    administraties: int
    fouten: int
    tellers: TellersDto
