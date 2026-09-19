"""Extractie-wachtrij: interface + in-process dev-implementatie (async extractie, 2026-07-10).

Het contract (`ExtractieWachtrij`) is bewust smal en payload-gedreven — enqueue krijgt alleen
(administratie_id, document_id), nooit een callable of open sessie. Precies dat contract past
straks één-op-één op de geplande Cloud Tasks/Cloud Run-variant (BOUWPLAN, platformverbetering 1):
de cloud-implementatie bouwt uit dezelfde twee id's een HTTP-taak; de taaknaam kan er dan
deterministisch uit worden afgeleid (idempotency-key-conventie, besluit 0013-stijl). De worker-
functie zelf (`service.verwerk_extractie_taak`) is al idempotent via de statusmachine: alleen een
document dat daadwerkelijk op `extractie_wachtrij` staat wordt opgepakt, een dubbele of verouderde
taak is een zichtbare no-op in de log.

De dev-implementatie is een in-process threadpool met een kleine, configureerbare limiet
(`settings.ai_extractie_worker_concurrency`, default 1) — de overbelastingsbescherming: één
monsterfactuur kan de machine niet plattrekken, volgende taken wachten netjes in de queue.
Bekende beperking (bewust, dev-only): de queue overleeft een proces-herstart niet — het
startup-vangnet `service.herstel_achtergebleven_extracties()` zet achtergebleven documenten dan
terug in de wachtrij ("niets verdwijnt stil").

CLOUD (feedbackronde 26-08 punt 4 — "geüploade factuur krijgt geen AI-extractie"): op Cloud Run
met request-based billing (deploy.yml: bewust géén --no-cpu-throttling) krijgt een achtergrond-
thread buiten een request nauwelijks CPU — een groot document (scan > 3 MB of > 8 pagina's,
`ai_extractie_sync_max_*`) bleef daardoor in `extractie_wachtrij` hangen tot de volgende
herstart; kleine (digitale, gemailde) PDF's gaan synchroon en merkten er niets van. Daarom
`CloudRunJobExtractieWachtrij`: enqueue triggert één uitvoering van de on-demand job
`rlz-extractie-wachtrij` (zelfde metadata-server-patroon als rlz-projecten-cijfers/rlz-bank-sync),
die met `DirecteExtractieWachtrij` álle wachtrij-documenten synchroon afwerkt
(`service.verwerk_extractie_wachtrij`). Een scheduler-vangnet (elke 10 min, f3_jobs.sh) vangt
een gemiste trigger. De rij-status ís de opdracht: dubbele job-runs zijn idempotent via de
statusmachine.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Protocol

logger = logging.getLogger(__name__)

# Signatuur van de worker-taak: (administratie_id, document_id) -> None, vangt zelf al zijn
# fouten af (zie service.verwerk_extractie_taak) — de wachtrij heeft er alleen een vangnet-log op.
ExtractieTaak = Callable[..., None]


class ExtractieWachtrij(Protocol):
    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None: ...


class InProcessExtractieWachtrij:
    """Dev-wachtrij: threadpool met max `max_workers` gelijktijdige extracties (default uit
    settings, bewust 1). `wacht_tot_leeg()` is er voor tests en een nette shutdown — productie
    (Cloud Tasks) heeft dat concept niet nodig."""

    def __init__(self, *, taak: ExtractieTaak, max_workers: int | None = None) -> None:
        from app.config import settings  # lokaal: houdt deze module vrij van settings bij import

        self._taak = taak
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or settings.ai_extractie_worker_concurrency,
            thread_name_prefix="extractie-worker",
        )
        self._lock = threading.Lock()
        self._futures: list[Future[None]] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]
            self._futures.append(
                self._executor.submit(self._veilig, administratie_id=administratie_id, document_id=document_id)
            )

    def _veilig(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        try:
            self._taak(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — vangnet: een worker-crash mag de threadpool nooit stil leegtrekken
            logger.exception("Extractie-wachtrijtaak faalde onverwacht voor document %s", document_id)

    def wacht_tot_leeg(self, timeout: float = 30.0) -> None:
        with self._lock:
            futures = list(self._futures)
        wait(futures, timeout=timeout)


class DirecteExtractieWachtrij:
    """Synchrone wachtrij voor het job-/CLI-proces: enqueue voert de taak meteen uit in de
    aanroepende thread. Geen threads, geen verloren queue — de job eindigt pas als alles af is."""

    def __init__(self, *, taak: ExtractieTaak) -> None:
        self._taak = taak
        self.verwerkt: list[uuid.UUID] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        try:
            self._taak(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — één falend document mag de rest van de wachtrij niet stoppen
            logger.exception("Extractie-wachtrijtaak faalde onverwacht voor document %s", document_id)
        self.verwerkt.append(document_id)


#: Bundelvenster van de job-trigger (systeemfout BLOW-bulk 18-09, opdracht ic_spiegel_rood/wachtrij): één executie per
#: batch. Binnen dit venster ná een GESLAAGDE trigger wordt niet opnieuw getriggerd — de job leest zelf álles wat op
#: `extractie_wachtrij` staat en doet ná een pas mét werk een extra pas (`verwerk_extractie_wachtrij`), dus de lopende
#: executie dekt de documenten die intussen binnenkomen. Vóór 19-09 triggerde élke upload apart: 180 uploads → 118
#: job-executies in één uur, 180 × `429 Too Many Requests` op de Jobs-API (LET-OP `vangnet_scheduler`) én parallelle
#: executies die dezelfde documenten dubbel verwerkten (AI-kosten, dubbele tijdlijnregels, stale overschrijving).
TRIGGER_BUNDEL_VENSTER_S = 30.0
UITKOMST_GESLAAGD = "geslaagd"
UITKOMST_MISLUKT = "mislukt"
#: Trigger bewust niet gedaan: valt binnen het bundelvenster van een geslaagde trigger — GEEN fout (teller-categorie
#: `trigger_gebundeld`, zacht; het document staat zichtbaar op 'in wachtrij' tot de lopende executie 'm pakt).
UITKOMST_GEBUNDELD = "gebundeld"

#: Laatste geslaagde trigger per job-resource (monotone klok), procesbreed: twee uploads in hetzelfde proces binnen het
#: venster delen één executie. Meerdere Cloud Run-instances triggeren ieder hooguit één keer per venster — nog steeds
#: ver onder het quotum, en de statusmachine + CAS houden dubbelverwerking tegen.
_laatste_trigger: dict[str, float] = {}
_laatste_trigger_lock = threading.Lock()


def reset_bundelvenster() -> None:
    """Testhulp: vergeet de laatste triggers (het venster is procesbreed)."""
    with _laatste_trigger_lock:
        _laatste_trigger.clear()


class CloudRunJobExtractieWachtrij:
    """Cloud-wachtrij: een enqueue triggert één uitvoering van de on-demand Cloud Run-job
    (`settings.extractie_wachtrij_job_resource`), hooguit één per `TRIGGER_BUNDEL_VENSTER_S` seconden (bundelvenster,
    zie daar). De job leest zelf welke documenten op `extractie_wachtrij` staan — de statusrij ís de opdracht, dus geen
    payload/overrides nodig (roles/run.invoker volstaat). Faalt de trigger, dan blijft het document zichtbaar op
    'in wachtrij' en pakt het scheduler-vangnet het binnen 10 minuten op; de fout wordt gelogd, nooit naar de uploader
    gegooid (de upload zelf is geslaagd). Élke enqueue laat een audit-spoor achter (geslaagd/gebundeld/mislukt)."""

    def __init__(
        self,
        *,
        job_resource: str,
        trigger: Callable[[str], None] | None = None,
        spoor: Callable[..., None] | None = None,
        bundel_venster_s: float = TRIGGER_BUNDEL_VENSTER_S,
        klok: Callable[[], float] = time.monotonic,
    ) -> None:
        self._job_resource = job_resource
        self._trigger = trigger
        self._spoor = spoor if spoor is not None else leg_trigger_uitkomst_vast
        self._bundel_venster_s = bundel_venster_s
        self._klok = klok

    def _binnen_bundelvenster(self, nu: float) -> float | None:
        """Seconden sinds de laatste geslaagde trigger als die binnen het venster valt, anders None."""
        with _laatste_trigger_lock:
            laatste = _laatste_trigger.get(self._job_resource)
        if laatste is None:
            return None
        verstreken = nu - laatste
        return verstreken if 0 <= verstreken < self._bundel_venster_s else None

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        fout: str | None = None
        nu = self._klok()
        verstreken = self._binnen_bundelvenster(nu)
        if verstreken is not None:
            logger.info(
                "Extractie-wachtrij: trigger voor document %s gebundeld met de trigger van %.0f s eerder (venster %.0f s)",
                document_id,
                verstreken,
                self._bundel_venster_s,
            )
            self._spoor(
                administratie_id=administratie_id,
                document_id=document_id,
                job_resource=self._job_resource,
                fout=None,
                uitkomst=UITKOMST_GEBUNDELD,
                gebundeld_na_s=round(verstreken, 1),
            )
            return
        try:
            if self._trigger is not None:
                self._trigger(self._job_resource)
            else:
                from app.projecten.cijfers_run import _trigger_cloud_run_job

                _trigger_cloud_run_job(self._job_resource)
        except Exception as exc:  # noqa: BLE001 — trigger-fout mag de upload nooit laten falen; vangnet = scheduler
            fout = f"{type(exc).__name__}: {exc}"[:500]
            logger.exception(
                "Extractie-wachtrij: Cloud Run-job %s triggeren mislukt voor document %s — het "
                "scheduler-vangnet pakt het document op",
                self._job_resource,
                document_id,
            )
        else:
            with _laatste_trigger_lock:
                _laatste_trigger[self._job_resource] = nu
        self._spoor(
            administratie_id=administratie_id,
            document_id=document_id,
            job_resource=self._job_resource,
            fout=fout,
            uitkomst=UITKOMST_MISLUKT if fout else UITKOMST_GESLAAGD,
        )


#: Audit-actie van het trigger-spoor (herstelrun "Basis eerst" 08-09, blok 2). Gelezen door de tellers per
#: automatisering in de reconciliatie (`app/reconciliatie/automatiseringen.py`, automatisering
#: `extractie_wachtrij`): geslaagd = gedaan, mislukt = overgeslagen "vangnet scheduler" (LET-OP).
TRIGGER_AUDIT_ACTIE = "extractie_wachtrij_trigger"


def leg_trigger_uitkomst_vast(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    job_resource: str,
    fout: str | None,
    uitkomst: str | None = None,
    gebundeld_na_s: float | None = None,
) -> None:
    """Eén audit-event per enqueue (bestaand patroon `record_audit_event`, systeem-actor, gescoopt op de
    administratie; geen migratie): `nieuwe_waarde = {uitkomst: geslaagd|gebundeld|mislukt, job, fout[, gebundeld_na_s]}`.
    Vóór 08-09 stond de uitkomst alleen in de log ("triggeren mislukt") — niet telbaar in de reconciliatiemail, dus een
    stil falende trigger (IAM `run.invoker`) zou pas opvallen als extracties tot 10 minuten wachtten. Sinds 19-09 óók
    `gebundeld` (bundelvenster): telbaar als zachte overslaan-reden, nooit een LET-OP. Nooit raise-n: een niet
    geschreven spoor mag de upload niet laten falen."""
    try:
        from app.db.audit import record_audit_event
        from app.db.session import scoped_session
        from app.db.systeem_actor import SYSTEEM_ACTOR_ID

        waarde: dict[str, object] = {
            "uitkomst": uitkomst or (UITKOMST_MISLUKT if fout else UITKOMST_GESLAAGD),
            "job": job_resource.rsplit("/", 1)[-1],
            "fout": fout,
        }
        if gebundeld_na_s is not None:
            waarde["gebundeld_na_s"] = gebundeld_na_s
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie=TRIGGER_AUDIT_ACTIE,
                correlatie_id=document_id,
                nieuwe_waarde=waarde,
                administratie_id=administratie_id,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Extractie-wachtrij: trigger-spoor niet geschreven voor document %s", document_id)
