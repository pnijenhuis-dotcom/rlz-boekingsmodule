from __future__ import annotations

import pytest
from sqlalchemy import Engine

from tests.aitoets.stub import StubPlausibiliteitClient, zet_ai_toets_stub, zet_intake_ai
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401


@pytest.fixture
def ai_aan(admin_engine: Engine) -> None:
    """AVG-gate open (intake_instelling.ai_ingeschakeld = true) — in de testdatabase staat hij standaard UIT."""
    zet_intake_ai(admin_engine, True)


@pytest.fixture
def ai_stub(monkeypatch) -> StubPlausibiliteitClient:
    return zet_ai_toets_stub(monkeypatch)
