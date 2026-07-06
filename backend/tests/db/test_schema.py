import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


def test_schemas_bestaan(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        schemas = {
            row[0]
            for row in conn.execute(
                text("SELECT schema_name FROM information_schema.schemata")
            )
        }
    assert {"platform", "boekhouding"} <= schemas


def test_gebruiker_heeft_geen_financiele_kolommen(admin_engine: Engine) -> None:
    """PII (platform.gebruiker) mag nooit financiële velden bevatten — die horen in boekhouding."""
    financial_hints = {"bedrag", "iban", "rekening", "factuur", "btw"}
    with admin_engine.connect() as conn:
        columns = {
            row[0].lower()
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'platform' AND table_name = 'gebruiker'"
                )
            )
        }
    assert columns == {
        "id",
        "naam",
        "e_mail",
        "aangemaakt_op",
        "gepseudonimiseerd_op",
        "wachtwoord_hash",
        "rol",
        "status",
    }
    assert not (columns & financial_hints)


def test_audit_event_is_append_only_voor_app_rol(admin_engine: Engine, app_engine: Engine) -> None:
    actor_id = uuid.uuid4()
    event_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol) "
                "VALUES (:id, 'Test', :mail, 'boekhouding')"
            ),
            {"id": actor_id, "mail": f"{actor_id}@test.local"},
        )
        conn.execute(
            text(
                "INSERT INTO platform.audit_event "
                "(id, actor_id, module, tabel, record_id, actie, correlatie_id) "
                "VALUES (:id, :actor_id, 'test', 'test_tabel', :record_id, 'aangemaakt', :corr)"
            ),
            {"id": event_id, "actor_id": actor_id, "record_id": uuid.uuid4(), "corr": uuid.uuid4()},
        )

    with app_engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(
            text("UPDATE platform.audit_event SET actie = 'gewijzigd' WHERE id = :id"),
            {"id": event_id},
        )
    with app_engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(text("DELETE FROM platform.audit_event WHERE id = :id"), {"id": event_id})
