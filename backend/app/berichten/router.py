"""Notificatie-endpoints (berichten-bouwsteen): push-subscripties voor de accordeur-PWA.

Autorisatie: klant-accordeur mét voorwaarden-akkoord (zelfde fail-closed poort als de
wachtrij — les AUTH-nazorg 2026-08-11: geen accordeur-endpoints buiten die poort) én een
apparaat-gebonden sessie (passkey) — de subscriptie hangt aan dat apparaat zodat de
kill-switch 'm mee intrekt."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import voorwaarden
from app.auth.deps import CurrentGebruiker, get_current_gebruiker
from app.berichten import schemas, service
from app.config import settings
from app.db.models import GebruikerRol

router = APIRouter(prefix="/notificaties", tags=["notificaties"])

VOORWAARDEN_AKKOORD_VEREIST = "voorwaarden_akkoord_vereist"


def _vereis_accordeur_met_akkoord(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> CurrentGebruiker:
    if actor.rol != GebruikerRol.KLANT_ACCORDEUR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor klant-accordeurs (PWA)"
        )
    if not voorwaarden.heeft_akkoord(gebruiker_id=actor.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=VOORWAARDEN_AKKOORD_VEREIST)
    return actor


@router.get("/push/config", response_model=schemas.PushConfigResponse)
def push_config(actor: CurrentGebruiker = Depends(_vereis_accordeur_met_akkoord)) -> schemas.PushConfigResponse:
    """VAPID-publieke sleutel (client: applicationServerKey). None = push niet geconfigureerd
    op deze omgeving — de PWA verbergt de aanzet-knop dan."""
    return schemas.PushConfigResponse(publieke_sleutel=settings.push_vapid_public_key)


@router.post(
    "/push/subscripties",
    response_model=schemas.PushSubscriptieResponse,
    status_code=status.HTTP_201_CREATED,
)
def subscriptie_registreren(
    payload: schemas.PushSubscriptieRequest,
    actor: CurrentGebruiker = Depends(_vereis_accordeur_met_akkoord),
) -> schemas.PushSubscriptieResponse:
    try:
        data = service.registreer_subscriptie(
            gebruiker_id=actor.id,
            apparaat_id=actor.apparaat_id,
            endpoint=payload.endpoint,
            p256dh=payload.p256dh,
            auth=payload.auth,
        )
    except service.ApparaatVereist as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.PushSubscriptieResponse(id=data.id, endpoint=data.endpoint, aangemaakt_op=data.aangemaakt_op)


@router.post("/push/subscripties/intrekken", status_code=status.HTTP_204_NO_CONTENT)
def subscriptie_intrekken(
    payload: schemas.PushSubscriptieIntrekkenRequest,
    actor: CurrentGebruiker = Depends(_vereis_accordeur_met_akkoord),
) -> None:
    try:
        service.trek_subscriptie_in(gebruiker_id=actor.id, endpoint=payload.endpoint)
    except service.OnbekendeSubscriptie as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
