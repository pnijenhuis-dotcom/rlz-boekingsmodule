"""DTO's Inzicht › Open vragen kantoorbreed (`GET /vragen`, `GET /vragen/stand`) — alleen leesmodellen."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OpenVraagRijDto(BaseModel):
    vraag_id: uuid.UUID
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    vraag_tekst: str
    laatste_bericht: str | None
    laatste_bericht_door: str | None
    laatste_bericht_op: datetime | None
    gesteld_door_id: uuid.UUID
    gesteld_door_naam: str | None
    gesteld_op: datetime
    aan_de_beurt_id: uuid.UUID
    aan_de_beurt_naam: str | None
    aan_mij: bool
    wacht_dagen: int
    document_bestandsnaam: str
    document_status: str
    leverancier_naam: str | None
    referentie: str | None
    totaalbedrag: Decimal | None
    blokkeert_boeken: bool


class OpenVragenTellersDto(BaseModel):
    open: int
    aan_mij: int
    blokkeert_boeken: int
    administraties: int


class OpenVragenAdministratieFacetDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    aantal: int


class OpenVragenLijstDto(BaseModel):
    rijen: list[OpenVraagRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: OpenVragenTellersDto
    administraties: list[OpenVragenAdministratieFacetDto]
