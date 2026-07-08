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
    """Bevat bewust geen refresh_token: die gaat uitsluitend als httpOnly-cookie mee
    (Auth-0010-b punt 1) — nooit in de JSON-body, anders kan een frontend hem alsnog in
    localStorage zetten en is het hele punt van httpOnly weg."""

    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    e_mail: str
    wachtwoord: str
    totp_code: str


class RolWijzigenRequest(BaseModel):
    rol: GebruikerRol


class ScopeToevoegenRequest(BaseModel):
    administratie_id: uuid.UUID
