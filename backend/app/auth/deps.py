from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.auth.rollen import is_externe_app_rol, is_kantoorrol
from app.db.models import GebruikerAdministratie, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.security.tokens import TokenError, decode_token

_bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class CurrentGebruiker:
    id: uuid.UUID
    rol: GebruikerRol
    status: GebruikerStatus
    # Apparaat-claim uit het access-token (passkey-sessie, migratie 0040) — None bij een
    # TOTP-sessie zonder apparaatbinding. Gebruikt door de push-subscriptie-endpoints
    # (berichten-bouwsteen): een subscriptie hoort bij precies dit geregistreerde apparaat,
    # zodat de kill-switch 'm mee intrekt.
    apparaat_id: uuid.UUID | None = None


def get_current_gebruiker(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentGebruiker:
    """Decodeert het access-token en haalt de ACTUELE rol/status uit de DB — nooit de claim in
    het token blindelings vertrouwen. Een access-token is kortlevend (15 min), maar een
    rol-downgrade of blokkering moet niet tot dan kunnen blijven gelden. Draagt het token een
    apparaat-claim (passkey-sessie, migratie 0040), dan geldt hetzelfde voor de
    kill-switch: een ingetrokken apparaat valt per direct uit, niet pas bij de volgende
    refresh."""
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    gebruiker_id = uuid.UUID(payload["sub"])
    apparaat_claim = payload.get("apparaat")
    with scoped_session(None) as session:
        row = session.execute(
            text("SELECT rol, status FROM platform.gebruiker WHERE id = :id"),
            {"id": gebruiker_id},
        ).first()
        apparaat_ingetrokken = False
        if apparaat_claim is not None:
            cred_row = session.execute(
                text("SELECT ingetrokken_op FROM platform.webauthn_credential WHERE id = :id"),
                {"id": uuid.UUID(apparaat_claim)},
            ).first()
            apparaat_ingetrokken = cred_row is None or cred_row[0] is not None

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Onbekende gebruiker")
    if apparaat_ingetrokken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Toegang voor dit apparaat is ingetrokken"
        )
    rol_waarde, status_waarde = row
    if status_waarde != GebruikerStatus.ACTIEF.value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account niet actief")
    return CurrentGebruiker(
        id=gebruiker_id,
        rol=GebruikerRol(rol_waarde),
        status=GebruikerStatus(status_waarde),
        apparaat_id=uuid.UUID(apparaat_claim) if apparaat_claim is not None else None,
    )


def vereis_kantoorrol(current: CurrentGebruiker = Depends(get_current_gebruiker)) -> CurrentGebruiker:
    """Kantoor-console-endpoints: elke externe app-rol (klant-accordeur + veldrollen, zie
    app/auth/rollen.py) krijgt 403 — rolniveau-poort, LOS van administratie-scope. Dat laatste
    is essentieel: accordeurs én veldwerkers hebben reguliere gebruiker_administratie-rijen
    (hun eigen flows vereisen die), dus vereis_administratie_scope alléén houdt ze niet buiten
    kantoor-data (rollen-gate-bug kliktest 2026-08-21). Router-breed toepasbaar via
    `APIRouter(dependencies=[Depends(vereis_kantoorrol)])` — dan zijn ook toekomstige
    endpoints in die router automatisch dicht (fail-closed)."""
    if is_externe_app_rol(current.rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Alleen toegankelijk voor kantoorrollen"
        )
    return current


def vereis_kantoor_of_accordeur(
    current: CurrentGebruiker = Depends(get_current_gebruiker),
) -> CurrentGebruiker:
    """Endpoints die de accordeur-PWA zelf nodig heeft bovenop het kantoor (PDF-bestand,
    accorderingsbesluiten, staande regels): veldrollen — en elke toekomstige rol die niet
    expliciet kantoor of klant-accordeur is — krijgen 403. Bewust een allowlist, geen
    `not is_veldrol`: een nieuwe externe rol valt dan dicht i.p.v. stil open."""
    if not (is_kantoorrol(current.rol) or current.rol == GebruikerRol.KLANT_ACCORDEUR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen toegankelijk voor kantoorrollen en klant-accordeurs",
        )
    return current


def require_beheerder(current: CurrentGebruiker = Depends(get_current_gebruiker)) -> CurrentGebruiker:
    if current.rol != GebruikerRol.BEHEERDER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alleen toegestaan voor Beheerder")
    return current


def require_beheerder_of_bp(current: CurrentGebruiker = Depends(get_current_gebruiker)) -> CurrentGebruiker:
    """Beheerder óf Boekhouding+Projecten (besluit Peter 31-08: leverancier-/catalogusbeheer
    verruimd naar B+P; audit ongewijzigd). Bewust een aparte dependency — require_beheerder
    blijft de harde poort voor gebruikers-/rechtenbeheer."""
    if current.rol not in (GebruikerRol.BEHEERDER, GebruikerRol.BOEKHOUDING_PROJECTEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Alleen toegestaan voor Beheerder en Boekhouding+Projecten"
        )
    return current


def require_beheerder_of_veldwerkerbeheer(
    current: CurrentGebruiker = Depends(get_current_gebruiker),
) -> CurrentGebruiker:
    """Gebruikersbeheer blijft exclusief Beheerder, mét één fijnmazige uitzondering (besluit
    Peter 31-08, 0019-patroon, migratie 0091): een kantoormedewerker mét het module-recht
    'veldwerkerbeheer' mag UITSLUITEND veldwerkers (ZZP'er/uitvoerder/detacheerder) aanmaken en
    archiveren binnen de eigen administratie-scope — nooit kantoorrollen, nooit rol-/scope-
    mutaties. Die inhoudelijke begrenzing dwingt de service af (app/auth/service.py); deze
    dependency opent alleen de deur voor houders van het recht."""
    if current.rol == GebruikerRol.BEHEERDER:
        return current
    from app.uren.service import heeft_veldwerkerbeheer_recht

    if not heeft_veldwerkerbeheer_recht(gebruiker_id=current.id, rol=current.rol):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alleen toegestaan voor Beheerder")
    return current


def require_meerwerk_urenstaten_recht(
    current: CurrentGebruiker = Depends(get_current_gebruiker),
) -> CurrentGebruiker:
    """Module-recht 'Meerwerk & urenstaten' (0019-patroon, migratie 0056): Beheerder altijd,
    andere kantoor-rollen alleen mét gebruiker_module_rol-rij — server-side afgedwongen op
    élk meerwerk-/urenstaten-kantoor-endpoint (menu/standen/zoeken/API); zonder recht
    verdwijnt de module overal, niet alleen in de UI. De klantscope (vereis_administratie_
    scope) blijft eronder gelden."""
    from app.uren.service import heeft_meerwerk_urenstaten_recht

    if not heeft_meerwerk_urenstaten_recht(gebruiker_id=current.id, rol=current.rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vereist het module-recht 'Meerwerk & urenstaten'",
        )
    return current


def vereis_administratie_scope(
    administratie_id: uuid.UUID, current: CurrentGebruiker = Depends(get_current_gebruiker)
) -> CurrentGebruiker:
    """Beheerder is platform-breed (zelfde bypass als platform.current_actor_is_beheerder() in de
    DB, migratie 0002); iedere andere rol moet een gebruiker_administratie-rij op precies déze
    administratie hebben. De sessie wordt bewust gescoped OP `administratie_id` (niet None) — de
    gebruiker_administratie-tabel heeft zelf RLS (migratie 0002); zonder deze scope zou de SELECT
    hieronder voor een niet-Beheerder altijd niets teruggeven, ook als de rij echt bestaat."""
    if current.rol == GebruikerRol.BEHEERDER:
        return current
    with scoped_session(administratie_id, actor_id=current.id) as session:
        heeft_scope = session.get(GebruikerAdministratie, (current.id, administratie_id)) is not None
    if not heeft_scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Geen toegang tot deze administratie")
    return current
