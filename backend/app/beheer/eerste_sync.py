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
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.beheer.models import AdministratieSyncRun, AdministratieSyncRunStatus
from app.config import settings
from app.db.session import scoped_session

logger = logging.getLogger(__name__)

STALE_NA = timedelta(minutes=15)
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
    nu = datetime.now(UTC)
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
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        _markeer_stale(session, administratie_id, nu)
        actief = _actieve_run(session, administratie_id)
        if actief is not None:
            return _dto(actief)
        rij = AdministratieSyncRun(
            administratie_id=administratie_id,
            aangevraagd_door=actor_id,
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
                rij.beeindigd_op = datetime.now(UTC)
        raise EersteSyncStartFout(str(exc)) from exc
    return run


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


def _claim(administratie_id: uuid.UUID) -> uuid.UUID | None:
    nu = datetime.now(UTC)
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
        return rij.id


def _schrijf_onderdeel(administratie_id: uuid.UUID, run_id: uuid.UUID, naam: str, stand: dict) -> None:
    with scoped_session(administratie_id) as session:
        rij = session.get(AdministratieSyncRun, run_id)
        if rij is None:
            return
        onderdelen = dict(rij.onderdelen or {})
        onderdelen[naam] = stand
        rij.onderdelen = onderdelen
        rij.laatst_actief_op = datetime.now(UTC)


def _telling(resultaat) -> dict:
    return {
        "status": "klaar",
        "aangemaakt": getattr(resultaat, "aangemaakt", None),
        "bijgewerkt": getattr(resultaat, "bijgewerkt", None),
        "verdwenen": getattr(resultaat, "verdwenen", None),
    }


def _voer_onderdelen_uit(administratie_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, dict]:
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
    uitkomsten: dict[str, dict] = {}
    try:
        for naam in ONDERDELEN:
            _schrijf_onderdeel(administratie_id, run_id, naam, {"status": "bezig"})
            try:
                uitkomsten[naam] = _telling(stappen[naam]())
            except Exception as exc:  # noqa: BLE001 — per onderdeel zichtbaar, de rest gaat door
                logger.exception("Eerste sync: onderdeel %s mislukt voor %s", naam, administratie_id)
                uitkomsten[naam] = {"status": "fout", "fout": f"{type(exc).__name__}: {exc}"[:500]}
            _schrijf_onderdeel(administratie_id, run_id, naam, uitkomsten[naam])
    finally:
        client.close()
    return uitkomsten


def verwerk_wachtrij_voor(administratie_id: uuid.UUID) -> int:
    aantal = 0
    while (run_id := _claim(administratie_id)) is not None:
        aantal += 1
        try:
            uitkomsten = _voer_onderdelen_uit(administratie_id, run_id)
            mislukt = [naam for naam, stand in uitkomsten.items() if stand.get("status") != "klaar"]
            fout: str | None = (
                None
                if not mislukt
                else "Niet alle onderdelen gelukt: " + ", ".join(mislukt) + " — zie details per onderdeel"
            )
        except Exception as exc:  # noqa: BLE001 — bv. geen credentials: reden op de run, nooit stil
            logger.exception("Eerste sync mislukt voor %s", administratie_id)
            fout = f"{type(exc).__name__}: {exc}"
        with scoped_session(administratie_id) as session:
            rij = session.get(AdministratieSyncRun, run_id)
            if rij is None:
                continue
            rij.beeindigd_op = datetime.now(UTC)
            rij.laatst_actief_op = rij.beeindigd_op
            if fout is None:
                rij.status = AdministratieSyncRunStatus.KLAAR.value
            else:
                rij.status = AdministratieSyncRunStatus.FOUT.value
                rij.fout_reden = fout
    return aantal


def verwerk_wachtrij() -> int:
    """CLI-/job-entrypoint (`eerste-sync-wachtrij`): alle administraties met een wachtrij-rij."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    return sum(verwerk_wachtrij_voor(administratie_id) for administratie_id in administratie_ids)


def als_dict(info: EersteSyncRunInfo) -> dict:
    return asdict(info)
