from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.rlz.client import RlzClient
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / "verkenning" / ".env")

UNIVERSAL_ADMIN_ID = "3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac"  # geverifieerd, verkenning/api-verkenning.md
RUBICON_ADMIN_ID = "be5e66b3-b38c-4927-85c1-670490f16e3a"  # Platform/registers/entiteiten.md


def _credentials(prefix: str) -> tuple[str, str] | None:
    username = os.environ.get(f"{prefix}_USERNAME")
    password = os.environ.get(f"{prefix}_PASSWORD")
    if not username or not password:
        return None
    return username, password


def _login(prefix: str) -> Generator[RlzClient, None, None]:
    creds = _credentials(prefix)
    if creds is None:
        pytest.skip(f"{prefix}_USERNAME/{prefix}_PASSWORD niet gevuld in verkenning/.env")
    username, password = creds
    with RlzClient(username=username, password=password) as client:
        yield client


@pytest.fixture
def blow_login() -> Generator[RlzClient, None, None]:
    yield from _login("RLZ")


@pytest.fixture
def universal_login() -> Generator[RlzClient, None, None]:
    yield from _login("UNIVERSAL")


@pytest.fixture
def testadmin_login() -> Generator[RlzClient, None, None]:
    yield from _login("TESTADMIN")


@pytest.fixture
def rubicon_login() -> Generator[RlzClient, None, None]:
    yield from _login("RUBICON")


@pytest.fixture
def blow_client(blow_login: RlzClient) -> RlzClient:
    administraties = blow_login.list_administrations()
    assert administraties, "GET Administrations gaf niets terug voor de BLOW-login"
    return blow_login.for_administration(administraties[0]["id"])


@pytest.fixture
def universal_client(universal_login: RlzClient) -> RlzClient:
    administraties = universal_login.list_administrations()
    assert administraties, "GET Administrations gaf niets terug voor de Universal-login"
    admin_id = administraties[0]["id"]
    assert admin_id == UNIVERSAL_ADMIN_ID, f"Verwachtte {UNIVERSAL_ADMIN_ID}, kreeg {admin_id}"
    return universal_login.for_administration(admin_id)


@pytest.fixture
def testadmin_client(testadmin_login: RlzClient) -> RlzClient:
    """RLZ-test-administratie ('Administratiekantoor Nijenhuis', Platform/registers/entiteiten.md)
    — de enige plek waar de schrijf-integratietests mogen schrijven."""
    administraties = testadmin_login.list_administrations()
    assert administraties, "GET Administrations gaf niets terug voor de TESTADMIN-login"
    return testadmin_login.for_administration(administraties[0]["id"])


@pytest.fixture
def rubicon_client(rubicon_login: RlzClient) -> RlzClient:
    administraties = rubicon_login.list_administrations()
    assert administraties, "GET Administrations gaf niets terug voor de RUBICON-login"
    admin_id = administraties[0]["id"]
    assert admin_id == RUBICON_ADMIN_ID, f"Verwachtte {RUBICON_ADMIN_ID}, kreeg {admin_id}"
    return rubicon_login.for_administration(admin_id)
