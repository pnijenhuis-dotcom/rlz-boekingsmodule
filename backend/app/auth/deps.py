from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.db.models import GebruikerAdministratie, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.security.tokens import TokenError, decode_token

_bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class CurrentGebruiker:
    id: uuid.UUID
    rol: GebruikerRol
    status: GebruikerStatus


def get_current_gebruiker(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentGebruiker:
    """Decodeert het access-token en haalt de ACTUELE rol/status uit de DB — nooit de claim in
    het token blindelings vertrouwen. Een access-token is kortlevend (15 min), maar een
    rol-downgrade of blokkering moet niet tot dan kunnen blijven gelden."""
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    gebruiker_id = uuid.UUID(payload["sub"])
    with scoped_session(None) as session:
        row = session.execute(
            text("SELECT rol, status FROM platform.gebruiker WHERE id = :id"),
            {"id": gebruiker_id},
        ).first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Onbekende gebruiker")
    rol_waarde, status_waarde = row
    if status_waarde != GebruikerStatus.ACTIEF.value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account niet actief")
    return CurrentGebruiker(id=gebruiker_id, rol=GebruikerRol(rol_waarde), status=GebruikerStatus(status_waarde))


def require_beheerder(current: CurrentGebruiker = Depends(get_current_gebruiker)) -> CurrentGebruiker:
    if current.rol != GebruikerRol.BEHEERDER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alleen toegestaan voor Beheerder")
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
