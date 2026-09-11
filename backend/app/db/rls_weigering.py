"""RLS-weigering = systeemfout "automatisch gemeld" (blok 1 run 11-09 middag).

Aanleiding: `POST …/documenten/{id}/verplaats` gaf in productie tweemaal een kale 500 (correlatie-id 2fa4a61b-…)
op `psycopg.errors.InsufficientPrivilege: new row violates row-level security policy for table "document"` —
een schrijfpad dat door het RLS-beleid werd geweigerd (migratie 0080 werkte op Cloud SQL nooit, fix 0132). Zo'n
weigering is per definitie een BUG in de app-laag (de app hoort nooit iets te proberen dat RLS moet tegenhouden),
geen handeling voor de gebruiker — dus: leesbare melding aan de client, en het systeem meldt zichzelf:

- audit_event `rls_weigering` (platform-breed, systeem-actor; route, methode, correlatie-id, tabel uit de melding,
  de aangemelde gebruiker als `gebruiker_id` in de nieuwe waarde);
- bewakingsprobe `rls_weigering` (app/bewaking/service.py): audit-rijen in de laatste 24 u > 0 = alert;
- LET-OP in de reconciliatie-tellers (automatiseringen.rls_weigering_bevindingen): "Systeemfout — automatisch
  gemeld: RLS-weigering op <route>" mét deeplink naar het document.

Herkenning loopt over de volledige exception-keten (`__cause__`/`__context__` én SQLAlchemy's `.orig`), zodat
zowel de centrale onverwachte-fout-handler (app/main.py) als een router die de fout zélf vertaalt dezelfde bron
gebruiken. Registreren faalt nooit hard: een audit-fout wordt gelogd, de 500 aan de client blijft staan.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from psycopg.errors import InsufficientPrivilege

logger = logging.getLogger(__name__)

AUDIT_ACTIE = "rls_weigering"
_TABEL = re.compile(r'for table "([^"]+)"')
_TABEL_RELATIE = re.compile(r'relation "([^"]+)"')


def vind_insufficient_privilege(exc: BaseException | None) -> InsufficientPrivilege | None:
    """De eerste `InsufficientPrivilege` in de keten (cause/context/SQLAlchemy `.orig`), of None."""
    gezien: set[int] = set()
    stapel: list[BaseException] = [exc] if exc is not None else []
    while stapel:
        huidige = stapel.pop()
        if id(huidige) in gezien:
            continue
        gezien.add(id(huidige))
        if isinstance(huidige, InsufficientPrivilege):
            return huidige
        orig = getattr(huidige, "orig", None)
        for volgende in (orig, huidige.__cause__, huidige.__context__):
            if isinstance(volgende, BaseException):
                stapel.append(volgende)
    return None


def tabel_uit_melding(melding: str) -> str | None:
    m = _TABEL.search(melding) or _TABEL_RELATIE.search(melding)
    return m.group(1) if m else None


def gebruiker_uit_bearer(authorization: str | None) -> uuid.UUID | None:
    """Het `sub` uit een access-token, zonder DB-lookup (de handler draait buiten elke dependency). Nooit een fout:
    een onleesbaar of verlopen token = onbekende gebruiker."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        from app.security.tokens import decode_token

        payload = decode_token(authorization.split(" ", 1)[1].strip(), expected_type="access")
        return uuid.UUID(str(payload["sub"]))
    except Exception:  # noqa: BLE001 — diagnostisch, nooit blokkerend
        return None


def registreer(
    *,
    exc: BaseException,
    route: str,
    methode: str,
    correlatie_id: uuid.UUID,
    gebruiker_id: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Audit `rls_weigering` (administratie-loos, systeem-actor). True = geschreven; False = geen RLS-weigering of
    de audit zelf mislukte (gelogd, nooit een tweede fout richting de client)."""
    gevonden = vind_insufficient_privilege(exc)
    if gevonden is None:
        return False
    melding = str(gevonden).strip()
    try:
        from app.db.audit import record_audit_event
        from app.db.session import scoped_session
        from app.db.systeem_actor import SYSTEEM_ACTOR_ID

        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="platform",
                tabel="rls_weigering",
                record_id=correlatie_id,
                actie=AUDIT_ACTIE,
                correlatie_id=correlatie_id,
                nieuwe_waarde={
                    "route": route[:300],
                    "methode": methode,
                    "tabel": tabel_uit_melding(melding),
                    "melding": melding[:500],
                    "gebruiker_id": str(gebruiker_id) if gebruiker_id else None,
                    **(extra or {}),
                },
            )
        return True
    except Exception:  # noqa: BLE001 — de 500 naar de client blijft; dit is het vangnet zelf
        logger.exception("rls_weigering: audit kon niet worden geschreven (route %s %s)", methode, route)
        return False


def route_patroon(route: str) -> str:
    """Route met UUID's vervangen door `{id}` — één vingerafdruk per endpoint, niet per document."""
    return re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "{id}", route)


def doel_pad_voor_route(route: str) -> str:
    """Deeplink voor de LET-OP: een document-route → het document in de kantoor-UI, anders /reconciliatie."""
    m = re.match(
        r"^/administraties/([0-9a-fA-F-]{36})/documenten/([0-9a-fA-F-]{36})(?:/|$)",
        route,
    )
    if m:
        return f"/documenten/{m.group(1)}/{m.group(2)}"
    return "/reconciliatie"
