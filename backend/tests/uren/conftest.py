from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.uren import service as uren_service
from tests.auth.conftest import beheerder_id  # noqa: F401


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    """Administratie MÉT de uren-&-meerwerk-opt-in aan (het Universal-scenario)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, uren_meerwerk_ingeschakeld) "
                "VALUES (:id, 'Universal Steigerbouw (test)', :rlz, true)"
            ),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def administratie_zonder_opt_in(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id) "
                "VALUES (:id, 'Zonder opt-in (test)', :rlz)"
            ),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def maak_project(admin_engine: Engine, administratie_id: uuid.UUID, naam: str) -> uuid.UUID:
    pid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_cache (id, administratie_id, naam, is_actief, brondata) "
                "VALUES (:id, :aid, :naam, true, '{}')"
            ),
            {"id": pid, "aid": administratie_id, "naam": naam},
        )
    return pid


@pytest.fixture
def project_id(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    return maak_project(admin_engine, administratie_id, "26014 Eindhoven (BAM)")


@pytest.fixture
def tweede_project_id(admin_engine: Engine, administratie_id: uuid.UUID) -> uuid.UUID:
    return maak_project(admin_engine, administratie_id, "26021 Tilburg (Heijmans)")


def maak_gebruiker(admin_engine: Engine, rol: str, naam: str) -> uuid.UUID:
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, :naam, :mail, :rol, 'actief')"
            ),
            {"id": gid, "naam": naam, "mail": f"{gid}@test.local", "rol": rol},
        )
    return gid


@pytest.fixture
def zzper(admin_engine: Engine) -> uuid.UUID:
    return maak_gebruiker(admin_engine, "zzper", "Milan K.")


@pytest.fixture
def uitvoerder(admin_engine: Engine) -> uuid.UUID:
    return maak_gebruiker(admin_engine, "uitvoerder", "Ben v. Dijk")


@pytest.fixture
def detacheerder(admin_engine: Engine) -> uuid.UUID:
    return maak_gebruiker(admin_engine, "detacheerder", "Karin S.")


@pytest.fixture
def gekoppelde_zzper(
    zzper: uuid.UUID, administratie_id: uuid.UUID, project_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
) -> uuid.UUID:
    uren_service.koppel_project(
        administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, actor_id=beheerder_id
    )
    return zzper


@pytest.fixture
def gekoppelde_uitvoerder(
    uitvoerder: uuid.UUID, administratie_id: uuid.UUID, project_id: uuid.UUID, beheerder_id: uuid.UUID  # noqa: F811
) -> uuid.UUID:
    uren_service.koppel_project(
        administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_id, actor_id=beheerder_id
    )
    return uitvoerder
