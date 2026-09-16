"""Pydantic-DTO's voor de Beheerder-routes van de intercompany-module (blok A opdracht 16-09)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RelatieStatus = Literal["afgeleid", "bevestigd", "uitgesloten"]


class IntercompanyRelatieDto(BaseModel):
    id: uuid.UUID
    administratie_a_id: uuid.UUID
    administratie_a_naam: str
    entity_in_a: uuid.UUID
    entity_naam: str | None
    administratie_b_id: uuid.UUID
    administratie_b_naam: str
    richting: Literal["crediteur", "debiteur"]
    basis: Literal["kvk", "btw", "naam", "doorbelasting"]
    status: RelatieStatus
    bron: Literal["afgeleid", "mens"]
    reden: str | None
    gewijzigd_op: datetime | None
    #: Telt mee in de factuurmatch (bevestigd, of afgeleid mét basis ≠ naam).
    actief: bool


class IntercompanyRelatiesDto(BaseModel):
    relaties: list[IntercompanyRelatieDto]


class StatusWijzigingDto(BaseModel):
    status: RelatieStatus
    reden: str | None = Field(default=None, max_length=500)


class RcKoppelingDto(BaseModel):
    id: uuid.UUID
    administratie_a_id: uuid.UUID
    administratie_a_naam: str
    rekening_a: uuid.UUID
    rekening_a_code: str | None
    rekening_a_naam: str | None
    administratie_b_id: uuid.UUID
    administratie_b_naam: str
    rekening_b: uuid.UUID | None
    rekening_b_code: str | None
    rekening_b_naam: str | None
    basis: Literal["naam", "afkorting", "mens"]
    status: RelatieStatus
    bron: Literal["afgeleid", "mens"]
    reden: str | None
    gewijzigd_op: datetime | None
    actief: bool


class IdentiteitDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    naam: str | None
    kvk: str | None
    btw: str | None
    bron: str
    afkortingen: list[str]
    gelezen_op: datetime | None


class RcKoppelingenDto(BaseModel):
    koppelingen: list[RcKoppelingDto]
    identiteiten: list[IdentiteitDto]


class AfkortingenDto(BaseModel):
    afkortingen: list[str] = Field(default_factory=list, max_length=50)


class AfleidenResultaatDto(BaseModel):
    identiteiten: dict[str, int]
    identiteit_meldingen: list[str]
    relaties: dict
    rc_koppelingen: dict
