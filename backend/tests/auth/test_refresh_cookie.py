from __future__ import annotations

import time
import uuid

import pyotp
from fastapi.testclient import TestClient

from app.main import app
from app.security.tokens import create_access_token
from app.security.totp import STEP_SECONDS

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _activeer_gebruiker(beheerder_id: uuid.UUID) -> tuple[str, str, str]:
    """Volledige activatie via de HTTP-laag (zelfde stappen als test_router_e2e.py) — geeft
    (e_mail, wachtwoord, secret) terug."""
    e_mail = f"{uuid.uuid4()}@test.local"
    wachtwoord = "een-heel-lang-wachtwoord"
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "Cookie Test", "e_mail": e_mail, "rol": "boekhouding", "administratie_ids": []},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    resp = client.post("/auth/uitnodigingen/accepteren", json={"token": token, "wachtwoord": wachtwoord})
    assert resp.status_code == 200, resp.text
    accept_data = resp.json()

    code = pyotp.TOTP(accept_data["secret"]).at(time.time())
    resp = client.post(
        "/auth/totp/bevestigen",
        json={"code": code},
        headers={"Authorization": f"Bearer {accept_data['totp_setup_token']}"},
    )
    assert resp.status_code == 200, resp.text
    return e_mail, wachtwoord, accept_data["secret"]


def test_login_zet_refresh_cookie_met_verwachte_vlaggen(beheerder_id: uuid.UUID) -> None:
    e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)

    login_code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
    resp = client.post("/auth/login", json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": login_code})
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "refresh_token" not in body
    assert set(body.keys()) == {"access_token", "token_type"}

    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    attributen = set_cookie.lower()
    assert "httponly" in attributen
    assert "samesite=strict" in attributen
    assert "path=/auth/token/vernieuwen" in attributen
    # settings.environment default is "dev" in tests -> secure=False (anders werkt lokaal http niet,
    # zelfde gate als de JWT-secret-fallback in app/security/tokens.py).
    assert "secure" not in attributen


def test_logout_wist_cookie_en_trekt_token_in(beheerder_id: uuid.UUID) -> None:
    e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)
    login_code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
    resp = client.post("/auth/login", json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": login_code})
    assert resp.status_code == 200, resp.text

    resp = client.post("/auth/logout")
    assert resp.status_code == 204, resp.text
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "refresh_token=" in set_cookie
    assert "max-age=0" in set_cookie

    resp = client.post("/auth/token/vernieuwen")
    assert resp.status_code == 401, resp.text


def test_logout_zonder_cookie_is_geen_fout() -> None:
    losse_client = TestClient(app)
    resp = losse_client.post("/auth/logout")
    assert resp.status_code == 204


def test_logout_overal_vereist_authenticatie() -> None:
    losse_client = TestClient(app)
    resp = losse_client.post("/auth/logout-overal")
    assert resp.status_code in (401, 403)


def test_logout_overal_via_http_trekt_sessie_in(beheerder_id: uuid.UUID) -> None:
    e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)
    login_code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
    resp = client.post("/auth/login", json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": login_code})
    assert resp.status_code == 200, resp.text
    access_token = resp.json()["access_token"]

    resp = client.post("/auth/logout-overal", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 204, resp.text

    resp = client.post("/auth/token/vernieuwen")
    assert resp.status_code == 401, resp.text
