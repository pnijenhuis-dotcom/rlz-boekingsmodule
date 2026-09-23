""""Nu verwerken" op de postvak-bevinding (reconciliatieblok `intake`, Peter 22-09): start de intake-job van het kanaal
on-demand — in de cloud via de Cloud Run v2 `:run` op `settings.intake_*_job_resource` (zelfde helper als "Nu draaien"
van de reconciliatie; de job draagt zijn kanaal zelf, dus geen args-overrides), lokaal een daemon-thread mét dezelfde
CLI. De service heeft géén IMAP-credentials; de job wél — daarom nooit rechtstreeks IMAP vanuit de request. Élke start
= audit `intake_postvak_nu_verwerken` (wie/welk kanaal/voertuig/uitkomst); een mislukte trigger is een 502 mét reden,
nooit stil."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.betaalstatus import KANAAL_FACTUREN, KANAAL_FACTUREN_KEMPENGROEP
from app.intake.verwerkt import AUDIT_NU_VERWERKEN

logger = logging.getLogger(__name__)

_CLI_PER_KANAAL = {
    KANAAL_FACTUREN: ["intake-postvak-verwerken"],
    KANAAL_FACTUREN_KEMPENGROEP: ["intake-postvak-kempengroep-verwerken"],
}


class OnbekendKanaal(Exception):
    pass


class StartMislukt(Exception):
    pass


@dataclass(frozen=True)
class StartResultaat:
    kanaal: str
    voertuig: str  # 'cloud_run_job' | 'thread'
    job_resource: str | None


def job_resource_voor(kanaal: str) -> str | None:
    if kanaal == KANAAL_FACTUREN:
        return settings.intake_imap_job_resource or None
    if kanaal == KANAAL_FACTUREN_KEMPENGROEP:
        return settings.intake_kempengroep_imap_job_resource or None
    return None


def start(*, kanaal: str, actor_id: uuid.UUID) -> StartResultaat:
    if kanaal not in _CLI_PER_KANAAL:
        raise OnbekendKanaal(f"Kanaal {kanaal!r} heeft geen intake-job (alleen {', '.join(_CLI_PER_KANAAL)})")
    resource = job_resource_voor(kanaal)
    voertuig = "cloud_run_job" if resource else "thread"
    try:
        if resource:
            from app.projecten.cijfers_run import _trigger_cloud_run_job

            _trigger_cloud_run_job(resource)
        else:
            threading.Thread(
                target=_thread, args=(_CLI_PER_KANAAL[kanaal],), name=f"intake-{kanaal}", daemon=True
            ).start()
    except Exception as exc:  # noqa: BLE001 — zichtbaar in audit + 502
        _audit(actor_id=actor_id, kanaal=kanaal, voertuig=voertuig, uitkomst="mislukt", fout=str(exc)[:500])
        raise StartMislukt(f"Intake-job voor {kanaal} starten mislukt: {exc}") from exc
    _audit(actor_id=actor_id, kanaal=kanaal, voertuig=voertuig, uitkomst="gestart", fout=None)
    return StartResultaat(kanaal=kanaal, voertuig=voertuig, job_resource=resource)


def _thread(argv: list[str]) -> None:
    try:
        from app import cli

        cli.main(list(argv))
    except Exception:  # noqa: BLE001
        logger.exception("Intake 'Nu verwerken': achtergrond-thread gecrasht")


def _audit(*, actor_id: uuid.UUID, kanaal: str, voertuig: str, uitkomst: str, fout: str | None) -> None:
    with scoped_session(None, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="intake_bericht_verwerkt",
            record_id=uuid.uuid4(),  # administratie-loze run-rij: eigen id, geen tabelrecord
            actie=AUDIT_NU_VERWERKEN,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"kanaal": kanaal, "voertuig": voertuig, "uitkomst": uitkomst, "fout": fout},
            administratie_id=None,
        )
