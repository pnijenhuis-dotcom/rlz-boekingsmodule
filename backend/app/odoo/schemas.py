from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class OdooGegevensDto(StrikteInvoer):
    """URL + API-key — alleen inkomend; de key komt nooit terug in een response."""

    odoo_url: str = Field(min_length=8)
    api_key: str = Field(min_length=8)
    api_gebruiker: str | None = None


class GevondenCompanyDto(BaseModel):
    company_id: int
    naam: str
    al_gekoppeld: bool


class OdooVerbindingTestDto(BaseModel):
    companies: list[GevondenCompanyDto]


class OdooKoppelenDto(OdooGegevensDto):
    company_ids: list[int] = Field(min_length=1)
    #: optionele eigen administratienaam per company-id (string-sleutels: JSON) — default de Odoo-companynaam
    namen: dict[str, str] = Field(default_factory=dict)


class GekoppeldeAdministratieDto(BaseModel):
    id: uuid.UUID
    naam: str
    company_id: int
    probe: dict[str, str]
    sync_run_id: uuid.UUID | None
    sync: dict[str, dict] = Field(default_factory=dict)


class OdooGekoppeldDto(BaseModel):
    administraties: list[GekoppeldeAdministratieDto]


class OdooWijzigDto(StrikteInvoer):
    """Odoo-gegevens wijzigen (sleutelrotatie): alles optioneel — leeg = ongewijzigd; zonder key = herprobe."""

    odoo_url: str | None = None
    api_key: str | None = None
    api_gebruiker: str | None = None


class OdooProbeDto(BaseModel):
    groen: bool
    rapport: dict[str, str]
    company_naam: str | None = None
    versie: str | None = None
    lock_dates: dict[str, str | None] = Field(default_factory=dict)


class OdooStandDto(BaseModel):
    company_id: int
    company_naam: str | None
    odoo_url: str
    api_gebruiker: str | None
    api_key_verloopt_op: str | None
    probe_groen: bool | None
    probe_op: datetime | None
    #: Blok D: alleen-lezen (Odoo = leesbron voor de voorraad-uitstroom; boeken blijft in RLZ) + voorraad-knip.
    alleen_lezen: bool = False
    voorraad_knip_datum: date | None = None


class OdooLeesbronKoppelenDto(OdooGegevensDto):
    """Blok D: een RLZ-administratie een ALLEEN-LEZEN Odoo-koppeling geven (company + optionele voorraad-knip)."""

    company_id: int = Field(gt=0)
    voorraad_knip_datum: date | None = None


class OdooLeesbronKnipDto(StrikteInvoer):
    voorraad_knip_datum: date | None = None


class OdooSyncResultaatDto(BaseModel):
    run_id: uuid.UUID
    onderdelen: dict[str, dict]


class OdooProductBrugDto(BaseModel):
    """Uitkomst van de materiaalcatalogus → product.product-brug per leverancier/administratie."""

    gevonden: int
    aangemaakt: int
    overgeslagen: list[str] = Field(default_factory=list)
