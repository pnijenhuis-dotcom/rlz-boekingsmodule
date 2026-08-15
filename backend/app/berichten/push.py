"""Web Push-verzending (accordeur-PWA, berichten-bouwsteen).

Dunne schil om pywebpush (VAPID, RFC 8292): payload-encryptie en de POST naar de push-dienst
van de browser (Apple/Google/Mozilla). Sleutels via config/Secret Manager; de public key gaat
naar de client bij het subscriben (applicationServerKey).

Fail-onderscheid voor de aanroeper:
- PushNietGeconfigureerd — geen VAPID-sleutels (dev zonder push): terugvallen op e-mail.
- PushSubscriptieVervallen — de push-dienst zegt 404/410: subscriptie bestaat niet meer,
  aanroeper markeert 'm ingetrokken (reden 'vervallen') en valt terug — nooit eeuwig blijven
  posten op een dood endpoint.
- PushVerzendFout — al het andere (netwerk, 5xx): zichtbaar falen, aanroeper beslist."""

from __future__ import annotations

import json

from app.berichten.models import PushSubscriptie
from app.config import settings


class PushFout(Exception):
    """Basisfout van het pushkanaal."""


class PushNietGeconfigureerd(PushFout):
    pass


class PushSubscriptieVervallen(PushFout):
    pass


class PushVerzendFout(PushFout):
    pass


def is_geconfigureerd() -> bool:
    return bool(settings.push_vapid_private_key and settings.push_vapid_public_key)


def verzend_push(subscriptie: PushSubscriptie, *, payload: dict) -> None:
    """Verzend één pushbericht naar één subscriptie (apparaat). Payload is een klein
    JSON-object dat de service worker (accordeur-sw.js) toont — geen financiële details in de
    notificatie zelf, alleen aantal + deep-link (dataminimalisatie op het lockscreen)."""
    if not is_geconfigureerd():
        raise PushNietGeconfigureerd("Web Push niet geconfigureerd (PUSH_VAPID_*-sleutels ontbreken).")
    # Lazy import: pywebpush (en zijn crypto-stack) alleen laden waar er echt gepusht wordt —
    # zelfde patroon als de GCS/KMS-clients (pyproject-toelichting).
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": subscriptie.endpoint,
                "keys": {"p256dh": subscriptie.p256dh, "auth": subscriptie.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.push_vapid_private_key,
            vapid_claims={"sub": settings.push_vapid_onderwerp},
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            raise PushSubscriptieVervallen(f"Subscriptie vervallen ({status}): {subscriptie.endpoint}") from exc
        raise PushVerzendFout(f"Push niet verzonden (status {status}): {exc}") from exc
