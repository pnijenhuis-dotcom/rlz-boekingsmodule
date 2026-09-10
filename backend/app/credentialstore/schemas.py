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


class RechtenProbeResponse(BaseModel):
    """`rapport` = route → 'ok' | HTTP-status; `meldingen` (10-09) = per rode route het letterlijke RLZ-antwoord
    ("HTTP 403 — <body, ≤ 300 tekens>") zodat de Beheerder ziet wát Reeleezee zegt."""

    rapport: dict[str, str]
    meldingen: dict[str, str] = {}
