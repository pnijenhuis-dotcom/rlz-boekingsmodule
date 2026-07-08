from __future__ import annotations

import hashlib
import time
import uuid

import pyotp
import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.security.tokens import create_refresh_token
from app.security.totp import STEP_SECONDS
from tests.auth.conftest import ActieveGebruiker


def _login_code(secret: str, *, stap_offset: int = 1) -> str:
    """Elke login vraagt een NIEUWE TOTP-stap: de enrollment-stap (bevestig_totp) en eerdere
    logins in dezelfde test hebben al stappen verbruikt (replay-bescherming, zie
    app/security/totp.py). stap_offset loopt op zodat opeenvolgende logins in één test elk hun
    eigen, nog-niet-geaccepteerde stap gebruiken."""
    return pyotp.TOTP(secret).at(time.time() + stap_offset * STEP_SECONDS)


def _login(gebruiker: ActieveGebruiker, *, stap_offset: int = 1, ip_adres: str | None = None) -> service.TokenPaar:
    return service.login(
        e_mail=gebruiker.e_mail,
        wachtwoord=gebruiker.wachtwoord,
        totp_code=_login_code(gebruiker.secret, stap_offset=stap_offset),
        ip_adres=ip_adres,
    )


def _audit_acties(admin_engine: Engine, *, tabel: str, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = :tabel AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"tabel": tabel, "id": record_id},
            )
            .scalars()
            .all()
        )


# --- Login-events -----------------------------------------------------------------------------


def test_login_geslaagd_schrijft_audit_event(actieve_gebruiker: ActieveGebruiker, admin_engine: Engine) -> None:
    paar = _login(actieve_gebruiker, ip_adres="203.0.113.5")
    assert paar.access_token
    assert paar.refresh_token

    acties = _audit_acties(admin_engine, tabel="gebruiker", record_id=actieve_gebruiker.id)
    assert acties == ["login_geslaagd"]

    with admin_engine.connect() as conn:
        nieuwe_waarde = conn.execute(
            text(
                "SELECT nieuwe_waarde FROM platform.audit_event "
                "WHERE tabel = 'gebruiker' AND record_id = :id AND actie = 'login_geslaagd'"
            ),
            {"id": actieve_gebruiker.id},
        ).scalar_one()
    assert nieuwe_waarde == {"ip": "203.0.113.5"}


def test_login_verkeerd_wachtwoord_schrijft_login_mislukt_en_faalt(
    actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    with pytest.raises(service.AuthError, match="Ongeldige inloggegevens"):
        service.login(
            e_mail=actieve_gebruiker.e_mail,
            wachtwoord="dit-is-het-verkeerde-wachtwoord",
            totp_code=_login_code(actieve_gebruiker.secret),
        )
    assert _audit_acties(admin_engine, tabel="gebruiker", record_id=actieve_gebruiker.id) == ["login_mislukt"]


def test_login_verkeerde_totp_schrijft_totp_mislukt_en_faalt(
    actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    with pytest.raises(service.AuthError, match="Ongeldige inloggegevens"):
        service.login(e_mail=actieve_gebruiker.e_mail, wachtwoord=actieve_gebruiker.wachtwoord, totp_code="000000")
    assert _audit_acties(admin_engine, tabel="gebruiker", record_id=actieve_gebruiker.id) == ["totp_mislukt"]


def test_login_onbekend_e_mailadres_faalt_zonder_audit_event(admin_engine: Engine) -> None:
    """Geen platform.gebruiker-rij om aan te koppelen (audit_event.actor_id is NOT NULL) — de
    afwezigheid van een audit-rij is hier het verwachte gedrag, geen omissie."""
    with pytest.raises(service.AuthError, match="Ongeldige inloggegevens"):
        service.login(e_mail="onbekend@test.local", wachtwoord="wat-dan-ook-1234", totp_code="000000")
    with admin_engine.connect() as conn:
        aantal = conn.execute(text("SELECT count(*) FROM platform.audit_event")).scalar_one()
    assert aantal == 0


# --- Rotatie -----------------------------------------------------------------------------------


def _token_status(admin_engine: Engine, refresh_token: str) -> tuple[bool, bool]:
    """(is_gebruikt, is_actief) voor het gegeven refresh-token."""
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    with admin_engine.connect() as conn:
        gebruikt_op, ingetrokken_op = conn.execute(
            text("SELECT gebruikt_op, ingetrokken_op FROM platform.refresh_token WHERE token_hash = :h"),
            {"h": token_hash},
        ).one()
    return (gebruikt_op is not None, ingetrokken_op is None)


def test_refresh_token_roteert_bij_elke_aanroep(actieve_gebruiker: ActieveGebruiker, admin_engine: Engine) -> None:
    """actieve_gebruiker doorloopt zelf al bevestig_totp() (die ook een TokenPaar uitgeeft) —
    deze test kijkt dus gericht naar de login()- en rotatie-tokens zelf, niet naar het volledige
    aantal rijen voor deze gebruiker (dat zou ook de activatie-rij meetellen)."""
    eerste = _login(actieve_gebruiker)
    tweede = service.vernieuw_token(refresh_token=eerste.refresh_token)

    assert tweede.refresh_token != eerste.refresh_token
    assert tweede.access_token != eerste.access_token

    assert _token_status(admin_engine, eerste.refresh_token) == (True, True)  # verbruikt, niet ingetrokken
    assert _token_status(admin_engine, tweede.refresh_token) == (False, True)  # nog niet verbruikt, actief

    # Het geroteerde token blijft zelf bruikbaar voor de volgende rotatie.
    derde = service.vernieuw_token(refresh_token=tweede.refresh_token)
    assert derde.refresh_token != tweede.refresh_token


def test_refresh_token_hergebruik_trekt_alle_sessies_in(
    actieve_gebruiker: ActieveGebruiker, admin_engine: Engine
) -> None:
    eerste = _login(actieve_gebruiker)
    tweede = service.vernieuw_token(refresh_token=eerste.refresh_token)  # rotatie: eerste is nu "gebruikt"

    # Het al-geroteerde token opnieuw aanbieden = hergebruik-signaal.
    with pytest.raises(service.AuthError, match="al gebruikt"):
        service.vernieuw_token(refresh_token=eerste.refresh_token)

    assert "refresh_token_hergebruik_gedetecteerd" in _audit_acties(
        admin_engine, tabel="refresh_token", record_id=_refresh_token_id(admin_engine, eerste.refresh_token)
    )

    # Alle sessies zijn ingetrokken — ook het net-geroteerde (op zich nog geldige) tweede token.
    with pytest.raises(service.AuthError, match="Ongeldig refresh-token|al gebruikt|ingetrokken"):
        service.vernieuw_token(refresh_token=tweede.refresh_token)

    with admin_engine.connect() as conn:
        alle_ingetrokken = conn.execute(
            text(
                "SELECT bool_and(ingetrokken_op IS NOT NULL) FROM platform.refresh_token WHERE gebruiker_id = :g"
            ),
            {"g": actieve_gebruiker.id},
        ).scalar_one()
    assert alle_ingetrokken is True


def _refresh_token_id(admin_engine: Engine, refresh_token: str) -> uuid.UUID:
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM platform.refresh_token WHERE token_hash = :h"), {"h": token_hash}
        ).scalar_one()


def test_refresh_token_verlopen_faalt(actieve_gebruiker: ActieveGebruiker, admin_engine: Engine) -> None:
    paar = _login(actieve_gebruiker)
    token_id = _refresh_token_id(admin_engine, paar.refresh_token)
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.refresh_token SET verloopt_op = now() - interval '1 hour' WHERE id = :id"),
            {"id": token_id},
        )
    with pytest.raises(service.AuthError, match="verlopen"):
        service.vernieuw_token(refresh_token=paar.refresh_token)


def test_onbekend_refresh_token_faalt(actieve_gebruiker: ActieveGebruiker) -> None:
    vreemd_token = create_refresh_token(actieve_gebruiker.id)
    with pytest.raises(service.AuthError, match="Ongeldig refresh-token"):
        service.vernieuw_token(refresh_token=vreemd_token)
