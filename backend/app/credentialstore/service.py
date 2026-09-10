from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie, RlzCredential, RlzRechtenProbe
from app.db.session import scoped_session
from app.rlz import leesroutes
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import BEKENDE_ADMINISTRATIES, BekendeAdministratie, lees_env_login, open_root_client
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


def trek_credential_in(*, actor_id: uuid.UUID, administratie_id: uuid.UUID) -> bool:
    """Webservice-login intrekken (archiveren van een administratie, v2 30-08): de credential-rij
    verdwijnt uit de store (een geheim, geen boekhoudkundige data — het audit_event blijft als spoor;
    DELETE-grant sinds migratie 0089). Zonder credential valt élke RLZ-toegang voor deze administratie
    weg (store-first; de .env-terugval geldt alleen in dev). Idempotent: geen rij = False, geen fout."""
    with scoped_session(None, actor_id=actor_id) as session:
        bestaand = session.get(RlzCredential, administratie_id)
        if bestaand is None:
            return False
        username = bestaand.webservice_username
        session.delete(bestaand)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="rlz_credential",
            record_id=administratie_id,
            actie="credential_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"webservice_username": username},
            nieuwe_waarde=None,
        )
        return True


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


# Legacy-vijf + de onboarding-batch 15-08 (lijst Peter; env-vorm RLZ_{PREFIX}_GEBRUIKER/-
# _WACHTWOORD — zie app/rlz/credentials.py::lees_env_login) + NIJENHUIS (na-onboarding
# 15-08, ná credential-herstel — 401 bij de batch zelf). RLZ (BLOw) en KEMPEN blijven staan
# als legacy-skips zolang hun registry-rij ontbreekt.
_TE_IMPORTEREN_PREFIXEN = (
    "RLZ",
    "UNIVERSAL",
    "TESTADMIN",
    "KEMPEN",
    "RUBICON",
    "ARVUM",
    "MEYER",
    "ELISSEN",
    "FACILITIES",
    "MOLENHOFB",
    "MOLENHOFV",
    "OIRSCHOT",
    "OVB",
    "VELDHOVEN",
    "SHUTO",
    "NIJENHUIS",
)


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
    """Overzet-hulp (CLI, zie app/cli.py): de bekende .env-logins de store in. Skipt (met
    duidelijke reden) prefixen zonder geregistreerd RLZ-adminId (BLOw via prefix RLZ; KEMPEN =
    de legacy-prefix van Facilities, dat sinds de onboarding-batch 15-08 onder FACILITIES
    geregistreerd staat) en prefixen zonder gevulde env-vars. Maakt de
    platform.administratie-rij aan als die nog niet bestaat (naar analogie van het
    bootstrap-CLI-patroon: eenmalig, CLI-only, geen seed-logica in migraties)."""
    bekend_per_prefix = {a.prefix: a for a in BEKENDE_ADMINISTRATIES}
    resultaten: dict[str, str] = {}
    for prefix in _TE_IMPORTEREN_PREFIXEN:
        login = lees_env_login(prefix)
        if login is None:
            resultaten[prefix] = "overgeslagen: env-vars niet gevuld"
            continue
        username, wachtwoord = login
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


#: Compat-alias: de probe-set leeft sinds 10-09 in app/rlz/leesroutes.py (één bron mét de sync-paden).
_TE_PROBEREN_ENDPOINTS = tuple(r.naam for r in leesroutes.PROBE_LEESROUTES)

#: Maximale lengte van het letterlijke RLZ-antwoord dat we in rapport/melding/audit bewaren (blok C 10-09).
RLZ_MELDING_MAX = 300


@dataclass(frozen=True)
class ProbeUitkomst:
    """Rechtenrapport (`rapport`: route → 'ok' | HTTP-status als string — de bestaande DTO-/opslagvorm) plús per rode
    route het LETTERLIJKE RLZ-antwoord (`meldingen`: route → "HTTP <status> — <body, afgekapt>"), zodat de Beheerder
    ziet wát RLZ zegt en niet alleen de statuscode (blok C 10-09)."""

    rapport: dict[str, str]
    meldingen: dict[str, str]


def _rlz_melding(exc: RlzApiError) -> str:
    body = " ".join((exc.body or "").split())
    if len(body) > RLZ_MELDING_MAX:
        body = body[: RLZ_MELDING_MAX - 1] + "…"
    return f"HTTP {exc.status_code}" + (f" — {body}" if body else " — (leeg antwoord)")


def voer_probe_uit(client: RlzClient, rlz_admin_id: str) -> ProbeUitkomst:
    """Het rechtenrapport voor één RLZ-administratie met een gegeven (root-)client — herbruikbaar vóór er een
    administratie-rij bestaat (onboarding-wizard, punt 5 26-08). De set komt uit `leesroutes.PROBE_LEESROUTES`:
    `Administrations` via de root-client, de rest via de gescoped variant met EXACT het pad (+ params) dat de sync-
    motoren gebruiken — bewaakt door tests/rlz/test_leesroutes.py."""
    scoped_client = client.for_administration(rlz_admin_id)
    rapport: dict[str, str] = {}
    meldingen: dict[str, str] = {}
    for route in leesroutes.PROBE_LEESROUTES:
        actieve_client = client if route.scope == "root" else scoped_client
        try:
            if route.params:
                actieve_client.get(route.pad, params=dict(route.params))
            else:
                actieve_client.get(route.pad)
            rapport[route.naam] = "ok"
        except RlzApiError as exc:
            rapport[route.naam] = str(exc.status_code)
            meldingen[route.naam] = _rlz_melding(exc)
    return ProbeUitkomst(rapport=rapport, meldingen=meldingen)


def probe_rapport(client: RlzClient, rlz_admin_id: str) -> dict[str, str]:
    """Compat: alleen het kale rapport (route → 'ok' | status). Nieuwe aanroepers gebruiken `voer_probe_uit`."""
    return voer_probe_uit(client, rlz_admin_id).rapport


def verkoopmodule_afwezig_in(rapport: dict[str, str]) -> bool:
    """Facturatiemodule niet afgenomen (spoedopdracht 01-09 blok A, casus A.Y. Holding 2 + Abbegaa,
    bevestigd door Peter in de RLZ-UI): een RLZ-administratie zonder facturatie-/verkoopmodule geeft
    op de SalesInvoices-collectie een 403 ongeacht de gebruikersrechten. UITSLUITEND die combinatie
    telt als "module afwezig" — elke andere fout (ook op SalesInvoices) blijft een echte rechtenfout."""
    return rapport.get("SalesInvoices") == "403"


def probe_is_groen(rapport: dict[str, str]) -> bool:
    """Bruikbaar aangesloten: alle leesroutes ok, mét als enige uitzondering SalesInvoices-403 =
    "facturatiemodule niet afgenomen" (besluit 01-09) — dat is een waarschuwing + persistent kenmerk
    (`Administratie.verkoopmodule_afwezig`, gezet in sla_probe_op), geen blokkade. Elke andere route
    én elke andere fout op SalesInvoices blijft hard rood."""
    return bool(rapport) and all(
        v == "ok" or (endpoint == "SalesInvoices" and v == "403") for endpoint, v in rapport.items()
    )


def beschrijf_probe_fouten(rapport: dict[str, str], meldingen: dict[str, str] | None = None) -> str:
    """Rode regels mét handelingsperspectief (blok A punt 3 01-09; blok C 10-09 verrijkt): per rode route het
    RLZ-recht dat de Beheerder in Reeleezee moet zetten (`leesroutes.rlz_recht_voor`) én, als bekend, het
    letterlijke RLZ-antwoord. De SalesInvoices-403 is geen fout (zie probe_is_groen) en staat hier nooit tussen."""
    meldingen = meldingen or {}
    regels = []
    for endpoint, v in rapport.items():
        if v == "ok" or (endpoint == "SalesInvoices" and v == "403"):
            continue
        recht = leesroutes.rlz_recht_voor(endpoint)
        if v == "403":
            regel = f"{endpoint}=403 (geef de webservice-gebruiker in RLZ leesrecht op {endpoint}"
            regel += f": {recht})" if recht else ")"
        elif v == "401":
            regel = f"{endpoint}=401 (Reeleezee weigert de login zelf — controleer gebruikersnaam/wachtwoord)"
        else:
            regel = f"{endpoint}={v}"
        if endpoint in meldingen:
            regel += f' — RLZ zegt: "{meldingen[endpoint]}"'
        regels.append(regel)
    return ", ".join(regels)


def sla_probe_op(
    session,
    *,
    administratie_id: uuid.UUID,
    rapport: dict[str, str],
    actor_id: uuid.UUID,
    meldingen: dict[str, str] | None = None,
    bron: str = "probe",
) -> None:
    """Rapport op platform.rlz_rechten_probe (overschrijft; historie in audit) + geaggregeerde audit — sinds 10-09
    mét de letterlijke RLZ-meldingen per rode route en de `bron` (probe met invoer | herprobe met opgeslagen login)
    in het audit-event, zodat een latere 403 in de eerste sync tegen de probe-stand gelegd kan worden.
    Onderhoudt óók het kenmerk `verkoopmodule_afwezig` (01-09): SalesInvoices "403" zet 'm,
    SalesInvoices "ok" (geslaagde herprobe) wist 'm; élke andere uitkomst laat 'm staan (geen
    uitspraak). Wijziging = eigen audit-event oud→nieuw."""
    now = datetime.now(UTC)
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
            "verkoopmodule_afwezig": verkoopmodule_afwezig_in(rapport),
            "rapport": rapport,
            "meldingen": meldingen or {},
            "bron": bron,
        },
    )
    sales_stand = rapport.get("SalesInvoices")
    if sales_stand not in ("ok", "403"):
        return  # geen uitspraak over de facturatiemodule — kenmerk ongemoeid
    administratie = session.get(Administratie, administratie_id)
    if administratie is None:
        return
    nieuw = sales_stand == "403"
    if administratie.verkoopmodule_afwezig == nieuw:
        return
    oud = administratie.verkoopmodule_afwezig
    administratie.verkoopmodule_afwezig = nieuw
    record_audit_event(
        session,
        actor_id=actor_id,
        module="platform",
        tabel="administratie",
        record_id=administratie_id,
        actie="verkoopmodule_afwezig_gewijzigd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"verkoopmodule_afwezig": oud},
        nieuwe_waarde={"verkoopmodule_afwezig": nieuw, "bron": "rechten_probe"},
    )


def voer_herprobe_met_opgeslagen_login(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, client: RlzClient | None = None
) -> ProbeUitkomst:
    """Read-only rechtenrapport met de OPGESLAGEN login (koppel-flow + `POST /administraties/{id}/rlz-check`):
    `open_root_client(rlz_admin_id)` loopt door dezelfde credential-resolutie als de sync-motoren
    (`resolve_credentials`: store-first op rlz_admin_id, KMS-unwrap), dus de uitkomst zegt wat de EERSTE SYNC gaat
    zien — niet wat de wizard-invoer zag. `Administrations` via de root-client, de rest gescoped. Rapport + letterlijke
    RLZ-meldingen worden opgeslagen (`sla_probe_op`, bron 'herprobe_opgeslagen_login')."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise CredentialStoreFout(f"Onbekende administratie: {administratie_id}")
        rlz_admin_id = administratie.rlz_admin_id

    eigen_client = client is None
    if client is None:
        client = open_root_client(rlz_admin_id)
    try:
        uitkomst = voer_probe_uit(client, rlz_admin_id)
    finally:
        if eigen_client:
            client.close()

    with scoped_session(None, actor_id=actor_id) as session:
        sla_probe_op(
            session,
            administratie_id=administratie_id,
            rapport=uitkomst.rapport,
            actor_id=actor_id,
            meldingen=uitkomst.meldingen,
            bron="herprobe_opgeslagen_login",
        )
    return uitkomst


def voer_rechten_probe_uit(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, client: RlzClient | None = None
) -> dict[str, str]:
    """Compat-vorm van `voer_herprobe_met_opgeslagen_login`: alleen het kale rapport."""
    uitkomst = voer_herprobe_met_opgeslagen_login(administratie_id=administratie_id, actor_id=actor_id, client=client)
    return uitkomst.rapport
