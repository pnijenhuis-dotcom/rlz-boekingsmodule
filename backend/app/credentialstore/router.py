from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope
from app.credentialstore import schemas, service
from app.rlz.credentials import GeenRlzCredentials

router = APIRouter(tags=["credential-store"])


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
    """Koppel-flow: read-only rechten-probe over de endpoints die de boekingsmodule daadwerkelijk
    gebruikt. Administratie-scope (niet Beheerder-only) — zelfde autorisatie als document-upload
    en de sync-trigger, want dit hoort bij het aansluiten van een klant, geen platformbeheer."""
    try:
        rapport = service.voer_rechten_probe_uit(administratie_id=administratie_id, actor_id=actor.id)
    except service.CredentialStoreFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return schemas.RechtenProbeResponse(rapport=rapport)
