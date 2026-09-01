"""Bank auto-verversing bij openen (besluit Peter 25-08, feedbackronde deel 4 punt 2) — het
cijfers-sync-patroon (app/projecten/cijfers_run.py, migratie 0063) toegepast op de bank-sync:

  1. Het bankscherm toont de cache direct ("laatst ververst HH:MM") en POST `…/bank/sync-achtergrond`.
  2. DREMPEL tegen rate-limit-verspilling: is `BankSyncStand.laatste_sync_op` jonger dan
     `settings.bank_auto_ververs_drempel_minuten` (default 5), dan start er GEEN ronde — de
     aanroeper krijgt `overgeslagen=True` mét het laatste sync-moment. De handmatige
     verversen-knop (`POST …/bank/sync`, synchroon) blijft onbegrensd.
  3. Anders een `bank_sync_run`-rij (wachtrij) + voertuig: dev = thread, cloud = on-demand Cloud
     Run-job (`settings.bank_sync_job_resource`, CLI `bank-sync-wachtrij`). Eén actieve run per
     administratie (dubbelklik/tweede gebruiker = dezelfde run).
  4. De verwerker claimt de rij (skip_locked), draait `sync.sync_bank_voor_administratie` — exact
     dezelfde motor als de knop, incl. verificatie/autoflows — en zet klaar/fout mét reden.
  5. De UI pollt `GET …/bank/sync-achtergrond/status` en werkt de lijst bij zodra `klaar`; `fout`
     toont de reden. Een stille dood wordt via `laatst_actief_op` als fout vertaald (STALE_NA).
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.bank import sync
from app.bank.models import BankSyncRun, BankSyncRunStatus, BankSyncStand
from app.config import settings
from app.db.session import scoped_session

logger = logging.getLogger(__name__)

STALE_NA = timedelta(minutes=10)
AFGEBROKEN_REDEN = "Afgebroken — geen voortgang meer gezien (proces of container gestopt); ververs opnieuw"


class BankSyncStartFout(Exception):
    """Het achtergrond-voertuig kon niet gestart worden — de run staat zichtbaar op `fout`."""


@dataclass(frozen=True)
class BankSyncRunInfo:
    run_id: uuid.UUID | None
    status: str  # geen | overgeslagen | wachtrij | bezig | klaar | fout
    overgeslagen: bool
    laatste_sync_op: datetime | None
    aangevraagd_op: datetime | None = None
    beeindigd_op: datetime | None = None
    resultaat: dict | None = None
    fout_reden: str | None = None


def _is_stale(rij: BankSyncRun, nu: datetime) -> bool:
    if rij.status not in (BankSyncRunStatus.WACHTRIJ.value, BankSyncRunStatus.BEZIG.value):
        return False
    laatst = rij.laatst_actief_op or rij.gestart_op or rij.aangevraagd_op
    return laatst < nu - STALE_NA


def _laatste_sync_op(session, administratie_id: uuid.UUID) -> datetime | None:
    stand = session.get(BankSyncStand, administratie_id)
    return stand.laatste_sync_op if stand else None


def _dto(rij: BankSyncRun | None, *, laatste_sync_op: datetime | None, overgeslagen: bool = False) -> BankSyncRunInfo:
    if rij is None:
        return BankSyncRunInfo(
            run_id=None, status="overgeslagen" if overgeslagen else "geen", overgeslagen=overgeslagen,
            laatste_sync_op=laatste_sync_op,
        )
    return BankSyncRunInfo(
        run_id=rij.id, status=rij.status, overgeslagen=False, laatste_sync_op=laatste_sync_op,
        aangevraagd_op=rij.aangevraagd_op, beeindigd_op=rij.beeindigd_op, resultaat=rij.resultaat,
        fout_reden=rij.fout_reden,
    )


def _markeer_stale(session, administratie_id: uuid.UUID, nu: datetime) -> None:
    for rij in session.scalars(
        select(BankSyncRun).where(
            BankSyncRun.administratie_id == administratie_id,
            BankSyncRun.status.in_((BankSyncRunStatus.WACHTRIJ.value, BankSyncRunStatus.BEZIG.value)),
        )
    ):
        if _is_stale(rij, nu):
            rij.status = BankSyncRunStatus.FOUT.value
            rij.fout_reden = AFGEBROKEN_REDEN
            rij.beeindigd_op = nu


def _actieve_run(session, administratie_id: uuid.UUID) -> BankSyncRun | None:
    return session.scalars(
        select(BankSyncRun)
        .where(
            BankSyncRun.administratie_id == administratie_id,
            BankSyncRun.status.in_((BankSyncRunStatus.WACHTRIJ.value, BankSyncRunStatus.BEZIG.value)),
        )
        .order_by(BankSyncRun.aangevraagd_op.desc())
    ).first()


def laatste_run(administratie_id: uuid.UUID) -> BankSyncRunInfo:
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        _markeer_stale(session, administratie_id, nu)
        rij = session.scalars(
            select(BankSyncRun)
            .where(BankSyncRun.administratie_id == administratie_id)
            .order_by(BankSyncRun.aangevraagd_op.desc())
            .limit(1)
        ).first()
        return _dto(rij, laatste_sync_op=_laatste_sync_op(session, administratie_id))


def start_bij_openen(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID | None, forceer: bool = False
) -> BankSyncRunInfo:
    """Ingang van het bankscherm: drempel → hergebruik actieve run → nieuwe run + voertuig.
    `forceer` (blok E2, het ⟳-icoon = handmatige noodrem) slaat alleen de drempel over — een al
    lopende run wordt nog steeds hergebruikt (nooit twee runs tegelijk)."""
    nu = datetime.now(UTC)
    drempel = timedelta(minutes=settings.bank_auto_ververs_drempel_minuten)
    with scoped_session(administratie_id) as session:
        _markeer_stale(session, administratie_id, nu)
        laatste = _laatste_sync_op(session, administratie_id)
        actief = _actieve_run(session, administratie_id)
        if actief is not None:
            return _dto(actief, laatste_sync_op=laatste)
        if not forceer and laatste is not None and laatste > nu - drempel:
            return _dto(None, laatste_sync_op=laatste, overgeslagen=True)
        rij = BankSyncRun(administratie_id=administratie_id, aangevraagd_door=actor_id)
        session.add(rij)
        session.flush()
        run = _dto(rij, laatste_sync_op=laatste)
    try:
        _start_voertuig(administratie_id)
    except Exception as exc:  # noqa: BLE001 — élke voertuig-fout moet zichtbaar op de run
        logger.exception("Bank auto-verversing: voertuig starten mislukt")
        with scoped_session(administratie_id) as session:
            rij = session.get(BankSyncRun, run.run_id)
            if rij is not None and rij.status == BankSyncRunStatus.WACHTRIJ.value:
                rij.status = BankSyncRunStatus.FOUT.value
                rij.fout_reden = f"Achtergrondrun starten mislukt: {exc}"
                rij.beeindigd_op = datetime.now(UTC)
        raise BankSyncStartFout(str(exc)) from exc
    return run


def _start_voertuig(administratie_id: uuid.UUID) -> None:
    if settings.bank_sync_job_resource:
        from app.projecten.cijfers_run import _trigger_cloud_run_job

        _trigger_cloud_run_job(settings.bank_sync_job_resource)
        return
    threading.Thread(target=_thread_verwerker, args=(administratie_id,), name="bank-sync", daemon=True).start()


def _thread_verwerker(administratie_id: uuid.UUID) -> None:
    try:
        verwerk_wachtrij_voor(administratie_id)
    except Exception:  # noqa: BLE001
        logger.exception("Bank auto-verversing: achtergrond-thread gecrasht")


def _claim(administratie_id: uuid.UUID) -> uuid.UUID | None:
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        rij = session.scalars(
            select(BankSyncRun)
            .where(
                BankSyncRun.administratie_id == administratie_id,
                BankSyncRun.status == BankSyncRunStatus.WACHTRIJ.value,
            )
            .order_by(BankSyncRun.aangevraagd_op)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if rij is None:
            return None
        rij.status = BankSyncRunStatus.BEZIG.value
        rij.gestart_op = nu
        rij.laatst_actief_op = nu
        return rij.id


def verwerk_wachtrij_voor(administratie_id: uuid.UUID) -> int:
    """Verwerkt alle wachtrij-runs van één administratie (meestal één). Geeft het aantal
    afgeronde runs terug."""
    aantal = 0
    while (run_id := _claim(administratie_id)) is not None:
        aantal += 1
        try:
            resultaat = sync.sync_bank_voor_administratie(administratie_id=administratie_id)
            samenvatting = {
                "rekeningen_bijgewerkt": resultaat.rekeningen.aangemaakt + resultaat.rekeningen.bijgewerkt,
                "mutaties_nieuw": resultaat.mutaties.aangemaakt,
                "mutaties_bijgewerkt": resultaat.mutaties.bijgewerkt,
                "open_ververst": resultaat.mutaties.open_ververst,
                "open_posten_bijgewerkt": resultaat.open_posten.aangemaakt + resultaat.open_posten.bijgewerkt,
                "afletteren_geverifieerd": resultaat.afletteren_geverifieerd,
                "afletteren_wachtend": getattr(resultaat, "afletteren_wachtend", 0),
                "automatisch_afgeletterd": resultaat.automatisch_afgeletterd,
                "automatisch_geboekt": resultaat.automatisch_geboekt,
                "fouten": list(resultaat.afletter_fouten) + list(resultaat.automatisch_fouten),
            }
            fout: str | None = None
        except Exception as exc:  # noqa: BLE001 — de reden moet op de run, nooit stil
            logger.exception("Bank auto-verversing mislukt voor %s", administratie_id)
            samenvatting = None
            fout = f"{type(exc).__name__}: {exc}"
        with scoped_session(administratie_id) as session:
            rij = session.get(BankSyncRun, run_id)
            if rij is None:
                continue
            rij.beeindigd_op = datetime.now(UTC)
            rij.laatst_actief_op = rij.beeindigd_op
            if fout is None:
                rij.status = BankSyncRunStatus.KLAAR.value
                rij.resultaat = samenvatting
            else:
                rij.status = BankSyncRunStatus.FOUT.value
                rij.fout_reden = fout
    return aantal


def verwerk_wachtrij() -> int:
    """CLI-/job-entrypoint (`bank-sync-wachtrij`): alle administraties met een wachtrij-rij."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    totaal = 0
    for administratie_id in administratie_ids:
        totaal += verwerk_wachtrij_voor(administratie_id)
    return totaal


def als_dict(info: BankSyncRunInfo) -> dict:
    return asdict(info)
