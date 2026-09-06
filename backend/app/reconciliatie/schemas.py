"""DTO's Inzicht › Reconciliatie (opdracht 06-09) — spiegel in frontend/src/reconciliatie/reconciliatieApi.ts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReconciliatieRunDto(BaseModel):
    """Eén reconciliatie-alles-run (202-antwoord + status-poll, bank_sync_run-patroon)."""

    run_id: uuid.UUID
    status: str  # wachtend | bezig | klaar | fout
    bron: str  # scheduler | cli | handmatig
    aangevraagd_op: datetime
    gestart_op: datetime | None = None
    afgerond_op: datetime | None = None
    exit_code: int | None = None
    # per blok: {status: ok|actie|fout, exit_code, gecontroleerd, afwijkingen, geaccepteerd, uitgesloten,
    # let_op, fouten, foutmelding}
    samenvatting: dict | None = None
    fout_reden: str | None = None
    mail_status: str | None = None  # niet_nodig | verzonden | mislukt | niet_geconfigureerd
    mail_detail: str | None = None


class AcceptatieWeergaveDto(BaseModel):
    reden: str
    geaccepteerd_op: datetime
    geaccepteerd_door_naam: str | None = None


class GezienWeergaveDto(BaseModel):
    reden: str
    gezien_op: datetime
    vervalt_op: datetime
    gezien_door_naam: str | None = None


class BevindingDto(BaseModel):
    """Eén rij = één bevinding uit de laatste afgeronde run, mét precies één handeling."""

    id: uuid.UUID
    run_id: uuid.UUID
    blok: str  # bank | documenten | omzet | doorbelasting | run
    soort: str  # afwijking | let_op | fout | geaccepteerd | uitgesloten | gezien
    administratie_id: uuid.UUID | None = None
    administratie_naam: str | None = None
    vingerafdruk: str
    tekst: str
    sinds: datetime
    nieuw: bool
    acceptatie: AcceptatieWeergaveDto | None = None
    gezien: GezienWeergaveDto | None = None
    detail: dict | None = None
    doel_pad: str | None = None


class TellersDto(BaseModel):
    afwijkingen: int
    let_op: int
    fouten: int
    geaccepteerd: int
    uitgesloten: int
    gezien: int
    administraties: int


class AdministratieFacetDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class FacettenDto(BaseModel):
    soort: dict[str, int]
    administraties: list[AdministratieFacetDto]


class BevindingenLijstDto(BaseModel):
    rijen: list[BevindingDto]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: TellersDto
    facetten: FacettenDto
    laatste_run: ReconciliatieRunDto | None = None


class StandDto(BaseModel):
    """KPI-kaart werkvoorraad: teller = open afwijkingen + fouten + open LET-OP's."""

    teller: int
    afwijkingen: int
    let_op: int
    fouten: int
    laatste_run: ReconciliatieRunDto | None = None


class RedenInvoerDto(BaseModel):
    administratie_id: uuid.UUID
    reden: str = Field(min_length=1, max_length=2000)


class ActieResultaatDto(BaseModel):
    id: uuid.UUID


class InstellingDto(BaseModel):
    gezien_dagen: int = Field(ge=1, le=3650)
