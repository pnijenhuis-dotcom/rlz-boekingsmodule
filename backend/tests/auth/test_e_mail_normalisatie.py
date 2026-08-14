"""Regressietests e-mail-normalisatie (bugfix 2026-08-14, live door Peter op de cloud gevonden):
login deed een case-gevoelige e-mailmatch. Structurele fix: normalisatie (lowercase + trim) op
élke ingang (app/auth/normalisatie.py) + DB-CHECK op de genormaliseerde vorm (migratie 0049)."""

from __future__ import annotations

import time
import uuid

import pyotp
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.auth import service, webauthn_service
from app.auth.normalisatie import normaliseer_e_mail
from app.db.models import GebruikerRol
from app.security.totp import STEP_SECONDS


def test_normaliseer_e_mail_lowercase_en_trim() -> None:
    assert normaliseer_e_mail("  Peter@AK-Nijenhuis.NL ") == "peter@ak-nijenhuis.nl"


def test_aanmaak_met_hoofdletters_en_login_in_kleine_letters(beheerder_id: uuid.UUID) -> None:
    """De cloud-casus zelf: uitnodiging aangemaakt met hoofdletters, inloggen in kleine letters."""
    uniek = uuid.uuid4().hex
    wachtwoord = "een-heel-lang-wachtwoord"
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Hoofdletter Gebruiker",
        e_mail=f"Hoofdletters.{uniek}@Test.LOCAL",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord=wachtwoord)
    secret = acceptatie.secret
    service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=pyotp.TOTP(secret).now())

    # Volgende TOTP-stap (+30s): de enrollment-stap is al verbruikt (replay-bescherming) en
    # verify_code accepteert één stap clock-skew vooruit — patroon test_refresh_tokens.
    paar = service.login(
        e_mail=f"hoofdletters.{uniek}@test.local",
        wachtwoord=wachtwoord,
        totp_code=pyotp.TOTP(secret).at(time.time() + STEP_SECONDS),
    )
    assert paar.access_token


def test_accordeur_login_is_case_ongevoelig(beheerder_id: uuid.UUID) -> None:
    uniek = uuid.uuid4().hex
    wachtwoord = "een-heel-lang-wachtwoord"
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Accordeur Hoofdletters",
        e_mail=f"Accordeur.{uniek}@Test.LOCAL",
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[],
    )
    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord=wachtwoord)
    assert acceptatie.soort == "passkey"

    login = webauthn_service.start_accordeur_login(e_mail=f"ACCORDEUR.{uniek}@test.local", wachtwoord=wachtwoord)
    assert login.passkey_setup_token


def test_db_check_weigert_niet_genormaliseerde_e_mail(admin_engine: Engine) -> None:
    """Het harde slot (migratie 0049): ook een schrijfpad dat de normalisatie omzeilt, kan geen
    case-gevoelig account meer maken."""
    with pytest.raises(IntegrityError, match="ck_gebruiker_e_mail_lowercase"), admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Omzeiler', :mail, 'boekhouding', 'uitgenodigd')"
            ),
            {"id": uuid.uuid4(), "mail": f"Omzeiler.{uuid.uuid4().hex}@test.local"},
        )
