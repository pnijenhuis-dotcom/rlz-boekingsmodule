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


# TIJDELIJK: BLOw ontbreekt bewust — het volledige RLZ-adminId staat nergens in de repo
# (registers/entiteiten.md toont het afgekapt), dus geen aanname/gok hier. Nieuwe administraties
# hier toevoegen zodra het volledige adminId bevestigd is (admin-pin: list_administrations()
# moet exact deze ene administratie tonen).
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
    # Onboarding-batch 2026-08-15 (lijst Peter 15-08): adminId's live geverifieerd via
    # list_administrations() per login (elk exact één administratie — admin-pin). Namen exact
    # conform Peters lijst; enige RLZ-naamverschil: RLZ toont "Arvum B.V." (casing) — bewust
    # niet stil overgenomen, zie BESLISSINGEN "Onboarding-batch 15-08". Env-vars van deze
    # groep volgen de nieuwe conventie RLZ_{PREFIX}_GEBRUIKER/-_WACHTWOORD (zie lees_env_login).
    BekendeAdministratie(prefix="ARVUM", rlz_admin_id="9da1f3ab-f2c5-4f40-a241-a7f2592a08ce", naam="ARVUM B.V."),
    BekendeAdministratie(
        prefix="MEYER", rlz_admin_id="8d87b05c-f3b8-42a0-a805-30e1aafa1e3a", naam="Beleggingsmaatschappij Meyer BV"
    ),
    BekendeAdministratie(
        prefix="ELISSEN", rlz_admin_id="291d2d57-9c90-46c8-b7dc-f711e9386ec4", naam="J.G.M. Elissen Holding BV"
    ),
    BekendeAdministratie(
        prefix="FACILITIES", rlz_admin_id="7bc1e33a-8860-40d7-aef3-08ecad3ad7cf", naam="Kempen Facilities B.V."
    ),
    BekendeAdministratie(
        prefix="MOLENHOFB", rlz_admin_id="71d59ccc-fb7d-4ae2-a0e2-0e0082b5b754", naam="Molenhof Beheer B.V."
    ),
    BekendeAdministratie(
        prefix="MOLENHOFV", rlz_admin_id="b86f0c6d-42e2-4f62-b9f4-74077f4282fe", naam="Molenhof Verhuur B.V."
    ),
    BekendeAdministratie(
        prefix="OIRSCHOT", rlz_admin_id="3a798481-8c00-49d9-a5f6-3757794c440e", naam="Oirschot Recreatie B.V."
    ),
    BekendeAdministratie(
        prefix="OVB", rlz_admin_id="ecfa2f7c-a230-4963-92d9-e7db6a509184", naam="Oirschot Vastgoed Beheer B.V."
    ),
    BekendeAdministratie(
        prefix="VELDHOVEN", rlz_admin_id="dc079584-5f7e-462f-9dbd-a9784763ae2a", naam="Veldhoven Recreatie B.V."
    ),
    BekendeAdministratie(
        prefix="SHUTO", rlz_admin_id="44fb7376-49a5-4c2c-908d-8da14fafdc6f", naam="Stichting Shuto"
    ),
    # Na-onboarding 2026-08-15: bij de batch gaf deze login een 401; na credential-herstel door
    # Peter dezelfde dag alsnog onboarded (adminId live geverifieerd via admin-pin, probe 10/10).
    BekendeAdministratie(
        prefix="NIJENHUIS",
        rlz_admin_id="97ac3a99-da88-4084-b163-06e23d329e05",
        naam="Administratiekantoor Nijenhuis C.V.",
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


def lees_env_login(prefix: str) -> tuple[str, str] | None:
    """Login uit de omgeving voor één prefix — kent beide naamconventies: de legacy-vorm
    `{PREFIX}_USERNAME`/`{PREFIX}_PASSWORD` (eerste vijf logins) en de vorm van de
    onboarding-batch 15-08 `RLZ_{PREFIX}_GEBRUIKER`/`RLZ_{PREFIX}_WACHTWOORD` (verkenning/.env).
    None = niet (volledig) gevuld."""
    username = os.environ.get(f"{prefix}_USERNAME") or os.environ.get(f"RLZ_{prefix}_GEBRUIKER")
    password = os.environ.get(f"{prefix}_PASSWORD") or os.environ.get(f"RLZ_{prefix}_WACHTWOORD")
    if not username or not password:
        return None
    return username, password


def _resolve_from_env(rlz_admin_id: str) -> tuple[str, str]:
    prefix = _PREFIX_PER_RLZ_ADMIN_ID.get(rlz_admin_id)
    if prefix is None:
        raise GeenRlzCredentials(f"Geen credential-prefix geregistreerd voor RLZ-adminId {rlz_admin_id!r}")
    login = lees_env_login(prefix)
    if login is None:
        raise GeenRlzCredentials(
            f"{prefix}_USERNAME/{prefix}_PASSWORD (of RLZ_{prefix}_GEBRUIKER/-_WACHTWOORD) "
            f"niet gevuld in de omgeving"
        )
    return login


def resolve_credentials(rlz_admin_id: str) -> tuple[str, str]:
    """Store-first (besluit 0001, credential-store is gedeeld platform-fundament): de DB-store
    (platform.rlz_credential) heeft voorrang; .env is de dev-fallback zolang niet elke
    administratie in de store zit — zie app/credentialstore/service.py::importeer_env_credentials
    voor het eenmalige overzetcommando.

    Odoo-administraties (migratie 0101) dragen een sentinel als rlz_admin_id: élke poging om er een
    RlzClient voor te openen is fail-loud — RLZ-rakende jobs slaan zo'n administratie zichtbaar over
    via hun bestaande GeenRlzCredentials-afhandeling (nooit stil, nooit per ongeluk RLZ)."""
    from app.odoo.ids import is_odoo_sentinel

    if is_odoo_sentinel(rlz_admin_id):
        raise GeenRlzCredentials(
            f"Administratie draait op Odoo ({rlz_admin_id}) — geen Reeleezee-verbinding; deze bewerking loopt "
            "via de Odoo-adapter of is voor Odoo-administraties (nog) niet beschikbaar"
        )
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
