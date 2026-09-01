"""Administratie toevoegen via de UI (feedbackronde 26-08 punt 5, besluit Peter 26-08) — de
onboarding-batch 15-08 als wizard, met hergebruik van de bestaande bouwstenen:

  a. webservice-gegevens → opslag UITSLUITEND via de credential-store (envelope-encryptie,
     KMS-gewrapte data-key; `zet_credential`) — het wachtwoord komt nooit in een response, log of
     audit-payload (besluit 0012), alleen "aanwezig" + username;
  b. verbindings- en rechten-probe (de 10 leesroutes van `credentialstore.service.probe_rapport`)
     verplicht GROEN vóór opslaan — anders duidelijke fout mét handelingsperspectief per route,
     niets half opgeslagen (alles-of-niets in één transactie). Eén uitzondering (01-09, casus
     A.Y. Holding 2 + Abbegaa): SalesInvoices-403 = "facturatiemodule niet afgenomen" — geen
     blokkade maar een waarschuwing + persistent kenmerk `verkoopmodule_afwezig` (gezet in
     `sla_probe_op`), dat alle verkoop-rakende leesroutes uitschakelt; een latere herprobe mét
     SalesInvoices ok wist het kenmerk;
  c. `GET Administrations` met die login → gevonden administraties, Beheerder kiest (naam +
     RLZ-id vooringevuld, nooit handmatig een id typen); admin-pin: alleen id's die de login
     écht ziet;
  d. opslaan met de bestaande defaults (alle toggles/tiers UIT — kolomdefaults) → eerste sync als
     achtergrondrun met status per onderdeel (`eerste_sync`);
  e. de TEST-boeking + storno (actie 19) uit het smoketest-protocol als aparte expliciete knop
     "Schrijftest uitvoeren" — nooit automatisch bij opslaan; TEST-referentie, direct gestorneerd,
     resultaat + audit zichtbaar; respecteert "Boeken platformbreed".

Ook "Webservice-gegevens wijzigen" op een bestaande administratie (stappen a-b) — dekt het
credential-herstel-scenario van 15-08. Scope-gedrag ongewijzigd: een nieuwe administratie is
voor niemand zichtbaar tot de Beheerder scopes toekent.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from app.credentialstore import service as credentialstore
from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening, RlzCredential, RlzRechtenProbe
from app.db.session import scoped_session
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, open_root_client
from app.security.envelope import wrap_secret
from app.sync.btw import taxrate_vlaggen
from app.sync.models import TaxRateCache, VendorCache

logger = logging.getLogger(__name__)

_SCHRIJFTEST_NAMESPACE = uuid.UUID("7c1b3c0e-4d2a-4f1e-9b7a-26082026aaaa")


class OnboardingFout(Exception):
    """Zichtbare domeinfout in de wizard (login geweigerd, probe niet groen, al aangesloten, …).
    Bevat NOOIT het wachtwoord."""

    def __init__(self, bericht: str, *, rapporten: dict[str, dict[str, str]] | None = None) -> None:
        super().__init__(bericht)
        self.rapporten = rapporten or {}


@dataclass(frozen=True)
class GevondenAdministratie:
    rlz_admin_id: str
    naam: str
    al_aangesloten: bool


@dataclass(frozen=True)
class AangemaakteAdministratie:
    id: uuid.UUID
    naam: str
    rlz_admin_id: str
    probe: dict[str, str]
    sync_run_id: uuid.UUID | None


@dataclass(frozen=True)
class SchrijftestStap:
    stap: str
    status: str  # ok | fout | overgeslagen
    detail: str | None = None


@dataclass(frozen=True)
class SchrijftestResultaat:
    uitkomst: str  # ok | fout
    referentie: str
    document_id: uuid.UUID
    stappen: list[SchrijftestStap] = field(default_factory=list)


def _nieuwe_root_client(webservice_username: str, wachtwoord: str) -> RlzClient:
    return RlzClient(username=webservice_username, password=wachtwoord)


def _vertaal_verbindingsfout(exc: Exception) -> OnboardingFout:
    if isinstance(exc, RlzApiError):
        if exc.status_code in (401, 403):
            return OnboardingFout(
                f"Reeleezee weigert deze login (HTTP {exc.status_code}) — controleer webservice-gebruiker en wachtwoord"
            )
        return OnboardingFout(f"Reeleezee antwoordt met HTTP {exc.status_code} op GET Administrations")
    if isinstance(exc, httpx.HTTPError):
        return OnboardingFout(f"Reeleezee niet bereikbaar: {type(exc).__name__}")
    return OnboardingFout(f"Verbinding testen mislukt: {type(exc).__name__}")


def _administraties_via(client: RlzClient) -> dict[str, str]:
    """`GET Administrations` via de root-client (zelfde vorm als RlzClient.list_administrations;
    bewust via `.get` zodat elke duck-typed client volstaat) → {rlz_admin_id: naam}."""
    try:
        rijen = client.get("Administrations").get("value", [])
    except Exception as exc:  # noqa: BLE001 — vertaald naar een zichtbare wizard-fout, nooit met het wachtwoord
        raise _vertaal_verbindingsfout(exc) from exc
    return {str(a.get("id")): str(a.get("Name") or a.get("name") or a.get("id")) for a in rijen}


def _aangesloten_ids() -> set[str]:
    with scoped_session(None) as session:
        return set(session.scalars(select(Administratie.rlz_admin_id)))


def test_verbinding(
    *, webservice_username: str, wachtwoord: str, client: RlzClient | None = None
) -> list[GevondenAdministratie]:
    """Stap a+c: login proberen en de zichtbare administraties teruggeven (mét 'al aangesloten')."""
    eigen = client is None
    client = client or _nieuwe_root_client(webservice_username, wachtwoord)
    try:
        gevonden = _administraties_via(client)
    finally:
        if eigen:
            client.close()
    aangesloten = _aangesloten_ids()
    return [
        GevondenAdministratie(rlz_admin_id=rlz_id, naam=naam, al_aangesloten=rlz_id in aangesloten)
        for rlz_id, naam in sorted(gevonden.items(), key=lambda kv: kv[1].lower())
    ]


def maak_administraties_aan(
    *,
    actor_id: uuid.UUID,
    webservice_username: str,
    wachtwoord: str,
    rlz_admin_ids: list[str],
    client: RlzClient | None = None,
    start_sync: bool = True,
) -> list[AangemaakteAdministratie]:
    """Stap b+d: admin-pin → probe per administratie (alles groen of niets opslaan) → in één
    transactie administratie + credential + probe-rapport + audit → eerste-sync-run."""
    if not rlz_admin_ids:
        raise OnboardingFout("Kies minstens één administratie")
    gekozen = list(dict.fromkeys(rlz_admin_ids))
    aangesloten = _aangesloten_ids()
    al = [rlz_id for rlz_id in gekozen if rlz_id in aangesloten]
    if al:
        raise OnboardingFout(f"Al aangesloten: {', '.join(al)} — gebruik 'Webservice-gegevens wijzigen' op die rij")

    eigen = client is None
    client = client or _nieuwe_root_client(webservice_username, wachtwoord)
    try:
        gevonden = _administraties_via(client)
        onbekend = [rlz_id for rlz_id in gekozen if rlz_id not in gevonden]
        if onbekend:
            raise OnboardingFout(
                f"Deze login ziet administratie(s) {', '.join(onbekend)} niet (admin-pin) — niets opgeslagen"
            )
        rapporten = {rlz_id: credentialstore.probe_rapport(client, rlz_id) for rlz_id in gekozen}
    finally:
        if eigen:
            client.close()

    rood = {rlz_id: r for rlz_id, r in rapporten.items() if not credentialstore.probe_is_groen(r)}
    if rood:
        samenvatting = "; ".join(
            f"{gevonden[rlz_id]}: {credentialstore.beschrijf_probe_fouten(r)}" for rlz_id, r in rood.items()
        )
        raise OnboardingFout(f"Rechten-probe niet groen — niets opgeslagen. {samenvatting}", rapporten=rapporten)

    ciphertext, wrapped_data_key = wrap_secret(wachtwoord.encode())
    resultaten: list[AangemaakteAdministratie] = []
    with scoped_session(None, actor_id=actor_id) as session:
        for rlz_id in gekozen:
            administratie_id = uuid.uuid4()
            naam = gevonden[rlz_id]
            # Defaults voor NIEUWE administraties (besluit Peter 29-08, mockup instellingen-administraties-v2):
            # boeken + AI-extractie AAN, alle overige opt-ins UIT; de wizard vermeldt dit. Bestaande rijen
            # blijven zoals ze zijn — alleen een afwijking van de default krijgt in de lijst een chip.
            session.add(
                Administratie(
                    id=administratie_id,
                    naam=naam,
                    rlz_admin_id=rlz_id,
                    boeken_ingeschakeld=True,
                    ai_extractie_ingeschakeld=True,
                )
            )
            session.add(
                RlzCredential(
                    administratie_id=administratie_id,
                    webservice_username=webservice_username,
                    wachtwoord_ciphertext=ciphertext,
                    wrapped_data_key=wrapped_data_key,
                    aangemaakt_door=actor_id,
                )
            )
            session.flush()
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie="administratie_aangemaakt",
                correlatie_id=uuid.uuid4(),
                # Platform-niveau-event (geen administratie-scope in de sessie): record_id ís de
                # administratie; audit_event-RLS laat administratie_id hier leeg.
                nieuwe_waarde={"naam": naam, "rlz_admin_id": rlz_id, "bron": "wizard"},
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="rlz_credential",
                record_id=administratie_id,
                actie="credential_aangemaakt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"webservice_username": webservice_username},
            )
            credentialstore.sla_probe_op(
                session, administratie_id=administratie_id, rapport=rapporten[rlz_id], actor_id=actor_id
            )
            resultaten.append(
                AangemaakteAdministratie(
                    id=administratie_id, naam=naam, rlz_admin_id=rlz_id, probe=rapporten[rlz_id], sync_run_id=None
                )
            )

    if not start_sync:
        return resultaten
    from app.beheer import eerste_sync

    met_run: list[AangemaakteAdministratie] = []
    for r in resultaten:
        run_id: uuid.UUID | None = None
        try:
            run_id = eerste_sync.start_run(administratie_id=r.id, actor_id=actor_id).run_id
        except eerste_sync.EersteSyncStartFout:
            logger.exception("Eerste sync starten mislukt voor %s — zichtbaar op de run", r.id)
        met_run.append(
            AangemaakteAdministratie(
                id=r.id, naam=r.naam, rlz_admin_id=r.rlz_admin_id, probe=r.probe, sync_run_id=run_id
            )
        )
    return met_run


def wijzig_webservice_gegevens(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    webservice_username: str,
    wachtwoord: str,
    client: RlzClient | None = None,
) -> dict[str, str]:
    """Stappen a-b op een bestaande administratie: admin-pin + probe groen met de NIEUWE login,
    dan pas de upsert in de credential-store (bestaande `zet_credential`, audit zonder secret)."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OnboardingFout("Onbekende administratie")
        rlz_admin_id, naam = administratie.rlz_admin_id, administratie.naam

    eigen = client is None
    client = client or _nieuwe_root_client(webservice_username, wachtwoord)
    try:
        gevonden = _administraties_via(client)
        if rlz_admin_id not in gevonden:
            raise OnboardingFout(
                f"Deze login ziet administratie '{naam}' niet in Reeleezee (admin-pin) — niets gewijzigd"
            )
        rapport = credentialstore.probe_rapport(client, rlz_admin_id)
    finally:
        if eigen:
            client.close()
    if not credentialstore.probe_is_groen(rapport):
        rood = credentialstore.beschrijf_probe_fouten(rapport)
        raise OnboardingFout(f"Rechten-probe niet groen ({rood}) — niets gewijzigd", rapporten={rlz_admin_id: rapport})

    credentialstore.zet_credential(
        actor_id=actor_id,
        administratie_id=administratie_id,
        webservice_username=webservice_username,
        wachtwoord=wachtwoord,
    )
    with scoped_session(None, actor_id=actor_id) as session:
        credentialstore.sla_probe_op(session, administratie_id=administratie_id, rapport=rapport, actor_id=actor_id)
    return rapport


def probe_nieuwe_login(
    *, rlz_admin_id: str, naam: str, webservice_username: str, wachtwoord: str, client: RlzClient | None = None
) -> dict[str, str]:
    """Admin-pin + rechten-probe met een NIEUWE login, zonder iets op te slaan (dearchiveren v2 30-08 —
    zelfde poort als `wijzig_webservice_gegevens`). Geeft het groene rapport terug, anders OnboardingFout."""
    eigen = client is None
    client = client or _nieuwe_root_client(webservice_username, wachtwoord)
    try:
        gevonden = _administraties_via(client)
        if rlz_admin_id not in gevonden:
            raise OnboardingFout(
                f"Deze login ziet administratie '{naam}' niet in Reeleezee (admin-pin) — niets gewijzigd"
            )
        rapport = credentialstore.probe_rapport(client, rlz_admin_id)
    finally:
        if eigen:
            client.close()
    if not credentialstore.probe_is_groen(rapport):
        rood = credentialstore.beschrijf_probe_fouten(rapport)
        raise OnboardingFout(f"Rechten-probe niet groen ({rood}) — niets gewijzigd", rapporten={rlz_admin_id: rapport})
    return rapport


def _kies_schrijftest_bouwstenen(administratie_id: uuid.UUID) -> tuple[uuid.UUID, str, uuid.UUID, str, uuid.UUID]:
    """Kostenrekening (AccountType 2, geen totaal, laagste code), eerste crediteur en het
    21%-tarief (RLZ-favoriet, niet verlegd/vrijgesteld/gemengd) uit de sync-caches — dezelfde
    keuzes als scripts/onboarding_smoketest.py, maar de TaxRate niet meer hardcoded."""
    with scoped_session(administratie_id) as session:
        kosten = session.scalars(
            select(Grootboekrekening)
            .where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.soort == 2,
                Grootboekrekening.is_totaalrekening.is_(False),
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
            .order_by(Grootboekrekening.code)
        ).first()
        vendor = session.scalars(
            select(VendorCache)
            .where(VendorCache.administratie_id == administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None))
            .order_by(VendorCache.naam)
        ).first()
        tarieven = list(
            session.scalars(
                select(TaxRateCache).where(
                    TaxRateCache.administratie_id == administratie_id,
                    TaxRateCache.verdwenen_uit_bron_op.is_(None),
                    TaxRateCache.percentage == 0.21,
                )
            )
        )
        if kosten is None:
            raise OnboardingFout("Geen kostenrekening (AccountType 2) in de cache — draai eerst de sync")
        if vendor is None:
            raise OnboardingFout("Geen crediteuren in de cache — draai eerst de sync")
        kandidaten = []
        for t in tarieven:
            verlegd, vrijgesteld = taxrate_vlaggen(t.brondata)
            if verlegd or vrijgesteld or (t.brondata or {}).get("IsMixed"):
                continue
            kandidaten.append(t)
        favorieten = [t for t in kandidaten if (t.brondata or {}).get("IsFavorite")]
        tarief = favorieten[0] if len(favorieten) == 1 else (kandidaten[0] if len(kandidaten) == 1 else None)
        if tarief is None:
            raise OnboardingFout("Geen eenduidig 21%-tarief in de cache — draai eerst de sync")
        return kosten.ledger_id, kosten.code, vendor.id, vendor.naam or "", tarief.id


def voer_schrijftest_uit(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    client: RlzClient | None = None,
    root_client: RlzClient | None = None,
) -> SchrijftestResultaat:
    """Stap e (expliciete knop): TEST-inkoopfactuur (1,00 + 0,21) → boeken (17) → verifiëren →
    storno (19) → verifiëren concept. Nooit verwijderen; elke stap zichtbaar; audit zonder
    secrets. Geweigerd als 'Boeken platformbreed' uit staat (noodstop)."""
    from app.beheer import service as beheer_service

    if not beheer_service.haal_globale_kill_switch_op():
        raise OnboardingFout("Boeken platformbreed staat UIT (noodstop) — schrijftest geweigerd")
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OnboardingFout("Onbekende administratie")
        rlz_admin_id = administratie.rlz_admin_id

    kosten_ledger_id, kosten_code, vendor_id, vendor_naam, taxrate_id = _kies_schrijftest_bouwstenen(administratie_id)
    nu = datetime.now(UTC)
    referentie = f"TEST-ONB-{nu.strftime('%Y%m%d-%H%M%S')}"
    assert len(referentie) <= 30
    document_id = uuid.uuid5(_SCHRIJFTEST_NAMESPACE, f"{rlz_admin_id}/{referentie}")
    stappen: list[SchrijftestStap] = []

    eigen_root = root_client is None
    root_client = root_client or open_root_client(rlz_admin_id)
    eigen_client = client is None
    client = client or client_voor_rlz_admin_id(rlz_admin_id)
    uitkomst = "fout"
    try:
        gezien = _administraties_via(root_client)
        if rlz_admin_id not in gezien:
            stappen.append(SchrijftestStap("admin-pin", "fout", "de opgeslagen login ziet deze administratie niet"))
            raise OnboardingFout("Admin-pin faalde — geen write gedaan")
        stappen.append(SchrijftestStap("admin-pin", "ok", f"login ziet {rlz_admin_id}"))

        if client.find_purchase_invoices_by_reference(vendor_id=vendor_id, reference=referentie):
            stappen.append(SchrijftestStap("duplicaatcheck", "fout", "referentie bestaat al"))
            raise OnboardingFout("TEST-referentie bestaat al in RLZ — geen tweede PUT")
        stappen.append(SchrijftestStap("duplicaatcheck", "ok", referentie))

        client.put_purchase_invoice(
            document_id,
            vendor_id=vendor_id,
            reference=referentie,
            lines=[
                {
                    "Account": {"id": str(kosten_ledger_id)},
                    "TaxRate": {"id": str(taxrate_id)},
                    "NetAmount": 1.00,
                    "TaxAmount": 0.21,
                    "Description": "TEST schrijftest onboarding — wordt direct gestorneerd",
                }
            ],
            Date=date.today().isoformat(),
        )
        stappen.append(SchrijftestStap("put", "ok", f"crediteur '{vendor_naam}', kosten-GB {kosten_code}, € 1,21"))

        status_concept = client.get(f"PurchaseInvoices/{document_id}").get("Status")
        if status_concept != 1:
            stappen.append(SchrijftestStap("verificatie-concept", "fout", f"status {status_concept}"))
            raise OnboardingFout("Document na PUT niet op concept")
        stappen.append(SchrijftestStap("verificatie-concept", "ok", "Status 1"))

        client.book_purchase_invoice(document_id)
        status_geboekt = client.get(f"PurchaseInvoices/{document_id}").get("Status")
        if status_geboekt not in (2, 3):
            stappen.append(SchrijftestStap("boeken (17)", "fout", f"status {status_geboekt}"))
            raise OnboardingFout("Boeken niet geverifieerd")
        stappen.append(SchrijftestStap("boeken (17)", "ok", f"Status {status_geboekt}"))

        client.correct_purchase_invoice(document_id)
        status_storno = client.get(f"PurchaseInvoices/{document_id}").get("Status")
        if status_storno != 1:
            stappen.append(SchrijftestStap("storno (19)", "fout", f"status {status_storno}"))
            raise OnboardingFout("Storno niet geverifieerd — document staat mogelijk nog geboekt")
        stappen.append(SchrijftestStap("storno (19)", "ok", "terug naar concept (Status 1)"))
        uitkomst = "ok"
    except OnboardingFout:
        pass
    except RlzApiError as exc:
        stappen.append(SchrijftestStap("rlz", "fout", f"HTTP {exc.status_code}"))
    finally:
        if eigen_client:
            client.close()
        if eigen_root:
            root_client.close()
        with scoped_session(None, actor_id=actor_id) as session:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie="schrijftest_uitgevoerd",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "uitkomst": uitkomst,
                    "referentie": referentie,
                    "document_id": str(document_id),
                    "stappen": [{"stap": s.stap, "status": s.status, "detail": s.detail} for s in stappen],
                },
            )
    return SchrijftestResultaat(uitkomst=uitkomst, referentie=referentie, document_id=document_id, stappen=stappen)


def koppelstand(administratie_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str | None, bool | None]]:
    """Per administratie (webservice_username of None, probe groen of None) voor de lijst."""
    with scoped_session(None) as session:
        creds = dict(
            session.execute(
                select(RlzCredential.administratie_id, RlzCredential.webservice_username).where(
                    RlzCredential.administratie_id.in_(administratie_ids)
                )
            ).all()
        )
        probes = dict(
            session.execute(
                select(RlzRechtenProbe.administratie_id, RlzRechtenProbe.rapport).where(
                    RlzRechtenProbe.administratie_id.in_(administratie_ids)
                )
            ).all()
        )
    return {
        aid: (creds.get(aid), credentialstore.probe_is_groen(probes[aid]) if aid in probes else None)
        for aid in administratie_ids
    }
