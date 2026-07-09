from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder
from app.beheer import schemas, service

router = APIRouter(tags=["beheer"])


@router.get(
    "/administraties/{administratie_id}/boeken-instelling",
    response_model=schemas.BoekenIngeschakeldDto,
)
def boeken_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.BoekenIngeschakeldDto:
    try:
        ingeschakeld = service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.BoekenIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.put(
    "/administraties/{administratie_id}/boeken-instelling",
    response_model=schemas.BoekenIngeschakeldDto,
)
def boeken_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.BoekenIngeschakeldDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.BoekenIngeschakeldDto:
    """Boeken-failsafe (a), per-administratie toggle — Beheerder-only (CLAUDE.md-taak 2.4)."""
    try:
        ingeschakeld = service.zet_boeken_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.BoekenIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.get(
    "/instellingen/boeken-kill-switch",
    response_model=schemas.BoekenIngeschakeldDto,
)
def kill_switch_ophalen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.BoekenIngeschakeldDto:
    return schemas.BoekenIngeschakeldDto(ingeschakeld=service.haal_globale_kill_switch_op())


@router.put(
    "/instellingen/boeken-kill-switch",
    response_model=schemas.BoekenIngeschakeldDto,
)
def kill_switch_zetten(
    invoer: schemas.BoekenIngeschakeldDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.BoekenIngeschakeldDto:
    """Boeken-failsafe (a), globale kill switch — Beheerder-only (CLAUDE.md-taak 2.4)."""
    try:
        ingeschakeld = service.zet_globale_kill_switch(actor_id=actor.id, ingeschakeld=invoer.ingeschakeld)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return schemas.BoekenIngeschakeldDto(ingeschakeld=ingeschakeld)
