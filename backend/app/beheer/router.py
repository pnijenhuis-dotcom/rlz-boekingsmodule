from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope
from app.beheer import schemas, service

router = APIRouter(tags=["beheer"])


@router.get(
    "/instellingen/administraties",
    response_model=schemas.AdministratieInstellingenLijstDto,
)
def administratie_instellingen_lijst(
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AdministratieInstellingenLijstDto:
    """Instellingen-scherm (design-pass taak 3): alle administraties met beide schakelaars in
    één response — Beheerder-only, net als de losse per-administratie/globale endpoints."""
    overzicht = service.overzicht_administratie_instellingen()
    return schemas.AdministratieInstellingenLijstDto(
        administraties=[
            schemas.AdministratieInstellingenDto(
                id=r.administratie_id,
                naam=r.naam,
                boeken_ingeschakeld=r.boeken_ingeschakeld,
                project_verplicht=r.project_verplicht,
            )
            for r in overzicht
        ]
    )


@router.get(
    "/administraties/{administratie_id}/project-instelling",
    response_model=schemas.ProjectVerplichtDto,
)
def project_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ProjectVerplichtDto:
    """Scope-check, geen Beheerder-only: elke gebruiker die het controlescherm van deze
    administratie mag openen, moet kunnen weten of de Project-kolom verplicht is (design-pass
    taak 4) — dit is geen gevoelige beheerinstelling zoals de boeken-toggle."""
    try:
        verplicht = service.haal_project_verplicht_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ProjectVerplichtDto(verplicht=verplicht)


@router.put(
    "/administraties/{administratie_id}/project-instelling",
    response_model=schemas.ProjectVerplichtDto,
)
def project_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.ProjectVerplichtDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ProjectVerplichtDto:
    """Wijzigen blijft wél Beheerder-only, net als de boeken-toggle."""
    try:
        verplicht = service.zet_project_verplicht(
            actor_id=actor.id, administratie_id=administratie_id, verplicht=invoer.verplicht
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ProjectVerplichtDto(verplicht=verplicht)


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
