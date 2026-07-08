from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db.models import Administratie, RlzCredential
from app.db.session import scoped_session
from app.rlz.client import RlzClient
from app.security.envelope import unwrap_secret


@dataclass(frozen=True)
class BekendeAdministratie:
    """Een administratie waarvan het RLZ-adminId geverifieerd is (zie verkenning/api-verkenning.md
    en Platform/registers/entiteiten.md) — gebruikt voor de .env-fallback én het
    CLI-importcommando (app/credentialstore/service.py::importeer_env_credentials)."""

    prefix: str
    rlz_admin_id: str
    naam: str


# TIJDELIJK: BLOw en Kempen Facilities ontbreken bewust — hun volledige RLZ-adminId staat nergens
# in de repo (registers/entiteiten.md toont BLOw afgekapt; Kempen Facilities staat er nog
# helemaal niet in), dus geen aanname/gok hier. Nieuwe administraties hier toevoegen zodra het
# volledige adminId bevestigd is.
BEKENDE_ADMINISTRATIES: tuple[BekendeAdministratie, ...] = (
    BekendeAdministratie(
        prefix="UNIVERSAL", rlz_admin_id="3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac", naam="Universal Steigerbouw B.V."
    ),
    BekendeAdministratie(
        prefix="TESTADMIN",
        rlz_admin_id="8dbfb856-d75b-4ec3-9124-c8b739fe3bc5",
        naam="Administratiekantoor Nijenhuis (test)",
    ),
    BekendeAdministratie(
        prefix="RUBICON", rlz_admin_id="be5e66b3-b38c-4927-85c1-670490f16e3a", naam="Rubicon Investments B.V."
    ),
)
_PREFIX_PER_RLZ_ADMIN_ID: dict[str, str] = {a.rlz_admin_id: a.prefix for a in BEKENDE_ADMINISTRATIES}


class GeenRlzCredentials(Exception):
    """Geen credentials beschikbaar voor deze RLZ-administratie — noch in de store, noch in de
    .env-fallback (nog niet geregistreerd, of de env-vars zijn niet gevuld)."""


def _resolve_from_store(rlz_admin_id: str) -> tuple[str, str] | None:
    with scoped_session(None) as session:
        administratie = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == rlz_admin_id)
        ).one_or_none()
        if administratie is None:
            return None
        credential = session.get(RlzCredential, administratie.id)
        if credential is None:
            return None
        wachtwoord = unwrap_secret(credential.wachtwoord_ciphertext, credential.wrapped_data_key).decode()
        return credential.webservice_username, wachtwoord


def _resolve_from_env(rlz_admin_id: str) -> tuple[str, str]:
    prefix = _PREFIX_PER_RLZ_ADMIN_ID.get(rlz_admin_id)
    if prefix is None:
        raise GeenRlzCredentials(f"Geen credential-prefix geregistreerd voor RLZ-adminId {rlz_admin_id!r}")
    username = os.environ.get(f"{prefix}_USERNAME")
    password = os.environ.get(f"{prefix}_PASSWORD")
    if not username or not password:
        raise GeenRlzCredentials(f"{prefix}_USERNAME/{prefix}_PASSWORD niet gevuld in de omgeving")
    return username, password


def resolve_credentials(rlz_admin_id: str) -> tuple[str, str]:
    """Store-first (besluit 0001, credential-store is gedeeld platform-fundament): de DB-store
    (platform.rlz_credential) heeft voorrang; .env is de dev-fallback zolang niet elke
    administratie in de store zit — zie app/credentialstore/service.py::importeer_env_credentials
    voor het eenmalige overzetcommando."""
    store_credentials = _resolve_from_store(rlz_admin_id)
    if store_credentials is not None:
        return store_credentials
    return _resolve_from_env(rlz_admin_id)


def rlz_admin_id_voor(administratie_id: uuid.UUID) -> str:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise GeenRlzCredentials(f"Onbekende administratie: {administratie_id}")
        return administratie.rlz_admin_id


def client_voor_rlz_admin_id(rlz_admin_id: str) -> RlzClient:
    username, password = resolve_credentials(rlz_admin_id)
    return RlzClient(username=username, password=password, admin_id=rlz_admin_id)


def open_root_client(rlz_admin_id: str) -> RlzClient:
    """Onbescoped client (geen adminId-prefix in de requests) — nodig voor endpoints zonder
    administratie-context, zoals `Administrations` zelf (koppel-flow rechten-probe). Gebruik
    `.for_administration(rlz_admin_id)` op het resultaat voor de rest van de probes; sluit
    uitsluitend deze root-client af (de scoped variant deelt 'm en sluit niet echt af, zie
    RlzClient.for_administration)."""
    username, password = resolve_credentials(rlz_admin_id)
    return RlzClient(username=username, password=password)
