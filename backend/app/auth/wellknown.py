"""Passkey-domeinkoppeling voor de native store-apps (fase 2, GO Peter 2026-08-16).

De apex (rp_id, besluit 0022) moet twee well-known-bestanden serveren zodat het OS de app
aan het domein koppelt — zónder die keten weigert iOS/Android de passkey-prompt in de app:

- iOS:     /.well-known/apple-app-site-association  (webcredentials → <team>.<bundle>)
- Android: /.well-known/assetlinks.json             (get_login_creds → pakket + key-hash)

Fail-closed: zolang de bijbehorende settings leeg zijn (team-id resp. vingerafdrukken)
antwoordt de route 404 — er wordt nooit een halve of onjuiste koppeling gepubliceerd.
Geen auth op deze routes (het OS haalt ze anoniem op); inhoud is uitsluitend publieke
configuratie, nooit secret-materiaal.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(tags=["wellknown"])


@router.get("/.well-known/apple-app-site-association", include_in_schema=False)
def apple_app_site_association() -> JSONResponse:
    if not settings.apple_team_id or not settings.native_app_bundle_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    app_id = f"{settings.apple_team_id}.{settings.native_app_bundle_id}"
    # Apple vereist Content-Type application/json (het pad heeft bewust geen extensie).
    return JSONResponse(content={"webcredentials": {"apps": [app_id]}})


@router.get("/.well-known/assetlinks.json", include_in_schema=False)
def assetlinks() -> JSONResponse:
    if not settings.android_cert_sha256_vingerafdrukken or not settings.native_app_bundle_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return JSONResponse(
        content=[
            {
                "relation": [
                    "delegate_permission/common.handle_all_urls",
                    "delegate_permission/common.get_login_creds",
                ],
                "target": {
                    "namespace": "android_app",
                    "package_name": settings.native_app_bundle_id,
                    "sha256_cert_fingerprints": list(settings.android_cert_sha256_vingerafdrukken),
                },
            }
        ]
    )
