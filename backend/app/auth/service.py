from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.normalisatie import normaliseer_e_mail
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
    WebauthnCredential,
)
from app.db.session import scoped_session
from app.security.envelope import unwrap_secret, wrap_secret
from app.security.passwords import hash_password, verify_password
from app.security.tokens import (
    TokenError,
    create_access_token,
    create_passkey_setup_token,
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


class RotatieBezetError(Exception):
    """De rij-lock op het aangeboden refresh-token kwam niet binnen de lock-timeout vrij — een
    andere rotatie van hetzelfde token is nog bezig. Bewust GEEN AuthError: dit is geen ongeldige
    sessie (401 zou de client uitloggen) maar een tijdelijke botsing; de router vertaalt dit naar
    een 409 zodat de client kort kan wachten en één keer opnieuw proberen."""


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
    e_mail = normaliseer_e_mail(e_mail)
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
    """`soort` bepaalt de tweede stap van de activatie: 'totp' (kantoor-rollen, bestaand) of
    'passkey' (klant-accordeur, besluit auth-cadans 2026-08-11 — de passkey-registratie op het
    apparaat vervangt de TOTP-stap; velden van de andere variant zijn dan None)."""

    soort: str
    totp_setup_token: str | None = None
    otpauth_uri: str | None = None
    secret: str | None = None
    passkey_setup_token: str | None = None


def accepteer_uitnodiging(*, token: str, wachtwoord: str) -> AcceptatieResultaat:
    """Token -> wachtwoord zetten -> tweede factor voorbereiden. Kantoor-rollen: TOTP-secret
    genereren (nog niet bevestigd), activatie volgt pas na bevestig_totp(). Klant-accordeur:
    status wacht_op_passkey + een passkey_setup-token — activatie volgt pas na de
    passkey-registratie (app/auth/webauthn_service.py). Het token is hierna altijd verbruikt,
    ook als een latere stap faalt — een mislukte enrollment betekent een nieuwe uitnodiging,
    geen herbruikbaar token (consistent met "eenmalig")."""
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
        uitnodiging.gebruikt_op = now

        if gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR:
            gebruiker.status = GebruikerStatus.WACHT_OP_PASSKEY
            return AcceptatieResultaat(
                soort="passkey", passkey_setup_token=create_passkey_setup_token(gebruiker.id)
            )

        gebruiker.status = GebruikerStatus.WACHT_OP_TOTP
        secret = generate_secret()
        ciphertext, wrapped_key = wrap_secret(secret.encode())
        session.add(
            TotpSecret(gebruiker_id=gebruiker.id, secret_ciphertext=ciphertext, wrapped_data_key=wrapped_key)
        )
        e_mail = gebruiker.e_mail
        gebruiker_id = gebruiker.id

    return AcceptatieResultaat(
        soort="totp",
        totp_setup_token=create_totp_setup_token(gebruiker_id),
        otpauth_uri=build_otpauth_uri(secret, account_name=e_mail),
        secret=secret,
    )


@dataclass(frozen=True)
class TokenPaar:
    access_token: str
    refresh_token: str
    # Cookie-max_age hoort bij de TTL van dít token (accordeur = 7 dagen sliding, besluit
    # 2026-08-11; overige rollen 30 dagen) — de router mag niet blind de platform-default zetten.
    refresh_ttl_seconds: int = 0


def _refresh_ttl_voor(rol: GebruikerRol) -> int:
    """Accordeur-cadans (besluit 2026-08-11): 7 dagen sliding voor klant-accordeurs — elke
    rotatie geeft een vers token met deze TTL, dus 7 dagen zónder gebruik = volledige login."""
    if rol == GebruikerRol.KLANT_ACCORDEUR:
        return settings.jwt_refresh_ttl_accordeur_seconds
    return settings.jwt_refresh_ttl_seconds


def _issue_token_paar(
    session: Session,
    *,
    gebruiker_id: uuid.UUID,
    rol: GebruikerRol,
    voorganger_id: uuid.UUID | None = None,
    apparaat_id: uuid.UUID | None = None,
) -> TokenPaar:
    """Enige plek die een refresh-token uitgeeft: naast het JWT ook de bijbehorende hash
    vastleggen in `refresh_token`, anders is rotatie/hergebruik-detectie niet mogelijk voor dit
    token. `voorganger_id` legt de rotatieketen vast (None bij een verse login/activatie);
    `apparaat_id` bindt de sessie aan een geregistreerd apparaat (passkey — migratie 0040) en
    reist ook als claim in het access-token mee (kill-switch per request, zie deps)."""
    ttl_seconds = _refresh_ttl_voor(rol)
    access_token = create_access_token(gebruiker_id, rol=rol.value, apparaat_id=apparaat_id)
    refresh_token = create_refresh_token(gebruiker_id, ttl_seconds=ttl_seconds)
    session.add(
        RefreshToken(
            id=uuid.uuid4(),
            gebruiker_id=gebruiker_id,
            token_hash=_hash_token(refresh_token),
            voorganger_id=voorganger_id,
            apparaat_id=apparaat_id,
            verloopt_op=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
    )
    return TokenPaar(access_token=access_token, refresh_token=refresh_token, refresh_ttl_seconds=ttl_seconds)


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
    e_mail = normaliseer_e_mail(e_mail)
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


def _is_lock_timeout(exc: OperationalError) -> bool:
    """SQLSTATE 55P03 (lock_not_available) = de `SET LOCAL lock_timeout` sloeg toe. Andere
    OperationalErrors (verbinding weg e.d.) horen gewoon door te bubbelen."""
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) == "55P03"


def vernieuw_token(*, refresh_token: str, ip_adres: str | None = None) -> TokenPaar:
    """Rotatie bij elke aanroep (Auth-0010-b punt 1): het aangeboden token wordt verbruikt-
    gemarkeerd en vervangen door een nieuwe. Wordt hetzelfde token een tweede keer aangeboden
    (gebruikt_op of ingetrokken_op al gezet), dan is dat in beginsel hergebruik van een
    gestolen/gelekt token — alle actieve sessies van de gebruiker worden dan preventief
    ingetrokken.

    Race-tolerantie (browserreview 2026-08-07): één browser kan legitiem twee vernieuwen-calls
    tegelijk sturen (dubbel React-effect, meerdere tabs met dezelfde cookie). Daarom (1) wordt de
    tokenrij met FOR UPDATE gelezen zodat gelijktijdige rotaties serialiseren i.p.v. dubbel
    uitgeven, met een lock_timeout zodat een wachter nooit eeuwig blokkeert (RotatieBezetError →
    409, geen uitlog); en (2) geldt een korte grace-periode: hergebruik bínnen
    `refresh_hergebruik_grace_seconds` na de rotatie is een race, geen diefstal — de verliezer
    krijgt een vers sibling-token (zelfde voorganger, wél ge-audit), zónder revoke-all. Ná de
    grace-periode is de replay-bescherming onverkort: revoke-all + 401.

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

    faal_reden: str | None = None
    paar: TokenPaar | None = None

    try:
        with scoped_session(None) as session:
            session.execute(
                text("SELECT set_config('lock_timeout', :ms, true)"),
                {"ms": f"{settings.refresh_rotatie_lock_timeout_ms}ms"},
            )
            # FOR UPDATE: een gelijktijdige rotatie van hetzelfde token wacht hier tot de winnaar
            # gecommit heeft en leest daarna de gecommitte staat (gebruikt_op gezet) — de
            # grace-tak hieronder handelt dat netjes af. `now` pas ná het verkrijgen van de lock
            # bepalen, anders telt de wachttijd op de winnaar mee in de grace-vergelijking.
            rij = session.scalars(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
            ).one_or_none()
            now = datetime.now(UTC)
            # Kill-switch per apparaat (migratie 0040): een sessie die aan een ingetrokken
            # passkey-credential hangt, wordt bij de eerstvolgende rotatie hard geweigerd —
            # vóór de gebruikt_op-tak, anders zou een grace-race op een ingetrokken apparaat
            # alsnog een vers token opleveren.
            apparaat_ingetrokken = False
            if rij is not None and rij.apparaat_id is not None:
                credential = session.get(WebauthnCredential, rij.apparaat_id)
                apparaat_ingetrokken = credential is None or credential.ingetrokken_op is not None
            if rij is None:
                faal_reden = "onbekend"
            elif apparaat_ingetrokken:
                if rij.ingetrokken_op is None:
                    rij.ingetrokken_op = now
                faal_reden = "apparaat_ingetrokken"
            elif rij.gebruikt_op is not None or rij.ingetrokken_op is not None:
                grace = timedelta(seconds=settings.refresh_hergebruik_grace_seconds)
                binnen_grace = (
                    rij.ingetrokken_op is None and rij.gebruikt_op is not None and now - rij.gebruikt_op <= grace
                )
                gebruiker = session.get(Gebruiker, gebruiker_id)
                if binnen_grace and gebruiker is not None and gebruiker.status == GebruikerStatus.ACTIEF:
                    record_audit_event(
                        session,
                        actor_id=gebruiker_id,
                        module="platform",
                        tabel="refresh_token",
                        record_id=rij.id,
                        actie="refresh_token_hergebruik_binnen_grace",
                        correlatie_id=uuid.uuid4(),
                        nieuwe_waarde=_login_metadata(ip_adres),
                    )
                    paar = _issue_token_paar(
                        session,
                        gebruiker_id=gebruiker_id,
                        rol=gebruiker.rol,
                        voorganger_id=rij.id,
                        apparaat_id=rij.apparaat_id,
                    )
                else:
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
                    paar = _issue_token_paar(
                        session,
                        gebruiker_id=gebruiker_id,
                        rol=gebruiker.rol,
                        voorganger_id=rij.id,
                        apparaat_id=rij.apparaat_id,
                    )
    except OperationalError as exc:
        if _is_lock_timeout(exc):
            raise RotatieBezetError("Een andere vernieuwing van deze sessie is nog bezig") from exc
        raise

    if paar is None:
        foutmeldingen = {
            "onbekend": "Ongeldig refresh-token",
            "hergebruik": "Refresh-token al gebruikt — alle sessies zijn ter voorzorg beëindigd",
            "verlopen": "Refresh-token verlopen",
            "inactief": "Account niet (meer) actief",
            "apparaat_ingetrokken": "Toegang voor dit apparaat is ingetrokken",
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
    e_mail = normaliseer_e_mail(e_mail)
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


@dataclass(frozen=True)
class GebruikerOverzicht:
    """Eén rij op het scherm Gebruikers & toegang (fase 3 modernisering, designronde 15-08).
    Dataminimalisatie: alleen bestaans-/statusfeiten over de beveiliging (heeft TOTP, aantal
    actieve passkeys) — nooit secret- of credentialmateriaal."""

    id: uuid.UUID
    naam: str
    e_mail: str
    rol: GebruikerRol
    status: GebruikerStatus
    administratie_ids: list[uuid.UUID]
    heeft_totp: bool
    aantal_passkeys: int
    open_uitnodiging_verloopt_op: datetime | None


def lijst_gebruikers(*, actor_id: uuid.UUID) -> list[GebruikerOverzicht]:
    """Gebruikerslijst voor Gebruikers & toegang — Beheerder-only (router-dependency; de
    RLS-beheerder-bypass op gebruiker_administratie maakt de scope-kolom platform-breed
    leesbaar). Gepseudonimiseerde gebruikers (AVG) blijven buiten de lijst."""
    now = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruikers = list(
            session.scalars(
                select(Gebruiker).where(Gebruiker.gepseudonimiseerd_op.is_(None)).order_by(Gebruiker.naam)
            )
        )
        scope_rijen = session.execute(
            select(GebruikerAdministratie.gebruiker_id, GebruikerAdministratie.administratie_id)
        ).all()
        totp_ids = set(
            session.scalars(select(TotpSecret.gebruiker_id).where(TotpSecret.bevestigd_op.is_not(None)))
        )
        passkeys = dict(
            session.execute(
                select(WebauthnCredential.gebruiker_id, func.count())
                .where(WebauthnCredential.ingetrokken_op.is_(None))
                .group_by(WebauthnCredential.gebruiker_id)
            ).all()
        )
        open_uitnodigingen = dict(
            session.execute(
                select(Uitnodiging.gebruiker_id, func.max(Uitnodiging.verloopt_op))
                .where(Uitnodiging.gebruikt_op.is_(None), Uitnodiging.verloopt_op > now)
                .group_by(Uitnodiging.gebruiker_id)
            ).all()
        )
        session.expunge_all()

    scope_per_gebruiker: dict[uuid.UUID, list[uuid.UUID]] = {}
    for gebruiker_id, administratie_id in scope_rijen:
        scope_per_gebruiker.setdefault(gebruiker_id, []).append(administratie_id)

    return [
        GebruikerOverzicht(
            id=g.id,
            naam=g.naam,
            e_mail=g.e_mail,
            rol=g.rol,
            status=g.status,
            administratie_ids=scope_per_gebruiker.get(g.id, []),
            heeft_totp=g.id in totp_ids,
            aantal_passkeys=passkeys.get(g.id, 0),
            open_uitnodiging_verloopt_op=open_uitnodigingen.get(g.id),
        )
        for g in gebruikers
    ]


def staande_goedkeuringen_per_accordeur(*, administratie_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Aantal actieve staande goedkeuringen per accordeur, opgeteld over de administraties.
    Per administratie een eigen gescoopte transactie: boekhouding.staande_goedkeuring heeft een
    strikte per-administratie-RLS zonder beheerder-bypass (migratie 0033) — zelfde looppatroon
    als de dagelijkse herinnering."""
    from app.accordering.models import StaandeGoedkeuring

    totalen: dict[uuid.UUID, int] = {}
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id) as session:
            rijen = session.execute(
                select(StaandeGoedkeuring.accordeur_gebruiker_id, func.count())
                .where(
                    StaandeGoedkeuring.administratie_id == administratie_id,
                    StaandeGoedkeuring.actief.is_(True),
                    StaandeGoedkeuring.ingetrokken_op.is_(None),
                )
                .group_by(StaandeGoedkeuring.accordeur_gebruiker_id)
            ).all()
        for accordeur_id, aantal in rijen:
            totalen[accordeur_id] = totalen.get(accordeur_id, 0) + aantal
    return totalen


@dataclass(frozen=True)
class VernieuwdeUitnodiging:
    resultaat: UitnodigingResultaat
    naam: str
    e_mail: str


def vernieuw_uitnodiging(*, actor_id: uuid.UUID, gebruiker_id: uuid.UUID) -> VernieuwdeUitnodiging:
    """"Opnieuw mailen" (Gebruikers & toegang): het oorspronkelijke token bestaat alleen als
    hash, dus opnieuw versturen = een nieuw token uitgeven. Oudere nog-open uitnodigingen van
    dezelfde gebruiker verlopen per direct (één werkende link tegelijk); de handeling zelf gaat
    het append-only audit_event in. Alleen voor gebruikers die nog in de uitnodigingsfase
    zitten — een (deels) geactiveerd account krijgt nooit een verse activatielink."""
    token = secrets.token_urlsafe(32)
    verloopt_op = datetime.now(UTC) + INVITE_TTL
    uitnodiging_id = uuid.uuid4()
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.gepseudonimiseerd_op is not None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.status != GebruikerStatus.UITGENODIGD:
            raise AuthError("Alleen een nog niet geactiveerde uitnodiging kan opnieuw gemaild worden")
        naam, e_mail = gebruiker.naam, gebruiker.e_mail
        nu = datetime.now(UTC)
        session.execute(
            update(Uitnodiging)
            .where(
                Uitnodiging.gebruiker_id == gebruiker_id,
                Uitnodiging.gebruikt_op.is_(None),
                Uitnodiging.verloopt_op > nu,
            )
            .values(verloopt_op=nu)
        )
        session.add(
            Uitnodiging(
                id=uitnodiging_id,
                gebruiker_id=gebruiker_id,
                token_hash=_hash_token(token),
                aangemaakt_door=actor_id,
                verloopt_op=verloopt_op,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="platform.uitnodiging",
            record_id=uitnodiging_id,
            actie="uitnodiging_opnieuw_gemaild",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"gebruiker_id": str(gebruiker_id), "verloopt_op": verloopt_op.isoformat()},
        )
    return VernieuwdeUitnodiging(
        resultaat=UitnodigingResultaat(
            uitnodiging_id=uitnodiging_id, gebruiker_id=gebruiker_id, token=token, verloopt_op=verloopt_op
        ),
        naam=naam,
        e_mail=e_mail,
    )
