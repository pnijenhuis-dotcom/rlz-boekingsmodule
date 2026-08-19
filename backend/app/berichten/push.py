"""Push-verzending — adapterlaag over de drie subscriptie-soorten (fase 3 native store-apps).

webpush = dunne schil om pywebpush (VAPID, RFC 8292): payload-encryptie en de POST naar de
push-dienst van de browser (Apple/Google/Mozilla); apns/fcm = de native store-apps
(app/berichten/apns.py resp. fcm.py). De aanroepers (verzending.py) merken niets van de
soort: één verzend_push per subscriptie, uniforme fouten.

Fail-onderscheid voor de aanroeper (alle soorten):
- PushNietGeconfigureerd — die soort heeft geen sleutels op deze omgeving: terugvallen op e-mail.
- PushSubscriptieVervallen — de push-dienst zegt dat endpoint/token niet meer bestaat:
  aanroeper markeert 'm ingetrokken (reden 'vervallen') en valt terug — nooit eeuwig blijven
  posten op een dood endpoint.
- PushVerzendFout — al het andere (netwerk, 5xx): zichtbaar falen, aanroeper beslist."""

from __future__ import annotations

import json

from app.berichten import apns, fcm
from app.berichten.models import PushSoort, PushSubscriptie
from app.config import settings


class PushFout(Exception):
    """Basisfout van het pushkanaal."""


class PushNietGeconfigureerd(PushFout):
    pass


class PushSubscriptieVervallen(PushFout):
    pass


class PushVerzendFout(PushFout):
    pass


def is_geconfigureerd(soort: str = PushSoort.WEBPUSH.value) -> bool:
    if soort == PushSoort.APNS.value:
        return apns.is_geconfigureerd()
    if soort == PushSoort.FCM.value:
        return fcm.is_geconfigureerd()
    return bool(settings.push_vapid_private_key and settings.push_vapid_public_key)


def verzend_push(subscriptie: PushSubscriptie, *, payload: dict) -> None:
    """Verzend één pushbericht naar één subscriptie (apparaat), via de adapter van de soort.
    Payload is een klein JSON-object ({titel, tekst, url} + extra's) — geen financiële details
    in de notificatie zelf, alleen aantal + deep-link (dataminimalisatie op het lockscreen)."""
    if subscriptie.soort == PushSoort.APNS.value:
        _verzend_apns(subscriptie, payload)
        return
    if subscriptie.soort == PushSoort.FCM.value:
        _verzend_fcm(subscriptie, payload)
        return
    _verzend_webpush(subscriptie, payload)


def _verzend_apns(subscriptie: PushSubscriptie, payload: dict) -> None:
    try:
        apns.verzend_apns(
            subscriptie.endpoint,
            titel=str(payload.get("titel", "Nijenhuis Boekingsmodule")),
            tekst=str(payload.get("tekst", "")),
            url=str(payload.get("url", "/accordeur")),
        )
    except apns.ApnsNietGeconfigureerd as exc:
        raise PushNietGeconfigureerd(str(exc)) from exc
    except apns.ApnsTokenVervallen as exc:
        raise PushSubscriptieVervallen(str(exc)) from exc
    except apns.ApnsFout as exc:
        raise PushVerzendFout(str(exc)) from exc


def _verzend_fcm(subscriptie: PushSubscriptie, payload: dict) -> None:
    try:
        fcm.verzend_fcm(
            subscriptie.endpoint,
            titel=str(payload.get("titel", "Nijenhuis Boekingsmodule")),
            tekst=str(payload.get("tekst", "")),
            url=str(payload.get("url", "/accordeur")),
        )
    except fcm.FcmNietGeconfigureerd as exc:
        raise PushNietGeconfigureerd(str(exc)) from exc
    except fcm.FcmTokenVervallen as exc:
        raise PushSubscriptieVervallen(str(exc)) from exc
    except fcm.FcmFout as exc:
        raise PushVerzendFout(str(exc)) from exc


def _verzend_webpush(subscriptie: PushSubscriptie, payload: dict) -> None:
    if not is_geconfigureerd(PushSoort.WEBPUSH.value):
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
