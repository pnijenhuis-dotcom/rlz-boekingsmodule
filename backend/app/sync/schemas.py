from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class SyncTellingResponse(BaseModel):
    aangemaakt: int
    bijgewerkt: int
    verdwenen: int


class GrootboekOptieResponse(BaseModel):
    ledger_id: uuid.UUID
    code: str
    naam: str
    soort: int


class GrootboekLijstResponse(BaseModel):
    rekeningen: list[GrootboekOptieResponse]


class TaxrateOptieResponse(BaseModel):
    id: uuid.UUID
    naam: str | None
    percentage: Decimal | None


class TaxrateLijstResponse(BaseModel):
    btw_codes: list[TaxrateOptieResponse]


class VendorOptieResponse(BaseModel):
    id: uuid.UUID
    naam: str | None


class VendorLijstResponse(BaseModel):
    crediteuren: list[VendorOptieResponse]


class NieuweCrediteurInput(StrikteInvoer):
    naam: str
    # Controlescherm v2 ⑥ (02-09): voorgevuld uit de scan. RLZ's Vendor-PUT kent alleen `Name`
    # (api-verkenning) — KvK/btw landen in `crediteur_kenmerk`, het IBAN in de vertrouwde set
    # (`leverancier_iban`, bron bevestigd — de mens maakt bewust déze crediteur mét dít IBAN aan).
    kvk_nummer: str | None = None
    btw_nummer: str | None = None
    iban: str | None = None
    document_id: uuid.UUID | None = None


class NieuweCrediteurResponse(BaseModel):
    id: uuid.UUID
    naam: str | None
    kvk_opgeslagen: bool = False
    btw_opgeslagen: bool = False
    iban_vertrouwd: bool = False
    waarschuwingen: list[str] = []


class DubbeleCrediteurDto(BaseModel):
    vendor_id: uuid.UUID
    naam: str | None
    btw_nummer: str | None
    kvk_nummer: str | None
    ibans: list[str]


class DubbelGroepDto(BaseModel):
    """Punt 14 (28-08): groep waarschijnlijk-dezelfde crediteuren; `soort` = waarop ze gelijk zijn
    (btw_nummer | kvk_nummer | iban | naam). Samenvoegen blijft RLZ-mensenwerk — wij verwijderen niets."""

    soort: str
    sleutel: str
    crediteuren: list[DubbeleCrediteurDto]


class DubbeleCrediteurenResponse(BaseModel):
    aantal_crediteuren: int
    groepen: list[DubbelGroepDto]


class CrediteurKvkDto(BaseModel):
    """KvK Basisprofiel voor een crediteur (hergebruik app/integraties/kvk.py, steigerbouw-A3) —
    ter controle door een mens, schrijft niets."""

    kvk_nummer: str
    gevonden: bool
    naam: str | None = None
    rechtsvorm: str | None = None
    plaats: str | None = None
    uitgeschreven: bool | None = None
    testomgeving: bool


class ProjectOptieResponse(BaseModel):
    id: uuid.UUID
    naam: str | None


class ProjectLijstResponse(BaseModel):
    projecten: list[ProjectOptieResponse]
