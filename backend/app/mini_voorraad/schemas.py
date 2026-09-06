"""DTO's mini-voorraad (CONTRACT_F — spiegel in frontend/src/materiaal/miniVoorraadApi.ts). Aantallen en
standen reizen als STRING (Decimal, max 3 decimalen) — nooit floats over de lijn."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class ProductDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier_naam: str | None = None
    artikelcode: str | None = None
    omschrijving: str
    weergavenaam: str | None = None
    eenheid: str | None = None
    nieuw_controleren: bool
    gearchiveerd: bool
    stand: str
    laatste_mutatie_op: str | None = None
    aangemaakt_op: str


class ProductLijstDto(BaseModel):
    items: list[ProductDto]
    totaal: int
    pagina: int
    per_pagina: int = 25
    nieuw_controleren: int
    ingeschakeld: bool


class MutatieDto(BaseModel):
    id: uuid.UUID
    soort: str
    aantal: str
    datum: str
    document_id: str | None = None
    document_referentie: str | None = None
    document_leverancier: str | None = None
    boek_cyclus: int | None = None
    project_id: str | None = None
    project_naam: str | None = None
    gemeld_door_naam: str | None = None
    toelichting: str | None = None
    aangemaakt_op: str


class LogLijstDto(BaseModel):
    items: list[MutatieDto]
    totaal: int
    pagina: int
    per_pagina: int = 25


class StandDto(BaseModel):
    ingeschakeld: bool
    producten: int
    nieuw_controleren: int


class NaamBevestigenRequest(StrikteInvoer):
    weergavenaam: str = Field(min_length=1, max_length=200)


class ArchiverenRequest(StrikteInvoer):
    reden: str = Field(min_length=5, max_length=500)


class BeschadigingRequest(StrikteInvoer):
    product_id: uuid.UUID
    aantal: str = Field(min_length=1, max_length=20)
    project_id: uuid.UUID
    datum: date
    toelichting: str | None = Field(default=None, max_length=1000)


class MateriaallijstItemDto(BaseModel):
    """F5: read-only regel voor de materiaallijst van planning/transport — mini-producten mét stand > 0."""

    id: uuid.UUID
    naam: str
    eenheid: str | None = None
    mini_voorraad_stand: str
    leverancier_naam: str | None = None
    artikelcode: str | None = None


class MateriaallijstDto(BaseModel):
    categorie: str = "Speciale producten (mini-voorraad)"
    items: list[MateriaallijstItemDto]
