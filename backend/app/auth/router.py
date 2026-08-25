from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import schemas, service, voorwaarden, webauthn_service
from app.auth.deps import CurrentGebruiker, get_current_gebruiker, require_beheerder
from app.auth.rollen import is_externe_app_rol
from app.berichten import mail as berichten_mail
from app.berichten import uitnodigingsmail
from app.config import settings
from app.db.models import GebruikerRol

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=True)

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth/token/vernieuwen"


def _set_refresh_cookie(response: Response, paar: service.TokenPaar) -> None:
    """httpOnly+Secure+SameSite (Auth-0010-b punt 1) — nooit leesbaar voor JS, dus nooit via
    localStorage lekbaar. Path beperkt tot het refresh-endpoint (de ontgrendel-endpoints van de
    accordeur-cadans leven bewust ónder dit pad — RFC 6265-prefix-match — zodat de scope niet
    verruimd hoeft te worden): de browser stuurt hem nergens anders naartoe. max_age volgt de
    TTL van het uitgegeven token (accordeur 7 dagen sliding, overige rollen 30 dagen).
    secure=False alleen in dev/local (zelfde gate als de JWT-secret-fallback in
    app/security/tokens.py) — anders werkt lokaal draaien over http niet."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=paar.refresh_token,
        max_age=paar.refresh_ttl_seconds or settings.jwt_refresh_ttl_seconds,
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


# Native store-app (fase 4, verkenning/17 (d) route 2): de Capacitor-webview (origin
# capacitor://localhost) kan de SameSite=Strict-cookie niet dragen — daar leeft het
# refresh-token in Keychain/Keystore en reist het als header.
NATIVE_CLIENT_HEADER = "X-Native-Client"
REFRESH_HEADER = "X-Refresh-Token"


def _is_native_client(request: Request) -> bool:
    return request.headers.get(NATIVE_CLIENT_HEADER) == "1" or REFRESH_HEADER in request.headers


def _lees_refresh_token(request: Request) -> str | None:
    """Cookie eerst (web-pad, ongewijzigd); anders de native header. Beide dragen exact
    hetzelfde token-formaat — service-laag en rotatie merken geen verschil."""
    return request.cookies.get(REFRESH_COOKIE_NAME) or request.headers.get(REFRESH_HEADER)


def _lever_token_paar(request: Request, response: Response, paar: service.TokenPaar) -> schemas.TokenPaarResponse:
    """Web: refresh-token uitsluitend als httpOnly-cookie (Auth-0010-b — nooit in de body).
    Native: het paar in de body (de app bewaart het refresh-token in secure native storage),
    géén cookie erbij — één kanaal per client. De body-vorm vergt de expliciete
    native-aankondiging; een web-context zonder die header krijgt het token dus nooit te
    lezen, ook niet via een XSS die dit endpoint aanroept (de cookie blijft httpOnly)."""
    if _is_native_client(request):
        return schemas.TokenPaarResponse(access_token=paar.access_token, refresh_token=paar.refresh_token)
    _set_refresh_cookie(response, paar)
    return schemas.TokenPaarResponse(access_token=paar.access_token)


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
    # Uitnodiging per mail (berichten-bouwsteen 2026-08-15). Fail-zichtbaar, niet fail-hard:
    # de uitnodiging bestaat al (en de link zit in de respons), dus een mailfout mag het
    # aanmaken niet terugdraaien — hij moet alleen nooit stil zijn.
    mail_verzonden = False
    mail_fout: str | None = None
    try:
        uitnodigingsmail.verstuur_uitnodigingsmail(
            naam=payload.naam,
            e_mail=payload.e_mail,
            token=resultaat.token,
            verloopt_op=resultaat.verloopt_op,
        )
        mail_verzonden = True
    except berichten_mail.MailFout as exc:
        mail_fout = str(exc)
    return schemas.UitnodigingAanmakenResponse(
        uitnodiging_id=resultaat.uitnodiging_id,
        gebruiker_id=resultaat.gebruiker_id,
        token=resultaat.token,
        verloopt_op=resultaat.verloopt_op,
        mail_verzonden=mail_verzonden,
        mail_fout=mail_fout,
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
        soort=resultaat.soort,
        totp_setup_token=resultaat.totp_setup_token,
        otpauth_uri=resultaat.otpauth_uri,
        secret=resultaat.secret,
        passkey_setup_token=resultaat.passkey_setup_token,
    )


@router.post("/totp/bevestigen", response_model=schemas.TokenPaarResponse)
def totp_bevestigen(
    payload: schemas.TotpBevestigenRequest,
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> schemas.TokenPaarResponse:
    try:
        paar = service.bevestig_totp(totp_setup_token=credentials.credentials, code=payload.code)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _lever_token_paar(request, response, paar)


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
    return _lever_token_paar(request, response, paar)


@router.post("/token/vernieuwen", response_model=schemas.TokenPaarResponse)
def token_vernieuwen(request: Request, response: Response) -> schemas.TokenPaarResponse:
    refresh_token = _lees_refresh_token(request)
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geen refresh-token aangeleverd")
    try:
        paar = service.vernieuw_token(refresh_token=refresh_token, ip_adres=_client_ip(request))
    except service.RotatieBezetError as exc:
        # Bewust géén 401: de sessie is niet ongeldig, een parallelle rotatie hield de rij-lock
        # langer vast dan de lock-timeout. De client mag kort wachten en één keer opnieuw proberen.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _lever_token_paar(request, response, paar)


@router.post("/token/vernieuwen/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    """Trekt alleen de huidige sessie (het refresh-token in de cookie) in — andere sessies van
    de gebruiker blijven actief. Geen authenticatie vereist: moet ook werken als het access-token
    al verlopen is, en is idempotent bij een ontbrekende/al-ongeldige cookie.

    Leeft bewust ónder het cookie-pad /auth/token/vernieuwen (zelfde RFC 6265-truc als de
    ontgrendel-endpoints): de refresh-cookie is path-gebonden en bereikte het oude /auth/logout
    in een echte browser nooit — de server-side intrekking gebeurde daardoor feitelijk niet
    (nazorg-fix 2026-08-11; TestClient negeert path-matching, vandaar dat geen test dit zag)."""
    refresh_token = _lees_refresh_token(request)
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


@router.get("/gebruikers", response_model=schemas.GebruikersLijstResponse)
def gebruikers_lijst(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.GebruikersLijstResponse:
    """Gebruikers & toegang (fase 3 modernisering, designronde 15-08) — Beheerder-only.
    Staande-goedkeuring-tellers per accordeur komen per administratie (strikte RLS) mee."""
    items = service.lijst_gebruikers(actor_id=actor.id)
    administraties = service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    staande = service.staande_goedkeuringen_per_accordeur(administratie_ids=[a.id for a in administraties])
    return schemas.GebruikersLijstResponse(
        gebruikers=[
            schemas.GebruikerOverzichtResponse(
                id=item.id,
                naam=item.naam,
                e_mail=item.e_mail,
                rol=item.rol,
                status=item.status.value,
                administratie_ids=item.administratie_ids,
                heeft_totp=item.heeft_totp,
                aantal_passkeys=item.aantal_passkeys,
                open_uitnodiging_verloopt_op=item.open_uitnodiging_verloopt_op,
                open_herstel_verloopt_op=item.open_herstel_verloopt_op,
                staande_goedkeuringen=staande.get(item.id, 0),
                geblokkeerd_op=item.geblokkeerd_op,
                geblokkeerd_door_naam=item.geblokkeerd_door_naam,
            )
            for item in items
        ]
    )


@router.post("/gebruikers/{gebruiker_id}/uitnodiging-opnieuw", response_model=schemas.UitnodigingAanmakenResponse)
def uitnodiging_opnieuw_mailen(
    gebruiker_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.UitnodigingAanmakenResponse:
    """"Opnieuw mailen" op Gebruikers & toegang: nieuw eenmalig token (oude open links verlopen
    per direct), zelfde fail-zichtbare mailafhandeling als het aanmaken."""
    try:
        vernieuwd = service.vernieuw_uitnodiging(actor_id=actor.id, gebruiker_id=gebruiker_id)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    mail_verzonden = False
    mail_fout: str | None = None
    try:
        uitnodigingsmail.verstuur_uitnodigingsmail(
            naam=vernieuwd.naam,
            e_mail=vernieuwd.e_mail,
            token=vernieuwd.resultaat.token,
            verloopt_op=vernieuwd.resultaat.verloopt_op,
        )
        mail_verzonden = True
    except berichten_mail.MailFout as exc:
        mail_fout = str(exc)
    return schemas.UitnodigingAanmakenResponse(
        uitnodiging_id=vernieuwd.resultaat.uitnodiging_id,
        gebruiker_id=vernieuwd.resultaat.gebruiker_id,
        token=vernieuwd.resultaat.token,
        verloopt_op=vernieuwd.resultaat.verloopt_op,
        mail_verzonden=mail_verzonden,
        mail_fout=mail_fout,
    )


@router.post("/gebruikers/{gebruiker_id}/herstel-link", response_model=schemas.UitnodigingAanmakenResponse)
def herstel_link_sturen(
    gebruiker_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.UitnodigingAanmakenResponse:
    """"Herstel-link sturen" op Gebruikers & toegang (feedbackronde 25-08 punt 7): eenmalige
    72-uurs link voor een actieve accordeur/veldwerker die zijn wachtwoord kwijt is (bv. ná een
    kill-switch). Zelfde responsvorm + fail-zichtbare mailafhandeling als de uitnodiging — de
    link zit in de respons als handmatige terugval. Beheerder-only; 409 bij een account dat
    hier niet voor in aanmerking komt (kantoorrol, geblokkeerd, nog niet geactiveerd)."""
    try:
        herstel = service.maak_herstel_link(actor_id=actor.id, gebruiker_id=gebruiker_id)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    mail_verzonden = False
    mail_fout: str | None = None
    try:
        uitnodigingsmail.verstuur_herstelmail(
            naam=herstel.naam,
            e_mail=herstel.e_mail,
            token=herstel.resultaat.token,
            verloopt_op=herstel.resultaat.verloopt_op,
        )
        mail_verzonden = True
    except berichten_mail.MailFout as exc:
        mail_fout = str(exc)
    return schemas.UitnodigingAanmakenResponse(
        uitnodiging_id=herstel.resultaat.uitnodiging_id,
        gebruiker_id=herstel.resultaat.gebruiker_id,
        token=herstel.resultaat.token,
        verloopt_op=herstel.resultaat.verloopt_op,
        mail_verzonden=mail_verzonden,
        mail_fout=mail_fout,
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


@router.post("/gebruikers/{gebruiker_id}/blokkeren", status_code=status.HTTP_204_NO_CONTENT)
def gebruiker_blokkeren(
    gebruiker_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    """Blokkeer een gebruiker (beheer-mini 2026-08-16): login geweigerd, sessies/refresh per
    direct dood, passkeys onbruikbaar zolang de blokkade staat. Guards (eigen account,
    systeem-actor, laatste actieve Beheerder) zitten server-side in de service."""
    try:
        service.blokkeer_gebruiker(actor_id=actor.id, doel_gebruiker_id=gebruiker_id)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/gebruikers/{gebruiker_id}/heractiveren", status_code=status.HTTP_204_NO_CONTENT)
def gebruiker_heractiveren(
    gebruiker_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.heractiveer_gebruiker(actor_id=actor.id, doel_gebruiker_id=gebruiker_id)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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


# --- accordeur-cadans: passkeys/WebAuthn (migratie 0040, besluit 2026-08-11) ----------------------


def _passkey_setup_gebruiker(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> uuid.UUID:
    """Bearer = het passkey_setup-token uit de wachtwoordstap (accordeur-login) of de
    activeringsflow — machtigt uitsluitend het afronden van registratie/assertion."""
    try:
        return webauthn_service.gebruiker_id_uit_passkey_setup(credentials.credentials)
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/webauthn/config", response_model=schemas.WebauthnConfigResponse)
def webauthn_config() -> schemas.WebauthnConfigResponse:
    """Publiek: de PWA moet vóór de login weten of de dev-stub actief is (LAN-IP-kliktest heeft
    geen secure context, dus geen echte WebAuthn). Bevat geen gevoelige informatie."""
    return schemas.WebauthnConfigResponse(
        dev_stub=webauthn_service.dev_stub_actief(), rp_id=settings.webauthn_rp_id
    )


@router.post("/accordeur/login", response_model=schemas.AccordeurLoginResponse)
def accordeur_login(
    payload: schemas.AccordeurLoginRequest, request: Request
) -> schemas.AccordeurLoginResponse:
    """Wachtwoordstap van de volledige accordeur-login (eerste gebruik / nieuw apparaat / ná 7
    dagen inactiviteit). Kantoor-rollen blijven op /auth/login (wachtwoord + TOTP)."""
    try:
        resultaat = webauthn_service.start_accordeur_login(
            e_mail=payload.e_mail, wachtwoord=payload.wachtwoord, ip_adres=_client_ip(request)
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return schemas.AccordeurLoginResponse(
        passkey_setup_token=resultaat.passkey_setup_token, heeft_passkeys=resultaat.heeft_passkeys
    )


@router.post("/webauthn/registratie/opties", response_model=schemas.WebauthnOptiesResponse)
def webauthn_registratie_opties(
    gebruiker_id: uuid.UUID = Depends(_passkey_setup_gebruiker),
) -> schemas.WebauthnOptiesResponse:
    try:
        return schemas.WebauthnOptiesResponse(opties=webauthn_service.registratie_opties(gebruiker_id=gebruiker_id))
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/webauthn/registratie/voltooien", response_model=schemas.TokenPaarResponse)
def webauthn_registratie_voltooien(
    payload: schemas.WebauthnRegistratieVoltooienRequest,
    request: Request,
    response: Response,
    gebruiker_id: uuid.UUID = Depends(_passkey_setup_gebruiker),
) -> schemas.TokenPaarResponse:
    """Rondt de registratie van dít apparaat af en logt meteen in (apparaat-gebonden sessie)."""
    try:
        if payload.dev_stub:
            resultaat = webauthn_service.voltooi_registratie_stub(
                gebruiker_id=gebruiker_id, apparaat_naam=payload.apparaat_naam, ip_adres=_client_ip(request)
            )
        else:
            if payload.credential is None:
                raise service.AuthError("WebAuthn-response ontbreekt")
            resultaat = webauthn_service.voltooi_registratie(
                gebruiker_id=gebruiker_id,
                credential=payload.credential,
                apparaat_naam=payload.apparaat_naam,
                ip_adres=_client_ip(request),
            )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _lever_token_paar(request, response, resultaat.token_paar)


@router.post("/webauthn/login/opties", response_model=schemas.WebauthnOptiesResponse)
def webauthn_login_opties(
    gebruiker_id: uuid.UUID = Depends(_passkey_setup_gebruiker),
) -> schemas.WebauthnOptiesResponse:
    """Assertion-options voor de volledige login op een bekend apparaat (2e factor)."""
    try:
        return schemas.WebauthnOptiesResponse(opties=webauthn_service.assertie_opties(gebruiker_id=gebruiker_id))
    except webauthn_service.GeenPasskeys as exc:
        # Eigen status zodat de client deterministisch naar de registratie-flow kan (nieuw
        # apparaat) — geen 401 (sessie niet ongeldig) en geen generieke 400.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/webauthn/login/voltooien", response_model=schemas.TokenPaarResponse)
def webauthn_login_voltooien(
    payload: schemas.WebauthnAssertieVoltooienRequest,
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> schemas.TokenPaarResponse:
    try:
        paar = webauthn_service.login_met_assertie(
            passkey_setup_token=credentials.credentials,
            credential=payload.credential,
            dev_stub=payload.dev_stub,
            ip_adres=_client_ip(request),
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _lever_token_paar(request, response, paar)


@router.post("/token/vernieuwen/ontgrendel-opties", response_model=schemas.WebauthnOptiesResponse)
def ontgrendel_opties(request: Request) -> schemas.WebauthnOptiesResponse:
    """App-opening (bekend apparaat, sessie nog geldig): assertion-options op basis van de
    refresh-cookie. Bewust ónder het /auth/token/vernieuwen-pad: de httpOnly-cookie is
    path-gebonden en de scope blijft zo ongewijzigd smal."""
    refresh_token = _lees_refresh_token(request)
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geen refresh-token aangeleverd")
    try:
        gebruiker_id = webauthn_service.gebruiker_id_uit_geldig_refresh_token(refresh_token)
        return schemas.WebauthnOptiesResponse(opties=webauthn_service.assertie_opties(gebruiker_id=gebruiker_id))
    except webauthn_service.GeenPasskeys as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/token/vernieuwen/ontgrendelen", response_model=schemas.TokenPaarResponse)
def ontgrendelen(
    payload: schemas.WebauthnAssertieVoltooienRequest, request: Request, response: Response
) -> schemas.TokenPaarResponse:
    """Rondt de app-opening af: assertion verifiëren (éénmaal per opening, besluit 2026-08-11)
    en daarná de refresh-cookie roteren via de bestaande race-tolerante rotatie."""
    refresh_token = _lees_refresh_token(request)
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geen refresh-token aangeleverd")
    try:
        webauthn_service.ontgrendel_assertie(
            refresh_token=refresh_token,
            credential=payload.credential,
            dev_stub=payload.dev_stub,
            ip_adres=_client_ip(request),
        )
        paar = service.vernieuw_token(refresh_token=refresh_token, ip_adres=_client_ip(request))
    except service.RotatieBezetError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _lever_token_paar(request, response, paar)


# --- kantoor-passkeys (platformbesluit 0020: eerste authenticatielijn, TOTP = terugval) -----------


def _vereis_kantoorrol(actor: CurrentGebruiker) -> None:
    """Externe app-rollen (accordeur + veldrollen, app/auth/rollen.py) hebben hun eigen
    registratie-/loginflow (wachtwoord + passkey, 7-dagen-cadans); de kantoor-endpoints zouden
    hun wachtwoordstap omzeilen."""
    if is_externe_app_rol(actor.rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor kantoor-rollen"
        )


@router.post("/webauthn/kantoor/registratie/opties", response_model=schemas.WebauthnOptiesResponse)
def kantoor_registratie_opties(
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> schemas.WebauthnOptiesResponse:
    """Passkey toevoegen vanaf Instellingen → beveiliging (ná TOTP- of passkey-login): gewone
    ingelogde sessie is de machtiging — geen apart setup-token nodig. Zonder platform-pin:
    op een desktop zijn ook beveiligingssleutels en cross-device/QR-passkeys legitiem."""
    _vereis_kantoorrol(actor)
    try:
        return schemas.WebauthnOptiesResponse(
            opties=webauthn_service.registratie_opties(
                gebruiker_id=actor.id, alleen_platform_authenticator=False
            )
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/webauthn/kantoor/registratie/voltooien", response_model=schemas.ApparaatResponse)
def kantoor_registratie_voltooien(
    payload: schemas.WebauthnRegistratieVoltooienRequest,
    request: Request,
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> schemas.ApparaatResponse:
    """Rondt de registratie af zónder nieuw token-paar: de lopende sessie blijft staan, de
    passkey draagt pas een sessie bij de eerstvolgende passkey-login."""
    _vereis_kantoorrol(actor)
    try:
        apparaat = webauthn_service.voltooi_kantoor_registratie(
            gebruiker_id=actor.id,
            credential=payload.credential,
            apparaat_naam=payload.apparaat_naam,
            dev_stub=payload.dev_stub,
            ip_adres=_client_ip(request),
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.ApparaatResponse(
        id=apparaat.id,
        apparaat_naam=apparaat.apparaat_naam,
        is_dev_stub=apparaat.is_dev_stub,
        aangemaakt_op=apparaat.aangemaakt_op,
        laatst_gebruikt_op=apparaat.laatst_gebruikt_op,
        ingetrokken_op=apparaat.ingetrokken_op,
    )


@router.post("/webauthn/kantoor/login/opties", response_model=schemas.KantoorPasskeyOptiesResponse)
def kantoor_login_opties(payload: schemas.KantoorPasskeyLoginOptiesRequest) -> schemas.KantoorPasskeyOptiesResponse:
    """Eerste lijn van het kantoor-loginscherm (besluit 0020). 409 = geen bruikbare passkey —
    de client valt terug op wachtwoord + TOTP; het antwoord is identiek voor onbekend adres,
    accordeur, niet-actief account en passkey-loze gebruiker (geen account-enumeratie)."""
    try:
        resultaat = webauthn_service.kantoor_login_opties(e_mail=payload.e_mail)
    except webauthn_service.GeenPasskeys as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.KantoorPasskeyOptiesResponse(opties=resultaat.opties, dev_stub=resultaat.dev_stub)


@router.post("/webauthn/kantoor/login/voltooien", response_model=schemas.TokenPaarResponse)
def kantoor_login_voltooien(
    payload: schemas.KantoorPasskeyLoginVoltooienRequest, request: Request, response: Response
) -> schemas.TokenPaarResponse:
    try:
        paar = webauthn_service.login_met_kantoor_passkey(
            e_mail=payload.e_mail,
            credential=payload.credential,
            dev_stub=payload.dev_stub,
            ip_adres=_client_ip(request),
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _lever_token_paar(request, response, paar)


@router.get("/mijn/apparaten", response_model=schemas.ApparatenResponse)
def mijn_apparaten(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> schemas.ApparatenResponse:
    """Eigen passkey-apparaten (elke rol): naam, registratiedatum, laatst gebruikt, status."""
    return schemas.ApparatenResponse(
        apparaten=[
            schemas.ApparaatResponse(
                id=a.id,
                apparaat_naam=a.apparaat_naam,
                is_dev_stub=a.is_dev_stub,
                aangemaakt_op=a.aangemaakt_op,
                laatst_gebruikt_op=a.laatst_gebruikt_op,
                ingetrokken_op=a.ingetrokken_op,
            )
            for a in webauthn_service.apparaten_van(gebruiker_id=actor.id)
        ]
    )


@router.get("/apparaten/kantoor", response_model=schemas.KantoorApparatenResponse)
def kantoor_apparaten_overzicht(
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.KantoorApparatenResponse:
    """Beheerder-overzicht van álle kantoor-passkey-apparaten (intrekken kan per rij via het
    bestaande intrekken-endpoint — Beheerder mag óók andermans apparaten intrekken)."""
    return schemas.KantoorApparatenResponse(
        apparaten=[
            schemas.KantoorApparaatResponse(
                id=a.id,
                apparaat_naam=a.apparaat_naam,
                is_dev_stub=a.is_dev_stub,
                aangemaakt_op=a.aangemaakt_op,
                laatst_gebruikt_op=a.laatst_gebruikt_op,
                ingetrokken_op=a.ingetrokken_op,
                gebruiker_id=a.gebruiker_id,
                gebruiker_naam=a.gebruiker_naam,
            )
            for a in webauthn_service.kantoor_apparaten()
        ]
    )


# --- apparaatbeheer / kill-switch (kantoor) -------------------------------------------------------


@router.get("/gebruikers/{gebruiker_id}/apparaten", response_model=schemas.ApparatenResponse)
def apparaten_van_gebruiker(
    gebruiker_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.ApparatenResponse:
    """Beheerder-only (kill-switch-beheer op Instellingen → accordering)."""
    return schemas.ApparatenResponse(
        apparaten=[
            schemas.ApparaatResponse(
                id=a.id,
                apparaat_naam=a.apparaat_naam,
                is_dev_stub=a.is_dev_stub,
                aangemaakt_op=a.aangemaakt_op,
                laatst_gebruikt_op=a.laatst_gebruikt_op,
                ingetrokken_op=a.ingetrokken_op,
            )
            for a in webauthn_service.apparaten_van(gebruiker_id=gebruiker_id)
        ]
    )


@router.post("/apparaten/{apparaat_id}/intrekken", status_code=status.HTTP_204_NO_CONTENT)
def apparaat_intrekken(
    apparaat_id: uuid.UUID, actor: CurrentGebruiker = Depends(get_current_gebruiker)
) -> None:
    """Kill-switch: trekt de passkey-credential + alle gebonden sessies van dit apparaat in.
    Beheerder mag elk apparaat (óók andermans — kantoor-passkeys 0020); iedere andere rol
    uitsluitend de eigen apparaten — een niet-eigen apparaat antwoordt 404 (geen bestaans-lek).
    De laatste passkey intrekken sluit nooit buiten: wachtwoord + TOTP blijft het terugvalpad
    (accordeurs: wachtwoord + nieuwe registratie)."""
    try:
        webauthn_service.trek_apparaat_in(
            actor_id=actor.id,
            apparaat_id=apparaat_id,
            alleen_van_gebruiker=None if actor.rol == GebruikerRol.BEHEERDER else actor.id,
        )
    except service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- voorwaarden + privacyverklaring-akkoord (activeringsflow accordeur) --------------------------


@router.get("/accordeur/voorwaarden", response_model=schemas.VoorwaardenResponse)
def accordeur_voorwaarden(
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> schemas.VoorwaardenResponse:
    administraties = service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    return schemas.VoorwaardenResponse(
        tekst_versie=voorwaarden.AKKOORD_TEKST_VERSIE,
        tekst=voorwaarden.AKKOORD_TEKST,
        akkoord_gegeven=voorwaarden.heeft_akkoord(gebruiker_id=actor.id),
        administratie_namen=[a.naam for a in administraties],
    )


@router.post("/accordeur/voorwaarden-akkoord", status_code=status.HTTP_204_NO_CONTENT)
def accordeur_voorwaarden_akkoord(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> None:
    """Alleen zinvol (en toegestaan) voor de externe app-rollen (accordeur + veldrollen —
    zelfde app, zelfde voorwaarden-/privacyverklaring-poort); kantoor-rollen hebben deze
    informatieplicht-laag niet."""
    if not is_externe_app_rol(actor.rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor externe app-rollen"
        )
    voorwaarden.leg_akkoord_vast(gebruiker_id=actor.id)
