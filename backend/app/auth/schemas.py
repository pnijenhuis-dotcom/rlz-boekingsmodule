from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models import GebruikerRol
from app.schemas_basis import StrikteInvoer


class UitnodigingAanmakenRequest(StrikteInvoer):
    naam: str = Field(min_length=1)
    e_mail: str = Field(min_length=3)
    rol: GebruikerRol
    administratie_ids: list[uuid.UUID] = Field(default_factory=list)


class UitnodigingAanmakenResponse(BaseModel):
    uitnodiging_id: uuid.UUID
    gebruiker_id: uuid.UUID
    token: str
    verloopt_op: datetime


class UitnodigingAccepterenRequest(StrikteInvoer):
    token: str
    wachtwoord: str


class UitnodigingAccepterenResponse(BaseModel):
    """`soort` bepaalt de tweede activatiestap: 'totp' (kantoor-rollen; totp-velden gevuld) of
    'passkey' (klant-accordeur; passkey_setup_token gevuld — besluit auth-cadans 2026-08-11)."""

    soort: str
    totp_setup_token: str | None = None
    otpauth_uri: str | None = None
    secret: str | None = None
    passkey_setup_token: str | None = None


class TotpBevestigenRequest(StrikteInvoer):
    code: str


class TokenPaarResponse(BaseModel):
    """Bevat bewust geen refresh_token: die gaat uitsluitend als httpOnly-cookie mee
    (Auth-0010-b punt 1) — nooit in de JSON-body, anders kan een frontend hem alsnog in
    localStorage zetten en is het hele punt van httpOnly weg."""

    access_token: str
    token_type: str = "bearer"


class LoginRequest(StrikteInvoer):
    e_mail: str
    wachtwoord: str
    totp_code: str


class AccordeurLoginRequest(StrikteInvoer):
    e_mail: str
    wachtwoord: str


class AccordeurLoginResponse(BaseModel):
    """Wachtwoordstap geslaagd; de client rondt af met een passkey-assertion (bekend apparaat)
    of -registratie (nieuw apparaat). Het setup-token machtigt uitsluitend die afronding."""

    passkey_setup_token: str
    heeft_passkeys: bool


class WebauthnConfigResponse(BaseModel):
    """Publiek (geen auth): de PWA moet vóór het inlogscherm weten of de dev-stub actief is —
    op een LAN-IP (geen secure context) bestaat window.PublicKeyCredential niet en is de stub
    de enige kliktest-route. Bevat bewust geen secrets."""

    dev_stub: bool
    rp_id: str


class WebauthnRegistratieVoltooienRequest(StrikteInvoer):
    """`credential` = de JSON-geserialiseerde PublicKeyCredential uit de browser (registratie).
    `dev_stub` = expliciet gemarkeerde dev-fallback (alleen werkzaam buiten productie)."""

    credential: dict | None = None
    apparaat_naam: str | None = None
    dev_stub: bool = False


class WebauthnAssertieVoltooienRequest(StrikteInvoer):
    credential: dict | None = None
    dev_stub: bool = False


class WebauthnOptiesResponse(BaseModel):
    """`opties` is de door py_webauthn geserialiseerde options-JSON (registratie of assertie) —
    als string doorgegeven zodat de byte-exacte challenge-encoding intact blijft."""

    opties: str


class ApparaatResponse(BaseModel):
    id: uuid.UUID
    apparaat_naam: str | None
    is_dev_stub: bool
    aangemaakt_op: datetime
    laatst_gebruikt_op: datetime | None
    ingetrokken_op: datetime | None


class ApparatenResponse(BaseModel):
    apparaten: list[ApparaatResponse]


class KantoorPasskeyLoginOptiesRequest(StrikteInvoer):
    """Kantoor-passkey-login stap 1 (besluit 0020): usernameless mag niet (0022/0006-lijn) —
    het e-mailadres blijft het startpunt van elke login."""

    e_mail: str


class KantoorPasskeyOptiesResponse(BaseModel):
    """`opties` = assertion-options-JSON; None kan alleen samen met dev_stub=True (er is enkel
    een stub-credential in een actieve dev-stub-omgeving — de client rondt af met dev_stub)."""

    opties: str | None
    dev_stub: bool


class KantoorPasskeyLoginVoltooienRequest(StrikteInvoer):
    e_mail: str
    credential: dict | None = None
    dev_stub: bool = False


class KantoorApparaatResponse(ApparaatResponse):
    gebruiker_id: uuid.UUID
    gebruiker_naam: str


class KantoorApparatenResponse(BaseModel):
    apparaten: list[KantoorApparaatResponse]


class VoorwaardenResponse(BaseModel):
    tekst_versie: str
    tekst: str
    akkoord_gegeven: bool
    administratie_namen: list[str]


class RolWijzigenRequest(StrikteInvoer):
    rol: GebruikerRol


class ScopeToevoegenRequest(StrikteInvoer):
    administratie_id: uuid.UUID


class AdministratieResponse(BaseModel):
    id: uuid.UUID
    naam: str


class MijnAdministratiesResponse(BaseModel):
    administraties: list[AdministratieResponse]
