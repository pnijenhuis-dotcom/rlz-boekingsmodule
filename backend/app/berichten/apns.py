"""APNs-verzending (native store-app iOS, fase 3 — verkenning/17 (b): APNs direct, .p8).

Token-based auth (RFC 7519 / Apple "Establishing a token-based connection to APNs"):
een ES256-JWT gesigneerd met de .p8-sleutel uit het Apple Developer-account, hergebruikt
tot ~50 minuten (Apple eist 20–60 min). Transport is verplicht HTTP/2 → httpx met http2=True
(dependency httpx[http2]).

Zelfde fail-onderscheid als push.py zodat de adapterlaag uniform blijft:
- 400 BadDeviceToken / 410 Unregistered → subscriptie vervallen (aanroeper trekt in);
- overige fouten → zichtbaar falen, aanroeper beslist (e-mail-terugval).
"""

from __future__ import annotations

import contextlib
import json
import time

from app.config import settings

_APNS_PRODUCTIE = "https://api.push.apple.com"
_APNS_SANDBOX = "https://api.sandbox.push.apple.com"
_JWT_LEVENSDUUR_SECONDEN = 50 * 60

# (token, uitgegeven_op) — module-cache; APNs weigert JWT's ouder dan 60 min én meer dan
# ~1 vernieuwing per 20 min, dus hergebruik is verplicht gedrag, geen optimalisatie.
_jwt_cache: tuple[str, float] | None = None


class ApnsFout(Exception):
    pass


class ApnsNietGeconfigureerd(ApnsFout):
    pass


class ApnsTokenVervallen(ApnsFout):
    """Het device-token is niet (meer) geldig — subscriptie intrekken, nooit blijven posten."""


def is_geconfigureerd() -> bool:
    return bool(settings.apns_key_p8 and settings.apns_key_id and settings.apple_team_id)


def _maak_jwt() -> str:
    global _jwt_cache
    nu = time.time()
    if _jwt_cache is not None and nu - _jwt_cache[1] < _JWT_LEVENSDUUR_SECONDEN:
        return _jwt_cache[0]
    import jwt as pyjwt

    token = pyjwt.encode(
        {"iss": settings.apple_team_id, "iat": int(nu)},
        settings.apns_key_p8,
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )
    _jwt_cache = (token, nu)
    return token


def verzend_apns(device_token: str, *, titel: str, tekst: str, url: str) -> None:
    """Eén alert-notificatie naar één iOS-apparaat. Payload minimaal (dataminimalisatie op het
    lockscreen, zelfde principe als Web Push): titel + tekst + deep-link; de app opent de
    deep-link bij de tap (pushClient-seam, nooit goedkeuren-vanuit-de-melding)."""
    if not is_geconfigureerd():
        raise ApnsNietGeconfigureerd("APNs niet geconfigureerd (APNS_KEY_P8/APNS_KEY_ID/APPLE_TEAM_ID).")
    # Lazy import (pyproject-patroon): httpx' HTTP/2-stack alleen laden waar er echt verzonden wordt.
    import httpx

    basis = _APNS_SANDBOX if settings.apns_sandbox else _APNS_PRODUCTIE
    payload = {
        "aps": {"alert": {"title": titel, "body": tekst}, "sound": "default"},
        "url": url,
    }
    try:
        with httpx.Client(http2=True, timeout=10) as client:
            antwoord = client.post(
                f"{basis}/3/device/{device_token}",
                content=json.dumps(payload),
                headers={
                    "authorization": f"bearer {_maak_jwt()}",
                    "apns-topic": settings.native_app_bundle_id,
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                },
            )
    except httpx.HTTPError as exc:
        raise ApnsFout(f"APNs niet bereikbaar: {exc}") from exc
    if antwoord.status_code == 200:
        return
    reden = ""
    with contextlib.suppress(ValueError):
        reden = str(antwoord.json().get("reason", ""))
    if antwoord.status_code == 410 or reden in ("BadDeviceToken", "Unregistered", "ExpiredToken"):
        raise ApnsTokenVervallen(f"APNs-token vervallen ({antwoord.status_code}/{reden})")
    raise ApnsFout(f"APNs weigerde ({antwoord.status_code}/{reden})")
