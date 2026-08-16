from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.documenten.schemas import CheckRapportResponse
from app.schemas_basis import StrikteInvoer


class MappingResponse(BaseModel):
    id: uuid.UUID
    doelentiteit_naam: str
    doel_customer_guid: uuid.UUID
    doel_administratie_id: uuid.UUID | None
    intercompany: bool
    provisie_kosten_ledger_id: uuid.UUID | None
    laatste_kosten_ledger_id: uuid.UUID | None
    actief: bool


class MappingWijzigRequest(StrikteInvoer):
    """Gerichte mapping-mutatie; niet-meegegeven velden blijven ongewijzigd (exclude_unset
    in de router — het verschil tussen 'null zetten' en 'niet wijzigen' moet betrouwbaar zijn)."""

    doel_administratie_id: uuid.UUID | None = None
    intercompany: bool | None = None
    provisie_kosten_ledger_id: uuid.UUID | None = None
    actief: bool | None = None


class InstellingResponse(BaseModel):
    administratie_id: uuid.UUID
    provisie_percentage: Decimal
    btw_taxrate_id: uuid.UUID | None
    omzet_ledger_id: uuid.UUID | None
    provisie_omzet_ledger_id: uuid.UUID | None


class InstellingRequest(StrikteInvoer):
    provisie_percentage: Decimal = Field(ge=0, le=100)
    btw_taxrate_id: uuid.UUID | None = None
    omzet_ledger_id: uuid.UUID | None = None
    provisie_omzet_ledger_id: uuid.UUID | None = None


class VerdeelRegelRequest(StrikteInvoer):
    bron_regel_id: uuid.UUID
    mapping_id: uuid.UUID
    percentage: Decimal = Field(gt=0, le=100)
    doel_kosten_ledger_id: uuid.UUID | None = None


class VerdelingRequest(StrikteInvoer):
    regels: list[VerdeelRegelRequest]


class VerdeelRegelResponse(BaseModel):
    id: uuid.UUID
    bron_regel_id: uuid.UUID
    mapping_id: uuid.UUID
    percentage: Decimal
    netto_deel: Decimal
    doel_kosten_ledger_id: uuid.UUID | None


class DoelentiteitPreviewResponse(BaseModel):
    mapping_id: uuid.UUID
    doelentiteit_naam: str
    onboarded: bool
    netto_totaal: Decimal
    provisie_bedrag: Decimal
    btw_bedrag: Decimal
    boeking_status: str | None
    boeking_id: uuid.UUID | None


class RunResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    laatste_fout: dict | None
    regels: list[VerdeelRegelResponse]
    previews: list[DoelentiteitPreviewResponse]
    checks: CheckRapportResponse


class BoekResultaatResponse(BaseModel):
    """Status per doelentiteit (mapping-id → geboekt/spiegel_open/half_geboekt/mislukt)."""

    per_doelentiteit: dict[str, str]


class SpiegelTaakResponse(BaseModel):
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    mapping_id: uuid.UUID
    doelentiteit_naam: str
    netto_totaal: Decimal
    provisie_bedrag: Decimal
    verkoop_referentie: str | None
    aangemaakt_op: datetime


class StornoRequest(StrikteInvoer):
    reden: str = Field(min_length=5)


class SpiegelDoelGbsRequest(StrikteInvoer):
    """GB-toewijzing voor een open spiegel-taak: alleen GB's, nooit bedragen/percentages."""

    regel_gbs: dict[uuid.UUID, uuid.UUID]
    provisie_kosten_ledger_id: uuid.UUID | None = None


class KantToetsDto(BaseModel):
    """Eén kant van de storno-aangifte-toets (bron-verkoop of doel-spiegel) — per kant
    zichtbaar waarom een storno geblokkeerd is (opdracht 2026-08-16)."""

    kant: str
    toegestaan: bool
    reden: str | None


class BoekingStornoToetsDto(BaseModel):
    toegestaan: bool
    melding: str | None  # de vaste blokkade-melding zodra één kant blokkeert
    kanten: list[KantToetsDto]


class StornoToetsResponse(BaseModel):
    """Per niet-gestorneerde boeking van het document: mag de storno-knop aan?"""

    per_boeking: dict[uuid.UUID, BoekingStornoToetsDto]
