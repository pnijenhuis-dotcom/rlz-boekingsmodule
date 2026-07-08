from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials
from app.sync import schemas, service

router = APIRouter(tags=["sync"])


@router.post(
    "/administraties/{administratie_id}/sync/ledgers",
    response_model=schemas.SyncTellingResponse,
)
def sync_ledgers_trigger(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SyncTellingResponse:
    """On-demand trigger (koppelcontract §2c) voor de ververs-knop. Nu met gebruikers-auth +
    administratie-scope (dezelfde dependency als document-upload); het service-to-service
    platform-JWT voor de vastgoed-kant komt bij de Cloud-uitrol — lezen blijft altijd via de
    gedeelde tabel, nooit via dit endpoint (§2c: "lezen nooit via endpoint")."""
    try:
        telling = service.sync_ledgers(administratie_id=administratie_id)
    except service.SyncFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RlzApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.SyncTellingResponse(
        aangemaakt=telling.aangemaakt, bijgewerkt=telling.bijgewerkt, verdwenen=telling.verdwenen
    )
