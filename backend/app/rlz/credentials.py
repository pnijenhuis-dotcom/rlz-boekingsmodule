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
        return _store_credential_voor(session, administratie.id)


def _store_credential_voor(session, administratie_id: uuid.UUID) -> tuple[str, str] | None:  # noqa: ANN001
    """De ene unwrap-route voor `platform.rlz_credential` (PK = administratie_id) — gedeeld door de gewone
    store-lookup (op rlz_admin_id) en de RLZ-verleden-lookup van een overgestapte administratie."""
    credential = session.get(RlzCredential, administratie_id)
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


def heeft_rlz_credential_geregistreerd(administratie_id: uuid.UUID, rlz_admin_id: str) -> bool:
    """Goedkope aanwezigheidstoets ZONDER unwrap/KMS (blok 1 08-09, reconciliatie-teller `bank_sync`):
    store-rij (platform.rlz_credential) óf gevulde .env-login voor het bekende prefix. Odoo-sentinels zijn
    per definitie geen RLZ-credential. Alleen voor tellers/rapportage — een échte verbinding toets je met
    `resolve_credentials`."""
    from app.odoo.ids import is_odoo_sentinel

    if is_odoo_sentinel(rlz_admin_id):
        return False
    with scoped_session(None) as session:
        if session.get(RlzCredential, administratie_id) is not None:
            return True
    prefix = _PREFIX_PER_RLZ_ADMIN_ID.get(rlz_admin_id)
    return prefix is not None and lees_env_login(prefix) is not None


def rlz_admin_id_voor(administratie_id: uuid.UUID) -> str:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise GeenRlzCredentials(f"Onbekende administratie: {administratie_id}")
        return administratie.rlz_admin_id


def client_voor_rlz_admin_id(rlz_admin_id: str) -> RlzClient:
    username, password = resolve_credentials(rlz_admin_id)
    return RlzClient(username=username, password=password, admin_id=rlz_admin_id)


RLZ_VERLEDEN_NIET_TOETSBAAR = "RLZ-verleden niet toetsbaar: geen bewaarde RLZ-credential"


def client_voor_rlz_verleden(administratie_id: uuid.UUID) -> RlzClient:
    """RLZ-leesclient voor het RLZ-VERLEDEN van een overgestapte administratie (RLZ → Odoo; besluit Peter 07-09
    op A12 beslispunt 1): documenten die vóór de kanteldatum in Reeleezee zijn geboekt blijven dáár de bron van
    waarheid (bewaarplicht 7 jaar) en worden tegen RLZ getoetst via de BEWAARDE credential.

    `administratie.rlz_admin_id` draagt ná de overstap de Odoo-sentinel, dus `client_voor_rlz_admin_id(oud_id)`
    vindt de store-rij niet meer (die zoekt op rlz_admin_id). Hier: oud RLZ-id uit `odoo_koppeling.
    rlz_admin_id_voor_overstap` + de `rlz_credential`-rij op administratie_id (blijft bij de overstap staan —
    nooit verwijderen), dev-fallback = .env-login voor het oude id. Geen bewaard id of geen credential
    (gearchiveerde webservice-login) = `GeenRlzCredentials` mét `RLZ_VERLEDEN_NIET_TOETSBAAR` — de aanroeper
    maakt daar een ZICHTBARE bevinding van, nooit een stille overslag."""
    from app.odoo.models import OdooKoppeling  # lazy: geen kring rlz ↔ odoo op moduleniveau

    with scoped_session(None) as session:
        koppeling = session.get(OdooKoppeling, administratie_id)
        oud_rlz_admin_id = koppeling.rlz_admin_id_voor_overstap if koppeling is not None else None
        if not oud_rlz_admin_id:
            raise GeenRlzCredentials(
                f"{RLZ_VERLEDEN_NIET_TOETSBAAR} (geen bewaard RLZ-administratie-id op de Odoo-koppeling)"
            )
        login = _store_credential_voor(session, administratie_id)
    if login is None:
        try:
            login = _resolve_from_env(oud_rlz_admin_id)
        except GeenRlzCredentials as exc:
            raise GeenRlzCredentials(f"{RLZ_VERLEDEN_NIET_TOETSBAAR} ({exc})") from exc
    username, password = login
    return RlzClient(username=username, password=password, admin_id=oud_rlz_admin_id)


def open_root_client(rlz_admin_id: str) -> RlzClient:
    """Onbescoped client (geen adminId-prefix in de requests) — nodig voor endpoints zonder
    administratie-context, zoals `Administrations` zelf (koppel-flow rechten-probe). Gebruik
    `.for_administration(rlz_admin_id)` op het resultaat voor de rest van de probes; sluit
    uitsluitend deze root-client af (de scoped variant deelt 'm en sluit niet echt af, zie
    RlzClient.for_administration)."""
    username, password = resolve_credentials(rlz_admin_id)
    return RlzClient(username=username, password=password)
