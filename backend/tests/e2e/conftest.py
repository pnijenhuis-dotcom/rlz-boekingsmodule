"""Fixtures voor de echte-HTTP-e2e-tests (Vastly-port c, 2026-08-07).

De server-fixture start een uvicorn-SUBPROCESS tegen de testdatabase — geen TestClient.
Motivatie (Vastly-diagnose 2026-07-14): TestClient praat in-process ASGI en slaat h11, de
socketlaag én de echte middleware-opbouw over; live faalden writes terwijl de suite groen was.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, text

from app.config import settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def beheerder_id(admin_engine: Engine) -> uuid.UUID:
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Test-Beheerder', :mail, 'beheerder', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    return gid


@pytest.fixture
def actieve_medewerker(admin_engine: Engine) -> uuid.UUID:
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Test-Medewerker', :mail, 'boekhouding', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    return gid


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'E2E-test', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _vrije_poort() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server() -> Generator[str, None, None]:
    """Draaiende uvicorn-subprocess op een vrije poort, tegen de TESTdatabase (env-override:
    dezelfde least-privilege app-rol als de rest van de suite). De migratie-guard in de lifespan
    draait dus tegen boekhouding_test — die staat op head door de sessie-fixture."""
    poort = _vrije_poort()
    proces = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(poort), "--log-level", "warning"],
        cwd=_BACKEND_ROOT,
        env={
            **os.environ,
            "APP_DATABASE_URL": settings.test_app_database_url,
            "DATABASE_URL": settings.test_database_url,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    basis = f"http://127.0.0.1:{poort}"
    try:
        for _ in range(75):
            if proces.poll() is not None:
                uitvoer = proces.stdout.read().decode() if proces.stdout else ""
                raise RuntimeError(f"uvicorn-subprocess stierf tijdens opstarten:\n{uitvoer[-2000:]}")
            try:
                httpx.get(f"{basis}/docs", timeout=1.0)
                break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            raise RuntimeError("uvicorn-subprocess kwam niet op binnen 15 s")
        yield basis
    finally:
        proces.terminate()
        proces.wait(timeout=10)
