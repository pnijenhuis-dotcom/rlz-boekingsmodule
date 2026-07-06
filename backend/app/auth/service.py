from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Gebruiker, GebruikerAdministratie, GebruikerRol, GebruikerStatus, TotpSecret, Uitnodiging
from app.db.session import scoped_session
from app.security.envelope import unwrap_secret, wrap_secret
from app.security.passwords import hash_password, verify_password
from app.security.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    create_totp_setup_token,
    decode_token,
)
from app.security.totp import build_otpauth_uri, generate_secret, verify_code

INVITE_TTL = timedelta(hours=72)
MIN_WACHTWOORD_LENGTE = 12


class AuthError(Exception):
    """Domeinfout in de auth-flow. De reden is hier expliciet (niet generiek) zodat tests scherp
    kunnen assert-en; de router vertaalt dit naar de HTTP-respons en houdt inlog-/TOTP-fouten
    bewust generiek naar de client toe, om account-/2FA-status-enumeratie te voorkomen."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class UitnodigingResultaat:
    uitnodiging_id: uuid.UUID
    gebruiker_id: uuid.UUID
    token: str
    verloopt_op: datetime


def maak_uitnodiging(
    *,
    actor_id: uuid.UUID,
    naam: str,
    e_mail: str,
    rol: GebruikerRol,
    administratie_ids: list[uuid.UUID],
) -> UitnodigingResultaat:
    """Beheerder-only (afgedwongen door de router-dependency, niet hier — zie deps.require_beheerder).
    Genereert een eenmalig token; alleen de hash ervan wordt opgeslagen (zie Uitnodiging)."""
    gebruiker_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)
    verloopt_op = datetime.now(UTC) + INVITE_TTL

    with scoped_session(None, actor_id=actor_id) as session:
        session.add(Gebruiker(id=gebruiker_id, naam=naam, e_mail=e_mail, rol=rol, status=GebruikerStatus.UITGENODIGD))
        session.flush()
        for administratie_id in administratie_ids:
            session.add(GebruikerAdministratie(gebruiker_id=gebruiker_id, administratie_id=administratie_id))
        uitnodiging_id = uuid.uuid4()
        session.add(
            Uitnodiging(
                id=uitnodiging_id,
                gebruiker_id=gebruiker_id,
                token_hash=_hash_token(token),
                aangemaakt_door=actor_id,
                verloopt_op=verloopt_op,
            )
        )

    return UitnodigingResultaat(
        uitnodiging_id=uitnodiging_id, gebruiker_id=gebruiker_id, token=token, verloopt_op=verloopt_op
    )


@dataclass(frozen=True)
class AcceptatieResultaat:
    totp_setup_token: str
    otpauth_uri: str
    secret: str


def accepteer_uitnodiging(*, token: str, wachtwoord: str) -> AcceptatieResultaat:
    """Token -> wachtwoord zetten -> TOTP-secret genereren (nog niet bevestigd). Activatie volgt
    pas na bevestig_totp(). Het token is hierna altijd verbruikt, ook als een latere stap
    (TOTP-bevestiging) faalt — een mislukte enrollment betekent een nieuwe uitnodiging, geen
    herbruikbaar token (consistent met "eenmalig")."""
    if len(wachtwoord) < MIN_WACHTWOORD_LENGTE:
        raise AuthError(f"Wachtwoord moet minimaal {MIN_WACHTWOORD_LENGTE} tekens zijn")

    token_hash = _hash_token(token)
    now = datetime.now(UTC)

    with scoped_session(None) as session:
        uitnodiging = session.scalars(select(Uitnodiging).where(Uitnodiging.token_hash == token_hash)).one_or_none()
        if uitnodiging is None:
            raise AuthError("Ongeldig uitnodigingstoken")
        if uitnodiging.gebruikt_op is not None:
            raise AuthError("Uitnodiging is al gebruikt")
        if uitnodiging.verloopt_op < now:
            raise AuthError("Uitnodiging is verlopen")

        gebruiker = session.get(Gebruiker, uitnodiging.gebruiker_id)
        assert gebruiker is not None  # FK garandeert dit

        gebruiker.wachtwoord_hash = hash_password(wachtwoord)
        gebruiker.status = GebruikerStatus.WACHT_OP_TOTP
        uitnodiging.gebruikt_op = now

        secret = generate_secret()
        ciphertext, wrapped_key = wrap_secret(secret.encode())
        session.add(
            TotpSecret(gebruiker_id=gebruiker.id, secret_ciphertext=ciphertext, wrapped_data_key=wrapped_key)
        )
        e_mail = gebruiker.e_mail
        gebruiker_id = gebruiker.id

    return AcceptatieResultaat(
        totp_setup_token=create_totp_setup_token(gebruiker_id),
        otpauth_uri=build_otpauth_uri(secret, account_name=e_mail),
        secret=secret,
    )


@dataclass(frozen=True)
class TokenPaar:
    access_token: str
    refresh_token: str


def bevestig_totp(*, totp_setup_token: str, code: str) -> TokenPaar:
    """Activatie-gate: pas na een geslaagde verificatie wordt de gebruiker Actief. Het
    totp_setup-token is eenmalig van aard: een tweede aanroep faalt omdat bevestigd_op al gezet is."""
    try:
        payload = decode_token(totp_setup_token, expected_type="totp_setup")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    gebruiker_id = uuid.UUID(payload["sub"])

    with scoped_session(None) as session:
        totp_row = session.get(TotpSecret, gebruiker_id)
        if totp_row is None or totp_row.bevestigd_op is not None:
            raise AuthError("Geen openstaande TOTP-enrollment voor deze gebruiker")

        secret = unwrap_secret(totp_row.secret_ciphertext, totp_row.wrapped_data_key).decode()
        matched_step = verify_code(secret, code, last_accepted_step=totp_row.laatste_stap)
        if matched_step is None:
            raise AuthError("Ongeldige TOTP-code")

        totp_row.laatste_stap = matched_step
        totp_row.bevestigd_op = datetime.now(UTC)

        gebruiker = session.get(Gebruiker, gebruiker_id)
        assert gebruiker is not None
        gebruiker.status = GebruikerStatus.ACTIEF
        rol = gebruiker.rol

    return TokenPaar(
        access_token=create_access_token(gebruiker_id, rol=rol.value),
        refresh_token=create_refresh_token(gebruiker_id),
    )


def login(*, e_mail: str, wachtwoord: str, totp_code: str) -> TokenPaar:
    """Bewust dezelfde generieke fout voor onbekend e-mailadres/verkeerd wachtwoord/verkeerde
    TOTP-code — anders lekt de foutmelding zelf of een account bestaat, actief is, of al
    TOTP-enrolled is (account-/2FA-enumeratie)."""
    generic_error = "Ongeldige inloggegevens"

    with scoped_session(None) as session:
        gebruiker = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail)).one_or_none()
        if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF or gebruiker.wachtwoord_hash is None:
            raise AuthError(generic_error)
        if not verify_password(wachtwoord, gebruiker.wachtwoord_hash):
            raise AuthError(generic_error)

        totp_row = session.get(TotpSecret, gebruiker.id)
        if totp_row is None or totp_row.bevestigd_op is None:
            raise AuthError(generic_error)
        secret = unwrap_secret(totp_row.secret_ciphertext, totp_row.wrapped_data_key).decode()
        matched_step = verify_code(secret, totp_code, last_accepted_step=totp_row.laatste_stap)
        if matched_step is None:
            raise AuthError(generic_error)
        totp_row.laatste_stap = matched_step

        gebruiker_id = gebruiker.id
        rol = gebruiker.rol

    return TokenPaar(
        access_token=create_access_token(gebruiker_id, rol=rol.value),
        refresh_token=create_refresh_token(gebruiker_id),
    )


def vernieuw_token(*, refresh_token: str) -> TokenPaar:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    gebruiker_id = uuid.UUID(payload["sub"])

    with scoped_session(None) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
            raise AuthError("Account niet (meer) actief")
        rol = gebruiker.rol

    return TokenPaar(
        access_token=create_access_token(gebruiker_id, rol=rol.value),
        refresh_token=create_refresh_token(gebruiker_id),
    )


def wijzig_rol(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, nieuwe_rol: GebruikerRol) -> None:
    """Hard (CLAUDE.md): niemand muteert zijn eigen rol, ook een Beheerder niet. Beheerder-only
    afgedwongen door de router-dependency; hier alleen de self-mutation-check, want die geldt
    onvoorwaardelijk — ook als een toekomstige aanroeper deze functie ooit los aanroept."""
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan de eigen rol niet wijzigen")
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None:
            raise AuthError("Onbekende gebruiker")
        gebruiker.rol = nieuwe_rol


def voeg_scope_toe(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan de eigen scope niet wijzigen")
    with scoped_session(None, actor_id=actor_id) as session:
        bestaat_al = session.get(GebruikerAdministratie, (doel_gebruiker_id, administratie_id))
        if bestaat_al is None:
            session.add(GebruikerAdministratie(gebruiker_id=doel_gebruiker_id, administratie_id=administratie_id))


def verwijder_scope(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan de eigen scope niet wijzigen")
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(GebruikerAdministratie, (doel_gebruiker_id, administratie_id))
        if rij is not None:
            session.delete(rij)
