from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


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
    # Proportionele validatie (02-09): dít deel doorstond de paginabereik-toets niet — mens beslist.
    ongeldig_reden: str | None = None


class VerzamelbakItemDto(BaseModel):
    document_id: uuid.UUID
    bestandsnaam: str
    soort: str
    bron: str
    afzender_hint: str | None = None
    tenaamstelling: str | None = None
    suggestie_administratie_id: uuid.UUID | None = None
    suggestie_bron: str | None = None
    # Intake-reden (02-09): technisch + leesbaar label voor de rij — "geen tenaamstelling gelezen"
    # alleen nog als de AI werkelijk niets las (app/intake/redenen.py).
    reden: str | None = None
    reden_label: str | None = None
    aangemaakt_op: datetime
    splitsing_id: uuid.UUID | None = None
    splitsing_voorstel: list[SplitsSegmentDto] | None = None


class VerzamelbakLijstResponse(BaseModel):
    items: list[VerzamelbakItemDto]


class ToewijzenInput(StrikteInvoer):
    administratie_id: uuid.UUID


class HoortNietBijOnsInput(StrikteInvoer):
    reden: str


class SplitsDeelInputDto(StrikteInvoer):
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None = None


class SplitsingBevestigenInput(StrikteInvoer):
    delen: list[SplitsDeelInputDto]


class SplitsingAfwijzenInput(StrikteInvoer):
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
    # Avondrun 26-08 (optimistisch verzamelbak-paneel): de actie was al eerder gedaan — geen
    # fout, rustig melden; `melding` is leesbare tekst voor de gebruiker.
    al_verwerkt: bool = False
    melding: str | None = None
