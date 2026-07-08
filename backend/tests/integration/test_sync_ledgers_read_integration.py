"""Sync-integratietest, read-only tegen de RLZ-test-administratie ('Administratiekantoor
Nijenhuis', Platform/registers/entiteiten.md). Alleen GET Ledgers wordt aangeroepen — er wordt
niets naar RLZ geschreven. `read_integration`-marker (net als write_integration) houdt 'm buiten
de kale run, zie pyproject.toml."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.rlz.client import RlzClient
from app.sync import service

pytestmark = pytest.mark.read_integration

TESTADMIN_RLZ_ADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
RUBICON_RLZ_ADMIN_ID = "be5e66b3-b38c-4927-85c1-670490f16e3a"


def test_sync_ledgers_tegen_testadministratie(testadmin_client: RlzClient, admin_engine: Engine) -> None:
    administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Testadmin', :rlz)"),
            {"id": administratie_id, "rlz": TESTADMIN_RLZ_ADMIN_ID},
        )

    telling = service.sync_ledgers(administratie_id=administratie_id, client=testadmin_client)
    assert telling.aangemaakt > 0

    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.grootboekrekening WHERE administratie_id = :aid"),
            {"aid": administratie_id},
        ).scalar_one()
    assert aantal == telling.aangemaakt


def test_sync_ledgers_tegen_rubicon(rubicon_client: RlzClient, admin_engine: Engine) -> None:
    """Overbrugging vastgoed (Platform/OPEN_ITEMS.md 'Grootboek-koppeling'): bevestigt dat de
    sync-mechaniek ook echt tegen Rubicons administratie werkt, vóór de gedeelde Cloud SQL er is.
    Repeatable — dit is exact de route waarmee de rubicon_ledgers_<datum>.json-export (zie
    Platform/uitwisseling/) is geproduceerd en later opnieuw gegenereerd kan worden."""
    administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Rubicon', :rlz)"),
            {"id": administratie_id, "rlz": RUBICON_RLZ_ADMIN_ID},
        )

    telling = service.sync_ledgers(administratie_id=administratie_id, client=rubicon_client)
    assert telling.aangemaakt > 0

    with admin_engine.connect() as conn:
        aantal = conn.execute(
            text("SELECT count(*) FROM platform.grootboekrekening WHERE administratie_id = :aid"),
            {"aid": administratie_id},
        ).scalar_one()
    assert aantal == telling.aangemaakt
