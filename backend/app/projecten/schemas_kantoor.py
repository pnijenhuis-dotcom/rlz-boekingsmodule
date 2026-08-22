"""Pydantic-schema's kantoor-projectenmodule (mockup projecten-invoer.html, akkoord Peter
22-08). Bedragen/Decimals serialiseren als string (client rekent nooit zelf)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class ProjectLijstRijDto(BaseModel):
    project_id: uuid.UUID
    naam: str | None = None
    is_actief: bool
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    specs_status: str  # 'compleet' | 'onvolledig' | 'geen'
    documenten: dict[str, int]
    staffels: int
    gebouwd_m2: Decimal
    contract_m2: Decimal | None = None
    doorlopende_huur: bool
    heeft_activiteit: bool


class ProjectenLijstResponse(BaseModel):
    projecten: list[ProjectLijstRijDto]
    zonder_specs: int  # alleen projecten mét uren-/meerwerk-activiteit (mockup-keuze 5)


class SpecificatieDto(BaseModel):
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    looptijd_van: date | None = None
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    doorlopende_huur_omschrijving: str | None = None


class SpecificatieInput(StrikteInvoer):
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    looptijd_van: date | None = None
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    doorlopende_huur_omschrijving: str | None = None


class ProjectDocumentDto(BaseModel):
    id: uuid.UUID
    soort: str
    titel: str
    versie_omschrijving: str | None = None
    bestandsnaam: str
    aangemaakt_op: datetime
    ontleed: bool


class StaffelDto(BaseModel):
    id: uuid.UUID
    omschrijving: str
    eenheid: str
    prijs_per_eenheid: Decimal
    verrekenbaar: bool
    bron: str | None = None
    aangemaakt_op: datetime


class StaffelInput(StrikteInvoer):
    omschrijving: str
    eenheid: Literal["m2", "m1", "stuks", "manuren"]
    prijs_per_eenheid: Decimal
    verrekenbaar: bool = True
    bron: str | None = None


class WerknummerDto(BaseModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier_naam: str | None = None
    werknummer: str
    bron: str
    bevestigd: bool
    aangemaakt_op: datetime


class WerknummerInput(StrikteInvoer):
    vendor_id: uuid.UUID
    werknummer: str


class OntledingRegelDto(BaseModel):
    id: uuid.UUID
    project_document_id: uuid.UUID
    soort: str
    omschrijving: str
    citaat: str | None = None
    waarde: dict | None = None
    zekerheid: Decimal | None = None
    status: str


class OntledingBeslisInput(StrikteInvoer):
    bevestigen: bool
    # Alleen bij een staffel-regel: de mens kiest de eenheid uit de vaste vier (de AI-eenheid
    # is alleen het voorstel) + de verrekenbaarheid.
    eenheid: Literal["m2", "m1", "stuks", "manuren"] | None = None
    verrekenbaar: bool = True


class ProjectDetailResponse(BaseModel):
    project_id: uuid.UUID
    naam: str | None = None
    is_actief: bool
    specificatie: SpecificatieDto | None = None
    documenten: list[ProjectDocumentDto]
    staffels: list[StaffelDto]
    werknummers: list[WerknummerDto]
    ontleding: list[OntledingRegelDto]
    gebouwd_m2: Decimal


class NieuwProjectInput(StrikteInvoer):
    projectnummer: str
    plaats: str
    opdrachtgever: str
    startdatum: date | None = None


class NieuwProjectResponse(BaseModel):
    rlz_project_id: uuid.UUID
    projectnaam: str
    bestond_al: bool


class VolgendNummerResponse(BaseModel):
    projectnummer: str


class OntleedResponse(BaseModel):
    project_document_id: uuid.UUID
    aantal_regels: int


class CijfersSyncResponse(BaseModel):
    documenten: int
    regels: int
    verdwenen: int


# --- resultaat (analytische laag) ----------------------------------------------------------------


class ProjectWeekDto(BaseModel):
    jaar: int
    weeknummer: int
    baten: Decimal
    kosten_geboekt: Decimal
    kosten_onderweg: Decimal
    onderweg_onbepaalbaar_uren: Decimal
    saldo: Decimal
    cumulatief: Decimal
    baten_detail: list[str]
    kosten_detail: list[str]


class ProjectResultaatResponse(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    baten_geboekt: Decimal
    kosten_geboekt: Decimal
    uren_onderweg_bedrag: Decimal
    uren_onderweg_uren: Decimal
    onbepaalbaar_uren: Decimal
    meerwerk_onderweg_bedrag: Decimal
    onderweg_saldo: Decimal
    verwachte_marge: Decimal
    marge_pct: Decimal | None = None
    weken: list[ProjectWeekDto]


class OverzichtRijDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    baten: Decimal  # geboekt + meerwerk-onderweg
    kosten_incl_onderweg: Decimal
    marge: Decimal
    marge_pct: Decimal | None = None
    trend: str  # 'stijgend' | 'dalend' | 'stabiel'
    kosten_zonder_omzet_weken: int
    meerwerk_te_lang_niet_doorbelast: int
    doorlopende_huur: bool
    onbepaalbaar_uren: Decimal


class ProjectenOverzichtResponse(BaseModel):
    baten_totaal: Decimal
    kosten_totaal_incl_onderweg: Decimal
    uren_onderweg_totaal: Decimal
    onbepaalbaar_uren_totaal: Decimal
    meerwerk_onderweg_totaal: Decimal
    marge_totaal: Decimal
    marge_pct: Decimal | None = None
    aandacht: int
    rijen: list[OverzichtRijDto]
