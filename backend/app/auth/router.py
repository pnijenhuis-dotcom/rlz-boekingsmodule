from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import schemas, service
from app.auth.deps import CurrentGebruiker, get_current_gebruiker, require_beheerder
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=True)

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth/token/vernieuwen"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """httpOnly+Secure+SameSite (Auth-0010-b punt 1) — nooit leesbaar voor JS, dus nooit via
    localStorage lekbaar. Path beperkt tot het refresh-endpoint: de browser stuurt hem nergens
    anders naartoe. secure=False alleen in dev/local (zelfde gate als de JWT-secret-fallback in
    app/security/tokens.py) — anders werkt lokaal draaien over http niet."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=True,
        secure=settings.environment not in ("dev", "local"),
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.environment not in ("dev", "local"),
        samesite="strict",
    )


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
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> schemas.TokenPaarResponse:
    try:
        paar = service.bevestig_totp(totp_setup_token=credentials.credentials, code=payload.code)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _set_refresh_cookie(response, paar.refresh_token)
    return schemas.TokenPaarResponse(access_token=paar.access_token)


@router.post("/login", response_model=schemas.TokenPaarResponse)
def login(payload: schemas.LoginRequest, request: Request, response: Response) -> schemas.TokenPaarResponse:
    try:
        paar = service.login(
            e_mail=payload.e_mail,
            wachtwoord=payload.wachtwoord,
            totp_code=payload.totp_code,
            ip_adres=_client_ip(request),
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_refresh_cookie(response, paar.refresh_token)
    return schemas.TokenPaarResponse(access_token=paar.access_token)


@router.post("/token/vernieuwen", response_model=schemas.TokenPaarResponse)
def token_vernieuwen(request: Request, response: Response) -> schemas.TokenPaarResponse:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geen refresh-token cookie aangeleverd")
    try:
        paar = service.vernieuw_token(refresh_token=refresh_token, ip_adres=_client_ip(request))
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_refresh_cookie(response, paar.refresh_token)
    return schemas.TokenPaarResponse(access_token=paar.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    """Trekt alleen de huidige sessie (het refresh-token in de cookie) in — andere sessies van
    de gebruiker blijven actief. Geen authenticatie vereist: moet ook werken als het access-token
    al verlopen is, en is idempotent bij een ontbrekende/al-ongeldige cookie."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token is not None:
        service.logout(refresh_token=refresh_token)
    _clear_refresh_cookie(response)


@router.post("/logout-overal", status_code=status.HTTP_204_NO_CONTENT)
def logout_overal(
    response: Response,
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> None:
    """Trekt ALLE sessies van de ingelogde gebruiker in — vereist een geldig access-token (i.t.t.
    /logout), zodat intrekken van alle sessies alleen kan met een nog-verse bewezen identiteit."""
    service.logout_overal(gebruiker_id=actor.id)
    _clear_refresh_cookie(response)


@router.get("/administraties", response_model=schemas.MijnAdministratiesResponse)
def mijn_administraties(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> schemas.MijnAdministratiesResponse:
    administraties = service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    return schemas.MijnAdministratiesResponse(
        administraties=[schemas.AdministratieResponse(id=a.id, naam=a.naam) for a in administraties]
    )


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
