"""DTO's crediteuren-dubbelen v2 (Inzicht › Crediteuren, kantoorbreed — design-ronde 03-09)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

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


class KlaargezetDto(BaseModel):
    werklijst_id: uuid.UUID
    voorkeur_vendor_id: uuid.UUID
    namen: list[str]
    aangemaakt_op: datetime


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
    klaargezet: KlaargezetDto | None


class TellersDto(BaseModel):
    clusters: int
    klaargezet: int
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


class OpenPostDto(BaseModel):
    rlz_document_id: str
    referentie: str | None
    datum: str | None
    open_bedrag: Decimal


class ClusterDetailDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    crediteuren: list[KaartDto]
    voorkeur_suggestie: uuid.UUID
    open_posten: dict[str, list[OpenPostDto]]
    toets_ok: bool
    toets_fout: str | None


class ArchiveerInvoer(StrikteInvoer):
    voorkeur_vendor_id: uuid.UUID
    overige_vendor_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class ArchiveerUitkomstDto(BaseModel):
    werklijst_id: uuid.UUID
    voorkeur_naam: str | None
    te_archiveren_namen: list[str]
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    al_klaargezet: bool
    melding: str


class AfmeldenInvoer(StrikteInvoer):
    vendor_ids: list[uuid.UUID] = Field(min_length=2, max_length=50)
    reden: str = Field(min_length=1, max_length=500)


class AfmeldenUitkomstDto(BaseModel):
    afmelding_id: uuid.UUID


class WerklijstRegelDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    voorkeur_vendor_id: uuid.UUID
    voorkeur_naam: str | None
    te_archiveren: list[dict]
    status: str
    aangemaakt_op: datetime
    gedaan_op: datetime | None
    gedaan_bron: str | None
    laatste_hertoets_op: datetime | None
    hertoets_detail: dict | None


class WerklijstDto(BaseModel):
    regels: list[WerklijstRegelDto]
    open: int
    gedaan: int
