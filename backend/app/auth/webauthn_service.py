"""Passkeys (WebAuthn) + device-cadans voor de accordeur-PWA (migratie 0040).

Besluit Peter 2026-08-11 (BESLISSINGEN "Mobiele bouwstenen accordeur-PWA" punt 2, herzien):
- volledige login (wachtwoord + passkey) alléén bij eerste gebruik, op een nieuw/onbekend
  apparaat, of ná 7 dagen inactiviteit (sliding refresh-TTL, zie service._refresh_ttl_voor);
- passkey-assertion (Face ID/Touch ID/Android-biometrie/toestel-pincode — de OS-fallbacks
  zitten in WebAuthn zelf) éénmaal bij elke app-opening, geldig tot de app sluit;
- GEEN biometrie per actie;
- kantoor-kill-switch per accordeur/apparaat (credential intrekken = gebonden sessies dicht).

Bibliotheek: py_webauthn (duo-labs, BSD-3-Clause, actief onderhouden — 3.x) doet de
attestation-/assertion-verificatie; challenges zijn server-side, éénmalig en kortlevend
(platform.webauthn_challenge — nooit een challenge uit de client vertrouwen).

Dev-stub (secure-context-beperking): WebAuthn werkt uitsluitend op https of localhost. Een
telefoontest via een LAN-IP kan dus geen echte passkey registreren. `auth_biometrie_dev_stub`
(default UIT) opent een expliciet gemarkeerde fallback — alleen werkzaam buiten productie
(dev_stub_actief() toetst environment hard, de setting alleen is niet genoeg) en elke
stub-credential is zichtbaar gemarkeerd (`is_dev_stub`). Echte passkeys activeren bij https
(GCP-uitrol)."""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.auth.normalisatie import normaliseer_e_mail
from app.auth.service import AuthError, TokenPaar, _hash_token, _issue_token_paar, _login_metadata
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import (
    Gebruiker,
    GebruikerRol,
    GebruikerStatus,
    RefreshToken,
    WebauthnChallenge,
    WebauthnCredential,
)
from app.db.session import scoped_session
from app.security.passwords import verify_password
from app.security.tokens import TokenError, create_passkey_setup_token, decode_token

_DEV_ENVIRONMENTS = ("dev", "local")


class GeenPasskeys(AuthError):
    """De gebruiker heeft (op geen enkel apparaat) een actieve passkey — de client moet naar de
    registratie-flow (volledige login op een nieuw apparaat), niet naar een assertion."""


def dev_stub_actief() -> bool:
    """De stub is dubbel vergrendeld: de expliciete setting ÉN een niet-productie-omgeving.
    In productie is de stub onwerkzaam ongeacht de setting — zelfde gate-principe als de
    JWT-secret-fallback (app/security/tokens.py)."""
    return settings.auth_biometrie_dev_stub and settings.environment in _DEV_ENVIRONMENTS


# --- challenges (server-side, eenmalig) -----------------------------------------------------------


def _maak_challenge(session: Session, *, gebruiker_id: uuid.UUID, soort: str) -> bytes:
    # Huishouding (nazorg 2026-08-11): verlopen rijen — verbruikt óf nooit gebruikt — zijn
    # per definitie waardeloos (_verbruik_challenge weigert ze toch al op verloopt_op) en
    # zouden anders eeuwig aangroeien. Opruimen bij elke insert houdt de tabel klein zonder
    # aparte scheduled job; de TTL is kort (settings.webauthn_challenge_ttl_seconds).
    session.execute(delete(WebauthnChallenge).where(WebauthnChallenge.verloopt_op < datetime.now(UTC)))
    challenge = secrets.token_bytes(32)
    session.add(
        WebauthnChallenge(
            id=uuid.uuid4(),
            gebruiker_id=gebruiker_id,
            soort=soort,
            challenge=challenge,
            verloopt_op=datetime.now(UTC) + timedelta(seconds=settings.webauthn_challenge_ttl_seconds),
        )
    )
    return challenge


def _challenge_uit_client_data(credential_json: dict) -> bytes:
    """De challenge die de authenticator ondertekende, uit de clientDataJSON — alleen om de
    bijbehorende server-side challenge-rij op te zoeken; de échte vergelijking doet
    py_webauthn daarna nogmaals (expected_challenge)."""
    try:
        client_data_b64 = credential_json["response"]["clientDataJSON"]
        client_data = json.loads(_b64url_decode(client_data_b64))
        return _b64url_decode(client_data["challenge"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("Ongeldige WebAuthn-response (clientDataJSON)") from exc


def _b64url_decode(waarde: str) -> bytes:
    return base64.urlsafe_b64decode(waarde + "=" * (-len(waarde) % 4))


def _verbruik_challenge(session: Session, *, gebruiker_id: uuid.UUID, soort: str, challenge: bytes) -> bytes:
    """Zoekt de exacte, nog geldige challenge-rij en verbrandt 'm (gebruikt_op) — eenmalig
    gebruik, replay van een oude ondertekende response faalt hier."""
    rij = session.scalars(
        select(WebauthnChallenge)
        .where(
            WebauthnChallenge.gebruiker_id == gebruiker_id,
            WebauthnChallenge.soort == soort,
            WebauthnChallenge.challenge == challenge,
            WebauthnChallenge.gebruikt_op.is_(None),
        )
        .with_for_update()
    ).first()
    if rij is None or rij.verloopt_op < datetime.now(UTC):
        raise AuthError("Ongeldige of verlopen WebAuthn-challenge")
    rij.gebruikt_op = datetime.now(UTC)
    return rij.challenge


# --- accordeur-login (wachtwoordstap) -------------------------------------------------------------


@dataclass(frozen=True)
class AccordeurLoginResultaat:
    passkey_setup_token: str
    heeft_passkeys: bool


def start_accordeur_login(*, e_mail: str, wachtwoord: str, ip_adres: str | None = None) -> AccordeurLoginResultaat:
    """Wachtwoordstap van de accordeur-login (nieuw apparaat of ná 7 dagen inactiviteit).
    Zelfde generieke fout als service.login() — geen account-enumeratie. Alleen voor de rol
    klant-accordeur (kantoor-rollen houden wachtwoord + TOTP); status wacht_op_passkey mag ook
    inloggen om een afgebroken activatie (wachtwoord gezet, registratie nooit afgemaakt) af te
    ronden — er is dan nog geen andere weg naar een werkend account."""
    generic_error = "Ongeldige inloggegevens"
    e_mail = normaliseer_e_mail(e_mail)
    faal_gebruiker_id: uuid.UUID | None = None
    resultaat: AccordeurLoginResultaat | None = None

    with scoped_session(None) as session:
        gebruiker = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail)).one_or_none()
        if gebruiker is None:
            pass
        elif (
            gebruiker.rol != GebruikerRol.KLANT_ACCORDEUR
            or gebruiker.status not in (GebruikerStatus.ACTIEF, GebruikerStatus.WACHT_OP_PASSKEY)
            or gebruiker.wachtwoord_hash is None
            or not verify_password(wachtwoord, gebruiker.wachtwoord_hash)
        ):
            faal_gebruiker_id = gebruiker.id
        else:
            creds = _actieve_credentials(session, gebruiker.id)
            # Een stub-credential telt alleen als "bekend apparaat" zolang de stub actief is —
            # anders zou de client een assertion proberen die nooit kan slagen.
            heeft = any(not c.is_dev_stub for c in creds) or (
                dev_stub_actief() and any(c.is_dev_stub for c in creds)
            )
            resultaat = AccordeurLoginResultaat(
                passkey_setup_token=create_passkey_setup_token(gebruiker.id), heeft_passkeys=heeft
            )
            record_audit_event(
                session,
                actor_id=gebruiker.id,
                module="platform",
                tabel="gebruiker",
                record_id=gebruiker.id,
                actie="accordeur_login_wachtwoord_ok",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=_login_metadata(ip_adres),
            )

    if faal_gebruiker_id is not None:
        with scoped_session(None, actor_id=faal_gebruiker_id) as log_session:
            record_audit_event(
                log_session,
                actor_id=faal_gebruiker_id,
                module="platform",
                tabel="gebruiker",
                record_id=faal_gebruiker_id,
                actie="login_mislukt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=_login_metadata(ip_adres),
            )

    if resultaat is None:
        raise AuthError(generic_error)
    return resultaat


def gebruiker_id_uit_passkey_setup(token: str) -> uuid.UUID:
    try:
        payload = decode_token(token, expected_type="passkey_setup")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    return uuid.UUID(payload["sub"])


# --- registratie (nieuw apparaat) -----------------------------------------------------------------


def _actieve_credentials(session: Session, gebruiker_id: uuid.UUID) -> list[WebauthnCredential]:
    return list(
        session.scalars(
            select(WebauthnCredential).where(
                WebauthnCredential.gebruiker_id == gebruiker_id,
                WebauthnCredential.ingetrokken_op.is_(None),
            )
        )
    )


def registratie_opties(*, gebruiker_id: uuid.UUID, alleen_platform_authenticator: bool = True) -> str:
    """PublicKeyCredentialCreationOptions (JSON) voor het registreren van dít apparaat.
    user_verification=REQUIRED: de biometrie-/pincodecheck van het OS is precies het punt van
    de cadans. Platform-authenticator (accordeur-default): de passkey hoort bij de telefoon
    zelf; kantoor-registratie (besluit 0020) zet dit uit — op een desktop zijn ook
    beveiligingssleutels en cross-device/QR-passkeys legitiem."""
    with scoped_session(None) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None:
            raise AuthError("Onbekende gebruiker")
        bestaande = _actieve_credentials(session, gebruiker_id)
        opties = generate_registration_options(
            rp_id=settings.webauthn_rp_id,
            rp_name=settings.webauthn_rp_naam,
            user_id=gebruiker_id.bytes,
            user_name=gebruiker.e_mail,
            user_display_name=gebruiker.naam,
            challenge=_maak_challenge(session, gebruiker_id=gebruiker_id, soort="registratie"),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=c.credential_id) for c in bestaande if not c.is_dev_stub
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM if alleen_platform_authenticator else None,
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
    return options_to_json(opties)


@dataclass(frozen=True)
class RegistratieResultaat:
    token_paar: TokenPaar
    apparaat_id: uuid.UUID


def _verifieer_en_bewaar_credential(
    session: Session, *, gebruiker_id: uuid.UUID, credential: dict, apparaat_naam: str | None
) -> WebauthnCredential:
    """Gedeelde registratie-kern (accordeur + kantoor): attestation verifiëren tegen de
    server-side challenge en de publieke sleutel per GEBRUIKER+APPARAAT opslaan."""
    verwachte_challenge = _verbruik_challenge(
        session,
        gebruiker_id=gebruiker_id,
        soort="registratie",
        challenge=_challenge_uit_client_data(credential),
    )
    try:
        verificatie = verify_registration_response(
            credential=credential,
            expected_challenge=verwachte_challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=list(settings.webauthn_origins),
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        raise AuthError(f"Passkey-registratie geweigerd: {exc}") from exc

    bestaat = session.scalars(
        select(WebauthnCredential).where(WebauthnCredential.credential_id == verificatie.credential_id)
    ).first()
    if bestaat is not None:
        raise AuthError("Deze passkey is al geregistreerd")

    rij = WebauthnCredential(
        id=uuid.uuid4(),
        gebruiker_id=gebruiker_id,
        credential_id=verificatie.credential_id,
        public_key=verificatie.credential_public_key,
        sign_count=verificatie.sign_count,
        aaguid=str(verificatie.aaguid) if verificatie.aaguid else None,
        transports=credential.get("response", {}).get("transports"),
        apparaat_naam=apparaat_naam,
        laatst_gebruikt_op=datetime.now(UTC),
    )
    session.add(rij)
    return rij


def voltooi_registratie(
    *, gebruiker_id: uuid.UUID, credential: dict, apparaat_naam: str | None, ip_adres: str | None = None
) -> RegistratieResultaat:
    """Verifieert de attestation, slaat de publieke sleutel per GEBRUIKER+APPARAAT op en geeft
    een apparaat-gebonden sessie uit. Een gebruiker in wacht_op_passkey (activeringsflow) wordt
    hier actief — de passkey ís de tweede factor."""
    with scoped_session(None, actor_id=gebruiker_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.status not in (GebruikerStatus.ACTIEF, GebruikerStatus.WACHT_OP_PASSKEY):
            raise AuthError("Account niet (meer) actief")
        rij = _verifieer_en_bewaar_credential(
            session, gebruiker_id=gebruiker_id, credential=credential, apparaat_naam=apparaat_naam
        )
        return _rond_registratie_af(session, gebruiker, rij, ip_adres=ip_adres)


def voltooi_registratie_stub(
    *, gebruiker_id: uuid.UUID, apparaat_naam: str | None, ip_adres: str | None = None
) -> RegistratieResultaat:
    """Dev-stub-registratie (zie moduledocstring): geen crypto, wel exact dezelfde flow en
    vastlegging — zichtbaar gemarkeerd met is_dev_stub. Hard geweigerd buiten dev/local."""
    if not dev_stub_actief():
        raise AuthError("Biometrie-dev-stub is niet actief")
    with scoped_session(None, actor_id=gebruiker_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.status not in (GebruikerStatus.ACTIEF, GebruikerStatus.WACHT_OP_PASSKEY):
            raise AuthError("Account niet (meer) actief")
        rij = WebauthnCredential(
            id=uuid.uuid4(),
            gebruiker_id=gebruiker_id,
            credential_id=secrets.token_bytes(16),
            public_key=b"dev-stub",
            sign_count=0,
            apparaat_naam=apparaat_naam,
            is_dev_stub=True,
            laatst_gebruikt_op=datetime.now(UTC),
        )
        session.add(rij)
        return _rond_registratie_af(session, gebruiker, rij, ip_adres=ip_adres)


def _rond_registratie_af(
    session: Session, gebruiker: Gebruiker, rij: WebauthnCredential, *, ip_adres: str | None
) -> RegistratieResultaat:
    if gebruiker.status == GebruikerStatus.WACHT_OP_PASSKEY:
        gebruiker.status = GebruikerStatus.ACTIEF
    record_audit_event(
        session,
        actor_id=gebruiker.id,
        module="platform",
        tabel="webauthn_credential",
        record_id=rij.id,
        actie="passkey_geregistreerd",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "apparaat_naam": rij.apparaat_naam,
            "is_dev_stub": rij.is_dev_stub,
            **(_login_metadata(ip_adres) or {}),
        },
    )
    paar = _issue_token_paar(session, gebruiker_id=gebruiker.id, rol=gebruiker.rol, apparaat_id=rij.id)
    return RegistratieResultaat(token_paar=paar, apparaat_id=rij.id)


# --- assertie (bekend apparaat: volledige login of app-opening/ontgrendelen) ----------------------


def assertie_opties(*, gebruiker_id: uuid.UUID) -> str:
    with scoped_session(None) as session:
        credentials = [c for c in _actieve_credentials(session, gebruiker_id) if not c.is_dev_stub]
        if not credentials:
            raise GeenPasskeys("Geen geregistreerde passkeys voor deze gebruiker")
        opties = generate_authentication_options(
            rp_id=settings.webauthn_rp_id,
            challenge=_maak_challenge(session, gebruiker_id=gebruiker_id, soort="assertie"),
            allow_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in credentials],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
    return options_to_json(opties)


def _voltooi_assertie(
    session: Session, *, gebruiker_id: uuid.UUID, credential: dict, ip_adres: str | None
) -> WebauthnCredential:
    """Verifieert de assertion tegen de opgeslagen publieke sleutel; werkt sign_count en
    laatst_gebruikt_op bij. Geeft de credential-rij terug (voor de apparaatbinding)."""
    try:
        raw_id = _b64url_decode(credential["rawId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("Ongeldige WebAuthn-response (rawId)") from exc

    rij = session.scalars(
        select(WebauthnCredential).where(WebauthnCredential.credential_id == raw_id).with_for_update()
    ).one_or_none()
    if rij is None or rij.gebruiker_id != gebruiker_id or rij.ingetrokken_op is not None:
        raise AuthError("Onbekende of ingetrokken passkey")

    verwachte_challenge = _verbruik_challenge(
        session, gebruiker_id=gebruiker_id, soort="assertie", challenge=_challenge_uit_client_data(credential)
    )
    try:
        verificatie = verify_authentication_response(
            credential=credential,
            expected_challenge=verwachte_challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=list(settings.webauthn_origins),
            credential_public_key=rij.public_key,
            credential_current_sign_count=rij.sign_count,
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as exc:
        raise AuthError(f"Passkey-verificatie geweigerd: {exc}") from exc

    rij.sign_count = verificatie.new_sign_count
    rij.laatst_gebruikt_op = datetime.now(UTC)
    record_audit_event(
        session,
        actor_id=gebruiker_id,
        module="platform",
        tabel="webauthn_credential",
        record_id=rij.id,
        actie="passkey_assertie_ok",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde=_login_metadata(ip_adres),
    )
    return rij


def _voltooi_assertie_stub(
    session: Session, *, gebruiker_id: uuid.UUID, ip_adres: str | None
) -> WebauthnCredential:
    if not dev_stub_actief():
        raise AuthError("Biometrie-dev-stub is niet actief")
    rij = session.scalars(
        select(WebauthnCredential)
        .where(
            WebauthnCredential.gebruiker_id == gebruiker_id,
            WebauthnCredential.is_dev_stub.is_(True),
            WebauthnCredential.ingetrokken_op.is_(None),
        )
        .order_by(WebauthnCredential.aangemaakt_op.desc())
    ).first()
    if rij is None:
        raise GeenPasskeys("Geen (stub-)apparaat geregistreerd")
    rij.laatst_gebruikt_op = datetime.now(UTC)
    record_audit_event(
        session,
        actor_id=gebruiker_id,
        module="platform",
        tabel="webauthn_credential",
        record_id=rij.id,
        actie="passkey_assertie_ok",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"is_dev_stub": True, **(_login_metadata(ip_adres) or {})},
    )
    return rij


def login_met_assertie(
    *, passkey_setup_token: str, credential: dict | None, dev_stub: bool = False, ip_adres: str | None = None
) -> TokenPaar:
    """Volledige login op een bekend apparaat (ná 7 dagen inactiviteit): wachtwoordstap gaf het
    passkey_setup-token, de assertion is de tweede factor. Geeft een verse apparaat-gebonden
    sessie uit."""
    gebruiker_id = gebruiker_id_uit_passkey_setup(passkey_setup_token)
    with scoped_session(None, actor_id=gebruiker_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
            raise AuthError("Account niet (meer) actief")
        if dev_stub:
            rij = _voltooi_assertie_stub(session, gebruiker_id=gebruiker_id, ip_adres=ip_adres)
        else:
            if credential is None:
                raise AuthError("WebAuthn-response ontbreekt")
            rij = _voltooi_assertie(session, gebruiker_id=gebruiker_id, credential=credential, ip_adres=ip_adres)
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="gebruiker",
            record_id=gebruiker_id,
            actie="login_geslaagd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=_login_metadata(ip_adres),
        )
        return _issue_token_paar(session, gebruiker_id=gebruiker_id, rol=gebruiker.rol, apparaat_id=rij.id)


def gebruiker_id_uit_geldig_refresh_token(refresh_token: str) -> uuid.UUID:
    """Voor het ontgrendel-scherm (app-opening): wie hoort bij deze nog-geldige refresh-cookie?
    Bewust ZONDER rotatie — de rotatie gebeurt pas bij het afronden van de ontgrendeling
    (service.vernieuw_token), anders zou het openen van het scherm alleen al de sessie muteren."""
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    gebruiker_id = uuid.UUID(payload["sub"])
    token_hash = _hash_token(refresh_token)
    with scoped_session(None) as session:
        rij = session.scalars(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).one_or_none()
        now = datetime.now(UTC)
        if (
            rij is None
            or rij.gebruikt_op is not None
            or rij.ingetrokken_op is not None
            or rij.verloopt_op < now
        ):
            raise AuthError("Sessie verlopen — log opnieuw in")
    return gebruiker_id


def ontgrendel_assertie(
    *, refresh_token: str, credential: dict | None, dev_stub: bool = False, ip_adres: str | None = None
) -> None:
    """Verifieert de app-opening-assertion (éénmaal per opening, besluit 2026-08-11). De
    aanroeper (router) rotereert daarná de refresh-cookie via service.vernieuw_token — de
    bestaande race-tolerante rotatie blijft de enige rotatieroute."""
    gebruiker_id = gebruiker_id_uit_geldig_refresh_token(refresh_token)
    with scoped_session(None, actor_id=gebruiker_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
            raise AuthError("Account niet (meer) actief")
        if dev_stub:
            _voltooi_assertie_stub(session, gebruiker_id=gebruiker_id, ip_adres=ip_adres)
        else:
            if credential is None:
                raise AuthError("WebAuthn-response ontbreekt")
            _voltooi_assertie(session, gebruiker_id=gebruiker_id, credential=credential, ip_adres=ip_adres)


# --- kantoor-passkeys (platformbesluit 0020: passkeys eerste lijn, wachtwoord+TOTP terugval) ------
#
# Tweede afnemer van de accordeur-bouwstenen (migratie 0040) — géén nieuw auth-systeem: zelfde
# credential-/challenge-tabellen, zelfde kill-switch-lagen, zelfde dev-stub-vergrendeling. De
# verschillen zijn bewust klein: (1) registratie gebeurt ín een bestaande sessie (ná TOTP-login,
# Instellingen → beveiliging) en geeft dus géén nieuw token-paar uit; (2) de passkey-login is
# één stap (assertion mét user verification = bezit + biometrie/pincode — de wachtwoordstap van
# de accordeur-flow vervalt, wachtwoord+TOTP blijft het volwaardige terugvalpad); (3) de
# sessiesemantiek blijft de bestaande kantoor-JWT (standaard refresh-TTL, geen 7-dagen-cadans,
# geen ontgrendel-assertion per app-opening) — de passkey vervangt alléén de inlogstap.


def _is_kantoorrol(rol: GebruikerRol) -> bool:
    """Kantoor = elke rol behalve klant-accordeur; accordeurs houden hun eigen flow (wachtwoord +
    passkey, 7-dagen-cadans) en mogen de éénstaps-kantoor-login niet gebruiken — dat zou hun
    wachtwoordstap omzeilen."""
    return rol != GebruikerRol.KLANT_ACCORDEUR


def voltooi_kantoor_registratie(
    *,
    gebruiker_id: uuid.UUID,
    credential: dict | None,
    apparaat_naam: str | None,
    dev_stub: bool = False,
    ip_adres: str | None = None,
) -> ApparaatData:
    """Registratie vanaf Instellingen → beveiliging (ingelogde kantoorgebruiker): credential
    opslaan + audit, maar GEEN nieuw token-paar — de lopende sessie blijft gewoon staan. De
    passkey gaat pas een sessie dragen bij de eerstvolgende passkey-login."""
    with scoped_session(None, actor_id=gebruiker_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
            raise AuthError("Account niet (meer) actief")
        if not _is_kantoorrol(gebruiker.rol):
            raise AuthError("Alleen voor kantoor-rollen — accordeurs registreren via de goedkeur-app")
        if dev_stub:
            if not dev_stub_actief():
                raise AuthError("Biometrie-dev-stub is niet actief")
            rij = WebauthnCredential(
                id=uuid.uuid4(),
                gebruiker_id=gebruiker_id,
                credential_id=secrets.token_bytes(16),
                public_key=b"dev-stub",
                sign_count=0,
                apparaat_naam=apparaat_naam,
                is_dev_stub=True,
                laatst_gebruikt_op=datetime.now(UTC),
            )
            session.add(rij)
        else:
            if credential is None:
                raise AuthError("WebAuthn-response ontbreekt")
            rij = _verifieer_en_bewaar_credential(
                session, gebruiker_id=gebruiker_id, credential=credential, apparaat_naam=apparaat_naam
            )
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="webauthn_credential",
            record_id=rij.id,
            actie="passkey_geregistreerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "apparaat_naam": rij.apparaat_naam,
                "is_dev_stub": rij.is_dev_stub,
                **(_login_metadata(ip_adres) or {}),
            },
        )
        session.flush()
        session.refresh(rij)  # aangemaakt_op komt uit de server_default
        return ApparaatData(
            id=rij.id,
            apparaat_naam=rij.apparaat_naam,
            is_dev_stub=rij.is_dev_stub,
            aangemaakt_op=rij.aangemaakt_op,
            laatst_gebruikt_op=rij.laatst_gebruikt_op,
            ingetrokken_op=rij.ingetrokken_op,
        )


@dataclass(frozen=True)
class KantoorLoginOpties:
    # opties=None kan alleen samen met dev_stub=True: er is geen echte passkey maar wél een
    # stub-credential in een actieve dev-stub-omgeving — de client rondt dan af met dev_stub.
    opties: str | None
    dev_stub: bool


def kantoor_login_opties(*, e_mail: str) -> KantoorLoginOpties:
    """Eerste lijn van de kantoor-login (besluit 0020): assertion-options op e-mailadres —
    usernameless mag niet (0022/0006-lijn), de gebruikersnaam blijft het startpunt. GeenPasskeys
    is bewust het ENIGE onderscheidbare faalpad: een onbekend adres, een accordeur, een
    niet-actieve gebruiker en een passkey-loze kantoorgebruiker antwoorden identiek — dit
    endpoint geeft dus alleen prijs "dit adres heeft een bruikbare kantoor-passkey", nooit of
    een account bestaat. De client valt bij GeenPasskeys terug op wachtwoord + TOTP (het
    ongewijzigde /auth/login-pad)."""
    e_mail = normaliseer_e_mail(e_mail)
    generieke_fout = "Geen passkey voor dit adres — log in met wachtwoord + TOTP"
    with scoped_session(None) as session:
        gebruiker = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail)).one_or_none()
        if (
            gebruiker is None
            or not _is_kantoorrol(gebruiker.rol)
            or gebruiker.status != GebruikerStatus.ACTIEF
        ):
            raise GeenPasskeys(generieke_fout)
        alle = _actieve_credentials(session, gebruiker.id)
        echte = [c for c in alle if not c.is_dev_stub]
        stub_beschikbaar = dev_stub_actief() and any(c.is_dev_stub for c in alle)
        if not echte:
            if stub_beschikbaar:
                return KantoorLoginOpties(opties=None, dev_stub=True)
            raise GeenPasskeys(generieke_fout)
        opties = generate_authentication_options(
            rp_id=settings.webauthn_rp_id,
            challenge=_maak_challenge(session, gebruiker_id=gebruiker.id, soort="assertie"),
            allow_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in echte],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
    return KantoorLoginOpties(opties=options_to_json(opties), dev_stub=stub_beschikbaar)


def login_met_kantoor_passkey(
    *, e_mail: str, credential: dict | None, dev_stub: bool = False, ip_adres: str | None = None
) -> TokenPaar:
    """Volledige kantoor-login in één stap: de assertion mét verplichte user verification is
    bezit + biometrie/pincode (twee factoren). Zelfde generieke fout als service.login() —
    geen account-enumeratie. De uitgegeven sessie volgt de bestaande kantoor-JWT-semantiek
    (standaard refresh-TTL via _refresh_ttl_voor), alleen nu apparaat-gebonden: de
    kill-switch bijt per request (deps) én bij elke rotatie."""
    generic_error = "Ongeldige inloggegevens"
    e_mail = normaliseer_e_mail(e_mail)
    faal_gebruiker_id: uuid.UUID | None = None
    paar: TokenPaar | None = None

    with scoped_session(None) as session:
        gebruiker = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail)).one_or_none()
        if gebruiker is None:
            pass
        elif not _is_kantoorrol(gebruiker.rol) or gebruiker.status != GebruikerStatus.ACTIEF:
            faal_gebruiker_id = gebruiker.id
        else:
            if dev_stub:
                rij = _voltooi_assertie_stub(session, gebruiker_id=gebruiker.id, ip_adres=ip_adres)
            else:
                if credential is None:
                    raise AuthError("WebAuthn-response ontbreekt")
                rij = _voltooi_assertie(
                    session, gebruiker_id=gebruiker.id, credential=credential, ip_adres=ip_adres
                )
            record_audit_event(
                session,
                actor_id=gebruiker.id,
                module="platform",
                tabel="gebruiker",
                record_id=gebruiker.id,
                actie="login_geslaagd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=_login_metadata(ip_adres),
            )
            paar = _issue_token_paar(session, gebruiker_id=gebruiker.id, rol=gebruiker.rol, apparaat_id=rij.id)

    # Zelfde patroon als service.login(): het faal-audit-event in een eigen, ná de hoofdtransactie
    # gestarte transactie — een raise binnen het with-blok zou de audit-rij mee terugrollen.
    if faal_gebruiker_id is not None:
        with scoped_session(None, actor_id=faal_gebruiker_id) as log_session:
            record_audit_event(
                log_session,
                actor_id=faal_gebruiker_id,
                module="platform",
                tabel="gebruiker",
                record_id=faal_gebruiker_id,
                actie="login_mislukt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=_login_metadata(ip_adres),
            )

    if paar is None:
        raise AuthError(generic_error)
    return paar


# --- apparaatbeheer / kill-switch -----------------------------------------------------------------


@dataclass(frozen=True)
class ApparaatData:
    id: uuid.UUID
    apparaat_naam: str | None
    is_dev_stub: bool
    aangemaakt_op: datetime
    laatst_gebruikt_op: datetime | None
    ingetrokken_op: datetime | None


def apparaten_van(*, gebruiker_id: uuid.UUID) -> list[ApparaatData]:
    with scoped_session(None) as session:
        rijen = session.scalars(
            select(WebauthnCredential)
            .where(WebauthnCredential.gebruiker_id == gebruiker_id)
            .order_by(WebauthnCredential.aangemaakt_op.desc())
        ).all()
        return [
            ApparaatData(
                id=r.id,
                apparaat_naam=r.apparaat_naam,
                is_dev_stub=r.is_dev_stub,
                aangemaakt_op=r.aangemaakt_op,
                laatst_gebruikt_op=r.laatst_gebruikt_op,
                ingetrokken_op=r.ingetrokken_op,
            )
            for r in rijen
        ]


def trek_apparaat_in(
    *, actor_id: uuid.UUID, apparaat_id: uuid.UUID, alleen_van_gebruiker: uuid.UUID | None = None
) -> None:
    """Kill-switch: trekt de passkey-credential én alle eraan gebonden actieve refresh-tokens
    in — het apparaat valt binnen de access-TTL óók per request uit (deps toetst de
    apparaat-claim). Idempotent op een al-ingetrokken apparaat. `alleen_van_gebruiker`
    (kantoor-passkeys 0020): niet-Beheerders mogen uitsluitend hun éigen apparaten intrekken —
    een niet-eigen apparaat antwoordt als "onbekend" (zelfde fout, geen bestaans-lek)."""
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(WebauthnCredential, apparaat_id)
        if rij is None or (alleen_van_gebruiker is not None and rij.gebruiker_id != alleen_van_gebruiker):
            raise AuthError("Onbekend apparaat")
        if rij.ingetrokken_op is not None:
            return
        now = datetime.now(UTC)
        rij.ingetrokken_op = now
        rij.ingetrokken_door = actor_id
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.apparaat_id == apparaat_id, RefreshToken.ingetrokken_op.is_(None))
            .values(ingetrokken_op=now)
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="webauthn_credential",
            record_id=apparaat_id,
            actie="apparaat_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"ingetrokken_op": None},
            nieuwe_waarde={
                "gebruiker_id": str(rij.gebruiker_id),
                "apparaat_naam": rij.apparaat_naam,
                "ingetrokken_op": now.isoformat(),
            },
        )


@dataclass(frozen=True)
class KantoorApparaatData(ApparaatData):
    gebruiker_id: uuid.UUID
    gebruiker_naam: str


def kantoor_apparaten() -> list[KantoorApparaatData]:
    """Alle passkey-apparaten van kantoor-rollen, mét gebruikersnaam (Beheerder-only via de
    router) — het beheerder-overzicht op Instellingen → beveiliging; accordeur-apparaten hebben
    hun eigen overzicht per administratie (AccorderingInstellingen)."""
    with scoped_session(None) as session:
        rijen = session.execute(
            select(WebauthnCredential, Gebruiker.naam)
            .join(Gebruiker, Gebruiker.id == WebauthnCredential.gebruiker_id)
            .where(Gebruiker.rol != GebruikerRol.KLANT_ACCORDEUR)
            .order_by(Gebruiker.naam, WebauthnCredential.aangemaakt_op.desc())
        ).all()
        return [
            KantoorApparaatData(
                id=r.id,
                apparaat_naam=r.apparaat_naam,
                is_dev_stub=r.is_dev_stub,
                aangemaakt_op=r.aangemaakt_op,
                laatst_gebruikt_op=r.laatst_gebruikt_op,
                ingetrokken_op=r.ingetrokken_op,
                gebruiker_id=r.gebruiker_id,
                gebruiker_naam=naam,
            )
            for r, naam in rijen
        ]


def is_apparaat_ingetrokken(apparaat_id: uuid.UUID) -> bool:
    """Per-request kill-switch-toets (deps.get_current_gebruiker) voor access-tokens met een
    apparaat-claim — zelfde principe als de rol/status-hertoets per request."""
    with scoped_session(None) as session:
        rij = session.get(WebauthnCredential, apparaat_id)
        return rij is None or rij.ingetrokken_op is not None
