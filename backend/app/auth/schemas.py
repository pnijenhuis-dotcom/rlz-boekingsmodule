from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models import GebruikerRol


class UitnodigingAanmakenRequest(BaseModel):
    naam: str = Field(min_length=1)
    e_mail: str = Field(min_length=3)
    rol: GebruikerRol
    administratie_ids: list[uuid.UUID] = Field(default_factory=list)


class UitnodigingAanmakenResponse(BaseModel):
    uitnodiging_id: uuid.UUID
    gebruiker_id: uuid.UUID
    token: str
    verloopt_op: datetime


class UitnodigingAccepterenRequest(BaseModel):
    token: str
    wachtwoord: str


class UitnodigingAccepterenResponse(BaseModel):
    totp_setup_token: str
    otpauth_uri: str
    secret: str


class TotpBevestigenRequest(BaseModel):
    code: str


class TokenPaarResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    e_mail: str
    wachtwoord: str
    totp_code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RolWijzigenRequest(BaseModel):
    rol: GebruikerRol


class ScopeToevoegenRequest(BaseModel):
    administratie_id: uuid.UUID
