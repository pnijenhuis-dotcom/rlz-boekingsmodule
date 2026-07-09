from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    mogelijk_duplicaat_van: uuid.UUID | None = None


class DocumentListItemResponse(BaseModel):
    id: uuid.UUID
    bestandsnaam: str
    status: str
    bron: str
    mogelijk_duplicaat_van: uuid.UUID | None = None
    toegewezen_aan: uuid.UUID | None = None
    aangemaakt_op: datetime
    laatst_gewijzigd_op: datetime


class DocumentListResponse(BaseModel):
    documenten: list[DocumentListItemResponse]


class DocumentGebeurtenisResponse(BaseModel):
    van_status: str | None
    naar_status: str
    actor_id: uuid.UUID
    detail: dict | None
    tijdstip: datetime


class DocumentDetailResponse(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID | None
    bestandsnaam: str
    status: str
    bron: str
    mogelijk_duplicaat_van: uuid.UUID | None = None
    toegewezen_aan: uuid.UUID | None = None
    aangemaakt_op: datetime
    laatst_gewijzigd_op: datetime
    veldvoorstel: dict | None = None
    tijdlijn: list[DocumentGebeurtenisResponse]


class BoekvoorstelRegelDto(BaseModel):
    ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    netto_bedrag: Decimal | None = None
    btw_bedrag: Decimal | None = None
    omschrijving: str | None = None


class BoekvoorstelResponse(BaseModel):
    document_id: uuid.UUID
    vendor_id: uuid.UUID | None = None
    referentie: str | None = None
    factuurdatum: date | None = None
    totaalbedrag: Decimal | None = None
    rlz_boekstuknummer: str | None = None
    opgeslagen: bool
    regels: list[BoekvoorstelRegelDto]


class BoekvoorstelInput(BaseModel):
    vendor_id: uuid.UUID | None = None
    referentie: str | None = None
    factuurdatum: date | None = None
    totaalbedrag: Decimal | None = None
    regels: list[BoekvoorstelRegelDto] = []


class CheckResultaatDto(BaseModel):
    naam: str
    ok: bool
    melding: str


class CheckRapportResponse(BaseModel):
    geblokkeerd: bool
    resultaten: list[CheckResultaatDto]


class BoekvoorstelMetChecksResponse(BaseModel):
    boekvoorstel: BoekvoorstelResponse
    checks: CheckRapportResponse


class BoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    rlz_document_id: uuid.UUID
    rlz_boekstuknummer: str | None = None
