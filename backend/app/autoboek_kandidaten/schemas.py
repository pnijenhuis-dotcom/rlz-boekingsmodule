"""DTO's Autoboek-kandidaten (Instellingen › Autoboeken, Beheerder-only)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

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


class BulkSelectieDto(StrikteInvoer):
    """Bulk-selectie (B5.2, design-ronde 03-09): óf expliciete `items` (huidige pagina), óf `alle: true`
    mét dezelfde filters als de lijst (`tab`/`q`/`verborgen`) — de server herleidt dan de rijen
    ZONDER paginering ("Selecteer alle N resultaten") i.p.v. duizenden id's te posten."""

    items: list[SleutelDto] | None = Field(default=None, max_length=200)
    alle: bool = False
    tab: str = "kandidaten"
    q: str = Field(default="", max_length=200)
    verborgen: bool = False

    @model_validator(mode="after")
    def _precies_een_vorm(self) -> BulkSelectieDto:
        if self.alle and self.items:
            raise ValueError("Geef óf items óf alle=true, niet beide")
        if not self.alle and not self.items:
            raise ValueError("Geef minstens één item of alle=true")
        return self


class BulkAanzettenDto(BulkSelectieDto):
    pass


class BulkVerbergenDto(BulkSelectieDto):
    reden: str = Field(min_length=1, max_length=500)

    @field_validator("reden")
    @classmethod
    def _reden_niet_leeg(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Een reden is verplicht bij het verbergen van een kandidaat")
        return v.strip()


class AanzetUitkomstDto(BaseModel):
    """Uitkomst per rij (aanzetten: aangezet | overgeslagen | fout; verbergen: verborgen | overgeslagen | fout).
    Namen additief (03-09) zodat het scherm ook rijen buiten de huidige pagina kan benoemen."""

    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str
    reden: str | None
    leverancier_naam: str | None = None
    administratie_naam: str | None = None


class BulkAanzettenResultaatDto(BaseModel):
    uitkomsten: list[AanzetUitkomstDto]
    aangezet: int
    overgeslagen: int


class BulkVerbergenResultaatDto(BaseModel):
    uitkomsten: list[AanzetUitkomstDto]
    verborgen: int
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
