from __future__ import annotations

import uuid

import pyotp
import pytest
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol


def test_volledige_flow_tot_activatie(beheerder_id: uuid.UUID) -> None:
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Nieuwe Gebruiker",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")
    assert acceptatie.otpauth_uri.startswith("otpauth://totp/")

    code = pyotp.TOTP(acceptatie.secret).now()
    paar = service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=code)
    assert paar.access_token
    assert paar.refresh_token


def test_ongeldig_token_faalt(beheerder_id: uuid.UUID) -> None:
    with pytest.raises(service.AuthError, match="Ongeldig"):
        service.accepteer_uitnodiging(token="niet-bestaand-token", wachtwoord="een-heel-lang-wachtwoord")


def test_verlopen_token_faalt(beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Verlopen",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.uitnodiging SET verloopt_op = now() - interval '1 hour' WHERE id = :id"),
            {"id": resultaat.uitnodiging_id},
        )
    with pytest.raises(service.AuthError, match="verlopen"):
        service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")


def test_hergebruikt_token_faalt(beheerder_id: uuid.UUID) -> None:
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Hergebruik",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")
    with pytest.raises(service.AuthError, match="al gebruikt"):
        service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-ander-wachtwoord-12")


def test_te_kort_wachtwoord_faalt(beheerder_id: uuid.UUID) -> None:
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Kort",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    with pytest.raises(service.AuthError, match="minimaal"):
        service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="kort")


def test_totp_setup_token_is_eenmalig(beheerder_id: uuid.UUID) -> None:
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Dubbel",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord="een-heel-lang-wachtwoord")
    code = pyotp.TOTP(acceptatie.secret).now()
    service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=code)

    with pytest.raises(service.AuthError, match="Geen openstaande"):
        service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=code)
