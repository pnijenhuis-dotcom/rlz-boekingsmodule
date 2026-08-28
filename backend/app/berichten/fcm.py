"""FCM-verzending (native store-app Android, fase 3 — verkenning/17 (b): FCM HTTP v1).

Auth (Android-bouwronde 28-08): Firebase zit in hetzelfde GCP-project als de backend, dus de
standaardroute is **Application Default Credentials** — op Cloud Run de identiteit van de
service/job (run-backend@ / run-jobs@) via de metadata-server, met IAM-rol
roles/firebasecloudmessaging.admin; er bestaat géén los server-key-secret. Het project-id komt
expliciet uit FCM_PROJECT_ID (nooit stil uit ADC afgeleid). Terugval: een service-account-JSON
(FCM_SERVICE_ACCOUNT_JSON, project-id uit de JSON) voor omgevingen zonder ADC — staat die, dan
wint die. AVG-lijn: de payload bevat alleen aantal + deep-link (dataminimalisatie, zelfde
principe als Web Push) — de gegevensstroom via Google is als notitie vastgelegd bij de
config-setting.

Zelfde fail-onderscheid als push.py/apns.py:
- 404 / UNREGISTERED → registratietoken vervallen (aanroeper trekt de subscriptie in);
- overige fouten → zichtbaar falen, aanroeper beslist (e-mail-terugval).
"""

from __future__ import annotations

import contextlib
import json

from app.config import settings

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

# Module-cache: google-auth-Credentials vernieuwen hun access-token zelf; alleen het opzetten
# (JSON parsen resp. ADC-detectie) hoeft niet per bericht.
_credentials_cache: tuple[object, str] | None = None


class FcmFout(Exception):
    pass


class FcmNietGeconfigureerd(FcmFout):
    pass


class FcmTokenVervallen(FcmFout):
    """Het registratietoken is niet (meer) geldig — subscriptie intrekken."""


def is_geconfigureerd() -> bool:
    return bool(settings.fcm_project_id or settings.fcm_service_account_json)


def _credentials_en_project() -> tuple[object, str]:
    """Credentials + project-id, éénmalig opgezet. Volgorde: expliciete service-account-JSON
    (terugval) → Application Default Credentials (Cloud Run-identiteit; standaard)."""
    global _credentials_cache
    if _credentials_cache is not None:
        return _credentials_cache
    if settings.fcm_service_account_json:
        from google.oauth2 import service_account

        info = json.loads(settings.fcm_service_account_json)
        project_id = str(info.get("project_id", "") or settings.fcm_project_id or "")
        if not project_id:
            raise FcmNietGeconfigureerd("FCM-service-account-JSON zonder project_id.")
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[_FCM_SCOPE])
    else:
        project_id = str(settings.fcm_project_id or "")
        if not project_id:
            raise FcmNietGeconfigureerd("FCM niet geconfigureerd (FCM_PROJECT_ID).")
        import google.auth
        from google.auth import exceptions as auth_exceptions

        try:
            credentials, _adc_project = google.auth.default(scopes=[_FCM_SCOPE])
        except auth_exceptions.DefaultCredentialsError as exc:
            # Geen ADC (lokale dev zonder gcloud-login): zichtbaar falen als 'niet geconfigureerd'
            # zodat de aanroeper netjes op e-mail terugvalt i.p.v. een kale stacktrace.
            raise FcmNietGeconfigureerd(f"FCM: geen Application Default Credentials ({exc}).") from exc
    _credentials_cache = (credentials, project_id)
    return _credentials_cache


def _access_token() -> tuple[str, str]:
    from google.auth.transport.requests import Request

    credentials, project_id = _credentials_en_project()
    if not getattr(credentials, "valid", False):
        credentials.refresh(Request())  # type: ignore[attr-defined]
    return str(getattr(credentials, "token", "")), project_id


def verzend_fcm(registratie_token: str, *, titel: str, tekst: str, url: str) -> None:
    """Eén notificatie naar één Android-apparaat (FCM HTTP v1). De deep-link reist als
    data-veld mee; de app opent 'm bij de tap (pushClient-seam)."""
    if not is_geconfigureerd():
        raise FcmNietGeconfigureerd("FCM niet geconfigureerd (FCM_PROJECT_ID / FCM_SERVICE_ACCOUNT_JSON).")
    import httpx

    access_token, project_id = _access_token()
    bericht = {
        "message": {
            "token": registratie_token,
            "notification": {"title": titel, "body": tekst},
            "data": {"url": url},
        }
    }
    try:
        antwoord = httpx.post(
            f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
            json=bericht,
            headers={"authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise FcmFout(f"FCM niet bereikbaar: {exc}") from exc
    if antwoord.status_code == 200:
        return
    detail = ""
    with contextlib.suppress(ValueError):
        detail = json.dumps(antwoord.json().get("error", {}))
    if antwoord.status_code == 404 or "UNREGISTERED" in detail:
        raise FcmTokenVervallen(f"FCM-token vervallen ({antwoord.status_code})")
    raise FcmFout(f"FCM weigerde ({antwoord.status_code}): {detail[:200]}")
