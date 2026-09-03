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


# --- kantoorbreed (design-ronde 03-09 blok B1, mockup inzicht-kantoorbreed ①②③) -------------------


class KantoorRijDto(BaseModel):
    """Eén rij = één signaal (ontbreekt óf prijsstijging) met precies één handeling."""

    administratie_id: uuid.UUID
    administratie_naam: str
    vendor_id: uuid.UUID
    leverancier: str | None = None
    soort: str  # ontbreekt | prijsstijging
    status: str  # aandacht | gesnoozed | afgemeld
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
    dagen_te_laat: int | None = None
    prijsstijging_pct: Decimal | None = None
    snooze_tot: date | None = None
    afgemeld_op: datetime | None = None
    berekend_op: datetime


class KantoorTellersDto(BaseModel):
    ontbrekend: int
    prijsstijging: int
    administraties: int


class AdministratieFacetDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class KantoorFacettenDto(BaseModel):
    status: dict[str, int]
    administraties: list[AdministratieFacetDto]


class KantoorLijstDto(BaseModel):
    rijen: list[KantoorRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: KantoorTellersDto
    facetten: KantoorFacettenDto


class HerberekenRunDto(BaseModel):
    """202-antwoord + status-poll (bank_sync_run-patroon, platformbreed)."""

    run_id: uuid.UUID
    status: str  # wachtend | bezig | klaar | fout
    aangevraagd_op: datetime
    gestart_op: datetime | None = None
    klaar_op: datetime | None = None
    aantal_administraties: int
    aantal_verwerkt: int
    aantal_fouten: int
    foutreden: str | None = None
    resultaat: dict | None = None


class ConceptMailDto(BaseModel):
    ontvanger_e_mail: str | None = None
    leverancier: str | None = None
    administratie_naam: str
    onderwerp: str
    tekst: str


class ConceptMailVersturenDto(StrikteInvoer):
    naar: str = Field(min_length=3, max_length=320)
    onderwerp: str = Field(min_length=1, max_length=300)
    tekst: str = Field(min_length=1, max_length=20000)


class ConceptMailVerzondenDto(BaseModel):
    verzonden_aan: str
