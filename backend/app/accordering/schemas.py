"""DTO's voor de klant-accorderingsflow (migratie 0033). De endpoints zijn ontworpen voor de
latere accordeur-PWA (wachtrij/akkoord/afwijzen/staande regel) én de kantoor-UI (instellingen,
accorderingshistorie) — zelfde scope-regels als overal (RLS + server-side checks)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class LaagDto(BaseModel):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None = None
    bedrag_drempel: Decimal | None = None


class InstellingenResponse(BaseModel):
    ingeschakeld: bool
    lagen: list[LaagDto]


class LaagInputDto(StrikteInvoer):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None = None


class InstellingenInput(StrikteInvoer):
    ingeschakeld: bool
    lagen: list[LaagInputDto]


class KandidaatDto(BaseModel):
    id: uuid.UUID
    naam: str


class KandidatenResponse(BaseModel):
    kandidaten: list[KandidaatDto]


class StapResponse(BaseModel):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    bedrag_drempel: Decimal | None
    vereist: bool
    besluit: str | None
    besluit_bron: str | None
    reden: str | None
    besloten_op: datetime | None
    aan_de_beurt: bool


class AccorderingResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    aangeboden_op: datetime
    afgerond_op: datetime | None
    stappen: list[StapResponse]


class HerinneringResponse(BaseModel):
    """Uitkomst van een handmatige herinnering (beheer-mini 2026-08-16, migratie 0053)."""

    document_id: uuid.UUID
    accordeur_naam: str
    verzonden_op: datetime
    kanaal: str


class HerinneringenOverzichtResponse(BaseModel):
    """document_id -> laatste geslaagde handmatige herinnering ("laatst herinnerd")."""

    laatst_herinnerd: dict[uuid.UUID, datetime]


class AkkoordInput(StrikteInvoer):
    staande_regel_aanmaken: bool = False


class AfwijsInput(StrikteInvoer):
    reden: str


class BesluitResponse(BaseModel):
    accordering: AccorderingResponse
    alles_akkoord: bool
    geboekt: bool
    boek_fout: str | None
    staande_regel_id: uuid.UUID | None


class WachtrijItemResponse(BaseModel):
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    leverancier_naam: str | None
    referentie: str | None
    factuurdatum: date | None
    totaalbedrag: Decimal | None
    aangeboden_op: datetime
    laag_volgnummer: int
    boeking_omschrijving: str | None = None
    staande_regel_kandidaat: bool = False


class WachtrijResponse(BaseModel):
    items: list[WachtrijItemResponse]


class StaandeRegelResponse(BaseModel):
    id: uuid.UUID
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    bedrag: Decimal
    actief: bool
    aangemaakt_op: datetime
    ingetrokken_op: datetime | None


class StaandeRegelsResponse(BaseModel):
    regels: list[StaandeRegelResponse]
