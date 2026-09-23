"""DTO's activa fase 1 (CONTRACT A §API; frontend `frontend/src/activa/activaApi.ts` 1:1). Bedragen als strings met twee
decimalen ("450.00"), datums ISO; invoer erft `StrikteInvoer` (onbekend veld = 422)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class SignaalDto(BaseModel):
    code: str
    tekst: str


class KoppelingDto(BaseModel):
    id: uuid.UUID
    status: str
    herkomst: str
    rlz_fixed_asset_id: uuid.UUID | None = None
    rlz_receipt_number: str | None = None
    reden: str | None = None
    door: uuid.UUID | None = None
    gewijzigd_op: datetime


class KandidaatDto(BaseModel):
    regel_volgnummer: int
    ledger_id: uuid.UUID
    ledger_code: str
    ledger_naam: str
    omschrijving: str
    aanschafwaarde: str
    aanschafdatum: date
    categorie: str
    categorie_label: str
    termijn_maanden: int
    methode_naam: str
    restwaarde: str
    afschrijving_ledger_id: uuid.UUID | None = None
    afschrijving_ledger_code: str | None = None
    #: `koppeling` | `instelling` | `conventie` | None — herkomst-chip op de kaart (BUG 24-09).
    afschrijving_bron: str | None = None
    signalen: list[SignaalDto]
    koppeling: KoppelingDto | None = None


class OnderGrensDto(BaseModel):
    regel_volgnummer: int
    ledger_code: str
    ledger_naam: str
    netto: str
    tekst: str


class LedgerOptieDto(BaseModel):
    ledger_id: uuid.UUID
    code: str
    naam: str


class ActivaVoorstelDto(BaseModel):
    administratie_id: uuid.UUID
    document_id: uuid.UUID
    document_geboekt: bool
    grens: str
    grens_bron: str
    automatisch_ingeschakeld: bool
    register_leesbaar: bool | None = None
    register_fout: str | None = None
    kandidaten: list[KandidaatDto]
    onder_grens: list[OnderGrensDto]
    afschrijving_ledger_opties: list[LedgerOptieDto]


class AanmakenInput(StrikteInvoer):
    afschrijving_ledger_id: uuid.UUID | None = None
    termijn_maanden: int | None = None


class OverslaanInput(StrikteInvoer):
    reden: str


class CategorieDto(BaseModel):
    code: str
    label: str
    default_maanden: int


class KoppelingTellersDto(BaseModel):
    gepland: int = 0
    aangemaakt: int = 0
    overgeslagen: int = 0
    mislukt: int = 0
    beoordelen: int = 0


class ActivaInstellingDto(BaseModel):
    automatisch_aanmaken_ingeschakeld: bool
    activeringsgrens: str
    grens_rlz: str | None = None
    grens_rlz_gelezen_op: datetime | None = None
    effectieve_grens: str
    grens_bron: str
    termijnen: dict[str, int]
    afschrijving_ledgers: dict[str, uuid.UUID]
    register_leesbaar: bool | None = None
    register_geprobeerd_op: datetime | None = None
    register_fout: str | None = None
    categorieen: list[CategorieDto]
    mva_rekeningen: list[LedgerOptieDto]
    afschrijving_ledger_opties: list[LedgerOptieDto]
    koppelingen_tellers: KoppelingTellersDto


class ActivaInstellingInput(StrikteInvoer):
    automatisch_aanmaken_ingeschakeld: bool
    activeringsgrens: str
    termijnen: dict[str, int]
    afschrijving_ledgers: dict[str, uuid.UUID | None]
