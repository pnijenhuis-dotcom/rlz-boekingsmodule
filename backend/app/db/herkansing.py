"""Eén herkansing per item bij een verbroken databaseverbinding (nazorg-CLI's, akkoord Peter 03-09).

Aanleiding: de nabundel-cloud-run van 03-09 verloor om 12:36 de Cloud SQL Auth Proxy; élk volgend
paar faalde op `OperationalError: server closed the connection unexpectedly`. De engine draagt al
sinds migratie 0001 `pool_pre_ping=True` (een dode pool-verbinding wordt bij het uitchecken
vervangen), maar een verbinding die MIDDEN in een item wegvalt is daarmee niet gedekt: het item
faalt, en zonder herkansing telt het als mislukt terwijl de transactie schoon is teruggerold.

Contract:
- `voer_uit_met_herkansing(fn)` roept `fn()` aan; faalt dat op een VERBROKEN VERBINDING (en alleen
  dan), dan wacht het kort en probeert precies één keer opnieuw — een nieuwe transactie langs
  dezelfde idempotente poorten (elk item is één `scoped_session`-transactie: geslaagd óf volledig
  teruggerold, dus een herkansing herhaalt nooit een half item; bleek de eerste poging tóch
  gecommit — de bevestiging ging verloren ná de commit — dan ziet de herkansing dat aan de
  poorten en meldt "al verwerkt"). Elke andere fout gaat ongewijzigd door: die is geen blip.
- Faalt ook de herkansing op een verbroken verbinding, dan komt `VerbindingVerbroken` — de
  aanroeper telt het item als mislukt mét die reden en kan bij een reeks van zulke items stoppen
  (de proxy is dan écht weg; doorstampen levert alleen dezelfde fout per item op).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

#: Wachttijd vóór de herkansing — lang genoeg voor een proxy-hertik, kort genoeg om een run niet te rekken.
HERKANSING_WACHT_SECONDS = 5.0

#: Fouttekstfragmenten (psycopg/libpq) die een weggevallen of onbereikbare verbinding betekenen — náást
#: SQLAlchemy's eigen `connection_invalidated` (is_disconnect) die niet op een connect-fout wordt gezet.
_VERBROKEN_FRAGMENTEN = (
    "server closed the connection unexpectedly",
    "connection refused",
    "could not connect",
    "connection failed",
    "connection is closed",
    "connection already closed",
    "terminating connection",
    "ssl connection has been closed",
    "ssl syscall error",
    "consuming input failed",
    "eof detected",
    "connection reset by peer",
    "broken pipe",
    "connection timed out",
    "the database system is shutting down",
    "the database system is starting up",
)


class VerbindingVerbroken(Exception):
    """Ook de herkansing faalde op een verbroken verbinding; `__cause__` is de onderliggende fout."""

    def __init__(self, label: str, oorzaak: BaseException) -> None:
        super().__init__(f"verbinding met de database verbroken bij {label}, ook ná één herkansing: {oorzaak}")
        self.label = label


def is_verbroken_verbinding(exc: BaseException) -> bool:
    """Herkent een weggevallen/onbereikbare databaseverbinding (SQLAlchemy-wrapper óf ruwe DBAPI-fout);
    nooit een gewone SQL-/integriteitsfout — die verdient geen herkansing."""
    keten: list[BaseException] = []
    huidige: BaseException | None = exc
    while huidige is not None and huidige not in keten:
        keten.append(huidige)
        huidige = huidige.__cause__ or huidige.__context__
    for fout in keten:
        if isinstance(fout, DBAPIError) and fout.connection_invalidated:
            return True
        naam = type(fout).__name__
        if naam in {"OperationalError", "InterfaceError"}:
            tekst = str(fout).lower()
            if any(fragment in tekst for fragment in _VERBROKEN_FRAGMENTEN):
                return True
    return False


def voer_uit_met_herkansing[T](
    fn: Callable[[], T],
    *,
    label: str,
    wacht_seconds: float = HERKANSING_WACHT_SECONDS,
    slaap: Callable[[float], None] = time.sleep,
    voor_herkansing: Callable[[], None] | None = None,
) -> tuple[T, bool]:
    """Voer `fn` uit; bij een verbroken verbinding precies één herkansing ná `wacht_seconds`. Geeft
    (resultaat, herkanst). Andere fouten gaan ongewijzigd door; een tweede verbindingsfout wordt
    `VerbindingVerbroken`. `voor_herkansing` draait vlak vóór de tweede poging (bv. een rapport-telling
    terugzetten die de eerste poging al deels had bijgewerkt)."""
    try:
        return fn(), False
    except Exception as exc:  # noqa: BLE001 — classificatie direct hieronder, alles anders gaat door
        if not is_verbroken_verbinding(exc):
            raise
        logger.warning(
            "Databaseverbinding verbroken bij %s (%s: %s) — één herkansing na %.0f s",
            label,
            type(exc).__name__,
            str(exc).splitlines()[0] if str(exc) else "",
            wacht_seconds,
        )
    if wacht_seconds > 0:
        slaap(wacht_seconds)
    if voor_herkansing is not None:
        voor_herkansing()
    try:
        return fn(), True
    except Exception as exc:  # noqa: BLE001 — zelfde classificatie
        if is_verbroken_verbinding(exc):
            raise VerbindingVerbroken(label, exc) from exc
        raise
