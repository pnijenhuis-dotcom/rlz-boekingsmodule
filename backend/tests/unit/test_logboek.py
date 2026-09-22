"""Logboek (nameting 22-09): de `server_timing`-logregel uit `app.documenten.router` bereikte Cloud Logging nooit — de
`app`-loggers hadden geen handler en de root stond op WARNING. Deze guard bewijst dat een `app`-INFO-regel mét `extra=`
als één JSON-object (severity/message + extra-sleutels) op de stream komt, dat bibliotheek-INFO stil blijft, dat de
configuratie idempotent is én dat service (`app.main`) en jobs (`app.cli.main`) 'm aanroepen."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import logboek

APP = Path(__file__).resolve().parents[2] / "app"


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    logboek.configureer_logboek(buffer)
    try:
        yield buffer
    finally:
        logboek.verwijder_logboek()


def _regels(buffer: io.StringIO) -> list[dict]:
    return [json.loads(r) for r in buffer.getvalue().splitlines() if r.strip()]


def test_server_timing_regel_komt_als_json_met_extra_velden_aan(stream: io.StringIO) -> None:
    logging.getLogger("app.documenten.router").info(
        "server_timing",
        extra={"route": "boekvoorstel_checks", "document_id": "d-1", "stappen_ms": {"extern": 12.5, "lokaal": 3.0}},
    )
    regels = _regels(stream)
    assert len(regels) == 1
    regel = regels[0]
    assert regel["message"] == "server_timing" and regel["severity"] == "INFO"
    assert regel["logger"] == "app.documenten.router"
    assert regel["route"] == "boekvoorstel_checks" and regel["document_id"] == "d-1"
    assert regel["stappen_ms"] == {"extern": 12.5, "lokaal": 3.0}
    assert regel["time"].endswith("+00:00")


def test_bibliotheek_info_blijft_stil_maar_warning_komt_door(stream: io.StringIO) -> None:
    logging.getLogger("httpx").info("HTTP Request: GET https://apps.reeleezee.nl/… 200 OK")
    logging.getLogger("sqlalchemy.engine.Engine").info("SELECT 1")
    logging.getLogger("iets.anders").warning("let op %s", "x")
    regels = _regels(stream)
    assert [r["message"] for r in regels] == ["let op x"]
    assert regels[0]["severity"] == "WARNING"


def test_exception_reist_mee_en_niet_serialiseerbare_extra_wordt_tekst(stream: io.StringIO) -> None:
    try:
        raise ValueError("boem")
    except ValueError:
        logging.getLogger("app.x").exception("mislukt", extra={"pad": Path("/tmp/a")})
    (regel,) = _regels(stream)
    assert regel["severity"] == "ERROR" and "ValueError: boem" in regel["exception"]
    assert regel["pad"] == "/tmp/a"


def test_configureren_is_idempotent() -> None:
    eerste = logboek.configureer_logboek()
    tweede = logboek.configureer_logboek()
    try:
        root = logging.getLogger()
        assert eerste is tweede
        assert [h for h in root.handlers if h.get_name() == logboek.HANDLER_NAAM] == [eerste]
        assert logging.getLogger("app").level == logging.INFO
        assert root.level == logging.WARNING or root.level == logging.INFO  # pytest kan root al lager zetten
    finally:
        logboek.verwijder_logboek()


def test_service_en_jobs_roepen_het_logboek_aan() -> None:
    assert "configureer_logboek()" in (APP / "main.py").read_text(encoding="utf-8")
    cli = (APP / "cli.py").read_text(encoding="utf-8")
    aanroep = cli.index("configureer_logboek()")
    assert cli.index("def main(") < aanroep < cli.index('parser = argparse.ArgumentParser(prog="python -m app.cli"')


def test_handler_schrijft_default_naar_stderr_nooit_stdout() -> None:
    import sys

    handler = logboek.configureer_logboek()
    try:
        assert isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr
    finally:
        logboek.verwijder_logboek()
