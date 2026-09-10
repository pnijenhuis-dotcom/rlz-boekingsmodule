from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class CredentialUpsertRequest(StrikteInvoer):
    webservice_username: str
    wachtwoord: str


class CredentialMetadataResponse(BaseModel):
    """Bewust geen wachtwoord-veld — schrijf-only (besluit 0012)."""

    administratie_id: uuid.UUID
    webservice_username: str
    aangemaakt_op: datetime
    bijgewerkt_op: datetime


class ZichtbareAdministratieDto(BaseModel):
    """Eén administratie die de webservice-login via `GET Administrations` ziet (nachtrun 10/11-09 blok 1)."""

    id: str
    naam: str | None = None


class RechtenProbeResponse(BaseModel):
    """`rapport` = route → 'ok' | HTTP-status; `meldingen` (10-09) = per rode route het letterlijke RLZ-antwoord
    ("HTTP 403 — <body, ≤ 300 tekens>") zodat de Beheerder ziet wát Reeleezee zegt.

    Nachtrun 10/11-09 blok 1 (knop "RLZ-check", additief): `rechten` = route → RLZ-recht (app/rlz/leesroutes.py),
    `administraties_zichtbaar` = wat de login via `GET Administrations` ziet (leeg + `administraties_fout` met de
    letterlijke melding als die call zelf faalde), `rlz_admin_id` = het geprobeerde administratie-id — zo is een
    verkeerd id direct zichtbaar ("eigen id NIET in de lijst")."""

    rapport: dict[str, str]
    meldingen: dict[str, str] = {}
    rechten: dict[str, str] = {}
    administraties_zichtbaar: list[ZichtbareAdministratieDto] = []
    administraties_fout: str | None = None
    rlz_admin_id: str = ""
