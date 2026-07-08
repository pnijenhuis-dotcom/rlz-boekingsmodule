from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie, RlzCredential, RlzRechtenProbe
from app.db.session import scoped_session
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import BEKENDE_ADMINISTRATIES, BekendeAdministratie, open_root_client
from app.security.envelope import wrap_secret


class CredentialStoreFout(Exception):
    """Domeinfout in de credential-store-servicelaag (bv. onbekende administratie)."""


def zet_credential(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, webservice_username: str, wachtwoord: str
) -> None:
    """Aanmaken of overschrijven (upsert) — één credential-set per administratie. Beheerder-only,
    afgedwongen door de router-dependency, niet hier. Het wachtwoord zelf komt NOOIT in
    audit_event terecht (besluit 0012) — alleen de username en het feit van de wijziging."""
    ciphertext, wrapped_data_key = wrap_secret(wachtwoord.encode())

    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise CredentialStoreFout(f"Onbekende administratie: {administratie_id}")

        bestaand = session.get(RlzCredential, administratie_id)
        if bestaand is None:
            session.add(
                RlzCredential(
                    administratie_id=administratie_id,
                    webservice_username=webservice_username,
                    wachtwoord_ciphertext=ciphertext,
                    wrapped_data_key=wrapped_data_key,
                    aangemaakt_door=actor_id,
                )
            )
            actie = "credential_aangemaakt"
        else:
            bestaand.webservice_username = webservice_username
            bestaand.wachtwoord_ciphertext = ciphertext
            bestaand.wrapped_data_key = wrapped_data_key
            actie = "credential_bijgewerkt"

        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="rlz_credential",
            record_id=administratie_id,
            actie=actie,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"webservice_username": webservice_username},
        )


@dataclass(frozen=True)
class CredentialMetadata:
    """Bewust GEEN wachtwoord-veld — deze dataclass is de enige weg naar de API-laag, dus het
    geheim kan hier structureel niet doorheen lekken (besluit 0012)."""

    administratie_id: uuid.UUID
    webservice_username: str
    aangemaakt_op: datetime
    bijgewerkt_op: datetime


def haal_credential_metadata_op(*, administratie_id: uuid.UUID) -> CredentialMetadata | None:
    with scoped_session(None) as session:
        rij = session.get(RlzCredential, administratie_id)
        if rij is None:
            return None
        return CredentialMetadata(
            administratie_id=rij.administratie_id,
            webservice_username=rij.webservice_username,
            aangemaakt_op=rij.aangemaakt_op,
            bijgewerkt_op=rij.bijgewerkt_op,
        )


_TE_IMPORTEREN_PREFIXEN = ("RLZ", "UNIVERSAL", "TESTADMIN", "KEMPEN", "RUBICON")


def _zorg_voor_administratie(bekend: BekendeAdministratie) -> uuid.UUID:
    with scoped_session(None) as session:
        bestaand = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == bekend.rlz_admin_id)
        ).one_or_none()
        if bestaand is not None:
            return bestaand.id
        administratie_id = uuid.uuid4()
        session.add(Administratie(id=administratie_id, naam=bekend.naam, rlz_admin_id=bekend.rlz_admin_id))
        return administratie_id


def importeer_env_credentials(*, actor_id: uuid.UUID) -> dict[str, str]:
    """Eenmalige overzet-hulp (CLI, zie app/cli.py): de bekende .env-logins de store in. Skipt
    (met duidelijke reden) prefixen zonder geregistreerd RLZ-adminId (BLOw, Kempen Facilities —
    zie app/rlz/credentials.py::BEKENDE_ADMINISTRATIES, hun volledige adminId staat nergens in de
    repo) en prefixen zonder gevulde env-vars. Maakt de platform.administratie-rij aan als die
    nog niet bestaat (naar analogie van het bootstrap-CLI-patroon: eenmalig, CLI-only, geen
    seed-logica in migraties)."""
    bekend_per_prefix = {a.prefix: a for a in BEKENDE_ADMINISTRATIES}
    resultaten: dict[str, str] = {}
    for prefix in _TE_IMPORTEREN_PREFIXEN:
        username = os.environ.get(f"{prefix}_USERNAME")
        wachtwoord = os.environ.get(f"{prefix}_PASSWORD")
        if not username or not wachtwoord:
            resultaten[prefix] = "overgeslagen: env-vars niet gevuld"
            continue
        bekend = bekend_per_prefix.get(prefix)
        if bekend is None:
            resultaten[prefix] = "overgeslagen: geen geregistreerd RLZ-adminId voor deze prefix"
            continue
        administratie_id = _zorg_voor_administratie(bekend)
        zet_credential(
            actor_id=actor_id, administratie_id=administratie_id, webservice_username=username, wachtwoord=wachtwoord
        )
        resultaten[prefix] = f"geïmporteerd (administratie_id={administratie_id})"
    return resultaten


_TE_PROBEREN_ENDPOINTS = (
    "Administrations",
    "Ledgers",
    "TaxRates",
    "Vendors",
    "Customers",
    "Projects",
    "SalesInvoices",
    "PurchaseInvoices",
    "JournalEntries",
    "PaymentAccounts",
)


def voer_rechten_probe_uit(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, client: RlzClient | None = None
) -> dict[str, str]:
    """Read-only rechtenrapport voor de koppel-flow (nieuwe administratie aansluiten): per
    endpoint 'ok' of de HTTP-statuscode als string. `Administrations` gaat via de onbescoped
    root-client (top-level endpoint, geen adminId-routing — zie open_root_client); de overige
    endpoints via de administratie-gescoped client, exact zoals de rest van de app RLZ aanspreekt."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise CredentialStoreFout(f"Onbekende administratie: {administratie_id}")
        rlz_admin_id = administratie.rlz_admin_id

    eigen_client = client is None
    if client is None:
        client = open_root_client(rlz_admin_id)
    scoped_client = client.for_administration(rlz_admin_id)

    try:
        rapport: dict[str, str] = {}
        for endpoint in _TE_PROBEREN_ENDPOINTS:
            actieve_client = client if endpoint == "Administrations" else scoped_client
            try:
                actieve_client.get(endpoint)
                rapport[endpoint] = "ok"
            except RlzApiError as exc:
                rapport[endpoint] = str(exc.status_code)
    finally:
        if eigen_client:
            client.close()

    now = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        bestaand = session.get(RlzRechtenProbe, administratie_id)
        if bestaand is None:
            session.add(RlzRechtenProbe(administratie_id=administratie_id, rapport=rapport, uitgevoerd_door=actor_id))
        else:
            bestaand.rapport = rapport
            bestaand.uitgevoerd_door = actor_id
            bestaand.uitgevoerd_op = now
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="rlz_rechten_probe",
            record_id=administratie_id,
            actie="rechten_probe_uitgevoerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "aantal_ok": sum(1 for v in rapport.values() if v == "ok"),
                "aantal_totaal": len(rapport),
            },
        )
    return rapport
