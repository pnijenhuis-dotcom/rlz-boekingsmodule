from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.documenten.schemas import CheckRapportResponse


class OmzetRegelDto(BaseModel):
    categorie: str
    categorie_sleutel: str | None = None
    omzet_bedrag: Decimal | None = None
    kostprijs_bedrag: Decimal | None = None
    omzet_ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    kostprijs_ledger_id: uuid.UUID | None = None
    # 'mapping' (onthouden per administratie) | 'nieuw' (blokkerend tot ingesteld) | 'opgeslagen'.
    herkomst: str = "nieuw"


class OmzetVoorstelResponse(BaseModel):
    document_id: uuid.UUID
    periode_start: date | None = None
    periode_eind: date | None = None
    rapport_totaal_omzet: Decimal | None = None
    rapport_totaal_kostprijs: Decimal | None = None
    # In code berekend (nooit AI): omzet / kostprijs × 100, 1 decimaal.
    marge_pct: Decimal | None = None
    regels: list[OmzetRegelDto]
    voorraad_ledger_id: uuid.UUID | None = None
    kasomzet_naam: str | None = None
    opgeslagen: bool
    rapport_titel: str | None = None
    entiteit_naam: str | None = None


class OmzetVoorstelMetChecksResponse(BaseModel):
    voorstel: OmzetVoorstelResponse
    checks: CheckRapportResponse


class OmzetRegelInputDto(BaseModel):
    categorie: str
    omzet_bedrag: Decimal | None = None
    kostprijs_bedrag: Decimal | None = None
    omzet_ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    kostprijs_ledger_id: uuid.UUID | None = None


class OmzetVoorstelInput(BaseModel):
    periode_start: date | None = None
    periode_eind: date | None = None
    rapport_totaal_omzet: Decimal | None = None
    rapport_totaal_kostprijs: Decimal | None = None
    regels: list[OmzetRegelInputDto]
    voorraad_ledger_id: uuid.UUID | None = None
    # Mockup: "mapping onthouden per administratie" — default aan; uitzetten bewaart alleen dit
    # voorstel zonder de mapping voor volgende rapporten te wijzigen.
    mapping_onthouden: bool = True


class OmzetBoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    verkoop_rlz_id: uuid.UUID
    verkoop_referentie: str | None = None
    verkoop_boekstuknummer: str | None = None
    memoriaal_rlz_id: uuid.UUID | None = None
    memoriaal_boekstuknummer: str | None = None


class OmzetMappingDto(BaseModel):
    categorie_sleutel: str
    weergave_naam: str
    omzet_ledger_id: uuid.UUID
    taxrate_id: uuid.UUID
    kostprijs_ledger_id: uuid.UUID | None = None


class OmzetMappingLijstResponse(BaseModel):
    mappingen: list[OmzetMappingDto]
