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
    """Duck-typed vervanger van RlzClient voor sync-/credentialstore-unittests — geen echte
    HTTP-calls. `.get(path)`, `.close()` en `.for_administration(admin_id)` worden gebruikt
    (de laatste door de rechten-probe, die een root- en een gescoped client onderscheidt).
    `fouten` is een optionele {endpoint: Exception}-map om 403's etc. te simuleren."""

    def __init__(
        self, data: dict[str, list[dict[str, Any]]], *, fouten: dict[str, Exception] | None = None
    ) -> None:
        self._data = data
        self._fouten = fouten or {}
        self.closed = False
        self.admin_id: str | None = None
        self.opgevraagde_paden: list[str] = []

    def get(self, path: str) -> dict[str, Any]:
        self.opgevraagde_paden.append(path)
        if path in self._fouten:
            raise self._fouten[path]
        return {"value": self._data.get(path, [])}

    def for_administration(self, admin_id: str) -> FakeRlzClient:
        gescoped = FakeRlzClient(self._data, fouten=self._fouten)
        gescoped.admin_id = admin_id
        gescoped.opgevraagde_paden = self.opgevraagde_paden  # zelfde "verbinding", gedeelde log
        return gescoped

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
