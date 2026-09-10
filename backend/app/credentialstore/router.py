from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.credentialstore import schemas, service
from app.rlz.credentials import GeenRlzCredentials

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["credential-store"], dependencies=[Depends(vereis_kantoorrol)])


@router.put("/administraties/{administratie_id}/rlz-credential", status_code=status.HTTP_204_NO_CONTENT)
def credential_upsert(
    administratie_id: uuid.UUID,
    payload: schemas.CredentialUpsertRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.zet_credential(
            actor_id=actor.id,
            administratie_id=administratie_id,
            webservice_username=payload.webservice_username,
            wachtwoord=payload.wachtwoord,
        )
    except service.CredentialStoreFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/administraties/{administratie_id}/rlz-credential",
    response_model=schemas.CredentialMetadataResponse,
)
def credential_metadata(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.CredentialMetadataResponse:
    metadata = service.haal_credential_metadata_op(administratie_id=administratie_id)
    if metadata is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Geen credential geregistreerd")
    return schemas.CredentialMetadataResponse(
        administratie_id=metadata.administratie_id,
        webservice_username=metadata.webservice_username,
        aangemaakt_op=metadata.aangemaakt_op,
        bijgewerkt_op=metadata.bijgewerkt_op,
    )


@router.post(
    "/administraties/{administratie_id}/rlz-check",
    response_model=schemas.RechtenProbeResponse,
)
def rlz_rechten_check(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RechtenProbeResponse:
    """Koppel-flow: read-only rechten-probe met de OPGESLAGEN webservice-login over exact de leesroutes die de
    eerste sync gebruikt (app/rlz/leesroutes.py) — dit is de herprobe-route van blok C 10-09 (Baard): de uitkomst zegt
    wat de sync ziet, mét het letterlijke RLZ-antwoord per rode route. Administratie-scope (niet Beheerder-only) —
    zelfde autorisatie als document-upload en de sync-trigger: aansluiten van een klant, geen platformbeheer."""
    try:
        uitkomst = service.voer_herprobe_met_opgeslagen_login(administratie_id=administratie_id, actor_id=actor.id)
    except service.CredentialStoreFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return schemas.RechtenProbeResponse(rapport=uitkomst.rapport, meldingen=uitkomst.meldingen)
