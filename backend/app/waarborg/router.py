from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.documenten.boeken import (
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
)
from app.documenten.checks import CheckRapport
from app.documenten.schemas import CheckRapportResponse, CheckResultaatDto
from app.documenten.service import DocumentNietGevonden
from app.rlz.credentials import GeenRlzCredentials
from app.waarborg import boeken, schemas, service

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["waarborg"], dependencies=[Depends(vereis_kantoorrol)])


def _naar_check_rapport(rapport: CheckRapport) -> CheckRapportResponse:
    return CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding) for r in rapport.resultaten],
    )


def _naar_response(data: service.WaarborgVoorstelData) -> schemas.WaarborgVoorstelResponse:
    return schemas.WaarborgVoorstelResponse(
        document_id=data.document_id,
        bericht_id=data.bericht_id,
        verhuurder_entiteit=data.verhuurder_entiteit,
        contract_referentie=data.contract_referentie,
        huurder=data.huurder,
        bedrag=data.bedrag,
        richting=data.richting,
        datum=data.datum,
        balans_gb_code=data.balans_gb_code,
        balans_ledger_id=data.balans_ledger_id,
        balans_gb_status=data.balans_gb_status,
        tegenrekening_ledger_id=data.tegenrekening_ledger_id,
        status=data.status,
        rlz_boekstuknummer=data.rlz_boekstuknummer,
    )


@router.get(
    "/administraties/{administratie_id}/waarborg/documenten/{document_id}/voorstel",
    response_model=schemas.WaarborgVoorstelResponse,
)
def waarborg_voorstel_ophalen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WaarborgVoorstelResponse:
    try:
        data = service.haal_waarborg_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WaarborgFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_response(data)


@router.put(
    "/administraties/{administratie_id}/waarborg/documenten/{document_id}/tegenrekening",
    response_model=schemas.WaarborgVoorstelResponse,
)
def waarborg_tegenrekening_kiezen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.WaarborgTegenrekeningInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WaarborgVoorstelResponse:
    try:
        data = service.sla_tegenrekening_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            tegenrekening_ledger_id=invoer.tegenrekening_ledger_id,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WaarborgFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_response(data)


@router.post(
    "/administraties/{administratie_id}/waarborg/documenten/{document_id}/checks",
    response_model=CheckRapportResponse,
)
def waarborg_checks_uitvoeren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> CheckRapportResponse:
    """Lokale checks (read-only, blok B-patroon): de boekmotor herdraait alles server-side mét
    de live RLZ-duplicaatquery vóór elke echte boeking."""
    try:
        rapport = service.voer_waarborg_checks_uit(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WaarborgFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_check_rapport(rapport)


@router.post(
    "/administraties/{administratie_id}/waarborg/documenten/{document_id}/boeken",
    response_model=schemas.WaarborgBoekenResponse,
)
def waarborg_boeken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WaarborgBoekenResponse:
    try:
        resultaat = boeken.boek_waarborg_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "melding": "Boeken geblokkeerd door harde checks",
                "checks": _naar_check_rapport(exc.rapport).model_dump(mode="json"),
            },
        ) from exc
    except (OngeldigeBoekpoging, BoekenUitgeschakeld, service.WaarborgFout) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VolumeremBereikt as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RlzBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.WaarborgBoekenResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        memoriaal_rlz_id=resultaat.memoriaal_rlz_id,
        rlz_boekstuknummer=resultaat.rlz_boekstuknummer,
    )
