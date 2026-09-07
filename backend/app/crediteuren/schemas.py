"""DTO's crediteuren-dubbelen (Inzicht › Crediteuren, kantoorbreed — design-ronde 03-09; schaalbaar blok B13 07-09)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class KaartDto(BaseModel):
    vendor_id: uuid.UUID
    naam: str | None
    btw_nummer: str | None
    kvk_nummer: str | None
    ibans: list[str]
    aantal_boekingen: int
    laatst_geboekt: date | None


class SleutelDto(BaseModel):
    soort: str
    sleutel: str


class ClusterDto(BaseModel):
    cluster_id: str
    administratie_id: uuid.UUID
    administratie_naam: str
    soort: str
    sleutel: str
    sleutels: list[SleutelDto]
    chips: list[str]
    crediteuren: list[KaartDto]
    aantal_boekingen: int
    laatst_geboekt: date | None
    kvk_verschilt: bool
    afmelden_primair: bool
    voorkeur_suggestie: uuid.UUID
    eenduidig: bool
    classificatie_reden: str


class TellersDto(BaseModel):
    clusters: int  # twijfel — mens nodig
    eenduidig: int  # automatisch afhandelbaar
    administraties: int


class FacetAdministratieDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class FacettenDto(BaseModel):
    administraties: list[FacetAdministratieDto]
    sleutels: dict[str, int]


class LijstDto(BaseModel):
    rijen: list[ClusterDto]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: TellersDto
    facetten: FacettenDto


class ClusterDetailDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    crediteuren: list[KaartDto]
    voorkeur_suggestie: uuid.UUID
    eenduidig: bool
    classificatie_reden: str


class AfhandelenInvoer(StrikteInvoer):
    voorkeur_vendor_id: uuid.UUID
    verliezer_vendor_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class AfhandelUitkomstDto(BaseModel):
    afhandeling_id: uuid.UUID
    voorkeur_naam: str | None
    verliezer_namen: list[str]
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    boekvoorstellen_hervertaald: int
    melding: str


class AfmeldenInvoer(StrikteInvoer):
    vendor_ids: list[uuid.UUID] = Field(min_length=2, max_length=50)
    reden: str = Field(min_length=1, max_length=500)


class AfmeldenUitkomstDto(BaseModel):
    afmelding_id: uuid.UUID


class AutoAfhandelenInvoer(StrikteInvoer):
    dry_run: bool = True
    administratie_id: uuid.UUID | None = None


class VoorbeeldDto(BaseModel):
    cluster_id: str
    voorkeur_naam: str | None
    verliezer_namen: list[str]
    reden: str
    afgehandeld: bool
    fout: str | None


class AdministratieUitkomstDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    eenduidig: int
    twijfel: int
    afgehandeld: int
    fouten: int
    voorbeelden: list[VoorbeeldDto]


class AutoRunDto(BaseModel):
    run_id: uuid.UUID
    dry_run: bool
    eenduidig: int
    twijfel: int
    afgehandeld: int
    fouten: int
    administraties: list[AdministratieUitkomstDto]


class AfhandelingRegelDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    bron: str
    voorkeur_vendor_id: uuid.UUID
    voorkeur_naam: str | None
    verliezers: list[dict]
    sleutels: list[dict]
    classificatie_reden: str
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    boekvoorstellen_hervertaald: int
    afgehandeld_op: datetime
    teruggedraaid_op: datetime | None
    teruggedraaid_reden: str | None


class AfhandelingenDto(BaseModel):
    regels: list[AfhandelingRegelDto]
    actief: int
    teruggedraaid: int


class TerugdraaiInvoer(StrikteInvoer):
    reden: str = Field(min_length=1, max_length=500)
