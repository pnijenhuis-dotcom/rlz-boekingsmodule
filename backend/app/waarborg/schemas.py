from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class WaarborgVoorstelResponse(BaseModel):
    document_id: uuid.UUID
    bericht_id: uuid.UUID
    verhuurder_entiteit: str
    contract_referentie: str
    huurder: str
    bedrag: Decimal
    richting: str
    datum: date
    balans_gb_code: str
    balans_ledger_id: uuid.UUID | None
    balans_gb_status: str
    tegenrekening_ledger_id: uuid.UUID | None
    status: str
    rlz_boekstuknummer: str | None


class WaarborgTegenrekeningInput(StrikteInvoer):
    """De énige muteerbare keuze — alle berichtvelden zijn brongegeven (§2d v1.11)."""

    tegenrekening_ledger_id: uuid.UUID | None = None


class WaarborgBoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    memoriaal_rlz_id: uuid.UUID
    rlz_boekstuknummer: str | None
