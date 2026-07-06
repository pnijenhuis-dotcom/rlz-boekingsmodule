from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import schemas, service
from app.auth.deps import CurrentGebruiker, require_beheerder

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=True)


@router.post("/uitnodigingen", response_model=schemas.UitnodigingAanmakenResponse)
def uitnodiging_aanmaken(
    payload: schemas.UitnodigingAanmakenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.UitnodigingAanmakenResponse:
    resultaat = service.maak_uitnodiging(
        actor_id=actor.id,
        naam=payload.naam,
        e_mail=payload.e_mail,
        rol=payload.rol,
        administratie_ids=payload.administratie_ids,
    )
    return schemas.UitnodigingAanmakenResponse(
        uitnodiging_id=resultaat.uitnodiging_id,
        gebruiker_id=resultaat.gebruiker_id,
        token=resultaat.token,
        verloopt_op=resultaat.verloopt_op,
    )


@router.post("/uitnodigingen/accepteren", response_model=schemas.UitnodigingAccepterenResponse)
def uitnodiging_accepteren(
    payload: schemas.UitnodigingAccepterenRequest,
) -> schemas.UitnodigingAccepterenResponse:
    try:
        resultaat = service.accepteer_uitnodiging(token=payload.token, wachtwoord=payload.wachtwoord)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.UitnodigingAccepterenResponse(
        totp_setup_token=resultaat.totp_setup_token,
        otpauth_uri=resultaat.otpauth_uri,
        secret=resultaat.secret,
    )


@router.post("/totp/bevestigen", response_model=schemas.TokenPaarResponse)
def totp_bevestigen(
    payload: schemas.TotpBevestigenRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> schemas.TokenPaarResponse:
    try:
        paar = service.bevestig_totp(totp_setup_token=credentials.credentials, code=payload.code)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.TokenPaarResponse(access_token=paar.access_token, refresh_token=paar.refresh_token)


@router.post("/login", response_model=schemas.TokenPaarResponse)
def login(payload: schemas.LoginRequest) -> schemas.TokenPaarResponse:
    try:
        paar = service.login(e_mail=payload.e_mail, wachtwoord=payload.wachtwoord, totp_code=payload.totp_code)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return schemas.TokenPaarResponse(access_token=paar.access_token, refresh_token=paar.refresh_token)


@router.post("/token/vernieuwen", response_model=schemas.TokenPaarResponse)
def token_vernieuwen(payload: schemas.RefreshRequest) -> schemas.TokenPaarResponse:
    try:
        paar = service.vernieuw_token(refresh_token=payload.refresh_token)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return schemas.TokenPaarResponse(access_token=paar.access_token, refresh_token=paar.refresh_token)


@router.patch("/gebruikers/{gebruiker_id}/rol", status_code=status.HTTP_204_NO_CONTENT)
def rol_wijzigen(
    gebruiker_id: uuid.UUID,
    payload: schemas.RolWijzigenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.wijzig_rol(actor_id=actor.id, doel_gebruiker_id=gebruiker_id, nieuwe_rol=payload.rol)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/gebruikers/{gebruiker_id}/scope", status_code=status.HTTP_204_NO_CONTENT)
def scope_toevoegen(
    gebruiker_id: uuid.UUID,
    payload: schemas.ScopeToevoegenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.voeg_scope_toe(
            actor_id=actor.id, doel_gebruiker_id=gebruiker_id, administratie_id=payload.administratie_id
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete("/gebruikers/{gebruiker_id}/scope/{administratie_id}", status_code=status.HTTP_204_NO_CONTENT)
def scope_verwijderen(
    gebruiker_id: uuid.UUID,
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.verwijder_scope(actor_id=actor.id, doel_gebruiker_id=gebruiker_id, administratie_id=administratie_id)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
