"""Afdelingen-endpoints (blok A 28-08). Router-breed kantoor-only (rollen-gate-fix 2026-08-21);
lezen = administratie-scope (het controlescherm moet de keuzelijst kunnen tonen), schrijven =
Beheerder-only (project_verplicht-patroon)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.accordering import service as accordering_service
from app.afdelingen import schemas, service
from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol

router = APIRouter(tags=["afdelingen"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: service.AfdelingFout) -> HTTPException:
    if isinstance(exc, service.AfdelingNietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _naar_dto(a: service.AfdelingOverzicht) -> schemas.AfdelingDto:
    return schemas.AfdelingDto(
        id=a.id,
        naam=a.naam,
        is_terugval=a.is_terugval,
        actief=a.actief,
        route=[
            schemas.RouteLaagDto(
                volgnummer=laag.volgnummer,
                accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                accordeur_naam=laag.accordeur_naam,
                bedrag_drempel=laag.bedrag_drempel,
            )
            for laag in a.route
        ],
        staande_goedkeuringen=a.staande_goedkeuringen,
        gearchiveerd_op=a.gearchiveerd_op,
    )


@router.get("/administraties/{administratie_id}/afdelingen", response_model=schemas.AfdelingenLijstDto)
def afdelingen_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.AfdelingenLijstDto:
    """Scope-check, geen Beheerder-only: elke controleur die het controlescherm opent moet de
    afdelingen kunnen kiezen (net als de project-instelling)."""
    return schemas.AfdelingenLijstDto(
        ingeschakeld=service.is_ingeschakeld(administratie_id=administratie_id),
        afdelingen=[_naar_dto(a) for a in service.lijst(administratie_id=administratie_id)],
    )


@router.put("/administraties/{administratie_id}/afdelingen-instelling", response_model=schemas.AfdelingenInstellingDto)
def afdelingen_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.AfdelingenInstellingDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AfdelingenInstellingDto:
    try:
        ingeschakeld = service.zet_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.AfdelingFout as exc:
        raise _vertaal(exc) from exc
    return schemas.AfdelingenInstellingDto(ingeschakeld=ingeschakeld)


@router.post(
    "/administraties/{administratie_id}/afdelingen",
    response_model=schemas.AfdelingDto,
    status_code=status.HTTP_201_CREATED,
)
def afdeling_aanmaken(
    administratie_id: uuid.UUID,
    invoer: schemas.AfdelingAanmakenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AfdelingDto:
    try:
        return _naar_dto(service.maak_aan(actor_id=actor.id, administratie_id=administratie_id, naam=invoer.naam))
    except service.AfdelingFout as exc:
        raise _vertaal(exc) from exc


@router.post(
    "/administraties/{administratie_id}/afdelingen/{afdeling_id}/archiveren",
    status_code=status.HTTP_204_NO_CONTENT,
)
def afdeling_archiveren(
    administratie_id: uuid.UUID,
    afdeling_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.archiveer(actor_id=actor.id, administratie_id=administratie_id, afdeling_id=afdeling_id)
    except service.AfdelingFout as exc:
        raise _vertaal(exc) from exc


@router.get(
    "/administraties/{administratie_id}/afdelingen/{afdeling_id}/accordering/route",
    response_model=schemas.AfdelingRouteResponse,
)
def afdeling_route_ophalen(
    administratie_id: uuid.UUID,
    afdeling_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfdelingRouteResponse:
    try:
        lagen, namen = accordering_service.afdeling_route_ophalen(
            administratie_id=administratie_id, afdeling_id=afdeling_id
        )
    except accordering_service.AccorderingFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.AfdelingRouteResponse(
        afdeling_id=afdeling_id,
        lagen=[
            schemas.RouteLaagDto(
                volgnummer=laag.volgnummer,
                accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                accordeur_naam=namen.get(laag.accordeur_gebruiker_id),
                bedrag_drempel=laag.bedrag_drempel,
            )
            for laag in lagen
        ],
    )


@router.put(
    "/administraties/{administratie_id}/afdelingen/{afdeling_id}/accordering/route",
    response_model=schemas.AfdelingRouteResponse,
)
def afdeling_route_opslaan(
    administratie_id: uuid.UUID,
    afdeling_id: uuid.UUID,
    invoer: schemas.AfdelingRouteInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AfdelingRouteResponse:
    """Beheerder-only. Wijzigt de route van de afdeling, dan vervallen de lopende rondes van
    documenten in díe afdeling (zelfde patroon als de administratie-route, punt 2a)."""
    try:
        vervallen = accordering_service.afdeling_route_opslaan(
            administratie_id=administratie_id,
            afdeling_id=afdeling_id,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
            lagen=[
                accordering_service.LaagInput(
                    volgnummer=laag.volgnummer,
                    accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                    bedrag_drempel=laag.bedrag_drempel,
                )
                for laag in invoer.lagen
            ],
        )
    except accordering_service.AccorderingFout as exc:
        if isinstance(exc, accordering_service.GeenLagenIngesteld | accordering_service.OngeldigeAanbieding):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    antwoord = afdeling_route_ophalen(administratie_id, afdeling_id, actor)
    return antwoord.model_copy(update={"rondes_vervallen": vervallen})
