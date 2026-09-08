"""App-auth zonder passkey en TOTP — toestelbinding + activatiecode (besluit Peter 08-09-2026, migratie 0125).

De native accordeur-/veldwerker-app en de accordeur-PWA kennen nog precies één toegangspad:
uitnodiging → activatie op dít toestel (link óf 8-tekens activatiecode) → 5-cijferige toegangscode.
Toestel = factor 1 (langlevend apparaat-token in Keychain/Keystore/IndexedDB), toegangscode = factor 2
(lokaal anker, bereikt de server nooit). Passkey/WebAuthn, TOTP en wachtwoord verdwijnen uit de
app-oppervlakte; de kantoor-webapp blijft ongewijzigd (platformbesluit 0020 geldt dáár).

Hergebruik, geen nieuw auth-systeem: het toestel is een rij in `platform.webauthn_credential`
(`soort='toestel'`, `public_key=b"toestel"`) — kill-switch (`ingetrokken_op`), `RefreshToken.apparaat_id`,
de per-request-toets in deps en de push-subscripties werken er ongewijzigd op. De sessie komt uit
`service._issue_token_paar` (7-dagen sliding-TTL voor app-rollen, rotatie + hergebruik-detectie in
`service.vernieuw_token`). De link/code wordt atomair verbruikt via `service.rond_uitnodiging_af`.

Activatiecode: alfabet zonder 0/O/1/I (32 tekens), lengte 8, weergave XXXX-XXXX; server én client
normaliseren (hoofdletters, spaties/koppeltekens weg); opgeslagen wordt uitsluitend de sha256-hex.
Rate-limits: per uitnodiging max 5 pogingen per uur (kolommen op de rij) én per IP max 5 missers per
uur (`platform.activatiecode_poging`, over Cloud-Run-instanties heen). Geen account-enumeratie (0022):
een onbekende code en een ongeldige/verlopen link geven dezelfde 400-tekst."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.auth.rollen import EXTERNE_APP_ROLLEN, is_externe_app_rol
from app.auth.service import (
    AuthError,
    TokenPaar,
    _hash_token,
    _issue_token_paar,
    _login_metadata,
    _toets_externe_activatie_status,
    rond_uitnodiging_af,
)
from app.db.audit import record_audit_event
from app.db.models import (
    ActivatiecodePoging,
    Gebruiker,
    RefreshToken,
    Uitnodiging,
    UitnodigingSoort,
    WebauthnCredential,
    WebauthnCredentialSoort,
)
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

# --- activatiecode: alfabet, generatie, normalisatie, hash --------------------------------------------

ACTIVATIECODE_ALFABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 tekens: geen 0/O/1/I
ACTIVATIECODE_LENGTE = 8
_ALFABET_SET = frozenset(ACTIVATIECODE_ALFABET)

# UITSLUITEND het review-demo-account (scripts/cloud_seed_review_demo.py): `demo_herbruikbaar` op een
# uitnodiging wordt alleen gehonoreerd als de gebruiker dít adres heeft — voor elk ander account is de
# vlag betekenisloos (server-side afgedwongen, niet alleen in het seed-script).
REVIEW_DEMO_EMAIL = "p.nijenhuis+applereview@kempengroep.nl"

MAX_POGINGEN_PER_UITNODIGING = 5
MAX_MISSERS_PER_IP = 5
POGINGEN_VENSTER = timedelta(hours=1)

TOEGESTANE_PLATFORMS = ("ios", "android", "web")

# Foutteksten — leesbaar Nederlands, en bewust één tekst voor "onbekend/ongeldig/verlopen" (0022).
FOUT_ONGELDIG = "Deze activatiecode of link is niet (meer) geldig"
FOUT_AL_GEBRUIKT = "Deze uitnodiging is al op een ander toestel gebruikt — vraag het kantoor om een nieuwe uitnodiging"
FOUT_TE_VEEL_POGINGEN = (
    "Te veel pogingen — probeer het over een uur opnieuw of vraag het kantoor om een nieuwe uitnodiging"
)
FOUT_KANTOORROL = "Deze activatie is alleen voor app-gebruikers — kantoor activeert met wachtwoord + TOTP"
FOUT_ALLEEN_APP = "Deze activatie is alleen voor de app"


def genereer_activatiecode() -> str:
    """8 tekens uit het alfabet, cryptografisch random (secrets). Ongeformatteerd (XXXXXXXX)."""
    return "".join(secrets.choice(ACTIVATIECODE_ALFABET) for _ in range(ACTIVATIECODE_LENGTE))


def formatteer_activatiecode(code: str) -> str:
    """Weergave XXXX-XXXX (mail, Beheerder-respons, seed-script)."""
    kaal = normaliseer_activatiecode(code)
    return f"{kaal[:4]}-{kaal[4:]}" if len(kaal) == ACTIVATIECODE_LENGTE else kaal


def normaliseer_activatiecode(code: str) -> str:
    """Hoofdletters, spaties en koppeltekens weg — server én client doen exact dit."""
    return "".join(ch for ch in code.upper() if ch not in " -‐‑‒–—\t\n")


def is_geldig_activatiecode_formaat(code: str) -> bool:
    kaal = normaliseer_activatiecode(code)
    return len(kaal) == ACTIVATIECODE_LENGTE and all(ch in _ALFABET_SET for ch in kaal)


def hash_activatiecode(code: str) -> str:
    """sha256-hex van de genormaliseerde code — het enige dat de database ziet."""
    return hashlib.sha256(normaliseer_activatiecode(code).encode()).hexdigest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# --- domeinfouten (router → status) -----------------------------------------------------------------------


class ActivatieGeweigerd(AuthError):
    """400: onbekende/ongeldige/verlopen code of link, kantoor-rol, geblokkeerd account."""


class UitnodigingAlGebruikt(AuthError):
    """409: de link/code is al op een (ander) toestel verzilverd."""


class TeVeelPogingen(AuthError):
    """429: per uitnodiging > 5 pogingen per uur, óf per IP > 5 missers per uur."""


# --- rate-limit per IP ------------------------------------------------------------------------------------


def _ip_missers_laatste_uur(session: Session, *, ip: str, now: datetime) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ActivatiecodePoging)
            .where(ActivatiecodePoging.ip == ip, ActivatiecodePoging.tijdstip > now - POGINGEN_VENSTER)
        )
        or 0
    )


def _registreer_ip_misser(*, ip: str | None) -> None:
    """Eigen transactie ná de hoofdtransactie (zelfde reden als het faal-audit in service.login: een raise
    in het with-blok zou de registratie mee terugrollen). Huishouding: rijen ouder dan het venster weg."""
    if not ip:
        return
    now = datetime.now(UTC)
    with scoped_session(None) as session:
        session.execute(delete(ActivatiecodePoging).where(ActivatiecodePoging.tijdstip < now - POGINGEN_VENSTER))
        session.add(ActivatiecodePoging(id=uuid.uuid4(), ip=ip, tijdstip=now))


# --- de activatie -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ToestelActivatie:
    token_paar: TokenPaar
    apparaat_id: uuid.UUID
    # base64url van `credential_id` — de meldsleutel van het toestel voor /auth/app-lock/* (5× foute
    # toegangscode → uitsluiting; hulpvraag). Leeft alleen op het toestel en bij de server.
    apparaat_credential_id: str
    naam: str
    herstel: bool


def _zoek_uitnodiging(session: Session, *, token: str | None, activatiecode: str | None) -> Uitnodiging | None:
    if token is not None:
        return session.scalars(select(Uitnodiging).where(Uitnodiging.token_hash == _hash_token(token))).one_or_none()
    assert activatiecode is not None
    if not is_geldig_activatiecode_formaat(activatiecode):
        return None
    return session.scalars(
        select(Uitnodiging).where(Uitnodiging.activatiecode_hash == hash_activatiecode(activatiecode))
    ).one_or_none()


def _tel_poging_op_uitnodiging(uitnodiging: Uitnodiging, *, now: datetime) -> bool:
    """Venster van een uur per uitnodiging; True = deze poging valt nog binnen het maximum. De teller wordt
    hier verhoogd en bij een geslaagde activatie door rond_uitnodiging_af weer op nul gezet."""
    vanaf = uitnodiging.activatiecode_pogingen_vanaf
    if vanaf is None or now - vanaf > POGINGEN_VENSTER:
        uitnodiging.activatiecode_pogingen = 0
        uitnodiging.activatiecode_pogingen_vanaf = now
    if uitnodiging.activatiecode_pogingen >= MAX_POGINGEN_PER_UITNODIGING:
        return False
    uitnodiging.activatiecode_pogingen += 1
    return True


def _trek_oude_toestellen_in(
    session: Session, *, gebruiker: Gebruiker, behalve: uuid.UUID, now: datetime, ip_adres: str | None
) -> int:
    """Herstel = toestel opnieuw koppelen: de eerdere toestel-rijen van de gebruiker gaan dicht via het
    kill-switch-pad (credential + gebonden refresh-tokens + push, audit `apparaat_ingetrokken`) — zelfde
    schrijver-semantiek als webauthn_service.trek_apparaat_in, hier bínnen de activatie-transactie. Waarom
    niet alleen sessies intrekken (`_intrek_alle_sessies`, gebeurt óók): een verloren toestel dat later zijn
    ingetrokken refresh-token aanbiedt, valt dan op de apparaat-poort (401, alleen dat toestel) en niet op de
    hergebruik-detectie, die uit voorzorg ÁLLE sessies — dus ook het nieuwe toestel — zou beëindigen.
    Legacy passkey-rijen blijven ongemoeid (sunset-pad; CLI app-passkeys-markeren)."""
    from app.berichten.models import PushSubscriptie

    oude = session.scalars(
        select(WebauthnCredential).where(
            WebauthnCredential.gebruiker_id == gebruiker.id,
            WebauthnCredential.soort == WebauthnCredentialSoort.TOESTEL.value,
            WebauthnCredential.ingetrokken_op.is_(None),
            WebauthnCredential.id != behalve,
        )
    ).all()
    for rij in oude:
        rij.ingetrokken_op = now
        rij.ingetrokken_door = gebruiker.id
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.apparaat_id == rij.id, RefreshToken.ingetrokken_op.is_(None))
            .values(ingetrokken_op=now)
        )
        session.execute(
            update(PushSubscriptie)
            .where(PushSubscriptie.apparaat_id == rij.id, PushSubscriptie.ingetrokken_op.is_(None))
            .values(ingetrokken_op=now, ingetrokken_reden="kill_switch")
        )
        record_audit_event(
            session,
            actor_id=gebruiker.id,
            module="platform",
            tabel="webauthn_credential",
            record_id=rij.id,
            actie="apparaat_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"ingetrokken_op": None},
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker.id),
                "apparaat_naam": rij.apparaat_naam,
                "soort": rij.soort,
                "aanleiding": "herstel_nieuw_toestel",
                "ingetrokken_op": now.isoformat(),
                **(_login_metadata(ip_adres) or {}),
            },
        )
    return len(oude)


def activeer_toestel(
    *,
    token: str | None,
    activatiecode: str | None,
    toestel_naam: str | None,
    platform: str | None,
    ip_adres: str | None,
) -> ToestelActivatie:
    """Eén transactie: rate-limit IP → uitnodiging zoeken (link óf code) → rate-limit per uitnodiging →
    poorten (gebruikt/verlopen/rol/status) → toestel-rij → rond_uitnodiging_af (verse uitnodiging: actief +
    `activatie_afgerond`; herstel: alle sessies + oude toestel-rijen ingetrokken + `wachtwoord_hersteld`,
    `via: toestel`) → audit
    `toestel_geactiveerd` op de toestel-rij (NOOIT de code) → token-paar aan het toestel gebonden.

    Faalpaden raise-n pas ná het with-blok: de pogingen-teller op de uitnodiging en het weigerings-audit
    moeten juist WEL gecommit worden; de IP-misser gaat in een eigen transactie. Op het succespad rolt een
    AuthError uit rond_uitnodiging_af de hele activatie terug (geen halve toestel-rij)."""
    if (token is None) == (activatiecode is None):
        raise ActivatieGeweigerd("Geef óf een activatiecode óf een link op")
    if platform is not None and platform not in TOEGESTANE_PLATFORMS:
        raise ActivatieGeweigerd("Onbekend platform")

    fout: AuthError | None = None
    resultaat: ToestelActivatie | None = None
    now = datetime.now(UTC)

    with scoped_session(None) as session:
        if ip_adres and _ip_missers_laatste_uur(session, ip=ip_adres, now=now) >= MAX_MISSERS_PER_IP:
            raise TeVeelPogingen(FOUT_TE_VEEL_POGINGEN)  # niets te committen, geen extra misser-rij

        uitnodiging = _zoek_uitnodiging(session, token=token, activatiecode=activatiecode)
        if uitnodiging is None:
            fout = ActivatieGeweigerd(FOUT_ONGELDIG)
        else:
            gebruiker = session.get(Gebruiker, uitnodiging.gebruiker_id)
            assert gebruiker is not None  # FK garandeert dit
            demo = bool(uitnodiging.demo_herbruikbaar) and gebruiker.e_mail == REVIEW_DEMO_EMAIL
            if not _tel_poging_op_uitnodiging(uitnodiging, now=now):
                fout = TeVeelPogingen(FOUT_TE_VEEL_POGINGEN)
            elif uitnodiging.gebruikt_op is not None:
                fout = UitnodigingAlGebruikt(FOUT_AL_GEBRUIKT)
            elif uitnodiging.verloopt_op < now:  # demo-code: verloopt_op 2099 (seed) — nooit stil eeuwig
                fout = ActivatieGeweigerd(FOUT_ONGELDIG)
            elif not is_externe_app_rol(gebruiker.rol):
                fout = ActivatieGeweigerd(FOUT_KANTOORROL)
            else:
                try:
                    _toets_externe_activatie_status(uitnodiging, gebruiker)
                except AuthError as exc:
                    fout = ActivatieGeweigerd(str(exc))
            if fout is not None:
                record_audit_event(
                    session,
                    actor_id=gebruiker.id,
                    module="platform",
                    tabel="gebruiker",
                    record_id=gebruiker.id,
                    actie="toestel_activatie_geweigerd",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "uitnodiging_id": str(uitnodiging.id),
                        "via": "link" if token is not None else "code",
                        "reden": type(fout).__name__,
                        "pogingen": uitnodiging.activatiecode_pogingen,
                        **(_login_metadata(ip_adres) or {}),
                    },
                )
            else:
                herstel = uitnodiging.soort == UitnodigingSoort.WACHTWOORD_HERSTEL.value
                rij = WebauthnCredential(
                    id=uuid.uuid4(),
                    gebruiker_id=gebruiker.id,
                    credential_id=secrets.token_bytes(16),
                    public_key=b"toestel",
                    sign_count=0,
                    apparaat_naam=toestel_naam,
                    soort=WebauthnCredentialSoort.TOESTEL.value,
                    platform=platform,
                    is_dev_stub=False,
                    laatst_gebruikt_op=now,
                )
                session.add(rij)
                session.flush()
                rond_uitnodiging_af(
                    session,
                    gebruiker=gebruiker,
                    uitnodiging_id=uitnodiging.id,
                    now=now,
                    via="toestel",
                    demo_herbruikbaar=demo,
                )
                oude_toestellen = 0
                if herstel and not demo:
                    oude_toestellen = _trek_oude_toestellen_in(
                        session, gebruiker=gebruiker, behalve=rij.id, now=now, ip_adres=ip_adres
                    )
                record_audit_event(
                    session,
                    actor_id=gebruiker.id,
                    module="platform",
                    tabel="webauthn_credential",
                    record_id=rij.id,
                    actie="toestel_geactiveerd",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "via": "link" if token is not None else "code",
                        "platform": platform,
                        "apparaat_naam": toestel_naam,
                        "herstel": herstel,
                        "oude_toestellen_ingetrokken": oude_toestellen,
                        "demo_herbruikbaar": demo,
                        "uitnodiging_id": str(uitnodiging.id),
                        **(_login_metadata(ip_adres) or {}),
                    },
                )
                paar = _issue_token_paar(session, gebruiker_id=gebruiker.id, rol=gebruiker.rol, apparaat_id=rij.id)
                resultaat = ToestelActivatie(
                    token_paar=paar,
                    apparaat_id=rij.id,
                    apparaat_credential_id=_b64url(rij.credential_id),
                    naam=gebruiker.naam,
                    herstel=herstel,
                )

    if fout is not None:
        _registreer_ip_misser(ip=ip_adres)
        raise fout
    assert resultaat is not None
    return resultaat


# --- toegangscode gewijzigd (lokaal anker; de server krijgt alleen het feit) ---------------------------------


def meld_toegangscode_gewijzigd(*, actor_id: uuid.UUID, apparaat_id: uuid.UUID) -> None:
    """Instellingen › "Toegangscode wijzigen" in de app: de code zelf bereikt de server nooit — alleen het
    audit-feit op de toestel-rij (record = apparaat, actor = gebruiker). Een apparaat dat niet van de actor
    is of niet bestaat antwoordt als 'onbekend' (geen bestaans-lek)."""
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(WebauthnCredential, apparaat_id)
        if rij is None or rij.gebruiker_id != actor_id:
            raise AuthError("Onbekend apparaat")
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="webauthn_credential",
            record_id=apparaat_id,
            actie="toegangscode_gewijzigd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"soort": rij.soort},
        )


# --- CLI: legacy app-passkeys markeren ------------------------------------------------------------------------


def markeer_app_passkeys(*, dry_run: bool = False) -> dict[str, int]:
    """`app-passkeys-markeren`: zet `niet_meer_gebruikt_op = now()` op alle passkey-rijen van gebruikers met een
    externe app-rol die nog niet gemarkeerd zijn — audit `passkey_niet_meer_gebruikt` per rij (systeem-actor).
    NIETS verwijderen, `ingetrokken_op` ONGEMOEID: bestaande sessies op oude toestellen blijven werken tot
    hun TTL (blok 2-eis). Geeft het aantal per rol terug; --dry-run telt alleen."""
    now = datetime.now(UTC)
    per_rol: dict[str, int] = {}
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.execute(
            select(WebauthnCredential, Gebruiker.rol)
            .join(Gebruiker, Gebruiker.id == WebauthnCredential.gebruiker_id)
            .where(
                Gebruiker.rol.in_(list(EXTERNE_APP_ROLLEN)),
                WebauthnCredential.soort == WebauthnCredentialSoort.PASSKEY.value,
                WebauthnCredential.niet_meer_gebruikt_op.is_(None),
            )
            .order_by(WebauthnCredential.aangemaakt_op)
        ).all()
        for rij, rol in rijen:
            per_rol[rol.value] = per_rol.get(rol.value, 0) + 1
            if dry_run:
                continue
            rij.niet_meer_gebruikt_op = now
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="platform",
                tabel="webauthn_credential",
                record_id=rij.id,
                actie="passkey_niet_meer_gebruikt",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"niet_meer_gebruikt_op": None},
                nieuwe_waarde={
                    "niet_meer_gebruikt_op": now.isoformat(),
                    "gebruiker_id": str(rij.gebruiker_id),
                    "rol": rol.value,
                    "ingetrokken_op_ongemoeid": True,
                },
            )
    return per_rol
