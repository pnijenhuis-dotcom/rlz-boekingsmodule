"""Kantoorbrede herberekening als ACHTERGRONDRUN (design-ronde 03-09 blok B1, mockup
inzicht-kantoorbreed ③: "één kantoorbrede knop, zelfde 202+status-patroon als de bank-sync — nooit
meer per administratie klikken"). Het bank_sync_run-patroon (app/bank/sync_run.py) toegepast op
`herbereken_alle()`, maar PLATFORMBREED (migratie 0099):

  1. `POST /terugkerend/herbereken` maakt één `terugkerend_herbereken_run`-rij (202 + run-id); een
     al wachtende/bezige run wordt hergebruikt (dubbelklik/tweede gebruiker = dezelfde run).
  2. Voertuig: dev = daemon-thread, cloud = on-demand Cloud Run-job
     (`settings.terugkerend_herbereken_job_resource`, CLI `terugkerend-herbereken-wachtrij`).
  3. De verwerker claimt de rij (FOR UPDATE SKIP LOCKED), draait de BESTAANDE motor
     `service.herbereken_alle()` — géén RLZ-calls, géén AI — en telt per administratie mee
     (`aantal_verwerkt`/`aantal_fouten`/`laatst_actief_op`), zet klaar/fout mét reden.
  4. De UI pollt `GET /terugkerend/herbereken/{run_id}`; een stille dood wordt via `laatst_actief_op`
     als zichtbare fout vertaald (STALE_NA) — nooit eeuwig 'bezig'."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import settings
from app.db.models import Administratie
from app.db.session import scoped_session
from app.terugkerend import service
from app.terugkerend.models import HerberekenRunStatus, TerugkerendHerberekenRun

logger = logging.getLogger(__name__)

STALE_NA = timedelta(minutes=15)
AFGEBROKEN_REDEN = "Afgebroken — geen voortgang meer gezien (proces of container gestopt); start opnieuw"
_ACTIEF = (HerberekenRunStatus.WACHTEND.value, HerberekenRunStatus.BEZIG.value)


class HerberekenStartFout(Exception):
    """Het achtergrond-voertuig kon niet gestart worden — de run staat zichtbaar op `fout`."""


class HerberekenRunNietGevonden(Exception):
    pass


@dataclass(frozen=True)
class HerberekenRunInfo:
    run_id: uuid.UUID
    status: str  # wachtend | bezig | klaar | fout
    aangevraagd_op: datetime
    gestart_op: datetime | None
    klaar_op: datetime | None
    aantal_administraties: int
    aantal_verwerkt: int
    aantal_fouten: int
    foutreden: str | None
    resultaat: dict | None


def _dto(rij: TerugkerendHerberekenRun) -> HerberekenRunInfo:
    return HerberekenRunInfo(
        run_id=rij.id,
        status=rij.status,
        aangevraagd_op=rij.aangevraagd_op,
        gestart_op=rij.gestart_op,
        klaar_op=rij.klaar_op,
        aantal_administraties=rij.aantal_administraties,
        aantal_verwerkt=rij.aantal_verwerkt,
        aantal_fouten=rij.aantal_fouten,
        foutreden=rij.foutreden,
        resultaat=rij.resultaat,
    )


def _markeer_stale(session, nu: datetime) -> None:
    for rij in session.scalars(select(TerugkerendHerberekenRun).where(TerugkerendHerberekenRun.status.in_(_ACTIEF))):
        laatst = rij.laatst_actief_op or rij.gestart_op or rij.aangevraagd_op
        if laatst < nu - STALE_NA:
            rij.status = HerberekenRunStatus.FOUT.value
            rij.foutreden = AFGEBROKEN_REDEN
            rij.klaar_op = nu


def start_run(*, actor_id: uuid.UUID) -> HerberekenRunInfo:
    """Hergebruik een actieve run, anders een nieuwe rij + voertuig. Voertuig-fout = zichtbaar op de run."""
    nu = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        _markeer_stale(session, nu)
        actief = session.scalars(
            select(TerugkerendHerberekenRun)
            .where(TerugkerendHerberekenRun.status.in_(_ACTIEF))
            .order_by(TerugkerendHerberekenRun.aangevraagd_op.desc())
        ).first()
        if actief is not None:
            return _dto(actief)
        aantal = session.scalar(select(func.count()).select_from(Administratie).where(Administratie.actief.is_(True)))
        rij = TerugkerendHerberekenRun(gestart_door=actor_id, aantal_administraties=int(aantal or 0))
        session.add(rij)
        session.flush()
        session.refresh(rij)
        info = _dto(rij)
    try:
        _start_voertuig()
    except Exception as exc:  # noqa: BLE001 — élke voertuig-fout moet zichtbaar op de run
        logger.exception("Terugkerend-herberekening: voertuig starten mislukt")
        with scoped_session(None, actor_id=actor_id) as session:
            rij = session.get(TerugkerendHerberekenRun, info.run_id)
            if rij is not None and rij.status == HerberekenRunStatus.WACHTEND.value:
                rij.status = HerberekenRunStatus.FOUT.value
                rij.foutreden = f"Achtergrondrun starten mislukt: {exc}"
                rij.klaar_op = datetime.now(UTC)
        raise HerberekenStartFout(str(exc)) from exc
    return info


def status_van(run_id: uuid.UUID) -> HerberekenRunInfo:
    nu = datetime.now(UTC)
    with scoped_session(None) as session:
        _markeer_stale(session, nu)
        rij = session.get(TerugkerendHerberekenRun, run_id)
        if rij is None:
            raise HerberekenRunNietGevonden(f"Herberekening {run_id} niet gevonden")
        return _dto(rij)


def laatste_run() -> HerberekenRunInfo | None:
    """De jongste run (voor "stand van …" op het scherm bij binnenkomst)."""
    nu = datetime.now(UTC)
    with scoped_session(None) as session:
        _markeer_stale(session, nu)
        rij = session.scalars(
            select(TerugkerendHerberekenRun).order_by(TerugkerendHerberekenRun.aangevraagd_op.desc()).limit(1)
        ).first()
        return _dto(rij) if rij is not None else None


def _start_voertuig() -> None:
    if settings.terugkerend_herbereken_job_resource:
        from app.projecten.cijfers_run import _trigger_cloud_run_job

        _trigger_cloud_run_job(settings.terugkerend_herbereken_job_resource)
        return
    threading.Thread(target=_thread_verwerker, name="terugkerend-herbereken", daemon=True).start()


def _thread_verwerker() -> None:
    try:
        verwerk_wachtrij()
    except Exception:  # noqa: BLE001
        logger.exception("Terugkerend-herberekening: achtergrond-thread gecrasht")


def _claim() -> uuid.UUID | None:
    nu = datetime.now(UTC)
    with scoped_session(None) as session:
        rij = session.scalars(
            select(TerugkerendHerberekenRun)
            .where(TerugkerendHerberekenRun.status == HerberekenRunStatus.WACHTEND.value)
            .order_by(TerugkerendHerberekenRun.aangevraagd_op)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if rij is None:
            return None
        rij.status = HerberekenRunStatus.BEZIG.value
        rij.gestart_op = nu
        rij.laatst_actief_op = nu
        return rij.id


class _Voortgang:
    """Telt per administratie mee op de run-rij (aantal_verwerkt/aantal_fouten/laatst_actief_op)."""

    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.resultaat: dict[str, dict | str] = {}
        self.fouten = 0

    def __call__(self, administratie_id: uuid.UUID, uitkomst: dict | str) -> None:
        self.resultaat[str(administratie_id)] = uitkomst
        if isinstance(uitkomst, str):
            self.fouten += 1
        with scoped_session(None) as session:
            rij = session.get(TerugkerendHerberekenRun, self.run_id)
            if rij is not None:
                rij.aantal_verwerkt = len(self.resultaat)
                rij.aantal_fouten = self.fouten
                rij.laatst_actief_op = datetime.now(UTC)


def verwerk_wachtrij() -> int:
    """CLI-/job-/thread-entrypoint (`terugkerend-herbereken-wachtrij`): verwerk alle wachtende runs
    (meestal één). Fouten per administratie landen in `resultaat` + `aantal_fouten`; alleen een
    crash van de motor zelf zet de run op `fout`. Geeft het aantal afgeronde runs terug."""
    aantal = 0
    while (run_id := _claim()) is not None:
        aantal += 1
        voortgang = _Voortgang(run_id)
        fout: str | None = None
        try:
            service.herbereken_alle(voortgang=voortgang)
        except Exception as exc:  # noqa: BLE001 — de reden moet op de run, nooit stil
            logger.exception("Terugkerend-herberekening kantoorbreed mislukt")
            fout = f"{type(exc).__name__}: {exc}"
        with scoped_session(None) as session:
            rij = session.get(TerugkerendHerberekenRun, run_id)
            if rij is None:
                continue
            rij.klaar_op = datetime.now(UTC)
            rij.laatst_actief_op = rij.klaar_op
            rij.aantal_verwerkt = len(voortgang.resultaat)
            rij.aantal_fouten = voortgang.fouten
            rij.resultaat = voortgang.resultaat
            if fout is None:
                rij.status = HerberekenRunStatus.KLAAR.value
            else:
                rij.status = HerberekenRunStatus.FOUT.value
                rij.foutreden = fout
    return aantal


def als_dict(info: HerberekenRunInfo) -> dict:
    return asdict(info)
