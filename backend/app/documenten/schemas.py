from __future__ import annotations

import uuid
from datetime import datetime

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
