from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class IntakeBijlageResultaatDto(BaseModel):
    bestandsnaam: str
    # 'toegewezen' | 'verzamelbak' | 'splitsingsvoorstel' | 'vgb_genegeerd' | 'niet_verwerkbaar'
    uitkomst: str
    document_id: uuid.UUID | None = None
    detail: str | None = None


class IntakeVerwerkResponse(BaseModel):
    bericht_id: uuid.UUID | None
    al_eerder_verwerkt: bool
    bijlagen: list[IntakeBijlageResultaatDto]


class SplitsSegmentDto(BaseModel):
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None = None
    leverancier: str | None = None
    factuurnummer: str | None = None
    zekerheid: float = 0.0


class VerzamelbakItemDto(BaseModel):
    document_id: uuid.UUID
    bestandsnaam: str
    soort: str
    bron: str
    afzender_hint: str | None = None
    tenaamstelling: str | None = None
    suggestie_administratie_id: uuid.UUID | None = None
    suggestie_bron: str | None = None
    aangemaakt_op: datetime
    splitsing_id: uuid.UUID | None = None
    splitsing_voorstel: list[SplitsSegmentDto] | None = None


class VerzamelbakLijstResponse(BaseModel):
    items: list[VerzamelbakItemDto]


class ToewijzenInput(BaseModel):
    administratie_id: uuid.UUID


class HoortNietBijOnsInput(BaseModel):
    reden: str


class SplitsDeelInputDto(BaseModel):
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None = None


class SplitsingBevestigenInput(BaseModel):
    delen: list[SplitsDeelInputDto]


class SplitsingAfwijzenInput(BaseModel):
    reden: str | None = None


class SplitsDeelResultaatDto(BaseModel):
    document_id: uuid.UUID
    bestandsnaam: str
    uitkomst: str
    administratie_id: uuid.UUID | None = None


class SplitsingBevestigenResponse(BaseModel):
    delen: list[SplitsDeelResultaatDto]


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: str
