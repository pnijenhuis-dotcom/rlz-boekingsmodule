from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.normalisatie import normaliseer_e_mail
from app.auth.rollen import is_externe_app_rol
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
    UitnodigingSoort,
    WebauthnCredential,
)
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
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


class EMailAlInGebruik(Exception):
    """Punt 22 (opruimrun 28-08, casus 9ba50485-…): het e-mailadres van een nieuwe uitnodiging hoort
    al bij een bestaand account (óók een gearchiveerd) — vóór de fix een UniqueViolation op
    `gebruiker_e_mail_key` → generieke 500 mét correlatie-id. Router → 409 mét leesbare uitleg.
    Bewust géén AuthError-subklasse: de router mapt 'm apart (409, niet 400)."""


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


class VeldwerkerbeheerBegrenzing(AuthError):
    """Buiten de begrenzing van het fijnmazige veldwerkerbeheer-recht (31-08) — router → 403."""


def toets_veldwerkerbeheer_uitnodiging(
    *, actor_id: uuid.UUID, actor_rol: GebruikerRol, rol: GebruikerRol, administratie_ids: list[uuid.UUID]
) -> None:
    """Begrenzing veldwerkerbeheer-recht (besluit Peter 31-08, migratie 0091): een
    niet-Beheerder mét het recht maakt UITSLUITEND veldwerkers (ZZP'er/uitvoerder/detacheerder)
    aan, mét scope, en uitsluitend binnen de eigen administratie-scope — nooit kantoorrollen.
    Het harde principe "gebruikersbeheer exclusief Beheerder" blijft voor al het overige."""
    from app.auth.rollen import is_veldrol

    if actor_rol == GebruikerRol.BEHEERDER:
        return
    if not is_veldrol(rol):
        raise VeldwerkerbeheerBegrenzing("Het veldwerkerbeheer-recht dekt alleen veldwerker-rollen")
    if not administratie_ids:
        raise VeldwerkerbeheerBegrenzing("Een veldwerker krijgt altijd een administratie-scope")
    eigen = {a.id for a in mijn_administraties(actor_id=actor_id, rol=actor_rol)}
    if not set(administratie_ids) <= eigen:
        raise VeldwerkerbeheerBegrenzing("De scope valt buiten uw eigen administraties")


def toets_veldwerkerbeheer_doel(*, actor_id: uuid.UUID, actor_rol: GebruikerRol, doel_gebruiker_id: uuid.UUID) -> None:
    """Begrenzing veldwerkerbeheer-recht op een BESTAANDE gebruiker (archiveren/open-werk):
    doel moet een veldwerker zijn én zijn VOLLEDIGE scope moet binnen die van de actor vallen —
    getoetst via de zelf-gepoorte SECURITY DEFINER-functie (RLS laat de actor andermans
    scope-rijen buiten de eigen administraties niet zien; fail-closed)."""
    from app.auth.rollen import is_veldrol

    if actor_rol == GebruikerRol.BEHEERDER:
        return
    with scoped_session(None, actor_id=actor_id) as session:
        doel = session.get(Gebruiker, doel_gebruiker_id)
        if doel is None or not is_veldrol(doel.rol):
            raise VeldwerkerbeheerBegrenzing("Het veldwerkerbeheer-recht dekt alleen veldwerkers")
        binnen = session.execute(
            text("SELECT platform.veldwerker_scope_binnen_actor(:doel, :actor)"),
            {"doel": str(doel_gebruiker_id), "actor": str(actor_id)},
        ).scalar()
        if binnen is not True:
            raise VeldwerkerbeheerBegrenzing("Deze veldwerker valt (deels) buiten uw administratie-scope")


def maak_uitnodiging(
    *,
    actor_id: uuid.UUID,
    naam: str,
    e_mail: str,
    rol: GebruikerRol,
    administratie_ids: list[uuid.UUID],
    uitnodiging_later: bool = False,
) -> UitnodigingResultaat:
    """Beheerder-only (afgedwongen door de router-dependency, niet hier — zie deps.require_beheerder),
    sinds 31-08 mét de veldwerkerbeheer-uitzondering (router toetst toets_veldwerkerbeheer_uitnodiging).
    Genereert een eenmalig token; alleen de hash ervan wordt opgeslagen (zie Uitnodiging).
    `uitnodiging_later` (A4) legt alleen vast dát de mail bewust is uitgesteld — de router
    slaat het verzenden over; het token blijft geldig voor "Opnieuw mailen"."""
    e_mail = normaliseer_e_mail(e_mail)
    gebruiker_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)
    verloopt_op = datetime.now(UTC) + INVITE_TTL

    with scoped_session(None, actor_id=actor_id) as session:
        # Punt 22 (28-08): leesbare weigering i.p.v. de DB-uniciteitsfout (500 mét correlatie-id).
        bestaand = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail)).first()
        if bestaand is not None:
            if bestaand.status == GebruikerStatus.GEARCHIVEERD:
                raise EMailAlInGebruik(
                    f"Dit e-mailadres hoort bij een gearchiveerd account ({bestaand.naam}) — wijzig eerst dat "
                    "adres via 'E-mail wijzigen' of dearchiveer het account"
                )
            raise EMailAlInGebruik(
                f"Dit e-mailadres is al in gebruik door {bestaand.naam} (status {bestaand.status.value}) — "
                "wijzig eerst dat adres of gebruik een ander adres"
            )
        session.add(Gebruiker(id=gebruiker_id, naam=naam, e_mail=e_mail, rol=rol, status=GebruikerStatus.UITGENODIGD))
        session.flush()
        for administratie_id in administratie_ids:
            # RLS-WITH-CHECK op gebruiker_administratie eist administratie_id =
            # current_administratie_id() voor een niet-Beheerder (veldwerkerbeheer-pad 31-08):
            # de GUC per rij zetten (SET LOCAL-semantiek, transactie-lokaal). Voor een
            # Beheerder verandert dit niets (eigen bypass in de policy).
            session.execute(
                text("SELECT set_config('app.current_administratie_id', :v, true)"),
                {"v": str(administratie_id)},
            )
            session.add(GebruikerAdministratie(gebruiker_id=gebruiker_id, administratie_id=administratie_id))
            session.flush()
        session.execute(text("SELECT set_config('app.current_administratie_id', '', true)"))
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
        # Audit op de uitnodiging-rij (record = uitnodiging, correlatie = gebruiker) — de
        # gebruiker-tabel houdt zo uitsluitend account-gebeurtenissen (login/rol/scope/e-mail).
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="uitnodiging",
            record_id=uitnodiging_id,
            actie="gebruiker_uitgenodigd",
            correlatie_id=gebruiker_id,
            nieuwe_waarde={
                "naam": naam,
                "e_mail": e_mail,
                "rol": rol.value,
                "administratie_ids": [str(a) for a in administratie_ids],
                "status": GebruikerStatus.UITGENODIGD.value,
                "mail_uitgesteld": uitnodiging_later,
            },
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
    """Token -> wachtwoord zetten -> tweede factor voorbereiden.

    Kantoor-rollen (ongewijzigd): wachtwoord direct definitief, TOTP-secret genereren (nog niet
    bevestigd), token verbruikt — activatie volgt pas na bevestig_totp().

    Externe app-rollen (klant-accordeur + veldrollen) — ATOMAIR sinds 28-08 (besluit Peter,
    mockup activatie-mobiel.html, casus Haci): het wachtwoord wordt hier NIET op de gebruiker
    gezet en het token NIET verbruikt. De hash wordt geparkeerd op de uitnodigingsrij
    (`wachtwoord_hash_in_wacht`, migratie 0083) en pas in dezelfde transactie als de geslaagde
    passkey-registratie definitief gemaakt (`webauthn_service._rond_registratie_af`). Mislukt
    de passkey, dan is er niets half geregistreerd en blijft de link tot zijn vervaldatum
    verzilverbaar (her-opening = flow opnieuw, geen nieuwe link nodig). Het passkey_setup-token
    draagt daarvoor de uitnodiging-id mee."""
    if len(wachtwoord) < MIN_WACHTWOORD_LENGTE:
        raise AuthError(f"Wachtwoord moet minimaal {MIN_WACHTWOORD_LENGTE} tekens zijn")

    token_hash = _hash_token(token)
    now = datetime.now(UTC)

    with scoped_session(None) as session:
        uitnodiging = _open_uitnodiging(session, token_hash=token_hash, now=now)
        gebruiker = session.get(Gebruiker, uitnodiging.gebruiker_id)
        assert gebruiker is not None  # FK garandeert dit

        if is_externe_app_rol(gebruiker.rol):
            return _parkeer_wachtwoord_voor_passkey(uitnodiging, gebruiker, wachtwoord=wachtwoord)

        if uitnodiging.soort == UitnodigingSoort.WACHTWOORD_HERSTEL.value:
            # Herstel-links bestaan alleen voor externe rollen (maak_herstel_link) — vangnet.
            raise AuthError("Herstel-links bestaan alleen voor externe app-gebruikers")

        gebruiker.wachtwoord_hash = hash_password(wachtwoord)
        uitnodiging.gebruikt_op = now
        gebruiker.status = GebruikerStatus.WACHT_OP_TOTP
        secret = generate_secret()
        ciphertext, wrapped_key = wrap_secret(secret.encode())
        session.add(TotpSecret(gebruiker_id=gebruiker.id, secret_ciphertext=ciphertext, wrapped_data_key=wrapped_key))
        e_mail = gebruiker.e_mail
        gebruiker_id = gebruiker.id

    return AcceptatieResultaat(
        soort="totp",
        totp_setup_token=create_totp_setup_token(gebruiker_id),
        otpauth_uri=build_otpauth_uri(secret, account_name=e_mail),
        secret=secret,
    )


def _open_uitnodiging(session: Session, *, token_hash: str, now: datetime) -> Uitnodiging:
    """Eén plek voor de drie token-poorten (onbekend / al gebruikt / verlopen)."""
    uitnodiging = session.scalars(select(Uitnodiging).where(Uitnodiging.token_hash == token_hash)).one_or_none()
    if uitnodiging is None:
        raise AuthError("Ongeldig uitnodigingstoken")
    if uitnodiging.gebruikt_op is not None:
        raise AuthError("Uitnodiging is al gebruikt")
    if uitnodiging.verloopt_op < now:
        raise AuthError("Uitnodiging is verlopen")
    return uitnodiging


def _parkeer_wachtwoord_voor_passkey(
    uitnodiging: Uitnodiging, gebruiker: Gebruiker, *, wachtwoord: str
) -> AcceptatieResultaat:
    """Wachtwoordstap externe rol (uitnodiging óf herstel): hash op de link parkeren, niets op de
    gebruiker muteren. Herstel eist een account dat mag herstellen (blokkade wint — 0052-lijn);
    de bestaande passkeys/akkoorden blijven staan, sessies worden pas bij afronding ingetrokken."""
    if uitnodiging.soort == UitnodigingSoort.WACHTWOORD_HERSTEL.value and gebruiker.status not in (
        GebruikerStatus.ACTIEF,
        GebruikerStatus.WACHT_OP_PASSKEY,
    ):
        raise AuthError("Account is geblokkeerd of niet geactiveerd — neem contact op met het kantoor")
    if uitnodiging.soort == UitnodigingSoort.UITNODIGING.value and gebruiker.status != GebruikerStatus.UITGENODIGD:
        raise AuthError("Account is al geactiveerd of geblokkeerd — neem contact op met het kantoor")
    uitnodiging.wachtwoord_hash_in_wacht = hash_password(wachtwoord)
    return AcceptatieResultaat(
        soort="passkey",
        passkey_setup_token=create_passkey_setup_token(gebruiker.id, uitnodiging_id=uitnodiging.id),
    )


def rond_uitnodiging_af_met_passkey(
    session: Session, *, gebruiker: Gebruiker, uitnodiging_id: uuid.UUID, now: datetime
) -> None:
    """Het atomaire sluitstuk (aangeroepen BINNEN de registratie-transactie van
    webauthn_service): geparkeerde hash → gebruiker, link verbruikt, status actief (uitnodiging)
    resp. alle sessies ingetrokken (herstel), audit. Faalt hier iets, dan rolt de hele
    registratie terug — passkey én wachtwoord bestaan dan allebei niet."""
    uitnodiging = session.get(Uitnodiging, uitnodiging_id)
    if uitnodiging is None or uitnodiging.gebruiker_id != gebruiker.id:
        raise AuthError("Ongeldig uitnodigingstoken")
    if uitnodiging.gebruikt_op is not None:
        raise AuthError("Uitnodiging is al gebruikt")
    if uitnodiging.verloopt_op < now:
        raise AuthError("Uitnodiging is verlopen — vraag het kantoor om een nieuwe link")
    if uitnodiging.wachtwoord_hash_in_wacht is None:
        raise AuthError("Wachtwoordstap ontbreekt — begin de activatie opnieuw via de link")
    if gebruiker.status in (GebruikerStatus.GEBLOKKEERD, GebruikerStatus.GEARCHIVEERD):
        raise AuthError("Account is geblokkeerd — neem contact op met het kantoor")

    gebruiker.wachtwoord_hash = uitnodiging.wachtwoord_hash_in_wacht
    uitnodiging.wachtwoord_hash_in_wacht = None
    uitnodiging.gebruikt_op = now
    if uitnodiging.soort == UitnodigingSoort.WACHTWOORD_HERSTEL.value:
        _intrek_alle_sessies(session, gebruiker.id, now=now)
        actie = "wachtwoord_hersteld"
    else:
        gebruiker.status = GebruikerStatus.ACTIEF
        actie = "activatie_afgerond"
    record_audit_event(
        session,
        actor_id=gebruiker.id,
        module="platform",
        tabel="gebruiker",
        record_id=gebruiker.id,
        actie=actie,
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"uitnodiging_id": str(uitnodiging.id), "status": gebruiker.status.value, "atomair": True},
    )


@dataclass(frozen=True)
class UitnodigingInfo:
    """Publieke voorkennis over een link (token = het geheim): welke flow hoort erbij, zodat het
    /activeren-scherm vóór de wachtwoordstap weet of het een externe (passkey, mobiel-first)
    of een kantoor-activatie (TOTP) is. Bewust minimaal — geen e-mail, geen rol."""

    flow: str  # 'passkey' | 'totp'
    naam: str
    herstel: bool
    verloopt_op: datetime


def uitnodiging_info(*, token: str) -> UitnodigingInfo:
    """Leest zonder te verzilveren; dezelfde drie poorten als accepteren."""
    now = datetime.now(UTC)
    with scoped_session(None) as session:
        uitnodiging = _open_uitnodiging(session, token_hash=_hash_token(token), now=now)
        gebruiker = session.get(Gebruiker, uitnodiging.gebruiker_id)
        assert gebruiker is not None
        return UitnodigingInfo(
            flow="passkey" if is_externe_app_rol(gebruiker.rol) else "totp",
            naam=gebruiker.naam,
            herstel=uitnodiging.soort == UitnodigingSoort.WACHTWOORD_HERSTEL.value,
            verloopt_op=uitnodiging.verloopt_op,
        )


def meld_activatie_probleem(*, token: str) -> str:
    """Knop "Ik kom er niet uit — meld het kantoor" (mockup activatie-mobiel.html, foutscherm):
    audit op de gebruiker (systeem-neutraal: de gebruiker zelf is actor) + notificatie aan het
    kantoor via het gedeelde mailkanaal (fail-zichtbaar in de log, nooit een fout richting de
    gebruiker — die kan er niets aan doen). Geeft de naam terug voor de bevestigingstekst."""
    now = datetime.now(UTC)
    with scoped_session(None) as session:
        uitnodiging = _open_uitnodiging(session, token_hash=_hash_token(token), now=now)
        gebruiker = session.get(Gebruiker, uitnodiging.gebruiker_id)
        assert gebruiker is not None
        record_audit_event(
            session,
            actor_id=gebruiker.id,
            module="platform",
            tabel="gebruiker",
            record_id=gebruiker.id,
            actie="activatie_probleem_gemeld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"uitnodiging_id": str(uitnodiging.id), "soort": uitnodiging.soort},
        )
        naam, e_mail = gebruiker.naam, gebruiker.e_mail
    from app.berichten import uitnodigingsmail

    uitnodigingsmail.verstuur_activatieprobleem_aan_kantoor(naam=naam, e_mail=e_mail)
    return naam


@dataclass(frozen=True)
class TokenPaar:
    access_token: str
    refresh_token: str
    # Cookie-max_age hoort bij de TTL van dít token (accordeur = 7 dagen sliding, besluit
    # 2026-08-11; overige rollen 30 dagen) — de router mag niet blind de platform-default zetten.
    refresh_ttl_seconds: int = 0
    # Ontgrendel-frequentie (besluit Peter 2026-08-27): alleen gezet op de STILLE REFRESH van een
    # apparaat-gebonden externe-app-sessie — True = de laatste passkey-ceremonie op dit apparaat
    # is ouder dan het venster (24 u), de app toont het ontgrendelscherm; False = direct door.
    # None = niet van toepassing (kantoor-sessies, login-/ontgrendel-responses) → het veld
    # ontbreekt in de JSON (contract-guard kantoor blijft byte-identiek).
    ontgrendeling_nodig: bool | None = None


def _refresh_ttl_voor(rol: GebruikerRol) -> int:
    """Accordeur-cadans (besluit 2026-08-11): 7 dagen sliding voor álle externe app-rollen
    (accordeur + veldrollen, migratie 0056) — elke rotatie geeft een vers token met deze TTL,
    dus 7 dagen zónder gebruik = volledige login."""
    if is_externe_app_rol(rol):
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


def _ontgrendeling_nodig(
    session: Session, *, apparaat_id: uuid.UUID | None, rol: GebruikerRol, now: datetime
) -> bool | None:
    """24-uursvenster (besluit 2026-08-27, `settings.ontgrendel_venster_seconds`): geldt alleen
    voor apparaat-gebonden sessies van externe app-rollen. Anker = laatst_gebruikt_op van het
    apparaat (elke passkey-ceremonie zet 'm; een stille refresh niet) — nooit gezet = ontgrendelen.
    De kill-switch is hiervóór al getoetst (ingetrokken apparaat komt hier niet)."""
    if apparaat_id is None or not is_externe_app_rol(rol):
        return None
    credential = session.get(WebauthnCredential, apparaat_id)
    if credential is None or credential.laatst_gebruikt_op is None:
        return True
    return now - credential.laatst_gebruikt_op > timedelta(seconds=settings.ontgrendel_venster_seconds)


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
                    paar = replace(
                        _issue_token_paar(
                            session,
                            gebruiker_id=gebruiker_id,
                            rol=gebruiker.rol,
                            voorganger_id=rij.id,
                            apparaat_id=rij.apparaat_id,
                        ),
                        ontgrendeling_nodig=_ontgrendeling_nodig(
                            session, apparaat_id=rij.apparaat_id, rol=gebruiker.rol, now=now
                        ),
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
                    paar = replace(
                        _issue_token_paar(
                            session,
                            gebruiker_id=gebruiker_id,
                            rol=gebruiker.rol,
                            voorganger_id=rij.id,
                            apparaat_id=rij.apparaat_id,
                        ),
                        ontgrendeling_nodig=_ontgrendeling_nodig(
                            session, apparaat_id=rij.apparaat_id, rol=gebruiker.rol, now=now
                        ),
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


def _weiger_systeem_actor(doel_gebruiker_id: uuid.UUID) -> None:
    """De systeem-actor (achtergrondverwerking, app/db/systeem_actor.py) is een technische
    gebruiker-rij voor FK's op audit/tijdlijn — nooit een beheerbaar account. Rol- of
    scope-mutatie erop is altijd een fout (controls-review 2026-08-16)."""
    if doel_gebruiker_id == SYSTEEM_ACTOR_ID:
        raise AuthError("De systeemgebruiker kan niet gewijzigd worden")


def wijzig_rol(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, nieuwe_rol: GebruikerRol) -> None:
    """Hard (CLAUDE.md): niemand muteert zijn eigen rol, ook een Beheerder niet. Beheerder-only
    afgedwongen door de router-dependency; hier alleen de self-mutation-check, want die geldt
    onvoorwaardelijk — ook als een toekomstige aanroeper deze functie ooit los aanroept."""
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan de eigen rol niet wijzigen")
    _weiger_systeem_actor(doel_gebruiker_id)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.status == GebruikerStatus.GEARCHIVEERD:
            raise AuthError("Gebruiker is gearchiveerd — dearchiveer eerst")
        gebruiker.rol = nieuwe_rol


def _tel_overige_actieve_beheerders(session: Session, *, behalve_gebruiker_id: uuid.UUID) -> int:
    """Aantal actieve Beheerders buiten het doelaccount. De systeem-actor telt nooit mee (die is
    technisch en staat zelf op geblokkeerd), gepseudonimiseerde accounts evenmin."""
    return session.scalar(
        select(func.count())
        .select_from(Gebruiker)
        .where(
            Gebruiker.rol == GebruikerRol.BEHEERDER,
            Gebruiker.status == GebruikerStatus.ACTIEF,
            Gebruiker.gepseudonimiseerd_op.is_(None),
            Gebruiker.id != behalve_gebruiker_id,
            Gebruiker.id != SYSTEEM_ACTOR_ID,
        )
    )


def blokkeer_gebruiker(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID) -> None:
    """Blokkeer een gebruiker (beheer-mini 2026-08-16). Status → geblokkeerd bijt per direct op
    álle paden: deps.py hertoetst per request, de refresh-rotatie weigert, en elk login-pad
    (wachtwoord+TOTP én alle WebAuthn-vormen) eist status actief — passkeys blijven geregistreerd
    maar zijn onbruikbaar zolang de blokkade staat (kill-switch-semantiek, omkeerbaar).
    Alle lopende sessies/refresh-tokens gaan per direct dood.

    Waarborgen (server-side, onvoorwaardelijk): eigen account nooit, systeem-actor nooit,
    de laatste actieve Beheerder nooit."""
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan het eigen account niet blokkeren")
    _weiger_systeem_actor(doel_gebruiker_id)
    now = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None or gebruiker.gepseudonimiseerd_op is not None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.status == GebruikerStatus.GEBLOKKEERD:
            raise AuthError("Gebruiker is al geblokkeerd")
        if gebruiker.status == GebruikerStatus.GEARCHIVEERD:
            raise AuthError("Gebruiker is gearchiveerd — dearchiveer eerst")
        if (
            gebruiker.rol == GebruikerRol.BEHEERDER
            and gebruiker.status == GebruikerStatus.ACTIEF
            and _tel_overige_actieve_beheerders(session, behalve_gebruiker_id=doel_gebruiker_id) == 0
        ):
            raise AuthError("De laatste actieve Beheerder kan niet geblokkeerd worden")
        oude_status = gebruiker.status
        gebruiker.status_voor_blokkade = oude_status.value
        gebruiker.status = GebruikerStatus.GEBLOKKEERD
        gebruiker.geblokkeerd_op = now
        gebruiker.geblokkeerd_door = actor_id
        _intrek_alle_sessies(session, doel_gebruiker_id, now=now)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="gebruiker",
            record_id=doel_gebruiker_id,
            actie="gebruiker_geblokkeerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": oude_status.value},
            nieuwe_waarde={"status": GebruikerStatus.GEBLOKKEERD.value},
        )


def heractiveer_gebruiker(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID) -> None:
    """Hef een blokkade op. De gebruiker keert terug naar de status van vóór de blokkade
    (status_voor_blokkade) — een half-geactiveerd account gaat dus terug de activatieflow in,
    nooit naar 'actief' zonder credentials. Sessies komen niet terug: opnieuw inloggen."""
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan het eigen account niet heractiveren")
    _weiger_systeem_actor(doel_gebruiker_id)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None or gebruiker.gepseudonimiseerd_op is not None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.status != GebruikerStatus.GEBLOKKEERD:
            raise AuthError("Gebruiker is niet geblokkeerd")
        # status_voor_blokkade is altijd gezet door blokkeer_gebruiker; de fallback 'actief'
        # bestaat alleen voor rijen die buiten de app om op geblokkeerd zijn gezet.
        doel_status = (
            GebruikerStatus(gebruiker.status_voor_blokkade)
            if gebruiker.status_voor_blokkade
            else GebruikerStatus.ACTIEF
        )
        gebruiker.status = doel_status
        gebruiker.status_voor_blokkade = None
        gebruiker.geblokkeerd_op = None
        gebruiker.geblokkeerd_door = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="gebruiker",
            record_id=doel_gebruiker_id,
            actie="gebruiker_geheractiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": GebruikerStatus.GEBLOKKEERD.value},
            nieuwe_waarde={"status": doel_status.value},
        )


@dataclass(frozen=True)
class OpenWerk:
    """Open werk van een gebruiker vóór archivering (feedbackronde 26-08 punt 1): een
    bevestigingswaarschuwing mét aantallen, geen blokkade — het werk blijft staan en kan
    opnieuw toegewezen worden."""

    open_accorderingen: int
    weekstaten_ter_keuring: int
    eigen_open_weekstaten: int

    @property
    def heeft_open_werk(self) -> bool:
        return bool(self.open_accorderingen or self.weekstaten_ter_keuring or self.eigen_open_weekstaten)


def open_werk_van_gebruiker(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID) -> OpenWerk:
    """Telt per gebruiker: open accorderingsstappen (vereist, nog zonder besluit, in een open
    ronde — over álle administraties in zijn scope, strikte RLS dus per administratie
    gescoped), weekstaten ter keuring op projecten waar hij keurrecht heeft (uitvoerder) en
    eigen weekstaten die nog niet goedgekeurd zijn (ZZP'er). De scope-lookup leest mét de
    (Beheerder-)actor — `gebruiker_administratie` heeft zelf RLS en toont zonder actor nul rijen
    (RLS-les 25-08, Platform conventies §RLS)."""
    from app.accordering.models import AccorderingStap, AccorderingStatus, DocumentAccordering
    from app.uren.models import UrenProjectToewijzing, Weekstaat, WeekstaatStatus

    with scoped_session(None, actor_id=actor_id) as session:
        administratie_ids = list(
            session.scalars(
                select(GebruikerAdministratie.administratie_id).where(
                    GebruikerAdministratie.gebruiker_id == doel_gebruiker_id
                )
            )
        )

    accorderingen = 0
    ter_keuring = 0
    eigen = 0
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id) as session:
            accorderingen += (
                session.scalar(
                    select(func.count())
                    .select_from(AccorderingStap)
                    .join(DocumentAccordering, DocumentAccordering.id == AccorderingStap.accordering_id)
                    .where(
                        AccorderingStap.administratie_id == administratie_id,
                        AccorderingStap.accordeur_gebruiker_id == doel_gebruiker_id,
                        AccorderingStap.vereist.is_(True),
                        AccorderingStap.besluit.is_(None),
                        DocumentAccordering.status == AccorderingStatus.OPEN.value,
                    )
                )
                or 0
            )
            keur_projecten = select(UrenProjectToewijzing.project_id).where(
                UrenProjectToewijzing.administratie_id == administratie_id,
                UrenProjectToewijzing.gebruiker_id == doel_gebruiker_id,
            )
            ter_keuring += (
                session.scalar(
                    select(func.count())
                    .select_from(Weekstaat)
                    .where(
                        Weekstaat.administratie_id == administratie_id,
                        Weekstaat.status == WeekstaatStatus.INGEDIEND.value,
                        Weekstaat.gebruiker_id != doel_gebruiker_id,
                        Weekstaat.project_id.in_(keur_projecten),
                    )
                )
                or 0
            )
            eigen += (
                session.scalar(
                    select(func.count())
                    .select_from(Weekstaat)
                    .where(
                        Weekstaat.administratie_id == administratie_id,
                        Weekstaat.gebruiker_id == doel_gebruiker_id,
                        Weekstaat.status.in_(
                            (
                                WeekstaatStatus.CONCEPT.value,
                                WeekstaatStatus.INGEDIEND.value,
                                WeekstaatStatus.CORRIGEREN.value,
                            )
                        ),
                    )
                )
                or 0
            )
    return OpenWerk(open_accorderingen=accorderingen, weekstaten_ter_keuring=ter_keuring, eigen_open_weekstaten=eigen)


def archiveer_gebruiker(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID) -> None:
    """Archiveer een gebruiker (feedbackronde 26-08 punt 1, 0052-patroon). Status → gearchiveerd
    bijt per direct op álle paden (elke poort eist status actief), sessies/refresh gaan dood,
    passkeys blijven geregistreerd maar onbruikbaar. Uit alle default-lijsten; historie, audit
    en akkoord-sporen blijven onaangetast — er wordt niets verwijderd. Open werk (accorderingen,
    weekstaten) is een bevestigingswaarschuwing in de UI (`open_werk_van_gebruiker`), geen
    blokkade hier.

    Waarborgen (server-side, onvoorwaardelijk): eigen account nooit, systeem-actor nooit,
    de laatste actieve Beheerder nooit."""
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan het eigen account niet archiveren")
    _weiger_systeem_actor(doel_gebruiker_id)
    now = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None or gebruiker.gepseudonimiseerd_op is not None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.status == GebruikerStatus.GEARCHIVEERD:
            raise AuthError("Gebruiker is al gearchiveerd")
        if (
            gebruiker.rol == GebruikerRol.BEHEERDER
            and gebruiker.status == GebruikerStatus.ACTIEF
            and _tel_overige_actieve_beheerders(session, behalve_gebruiker_id=doel_gebruiker_id) == 0
        ):
            raise AuthError("De laatste actieve Beheerder kan niet gearchiveerd worden")
        oude_status = gebruiker.status
        gebruiker.status_voor_archivering = oude_status.value
        gebruiker.status = GebruikerStatus.GEARCHIVEERD
        gebruiker.gearchiveerd_op = now
        gebruiker.gearchiveerd_door = actor_id
        _intrek_alle_sessies(session, doel_gebruiker_id, now=now)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="gebruiker",
            record_id=doel_gebruiker_id,
            actie="gebruiker_gearchiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": oude_status.value},
            nieuwe_waarde={"status": GebruikerStatus.GEARCHIVEERD.value},
        )


def dearchiveer_gebruiker(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID) -> None:
    """Haal een gebruiker uit het archief: exact de status van vóór archivering terug (óók
    'geblokkeerd' als dat zo was — dan blijft de blokkade staan tot heractiveren). Sessies komen
    niet terug: opnieuw inloggen."""
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan het eigen account niet dearchiveren")
    _weiger_systeem_actor(doel_gebruiker_id)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None or gebruiker.gepseudonimiseerd_op is not None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.status != GebruikerStatus.GEARCHIVEERD:
            raise AuthError("Gebruiker is niet gearchiveerd")
        doel_status = (
            GebruikerStatus(gebruiker.status_voor_archivering)
            if gebruiker.status_voor_archivering
            else GebruikerStatus.ACTIEF
        )
        gebruiker.status = doel_status
        gebruiker.status_voor_archivering = None
        gebruiker.gearchiveerd_op = None
        gebruiker.gearchiveerd_door = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="gebruiker",
            record_id=doel_gebruiker_id,
            actie="gebruiker_gedearchiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"status": GebruikerStatus.GEARCHIVEERD.value},
            nieuwe_waarde={"status": doel_status.value},
        )


def voeg_scope_toe(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan de eigen scope niet wijzigen")
    _weiger_systeem_actor(doel_gebruiker_id)
    with scoped_session(None, actor_id=actor_id) as session:
        bestaat_al = session.get(GebruikerAdministratie, (doel_gebruiker_id, administratie_id))
        if bestaat_al is None:
            session.add(GebruikerAdministratie(gebruiker_id=doel_gebruiker_id, administratie_id=administratie_id))


def verwijder_scope(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    if actor_id == doel_gebruiker_id:
        raise AuthError("Kan de eigen scope niet wijzigen")
    _weiger_systeem_actor(doel_gebruiker_id)
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
        # Gearchiveerde administraties (v2 30-08, `actief` = false) vallen uit álle werk-lijsten;
        # het Beheer-scherm haalt ze apart op achter het filter "gearchiveerd (N)".
        if rol == GebruikerRol.BEHEERDER:
            return list(
                session.scalars(
                    select(Administratie).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
                )
            )
        rijen = session.scalars(
            select(Administratie)
            .join(GebruikerAdministratie, GebruikerAdministratie.administratie_id == Administratie.id)
            .where(GebruikerAdministratie.gebruiker_id == actor_id, Administratie.actief.is_(True))
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
    # Open herstel-link (soort wachtwoord_herstel, migratie 0068) — apart van de uitnodiging,
    # zodat het scherm "herstel-link verstuurd" kan tonen zonder het account als
    # 'nog niet geactiveerd' te lezen.
    open_herstel_verloopt_op: datetime | None
    geblokkeerd_op: datetime | None
    geblokkeerd_door_naam: str | None
    gearchiveerd_op: datetime | None = None
    gearchiveerd_door_naam: str | None = None
    # Externe app-rol met wachtwoord maar zonder actieve passkey (28-08, casus Haci).
    half_geactiveerd: bool = False


def lijst_gebruikers(*, actor_id: uuid.UUID, inclusief_gearchiveerd: bool = False) -> list[GebruikerOverzicht]:
    """Gebruikerslijst voor Gebruikers & toegang — Beheerder-only (router-dependency; de
    RLS-beheerder-bypass op gebruiker_administratie maakt de scope-kolom platform-breed
    leesbaar). Gepseudonimiseerde gebruikers (AVG) blijven buiten de lijst, net als de
    systeem-actor (achtergrondverwerking — een technische rij, geen beheerbaar account;
    controls-review 2026-08-16: hij verscheen als muteerbare rij in Gebruikers & toegang).
    Gearchiveerde gebruikers (0075) blijven standaard buiten de lijst; het scherm vraagt ze
    expliciet op (`inclusief_gearchiveerd`) voor het filter "gearchiveerd (N)"."""
    now = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        query = select(Gebruiker).where(Gebruiker.gepseudonimiseerd_op.is_(None), Gebruiker.id != SYSTEEM_ACTOR_ID)
        if not inclusief_gearchiveerd:
            query = query.where(Gebruiker.status != GebruikerStatus.GEARCHIVEERD)
        gebruikers = list(session.scalars(query.order_by(Gebruiker.naam)))
        scope_rijen = session.execute(
            select(GebruikerAdministratie.gebruiker_id, GebruikerAdministratie.administratie_id)
        ).all()
        totp_ids = set(session.scalars(select(TotpSecret.gebruiker_id).where(TotpSecret.bevestigd_op.is_not(None))))
        passkeys = dict(
            session.execute(
                select(WebauthnCredential.gebruiker_id, func.count())
                .where(WebauthnCredential.ingetrokken_op.is_(None))
                .group_by(WebauthnCredential.gebruiker_id)
            ).all()
        )
        open_links = session.execute(
            select(Uitnodiging.gebruiker_id, Uitnodiging.soort, func.max(Uitnodiging.verloopt_op))
            .where(Uitnodiging.gebruikt_op.is_(None), Uitnodiging.verloopt_op > now)
            .group_by(Uitnodiging.gebruiker_id, Uitnodiging.soort)
        ).all()
        open_uitnodigingen = {gid: tot for gid, soort, tot in open_links if soort == UitnodigingSoort.UITNODIGING.value}
        open_herstellinks = {
            gid: tot for gid, soort, tot in open_links if soort == UitnodigingSoort.WACHTWOORD_HERSTEL.value
        }
        # Naam van de blokkeerder apart opgehaald: die kan zelf gepseudonimiseerd of de
        # systeem-actor zijn en dus buiten de lijst hierboven vallen.
        blokkeerder_ids = {g.geblokkeerd_door for g in gebruikers if g.geblokkeerd_door is not None} | {
            g.gearchiveerd_door for g in gebruikers if g.gearchiveerd_door is not None
        }
        blokkeerder_namen = (
            dict(session.execute(select(Gebruiker.id, Gebruiker.naam).where(Gebruiker.id.in_(blokkeerder_ids))).all())
            if blokkeerder_ids
            else {}
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
            open_herstel_verloopt_op=open_herstellinks.get(g.id),
            geblokkeerd_op=g.geblokkeerd_op,
            geblokkeerd_door_naam=(
                blokkeerder_namen.get(g.geblokkeerd_door) if g.geblokkeerd_door is not None else None
            ),
            gearchiveerd_op=g.gearchiveerd_op,
            gearchiveerd_door_naam=(
                blokkeerder_namen.get(g.gearchiveerd_door) if g.gearchiveerd_door is not None else None
            ),
            half_geactiveerd=(
                is_externe_app_rol(g.rol)
                and g.wachtwoord_hash is not None
                and passkeys.get(g.id, 0) == 0
                and g.status in (GebruikerStatus.ACTIEF, GebruikerStatus.WACHT_OP_PASSKEY)
            ),
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
    """ "Opnieuw mailen" (Gebruikers & toegang): het oorspronkelijke token bestaat alleen als
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


def maak_herstel_link(*, actor_id: uuid.UUID, gebruiker_id: uuid.UUID) -> VernieuwdeUitnodiging:
    """ "Herstel-link sturen" (Gebruikers & toegang, Beheerder-only via de router-dependency;
    feedbackronde 25-08 punt 7). Voor een al geactiveerde EXTERNE gebruiker (accordeur/veldwerker;
    status actief of wacht_op_passkey = wachtwoord ooit gezet) die zijn wachtwoord kwijt is —
    bv. ná een kill-switch op zijn enige apparaat. Zelfde token-mechaniek als de uitnodiging
    (hash-only, 72 u, eenmalig), soort `wachtwoord_herstel`; ALLE nog-open links van de
    gebruiker (uitnodiging óf herstel) verlopen per direct — één werkende link tegelijk. Niets
    anders wijzigt: status, passkeys, akkoorden en scope blijven staan tot de gebruiker de link
    verzilvert. Geen selfservice 'wachtwoord vergeten' (bewust — kantoor blijft poortwachter).
    Kantoorrollen vallen buiten dit pad (die hebben wachtwoord+TOTP mét eigen herstelroute via
    de Beheerder — blokkeren/opnieuw uitnodigen), een geblokkeerd account eerst heractiveren."""
    _weiger_systeem_actor(gebruiker_id)
    token = secrets.token_urlsafe(32)
    verloopt_op = datetime.now(UTC) + INVITE_TTL
    uitnodiging_id = uuid.uuid4()
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, gebruiker_id)
        if gebruiker is None or gebruiker.gepseudonimiseerd_op is not None:
            raise AuthError("Onbekende gebruiker")
        if not is_externe_app_rol(gebruiker.rol):
            raise AuthError("Een herstel-link is alleen voor externe app-gebruikers (accordeur/veldwerker)")
        if gebruiker.status == GebruikerStatus.GEBLOKKEERD:
            raise AuthError("Gebruiker is geblokkeerd — heractiveer eerst")
        if gebruiker.status == GebruikerStatus.GEARCHIVEERD:
            raise AuthError("Gebruiker is gearchiveerd — dearchiveer eerst")
        if gebruiker.status not in (GebruikerStatus.ACTIEF, GebruikerStatus.WACHT_OP_PASSKEY):
            raise AuthError("Account is nog niet geactiveerd — gebruik 'Opnieuw mailen' voor de uitnodiging")
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
                soort=UitnodigingSoort.WACHTWOORD_HERSTEL.value,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="platform.uitnodiging",
            record_id=uitnodiging_id,
            actie="wachtwoord_herstel_link_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker_id),
                "rol": gebruiker.rol.value,
                "status": gebruiker.status.value,
                "verloopt_op": verloopt_op.isoformat(),
            },
        )
    return VernieuwdeUitnodiging(
        resultaat=UitnodigingResultaat(
            uitnodiging_id=uitnodiging_id, gebruiker_id=gebruiker_id, token=token, verloopt_op=verloopt_op
        ),
        naam=naam,
        e_mail=e_mail,
    )


@dataclass(frozen=True)
class EMailGewijzigd:
    gebruiker_id: uuid.UUID
    naam: str
    oud_e_mail: str
    nieuw_e_mail: str
    # Gevuld als het account nog niet geactiveerd was: verse uitnodiging (oude links ongeldig).
    vernieuwde_uitnodiging: UitnodigingResultaat | None


def wijzig_e_mail(*, actor_id: uuid.UUID, doel_gebruiker_id: uuid.UUID, nieuw_e_mail: str) -> EMailGewijzigd:
    """A5 (steigerbouw-run 25-08, Beheerder-only via de router): het e-mailadres ís de login.
    Uniciteitscheck (409), systeem-actor nooit. Niet-geactiveerd account (uitgenodigd) → alle
    open uitnodigingslinks vervallen + een verse uitnodiging naar het nieuwe adres (de router
    mailt). Geactiveerd account → alleen de login wijzigt: passkeys, TOTP, sessies en historie
    hangen aan het account-id, niet aan het adres. Audit oud→nieuw.

    Punt 22 (opruimrun 28-08, casus Haci): de status-weigeringen voor geblokkeerd/gearchiveerd zijn
    VERVALLEN — het adres vrijmaken mag zonder de carrousel dearchiveren → wijzigen → archiveren.
    Bij een GEARCHIVEERD account gaat er nooit een uitnodigingsmail (ook niet als het vóór de
    archivering nog 'uitgenodigd' was): open links vervallen, alleen het adres wijzigt + audit."""
    _weiger_systeem_actor(doel_gebruiker_id)
    nieuw = normaliseer_e_mail(nieuw_e_mail)
    if "@" not in nieuw or nieuw.startswith("@") or nieuw.endswith("@"):
        raise AuthError("Ongeldig e-mailadres")
    now = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        gebruiker = session.get(Gebruiker, doel_gebruiker_id)
        if gebruiker is None:
            raise AuthError("Onbekende gebruiker")
        if gebruiker.e_mail == nieuw:
            raise AuthError("Dit is al het huidige e-mailadres")
        bezet = session.scalars(select(Gebruiker.id).where(Gebruiker.e_mail == nieuw)).first()
        if bezet is not None:
            raise AuthError("Dit e-mailadres is al in gebruik door een andere gebruiker")
        oud = gebruiker.e_mail
        gebruiker.e_mail = nieuw
        vernieuwd: UitnodigingResultaat | None = None
        if gebruiker.status in (GebruikerStatus.UITGENODIGD, GebruikerStatus.GEARCHIVEERD):
            open_links = session.scalars(
                select(Uitnodiging).where(
                    Uitnodiging.gebruiker_id == gebruiker.id,
                    Uitnodiging.gebruikt_op.is_(None),
                    Uitnodiging.soort == UitnodigingSoort.UITNODIGING.value,
                )
            ).all()
            for link in open_links:
                link.gebruikt_op = now  # oude links (naar het oude adres) ongeldig
        if gebruiker.status == GebruikerStatus.UITGENODIGD:
            token = secrets.token_urlsafe(32)
            verloopt_op = now + INVITE_TTL
            uitnodiging_id = uuid.uuid4()
            session.add(
                Uitnodiging(
                    id=uitnodiging_id,
                    gebruiker_id=gebruiker.id,
                    token_hash=_hash_token(token),
                    aangemaakt_door=actor_id,
                    verloopt_op=verloopt_op,
                )
            )
            vernieuwd = UitnodigingResultaat(
                uitnodiging_id=uitnodiging_id, gebruiker_id=gebruiker.id, token=token, verloopt_op=verloopt_op
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="gebruiker",
            record_id=gebruiker.id,
            actie="e_mail_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"e_mail": oud},
            nieuwe_waarde={
                "e_mail": nieuw,
                "status": gebruiker.status.value,
                "uitnodiging_vernieuwd": vernieuwd is not None,
            },
        )
        return EMailGewijzigd(
            gebruiker_id=gebruiker.id,
            naam=gebruiker.naam,
            oud_e_mail=oud,
            nieuw_e_mail=nieuw,
            vernieuwde_uitnodiging=vernieuwd,
        )
