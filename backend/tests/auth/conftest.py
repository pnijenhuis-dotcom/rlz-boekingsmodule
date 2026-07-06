from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.config import settings


@pytest.fixture(scope="session", autouse=True)
def _service_layer_gebruikt_testdatabase() -> Generator[None, None, None]:
    """app.auth.service roept scoped_session() aan zonder expliciete session_factory — dat
    gebruikt standaard de dev-/productie-engine (settings.app_database_url). Voor deze tests
    wordt die tijdelijk vervangen door de testdatabase-engine (least-privilege boekhouding_app-
    rol, zelfde als app_engine), zodat de auth-servicelaag daadwerkelijk tegen boekhouding_test
    draait — en meteen ook non-superuser is, zoals de RLS-tests vereisen."""
    test_engine = create_engine(settings.test_app_database_url, pool_pre_ping=True)
    origineel_engine, origineel_factory = db_session.engine, db_session.SessionLocal
    db_session.engine = test_engine
    db_session.SessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)
    yield
    db_session.engine = origineel_engine
    db_session.SessionLocal = origineel_factory
    test_engine.dispose()


@pytest.fixture
def beheerder_id(admin_engine: Engine) -> uuid.UUID:
    """Bootstrapt een actieve Beheerder rechtstreeks als schema-owner. In de praktijk is er nog
    geen 'nodig een eerste Beheerder uit'-mechanisme (kip-ei-probleem) — open item, zie
    eindrapport."""
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
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Scope-test', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid
