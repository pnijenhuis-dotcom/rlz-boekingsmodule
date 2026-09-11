"""Eerste sync van een via de wizard aangesloten administratie (feedbackronde 26-08 punt 5) —
het bank-sync-run-patroon (app/bank/sync_run.py) met status PER ONDERDEEL:

  1. Ná het opslaan van de administratie (onboarding.maak_administraties_aan) start een
     `administratie_sync_run` (wachtrij) + voertuig: dev = thread, cloud = on-demand Cloud
     Run-job (`settings.eerste_sync_job_resource`, CLI `eerste-sync-wachtrij`).
  2. De verwerker claimt de rij (skip_locked) en draait de bestaande sync-motoren onderdeel
     voor onderdeel — Ledgers, TaxRates, Vendors, Projects, PaymentAccounts — met één
     RLZ-verbinding; ná élk onderdeel wordt de rij bijgewerkt (heartbeat + zichtbare voortgang).
  3. Een onderdeel dat faalt zet alleen zíjn status op fout (mét reden) en stopt de rest niet;
     de run eindigt op `klaar` als alles lukte, anders `fout` met een samenvatting.
  4. De wizard pollt `GET /instellingen/administraties/{id}/eerste-sync/status`.

Blok 3 run 11-09 middag (bevinding Peter: Baard / Box Beheer / Kempen B.V.) — RLZ zet de rechten van een verse
API-koppeling met vertraging door (probe groen 11:5x, sync 403 direct erna, RLZ-check groen de volgende ochtend):
  5. Krijgt een onderdeel HTTP 403 op een route die de laatst opgeslagen rechten-probe (`platform.rlz_rechten_probe`)
     GROEN had, dan is dat geen fout maar "RLZ zet rechten door": de run krijgt status `rechten_onderweg` met
     `pogingen` + `volgende_poging_op` (5, 15, 60 min ná de vorige poging, daarna elk uur) — nooit langer dan
     `HERPROBEER_MAX` (24 u) ná `aangevraagd_op`; daarna `fout` mét het letterlijke RLZ-antwoord (bestaand patroon).
     Een 401, een 5xx of een 403 op een route die de probe NIET groen had blijft direct `fout`.
  6. De wekker `herprobeer_vervallen()` (stap `eerste_sync_wekker` in de kwartier-job rlz-bewaking, `app/bewaking/
     service.py`) zet vervallen runs terug in de wachtrij en start het bestaande voertuig; mislukt de job-trigger
     (IAM), dan verwerkt de wekker de run in-process — het herproberen stopt nooit stil. Alleen de onderdelen die nog
     niet `klaar` zijn worden opnieuw gedraaid. Audit per herpoging (`eerste_sync_herpoging_gepland` /
     `eerste_sync_herpoging_gestart` / `eerste_sync_herproberen_opgegeven`, systeem-actor).
  7. "Sync opnieuw starten" op een wachtende run = dezelfde run direct terug in de wachtrij (zelfde 24-uursvenster).
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import tijd
from app.beheer.models import AdministratieSyncRun, AdministratieSyncRunStatus
from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

logger = logging.getLogger(__name__)

STALE_NA = timedelta(minutes=15)
#: Herproberen ná een 403 op een probe-groene route (blok 3 run 11-09): wachttijd ná de 1e/2e/3e afgeronde poging …
HERPROBEER_INTERVALLEN_MIN: tuple[int, ...] = (5, 15, 60)
#: … en daarna elk uur, tot maximaal 24 u ná de aanvraag van de run.
HERPROBEER_VERVOLG_MIN = 60
HERPROBEER_MAX = timedelta(hours=24)
#: HTTP-statussen die "rechten nog onderweg" kúnnen betekenen (401 = login zelf geweigerd → direct fout).
HERPROBEERBARE_STATUSSEN = (403,)
#: Onderdeel-/run-stand "RLZ zet rechten door — opnieuw over N min".
RECHTEN_ONDERWEG = AdministratieSyncRunStatus.RECHTEN_ONDERWEG.value
OPGEGEVEN_PREFIX = "Na 24 uur herproberen"
AFGEBROKEN_REDEN = "Afgebroken — geen voortgang meer gezien (proces of container gestopt); start de sync opnieuw"
ONDERDELEN: tuple[str, ...] = ("ledgers", "taxrates", "vendors", "projects", "payment_accounts")


class EersteSyncStartFout(Exception):
    """Het achtergrond-voertuig kon niet gestart worden — de run staat zichtbaar op `fout`."""


@dataclass(frozen=True)
class EersteSyncRunInfo:
    run_id: uuid.UUID | None
    status: str  # geen | wachtrij | bezig | klaar | fout
    onderdelen: dict[str, dict] | None = None
    aangevraagd_op: datetime | None = None
    beeindigd_op: datetime | None = None
    fout_reden: str | None = None
    # Blok 3 run 11-09 (additief): aantal afgeronde pogingen + wanneer de wekker opnieuw probeert (alleen bij
    # status `rechten_onderweg`).
    pogingen: int = 0
    volgende_poging_op: datetime | None = None


def _nu() -> datetime:
    """Tijdstempel-bron van deze module (UTC) — via `app.tijd._klok` zodat tests het tijdsverloop kunnen sturen."""
    return tijd._klok()


def herprobeer_interval(pogingen: int) -> timedelta:
    """Wachttijd ná de N-de afgeronde poging: 1 → 5 min, 2 → 15 min, 3 → 60 min, daarna elk uur."""
    idx = max(pogingen, 1) - 1
    minuten = HERPROBEER_INTERVALLEN_MIN[idx] if idx < len(HERPROBEER_INTERVALLEN_MIN) else HERPROBEER_VERVOLG_MIN
    return timedelta(minutes=minuten)


def _dto(rij: AdministratieSyncRun | None) -> EersteSyncRunInfo:
    if rij is None:
        return EersteSyncRunInfo(run_id=None, status="geen")
    return EersteSyncRunInfo(
        run_id=rij.id,
        status=rij.status,
        onderdelen=rij.onderdelen,
        aangevraagd_op=rij.aangevraagd_op,
        beeindigd_op=rij.beeindigd_op,
        fout_reden=rij.fout_reden,
        pogingen=rij.pogingen or 0,
        volgende_poging_op=rij.volgende_poging_op,
    )


def _markeer_stale(session, administratie_id: uuid.UUID, nu: datetime) -> None:
    for rij in session.scalars(
        select(AdministratieSyncRun).where(
            AdministratieSyncRun.administratie_id == administratie_id,
            AdministratieSyncRun.status.in_(
                (AdministratieSyncRunStatus.WACHTRIJ.value, AdministratieSyncRunStatus.BEZIG.value)
            ),
        )
    ):
        laatst = rij.laatst_actief_op or rij.gestart_op or rij.aangevraagd_op
        if laatst < nu - STALE_NA:
            rij.status = AdministratieSyncRunStatus.FOUT.value
            rij.fout_reden = AFGEBROKEN_REDEN
            rij.beeindigd_op = nu


def _actieve_run(session, administratie_id: uuid.UUID) -> AdministratieSyncRun | None:
    return session.scalars(
        select(AdministratieSyncRun)
        .where(
            AdministratieSyncRun.administratie_id == administratie_id,
            AdministratieSyncRun.status.in_(
                (AdministratieSyncRunStatus.WACHTRIJ.value, AdministratieSyncRunStatus.BEZIG.value)
            ),
        )
        .order_by(AdministratieSyncRun.aangevraagd_op.desc())
    ).first()


def laatste_run(administratie_id: uuid.UUID) -> EersteSyncRunInfo:
    nu = _nu()
    with scoped_session(administratie_id) as session:
        _markeer_stale(session, administratie_id, nu)
        rij = session.scalars(
            select(AdministratieSyncRun)
            .where(AdministratieSyncRun.administratie_id == administratie_id)
            .order_by(AdministratieSyncRun.aangevraagd_op.desc())
            .limit(1)
        ).first()
        return _dto(rij)


def _is_odoo_administratie(administratie_id: uuid.UUID) -> bool:
    from app.backends.port import Backend
    from app.backends.registry import OnbekendeBackend, backend_voor

    try:
        return backend_voor(administratie_id) is Backend.ODOO
    except OnbekendeBackend:
        return False


def start_run(*, administratie_id: uuid.UUID, actor_id: uuid.UUID | None) -> EersteSyncRunInfo:
    """Nieuwe run (of hergebruik van een al actieve) + voertuig starten.

    Odoo-administratie (blok E): de RLZ-verwerker zou op het sentinel fail-loud stranden; de Odoo-
    stamgegevenssync is klein (~10 calls) en draait daarom SYNCHROON via `app.odoo.service.eerste_sync`
    (zelfde `administratie_sync_run`-rij) — zo werkt "Sync opnieuw starten" vanuit de gedeelde UI-component."""
    if _is_odoo_administratie(administratie_id):
        from app.db.systeem_actor import SYSTEEM_ACTOR_ID
        from app.odoo import service as odoo_service

        odoo_service.eerste_sync(administratie_id=administratie_id, actor_id=actor_id or SYSTEEM_ACTOR_ID)
        return laatste_run(administratie_id)
    nu = _nu()
    with scoped_session(administratie_id, actor_id=actor_id or SYSTEEM_ACTOR_ID) as session:
        _markeer_stale(session, administratie_id, nu)
        actief = _actieve_run(session, administratie_id)
        if actief is not None:
            return _dto(actief)
        wachtend = _rechten_onderweg_run(session, administratie_id)
        if wachtend is not None:
            # "Sync opnieuw starten" op een wachtende run (blok 3 run 11-09): dezelfde run direct terug in de wachtrij —
            # zelfde 24-uursvenster, poging telt door; de mens hoeft niet op de wekker te wachten.
            _zet_in_wachtrij(session, wachtend, nu=nu, aanleiding="handmatig", actor_id=actor_id or SYSTEEM_ACTOR_ID)
            run = _dto(wachtend)
        else:
            rij = AdministratieSyncRun(
                administratie_id=administratie_id,
                aangevraagd_door=actor_id,
                aangevraagd_op=nu,
                onderdelen={naam: {"status": "wachtrij"} for naam in ONDERDELEN},
            )
            session.add(rij)
            session.flush()
            run = _dto(rij)
    try:
        _start_voertuig(administratie_id)
    except Exception as exc:  # noqa: BLE001 — élke voertuig-fout moet zichtbaar op de run
        logger.exception("Eerste sync: voertuig starten mislukt")
        with scoped_session(administratie_id) as session:
            rij = session.get(AdministratieSyncRun, run.run_id)
            if rij is not None and rij.status == AdministratieSyncRunStatus.WACHTRIJ.value:
                rij.status = AdministratieSyncRunStatus.FOUT.value
                rij.fout_reden = f"Achtergrondrun starten mislukt: {exc}"
                rij.beeindigd_op = _nu()
        raise EersteSyncStartFout(str(exc)) from exc
    return run


def _rechten_onderweg_run(session, administratie_id: uuid.UUID) -> AdministratieSyncRun | None:
    return session.scalars(
        select(AdministratieSyncRun)
        .where(
            AdministratieSyncRun.administratie_id == administratie_id,
            AdministratieSyncRun.status == RECHTEN_ONDERWEG,
        )
        .order_by(AdministratieSyncRun.aangevraagd_op.desc())
    ).first()


def _zet_in_wachtrij(session, rij: AdministratieSyncRun, *, nu: datetime, aanleiding: str, actor_id: uuid.UUID) -> None:
    """Een wachtende run (`rechten_onderweg`) terug in de wachtrij zetten (wekker of mens) + audit per herpoging."""
    rij.status = AdministratieSyncRunStatus.WACHTRIJ.value
    rij.volgende_poging_op = None
    rij.laatst_actief_op = nu  # de stale-toets rekent vanaf nú, niet vanaf de vorige poging
    onderdelen = dict(rij.onderdelen or {})
    for naam, stand in onderdelen.items():
        if isinstance(stand, dict) and stand.get("status") == RECHTEN_ONDERWEG:
            onderdelen[naam] = {**stand, "status": "wachtrij"}
    rij.onderdelen = onderdelen
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="administratie_sync_run",
        record_id=rij.id,
        actie="eerste_sync_herpoging_gestart",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"poging": (rij.pogingen or 0) + 1, "aanleiding": aanleiding},
        administratie_id=rij.administratie_id,
    )


def herprobeer_vervallen(nu: datetime | None = None) -> int:
    """Wekker (stap `eerste_sync_wekker` in de kwartier-job rlz-bewaking): élke run in `rechten_onderweg` waarvan
    `volgende_poging_op` verstreken is gaat terug in de wachtrij en het bestaande voertuig wordt gestart (cloud: de
    on-demand job rlz-eerste-sync; dev: thread). Kan het voertuig niet starten (bv. IAM `run.invoker` ontbreekt voor
    run-jobs@), dan verwerkt de wekker de run zelf in-process — het herproberen stopt nooit stil. Geeft het aantal
    gestarte herpogingen terug (de bewaking legt dat als detail vast)."""
    from app.db.models import Administratie

    nu = nu or _nu()
    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    gestart = 0
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            vervallen = list(
                session.scalars(
                    select(AdministratieSyncRun).where(
                        AdministratieSyncRun.administratie_id == administratie_id,
                        AdministratieSyncRun.status == RECHTEN_ONDERWEG,
                        AdministratieSyncRun.volgende_poging_op.is_not(None),
                        AdministratieSyncRun.volgende_poging_op <= nu,
                    )
                )
            )
            for rij in vervallen:
                _zet_in_wachtrij(session, rij, nu=nu, aanleiding="wekker", actor_id=SYSTEEM_ACTOR_ID)
            aantal = len(vervallen)
        if not aantal:
            continue
        gestart += aantal
        try:
            _start_voertuig(administratie_id)
        except Exception:  # noqa: BLE001 — voertuig kapot ≠ herproberen kapot: in-process doorlopen, zichtbaar in de log
            logger.exception(
                "Eerste-sync-wekker: voertuig starten mislukt voor %s — in-process verwerkt", administratie_id
            )
            verwerk_wachtrij_voor(administratie_id)
    return gestart


def _start_voertuig(administratie_id: uuid.UUID) -> None:
    if settings.eerste_sync_job_resource:
        from app.projecten.cijfers_run import _trigger_cloud_run_job

        _trigger_cloud_run_job(settings.eerste_sync_job_resource)
        return
    threading.Thread(target=_thread_verwerker, args=(administratie_id,), name="eerste-sync", daemon=True).start()


def _thread_verwerker(administratie_id: uuid.UUID) -> None:
    try:
        verwerk_wachtrij_voor(administratie_id)
    except Exception:  # noqa: BLE001
        logger.exception("Eerste sync: achtergrond-thread gecrasht")


@dataclass(frozen=True)
class _Geclaimd:
    run_id: uuid.UUID
    pogingen: int
    aangevraagd_op: datetime
    eerder_klaar: dict[str, dict]  # onderdelen die een vorige poging al `klaar` had — niet opnieuw draaien


def _claim(administratie_id: uuid.UUID) -> _Geclaimd | None:
    nu = _nu()
    with scoped_session(administratie_id) as session:
        rij = session.scalars(
            select(AdministratieSyncRun)
            .where(
                AdministratieSyncRun.administratie_id == administratie_id,
                AdministratieSyncRun.status == AdministratieSyncRunStatus.WACHTRIJ.value,
            )
            .order_by(AdministratieSyncRun.aangevraagd_op)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if rij is None:
            return None
        rij.status = AdministratieSyncRunStatus.BEZIG.value
        rij.gestart_op = nu
        rij.laatst_actief_op = nu
        eerder_klaar = {
            naam: stand
            for naam, stand in (rij.onderdelen or {}).items()
            if isinstance(stand, dict) and stand.get("status") == "klaar"
        }
        return _Geclaimd(
            run_id=rij.id, pogingen=rij.pogingen or 0, aangevraagd_op=rij.aangevraagd_op, eerder_klaar=eerder_klaar
        )


def _schrijf_onderdeel(administratie_id: uuid.UUID, run_id: uuid.UUID, naam: str, stand: dict) -> None:
    with scoped_session(administratie_id) as session:
        rij = session.get(AdministratieSyncRun, run_id)
        if rij is None:
            return
        onderdelen = dict(rij.onderdelen or {})
        onderdelen[naam] = stand
        rij.onderdelen = onderdelen
        rij.laatst_actief_op = _nu()


def _telling(resultaat) -> dict:
    return {
        "status": "klaar",
        "aangemaakt": getattr(resultaat, "aangemaakt", None),
        "bijgewerkt": getattr(resultaat, "bijgewerkt", None),
        "verdwenen": getattr(resultaat, "verdwenen", None),
    }


#: HTTP-statussen die "Reeleezee weigert deze login/dit recht" betekenen — géén tijdelijke fout, een instelling in RLZ.
RECHTEN_STATUSSEN = (401, 403)


def _fout_stand(naam: str, exc: Exception) -> dict:
    """Zichtbare stand van een mislukt onderdeel (blok C 10-09): bij een RLZ-weigering (401/403) een leesbare regel
    mét de route, het RLZ-recht dat ontbreekt (app/rlz/leesroutes.py) en het LETTERLIJKE RLZ-antwoord (≤ 300
    tekens) — zodat de Beheerder weet wat hij in Reeleezee moet zetten. Andere fouten: het bestaande
    `TypeNaam: tekst`-spoor (afgekapt 500)."""
    from app.rlz import leesroutes
    from app.rlz.client import RlzApiError

    stand: dict = {"status": "fout", "fout": f"{type(exc).__name__}: {exc}"[:500]}
    if not isinstance(exc, RlzApiError):
        return stand
    route = leesroutes.SYNC_LEESROUTES.get(naam) or leesroutes.route_voor_pad(exc.url)
    melding = " ".join((exc.body or "").split())
    if len(melding) > 300:
        melding = melding[:299] + "…"
    stand.update({"http_status": exc.status_code, "rlz_melding": melding, "rlz_url": exc.url})
    routenaam = route.naam if route is not None else exc.url
    if exc.status_code in RECHTEN_STATUSSEN:
        recht = route.rlz_recht if route is not None else "controleer de rechten van de webservice-gebruiker in RLZ"
        stand["rlz_recht"] = recht
        stand["fout"] = (
            f"Reeleezee weigert GET {routenaam} (HTTP {exc.status_code}) — {recht}. "
            f'RLZ zegt: "{melding or "(leeg antwoord)"}"'
        )[:700]
    else:
        stand["fout"] = f'Reeleezee antwoordt HTTP {exc.status_code} op GET {routenaam}: "{melding or "(leeg)"}"'[:700]
    return stand


def _fout_reden(uitkomsten: dict[str, dict]) -> str | None:
    mislukt = [naam for naam, stand in uitkomsten.items() if stand.get("status") != "klaar"]
    if not mislukt:
        return None
    reden = "Niet alle onderdelen gelukt: " + ", ".join(mislukt) + " — zie details per onderdeel"
    geweigerd = [naam for naam in mislukt if uitkomsten[naam].get("http_status") in RECHTEN_STATUSSEN]
    if geweigerd:
        statussen = sorted({str(uitkomsten[n]["http_status"]) for n in geweigerd})
        reden += (
            f". LET OP: Reeleezee weigert de opgeslagen webservice-login (HTTP {'/'.join(statussen)}) op "
            + ", ".join(geweigerd)
            + " — geef de webservice-gebruiker in RLZ de ontbrekende leesrechten (per onderdeel staat welk recht) en "
            "start de sync opnieuw; de rechten-probe (Instellingen › Administraties › Webservice-gegevens) toont "
            "dezelfde routes"
        )
    return reden


def _voer_onderdelen_uit(
    administratie_id: uuid.UUID, run_id: uuid.UUID, *, eerder_klaar: dict[str, dict] | None = None
) -> dict[str, dict]:
    """Alle onderdelen draaien; bij een herpoging (blok 3 run 11-09) alleen de onderdelen die nog niet `klaar` waren —
    de al geslaagde standen reizen ongewijzigd mee."""
    from app.bank import sync as bank_sync
    from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
    from app.sync import service as sync_service

    client = client_voor_rlz_admin_id(rlz_admin_id_voor(administratie_id))
    stappen = {
        "ledgers": lambda: sync_service.sync_ledgers(administratie_id=administratie_id, client=client),
        "taxrates": lambda: sync_service.sync_taxrates(administratie_id=administratie_id, client=client),
        "vendors": lambda: sync_service.sync_vendors(administratie_id=administratie_id, client=client),
        "projects": lambda: sync_service.sync_projects(administratie_id=administratie_id, client=client),
        "payment_accounts": lambda: bank_sync.sync_payment_accounts(administratie_id=administratie_id, client=client),
    }
    uitkomsten: dict[str, dict] = dict(eerder_klaar or {})
    try:
        for naam in ONDERDELEN:
            if naam in uitkomsten:
                continue
            _schrijf_onderdeel(administratie_id, run_id, naam, {"status": "bezig"})
            try:
                uitkomsten[naam] = _telling(stappen[naam]())
            except Exception as exc:  # noqa: BLE001 — per onderdeel zichtbaar, de rest gaat door
                logger.exception("Eerste sync: onderdeel %s mislukt voor %s", naam, administratie_id)
                uitkomsten[naam] = _fout_stand(naam, exc)
            _schrijf_onderdeel(administratie_id, run_id, naam, uitkomsten[naam])
    finally:
        client.close()
    return uitkomsten


def is_herprobeerbaar(uitkomsten: dict[str, dict], probe_rapport: dict[str, str] | None) -> bool:
    """Puur: mag deze mislukte uitkomst herprobeerd worden? Alleen als ÉLK mislukt onderdeel een 403 kreeg op een route
    die de opgeslagen rechten-probe groen ('ok') had. Geen probe-rapport, een 401/5xx, een niet-RLZ-fout of een 403 op
    een route die de probe óók al rood had = nee (direct fout, bestaand gedrag)."""
    from app.rlz import leesroutes

    mislukt = {naam: stand for naam, stand in uitkomsten.items() if stand.get("status") != "klaar"}
    if not mislukt or not probe_rapport:
        return False
    for naam, stand in mislukt.items():
        if stand.get("http_status") not in HERPROBEERBARE_STATUSSEN:
            return False
        route = leesroutes.SYNC_LEESROUTES.get(naam)
        if route is None or probe_rapport.get(route.naam) != "ok":
            return False
    return True


def _probe_rapport(administratie_id: uuid.UUID) -> dict[str, str] | None:
    from app.db.models import RlzRechtenProbe

    with scoped_session(administratie_id) as session:
        rij = session.get(RlzRechtenProbe, administratie_id)
        return dict(rij.rapport) if rij is not None and isinstance(rij.rapport, dict) else None


def _rlz_melding_uit(uitkomsten: dict[str, dict]) -> str:
    """Het letterlijke RLZ-antwoord van het eerste mislukte onderdeel (≤ 300 tekens, al afgekapt in `_fout_stand`)."""
    for stand in uitkomsten.values():
        if stand.get("status") != "klaar" and stand.get("rlz_melding"):
            return str(stand["rlz_melding"])
    return ""


def _sluit_run_af(
    administratie_id: uuid.UUID, geclaimd: _Geclaimd, *, uitkomsten: dict[str, dict], fout: str | None, herprobeer: bool
) -> None:
    nu = _nu()
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(AdministratieSyncRun, geclaimd.run_id)
        if rij is None:
            return
        rij.pogingen = geclaimd.pogingen + 1
        rij.laatst_actief_op = nu
        if fout is None:
            rij.status = AdministratieSyncRunStatus.KLAAR.value
            rij.beeindigd_op = nu
            rij.volgende_poging_op = None
            rij.fout_reden = None
            return
        binnen_venster = nu - geclaimd.aangevraagd_op < HERPROBEER_MAX
        mislukt = [naam for naam, stand in uitkomsten.items() if stand.get("status") != "klaar"]
        if herprobeer and binnen_venster:
            rij.status = RECHTEN_ONDERWEG
            rij.beeindigd_op = None
            rij.fout_reden = None
            rij.volgende_poging_op = nu + herprobeer_interval(rij.pogingen)
            rij.onderdelen = {
                naam: ({**stand, "status": RECHTEN_ONDERWEG} if naam in mislukt else stand)
                for naam, stand in uitkomsten.items()
            }
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="administratie_sync_run",
                record_id=rij.id,
                actie="eerste_sync_herpoging_gepland",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "poging": rij.pogingen,
                    "volgende_poging_op": rij.volgende_poging_op.isoformat(),
                    "onderdelen": mislukt,
                    "rlz_melding": _rlz_melding_uit(uitkomsten),
                },
                administratie_id=administratie_id,
            )
            return
        rij.status = AdministratieSyncRunStatus.FOUT.value
        rij.beeindigd_op = nu
        rij.volgende_poging_op = None
        if herprobeer:
            # 24 u verstreken: nu wél rood, mét het letterlijke RLZ-antwoord (zit al in `fout` per onderdeel + reden).
            sinds = f"{geclaimd.aangevraagd_op.astimezone(UTC):%d-%m-%Y %H:%M} UTC"
            rij.fout_reden = (
                f"{OPGEGEVEN_PREFIX} ({rij.pogingen} pogingen sinds {sinds}) weigert Reeleezee nog steeds. {fout}"
            )
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="administratie_sync_run",
                record_id=rij.id,
                actie="eerste_sync_herproberen_opgegeven",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "pogingen": rij.pogingen,
                    "onderdelen": mislukt,
                    "rlz_melding": _rlz_melding_uit(uitkomsten),
                },
                administratie_id=administratie_id,
            )
        else:
            rij.fout_reden = fout


def verwerk_wachtrij_voor(administratie_id: uuid.UUID) -> int:
    aantal = 0
    while (geclaimd := _claim(administratie_id)) is not None:
        aantal += 1
        uitkomsten: dict[str, dict] = {}
        herprobeer = False
        try:
            uitkomsten = _voer_onderdelen_uit(administratie_id, geclaimd.run_id, eerder_klaar=geclaimd.eerder_klaar)
            fout: str | None = _fout_reden(uitkomsten)
            if fout is not None:
                herprobeer = is_herprobeerbaar(uitkomsten, _probe_rapport(administratie_id))
        except Exception as exc:  # noqa: BLE001 — bv. geen credentials: reden op de run, nooit stil
            logger.exception("Eerste sync mislukt voor %s", administratie_id)
            fout = f"{type(exc).__name__}: {exc}"
        _sluit_run_af(administratie_id, geclaimd, uitkomsten=uitkomsten, fout=fout, herprobeer=herprobeer)
    return aantal


def verwerk_wachtrij() -> int:
    """CLI-/job-entrypoint (`eerste-sync-wachtrij`): alle administraties met een wachtrij-rij."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    return sum(verwerk_wachtrij_voor(administratie_id) for administratie_id in administratie_ids)


def als_dict(info: EersteSyncRunInfo) -> dict:
    return asdict(info)
