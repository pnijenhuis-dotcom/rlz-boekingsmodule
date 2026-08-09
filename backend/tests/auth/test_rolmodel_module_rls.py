"""DB-niveau-gedrag van het rolmodel-fundament per module (besluit 0019, migratie 0034):
gebruiker_module_rol + gebruiker_entiteit. Getest via de echte app-rol (`app_engine` =
boekhouding_app, non-superuser) zodat RLS en de audit-triggers écht handhaven — dit is
autorisatie op geld-dragende data, dus test-verplicht vóór UI.

Bootstrap-nuance: de eerste module-beheerder (vastgoed-superadmin) kan alleen via de
schema-eigenaar worden gezet (RLS ENABLE zonder FORCE op gebruiker_module_rol) — precies wat
`admin_engine` hier doet en wat in productie een beheerde seed is."""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.auth import service
from app.db.models import GebruikerRol
from app.db.session import scoped_session, session_factory_for

_INSERT_ROL = "INSERT INTO platform.gebruiker_module_rol (gebruiker_id, module, rol) VALUES (:g, :m, :r)"


def _nieuwe_gebruiker(beheerder_id: uuid.UUID, naam: str) -> uuid.UUID:
    return service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam=naam,
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[],
    ).gebruiker_id


def _seed_superadmin(admin_engine: Engine, beheerder_id: uuid.UUID, gebruiker_id: uuid.UUID) -> None:
    """Bootstrap-pad: schema-eigenaar zet de eerste vastgoed-superadmin (audit-trigger eist een
    actor, dus ook de seed draait met gezette actor-context)."""
    with admin_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_actor_id', :a, true)"), {"a": str(beheerder_id)})
        conn.execute(
            text(_INSERT_ROL),
            {"g": gebruiker_id, "m": "vastgoed", "r": "superadmin"},
        )


class TestGebruikerModuleRol:
    def test_check_constraint_weigert_onbekende_module_en_rol(
        self, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        doel = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'X', :m, 'boekhouding', 'actief')"
                ),
                {"id": doel, "m": f"{doel}@test.local"},
            )
        for module, rol in (("vastgoed", "directeur"), ("onbekend", "superadmin")):
            with admin_engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.current_actor_id', :a, true)"), {"a": str(beheerder_id)})
                with pytest.raises(DBAPIError, match="ck_gebruiker_module_rol_geldig"):
                    conn.execute(
                        text(_INSERT_ROL),
                        {"g": doel, "m": module, "r": rol},
                    )

    def test_niet_beheerder_kan_geen_module_rol_inserten(
        self, app_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        doel = _nieuwe_gebruiker(beheerder_id, "Doelwit")
        factory = session_factory_for(app_engine)
        with scoped_session(uuid.uuid4(), actor_id=doel, session_factory=factory) as session:
            with pytest.raises(DBAPIError, match="row-level security"):
                session.execute(
                    text(_INSERT_ROL),
                    {"g": doel, "m": "vastgoed", "r": "eigenaar"},
                )
            session.rollback()

    def test_superadmin_beheert_andermans_rol_maar_nooit_zijn_eigen(
        self, app_engine: Engine, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        superadmin = _nieuwe_gebruiker(beheerder_id, "Vastgoed-superadmin")
        doel = _nieuwe_gebruiker(beheerder_id, "Vastgoed-eigenaar")
        _seed_superadmin(admin_engine, beheerder_id, superadmin)

        factory = session_factory_for(app_engine)
        # Andermans rol zetten: mag.
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            session.execute(
                text(_INSERT_ROL),
                {"g": doel, "m": "vastgoed", "r": "eigenaar"},
            )
            session.commit()
        # Eigen rol muteren (verwijderen): nooit — ook een module-beheerder niet (besluit 0019).
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            resultaat = session.execute(
                text("DELETE FROM platform.gebruiker_module_rol WHERE gebruiker_id = :g AND module = 'vastgoed'"),
                {"g": superadmin},
            )
            assert resultaat.rowcount == 0  # RLS filtert de eigen rij weg: stil geen effect
            session.rollback()

    def test_audit_event_bij_module_rol_mutaties(
        self, app_engine: Engine, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        superadmin = _nieuwe_gebruiker(beheerder_id, "Auditeur")
        doel = _nieuwe_gebruiker(beheerder_id, "Geaudit-doel")
        _seed_superadmin(admin_engine, beheerder_id, superadmin)

        factory = session_factory_for(app_engine)
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            session.execute(
                text(_INSERT_ROL),
                {"g": doel, "m": "vastgoed", "r": "kantoor"},
            )
            session.execute(
                text("DELETE FROM platform.gebruiker_module_rol WHERE gebruiker_id = :g AND module = 'vastgoed'"),
                {"g": doel},
            )
            session.commit()
        with admin_engine.connect() as conn:
            acties = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'gebruiker_module_rol' "
                        "AND record_id = :g ORDER BY tijdstip"
                    ),
                    {"g": doel},
                )
            ]
        assert acties == ["module_rol_toegevoegd", "module_rol_verwijderd"]

    def test_mutatie_zonder_actor_context_faalt_hard(self, admin_engine: Engine, beheerder_id: uuid.UUID) -> None:
        doel = _nieuwe_gebruiker(beheerder_id, "Zonder-actor")
        with admin_engine.begin() as conn, pytest.raises(DBAPIError, match="current_actor_id niet gezet"):
            conn.execute(
                text(_INSERT_ROL),
                {"g": doel, "m": "vastgoed", "r": "kantoor"},
            )


@pytest.fixture
def vastgoed_rol_engine(admin_engine: Engine) -> Generator[Engine, None, None]:
    """Simuleert vastgoed's app-rol voor de nieuwe rolmodel-tabellen. Lokaal draaien alleen
    RLZ's migraties, dus de voorwaardelijke GRANT in migratie 0034 is hier een no-op — deze
    fixture maakt de rol aan en herhaalt exact dezelfde GRANTs (zelfde patroon als
    tests/sync/conftest.py::vastgoed_engine voor migratie 0005)."""
    rol, wachtwoord = "vastgoed_app", "test-only-wachtwoord"
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{rol}') THEN
                        CREATE ROLE {rol} LOGIN PASSWORD '{wachtwoord}';
                    END IF;
                END
                $$
                """
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA platform TO {rol}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.gebruiker_module_rol TO {rol}"))
        conn.execute(text(f"GRANT SELECT, INSERT, DELETE ON platform.gebruiker_entiteit TO {rol}"))
        conn.execute(text(f"GRANT EXECUTE ON FUNCTION platform.current_actor_id() TO {rol}"))
        conn.execute(text(f"GRANT EXECUTE ON FUNCTION platform.actor_is_module_beheerder(text) TO {rol}"))
    engine = create_engine(admin_engine.url.set(username=rol, password=wachtwoord))
    yield engine
    engine.dispose()


class TestGebruikerEntiteit:
    def test_scope_zetten_alleen_door_module_beheerder_en_nooit_op_zichzelf(
        self, vastgoed_rol_engine: Engine, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        superadmin = _nieuwe_gebruiker(beheerder_id, "Scope-superadmin")
        eigenaar = _nieuwe_gebruiker(beheerder_id, "Scope-eigenaar")
        _seed_superadmin(admin_engine, beheerder_id, superadmin)
        entiteit = uuid.uuid4()

        factory = session_factory_for(vastgoed_rol_engine)
        # Niet-beheerder: geweigerd.
        with scoped_session(uuid.uuid4(), actor_id=eigenaar, session_factory=factory) as session:
            with pytest.raises(DBAPIError, match="row-level security"):
                session.execute(
                    text("INSERT INTO platform.gebruiker_entiteit (gebruiker_id, entiteit_id) VALUES (:g, :e)"),
                    {"g": eigenaar, "e": entiteit},
                )
            session.rollback()
        # Superadmin op een ander: mag; op zichzelf: geweigerd.
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            session.execute(
                text("INSERT INTO platform.gebruiker_entiteit (gebruiker_id, entiteit_id) VALUES (:g, :e)"),
                {"g": eigenaar, "e": entiteit},
            )
            session.commit()
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            with pytest.raises(DBAPIError, match="row-level security"):
                session.execute(
                    text("INSERT INTO platform.gebruiker_entiteit (gebruiker_id, entiteit_id) VALUES (:g, :e)"),
                    {"g": superadmin, "e": entiteit},
                )
            session.rollback()

    def test_gebruiker_leest_alleen_eigen_scope(
        self, vastgoed_rol_engine: Engine, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        superadmin = _nieuwe_gebruiker(beheerder_id, "Lees-superadmin")
        eigenaar_a = _nieuwe_gebruiker(beheerder_id, "Eigenaar A")
        eigenaar_b = _nieuwe_gebruiker(beheerder_id, "Eigenaar B")
        _seed_superadmin(admin_engine, beheerder_id, superadmin)
        factory = session_factory_for(vastgoed_rol_engine)
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            for wie in (eigenaar_a, eigenaar_b):
                session.execute(
                    text("INSERT INTO platform.gebruiker_entiteit (gebruiker_id, entiteit_id) VALUES (:g, :e)"),
                    {"g": wie, "e": uuid.uuid4()},
                )
            session.commit()

        with scoped_session(uuid.uuid4(), actor_id=eigenaar_a, session_factory=factory) as session:
            zichtbaar = session.execute(
                text("SELECT gebruiker_id FROM platform.gebruiker_entiteit WHERE gebruiker_id IN (:a, :b)"),
                {"a": eigenaar_a, "b": eigenaar_b},
            ).fetchall()
        assert {r[0] for r in zichtbaar} == {eigenaar_a}
        # De module-beheerder ziet wél alles (beheer-UI).
        with scoped_session(uuid.uuid4(), actor_id=superadmin, session_factory=factory) as session:
            alles = session.execute(
                text("SELECT gebruiker_id FROM platform.gebruiker_entiteit WHERE gebruiker_id IN (:a, :b)"),
                {"a": eigenaar_a, "b": eigenaar_b},
            ).fetchall()
        assert {r[0] for r in alles} == {eigenaar_a, eigenaar_b}
