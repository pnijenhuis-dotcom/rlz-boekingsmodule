from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

VASTGOED_ROLE = "vastgoed_app"
VASTGOED_WACHTWOORD = "test-only-wachtwoord"  # lokale testdatabase, geen echt geheim


class FakeRlzClient:
    """Duck-typed vervanger van RlzClient voor sync-unittests — geen echte HTTP-calls. Alleen
    `.get(path)` en `.close()` worden door de sync-servicelaag gebruikt."""

    def __init__(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self._data = data
        self.closed = False
        self.opgevraagde_paden: list[str] = []

    def get(self, path: str) -> dict[str, Any]:
        self.opgevraagde_paden.append(path)
        return {"value": self._data.get(path, [])}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def vastgoed_engine(admin_engine: Engine) -> Generator[Engine, None, None]:
    """Simuleert vastgoed's eigen leesrol (koppelcontract §2c). Lokaal draaien alleen RLZ's eigen
    migraties, dus migratie 0005's voorwaardelijke GRANT aan vastgoed_app is hier een no-op —
    deze fixture maakt de rol expliciet aan en herhaalt exact dezelfde GRANTs, zodat de test het
    geïmplementeerde leespatroon (SELECT-only + RLS) daadwerkelijk uitoefent, niet alleen de
    voorwaardelijke migratielogica op zich."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{VASTGOED_ROLE}') THEN
                        CREATE ROLE {VASTGOED_ROLE} LOGIN PASSWORD '{VASTGOED_WACHTWOORD}';
                    END IF;
                END
                $$
                """
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA platform TO {VASTGOED_ROLE}"))
        conn.execute(text(f"GRANT SELECT ON platform.grootboekrekening TO {VASTGOED_ROLE}"))
        conn.execute(text(f"GRANT EXECUTE ON FUNCTION platform.current_administratie_id() TO {VASTGOED_ROLE}"))

    vastgoed_url = admin_engine.url.set(username=VASTGOED_ROLE, password=VASTGOED_WACHTWOORD)
    engine = create_engine(vastgoed_url)
    yield engine
    engine.dispose()
