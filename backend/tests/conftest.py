from __future__ import annotations

import re
import sys
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from app.config import settings

REQUIRED_PYTHON = (3, 12)
REQUIRED_POSTGRES_MAJOR = 16
BACKEND_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def pytest_configure(config: pytest.Config) -> None:
    """Harde versie-pariteitscheck met productie — zie README.md 'Vereiste versies'.

    Lokaal nieuwer dan productie (Cloud Run pint 3.12, Cloud SQL pint PostgreSQL 16) is de
    gevaarlijke richting: iets dat hier werkt kan daar alsnog stuklopen. Faalt de hele testrun
    dus hard i.p.v. een losse test te laten falen, zodat de oorzaak meteen duidelijk is.
    """
    if sys.version_info[:2] != REQUIRED_PYTHON:
        pytest.exit(
            f"Python {'.'.join(map(str, REQUIRED_PYTHON))} vereist (pint de Cloud Run-container) "
            f"— deze interpreter is {sys.version.split()[0]}. Bouw de venv met "
            f"'make install' (of 'python3.12 -m venv .venv').",
            returncode=1,
        )

    engine = create_engine(settings.test_database_url)
    try:
        with engine.connect() as conn:
            version_string = conn.execute(text("SHOW server_version")).scalar_one()
    except Exception as exc:
        pytest.exit(
            f"Kan niet verbinden met {settings.test_database_url}: {exc}\n"
            f"Draait PostgreSQL 16 op poort 5433? Zie README.md ('make pg16-start').",
            returncode=1,
        )
    finally:
        engine.dispose()

    match = re.match(r"(\d+)", version_string)
    major = int(match.group(1)) if match else None
    if major != REQUIRED_POSTGRES_MAJOR:
        pytest.exit(
            f"PostgreSQL {REQUIRED_POSTGRES_MAJOR} vereist (pint Cloud SQL-productie) — "
            f"{settings.test_database_url} draait versie {version_string}.",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_database() -> None:
    """Reset boekhouding_test naar een schone, volledig gemigreerde staat vóór de testrun."""
    alembic_cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    import os

    os.environ["DATABASE_URL"] = settings.test_database_url
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(autouse=True)
def _clean_tables() -> Generator[None, None, None]:
    """Leegt de tabellen vóór elke test — de migratie zelf draait maar één keer per sessie
    (`_migrated_test_database`), dus zonder dit lekt data van de ene test naar de volgende."""
    engine = create_engine(settings.test_database_url)
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE TABLE platform.audit_event, platform.administratie, platform.gebruiker CASCADE")
        )
    engine.dispose()
    yield


@pytest.fixture
def admin_engine() -> Generator[Engine, None, None]:
    """Verbinding als schema-owner (migratierol) — voor testopzet/assertions op DDL-niveau."""
    engine = create_engine(settings.test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine() -> Generator[Engine, None, None]:
    """Verbinding als de least-privilege runtime-rol `boekhouding_app`, onderhevig aan RLS."""
    engine = create_engine(settings.test_app_database_url)
    yield engine
    engine.dispose()
