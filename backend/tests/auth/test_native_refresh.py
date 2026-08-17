"""Native token-kanaal (store-app fase 4, verkenning/17 (d) route 2): een client die zich
expliciet als native aandient (X-Native-Client) krijgt het refresh-token in de body i.p.v.
de cookie (Keychain/Keystore-flow); vernieuwen/logout accepteren het token als
X-Refresh-Token-header. Het web-pad blijft byte-voor-byte ongewijzigd (guards in
test_refresh_cookie.py)."""

from __future__ import annotations

import time
import uuid

import pyotp
from fastapi.testclient import TestClient

from app.main import app
from app.security.totp import STEP_SECONDS
from tests.auth.test_refresh_cookie import _activeer_gebruiker

# Eigen client: geen cookie-jar-vervuiling richting/vanuit andere testmodules.
client = TestClient(app)

NATIVE = {"X-Native-Client": "1"}


def _native_login(beheerder_id: uuid.UUID) -> dict:
    e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)
    login_code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
    resp = client.post(
        "/auth/login",
        json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": login_code},
        headers=NATIVE,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_native_login_geeft_paar_in_body_en_geen_cookie(beheerder_id: uuid.UUID) -> None:
    e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)
    login_code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
    resp = client.post(
        "/auth/login",
        json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": login_code},
        headers=NATIVE,
    )
    assert resp.status_code == 200
    assert "refresh_token=" not in resp.headers.get("set-cookie", "")
    assert resp.json()["refresh_token"]


def test_vernieuwen_via_header_roteert_en_geeft_nieuw_token_in_body(beheerder_id: uuid.UUID) -> None:
    eerste = _native_login(beheerder_id)
    resp = client.post("/auth/token/vernieuwen", headers={"X-Refresh-Token": eerste["refresh_token"]})
    assert resp.status_code == 200, resp.text
    tweede = resp.json()
    assert tweede["refresh_token"]
    assert tweede["refresh_token"] != eerste["refresh_token"]  # rotatie, zelfde semantiek als cookie-pad

    # Het geroteerde token werkt; het oude valt binnen de grace-periode niet als diefstal
    # (bestaande race-tolerante rotatie — hier niet hertest, zie test_refresh_hergebruik).
    resp = client.post("/auth/token/vernieuwen", headers={"X-Refresh-Token": tweede["refresh_token"]})
    assert resp.status_code == 200


def test_logout_via_header_trekt_de_sessie_in(beheerder_id: uuid.UUID) -> None:
    paar = _native_login(beheerder_id)
    resp = client.post("/auth/token/vernieuwen/logout", headers={"X-Refresh-Token": paar["refresh_token"]})
    assert resp.status_code == 204
    # Ingetrokken token vernieuwt niet meer.
    resp = client.post("/auth/token/vernieuwen", headers={"X-Refresh-Token": paar["refresh_token"]})
    assert resp.status_code == 401


def test_web_login_zonder_native_header_krijgt_nooit_een_body_token(beheerder_id: uuid.UUID) -> None:
    """De harde grens: zonder expliciete native-aankondiging blijft het web-contract exact
    zoals het was (cookie-only) — óók al bestaat het veld nu in het schema."""
    e_mail, wachtwoord, secret = _activeer_gebruiker(beheerder_id)
    login_code = pyotp.TOTP(secret).at(time.time() + STEP_SECONDS)
    resp = client.post("/auth/login", json={"e_mail": e_mail, "wachtwoord": wachtwoord, "totp_code": login_code})
    assert resp.status_code == 200
    assert "refresh_token" not in resp.json()
    assert "refresh_token=" in resp.headers.get("set-cookie", "")
