from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.documenten.schemas import CheckRapportResponse
from app.schemas_basis import StrikteInvoer


class VerkoopRegelDto(BaseModel):
    volgnummer: int
    omschrijving: str | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    gb_code: str | None
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    gb_code_status: str
    herkomst: str


class VerkoopVoorstelResponse(BaseModel):
    document_id: uuid.UUID
    debiteur_naam: str | None
    factuurnummer: str | None
    factuurdatum: date | None
    totaalbedrag_incl: Decimal | None
    is_creditnota: bool
    gecrediteerd_factuurnummer: str | None
    regels: list[VerkoopRegelDto]
    opgeslagen: bool
    rlz_boekstuknummer: str | None


class VerkoopRegelInputDto(StrikteInvoer):
    omschrijving: str | None = None
    netto_bedrag: Decimal | None = None
    btw_bedrag: Decimal | None = None
    gb_code: str | None = None
    ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None


class VerkoopVoorstelInput(StrikteInvoer):
    debiteur_naam: str | None = None
    factuurnummer: str | None = None
    factuurdatum: date | None = None
    totaalbedrag_incl: Decimal | None = None
    regels: list[VerkoopRegelInputDto]


class VerkoopVoorstelMetChecksResponse(BaseModel):
    voorstel: VerkoopVoorstelResponse
    checks: CheckRapportResponse


class VerkoopBoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    verkoop_rlz_id: uuid.UUID
    verkoop_referentie: str | None
    verkoop_boekstuknummer: str | None
