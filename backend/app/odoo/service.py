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
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.beheer.models import AdministratieSyncRun, AdministratieSyncRunStatus
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.odoo import sync as odoo_sync
from app.odoo.client import OdooClient, OdooFout
from app.odoo.credentials import odoo_client_voor
from app.odoo.ids import odoo_admin_sentinel
from app.odoo.models import OdooDocumentKoppeling, OdooKoppeling
from app.odoo.probe import ProbeUitkomst, lees_companies, voer_leesprobe_uit, voer_probe_uit
from app.security.envelope import wrap_secret

if TYPE_CHECKING:  # app/odoo/mapping.py importeert deze module (OdooKoppelFout) — runtime lokaal importeren
    from app.odoo.mapping import MappingInvoer

logger = logging.getLogger(__name__)


class OdooKoppelFout(Exception):
    """Zichtbare domeinfout in de Odoo-wizard (verbinding, probe niet groen, company al gekoppeld, …)."""

    def __init__(self, bericht: str, *, rapport: dict[str, str] | None = None) -> None:
        super().__init__(bericht)
        self.rapport = rapport or {}


class OvergangsdatumGeblokkeerd(OdooKoppelFout):
    """C1 (Odoo-afrondingsrun 04-09): de nieuwe overgangsdatum zou al in Odoo geboekte facturen (factuurdatum
    vóór die datum) achter de adapter-poort zetten — de tijdlijn zou dan liegen ("hoort nog in Reeleezee"
    terwijl het boekstuk in Odoo staat). Router: 409 mét het aantal + het oudste boekstuk."""


@dataclass(frozen=True)
class GevondenCompany:
    company_id: int
    naam: str
    al_gekoppeld: bool


@dataclass(frozen=True)
class GekoppeldeAdministratie:
    id: uuid.UUID
    naam: str
    company_id: int
    probe: dict[str, str]
    sync_run_id: uuid.UUID | None
    sync: dict[str, dict] = field(default_factory=dict)


def _client(url: str, api_key: str, company_id: int) -> OdooClient:
    try:
        return OdooClient(url=url, api_key=api_key, company_id=company_id)
    except ValueError as exc:
        raise OdooKoppelFout(str(exc)) from exc


def _gekoppelde_companies(url: str) -> dict[int, uuid.UUID]:
    """Company-id → administratie voor deze Odoo-host: via de koppeling-rijen én via administraties die het
    sentinel-`rlz_admin_id` (`odoo:<host>:<company>`) dragen zonder koppeling-rij (bv. gearchiveerd, of een
    halve stand). Het sentinel is uniek — zonder deze tweede bron strandde een tweede koppeling van dezelfde
    company op een UniqueViolation (500) i.p.v. een leesbare 422 (live keten-cyclus 04-09)."""
    host = url.split("//", 1)[-1].rstrip("/").lower()
    prefix = f"odoo:{host}:"
    with scoped_session(None) as session:
        rijen = session.scalars(select(OdooKoppeling)).all()
        uit = {
            r.company_id: r.administratie_id for r in rijen if r.odoo_url.split("//", 1)[-1].rstrip("/").lower() == host
        }
        for a in session.scalars(select(Administratie).where(Administratie.rlz_admin_id.like(f"{prefix}%"))):
            rest = (a.rlz_admin_id or "")[len(prefix) :]
            if rest.isdigit():
                uit.setdefault(int(rest), a.id)
        return uit


def test_verbinding(*, odoo_url: str, api_key: str) -> list[GevondenCompany]:
    """Stap a: de companies die deze sleutel ziet (mét 'al gekoppeld'). Niets opgeslagen."""
    with _client(odoo_url, api_key, 1) as client:
        try:
            client.versie()
            companies = lees_companies(client)
        except OdooFout as exc:
            if exc.status == 401:
                raise OdooKoppelFout("Odoo weigert deze API-key (HTTP 401) — controleer de sleutel") from exc
            raise OdooKoppelFout(f"Odoo antwoordt met HTTP {exc.status} ({exc.naam or 'fout'})") from exc
        except OdooKoppelFout:
            raise
        except Exception as exc:  # noqa: BLE001 — leesbaar, nooit met de key
            raise OdooKoppelFout(f"Odoo niet bereikbaar: {type(exc).__name__}") from exc
    gekoppeld = _gekoppelde_companies(odoo_url)
    return [GevondenCompany(company_id=c["id"], naam=c["naam"], al_gekoppeld=c["id"] in gekoppeld) for c in companies]


def probe_voor(*, odoo_url: str, api_key: str, company_id: int) -> ProbeUitkomst:
    with _client(odoo_url, api_key, company_id) as client:
        return voer_probe_uit(client)


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
) -> list[GekoppeldeAdministratie]:
    """Stap b+c(+d): probe per company (alles groen of niets opslaan) → administratie + koppeling + audit in
    één transactie → eerste sync mét zichtbare run."""
    if not company_ids:
        raise OdooKoppelFout("Kies minstens één company")
    gekozen = list(dict.fromkeys(int(c) for c in company_ids))
    al = _gekoppelde_companies(odoo_url)
    dubbel = [c for c in gekozen if c in al]
    if dubbel:
        raise OdooKoppelFout(
            f"Company {', '.join(map(str, dubbel))} is al gekoppeld (of een gearchiveerde administratie draagt dit "
            "Odoo-id nog) — gebruik 'Odoo-gegevens wijzigen' op die administratie of dearchiveer haar"
        )
    probes = {c: probe_voor(odoo_url=odoo_url, api_key=api_key, company_id=c) for c in gekozen}
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
                    odoo_url=odoo_url.rstrip("/"),
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
    url = (odoo_url or huidige_url).rstrip("/")
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
    from app.odoo.probe import INFORMATIEF

    return all(v == "ok" for k, v in rapport.items() if k not in INFORMATIEF)


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
    #: Blok E (migratie 0104): overstap van een RLZ-administratie — vanaf deze factuurdatum boekt ze in Odoo;
    #: het oude RLZ-administratie-id blijft herleidbaar.
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


def toets_overstap_voorwaarden(*, administratie_id: uuid.UUID, url: str, company_id: int) -> tuple[str, str]:
    """De voorvalidaties van een overstap (gedeeld door `koppel_overstap` en `mapping.voorbereid_overstap`):
    bestaande, actieve RLZ-administratie zonder Odoo-koppeling; company nog vrij op deze host. Retourneert
    (naam, oud rlz_admin_id)."""
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
    al = _gekoppelde_companies(url)
    if int(company_id) in al:
        raise OdooKoppelFout(f"Company {company_id} is al gekoppeld aan een andere administratie")
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
    bewaard op de koppeling, koppeling-rij (envelope-key, dagboeken/plan uit de probe, overgangsdatum) +
    audit (nooit de key). De RLZ-credential-rij blijft staan (via het sentinel onbereikbaar); bestaande
    documenten/boekvoorstellen blijven onaangeroerd. Daarna de eerste stamgegevens-sync zoals bij koppelen.

    Blok A (04-09): `mapping` = de door de mens bevestigde rekening-mapping RLZ → Odoo (grootboek + btw) voor
    álle in-gebruik-rijen van het boekingsgeheugen en de open boekvoorstellen — gevalideerd tegen de live
    Odoo-lijsten en ín dezelfde transactie geschreven (versie 1). Een lege administratie (niets in gebruik)
    mag met een lege mapping overstappen; anders is de mapping VERPLICHT (422 "onvolledig")."""
    from app.odoo import mapping as odoo_mapping  # lokaal: mapping importeert OdooKoppelFout uit deze module

    url = odoo_url.rstrip("/")
    naam, oud_rlz_admin_id = toets_overstap_voorwaarden(
        administratie_id=administratie_id, url=url, company_id=int(company_id)
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
    odoo_gb, odoo_btw = odoo_mapping.lees_live_odoo_stamgegevens(
        odoo_url=url, api_key=api_key, company_id=int(company_id)
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rlz_gb, rlz_btw = odoo_mapping.rlz_in_gebruik(session, administratie_id)
    mapping_rijen = odoo_mapping.valideer_mapping(
        grootboek=odoo_mapping.bepaal_grootboek_voorstel(rlz_gb, odoo_gb),
        btw=odoo_mapping.bepaal_btw_voorstel(rlz_btw, odoo_btw),
        odoo_grootboek=odoo_gb,
        odoo_btw=odoo_btw,
        invoer=mapping,
    )

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
        odoo_mapping.schrijf_mapping(
            session,
            administratie_id=administratie_id,
            company_id=int(company_id),
            rijen=mapping_rijen,
            actor_id=actor_id,
            versie=1,
        )

    resultaat = GekoppeldeAdministratie(
        id=administratie_id, naam=naam, company_id=int(company_id), probe=p.rapport, sync_run_id=None
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
    )


def _toets_overgangsdatum_tegen_odoo_boekingen(session, *, administratie_id: uuid.UUID, nieuw: date) -> None:
    """C1: bestaat er een Odoo-boeking (soort 'boeking', state ≠ 'cancel') van een document mét factuurdatum
    vóór de nieuwe datum, dan is de verschuiving geblokkeerd — de adapter-poort zou die facturen "hoort nog in
    Reeleezee" noemen terwijl ze al in Odoo staan. Melding noemt het aantal + het oudste boekstuk."""
    from app.documenten.models import Boekvoorstel

    geboekt = session.execute(
        select(OdooDocumentKoppeling.odoo_naam, Boekvoorstel.factuurdatum)
        .join(Boekvoorstel, Boekvoorstel.document_id == OdooDocumentKoppeling.document_id)
        .where(
            OdooDocumentKoppeling.administratie_id == administratie_id,
            OdooDocumentKoppeling.soort == "boeking",
            OdooDocumentKoppeling.state != "cancel",
            Boekvoorstel.factuurdatum.is_not(None),
            Boekvoorstel.factuurdatum < nieuw,
        )
        .order_by(Boekvoorstel.factuurdatum, OdooDocumentKoppeling.odoo_naam)
    ).all()
    if not geboekt:
        return
    oudste_naam, oudste_datum = geboekt[0]
    n = len(geboekt)
    datum = oudste_datum.strftime("%d-%m-%Y")
    raise OvergangsdatumGeblokkeerd(
        f"Overgangsdatum {nieuw.strftime('%d-%m-%Y')} niet mogelijk: {n} factu{'ur' if n == 1 else 'ren'} mét een "
        f"eerdere factuurdatum {'is' if n == 1 else 'zijn'} al in Odoo geboekt — {oudste_naam or 'boekstuk'} op "
        f"{datum} is al in Odoo geboekt — kies een datum op of vóór {datum} of boek die factuur tegen"
    )


def wijzig_overgangsdatum(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, overgangsdatum: date) -> OdooStand:
    """De overgangsdatum van een SCHRIJVENDE Odoo-koppeling zetten/verschuiven (audit oud→nieuw). De adapter-
    poort volgt de nieuwe datum bij de volgende boekpoging; een alleen-lezen-koppeling kent geen overgangsdatum
    (daar is de voorraad-knip het begrip)."""
    # Gescoopt op de administratie: de C1-toets leest de RLS-tabel odoo_document_koppeling.
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(OdooKoppeling, administratie_id)
        if rij is None:
            raise OdooKoppelFout("Deze administratie heeft geen Odoo-koppeling")
        if rij.alleen_lezen:
            raise OdooKoppelFout(
                "De overgangsdatum hoort bij een Odoo-administratie (volledige backend), niet bij een alleen-lezen "
                "leesbron-koppeling — daar geldt de voorraad-knip"
            )
        _toets_overgangsdatum_tegen_odoo_boekingen(session, administratie_id=administratie_id, nieuw=overgangsdatum)
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
    url = odoo_url.rstrip("/")
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
    al = _gekoppelde_companies(url)
    if int(company_id) in al and al[int(company_id)] != administratie_id:
        raise OdooKoppelFout(f"Company {company_id} is al gekoppeld aan een andere administratie")
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
