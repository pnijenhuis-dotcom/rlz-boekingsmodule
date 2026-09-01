from __future__ import annotations

import uuid
from typing import Literal
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


class KandidaatDoelDto(BaseModel):
    id: uuid.UUID
    naam: str


class ProvisieVoorstelDto(BaseModel):
    """Vooringevulde provisie-GB (mockup doorbelasting-doel-toevoegen ③): de meest voorkomende
    REKENINGCODE van de bestaande rijen — de dialoog zoekt de code op in het doel-schema."""

    code: str
    naam: str


class KandidaatDoelenResponse(BaseModel):
    kandidaten: list[KandidaatDoelDto]
    provisie_voorstel: ProvisieVoorstelDto | None


class DebiteurLookupRequest(StrikteInvoer):
    zoeknaam: str


class DebiteurMatchDto(BaseModel):
    customer_guid: uuid.UUID
    naam: str
    exact: bool
    # Kaartgegevens ter expliciete bevestiging (les Mantelzorgwoningen 01-09): label → waarde.
    kaart: dict[str, str]


class DebiteurLookupResponse(BaseModel):
    matches: list[DebiteurMatchDto]


class MappingAanmaakRequest(StrikteInvoer):
    """"+ Doelentiteit toevoegen" (akkoord Peter 01-09): `doel_customer_guid` gevuld = de door
    de mens bevestigde bestaande debiteur uit de lookup; None = idempotente aanmaak bij opslaan."""

    doel_administratie_id: uuid.UUID
    doelentiteit_naam: str
    doel_customer_guid: uuid.UUID | None = None
    provisie_kosten_ledger_id: uuid.UUID | None = None
    intercompany: bool = True


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
    # Doorbelasting × projecten (25-08, deel 2 punt 2): projecten in de DOEL-administratie; bij
    # meer dan één is `verdeelbasis` ('m2' | 'gelijk') verplicht — de server splitst en rekent.
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    verdeelbasis: Literal["m2", "gelijk"] | None = None


class VerdelingRequest(StrikteInvoer):
    regels: list[VerdeelRegelRequest]


class VerdeelRegelResponse(BaseModel):
    id: uuid.UUID
    bron_regel_id: uuid.UUID
    mapping_id: uuid.UUID
    percentage: Decimal
    netto_deel: Decimal
    doel_kosten_ledger_id: uuid.UUID | None
    project_id: uuid.UUID | None = None
    project_naam: str | None = None
    project_aandeel: Decimal | None = None
    verdeelbasis: str | None = None
    m2: Decimal | None = None


class ProjectPreviewResponse(BaseModel):
    project_id: uuid.UUID
    naam: str
    netto_totaal: Decimal


class DoelentiteitPreviewResponse(BaseModel):
    mapping_id: uuid.UUID
    doelentiteit_naam: str
    onboarded: bool
    netto_totaal: Decimal
    provisie_bedrag: Decimal
    btw_bedrag: Decimal
    boeking_status: str | None
    boeking_id: uuid.UUID | None
    projecten: list[ProjectPreviewResponse] = Field(default_factory=list)
    # Rechtsgeldige factuur-PDF (blok A 26-08): 'aanwezig' (downloadbaar via
    # /doorbelasting/{aid}/boekingen/{boeking_id}/factuur) | 'ontbreekt' (mét reden) | None.
    factuur_pdf_status: str | None = None
    factuur_pdf_reden: str | None = None
    factuur_pdf_bestandsnaam: str | None = None


class VerdeelsleutelKortResponse(BaseModel):
    id: uuid.UUID
    naam: str
    versie: int
    toegepast_op: datetime | None


class RunResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    laatste_fout: dict | None
    regels: list[VerdeelRegelResponse]
    previews: list[DoelentiteitPreviewResponse]
    checks: CheckRapportResponse
    # Verdeelsleutel-herleidbaarheid (25-08, punt 2c): welke sleutel(versie) is toegepast.
    verdeelsleutel: VerdeelsleutelKortResponse | None = None


class DoelProjectResponse(BaseModel):
    """Project van een doel-administratie voor de verdeel-UI (25-08, punt 2a/b)."""

    id: uuid.UUID
    naam: str
    is_actief: bool
    contract_m2: Decimal | None


class DoelProjectenResponse(BaseModel):
    doel_administratie_id: uuid.UUID | None
    project_verplicht: bool
    projecten: list[DoelProjectResponse]


class VerdeelsleutelDoelInput(StrikteInvoer):
    mapping_id: uuid.UUID
    percentage: Decimal = Field(gt=0, le=100)
    doel_kosten_ledger_id: uuid.UUID | None = None
    # lijst van project-id's, óf de string "alle_actief" (gematerialiseerd bij toepassen)
    projecten: list[uuid.UUID] | Literal["alle_actief"] = Field(default_factory=list)
    verdeelbasis: Literal["m2", "gelijk"] | None = None


class VerdeelsleutelInput(StrikteInvoer):
    naam: str = Field(min_length=1, max_length=80)
    doelen: list[VerdeelsleutelDoelInput] = Field(min_length=1)


class VerdeelsleutelResponse(BaseModel):
    id: uuid.UUID
    naam: str
    versie: int
    actief: bool
    definitie: dict
    aangemaakt_op: datetime


class BoekResultaatResponse(BaseModel):
    """Status per doelentiteit (mapping-id → geboekt/spiegel_open/half_geboekt/mislukt)."""

    per_doelentiteit: dict[str, str]


class OpruimKandidaatResponse(BaseModel):
    """Achtergebleven RLZ-concept van een gestorneerde/vervallen doorbelasting (hygiëne-run
    2026-08-16) — informatief: opruimen is klikwerk van een mens in de RLZ-UI, de app
    verwijdert nooit (kernprincipe 3)."""

    concept_administratie_id: uuid.UUID
    kant: str  # 'verkoop_bron' | 'spiegel_doel'
    rlz_id: uuid.UUID
    document_id: uuid.UUID
    referentie: str | None
    reden: str  # 'gestorneerd' | 'vervallen_run'
    detail: str


class OpruimlijstResponse(BaseModel):
    kandidaten: list[OpruimKandidaatResponse]
    fouten: list[str]


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
