from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import (
    Administratie,
    Gebruiker,
    GebruikerAdministratie,
    GebruikerRol,
    GebruikerStatus,
    RefreshToken,
    TotpSecret,
    Uitnodiging,
)
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


def _login_metadata(ip_adres: str | None) -> dict[str, str] | None:
    """IP is uitsluitend anomalie-metadata (Auth-0010-b) — nooit een auth-anker. Alleen
    opgenomen in het audit-record zelf, nooit gebruikt om een login/sessie te (dis)kwalificeren."""
    return {"ip": ip_adres} if ip_adres else None


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


def _issue_token_paar(
    session: Session, *, gebruiker_id: uuid.UUID, rol: GebruikerRol, voorganger_id: uuid.UUID | None = None
) -> TokenPaar:
    """Enige plek die een refresh-token uitgeeft: naast het JWT ook de bijbehorende hash
    vastleggen in `refresh_token`, anders is rotatie/hergebruik-detectie niet mogelijk voor dit
    token. `voorganger_id` legt de rotatieketen vast (None bij een verse login/activatie)."""
    access_token = create_access_token(gebruiker_id, rol=rol.value)
    refresh_token = create_refresh_token(gebruiker_id)
    session.add(
        RefreshToken(
            id=uuid.uuid4(),
            gebruiker_id=gebruiker_id,
            token_hash=_hash_token(refresh_token),
            voorganger_id=voorganger_id,
            verloopt_op=datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
        )
    )
    return TokenPaar(access_token=access_token, refresh_token=refresh_token)


def _intrek_alle_sessies(session: Session, gebruiker_id: uuid.UUID, *, now: datetime) -> None:
    """Hergebruik-detectie (Auth-0010-b): een al-geroteerd of al-ingetrokken refresh-token dat
    opnieuw wordt aangeboden, wijst op een gestolen/gelekt token — trek voor de zekerheid ALLE
    actieve refresh-tokens van deze gebruiker in, niet alleen de ene sessie die zich meldde."""
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.gebruiker_id == gebruiker_id, RefreshToken.ingetrokken_op.is_(None))
        .values(ingetrokken_op=now)
    )


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
        paar = _issue_token_paar(session, gebruiker_id=gebruiker_id, rol=gebruiker.rol)

    return paar


def login(*, e_mail: str, wachtwoord: str, totp_code: str, ip_adres: str | None = None) -> TokenPaar:
    """Bewust dezelfde generieke fout voor onbekend e-mailadres/verkeerd wachtwoord/verkeerde
    TOTP-code — anders lekt de foutmelding zelf of een account bestaat, actief is, of al
    TOTP-enrolled is (account-/2FA-enumeratie).

    Login-events (geslaagd/mislukt/TOTP-mislukt) gaan naar audit_event (Auth-0010-b punt 2). Bij
    een onbekend e-mailadres is er geen platform.gebruiker-rij om aan te koppelen (actor_id is
    NOT NULL) — daar wordt bewust geen audit-rij voor geschreven; er is geen entiteit om over te
    rapporteren. Faalpaden loggen we via een APARTE, ná deze functie gestarte transactie: deze
    hoofdtransactie faalt hier nooit hard (raise gebeurt pas na de `with`-blok), want
    `scoped_session` rolt bij een exception de hele transactie terug — inclusief een audit-schrijving
    die er middenin zou staan."""
    generic_error = "Ongeldige inloggegevens"
    faal_actie: str | None = None
    faal_gebruiker_id: uuid.UUID | None = None
    paar: TokenPaar | None = None

    with scoped_session(None) as session:
        gebruiker = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail)).one_or_none()
        if gebruiker is None:
            pass
        elif (
            gebruiker.status != GebruikerStatus.ACTIEF
            or gebruiker.wachtwoord_hash is None
            or not verify_password(wachtwoord, gebruiker.wachtwoord_hash)
        ):
            faal_actie, faal_gebruiker_id = "login_mislukt", gebruiker.id
        else:
            totp_row = session.get(TotpSecret, gebruiker.id)
            if totp_row is None or totp_row.bevestigd_op is None:
                faal_actie, faal_gebruiker_id = "login_mislukt", gebruiker.id
            else:
                secret = unwrap_secret(totp_row.secret_ciphertext, totp_row.wrapped_data_key).decode()
                matched_step = verify_code(secret, totp_code, last_accepted_step=totp_row.laatste_stap)
                if matched_step is None:
                    faal_actie, faal_gebruiker_id = "totp_mislukt", gebruiker.id
                else:
                    totp_row.laatste_stap = matched_step
                    paar = _issue_token_paar(session, gebruiker_id=gebruiker.id, rol=gebruiker.rol)
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

    if faal_actie is not None and faal_gebruiker_id is not None:
        with scoped_session(None, actor_id=faal_gebruiker_id) as log_session:
            record_audit_event(
                log_session,
                actor_id=faal_gebruiker_id,
                module="platform",
                tabel="gebruiker",
                record_id=faal_gebruiker_id,
                actie=faal_actie,
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=_login_metadata(ip_adres),
            )

    if paar is None:
        raise AuthError(generic_error)
    return paar


def vernieuw_token(*, refresh_token: str, ip_adres: str | None = None) -> TokenPaar:
    """Rotatie bij elke aanroep (Auth-0010-b punt 1): het aangeboden token wordt verbruikt-
    gemarkeerd en vervangen door een nieuwe. Wordt hetzelfde token een tweede keer aangeboden
    (gebruikt_op of ingetrokken_op al gezet), dan is dat hergebruik van een gestolen/gelekt token
    — alle actieve sessies van de gebruiker worden dan preventief ingetrokken.

    Zelfde reden als in login(): de revoke-all + audit-schrijving bij hergebruik mogen niet
    verloren gaan doordat deze functie voor de aanroeper een fout meldt — dus wordt hier nooit
    binnen de `with`-transactie ge-raised; de uitkomst wordt na het blok (dat altijd commit't)
    omgezet in een AuthError."""
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    gebruiker_id = uuid.UUID(payload["sub"])
    token_hash = _hash_token(refresh_token)
    now = datetime.now(UTC)

    faal_reden: str | None = None
    paar: TokenPaar | None = None

    with scoped_session(None) as session:
        rij = session.scalars(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).one_or_none()
        if rij is None:
            faal_reden = "onbekend"
        elif rij.gebruikt_op is not None or rij.ingetrokken_op is not None:
            _intrek_alle_sessies(session, gebruiker_id, now=now)
            record_audit_event(
                session,
                actor_id=gebruiker_id,
                module="platform",
                tabel="refresh_token",
                record_id=rij.id,
                actie="refresh_token_hergebruik_gedetecteerd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=_login_metadata(ip_adres),
            )
            faal_reden = "hergebruik"
        elif rij.verloopt_op < now:
            faal_reden = "verlopen"
        else:
            gebruiker = session.get(Gebruiker, gebruiker_id)
            if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
                faal_reden = "inactief"
            else:
                rij.gebruikt_op = now
                paar = _issue_token_paar(session, gebruiker_id=gebruiker_id, rol=gebruiker.rol, voorganger_id=rij.id)

    if paar is None:
        foutmeldingen = {
            "onbekend": "Ongeldig refresh-token",
            "hergebruik": "Refresh-token al gebruikt — alle sessies zijn ter voorzorg beëindigd",
            "verlopen": "Refresh-token verlopen",
            "inactief": "Account niet (meer) actief",
        }
        raise AuthError(foutmeldingen.get(faal_reden, "Ongeldig refresh-token"))
    return paar


def logout(*, refresh_token: str) -> None:
    """Trekt uitsluitend het aangeboden refresh-token in — andere sessies/apparaten van de
    gebruiker blijven actief. Idempotent en stil bij een onbekend/verlopen/al-ingetrokken token:
    een client die twee keer uitlogt (of een verlopen sessie) hoeft geen foutmelding te zien, en
    er valt dan ook niets meer in te trekken."""
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError:
        return
    gebruiker_id = uuid.UUID(payload["sub"])
    token_hash = _hash_token(refresh_token)

    with scoped_session(None, actor_id=gebruiker_id) as session:
        rij = session.scalars(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).one_or_none()
        if rij is None or rij.ingetrokken_op is not None:
            return
        rij.ingetrokken_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="refresh_token",
            record_id=rij.id,
            actie="logout",
            correlatie_id=uuid.uuid4(),
        )


def logout_overal(*, gebruiker_id: uuid.UUID) -> None:
    """Trekt ALLE actieve refresh-tokens van de gebruiker in (elke ingelogde sessie/apparaat) —
    zelfde intrek-mechanisme als hergebruik-detectie, hier bewust door de gebruiker zelf
    geïnitieerd."""
    with scoped_session(None, actor_id=gebruiker_id) as session:
        _intrek_alle_sessies(session, gebruiker_id, now=datetime.now(UTC))
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="gebruiker",
            record_id=gebruiker_id,
            actie="logout_overal",
            correlatie_id=uuid.uuid4(),
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


@dataclass(frozen=True)
class BootstrapResultaat:
    gebruiker_id: uuid.UUID
    token: str
    verloopt_op: datetime


def bootstrap_eerste_beheerder(*, naam: str, e_mail: str) -> BootstrapResultaat:
    """Doorbreekt het kip-ei-probleem van de uitnodigingsflow (Beheerder-only, zie
    deps.require_beheerder) — zonder dit commando is er geen manier om de allereerste Beheerder
    aan te maken. Idempotent: weigert zodra er al één Beheerder-rol bestaat, ongeacht diens
    status. Maakt, net als een normale uitnodiging, alleen de gebruiker + een eenmalig
    uitnodigingstoken aan; wachtwoord en TOTP lopen via de bestaande
    accepteer_uitnodiging()/bevestig_totp()-flow — geen aparte activatieroute om te onderhouden.

    Schrijft zelf een audit_event: de rol-wijzigingstrigger (migratie 0002) vuurt alleen op
    UPDATE van een bestaande rij, niet op deze allereerste INSERT."""
    with scoped_session(None) as session:
        bestaat_al = session.scalars(select(Gebruiker.id).where(Gebruiker.rol == GebruikerRol.BEHEERDER)).first()
        if bestaat_al is not None:
            raise AuthError("Er bestaat al een Beheerder — dit commando is eenmalig.")

        gebruiker_id = uuid.uuid4()
        session.add(
            Gebruiker(
                id=gebruiker_id,
                naam=naam,
                e_mail=e_mail,
                rol=GebruikerRol.BEHEERDER,
                status=GebruikerStatus.UITGENODIGD,
            )
        )
        session.flush()

        token = secrets.token_urlsafe(32)
        verloopt_op = datetime.now(UTC) + INVITE_TTL
        session.add(
            Uitnodiging(
                id=uuid.uuid4(),
                gebruiker_id=gebruiker_id,
                token_hash=_hash_token(token),
                aangemaakt_door=gebruiker_id,
                verloopt_op=verloopt_op,
            )
        )
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="gebruiker",
            record_id=gebruiker_id,
            actie="eerste_beheerder_bootstrapped",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"rol": GebruikerRol.BEHEERDER.value},
        )

    return BootstrapResultaat(gebruiker_id=gebruiker_id, token=token, verloopt_op=verloopt_op)


def mijn_administraties(*, actor_id: uuid.UUID, rol: GebruikerRol) -> list[Administratie]:
    """Beheerder ziet alles (platform-breed); iedereen anders alleen de eigen
    gebruiker_administratie-koppelingen. Vereist migratie 0007: de RLS-policy op
    gebruiker_administratie staat sinds die migratie ook 'lees je eigen rijen' toe
    (gebruiker_id = current_actor_id()), naast de bestaande scope-/beheerder-voorwaarden —
    zonder die uitbreiding zou een niet-Beheerder hier altijd een lege lijst krijgen, want een
    sessie is maar op één administratie tegelijk gescoped."""
    with scoped_session(None, actor_id=actor_id) as session:
        if rol == GebruikerRol.BEHEERDER:
            return list(session.scalars(select(Administratie).order_by(Administratie.naam)))
        rijen = session.scalars(
            select(Administratie)
            .join(GebruikerAdministratie, GebruikerAdministratie.administratie_id == Administratie.id)
            .where(GebruikerAdministratie.gebruiker_id == actor_id)
            .order_by(Administratie.naam)
        )
        return list(rijen)
