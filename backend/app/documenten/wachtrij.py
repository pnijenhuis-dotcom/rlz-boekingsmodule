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
"""

from __future__ import annotations

import logging
import threading
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
