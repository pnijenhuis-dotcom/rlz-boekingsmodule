"""Beheerder-only leesroutes (Feiten eerst, besluit Peter 17-09 punt 4 — Cowork leest via de Chrome-extensie onder Peters login):
`GET /lezen/queries` (bibliotheek), `POST /lezen/query/{naam}` (bibliotheek-query, RLS per administratie, systeem-scope = alles
in de scope van de Beheerder), `POST /lezen/sql` (vrije SELECT, uitsluitend op de leesreplica, rijenplafond 5.000, audit).
Router-breed `require_beheerder`; de fail-closed sweep (tests/security) eist 401/403 voor élke andere rol."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.deps import CurrentGebruiker, require_beheerder
from app.lezen import bibliotheek, service
from app.lezen.sql_poort import GeenSelect
from app.lezen.uitvoer import MAX_RIJEN_ROUTE, Resultaat

router = APIRouter(prefix="/lezen", tags=["lezen"], dependencies=[Depends(require_beheerder)])


class QueryDto(BaseModel):
    naam: str
    versie: str
    doel: str
    scope: str
    parameters: list[str]
    optioneel: list[str]
    kolommen: list[str]


class QueryInvoerDto(BaseModel):
    params: dict[str, str] = {}
    administratie_id: uuid.UUID | None = None
    max_rijen: int = Field(default=MAX_RIJEN_ROUTE, ge=1, le=MAX_RIJEN_ROUTE)


class SqlInvoerDto(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    #: Optioneel: RLS-scope op één administratie (tabellen zonder Beheerder-clausule, bv. bank_mutatie, geven anders niets).
    administratie_id: uuid.UUID | None = None
    max_rijen: int = Field(default=MAX_RIJEN_ROUTE, ge=1, le=MAX_RIJEN_ROUTE)


class ResultaatDto(BaseModel):
    query: str
    versie: str | None = None
    kolommen: list[str]
    rijen: list[list]
    totaal: int
    afgekapt: bool
    administraties: int = 0
    duur_ms: int


def _dto(u: service.Uitkomst) -> ResultaatDto:
    r: Resultaat = u.resultaat
    return ResultaatDto(
        query=u.query,
        versie=u.versie,
        kolommen=r.kolommen,
        rijen=r.rijen,
        totaal=r.totaal,
        afgekapt=r.afgekapt,
        administraties=r.administraties,
        duur_ms=u.duur_ms,
    )


@router.get("/queries", response_model=list[QueryDto])
def queries(actor: CurrentGebruiker = Depends(require_beheerder)) -> list[QueryDto]:
    return [QueryDto(**q) for q in service.overzicht()]


@router.post("/query/{naam}", response_model=ResultaatDto)
def query_uitvoeren(naam: str, invoer: QueryInvoerDto, actor: CurrentGebruiker = Depends(require_beheerder)) -> ResultaatDto:
    try:
        return _dto(
            service.voer_query_uit(
                naam, invoer.params, administratie_id=invoer.administratie_id, actor_id=actor.id, max_rijen=invoer.max_rijen
            )
        )
    except bibliotheek.OnbekendeQuery as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.OntbrekendeParameter as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/sql", response_model=ResultaatDto)
def sql_uitvoeren(invoer: SqlInvoerDto, actor: CurrentGebruiker = Depends(require_beheerder)) -> ResultaatDto:
    try:
        return _dto(service.voer_sql_uit(invoer.sql, actor_id=actor.id, administratie_id=invoer.administratie_id, max_rijen=invoer.max_rijen))
    except GeenSelect as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"geweigerd: {exc}") from exc
    except service.GeenBeheerder as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.GeenLeesreplica as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
