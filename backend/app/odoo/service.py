"""Odoo-koppeling beheren (blok 0/E): "Odoo-administratie toevoegen" en "Odoo-gegevens wijzigen" —
Beheerder-only, spiegel van de RLZ-wizard (app/beheer/onboarding.py):

  a. URL + API-key → verbinding testen → de companies die de sleutel ziet (keuzelijst, nooit een id typen);
  b. per gekozen company de rechten-/verbindingsprobe (app/odoo/probe.py) VERPLICHT groen vóór opslaan —
     anders 422 mét rapport, niets opgeslagen;
  c. in één transactie: administratie (backend 'odoo', sentinel-rlz_admin_id, defaults boeken + AI AAN) +
     koppeling (envelope-versleutelde key, company, dagboeken, plan) + audit (nooit de key);
  d. eerste stamgegevens-sync direct (klein: honderden rijen, ~10 calls) mét een zichtbare
     `administratie_sync_run`-rij zodat de bestaande sync-chip/-stand in de UI 'm toont.
De API-key wordt nooit gelogd/geretourneerd; alleen "aanwezig" + de gebruikersnaam/label."""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.beheer.models import AdministratieSyncRun, AdministratieSyncRunStatus
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.odoo import sync as odoo_sync
from app.odoo.client import OdooClient, OdooFout
from app.odoo.credentials import odoo_client_voor
from app.odoo.fouten import vertaal_verbindingsfout
from app.odoo.hervertaling import hervertaal_open_boekvoorstellen
from app.odoo.ids import normaliseer_odoo_url, odoo_admin_sentinel, odoo_host
from app.odoo.models import OdooKoppeling
from app.odoo.probe import ProbeUitkomst, is_ok, lees_companies, voer_leesprobe_uit, voer_probe_uit
from app.security.envelope import wrap_secret

if TYPE_CHECKING:  # app/odoo/mapping.py importeert deze module (OdooKoppelFout) — runtime lokaal importeren
    from app.odoo.mapping import MappingInvoer

logger = logging.getLogger(__name__)


class OdooKoppelFout(Exception):
    """Zichtbare domeinfout in de Odoo-wizard (verbinding, probe niet groen, …) → 422."""

    def __init__(self, bericht: str, *, rapport: dict[str, str] | None = None) -> None:
        super().__init__(bericht)
        self.rapport = rapport or {}


class OdooKoppelConflict(OdooKoppelFout):
    """Failsafe dubbele Odoo-koppeling, laag 2 (besluit Peter 14-09): de company is al gekoppeld aan óf gereserveerd
    als migratiedoel voor een andere administratie → 409 mét leesbare reden; de weigering staat in het audit-log.
    De unieke index (laag 1, migratie 0140) is het vangnet, deze 409 de normale weg."""


class RlzSignaalZonderBevestiging(OdooKoppelFout):
    """Failsafe laag 3: de company-naam komt overeen met een bestaande Reeleezee-administratie en de Beheerder heeft
    niet expliciet "toch als nieuwe administratie aanmaken" mét reden bevestigd → 422 (mens wint, nooit stil)."""


@dataclass(frozen=True)
class CompanyClaim:
    """Wie een (host, company) al bezet: de administratie mét naam en de aard van de koppeling."""

    administratie_id: uuid.UUID
    administratie_naam: str
    company_naam: str | None
    migratie_doel: bool
    alleen_lezen: bool
    gearchiveerd: bool
    #: True als de claim alleen via het sentinel-`rlz_admin_id` bestaat (gearchiveerd/halve stand zonder koppeling-rij).
    alleen_sentinel: bool = False

    def reden(self, company_id: int) -> str:
        wie = f"company {company_id}" + (f" ({self.company_naam})" if self.company_naam else "")
        naam = self.administratie_naam + (" — gearchiveerd" if self.gearchiveerd else "")
        if self.migratie_doel:
            return f"{wie} is gereserveerd als migratiedoel voor administratie ‹{naam}›"
        vorm = " (alleen-lezen leesbron)" if self.alleen_lezen else ""
        hint = " — dearchiveer die administratie of wijzig háár koppeling" if self.gearchiveerd else ""
        return f"{wie} is al gekoppeld aan administratie ‹{naam}›{vorm}{hint}"

    def wizard_label(self) -> str:
        """Korte grijs-reden voor de wizard-rij (punt 2c)."""
        if self.migratie_doel:
            return f"migratiedoel ({self.administratie_naam})"
        return f"al gekoppeld ({self.administratie_naam})"


@dataclass(frozen=True)
class GevondenCompany:
    company_id: int
    naam: str
    al_gekoppeld: bool
    #: Punt 2c (14-09): waarom de rij grijs is ("al gekoppeld (‹administratie›)" / "migratiedoel (‹administratie›)").
    gekoppeld_aan: str | None = None
    migratie_doel: bool = False
    #: Signaal (geen blokkade): de company-naam matcht een bestaande Reeleezee-administratie in de module — de wizard
    #: eist dan een expliciete vink "toch als nieuwe administratie aanmaken" mét reden.
    rlz_administratie: str | None = None


@dataclass(frozen=True)
class VerbindingUitkomst:
    """Stap a: de genormaliseerde URL (punt 4 — de wizard toont 'm vóór het testen) + de companies mét redenen."""

    odoo_url: str
    companies: list[GevondenCompany]


@dataclass(frozen=True)
class GekoppeldeAdministratie:
    id: uuid.UUID
    naam: str
    company_id: int
    probe: dict[str, str]
    sync_run_id: uuid.UUID | None
    sync: dict[str, dict] = field(default_factory=dict)
    #: Slotstuk 04-09 (overstap mét projectmapping "aanmaken in Odoo"): nieuw aangemaakte analytic accounts +
    #: zichtbaar overgeslagen projecten mét reden (nooit stil).
    projecten_aangemaakt: int = 0
    projecten_overgeslagen: list[str] = field(default_factory=list)
    #: Slotstuk 04-09 blok C1: open boekvoorstellen mét RLZ-rekeningen zijn bij de overstap via de mapping hervertaald
    #: (`app/odoo/hervertaling.py`) — tellingen voor het wizard-resultaat; None bij een gewone koppeling (ingang A).
    hervertaling: dict[str, object] | None = None


def _client(url: str, api_key: str, company_id: int, *, timeout: float | None = None) -> OdooClient:
    try:
        if timeout is not None:
            return OdooClient(url=url, api_key=api_key, company_id=company_id, timeout=timeout)
        return OdooClient(url=url, api_key=api_key, company_id=company_id)
    except ValueError as exc:
        raise OdooKoppelFout(str(exc)) from exc


def _normaliseer_url(odoo_url: str) -> str:
    """Punt 4 (14-09): élke ingang normaliseert de URL naar scheme + host vóór er iets mee gebeurt; onleesbaar =
    OdooKoppelFout (422) zonder HTTP-call."""
    try:
        return normaliseer_odoo_url(odoo_url)
    except ValueError as exc:
        raise OdooKoppelFout(str(exc)) from exc


def company_claims(url: str) -> dict[int, CompanyClaim]:
    """Company-id → claim voor deze Odoo-host: via de koppeling-rijen (leesbron, volledig, migratiedoel — alle
    tellen) én via administraties die het sentinel-`rlz_admin_id` (`odoo:<host>:<company>`) dragen zonder
    koppeling-rij (bv. gearchiveerd, of een halve stand). Het sentinel is uniek — zonder deze tweede bron strandde
    een tweede koppeling van dezelfde company op een UniqueViolation (500) i.p.v. een leesbare fout (04-09).
    Host-vergelijking uitsluitend via `odoo_host` (één normalisatie, punt 2a)."""
    host = odoo_host(url)
    prefix = f"odoo:{host}:"
    with scoped_session(None) as session:
        uit: dict[int, CompanyClaim] = {}
        rijen = session.execute(
            select(OdooKoppeling, Administratie).join(Administratie, Administratie.id == OdooKoppeling.administratie_id)
        ).all()
        for koppeling, administratie in rijen:
            if odoo_host(koppeling.odoo_url) != host:
                continue
            uit[int(koppeling.company_id)] = CompanyClaim(
                administratie_id=administratie.id,
                administratie_naam=administratie.naam,
                company_naam=koppeling.company_naam,
                migratie_doel=bool(getattr(koppeling, "migratie_doel", False)),
                alleen_lezen=bool(koppeling.alleen_lezen),
                gearchiveerd=administratie.gearchiveerd_op is not None or not administratie.actief,
            )
        for a in session.scalars(select(Administratie).where(Administratie.rlz_admin_id.like(f"{prefix}%"))):
            rest = (a.rlz_admin_id or "")[len(prefix) :]
            if rest.isdigit() and int(rest) not in uit:
                uit[int(rest)] = CompanyClaim(
                    administratie_id=a.id,
                    administratie_naam=a.naam,
                    company_naam=None,
                    migratie_doel=False,
                    alleen_lezen=False,
                    gearchiveerd=a.gearchiveerd_op is not None or not a.actief,
                    alleen_sentinel=True,
                )
        return uit


def _gekoppelde_companies(url: str) -> dict[int, uuid.UUID]:
    """Compat: company-id → administratie-id (zie `company_claims`)."""
    return {c: claim.administratie_id for c, claim in company_claims(url).items()}


def toets_company_vrij(
    *,
    url: str,
    company_id: int,
    actor_id: uuid.UUID | None,
    uitgezonderd_administratie_id: uuid.UUID | None = None,
    bron: str,
) -> None:
    """Failsafe laag 2: is (host, company) al bezet door een ANDERE administratie, dan `OdooKoppelConflict` (409) mét
    de leesbare reden ("… is al gekoppeld aan administratie ‹naam›" / "… is gereserveerd als migratiedoel voor
    administratie ‹naam›") én een audit-regel op de bezettende administratie. `bron` = welke ingang weigerde
    (koppelen/overstap/leesbron/migratiedoel-cli/…)."""
    claim = company_claims(url).get(int(company_id))
    if claim is None or claim.administratie_id == uitgezonderd_administratie_id:
        return
    reden = claim.reden(int(company_id))
    with scoped_session(None, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id or _systeem_actor(),
            module="platform",
            tabel="odoo_koppeling",
            record_id=claim.administratie_id,
            actie="odoo_koppeling_dubbel_geweigerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "odoo_host": odoo_host(url),
                "company_id": int(company_id),
                "company_naam": claim.company_naam,
                "bezet_door_administratie_id": str(claim.administratie_id),
                "bezet_door_administratie": claim.administratie_naam,
                "migratie_doel": claim.migratie_doel,
                "alleen_lezen": claim.alleen_lezen,
                "bron": bron,
                "reden": reden,
            },
        )
    raise OdooKoppelConflict(reden)


def _systeem_actor() -> uuid.UUID:
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    return SYSTEEM_ACTOR_ID


#: Rechtsvorm-tokens die bij de naamvergelijking company ↔ Reeleezee-administratie niet meetellen.
_RECHTSVORM_TOKENS = frozenset({"bv", "nv", "vof", "cv", "bvba", "gmbh", "ltd", "holding", "beheer", "groep"})
_NIET_ALFANUM = re.compile(r"[^a-z0-9 ]+")


def normaliseer_administratienaam(naam: str) -> str:
    """Kleine letters, geen leestekens/rechtsvormen ("Vastgoedgroep Nederland B.V." → "vastgoedgroepnederland";
    'Caravanpark "De Visotter"' → "caravanparkdevisotter")."""
    kaal = _NIET_ALFANUM.sub(" ", naam.lower().replace(".", ""))
    tokens = [t for t in kaal.split() if t not in _RECHTSVORM_TOKENS]
    return "".join(tokens)


def rlz_administratie_signalen(company_namen: dict[int, str]) -> dict[int, str]:
    """Punt 2c: company-id → naam van een bestaande, actieve REELEEZEE-administratie waarvan de genormaliseerde naam
    gelijk is aan de company-naam óf erin voorkomt (min. 6 tekens, anders te veel toeval). Signaal, geen blokkade —
    de wizard eist een expliciete bevestiging mét reden."""
    with scoped_session(None) as session:
        rlz = [
            (a.naam, normaliseer_administratienaam(a.naam))
            for a in session.scalars(
                select(Administratie).where(
                    Administratie.boekhoud_backend == "rlz",
                    Administratie.gearchiveerd_op.is_(None),
                    Administratie.actief.is_(True),
                )
            )
        ]
    uit: dict[int, str] = {}
    for company_id, company_naam in company_namen.items():
        genorm = normaliseer_administratienaam(company_naam)
        if len(genorm) < 6:
            continue
        for naam, n in rlz:
            if len(n) < 6:
                continue
            if n == genorm or n in genorm or genorm in n:
                uit[int(company_id)] = naam
                break
    return uit


def test_verbinding(*, odoo_url: str, api_key: str) -> VerbindingUitkomst:
    """Stap a: URL normaliseren, de companies die deze sleutel ziet mét de grijs-reden (al gekoppeld / migratiedoel)
    en het Reeleezee-signaal. Niets opgeslagen. Fouten leesbaar: status + pad + één zin, nooit een exception-naam."""
    url = _normaliseer_url(odoo_url)
    with _client(url, api_key, 1) as client:
        try:
            client.versie()
            companies = lees_companies(client)
        except OdooFout as exc:
            raise OdooKoppelFout(f"Odoo antwoordt met een fout: {vertaal_verbindingsfout(exc)}") from exc
        except OdooKoppelFout:
            raise
        except Exception as exc:  # noqa: BLE001 — leesbaar, nooit met de key
            raise OdooKoppelFout(f"Odoo niet bereikbaar: {vertaal_verbindingsfout(exc)}") from exc
    claims = company_claims(url)
    signalen = rlz_administratie_signalen({c["id"]: c["naam"] for c in companies})
    gevonden: list[GevondenCompany] = []
    for c in companies:
        claim = claims.get(c["id"])
        gevonden.append(
            GevondenCompany(
                company_id=c["id"],
                naam=c["naam"],
                al_gekoppeld=claim is not None,
                gekoppeld_aan=claim.wizard_label() if claim else None,
                migratie_doel=bool(claim and claim.migratie_doel),
                rlz_administratie=None if claim else signalen.get(c["id"]),
            )
        )
    return VerbindingUitkomst(odoo_url=url, companies=gevonden)


def probe_voor(*, odoo_url: str, api_key: str, company_id: int, timeout_s: float | None = None) -> ProbeUitkomst:
    with _client(odoo_url, api_key, company_id, timeout=timeout_s) as client:
        return voer_probe_uit(client, timeout_s=timeout_s)


def probe_company(*, odoo_url: str, api_key: str, company_id: int) -> ProbeUitkomst:
    """Punt 3 (14-09): de rechten-probe van ÉÉN company als eigen request (wizard stap 3, sequentieel per rij) mét het
    tijdbudget `settings.odoo_probe_timeout_seconds` — time-out = zichtbaar onderbroken rapport, nooit een 5xx die de
    UI als "backend niet bereikbaar" toont. Niets opgeslagen."""
    url = _normaliseer_url(odoo_url)
    start = time.monotonic()
    p = probe_voor(
        odoo_url=url, api_key=api_key, company_id=int(company_id), timeout_s=settings.odoo_probe_timeout_seconds
    )
    logger.info(
        "Odoo-probe company %s op %s: %s in %.1f s (budget %.0f s)",
        int(company_id),
        odoo_host(url),
        "onderbroken" if p.onderbroken else ("groen" if p.groen else "rood"),
        time.monotonic() - start,
        settings.odoo_probe_timeout_seconds,
    )
    return p


def _schrijf_sync_run(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, resultaat, fout: str | None) -> uuid.UUID:
    """Eén afgeronde run-rij in het bestaande eerste-sync-model (wizard-nazorg 27-08) zodat de sync-chip
    en de detailpagina de Odoo-stamgegevenssync tonen als elke andere eerste sync."""
    nu = datetime.now(UTC)
    onderdelen: dict[str, dict] = {}
    if resultaat is not None:
        for naam, telling in (
            ("ledgers", resultaat.ledgers),
            ("taxrates", resultaat.taxrates),
            ("vendors", resultaat.vendors),
            ("projects", resultaat.projects),
        ):
            onderdelen[naam] = {"status": "ok", **odoo_sync.sync_telling_als_dict(telling)}
    else:
        for naam in ("ledgers", "taxrates", "vendors", "projects"):
            onderdelen[naam] = {"status": "fout", "fout": fout}
    run = AdministratieSyncRun(
        administratie_id=administratie_id,
        status=AdministratieSyncRunStatus.KLAAR.value if fout is None else AdministratieSyncRunStatus.FOUT.value,
        aangevraagd_door=actor_id,
        gestart_op=nu,
        laatst_actief_op=nu,
        beeindigd_op=nu,
        onderdelen=onderdelen,
        fout_reden=fout,
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.add(run)
        session.flush()
        return run.id


def eerste_sync(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> tuple[uuid.UUID, dict[str, dict]]:
    fout: str | None = None
    resultaat = None
    try:
        resultaat = odoo_sync.sync_alles_voor_odoo_administratie(administratie_id=administratie_id, actor_id=actor_id)
    except Exception as exc:  # noqa: BLE001 — zichtbaar op de run, nooit een halve wizard
        logger.exception("Odoo-stamgegevenssync mislukt voor %s", administratie_id)
        fout = f"{type(exc).__name__}: {exc}"
    run_id = _schrijf_sync_run(administratie_id=administratie_id, actor_id=actor_id, resultaat=resultaat, fout=fout)
    with scoped_session(administratie_id) as session:
        run = session.get(AdministratieSyncRun, run_id)
        return run_id, dict(run.onderdelen or {})


def koppel_administraties(
    *,
    actor_id: uuid.UUID,
    odoo_url: str,
    api_key: str,
    api_gebruiker: str | None,
    company_ids: list[int],
    start_sync: bool = True,
    namen: dict[int, str] | None = None,
    rlz_signaal_bevestigd: dict[int, str] | None = None,
) -> list[GekoppeldeAdministratie]:
    """Stap b+c(+d): failsafe (409 zodra een company al bezet is; Reeleezee-signaal vereist een bevestiging mét reden)
    → probe per company (alles groen of niets opslaan) → administratie + koppeling + audit in één transactie →
    eerste sync mét zichtbare run. `rlz_signaal_bevestigd` = company-id → reden van de Beheerder ("toch als nieuwe
    administratie aanmaken"); de match wordt server-side opnieuw bepaald, nooit uit de client vertrouwd."""
    if not company_ids:
        raise OdooKoppelFout("Kies minstens één company")
    odoo_url = _normaliseer_url(odoo_url)
    gekozen = list(dict.fromkeys(int(c) for c in company_ids))
    for c in gekozen:
        toets_company_vrij(url=odoo_url, company_id=c, actor_id=actor_id, bron="koppelen")
    probes = {c: probe_voor(odoo_url=odoo_url, api_key=api_key, company_id=c) for c in gekozen}
    signalen = rlz_administratie_signalen({c: (p.company_naam or "") for c, p in probes.items()})
    bevestigd = {int(k): v.strip() for k, v in (rlz_signaal_bevestigd or {}).items() if v and v.strip()}
    zonder = [c for c in signalen if c not in bevestigd]
    if zonder:
        regels = "; ".join(
            f"company {c} ({probes[c].company_naam or '?'}) bestaat al als Reeleezee-administratie ‹{signalen[c]}›"
            for c in zonder
        )
        raise RlzSignaalZonderBevestiging(
            f"{regels} — voor een overstap gebruik 'Odoo koppelen…' op de detailpagina van die administratie, of "
            "bevestig expliciet 'toch als nieuwe administratie aanmaken' mét reden"
        )
    rood = {c: p for c, p in probes.items() if not p.groen}
    if rood:
        samenvatting = "; ".join(f"company {c} ({p.company_naam or '?'}): {p.rode_regels()}" for c, p in rood.items())
        raise OdooKoppelFout(
            f"Rechten-probe niet groen — niets opgeslagen. {samenvatting}",
            rapport={f"company {c}": p.rode_regels() for c, p in rood.items()},
        )

    ciphertext, wrapped = wrap_secret(api_key.encode())
    resultaten: list[GekoppeldeAdministratie] = []
    with scoped_session(None, actor_id=actor_id) as session:
        for c in gekozen:
            p = probes[c]
            administratie_id = uuid.uuid4()
            # Naam = de Odoo-companynaam, tenzij de Beheerder er een eigen geeft (bv. naast een nog lopende
            # RLZ-administratie van dezelfde BV tijdens de overgang: "… (Odoo)").
            naam = (namen or {}).get(c) or p.company_naam or f"Odoo company {c}"
            session.add(
                Administratie(
                    id=administratie_id,
                    naam=naam,
                    rlz_admin_id=odoo_admin_sentinel(odoo_url, c),
                    boekhoud_backend="odoo",
                    boeken_ingeschakeld=True,
                    ai_extractie_ingeschakeld=True,
                )
            )
            session.add(
                OdooKoppeling(
                    administratie_id=administratie_id,
                    odoo_url=odoo_url,
                    company_id=c,
                    company_naam=p.company_naam,
                    api_gebruiker=api_gebruiker,
                    api_key_ciphertext=ciphertext,
                    wrapped_data_key=wrapped,
                    api_key_verloopt_op=p.api_key_verloopt_op,
                    journal_purchase_id=p.journal_purchase_id,
                    journal_general_id=p.journal_general_id,
                    journal_sale_id=p.journal_sale_id,
                    analytic_plan_id=p.analytic_plan_id,
                    probe_rapport=p.rapport,
                    probe_op=datetime.now(UTC),
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
                nieuwe_waarde={"naam": naam, "boekhoud_backend": "odoo", "odoo_company_id": c, "bron": "odoo-wizard"},
            )
            if c in signalen:
                # Laag 3: de Beheerder overrulede het Reeleezee-signaal bewust — mens wint, maar nooit stil.
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="platform",
                    tabel="administratie",
                    record_id=administratie_id,
                    actie="odoo_koppeling_rlz_signaal_overruled",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "odoo_company_id": c,
                        "company_naam": p.company_naam,
                        "bestaande_rlz_administratie": signalen[c],
                        "reden": bevestigd[c],
                    },
                )
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="odoo_koppeling",
                record_id=administratie_id,
                actie="odoo_koppeling_aangemaakt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "odoo_url": odoo_url,
                    "company_id": c,
                    "api_gebruiker": api_gebruiker,
                    "probe_groen": True,
                    "journal_purchase_id": p.journal_purchase_id,
                    "journal_general_id": p.journal_general_id,
                    "analytic_plan_id": p.analytic_plan_id,
                    "versie": p.versie,
                },
            )
            resultaten.append(
                GekoppeldeAdministratie(id=administratie_id, naam=naam, company_id=c, probe=p.rapport, sync_run_id=None)
            )

    if not start_sync:
        return resultaten
    met_sync: list[GekoppeldeAdministratie] = []
    for r in resultaten:
        run_id, onderdelen = eerste_sync(administratie_id=r.id, actor_id=actor_id)
        met_sync.append(
            GekoppeldeAdministratie(
                id=r.id, naam=r.naam, company_id=r.company_id, probe=r.probe, sync_run_id=run_id, sync=onderdelen
            )
        )
    return met_sync


def wijzig_koppeling(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    odoo_url: str | None,
    api_key: str | None,
    api_gebruiker: str | None,
) -> ProbeUitkomst:
    """'Odoo-gegevens wijzigen' (sleutelrotatie!): probe met de nieuwe gegevens moet groen zijn, dan pas
    opslaan (URL/key/label; company blijft — een company-wissel is een nieuwe koppeling)."""
    with scoped_session(None) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None:
            raise OdooKoppelFout("Deze administratie heeft geen Odoo-koppeling")
        company_id = rij.company_id
        huidige_url = rij.odoo_url
    url = _normaliseer_url(odoo_url or huidige_url)
    if odoo_host(url) != odoo_host(huidige_url):
        toets_company_vrij(
            url=url,
            company_id=company_id,
            actor_id=actor_id,
            uitgezonderd_administratie_id=administratie_id,
            bron="wijzigen",
        )
    if api_key:
        p = probe_voor(odoo_url=url, api_key=api_key, company_id=company_id)
    else:
        with odoo_client_voor(administratie_id) as client:
            p = voer_probe_uit(client)
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        assert rij is not None
        oud = {"odoo_url": rij.odoo_url, "api_gebruiker": rij.api_gebruiker, "probe_groen": _groen(rij.probe_rapport)}
        if p.groen:
            rij.odoo_url = url
            if api_key:
                rij.api_key_ciphertext, rij.wrapped_data_key = wrap_secret(api_key.encode())
                rij.api_key_verloopt_op = p.api_key_verloopt_op
            if api_gebruiker is not None:
                rij.api_gebruiker = api_gebruiker
            rij.company_naam = p.company_naam or rij.company_naam
            rij.journal_purchase_id = p.journal_purchase_id
            rij.journal_general_id = p.journal_general_id
            rij.journal_sale_id = p.journal_sale_id
            rij.analytic_plan_id = p.analytic_plan_id
        rij.probe_rapport = p.rapport
        rij.probe_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="odoo_koppeling",
            record_id=administratie_id,
            actie="odoo_koppeling_gewijzigd" if p.groen else "odoo_probe_uitgevoerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "odoo_url": url,
                "api_gebruiker": api_gebruiker,
                "api_key_gewijzigd": bool(api_key) and p.groen,
                "probe_groen": p.groen,
            },
        )
    if not p.groen:
        raise OdooKoppelFout(f"Rechten-probe niet groen — niets gewijzigd. {p.rode_regels()}", rapport=p.rapport)
    return p


def _groen(rapport: dict | None) -> bool | None:
    if not rapport:
        return None
    from app.odoo.probe import INFORMATIEF, SLEUTEL_ONDERBROKEN

    if SLEUTEL_ONDERBROKEN in rapport:
        return False
    return all(is_ok(v) for k, v in rapport.items() if k not in INFORMATIEF)


@dataclass(frozen=True)
class OdooStand:
    company_id: int
    company_naam: str | None
    odoo_url: str
    api_gebruiker: str | None
    api_key_verloopt_op: str | None
    probe_groen: bool | None
    probe_op: datetime | None
    #: Blok D: alleen-lezen-koppeling (Odoo = leesbron, boeken blijft in RLZ) + voorraad-knip.
    alleen_lezen: bool = False
    voorraad_knip_datum: date | None = None
    #: Blok E (UI): het volledige probe-rapport (regel per onderdeel), de actuele stamgegevens-tellers
    #: ({"ledgers", "taxrates", "vendors", "projects"} — niet-verdwenen cache-rijen van déze administratie) en de
    #: jongste sync-tijd (zelfde bron als `laatste_sync_op` op de administraties-lijst). None = niet opgevraagd
    #: (`koppelstand(..., met_details=False)` voor lijsten) of geen koppeling.
    probe_rapport: dict[str, str] | None = None
    stamgegevens: dict[str, int] | None = None
    laatste_sync_op: datetime | None = None
    #: Blok E (migratie 0104), herzien slotstuk 04-09: de KANTELDATUM van een overstap (vanaf wanneer de
    #: administratie Odoo is; géén poort op documenten — nakomers boeken óók in Odoo, dedup filtert); het oude
    #: RLZ-administratie-id blijft herleidbaar.
    overgangsdatum: date | None = None
    rlz_admin_id_voor_overstap: str | None = None


STAMGEGEVENS_ONDERDELEN: tuple[str, ...] = ("ledgers", "taxrates", "vendors", "projects")


def _stamgegevens_tellers(administratie_id: uuid.UUID) -> tuple[dict[str, int], datetime | None]:
    """Actuele (niet-verdwenen) cache-rijen per onderdeel + de jongste sync-tijd — de caches die de Odoo-sync
    vult zijn dezélfde als die van RLZ (`app/odoo/sync.py`); RLS-tabellen, dus gescoopt lezen."""
    from app.beheer.service import _laatste_sync
    from app.db.models import Grootboekrekening
    from app.sync.models import ProjectCache, TaxRateCache, VendorCache

    modellen = {
        "ledgers": Grootboekrekening,
        "taxrates": TaxRateCache,
        "vendors": VendorCache,
        "projects": ProjectCache,
    }
    tellers: dict[str, int] = {}
    with scoped_session(administratie_id) as session:
        for naam in STAMGEGEVENS_ONDERDELEN:
            model = modellen[naam]
            tellers[naam] = int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.administratie_id == administratie_id, model.verdwenen_uit_bron_op.is_(None))
                )
                or 0
            )
        laatste = _laatste_sync(session, administratie_id)
    return tellers, laatste


def koppelstand(administratie_ids: list[uuid.UUID], *, met_details: bool = True) -> dict[uuid.UUID, OdooStand]:
    """Voor de administraties-lijst/detail: de Odoo-stand per administratie (nooit de key). `met_details`
    voegt per koppeling de stamgegevens-tellers + jongste sync-tijd toe (een paar gescoopte tellingen per
    gekoppelde administratie — voor het detailblok; lijsten zetten 'm uit)."""
    if not administratie_ids:
        return {}
    with scoped_session(None) as session:
        rijen = list(
            session.scalars(select(OdooKoppeling).where(OdooKoppeling.administratie_id.in_(administratie_ids)))
        )
        session.expunge_all()
    resultaat: dict[uuid.UUID, OdooStand] = {}
    for r in rijen:
        stamgegevens: dict[str, int] | None = None
        laatste_sync: datetime | None = None
        if met_details:
            stamgegevens, laatste_sync = _stamgegevens_tellers(r.administratie_id)
        resultaat[r.administratie_id] = OdooStand(
            company_id=r.company_id,
            company_naam=r.company_naam,
            odoo_url=r.odoo_url,
            api_gebruiker=r.api_gebruiker,
            api_key_verloopt_op=r.api_key_verloopt_op.isoformat() if r.api_key_verloopt_op else None,
            probe_groen=_groen(r.probe_rapport),
            probe_op=r.probe_op,
            alleen_lezen=bool(r.alleen_lezen),
            voorraad_knip_datum=r.voorraad_knip_datum,
            probe_rapport=dict(r.probe_rapport) if r.probe_rapport else None,
            stamgegevens=stamgegevens,
            laatste_sync_op=laatste_sync,
            overgangsdatum=r.overgangsdatum,
            rlz_admin_id_voor_overstap=r.rlz_admin_id_voor_overstap,
        )
    return resultaat


# --- blok E: overstap van een BESTAANDE RLZ-administratie op Odoo (ingang B, volledige backend) -----------


def toets_overstap_voorwaarden(
    *, administratie_id: uuid.UUID, url: str, company_id: int, actor_id: uuid.UUID | None = None
) -> tuple[str, str]:
    """De voorvalidaties van een overstap (gedeeld door `koppel_overstap` en `mapping.voorbereid_overstap`):
    bestaande, actieve RLZ-administratie zonder Odoo-koppeling; company nog vrij op deze host (anders 409 mét
    audit — failsafe laag 2). Retourneert (naam, oud rlz_admin_id)."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OdooKoppelFout("Onbekende administratie")
        if administratie.gearchiveerd_op is not None or not administratie.actief:
            raise OdooKoppelFout("Deze administratie is gearchiveerd — dearchiveer 'm eerst voordat je overstapt")
        if administratie.boekhoud_backend != "rlz":
            raise OdooKoppelFout(
                f"Deze administratie boekt al in Odoo (backend {administratie.boekhoud_backend}) — een overstap "
                "geldt alleen voor een Reeleezee-administratie"
            )
        bestaand = session.get(OdooKoppeling, administratie_id)
        if bestaand is not None:
            if bestaand.alleen_lezen:
                raise OdooKoppelFout(
                    "Deze administratie heeft al een alleen-lezen Odoo-koppeling (leesbron voorraad-uitstroom) — "
                    "een overstap naar Odoo als boekhoud-backend is dan niet mogelijk; laat de Beheerder de "
                    "leesbron-koppeling eerst beoordelen"
                )
            raise OdooKoppelFout("Deze administratie heeft al een Odoo-koppeling — gebruik 'Odoo-gegevens wijzigen'")
        naam = administratie.naam
        oud_rlz_admin_id = administratie.rlz_admin_id
    toets_company_vrij(url=url, company_id=int(company_id), actor_id=actor_id, bron="overstap")
    return naam, oud_rlz_admin_id


def koppel_overstap(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    odoo_url: str,
    api_key: str,
    company_id: int,
    overgangsdatum: date,
    api_gebruiker: str | None = None,
    start_sync: bool = True,
    mapping: MappingInvoer | None = None,
) -> GekoppeldeAdministratie:
    """Een bestaande RLZ-administratie stapt over op Odoo (het Universal-migratiescenario, mockup ingang B):
    volledige probe verplicht groen (anders 422 mét rapport, niets opgeslagen), dan in ÉÉN transactie
    `boekhoud_backend = 'odoo'`, `rlz_admin_id` → sentinel (dáárdoor slaan álle RLZ-jobs de administratie
    zichtbaar over — anders zouden RLZ- en Odoo-sync dezelfde caches over elkaar schrijven), het oude RLZ-id
    bewaard op de koppeling, koppeling-rij (envelope-key, dagboeken/plan uit de probe, overgangsdatum =
    KANTELDATUM: vanaf wanneer de administratie Odoo is, géén poort op documenten) + audit (nooit de key). De
    RLZ-credential-rij blijft staan (via het sentinel onbereikbaar); bestaande documenten/boekvoorstellen
    blijven onaangeroerd. Daarna de eerste stamgegevens-sync zoals bij koppelen.

    Blok A (04-09): `mapping` = de door de mens bevestigde rekening-mapping RLZ → Odoo (grootboek + btw) voor
    álle in-gebruik-rijen van het boekingsgeheugen en de open boekvoorstellen — gevalideerd tegen de live
    Odoo-lijsten en ín dezelfde transactie geschreven (versie 1). Een lege administratie (niets in gebruik)
    mag met een lege mapping overstappen; anders is de mapping VERPLICHT (422 "onvolledig").

    Slotstuk 04-09: `mapping.project` = de OPTIONELE projectmapping (RLZ-project → analytic account); een rij
    mét `aanmaken=True` wordt ná de probe en VÓÓR de DB-transactie in Odoo opgezocht/aangemaakt
    (`mapping.maak_odoo_projecten_aan`, lookup-vóór-create, mislukt = zichtbaar overgeslagen, nooit unlink);
    gevonden/aangemaakte accounts krijgen in de hoofdtransactie een id-koppeling + project-cache-rij."""
    from app.odoo import mapping as odoo_mapping  # lokaal: mapping importeert OdooKoppelFout uit deze module

    url = _normaliseer_url(odoo_url)
    naam, oud_rlz_admin_id = toets_overstap_voorwaarden(
        administratie_id=administratie_id, url=url, company_id=int(company_id), actor_id=actor_id
    )

    p = probe_voor(odoo_url=url, api_key=api_key, company_id=int(company_id))
    if not p.groen:
        raise OdooKoppelFout(
            f"Rechten-probe niet groen — niets opgeslagen. company {company_id} ({p.company_naam or '?'}): "
            f"{p.rode_regels()}",
            rapport=p.rapport,
        )

    # Blok A (04-09): de mens heeft de rekening-mapping RLZ → Odoo bevestigd. Live opnieuw lezen (de wizard-
    # stap "voorbereiden" was een eerdere request) en valideren VÓÓR er iets geschreven wordt: élke in-gebruik-
    # rij moet een bestaande Odoo-tegenhanger hebben, anders 422 en niets opgeslagen.
    odoo_gb, odoo_btw, odoo_projecten = odoo_mapping.live_odoo_lijsten(
        odoo_url=url, api_key=api_key, company_id=int(company_id), analytic_plan_id=p.analytic_plan_id
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rlz_gb, rlz_btw, rlz_projecten = odoo_mapping.rlz_in_gebruik(session, administratie_id)
    project_voorstel = odoo_mapping.bepaal_project_voorstel(rlz_projecten, odoo_projecten)
    mapping_rijen = odoo_mapping.valideer_mapping(
        grootboek=odoo_mapping.bepaal_grootboek_voorstel(rlz_gb, odoo_gb),
        btw=odoo_mapping.bepaal_btw_voorstel(rlz_btw, odoo_btw),
        odoo_grootboek=odoo_gb,
        odoo_btw=odoo_btw,
        invoer=mapping,
        project=project_voorstel,
        odoo_projecten=odoo_projecten,
        analytic_plan_id=p.analytic_plan_id,
    )

    # Slotstuk 04-09: "aanmaken in Odoo" — de enige Odoo-write van de overstap, ná de probe en vóór de DB-
    # transactie (lookup-vóór-create; mislukt = zichtbaar overgeslagen, de overstap gaat door).
    aanmaak = odoo_mapping.ProjectAanmaakUitkomst()
    verzoeken = odoo_mapping.project_aanmaak_verzoeken(project_voorstel, mapping)
    if verzoeken:
        assert p.analytic_plan_id is not None  # valideer_mapping weigert aanmaken zonder plan
        with _client(url, api_key, int(company_id)) as client:
            aanmaak = odoo_mapping.maak_odoo_projecten_aan(
                client, verzoeken=verzoeken, analytic_plan_id=p.analytic_plan_id, company_id=int(company_id)
            )
        mapping_rijen = [*mapping_rijen, *aanmaak.rijen]

    ciphertext, wrapped = wrap_secret(api_key.encode())
    sentinel = odoo_admin_sentinel(url, int(company_id))
    # Gescoopt op de administratie: de mapping-tabel is RLS-beveiligd en hoort in DEZELFDE transactie als de
    # koppeling (platform-tabellen kennen geen RLS — de scope is daar onschadelijk).
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        assert administratie is not None
        administratie.boekhoud_backend = "odoo"
        administratie.rlz_admin_id = sentinel
        session.add(
            OdooKoppeling(
                administratie_id=administratie_id,
                odoo_url=url,
                company_id=int(company_id),
                company_naam=p.company_naam,
                api_gebruiker=api_gebruiker,
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                api_key_verloopt_op=p.api_key_verloopt_op,
                journal_purchase_id=p.journal_purchase_id,
                journal_general_id=p.journal_general_id,
                journal_sale_id=p.journal_sale_id,
                analytic_plan_id=p.analytic_plan_id,
                probe_rapport=p.rapport,
                probe_op=datetime.now(UTC),
                overgangsdatum=overgangsdatum,
                rlz_admin_id_voor_overstap=oud_rlz_admin_id,
                aangemaakt_door=actor_id,
            )
        )
        session.flush()
        correlatie = uuid.uuid4()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="odoo_overstap",
            correlatie_id=correlatie,
            oude_waarde={"boekhoud_backend": "rlz", "rlz_admin_id": oud_rlz_admin_id},
            nieuwe_waarde={
                "administratie": naam,
                "boekhoud_backend": "odoo",
                "rlz_admin_id": sentinel,
                "odoo_url": url,
                "odoo_company_id": int(company_id),
                "company_naam": p.company_naam,
                "api_gebruiker": api_gebruiker,
                "overgangsdatum": overgangsdatum.isoformat(),
                "rlz_admin_id_voor_overstap": oud_rlz_admin_id,
                "probe_groen": True,
                "projecten_aangemaakt": aanmaak.aangemaakt,
                "projecten_gevonden": aanmaak.gevonden,
                "projecten_overgeslagen": list(aanmaak.overgeslagen),
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="odoo_koppeling",
            record_id=administratie_id,
            actie="odoo_koppeling_aangemaakt",
            correlatie_id=correlatie,
            nieuwe_waarde={
                "odoo_url": url,
                "company_id": int(company_id),
                "api_gebruiker": api_gebruiker,
                "probe_groen": True,
                "journal_purchase_id": p.journal_purchase_id,
                "journal_general_id": p.journal_general_id,
                "analytic_plan_id": p.analytic_plan_id,
                "versie": p.versie,
                "overgangsdatum": overgangsdatum.isoformat(),
                "bron": "overstap",
            },
        )
        if aanmaak.accounts:
            odoo_mapping.registreer_odoo_projecten(
                session,
                administratie_id=administratie_id,
                company_id=int(company_id),
                accounts=aanmaak.accounts,
                now=datetime.now(UTC),
            )
        odoo_mapping.schrijf_mapping(
            session,
            administratie_id=administratie_id,
            company_id=int(company_id),
            rijen=mapping_rijen,
            actor_id=actor_id,
            versie=1,
        )
        # Blok C1 (slotstuk 04-09, besluit Peter): open boekvoorstellen mét RLZ-grootboek/-btw/-project worden ín
        # dezelfde transactie via de zojuist geschreven mapping hervertaald — chip "vertaald bij overstap" per veld,
        # onvertaalbaar = leeg mét reden (de controleur ziet wat er gebeurd is; audit
        # `odoo_open_voorstellen_hervertaald`).
        hervertaald = hervertaal_open_boekvoorstellen(
            session,
            administratie_id=administratie_id,
            mapping=odoo_mapping.geldende_mapping(session, administratie_id),
            actor_id=actor_id,
        )
    hervertaling = {
        "documenten": hervertaald.documenten,
        "regels": hervertaald.regels,
        "vertaald": dict(hervertaald.vertaald),
        "leeg": dict(hervertaald.leeg),
    }

    resultaat = GekoppeldeAdministratie(
        id=administratie_id,
        naam=naam,
        company_id=int(company_id),
        probe=p.rapport,
        sync_run_id=None,
        projecten_aangemaakt=aanmaak.aangemaakt,
        projecten_overgeslagen=list(aanmaak.overgeslagen),
        hervertaling=hervertaling,
    )
    if not start_sync:
        return resultaat
    run_id, onderdelen = eerste_sync(administratie_id=administratie_id, actor_id=actor_id)
    return GekoppeldeAdministratie(
        id=administratie_id,
        naam=naam,
        company_id=int(company_id),
        probe=p.rapport,
        sync_run_id=run_id,
        sync=onderdelen,
        projecten_aangemaakt=aanmaak.aangemaakt,
        projecten_overgeslagen=list(aanmaak.overgeslagen),
        hervertaling=hervertaling,
    )


def wijzig_overgangsdatum(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, overgangsdatum: date) -> OdooStand:
    """De KANTELDATUM van een SCHRIJVENDE Odoo-koppeling zetten/verschuiven — altijd toegestaan, audit oud→nieuw
    (slotstuk 04-09, besluit Peter "geen blokkade": de C1-409 op al in Odoo geboekte facturen vóór de nieuwe datum
    is vervallen samen met de adapter-poort die 'm beschermde; terugzetten = één toets-functie vóór `oud = …`).
    De datum is informatief (vanaf wanneer de administratie Odoo is) — nakomers boeken óók in Odoo, de
    duplicaat-afhandeling filtert wat al in RLZ stond. Een alleen-lezen-koppeling kent geen overgangsdatum (daar is
    de voorraad-knip het begrip)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None:
            raise OdooKoppelFout("Deze administratie heeft geen Odoo-koppeling")
        if rij.alleen_lezen:
            raise OdooKoppelFout(
                "De overgangsdatum hoort bij een Odoo-administratie (volledige backend), niet bij een alleen-lezen "
                "leesbron-koppeling — daar geldt de voorraad-knip"
            )
        oud = rij.overgangsdatum
        rij.overgangsdatum = overgangsdatum
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="odoo_koppeling",
            record_id=administratie_id,
            actie="odoo_overgangsdatum_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"overgangsdatum": oud.isoformat() if oud else None},
            nieuwe_waarde={"overgangsdatum": overgangsdatum.isoformat()},
        )
    return koppelstand([administratie_id])[administratie_id]


# --- blok D: Odoo als LEESBRON voor een RLZ-administratie ---------------------------------------------


def koppel_leesbron(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    odoo_url: str,
    api_key: str,
    company_id: int,
    voorraad_knip_datum: date | None,
    api_gebruiker: str | None = None,
) -> ProbeUitkomst:
    """Een bestaande RLZ-administratie een ALLEEN-LEZEN Odoo-koppeling geven (casus Universal Verkoop, company 3:
    factureert sinds de knip in Odoo, boekt verder in RLZ). Leesprobe verplicht groen vóór opslaan (422 anders,
    niets opgeslagen); `alleen_lezen=True` is hard — `odoo_client_voor` levert er nooit een schrijvende client
    voor. De knip mag leeg zijn (koppeling zonder voorraadrol) en is later te zetten via `wijzig_leesbron`."""
    url = _normaliseer_url(odoo_url)
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OdooKoppelFout("Onbekende administratie")
        if administratie.boekhoud_backend != "rlz":
            raise OdooKoppelFout(
                "Een alleen-lezen Odoo-koppeling hoort bij een RLZ-administratie — deze administratie boekt al in Odoo"
            )
        if session.get(OdooKoppeling, administratie_id) is not None:
            raise OdooKoppelFout("Deze administratie heeft al een Odoo-koppeling — gebruik 'Odoo-gegevens wijzigen'")
        naam = administratie.naam
    toets_company_vrij(
        url=url,
        company_id=int(company_id),
        actor_id=actor_id,
        uitgezonderd_administratie_id=administratie_id,
        bron="leesbron",
    )
    with _client(url, api_key, int(company_id)) as client:
        p = voer_leesprobe_uit(client)
    if not p.groen:
        raise OdooKoppelFout(f"Leesprobe niet groen — niets opgeslagen. {p.rode_regels()}", rapport=p.rapport)
    ciphertext, wrapped = wrap_secret(api_key.encode())
    with scoped_session(None, actor_id=actor_id) as session:
        session.add(
            OdooKoppeling(
                administratie_id=administratie_id,
                odoo_url=url,
                company_id=int(company_id),
                company_naam=p.company_naam,
                api_gebruiker=api_gebruiker,
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                api_key_verloopt_op=p.api_key_verloopt_op,
                probe_rapport=p.rapport,
                probe_op=datetime.now(UTC),
                alleen_lezen=True,
                voorraad_knip_datum=voorraad_knip_datum,
                aangemaakt_door=actor_id,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="odoo_koppeling",
            record_id=administratie_id,
            actie="odoo_leesbron_gekoppeld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "administratie": naam,
                "odoo_url": url,
                "company_id": int(company_id),
                "company_naam": p.company_naam,
                "api_gebruiker": api_gebruiker,
                "alleen_lezen": True,
                "voorraad_knip_datum": voorraad_knip_datum.isoformat() if voorraad_knip_datum else None,
                "probe_groen": True,
            },
        )
    return p


def wijzig_leesbron(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, voorraad_knip_datum: date | None) -> OdooStand:
    """De voorraad-knip van een alleen-lezen-koppeling zetten/verschuiven/wissen (audit oud→nieuw). De RLZ- en
    Odoo-leesroutes volgen de nieuwe knip bij de volgende run (RLZ ruimt ≥ knip op; Odoo leest vanaf de knip —
    een verschoven knip vergt `voorraad-rlz-sync --volledig` voor het her-lezen van de tussenliggende periode)."""
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None:
            raise OdooKoppelFout("Deze administratie heeft geen Odoo-koppeling")
        if not rij.alleen_lezen:
            raise OdooKoppelFout(
                "De voorraad-knip hoort bij een alleen-lezen Odoo-koppeling (leesbron), niet bij een Odoo-administratie"
            )
        oud = rij.voorraad_knip_datum
        rij.voorraad_knip_datum = voorraad_knip_datum
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="odoo_koppeling",
            record_id=administratie_id,
            actie="odoo_leesbron_knip_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"voorraad_knip_datum": oud.isoformat() if oud else None},
            nieuwe_waarde={"voorraad_knip_datum": voorraad_knip_datum.isoformat() if voorraad_knip_datum else None},
        )
    return koppelstand([administratie_id])[administratie_id]
