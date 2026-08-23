"""Achtergrondrun-administratie van de projectcijfers-sync (fix 504-crash 2026-08-23).

De sync-knop deed de volledige RLZ-ronde (PurchaseInvoices + SalesInvoices + Lines per
document) in één synchrone HTTP-request — tegen de echte datamassa van Universal liep dat
in Cloud Runs request-timeout (300 s → 504; logbevinding BESLISSINGEN "CIJFERS-SYNC-CRASH").
Lange RLZ-rondes horen niet in één request-response (platformbesluit 0003: achtergrondwerk
via Cloud Run jobs). Het patroon hier:

- de knop maakt een `project_cijfers_sync_run`-rij (wachtrij) en antwoordt direct 202;
- het VOERTUIG verwerkt de wachtrij: in de cloud een on-demand uitvoering van de Cloud Run-
  job `rlz-projecten-cijfers` (settings.cijfers_sync_job_resource, getriggerd via de
  metadata-server — de rij ís de opdracht, de job-args blijven leeg zodat er geen
  runWithOverrides-IAM nodig is), lokaal/dev een achtergrond-thread;
- de UI pollt de status-leesroute: wachtrij/bezig/klaar/fout mét zichtbare foutreden en
  leesfouten-teller — nooit stil (kernprincipe 4);
- `laatst_actief_op` is de heartbeat (per RLZ-pagina): een bezig-run zonder verse heartbeat
  telt als afgebroken (zichtbaar fout) en blokkeert geen nieuwe run;
- een dubbele klik hergebruikt de actieve run — er draaien nooit twee RLZ-rondes tegelijk
  op dezelfde administratie (dat veroorzaakte 23-08 mede de RLZ-403-storm).

De dagelijkse verversing loopt via `sync_alle_via_runs()` (rlz-sync-job 07:00) door exact
dezelfde run-administratie, zodat "laatst ververst" ook dan zichtbaar is."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db.models import Administratie
from app.db.session import scoped_session
from app.projecten.cijfers import sync_project_regels
from app.projecten.models import CijfersSyncRunStatus, ProjectCijfersSyncRun

logger = logging.getLogger(__name__)

# Een bezig-/wachtrij-run zonder activiteit binnen dit venster telt als afgebroken (container
# of proces gestopt zonder afronding) — zichtbaar fout, nooit een eeuwige blokkade.
STALE_NA = timedelta(minutes=10)

AFGEBROKEN_REDEN = (
    "Afgebroken — geen voortgang meer gezien (proces of container gestopt); start de verversing opnieuw"
)


class CijfersSyncStartFout(Exception):
    """Het achtergrond-voertuig kon niet gestart worden (bv. de Cloud Run-job-trigger faalde)
    — de run staat dan zichtbaar op `fout`, de aanroeper krijgt de reden."""


@dataclass(frozen=True)
class RunInfo:
    run_id: uuid.UUID
    status: str
    aangevraagd_op: datetime
    gestart_op: datetime | None
    beeindigd_op: datetime | None
    documenten: int | None
    regels: int | None
    verdwenen: int | None
    leesfouten: int | None
    fout_reden: str | None


def _is_stale(rij: ProjectCijfersSyncRun, nu: datetime) -> bool:
    if rij.status not in (CijfersSyncRunStatus.WACHTRIJ.value, CijfersSyncRunStatus.BEZIG.value):
        return False
    laatst = rij.laatst_actief_op or rij.gestart_op or rij.aangevraagd_op
    return laatst < nu - STALE_NA


def _dto(rij: ProjectCijfersSyncRun) -> RunInfo:
    return RunInfo(
        run_id=rij.id,
        status=rij.status,
        aangevraagd_op=rij.aangevraagd_op,
        gestart_op=rij.gestart_op,
        beeindigd_op=rij.beeindigd_op,
        documenten=rij.documenten,
        regels=rij.regels,
        verdwenen=rij.verdwenen,
        leesfouten=rij.leesfouten,
        fout_reden=rij.fout_reden,
    )


def _markeer_stale_runs(session, administratie_id: uuid.UUID, nu: datetime) -> None:
    for rij in session.scalars(
        select(ProjectCijfersSyncRun).where(
            ProjectCijfersSyncRun.administratie_id == administratie_id,
            ProjectCijfersSyncRun.status.in_(
                (CijfersSyncRunStatus.WACHTRIJ.value, CijfersSyncRunStatus.BEZIG.value)
            ),
        )
    ):
        if _is_stale(rij, nu):
            rij.status = CijfersSyncRunStatus.FOUT.value
            rij.fout_reden = AFGEBROKEN_REDEN
            rij.beeindigd_op = nu


def _actieve_run(session, administratie_id: uuid.UUID, nu: datetime) -> ProjectCijfersSyncRun | None:
    rijen = list(
        session.scalars(
            select(ProjectCijfersSyncRun)
            .where(
                ProjectCijfersSyncRun.administratie_id == administratie_id,
                ProjectCijfersSyncRun.status.in_(
                    (CijfersSyncRunStatus.WACHTRIJ.value, CijfersSyncRunStatus.BEZIG.value)
                ),
            )
            .order_by(ProjectCijfersSyncRun.aangevraagd_op.desc())
        )
    )
    for rij in rijen:
        if not _is_stale(rij, nu):
            return rij
    return None


def laatste_run(administratie_id: uuid.UUID) -> RunInfo | None:
    """Status-leesroute: de recentste run, met stale-vertaling (een run waarvan de verwerker
    stil stierf wordt hier als zichtbare fout gemeld i.p.v. eeuwig 'bezig')."""
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        rij = session.scalars(
            select(ProjectCijfersSyncRun)
            .where(ProjectCijfersSyncRun.administratie_id == administratie_id)
            .order_by(ProjectCijfersSyncRun.aangevraagd_op.desc())
            .limit(1)
        ).first()
        if rij is None:
            return None
        if _is_stale(rij, nu):
            rij.status = CijfersSyncRunStatus.FOUT.value
            rij.fout_reden = AFGEBROKEN_REDEN
            rij.beeindigd_op = nu
        return _dto(rij)


def start_achtergrondrun(*, administratie_id: uuid.UUID, actor_id: uuid.UUID | None) -> RunInfo:
    """Knop-ingang: maak (of hergebruik) een run en start het voertuig. Een al actieve,
    verse run wordt hergebruikt — dubbelklik of een tweede gebruiker start nooit een tweede
    RLZ-ronde op dezelfde administratie."""
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        _markeer_stale_runs(session, administratie_id, nu)
        actief = _actieve_run(session, administratie_id, nu)
        if actief is not None and actief.status == CijfersSyncRunStatus.BEZIG.value:
            return _dto(actief)
        if actief is not None:
            # Verse wachtrij-rij: hergebruiken, maar het voertuig hieronder wél (opnieuw)
            # starten — een eerder gestorven thread/job-trigger heelt zo zichzelf; de
            # claim-stap voorkomt dubbele verwerking.
            run = _dto(actief)
        else:
            rij = ProjectCijfersSyncRun(administratie_id=administratie_id, aangevraagd_door=actor_id)
            session.add(rij)
            session.flush()
            run = _dto(rij)

    try:
        _start_voertuig(administratie_id)
    except Exception as exc:  # noqa: BLE001 — élke voertuig-fout moet zichtbaar op de run
        logger.exception("Projectcijfers-sync: achtergrond-voertuig starten mislukt")
        with scoped_session(administratie_id) as session:
            rij = session.get(ProjectCijfersSyncRun, run.run_id)
            if rij is not None and rij.status == CijfersSyncRunStatus.WACHTRIJ.value:
                rij.status = CijfersSyncRunStatus.FOUT.value
                rij.fout_reden = f"Achtergrondrun starten mislukt: {exc}"
                rij.beeindigd_op = datetime.now(UTC)
        raise CijfersSyncStartFout(str(exc)) from exc
    return run


def _start_voertuig(administratie_id: uuid.UUID) -> None:
    if settings.cijfers_sync_job_resource:
        _trigger_cloud_run_job(settings.cijfers_sync_job_resource)
        return
    threading.Thread(
        target=_thread_verwerker, args=(administratie_id,), name="cijfers-sync", daemon=True
    ).start()


def _thread_verwerker(administratie_id: uuid.UUID) -> None:
    try:
        verwerk_wachtrij_voor(administratie_id)
    except Exception:  # noqa: BLE001 — de thread mag nooit stil sterven zonder logregel
        logger.exception("Projectcijfers-sync: achtergrond-thread gecrasht")


def _trigger_cloud_run_job(job_resource: str) -> None:
    """Start één uitvoering van de on-demand Cloud Run-job via de v2-API, geauthenticeerd met
    het runtime-serviceaccount (metadata-server). Bewust zónder args-overrides: de
    wachtrij-rij ís de opdracht, dus `roles/run.invoker` op de job volstaat (geen
    runWithOverrides-permissie nodig)."""
    import httpx

    token_resp = httpx.get(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
        timeout=10,
    )
    token_resp.raise_for_status()
    token = token_resp.json()["access_token"]
    resp = httpx.post(
        f"https://run.googleapis.com/v2/{job_resource}:run",
        headers={"Authorization": f"Bearer {token}"},
        json={},
        timeout=30,
    )
    resp.raise_for_status()


# --- verwerker (job/thread) ----------------------------------------------------------------


def _claim_run(administratie_id: uuid.UUID) -> uuid.UUID | None:
    """Claim de oudste wachtrij-run (FOR UPDATE SKIP LOCKED — twee gelijktijdige verwerkers
    pakken nooit dezelfde rij). Geen claim zolang er een verse bezig-run loopt: nooit twee
    RLZ-rondes tegelijk op één administratie."""
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        _markeer_stale_runs(session, administratie_id, nu)
        bezig = session.scalars(
            select(ProjectCijfersSyncRun).where(
                ProjectCijfersSyncRun.administratie_id == administratie_id,
                ProjectCijfersSyncRun.status == CijfersSyncRunStatus.BEZIG.value,
            )
        ).first()
        if bezig is not None:
            return None
        rij = session.scalars(
            select(ProjectCijfersSyncRun)
            .where(
                ProjectCijfersSyncRun.administratie_id == administratie_id,
                ProjectCijfersSyncRun.status == CijfersSyncRunStatus.WACHTRIJ.value,
            )
            .order_by(ProjectCijfersSyncRun.aangevraagd_op)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if rij is None:
            return None
        rij.status = CijfersSyncRunStatus.BEZIG.value
        rij.gestart_op = nu
        rij.laatst_actief_op = nu
        return rij.id


def _voer_run_uit(run_id: uuid.UUID, administratie_id: uuid.UUID) -> RunInfo | None:
    def heartbeat(teller: dict[str, int]) -> None:
        with scoped_session(administratie_id) as session:
            rij = session.get(ProjectCijfersSyncRun, run_id)
            if rij is not None:
                rij.laatst_actief_op = datetime.now(UTC)
                rij.documenten = teller.get("documenten")
                rij.regels = teller.get("regels")

    try:
        teller = sync_project_regels(administratie_id=administratie_id, voortgang=heartbeat)
    except Exception as exc:  # noqa: BLE001 — élke fout zichtbaar op de run, nooit stil
        logger.exception("Projectcijfers-sync mislukt voor administratie %s", administratie_id)
        with scoped_session(administratie_id) as session:
            rij = session.get(ProjectCijfersSyncRun, run_id)
            if rij is not None:
                rij.status = CijfersSyncRunStatus.FOUT.value
                rij.fout_reden = str(exc) or exc.__class__.__name__
                rij.beeindigd_op = datetime.now(UTC)
            return _dto(rij) if rij is not None else None

    with scoped_session(administratie_id) as session:
        rij = session.get(ProjectCijfersSyncRun, run_id)
        if rij is not None:
            rij.status = CijfersSyncRunStatus.KLAAR.value
            rij.beeindigd_op = datetime.now(UTC)
            rij.laatst_actief_op = rij.beeindigd_op
            rij.documenten = teller["documenten"]
            rij.regels = teller["regels"]
            rij.verdwenen = teller["verdwenen"]
            rij.leesfouten = teller["leesfouten"]
            rij.fout_reden = None
        return _dto(rij) if rij is not None else None


def verwerk_wachtrij_voor(administratie_id: uuid.UUID) -> RunInfo | None:
    """Verwerk álle openstaande wachtrij-runs van één administratie (sequentieel — méér dan
    één komt door de hergebruik-logica zelden voor). Geeft de laatst verwerkte run terug."""
    laatste: RunInfo | None = None
    while (run_id := _claim_run(administratie_id)) is not None:
        laatste = _voer_run_uit(run_id, administratie_id)
    return laatste


def _opt_in_administraties() -> list[uuid.UUID]:
    with scoped_session(None) as session:
        return [
            rij.id
            for rij in session.scalars(select(Administratie).where(Administratie.uren_meerwerk_ingeschakeld))
        ]


def verwerk_wachtrij() -> dict[uuid.UUID, RunInfo | None]:
    """CLI-entrypoint van de on-demand job `rlz-projecten-cijfers`: verwerk de wachtrij van
    alle uren-&-meerwerk-administraties. Geen wachtrij = snelle no-op (een dubbele
    job-uitvoering is onschadelijk — de claim beschermt)."""
    return {administratie_id: verwerk_wachtrij_voor(administratie_id) for administratie_id in _opt_in_administraties()}


def sync_administratie_via_run(administratie_id: uuid.UUID) -> RunInfo | None:
    """Synchrone verversing via de run-administratie (dagelijkse sync-job + make-target):
    zelfde spoor als de knop, zodat 'laatst ververst' ook voor de nachtelijke run zichtbaar
    is in de status-leesroute. Een al actieve verse run wordt eerst afgewacht via de
    wachtrij-claim (geen dubbele RLZ-ronde)."""
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        _markeer_stale_runs(session, administratie_id, nu)
        if _actieve_run(session, administratie_id, nu) is None:
            session.add(ProjectCijfersSyncRun(administratie_id=administratie_id, aangevraagd_door=None))
    return verwerk_wachtrij_voor(administratie_id)


def sync_alle_via_runs() -> dict[uuid.UUID, RunInfo | str]:
    """Alle administraties mét de uren-&-meerwerk-opt-in (de steigerbouw-tak) — één kapotte
    administratie stopt de rest niet (patroon sync_alle_administraties)."""
    resultaten: dict[uuid.UUID, RunInfo | str] = {}
    for administratie_id in _opt_in_administraties():
        try:
            run = sync_administratie_via_run(administratie_id)
            resultaten[administratie_id] = run if run is not None else "geen run verwerkt (al bezig?)"
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie sync_alle_administraties
            resultaten[administratie_id] = str(exc)
    return resultaten
