"""Inzicht › Open vragen kantoorbreed (design-ronde 03-09 blok B2, mockup inzicht-kantoorbreed.html ④):
één lijst over álle administraties in scope, oudste eerst, paginering 25, facet-filters. Kantoorrol
vereist (router-breed, fail-closed); de scope zelf komt uit `mijn_administraties` + RLS per
administratie in de service. Leesroutes — geen mutaties, geen RLZ-calls."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, vereis_kantoorrol
from app.vragen import schemas, service

router = APIRouter(prefix="/vragen", tags=["vragen"], dependencies=[Depends(vereis_kantoorrol)])


def _rij(r: service.OpenVraagRij) -> schemas.OpenVraagRijDto:
    return schemas.OpenVraagRijDto(**r.__dict__)


def _tellers(t: service.Tellers) -> schemas.OpenVragenTellersDto:
    return schemas.OpenVragenTellersDto(**t.__dict__)


@router.get("", response_model=schemas.OpenVragenLijstDto)
def open_vragen_lijst(
    pagina: int = Query(1, ge=1),
    administratie_id: uuid.UUID | None = Query(None),
    toegewezen: Literal["alle", "mij"] = Query("alle"),
    ouder_dan_dagen: int | None = Query(None, ge=0, le=3650),
    q: str = Query("", max_length=200),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.OpenVragenLijstDto:
    """Alle open vragen binnen de scope van de actor. `administratie_id` is een filter (buiten scope =
    nul rijen, nooit een 403), `toegewezen=mij` = de actor is aan de beurt, `ouder_dan_dagen` = wacht
    minstens N dagen; tellers + administratie-facet gaan over de ongefilterde scope-set."""
    try:
        lijst = service.lijst(
            actor_id=actor.id,
            rol=actor.rol,
            pagina=pagina,
            administratie_id=administratie_id,
            toegewezen=toegewezen,
            ouder_dan_dagen=ouder_dan_dagen,
            q=q,
        )
    except service.OpenVragenFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return schemas.OpenVragenLijstDto(
        rijen=[_rij(r) for r in lijst.rijen],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        tellers=_tellers(lijst.tellers),
        administraties=[schemas.OpenVragenAdministratieFacetDto(**f.__dict__) for f in lijst.administraties],
    )


@router.get("/stand", response_model=schemas.OpenVragenTellersDto)
def open_vragen_stand(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.OpenVragenTellersDto:
    """Lichte stand voor de KPI-kaart "Open vragen" op de werkvoorraad (B2.3) — zelfde definitie als de
    lijst, zodat kaart en lijst nooit uiteenlopen."""
    return _tellers(service.tellers(actor_id=actor.id, rol=actor.rol))
