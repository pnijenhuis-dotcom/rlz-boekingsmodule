from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.auth import service
from tests.auth.conftest import ActieveGebruiker
from tests.auth.test_refresh_tokens import _login, _token_status


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


def test_logout_trekt_alleen_huidige_sessie_in(actieve_gebruiker: ActieveGebruiker, admin_engine: Engine) -> None:
    # activatie_paar (uitgegeven door bevestig_totp) en een login() erna zijn twee onafhankelijke
    # sessies — zie de docstring bij ActieveGebruiker voor waarom niet twee losse login()-aanroepen.
    sessie_a = actieve_gebruiker.activatie_paar
    sessie_b = _login(actieve_gebruiker)

    service.logout(refresh_token=sessie_a.refresh_token)

    assert _token_status(admin_engine, sessie_a.refresh_token) == (False, False)  # niet verbruikt, ingetrokken
    assert _token_status(admin_engine, sessie_b.refresh_token) == (False, True)  # onaangeroerd, nog actief

    # Andere sessie blijft echt bruikbaar.
    service.vernieuw_token(refresh_token=sessie_b.refresh_token)

    # De uitgelogde sessie werkt echt niet meer.
    with pytest.raises(service.AuthError):
        service.vernieuw_token(refresh_token=sessie_a.refresh_token)


def test_logout_schrijft_audit_event(actieve_gebruiker: ActieveGebruiker, admin_engine: Engine) -> None:
    sessie = _login(actieve_gebruiker)
    service.logout(refresh_token=sessie.refresh_token)

    with admin_engine.connect() as conn:
        token_id = conn.execute(
            text("SELECT id FROM platform.refresh_token WHERE gebruiker_id = :g AND ingetrokken_op IS NOT NULL"),
            {"g": actieve_gebruiker.id},
        ).scalar_one()
    assert _audit_acties(admin_engine, tabel="refresh_token", record_id=token_id) == ["logout"]


def test_logout_is_idempotent_en_stil_bij_onbekend_token() -> None:
    service.logout(refresh_token="niet-een-geldig-jwt")  # geen exception
    service.logout(refresh_token="niet-een-geldig-jwt")  # nogmaals, ook geen exception


def test_logout_overal_trekt_alle_sessies_in(actieve_gebruiker: ActieveGebruiker, admin_engine: Engine) -> None:
    sessie_a = actieve_gebruiker.activatie_paar
    sessie_b = _login(actieve_gebruiker)

    service.logout_overal(gebruiker_id=actieve_gebruiker.id)

    assert _token_status(admin_engine, sessie_a.refresh_token) == (False, False)
    assert _token_status(admin_engine, sessie_b.refresh_token) == (False, False)

    with pytest.raises(service.AuthError):
        service.vernieuw_token(refresh_token=sessie_a.refresh_token)
    with pytest.raises(service.AuthError):
        service.vernieuw_token(refresh_token=sessie_b.refresh_token)

    # ("login_geslaagd" staat er ook op, van de _login()-aanroep hierboven — dezelfde tabel/record.)
    assert "logout_overal" in _audit_acties(admin_engine, tabel="gebruiker", record_id=actieve_gebruiker.id)
