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
  6. Blok 1 (besluit Peter 08-09, "bank-sync automatisch, geen knoppen"): de nachtelijke `sync-alles`
     draait dezelfde motor voor ÁLLE actieve administraties via `sync_alle_via_runs(bron="sync_alles")`
     — elke administratie krijgt een `bank_sync_run`-rij (aangevraagd_door NULL, `resultaat.bron`),
     zodat klantenlijst ("laatste sync") en reconciliatie-teller `bank_sync` op één spoor leunen.
     Geen RLZ-verbinding (geen credential / Odoo-administratie) = zichtbaar overgeslagen, géén rij en
     géén fout; een al lopende on-demand run wordt hergebruikt (nooit twee tegelijk).
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
from app.rlz.credentials import GeenRlzCredentials, resolve_credentials, rlz_admin_id_voor

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


def verwerk_wachtrij_voor(administratie_id: uuid.UUID, *, bron: str | None = None) -> int:
    """Verwerkt alle wachtrij-runs van één administratie (meestal één). Geeft het aantal
    afgeronde runs terug. `bron` (blok 1, 08-09) reist mee in `resultaat.bron` — "sync_alles" voor de
    nachtelijke lus; None = on-demand (openen bankscherm / ⟳), ongewijzigd gedrag."""
    aantal = 0
    while (run_id := _claim(administratie_id)) is not None:
        aantal += 1
        try:
            resultaat = sync.sync_bank_voor_administratie(administratie_id=administratie_id)
            samenvatting = {
                **({"bron": bron} if bron else {}),
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
                # Blok B (10-09): AI-poort-uitkomsten en historie-cache-telling — reconciliatie-tellers lezen hieruit.
                "overgeslagen": list(getattr(resultaat, "automatisch_overgeslagen", [])),
                "historie_toegevoegd": getattr(resultaat, "historie_module_toegevoegd", 0)
                + getattr(resultaat, "historie_rlz_toegevoegd", 0),
                "historie_rlz_resterend": getattr(resultaat, "historie_rlz_resterend", 0),
                "historie_fouten": list(getattr(resultaat, "historie_fouten", [])),
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


# --- blok 1 (08-09): nachtelijke lus over álle actieve administraties ---------------------------------

BRON_SYNC_ALLES = "sync_alles"


@dataclass(frozen=True)
class BankSyncOvergeslagen:
    """Administratie zonder RLZ-verbinding: zichtbaar overgeslagen (CLI-regel + reconciliatie-teller),
    géén run-rij en géén fout. `reden` = 'odoo_administratie' | 'geen_credential'."""

    reden: str
    detail: str


def _overslaan_reden(administratie_id: uuid.UUID) -> BankSyncOvergeslagen | None:
    """Vooraf toetsen (zonder RlzClient te openen) of er een RLZ-verbinding is — `resolve_credentials`
    is voor Odoo-sentinels en ontbrekende credentials fail-loud met GeenRlzCredentials."""
    from app.odoo.ids import is_odoo_sentinel

    try:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        if is_odoo_sentinel(rlz_admin_id):
            return BankSyncOvergeslagen("odoo_administratie", "Odoo-administratie — bank loopt niet via Reeleezee")
        resolve_credentials(rlz_admin_id)
    except GeenRlzCredentials as exc:
        return BankSyncOvergeslagen("geen_credential", str(exc))
    return None


def start_nachtelijke_run(administratie_id: uuid.UUID) -> BankSyncRunInfo | BankSyncOvergeslagen:
    """Eén administratie in de nachtelijke lus: overslaan zonder verbinding; anders een run-rij
    (aangevraagd_door NULL) en direct synchroon verwerken — een al lopende (niet-stale) on-demand run
    wordt hergebruikt en NIET dubbel gestart (die maakt zijn eigen status af)."""
    overgeslagen = _overslaan_reden(administratie_id)
    if overgeslagen is not None:
        return overgeslagen
    nu = datetime.now(UTC)
    with scoped_session(administratie_id) as session:
        _markeer_stale(session, administratie_id, nu)
        actief = _actieve_run(session, administratie_id)
        if actief is not None and actief.status == BankSyncRunStatus.BEZIG.value:
            return _dto(actief, laatste_sync_op=_laatste_sync_op(session, administratie_id))
        if actief is None:
            session.add(BankSyncRun(administratie_id=administratie_id, aangevraagd_door=None))
            session.flush()
    verwerk_wachtrij_voor(administratie_id, bron=BRON_SYNC_ALLES)
    return laatste_run(administratie_id)


def sync_alle_via_runs() -> dict[uuid.UUID, BankSyncRunInfo | BankSyncOvergeslagen | str]:
    """Entrypoint voor `sync-alles` (cli.py::_sync_alles): álle actieve administraties, één kapotte stopt
    de rest niet (een onverwachte exception buiten de run-motor landt als string = fout)."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        administratie_ids = list(
            session.scalars(select(Administratie.id).where(Administratie.actief.is_(True)).order_by(Administratie.naam))
        )
    uit: dict[uuid.UUID, BankSyncRunInfo | BankSyncOvergeslagen | str] = {}
    for administratie_id in administratie_ids:
        try:
            uit[administratie_id] = start_nachtelijke_run(administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed: één kapotte administratie mag de rest niet raken
            logger.exception("Nachtelijke bank-sync mislukt voor %s", administratie_id)
            uit[administratie_id] = f"{type(exc).__name__}: {exc}"
    return uit


def als_dict(info: BankSyncRunInfo) -> dict:
    return asdict(info)
