"""Terugkerende-facturen-signaal (blok B 30-08): lezen = kantoorrol + administratie-scope, snooze/afmelden
= kantoorrol + scope (menskeuze mét audit, geen boeking), drempel = Beheerder-only. Alleen signaleren."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.terugkerend import schemas, service

router = APIRouter(tags=["terugkerend"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: service.TerugkerendFout) -> HTTPException:
    if "Onbekende administratie" in str(exc) or "Geen terugkerend patroon" in str(exc):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _dto(s: service.SignaalData) -> schemas.TerugkerendSignaalDto:
    return schemas.TerugkerendSignaalDto(**s.__dict__)


@router.get("/administraties/{administratie_id}/terugkerend", response_model=schemas.TerugkerendOverzichtDto)
def terugkerend_overzicht(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TerugkerendOverzichtDto:
    """Signaal-overzicht per administratie (ontbrekend eerst, dan prijsstijgingen)."""
    try:
        drempel = service.haal_drempel_op(administratie_id=administratie_id)
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    return schemas.TerugkerendOverzichtDto(
        administratie_id=administratie_id,
        prijsstijging_drempel_pct=drempel,
        signalen=[_dto(s) for s in service.overzicht(administratie_id=administratie_id)],
    )


@router.post("/administraties/{administratie_id}/terugkerend/herbereken", response_model=schemas.HerberekenResultaatDto)
def terugkerend_herberekenen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.HerberekenResultaatDto:
    """Op verzoek herberekenen (de dagelijkse sync-alles doet dit óók) — puur code, geen RLZ-calls."""
    return schemas.HerberekenResultaatDto(**service.herbereken_administratie(administratie_id=administratie_id))


@router.post(
    "/administraties/{administratie_id}/terugkerend/{vendor_id}/snooze", status_code=status.HTTP_204_NO_CONTENT
)
def terugkerend_snooze(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.SnoozeDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        service.snooze(administratie_id=administratie_id, vendor_id=vendor_id, tot=invoer.tot, actor_id=actor.id)
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc


@router.post(
    "/administraties/{administratie_id}/terugkerend/{vendor_id}/afmelden", status_code=status.HTTP_204_NO_CONTENT
)
def terugkerend_afmelden(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.AfmeldenDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        service.zet_afgemeld(
            administratie_id=administratie_id, vendor_id=vendor_id, afgemeld=invoer.afgemeld, actor_id=actor.id
        )
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc


@router.put("/administraties/{administratie_id}/terugkerend-instelling", response_model=schemas.DrempelResultaatDto)
def terugkerend_drempel_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.DrempelDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.DrempelResultaatDto:
    """Drempel prijsstijging (%) per administratie — Beheerder-only, default 10, audit oud→nieuw."""
    try:
        waarde = service.zet_drempel(
            administratie_id=administratie_id, prijsstijging_pct=invoer.prijsstijging_pct, actor_id=actor.id
        )
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    return schemas.DrempelResultaatDto(prijsstijging_pct=waarde)


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/terugkerend-signaal",
    response_model=schemas.DocumentTerugkerendSignaalDto,
)
def document_terugkerend_signaal(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentTerugkerendSignaalDto:
    """Prijsstijging-chip voor het controlescherm (aanbetaling-signaal-patroon): alleen als dít
    document de laatste factuur van een terugkerende leverancier is én boven de drempel ligt."""
    s = service.signaal_voor_document(administratie_id=administratie_id, document_id=document_id)
    if s is None:
        return schemas.DocumentTerugkerendSignaalDto()
    return schemas.DocumentTerugkerendSignaalDto(**s.__dict__)
