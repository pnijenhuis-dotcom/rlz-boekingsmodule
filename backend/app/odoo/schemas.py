from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

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


class OdooStamgegevensDto(BaseModel):
    """Actuele (niet-verdwenen) cache-rijen per onderdeel van déze administratie — het blok "Stamgegevens
    grootboek 212 · btw 14 · relaties 380" (mockup sectie 1)."""

    ledgers: int = 0
    taxrates: int = 0
    vendors: int = 0
    projects: int = 0


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
    #: Blok E (UI): probe-rapport per onderdeel, stamgegevens-tellers, jongste sync-tijd (zelfde bron als de
    #: lijst), overgangsdatum + oud RLZ-id bij een overgestapte administratie.
    probe_rapport: dict[str, str] | None = None
    stamgegevens: OdooStamgegevensDto | None = None
    laatste_sync_op: datetime | None = None
    overgangsdatum: date | None = None
    rlz_admin_id_voor_overstap: str | None = None


# --- blok A Odoo-afrondingsrun 04-09: rekening-mapping RLZ → Odoo bij een overstap (migratie 0111) ---------


class OdooMappingRijInvoerDto(StrikteInvoer):
    """Eén bevestigde rij: RLZ-id (grootboek `ledger_id` / btw `taxrate_id`) → Odoo-int-id (0 = synthetisch
    "Geen btw (0%)", alleen bij btw)."""

    rlz_id: uuid.UUID
    odoo_id: int = Field(ge=0)


class OdooMappingInvoerDto(StrikteInvoer):
    grootboek: list[OdooMappingRijInvoerDto] = Field(default_factory=list)
    btw: list[OdooMappingRijInvoerDto] = Field(default_factory=list)


class OdooOverstapDto(OdooGegevensDto):
    """Blok E, ingang B: een bestaande RLZ-administratie stapt over op Odoo (volledige backend) — company uit
    de lijst + verplichte overgangsdatum (vanaf die factuurdatum boekt de administratie in Odoo) + de door de
    mens bevestigde rekening-mapping (blok A 04-09; leeg mag alleen als er niets in gebruik is)."""

    company_id: int = Field(gt=0)
    overgangsdatum: date
    mapping: OdooMappingInvoerDto


class OdooOverstapVoorbereidenDto(OdooGegevensDto):
    """Stap vóór de overstap: probe + live Odoo-lijsten + in-gebruik-RLZ-rijen + deterministisch voorstel."""

    company_id: int = Field(gt=0)


class OdooRekeningDto(BaseModel):
    odoo_id: int
    lokaal_id: uuid.UUID
    code: str
    naam: str


class OdooTariefDto(BaseModel):
    """`percentage` = canonieke FRACTIE (0.21), zoals `TaxrateOptieResponse.percentage`; verlegd draagt het
    Odoo-`amount`/100 (21% R → 0.21), synthetisch = 0."""

    odoo_id: int
    lokaal_id: uuid.UUID
    naam: str
    percentage: Decimal
    verlegd: bool
    synthetisch: bool


class MappingVoorstelRijDto(BaseModel):
    rlz_id: uuid.UUID
    rlz_code: str | None
    rlz_naam: str | None
    in_gebruik_observaties: int
    in_gebruik_open_regels: int
    voorstel_odoo_id: int | None
    voorstel_odoo_code: str | None
    voorstel_odoo_naam: str | None
    reden: str | None


class BtwMappingVoorstelRijDto(BaseModel):
    rlz_id: uuid.UUID
    rlz_naam: str | None
    rlz_percentage: Decimal | None  # canonieke fractie (0.21) — verlegd = 0 (RLZ-conventie)
    verlegd: bool
    in_gebruik_observaties: int
    in_gebruik_open_regels: int
    voorstel_odoo_id: int | None
    voorstel_odoo_naam: str | None
    reden: str | None


class OdooMappingTellingDto(BaseModel):
    grootboek_totaal: int
    grootboek_met_voorstel: int
    btw_totaal: int
    btw_met_voorstel: int


class OdooOverstapVoorbereidingDto(BaseModel):
    company_naam: str | None
    probe: dict[str, str]
    grootboek: list[MappingVoorstelRijDto]
    btw: list[BtwMappingVoorstelRijDto]
    odoo_grootboek: list[OdooRekeningDto]
    odoo_btw: list[OdooTariefDto]
    telling: OdooMappingTellingDto


class MappingRijDto(BaseModel):
    soort: str
    rlz_id: uuid.UUID
    rlz_code: str | None
    rlz_naam: str | None
    odoo_id: int
    odoo_code: str | None
    odoo_naam: str | None
    bron: str
    versie: int
    bevestigd_op: datetime
    bevestigd_door_naam: str | None


class OdooMappingStandDto(BaseModel):
    grootboek: list[MappingRijDto]
    btw: list[MappingRijDto]
    odoo_grootboek: list[OdooRekeningDto]
    odoo_btw: list[OdooTariefDto]
    laatst_bevestigd_op: datetime | None
    laatst_bevestigd_door_naam: str | None


class OdooMappingCorrectieDto(StrikteInvoer):
    odoo_id: int = Field(ge=0)


class OdooOvergangsdatumDto(StrikteInvoer):
    overgangsdatum: date


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
