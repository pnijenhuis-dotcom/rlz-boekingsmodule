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
from app.verkoop import boeken, schemas, voorstel

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["verkoop"], dependencies=[Depends(vereis_kantoorrol)])


def _naar_check_rapport(rapport: CheckRapport) -> CheckRapportResponse:
    return CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding) for r in rapport.resultaten],
    )


def _naar_voorstel_response(data: voorstel.VerkoopVoorstelData) -> schemas.VerkoopVoorstelResponse:
    return schemas.VerkoopVoorstelResponse(
        document_id=data.document_id,
        debiteur_naam=data.debiteur_naam,
        factuurnummer=data.factuurnummer,
        factuurdatum=data.factuurdatum,
        totaalbedrag_incl=data.totaalbedrag_incl,
        is_creditnota=data.is_creditnota,
        gecrediteerd_factuurnummer=data.gecrediteerd_factuurnummer,
        regels=[
            schemas.VerkoopRegelDto(
                volgnummer=r.volgnummer,
                omschrijving=r.omschrijving,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                gb_code=r.gb_code,
                ledger_id=r.ledger_id,
                taxrate_id=r.taxrate_id,
                gb_code_status=r.gb_code_status,
                herkomst=r.herkomst,
                btw_categorie=r.btw_categorie,
                btw_percentage_ubl=r.btw_percentage_ubl,
                btw_vergrendeld=r.btw_vergrendeld,
                btw_bron=r.btw_bron,
                btw_kandidaten=list(r.btw_kandidaten),
            )
            for r in data.regels
        ],
        opgeslagen=data.opgeslagen,
        rlz_boekstuknummer=data.rlz_boekstuknummer,
    )


@router.get(
    "/administraties/{administratie_id}/verkoop/documenten/{document_id}/voorstel",
    response_model=schemas.VerkoopVoorstelResponse,
)
def verkoop_voorstel_ophalen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerkoopVoorstelResponse:
    try:
        data = voorstel.haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voorstel.GeenVerkoopfactuur as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_voorstel_response(data)


@router.put(
    "/administraties/{administratie_id}/verkoop/documenten/{document_id}/voorstel",
    response_model=schemas.VerkoopVoorstelResponse,
)
def verkoop_voorstel_opslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.VerkoopVoorstelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerkoopVoorstelResponse:
    try:
        data = voorstel.sla_verkoop_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            debiteur_naam=invoer.debiteur_naam,
            factuurnummer=invoer.factuurnummer,
            factuurdatum=invoer.factuurdatum,
            totaalbedrag_incl=invoer.totaalbedrag_incl,
            regels=[
                voorstel.VerkoopRegelInput(
                    omschrijving=r.omschrijving,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code,
                    ledger_id=r.ledger_id,
                    taxrate_id=r.taxrate_id,
                )
                for r in invoer.regels
            ],
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voorstel.GeenVerkoopfactuur as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except voorstel.VerkoopVoorstelFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_voorstel_response(data)


@router.post(
    "/administraties/{administratie_id}/verkoop/documenten/{document_id}/checks",
    response_model=schemas.VerkoopVoorstelMetChecksResponse,
)
def verkoop_checks_uitvoeren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerkoopVoorstelMetChecksResponse:
    try:
        rapport = voorstel.voer_verkoop_checks_uit(administratie_id=administratie_id, document_id=document_id)
        data = voorstel.haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (voorstel.GeenVerkoopfactuur, voorstel.VerkoopVoorstelFout) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.VerkoopVoorstelMetChecksResponse(
        voorstel=_naar_voorstel_response(data), checks=_naar_check_rapport(rapport)
    )


@router.post(
    "/administraties/{administratie_id}/verkoop/documenten/{document_id}/boeken",
    response_model=schemas.VerkoopBoekenResponse,
)
def verkoop_boeken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerkoopBoekenResponse:
    try:
        resultaat = boeken.boek_verkoop_document(
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
    except (OngeldigeBoekpoging, BoekenUitgeschakeld) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VolumeremBereikt as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RlzBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.VerkoopBoekenResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        verkoop_rlz_id=resultaat.verkoop_rlz_id,
        verkoop_referentie=resultaat.verkoop_referentie,
        verkoop_boekstuknummer=resultaat.verkoop_boekstuknummer,
    )
