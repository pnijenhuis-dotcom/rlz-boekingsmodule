"""Mini-voorraad-API (CONTRACT_F): prefix /mini-voorraad/{administratie_id}/…, router-breed `vereis_kantoorrol` +
`vereis_administratie_scope` per route; archiveren/dearchiveren Beheerder-only.

⑧ BEWUST AFWEZIG: er is geen PUT/PATCH/DELETE op producten of mutaties en geen route die een stand of aantal zet.
De enige POST's zijn "naam-bevestigen" (weergavenaam), "archiveren"/"dearchiveren" (kolom) en "beschadigingen"
(gebeurtenis-registratie mét verplicht project). `tests/mini_voorraad/test_router.py::test_geen_mutatie_endpoint`
loopt de routerlijst af en houdt dat zo."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.mini_voorraad import schemas, service

router = APIRouter(prefix="/mini-voorraad", tags=["mini-voorraad"], dependencies=[Depends(vereis_kantoorrol)])

#: Whitelist van niet-GET-routes (padstaart) — alles anders is per definitie een fout (⑧). De routertest toetst dit.
TOEGESTANE_POST_STAARTEN = ("/naam-bevestigen", "/archiveren", "/dearchiveren", "/beschadigingen")


def _vertaal(exc: service.MiniVoorraadFout) -> HTTPException:
    if isinstance(exc, service.MiniVoorraadUitgeschakeld):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.ProductNietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, service.OngeldigeInvoer):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _product_dto(p: service.ProductData) -> schemas.ProductDto:
    return schemas.ProductDto(**p.__dict__)


def _mutatie_dto(m: service.MutatieData) -> schemas.MutatieDto:
    return schemas.MutatieDto(**m.__dict__)


@router.get("/{administratie_id}/producten", response_model=schemas.ProductLijstDto)
def producten(
    administratie_id: uuid.UUID,
    q: str = Query(""),
    pagina: int = Query(1, ge=1),
    filter: str = Query("alle"),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProductLijstDto:
    try:
        lijst = service.producten(
            administratie_id=administratie_id, actor_id=actor.id, q=q, pagina=pagina, filter=filter
        )
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ProductLijstDto(
        items=[_product_dto(p) for p in lijst.items],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        nieuw_controleren=lijst.nieuw_controleren,
        ingeschakeld=lijst.ingeschakeld,
    )


@router.get("/{administratie_id}/stand", response_model=schemas.StandDto)
def stand(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.StandDto:
    s = service.stand(administratie_id=administratie_id, actor_id=actor.id)
    return schemas.StandDto(**s.__dict__)


@router.get("/{administratie_id}/materiaallijst", response_model=schemas.MateriaallijstDto)
def materiaallijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.MateriaallijstDto:
    """F5: read-only mini-producten mét stand > 0 voor de Materiaallijst-dialoog van planning/transport."""
    try:
        items = service.materiaallijst(administratie_id=administratie_id, actor_id=actor.id)
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.MateriaallijstDto(
        categorie=service.VIRTUELE_GROEP_NAAM, items=[schemas.MateriaallijstItemDto(**i.__dict__) for i in items]
    )


@router.get("/{administratie_id}/producten/{product_id}/log", response_model=schemas.LogLijstDto)
def log(
    administratie_id: uuid.UUID,
    product_id: uuid.UUID,
    pagina: int = Query(1, ge=1),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.LogLijstDto:
    try:
        lijst = service.log(administratie_id=administratie_id, actor_id=actor.id, product_id=product_id, pagina=pagina)
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.LogLijstDto(
        items=[_mutatie_dto(m) for m in lijst.items],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
    )


@router.post("/{administratie_id}/producten/{product_id}/naam-bevestigen", response_model=schemas.ProductDto)
def naam_bevestigen(
    administratie_id: uuid.UUID,
    product_id: uuid.UUID,
    invoer: schemas.NaamBevestigenRequest,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProductDto:
    """Wijzigt uitsluitend de weergavenaam en zet de vlag uit — nooit een aantal (⑦)."""
    try:
        p = service.bevestig_naam(
            administratie_id=administratie_id,
            actor_id=actor.id,
            product_id=product_id,
            weergavenaam=invoer.weergavenaam,
        )
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return _product_dto(p)


@router.post("/{administratie_id}/producten/{product_id}/archiveren", response_model=schemas.ProductDto)
def archiveren(
    administratie_id: uuid.UUID,
    product_id: uuid.UUID,
    invoer: schemas.ArchiverenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProductDto:
    try:
        p = service.archiveer(
            administratie_id=administratie_id, actor_id=actor.id, product_id=product_id, reden=invoer.reden
        )
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return _product_dto(p)


@router.post("/{administratie_id}/producten/{product_id}/dearchiveren", response_model=schemas.ProductDto)
def dearchiveren(
    administratie_id: uuid.UUID,
    product_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProductDto:
    try:
        p = service.dearchiveer(administratie_id=administratie_id, actor_id=actor.id, product_id=product_id)
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return _product_dto(p)


@router.post(
    "/{administratie_id}/beschadigingen", response_model=schemas.MutatieDto, status_code=status.HTTP_201_CREATED
)
def beschadiging_melden(
    administratie_id: uuid.UUID,
    invoer: schemas.BeschadigingRequest,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MutatieDto:
    """Gebeurtenis-registratie (wie/waar/wanneer) — de enige afname-bron náást de verkoopfactuur; project verplicht."""
    try:
        m = service.meld_beschadiging(
            administratie_id=administratie_id,
            actor_id=actor.id,
            product_id=invoer.product_id,
            aantal=invoer.aantal,
            project_id=invoer.project_id,
            datum=invoer.datum,
            toelichting=invoer.toelichting,
        )
    except service.MiniVoorraadFout as exc:
        raise _vertaal(exc) from exc
    return _mutatie_dto(m)
