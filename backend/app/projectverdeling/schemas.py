from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class VasteRegelDto(BaseModel):
    project_id: uuid.UUID
    bedrag: Decimal
    hint: str | None = None
    project_naam: str | None = None


class VerdeelDeelDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    wijze: str  # vast | pro_rato
    bedrag: Decimal
    aandeel: Decimal | None = None
    omzet: Decimal | None = None


class OmzetstandDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    omzet: Decimal


class HercontroleDto(BaseModel):
    op: datetime
    afwijking_pct: Decimal | None = None
    drempel_pct: Decimal
    periode: date | None = None
    signaal: bool
    nieuwe_verdeling: list[VerdeelDeelDto]


class ProjectverdelingDto(BaseModel):
    """De verdeling zoals het controlescherm 'm toont (mockup blok 1): vaste regels, restant pro rato, de
    berekende delen (preview "26120 Eindhoven 31,4% · € 439,60"), de blokkade-zin, en ná boeken de bevroren
    stand + het hercontrole-signaal."""

    document_id: uuid.UUID
    status: str  # voorstel | geboekt | vervallen | geen
    opgeslagen: bool
    prefill: bool = False
    basisbedrag: Decimal | None = None
    vaste_regels: list[VasteRegelDto] = []
    pro_rato: bool = False
    pro_rato_periode: date | None = None
    pro_rato_periode_label: str | None = None
    pro_rato_bedrag: Decimal | None = None
    delen: list[VerdeelDeelDto] = []
    omzetstanden: list[OmzetstandDto] = []
    aantal_projecten_met_omzet: int = 0
    omzet_cache_leeg: bool = False
    compleet: bool = False
    blokkade: str | None = None
    boek_cyclus: int | None = None
    hercontrole: HercontroleDto | None = None


class VasteRegelInput(StrikteInvoer):
    project_id: uuid.UUID
    bedrag: Decimal
    hint: str | None = Field(default=None, max_length=200)


class ProjectverdelingInput(StrikteInvoer):
    vaste_regels: list[VasteRegelInput] = []
    #: eerste dag van de omzetmaand; None = pro rato uit (alleen vaste regels)
    pro_rato_periode: date | None = None
    #: True = de mens haalt de verdeling weg (status vervallen — geen prefill meer, nooit een DELETE)
    vervallen: bool = False


class HerverdelenInput(StrikteInvoer):
    reden: str = Field(min_length=5, max_length=500)


class HerverdeelResultaatDto(BaseModel):
    document_id: uuid.UUID
    status: str
    rlz_tegenboeking_id: uuid.UUID
    rlz_boekstuknummer: str | None = None


class LeverancierProRatoDto(BaseModel):
    vendor_id: uuid.UUID
    naam: str | None = None
    projectverdeling_pro_rato: bool


class LeverancierProRatoLijstDto(BaseModel):
    leveranciers: list[LeverancierProRatoDto]


class LeverancierProRatoInput(StrikteInvoer):
    ingeschakeld: bool


class InstellingenDto(BaseModel):
    drempel_pct: Decimal
    wachtweken: int


class InstellingenInput(StrikteInvoer):
    drempel_pct: Decimal | None = Field(default=None, gt=0, le=100)
    wachtweken: int | None = Field(default=None, ge=0, le=52)


class SignaalRijDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    document_id: uuid.UUID
    bestandsnaam: str
    leverancier: str | None = None
    referentie: str | None = None
    pro_rato_periode: date | None = None
    pro_rato_bedrag: Decimal | None = None
    afwijking_pct: Decimal
    drempel_pct: Decimal
    hercontrole_op: datetime


class SignaalLijstDto(BaseModel):
    rijen: list[SignaalRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    administraties: int
