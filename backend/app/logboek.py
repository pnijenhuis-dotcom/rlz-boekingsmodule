"""Logboek — gestructureerde JSON-logregels naar stderr, zodat Cloud Run ze als `jsonPayload` opneemt.

Aanleiding (nameting 22-09, rapport `docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md`): het
meetrecept "Server-Timing `checks.extern` p50/p95 via `jsonPayload.message="server_timing"`" (Boeken sneller 18-09)
was in productie niet uitvoerbaar — `logger.info("server_timing", extra=…)` in `app.documenten.router` bereikte
Cloud Logging nooit, want de `app`-loggers hadden geen handler en de root-logger stond op de Python-default WARNING.
Alleen uvicorn's eigen access-log (textPayload "INFO: … HTTP/1.1 200 OK") was zichtbaar. Regel: een meetrecept dat
een logregel noemt is pas af als die logregel in productie aantoonbaar aankomt.

Wat dit doet (bewust minimaal):
- één `StreamHandler` op **stderr** (nooit stdout: de CLI-jobs printen hun rapport op stdout en tests toetsen
  `capsys.out`) mét een JSON-formatter — Cloud Run leest een JSON-regel op stdout/stderr als `jsonPayload` en neemt
  `severity`/`message` over; `extra=`-velden (route, document_id, stappen_ms, …) worden eigen `jsonPayload`-sleutels;
- root-logger op WARNING (bibliotheken zoals httpx/sqlalchemy blijven stil), de `app`-logger op INFO;
- idempotent (handler heeft een naam; een tweede aanroep voegt niets toe), aangeroepen bij het importeren van
  `app.main` (service) en in `app.cli.main` (jobs — óók de `boek_wachtrij_afgerond.stappen_ms`-regel van de
  achtergrond-schrijver).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import IO, Any

HANDLER_NAAM = "rlz-json-logboek"
APP_LOGGER = "app"

_STANDAARD_ATTRIBUTEN = frozenset(logging.LogRecord("x", logging.INFO, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Één JSON-object per regel: severity, message, logger, time + álle `extra=`-velden van de record."""

    def format(self, record: logging.LogRecord) -> str:
        regel: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        }
        for sleutel, waarde in record.__dict__.items():
            if sleutel in _STANDAARD_ATTRIBUTEN or sleutel.startswith("_") or sleutel in regel:
                continue
            regel[sleutel] = waarde
        if record.exc_info:
            regel["exception"] = self.formatException(record.exc_info)
        return json.dumps(regel, default=str, ensure_ascii=False)


def _bestaande_handler(root: logging.Logger) -> logging.Handler | None:
    for handler in root.handlers:
        if handler.get_name() == HANDLER_NAAM:
            return handler
    return None


def configureer_logboek(stream: IO[str] | None = None) -> logging.Handler:
    """Zet de JSON-handler op de root-logger (idempotent) en de niveaus: root WARNING, `app` INFO. `stream` alleen voor
    tests; default stderr. Geeft de actieve handler terug."""
    root = logging.getLogger()
    bestaande = _bestaande_handler(root)
    if bestaande is not None:
        if stream is None:
            return bestaande
        root.removeHandler(bestaande)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(HANDLER_NAAM)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.WARNING:
        root.setLevel(logging.WARNING)
    app_logger = logging.getLogger(APP_LOGGER)
    if app_logger.level == logging.NOTSET or app_logger.level > logging.INFO:
        app_logger.setLevel(logging.INFO)
    return handler


def verwijder_logboek() -> None:
    """Tests: handler weer weghalen."""
    root = logging.getLogger()
    bestaande = _bestaande_handler(root)
    if bestaande is not None:
        root.removeHandler(bestaande)
