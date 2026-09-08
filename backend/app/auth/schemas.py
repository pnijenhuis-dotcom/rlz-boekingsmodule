from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_serializer, model_validator

from app.db.models import GebruikerRol
from app.schemas_basis import StrikteInvoer

# Bugfix 04-09 (casus "+ Veldwerker" maakte een kantoormedewerker aan): de aanroepende INGANG reist mee,
# zodat de server een rolgroep die niet bij de ingang past weigert (422) én de audit de ingang draagt.
# None = onbekend (oudere client/scripts) — dan alleen de bestaande poorten.
UitnodigingBron = Literal["kantoor", "veldwerkers", "klant_accordeurs", "planning"]


class UitnodigingAanmakenRequest(StrikteInvoer):
    naam: str = Field(min_length=1)
    e_mail: str = Field(min_length=3)
    rol: GebruikerRol
    administratie_ids: list[uuid.UUID] = Field(default_factory=list)
    # A4 (steigerbouw-run 25-08): account aanmaken zónder mail — status 'uitgenodigd', de
    # uitnodiging wordt later verstuurd via de bestaande "Opnieuw mailen"-knop.
    uitnodiging_later: bool = False
    bron: UitnodigingBron | None = None


class DigestVoorkeurDto(BaseModel):
    """Maandagochtend-digest (D2, 01-09): eigen opt-out van de kantoormedewerker."""

    opt_out: bool


class UitnodigingAanmakenResponse(BaseModel):
    uitnodiging_id: uuid.UUID
    gebruiker_id: uuid.UUID
    token: str
    verloopt_op: datetime
    # Mailkanaal (berichten-bouwsteen 2026-08-15): de uitnodiging gaat per mail; lukt dat niet
    # (niet geconfigureerd of verzendfout) dan is dat ZICHTBAAR en blijft handmatig link delen
    # de terugval — de link (token) zit hoe dan ook in deze respons.
    mail_verzonden: bool = False
    mail_fout: str | None = None
    # A4: bewust niet gemaild (uitnodiging_later) — géén fout, wel zichtbaar.
    mail_uitgesteld: bool = False
    # App-auth zonder passkey (08-09, migratie 0125): 8-tekens activatiecode (XXXX-XXXX) voor externe
    # app-rollen — "voor wie de link niet kan openen; zelfde geldigheid". Kantoor-rollen: None.
    activatiecode: str | None = None


class UitnodigingAccepterenRequest(StrikteInvoer):
    token: str
    wachtwoord: str


class UitnodigingInfoResponse(BaseModel):
    """Publiek, op token: welke activatieflow hoort bij deze link (28-08, mockup
    activatie-mobiel.html). `flow` = 'app' (externe app-rol: toestel + activatiecode, 08-09 —
    was 'passkey') of 'totp' (kantoor). Verzilvert niets; minimaal — geen e-mail, geen rol."""

    flow: str
    naam: str
    herstel: bool
    verloopt_op: datetime


class ActivatieProbleemRequest(StrikteInvoer):
    token: str


class ActivatieZonderWachtwoordRequest(StrikteInvoer):
    """Pincode-activatie (31-08, mockup app-lock-pincode.html): alleen de link — de 5-cijferige
    code is een lokaal toestel-anker en reist NOOIT mee naar de server."""

    token: str


class ActivatieZonderWachtwoordResponse(BaseModel):
    """Machtigt uitsluitend de passkey-registratie; server-side is nog niets vastgelegd — pas de
    geslaagde registratie verbruikt de link en maakt het account definitief (atomair, 28-08)."""

    passkey_setup_token: str


AppPlatform = Literal["ios", "android", "web"]


class AppActiverenRequest(StrikteInvoer):
    """App-activatie (besluit Peter 08-09): precies één van `token` (universal link uit de mail) of
    `activatiecode` (8 tekens, XXXX-XXXX — normalisatie server-side) — anders 422. De 5-cijferige
    toegangscode reist NOOIT mee: die is een lokaal anker op het toestel."""

    token: str | None = None
    activatiecode: str | None = Field(default=None, max_length=32)
    toestel_naam: str | None = Field(default=None, max_length=120)
    platform: AppPlatform | None = None

    @model_validator(mode="after")
    def _precies_een_ingang(self) -> AppActiverenRequest:
        if (self.token is None) == (self.activatiecode is None):
            raise ValueError("Geef óf een activatiecode óf een link (token) op — niet beide, niet geen van beide")
        return self


class AppActiverenResponse(BaseModel):
    """Token-levering ALTIJD in de body (het toestel bewaart het refresh-token in Keychain/Keystore/IndexedDB
    achter het lokale slot) — de route eist daarom de client-aankondiging (X-Native-Client / X-App-Slot).
    `apparaat_credential_id` = base64url van de toestel-meldsleutel voor /auth/app-lock/*."""

    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    apparaat_credential_id: str
    naam: str
    herstel: bool = False


class AppLockMeldingRequest(StrikteInvoer):
    """App-lock-meldingen (5× foute code / hulpvraag): het credential_id (base64url) van de
    passkey op dít toestel is de sleutel — hoge entropie, leeft alleen op het toestel en bij de
    server; misbruik kan hoogstens het eigen apparaat uitsluiten (fail-safe richting)."""

    credential_id: str = Field(min_length=8, max_length=2048)


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
    """Voor web-clients bevat dit bewust geen refresh_token: die gaat uitsluitend als
    httpOnly-cookie mee (Auth-0010-b punt 1) — nooit in de JSON-body, anders kan een frontend
    hem alsnog in localStorage zetten en is het hele punt van httpOnly weg.

    Uitzondering (native store-app, fase 4 — verkenning/17 (d) route 2): de Capacitor-webview
    kan de SameSite-cookie niet dragen; ALLEEN wanneer de client zich expliciet als native
    aandient (X-Native-Client-header of een header-aangeleverd refresh-token, zie
    router._lever_token_paar) gaat `refresh_token` in de body mee en bewaart de app hem in
    Keychain/Keystore — er wordt dan géén cookie gezet (één kanaal per client)."""

    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    # Ontgrendel-frequentie (besluit Peter 2026-08-27): uitsluitend op de stille refresh van een
    # apparaat-gebonden externe-app-sessie — True = passkey-ontgrendeling nodig (laatste
    # ceremonie op dit apparaat > 24 u geleden), False = direct door. Ontbreekt (None) op alle
    # andere responses — de kantoor-JSON blijft byte-identiek.
    ontgrendeling_nodig: bool | None = None

    @model_serializer(mode="wrap")
    def _zonder_leeg_refresh_token(self, handler):  # noqa: ANN001, ANN202
        """Web-responses dragen het veld überhaupt niet (contract-guard in de tests): alleen
        de native vorm serialiseert refresh_token. Idem `ontgrendeling_nodig`: alleen wanneer
        de service er een uitspraak over doet."""
        data = handler(self)
        if data.get("refresh_token") is None:
            data.pop("refresh_token", None)
        if data.get("ontgrendeling_nodig") is None:
            data.pop("ontgrendeling_nodig", None)
        return data


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
    # Store-links (blok F): None zolang leeg — de schermen tonen dan niets (geen placeholders).
    store_link_ios: str | None = None
    store_link_android: str | None = None


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
    # App-auth zonder passkey (08-09, migratie 0125): 'passkey' | 'toestel'; platform ios/android/web van een
    # toestel; niet_meer_gebruikt_op = legacy app-passkey gemarkeerd (CLI app-passkeys-markeren).
    soort: str = "passkey"
    platform: str | None = None
    niet_meer_gebruikt_op: datetime | None = None


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


class EMailWijzigenRequest(StrikteInvoer):
    """A5 (steigerbouw-run 25-08): Beheerder wijzigt het e-mailadres (= login) van een gebruiker."""

    e_mail: str = Field(min_length=3, max_length=254)


class EMailWijzigenResponse(BaseModel):
    gebruiker_id: uuid.UUID
    oud_e_mail: str
    nieuw_e_mail: str
    # Niet-geactiveerd account: er is direct een verse uitnodiging naar het nieuwe adres gestuurd.
    uitnodiging_vernieuwd: bool = False
    token: str | None = None
    verloopt_op: datetime | None = None
    mail_verzonden: bool = False
    mail_fout: str | None = None
    # 08-09: bij een vernieuwde uitnodiging voor een app-rol reist ook de nieuwe activatiecode mee (additief).
    activatiecode: str | None = None


class ScopeToevoegenRequest(StrikteInvoer):
    administratie_id: uuid.UUID


class AdministratieResponse(BaseModel):
    id: uuid.UUID
    naam: str
    # Fixrun 07-09 blok C3 (additief): uren-&-meerwerk-opt-in per administratie, zodat de
    # veldwerker-dialogen zonder picker-poort een standaard-administratie kunnen kiezen
    # (regel 3: de administratie mét opt-in — nooit hardcoded Universal).
    uren_meerwerk_ingeschakeld: bool = False


class MijnAdministratiesResponse(BaseModel):
    administraties: list[AdministratieResponse]


class GebruikerAdministratieKortDto(BaseModel):
    """Blok 5 (herstelrun 08-09): naam + status van een scope-administratie — óók gearchiveerde, zodat Gebruikers &
    toegang "‹naam› — gearchiveerd" toont i.p.v. een kale GUID."""

    id: uuid.UUID
    naam: str
    actief: bool


class GebruikerOverzichtResponse(BaseModel):
    """Rij op Gebruikers & toegang (fase 3 modernisering 15-08) — alleen bestaans-/statusfeiten
    over de beveiliging, nooit secret- of credentialmateriaal."""

    id: uuid.UUID
    naam: str
    e_mail: str
    rol: GebruikerRol
    status: str
    administratie_ids: list[uuid.UUID]
    heeft_totp: bool
    aantal_passkeys: int
    open_uitnodiging_verloopt_op: datetime | None
    # Open wachtwoord-herstel-link (migratie 0068, feedbackronde 25-08 punt 7) — alleen bij
    # externe app-gebruikers; los van de uitnodiging zodat het scherm ze kan onderscheiden.
    open_herstel_verloopt_op: datetime | None = None
    # Alleen zinvol gevuld voor klant-accordeurs (0 voor kantoorrollen).
    staande_goedkeuringen: int
    # Half geactiveerd (casus Haci, 28-08): externe app-rol MÉT wachtwoord maar ZONDER actieve
    # passkey (status actief óf wacht_op_passkey) — de Haci-klasse van vóór de atomaire
    # activatie; het scherm biedt dan de Herstel-link aan.
    half_geactiveerd: bool = False
    # Alleen gevuld bij status 'geblokkeerd' (migratie 0052).
    geblokkeerd_op: datetime | None
    geblokkeerd_door_naam: str | None
    # Alleen gevuld bij status 'gearchiveerd' (migratie 0075, feedbackronde 26-08 punt 1).
    gearchiveerd_op: datetime | None = None
    gearchiveerd_door_naam: str | None = None
    # Blok 5 (08-09): naam + actief per scope-administratie (volgorde = administratie_ids), incl. gearchiveerde.
    administraties: list[GebruikerAdministratieKortDto] = Field(default_factory=list)


class GebruikersLijstResponse(BaseModel):
    gebruikers: list[GebruikerOverzichtResponse]


class OpenWerkResponse(BaseModel):
    """Open werk van een gebruiker vóór archivering — waarschuwing mét aantallen, geen blokkade."""

    open_accorderingen: int
    weekstaten_ter_keuring: int
    eigen_open_weekstaten: int
