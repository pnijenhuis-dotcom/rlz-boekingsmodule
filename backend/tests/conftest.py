from __future__ import annotations

import re
import sys
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

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


@pytest.fixture(scope="session", autouse=True)
def _service_layer_gebruikt_testdatabase() -> Generator[None, None, None]:
    """Elke `app.*.service`-module roept scoped_session() aan zonder expliciete session_factory —
    dat gebruikt standaard de dev-/productie-engine (settings.app_database_url). Voor de hele
    testrun wordt die tijdelijk vervangen door de testdatabase-engine (least-privilege
    boekhouding_app-rol, zelfde als app_engine), zodat ALLE servicelagen (auth, documenten, ...)
    daadwerkelijk tegen boekhouding_test draaien — en meteen ook non-superuser zijn, zoals de
    RLS-tests vereisen. Op tests/-rootniveau (niet alleen tests/auth/): elk nieuw service-module
    onder tests/<naam>/ heeft dit anders zelf moeten herhalen."""
    test_engine = create_engine(settings.test_app_database_url, pool_pre_ping=True)
    origineel_engine, origineel_factory = db_session.engine, db_session.SessionLocal
    db_session.engine = test_engine
    db_session.SessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)
    yield
    db_session.engine = origineel_engine
    db_session.SessionLocal = origineel_factory
    test_engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables() -> Generator[None, None, None]:
    """Leegt de tabellen vóór elke test — de migratie zelf draait maar één keer per sessie
    (`_migrated_test_database`), dus zonder dit lekt data van de ene test naar de volgende.

    `platform.gebruiker CASCADE` vaagt ook `platform.boeken_instelling` weg (de kill-switch-
    singleton heeft een nullable FK naar gebruiker via `gewijzigd_door`) — die rij hoort echter
    net als een migratie-seed altijd te bestaan (migratie 0008 zet 'm precies één keer), dus wordt
    'm hier hersteld i.p.v. per boeken-test opnieuw te moeten aanmaken. Zelfde geldt voor de
    systeem-actor (migratie 0016): de truncate wist de geseedde rij, en zonder die rij falen de
    FK's van elke worker-statusovergang."""
    engine = create_engine(settings.test_database_url)
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE TABLE platform.audit_event, platform.administratie, platform.gebruiker CASCADE")
        )
        conn.execute(
            text(
                "INSERT INTO platform.boeken_instelling (singleton, globaal_ingeschakeld) VALUES (true, true) "
                "ON CONFLICT (singleton) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Systeem (achtergrondverwerking)', 'systeem@platform.intern', "
                "'boekhouding', 'geblokkeerd') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": str(SYSTEEM_ACTOR_ID)},
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
