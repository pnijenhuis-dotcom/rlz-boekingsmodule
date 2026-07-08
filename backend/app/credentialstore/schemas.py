from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CredentialUpsertRequest(BaseModel):
    webservice_username: str
    wachtwoord: str


class CredentialMetadataResponse(BaseModel):
    """Bewust geen wachtwoord-veld — schrijf-only (besluit 0012)."""

    administratie_id: uuid.UUID
    webservice_username: str
    aangemaakt_op: datetime
    bijgewerkt_op: datetime


class RechtenProbeResponse(BaseModel):
    rapport: dict[str, str]
