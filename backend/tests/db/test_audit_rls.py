import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.db.audit import record_audit_event
from app.db.session import scoped_session, session_factory_for


@pytest.fixture
def two_administraties(admin_engine: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Twee administraties + één gebruiker (actor), rechtstreeks aangemaakt als schema-owner."""
    admin_a, admin_b, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES "
                "(:a, 'Administratie A', :a_rlz), (:b, 'Administratie B', :b_rlz)"
            ),
            {"a": admin_a, "a_rlz": f"rlz-{admin_a}", "b": admin_b, "b_rlz": f"rlz-{admin_b}"},
        )
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol) "
                "VALUES (:id, 'Actor', :mail, 'boekhouding')"
            ),
            {"id": actor, "mail": f"{actor}@test.local"},
        )
    return admin_a, admin_b, actor


def test_rls_toont_alleen_eigen_administratie_plus_platformbreed(
    app_engine: Engine, two_administraties: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    admin_a, admin_b, actor = two_administraties
    factory = session_factory_for(app_engine)

    with scoped_session(admin_a, session_factory=factory) as session:
        record_audit_event(
            session,
            actor_id=actor,
            module="test",
            tabel="test_tabel",
            record_id=uuid.uuid4(),
            actie="aangemaakt",
            correlatie_id=uuid.uuid4(),
            administratie_id=admin_a,
        )
    with scoped_session(admin_b, session_factory=factory) as session:
        record_audit_event(
            session,
            actor_id=actor,
            module="test",
            tabel="test_tabel",
            record_id=uuid.uuid4(),
            actie="aangemaakt",
            correlatie_id=uuid.uuid4(),
            administratie_id=admin_b,
        )
    with scoped_session(None, session_factory=factory) as session:
        record_audit_event(
            session,
            actor_id=actor,
            module="test",
            tabel="test_tabel",
            record_id=uuid.uuid4(),
            actie="platform-event",
            correlatie_id=uuid.uuid4(),
            administratie_id=None,
        )

    with scoped_session(admin_a, session_factory=factory) as session:
        acties = {row[0] for row in session.execute(text("SELECT actie FROM platform.audit_event"))}
    # Ziet het eigen event (admin_a) + het platformbrede event, NIET dat van admin_b.
    assert acties == {"aangemaakt", "platform-event"}
    with scoped_session(admin_a, session_factory=factory) as session:
        admin_ids = {
            row[0]
            for row in session.execute(
                text("SELECT administratie_id FROM platform.audit_event WHERE administratie_id IS NOT NULL")
            )
        }
    assert admin_ids == {admin_a}


def test_rls_zonder_scope_toont_alleen_platformbreed(
    app_engine: Engine, two_administraties: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    admin_a, admin_b, actor = two_administraties
    factory = session_factory_for(app_engine)

    with scoped_session(admin_a, session_factory=factory) as session:
        record_audit_event(
            session,
            actor_id=actor,
            module="test",
            tabel="test_tabel",
            record_id=uuid.uuid4(),
            actie="aangemaakt",
            correlatie_id=uuid.uuid4(),
            administratie_id=admin_a,
        )

    with scoped_session(None, session_factory=factory) as session:
        rows = session.execute(text("SELECT actie FROM platform.audit_event")).all()
    assert rows == []


def test_rls_blokkeert_schrijven_buiten_scope(
    app_engine: Engine, two_administraties: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """WITH CHECK moet een insert weigeren die beweert bij een andere administratie te horen
    dan de actieve scope — anders kan een lek in de applicatielaag alsnog cross-tenant schrijven."""
    admin_a, admin_b, actor = two_administraties
    factory = session_factory_for(app_engine)

    with scoped_session(admin_a, session_factory=factory) as session:
        with pytest.raises(DBAPIError, match="row-level security"):
            record_audit_event(
                session,
                actor_id=actor,
                module="test",
                tabel="test_tabel",
                record_id=uuid.uuid4(),
                actie="stiekem-voor-b",
                correlatie_id=uuid.uuid4(),
                administratie_id=admin_b,
            )
        session.rollback()
