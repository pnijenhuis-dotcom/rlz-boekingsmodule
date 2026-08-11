"""Logout over ECHTE HTTP (nazorg-fix 2026-08-11): de refresh-cookie is path-gebonden
(path=/auth/token/vernieuwen) en bereikte het oude /auth/logout in een echte browser nooit —
de server-side intrekking gebeurde daardoor feitelijk niet. TestClient negeert
cookie-path-matching (daarom zag geen TestClient-test dit); deze test gebruikt een
httpx.Client mét echte cookie-jar (RFC 6265-path-matching) tegen de uvicorn-subprocess."""

from __future__ import annotations

import time
import uuid

import httpx
import pyotp

from app.security.tokens import create_access_token
from app.security.totp import STEP_SECONDS

_CLIENT_TIMEOUT = 15.0
WACHTWOORD = "een-heel-lang-wachtwoord"


def _activeer_en_login(client: httpx.Client, beheerder_id: uuid.UUID) -> str:
    """Volledige activatie + login via de HTTP-laag (zelfde stappen als
    tests/auth/test_refresh_cookie.py) — de refresh-cookie landt in de jar van `client`
    mét zijn path-attribuut. Geeft het uitgegeven refresh-token terug."""
    e_mail = f"{uuid.uuid4()}@test.local"
    admin = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
    resp = client.post(
        "/auth/uitnodigingen",
        json={"naam": "Logout E2E", "e_mail": e_mail, "rol": "boekhouding", "administratie_ids": []},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/auth/uitnodigingen/accepteren", json={"token": resp.json()["token"], "wachtwoord": WACHTWOORD}
    )
    assert resp.status_code == 200, resp.text
    accept = resp.json()

    resp = client.post(
        "/auth/totp/bevestigen",
        json={"code": pyotp.TOTP(accept["secret"]).at(time.time())},
        headers={"Authorization": f"Bearer {accept['totp_setup_token']}"},
    )
    assert resp.status_code == 200, resp.text

    login_code = pyotp.TOTP(accept["secret"]).at(time.time() + STEP_SECONDS)
    resp = client.post(
        "/auth/login", json={"e_mail": e_mail, "wachtwoord": WACHTWOORD, "totp_code": login_code}
    )
    assert resp.status_code == 200, resp.text
    return resp.cookies["refresh_token"]


def test_logout_trekt_refresh_token_server_side_in(server: str, beheerder_id: uuid.UUID) -> None:
    with httpx.Client(base_url=server, timeout=_CLIENT_TIMEOUT) as client:
        refresh_token = _activeer_en_login(client, beheerder_id)

        # De jar stuurt de path-gebonden cookie alleen mee omdat het logout-endpoint ónder het
        # cookie-pad leeft. De 204 zelf bewijst niets (het endpoint is idempotent-stil zonder
        # cookie) — de replay-check hieronder is het echte bewijs.
        resp = client.post("/auth/token/vernieuwen/logout")
        assert resp.status_code == 204, resp.text

    # Server-side ingetrokken: hetzelfde token expliciet aanbieden faalt nu. Vóór de fix bleef
    # dit token gewoon werken (de cookie bereikte /auth/logout nooit, intrekking gebeurde niet).
    resp = httpx.post(
        f"{server}/auth/token/vernieuwen",
        cookies={"refresh_token": refresh_token},
        timeout=_CLIENT_TIMEOUT,
    )
    assert resp.status_code == 401, f"refresh-token niet ingetrokken: {resp.status_code} {resp.text}"


def test_oude_logout_route_buiten_cookie_pad_bestaat_niet(server: str) -> None:
    """Buiten het cookie-pad is een logout-endpoint per definitie een schijn-uitlog (de browser
    stuurt de cookie daar nooit heen) — de 404 houdt die regressie zichtbaar."""
    resp = httpx.post(f"{server}/auth/logout", timeout=_CLIENT_TIMEOUT)
    assert resp.status_code == 404
