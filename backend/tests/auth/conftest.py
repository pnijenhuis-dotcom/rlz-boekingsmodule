from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import dataclass

import pyotp
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.auth import service
from app.config import settings
from app.db.models import GebruikerRol


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


@dataclass(frozen=True)
class ActieveGebruiker:
    """Volledig geactiveerde gebruiker (uitgenodigd -> wachtwoord -> TOTP bevestigd) — herbruikbaar
    voor tests die daadwerkelijk moeten inloggen (login()/vernieuw_token()), i.p.v. de kortere
    `_bearer()`-shortcut die alleen een access-token nodig heeft."""

    id: uuid.UUID
    e_mail: str
    wachtwoord: str
    secret: str


@pytest.fixture
def actieve_gebruiker(beheerder_id: uuid.UUID) -> ActieveGebruiker:
    e_mail = f"{uuid.uuid4()}@test.local"
    wachtwoord = "een-heel-lang-wachtwoord"
    resultaat = service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam="Actieve Gebruiker",
        e_mail=e_mail,
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )
    acceptatie = service.accepteer_uitnodiging(token=resultaat.token, wachtwoord=wachtwoord)
    code = pyotp.TOTP(acceptatie.secret).now()
    service.bevestig_totp(totp_setup_token=acceptatie.totp_setup_token, code=code)
    return ActieveGebruiker(id=resultaat.gebruiker_id, e_mail=e_mail, wachtwoord=wachtwoord, secret=acceptatie.secret)


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Scope-test', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid
