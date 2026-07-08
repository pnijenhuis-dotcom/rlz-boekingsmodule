from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.db.session import scoped_session, session_factory_for


def _seed_grootboekrekening(admin_engine: Engine, administratie_id: uuid.UUID, *, code: str = "4000") -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.grootboekrekening "
                "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                "VALUES (gen_random_uuid(), :aid, :code, 'Testrekening', 2, false)"
            ),
            {"aid": administratie_id, "code": code},
        )


def test_vastgoed_ziet_alleen_gekoppelde_administratie(
    vastgoed_engine: Engine, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    _seed_grootboekrekening(admin_engine, administratie_id)

    andere_administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere klant', :rlz)"),
            {"id": andere_administratie_id, "rlz": f"rlz-{andere_administratie_id}"},
        )
    _seed_grootboekrekening(admin_engine, andere_administratie_id, code="5000")

    factory = session_factory_for(vastgoed_engine)

    with scoped_session(administratie_id, session_factory=factory) as session:
        codes = session.execute(text("SELECT code FROM platform.grootboekrekening")).scalars().all()
    assert codes == ["4000"]

    with scoped_session(andere_administratie_id, session_factory=factory) as session:
        codes = session.execute(text("SELECT code FROM platform.grootboekrekening")).scalars().all()
    assert codes == ["5000"]

    # Geen scope gezet -> geen enkele rij zichtbaar (nooit "open by default").
    with scoped_session(None, session_factory=factory) as session:
        aantal = session.execute(text("SELECT count(*) FROM platform.grootboekrekening")).scalar_one()
    assert aantal == 0


def test_vastgoed_kan_niet_schrijven(vastgoed_engine: Engine, administratie_id: uuid.UUID) -> None:
    factory = session_factory_for(vastgoed_engine)
    with scoped_session(administratie_id, session_factory=factory) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            session.execute(
                text(
                    "INSERT INTO platform.grootboekrekening "
                    "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                    "VALUES (gen_random_uuid(), :aid, '9999', 'Verboden', 1, false)"
                ),
                {"aid": administratie_id},
            )
        session.rollback()
