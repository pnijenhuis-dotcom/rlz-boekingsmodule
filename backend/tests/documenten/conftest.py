from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.config import settings
from app.documenten.storage import LokaleBestandsopslag
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401


@pytest.fixture(autouse=True)
def _opslag_naar_tmp(tmp_path: Path) -> None:
    """De router gebruikt service._standaard_opslag() (settings.document_opslag_basismap) —
    zonder dit zou een HTTP-niveau uploadtest echt naar backend/.data/documenten schrijven i.p.v.
    een tijdelijke testmap."""
    settings.document_opslag_basismap = str(tmp_path / "documenten")


@pytest.fixture
def gescoopte_gebruiker(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
) -> uuid.UUID:
    """Een ACTIEVE, niet-Beheerder gebruiker met scope op `administratie_id` — voor upload-/
    RLS-tests. Rechtstreeks als actief aangemaakt (zoals beheerder_id in tests/auth/conftest.py)
    omdat de volledige uitnodig-/TOTP-flow hier niet de kern van de test is; scope erna via de
    servicelaag (niet rechtstreeks SQL) zodat de audit-trigger een gezette actor krijgt."""
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Boekhouder', :mail, 'boekhouding', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
    return gid


@pytest.fixture
def opslag(tmp_path: Path) -> LokaleBestandsopslag:
    return LokaleBestandsopslag(tmp_path / "documenten")
