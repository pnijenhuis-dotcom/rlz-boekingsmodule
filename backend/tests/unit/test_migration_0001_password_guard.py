"""Het 'devpassword'-fallback in migratie 0001 mag nooit stilzwijgend in productie belanden."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0001_initial_schema.py"
)


@pytest.fixture(scope="module")
def migration_0001() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0001_under_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dev_zonder_wachtwoord_valt_terug_op_devpassword(migration_0001: ModuleType) -> None:
    assert migration_0001._resolve_app_role_password({}) == "devpassword"
    assert migration_0001._resolve_app_role_password({"ENVIRONMENT": "local"}) == "devpassword"


def test_expliciet_wachtwoord_wint_altijd(migration_0001: ModuleType) -> None:
    assert migration_0001._resolve_app_role_password({"APP_DB_PASSWORD": "s3cret"}) == "s3cret"
    assert (
        migration_0001._resolve_app_role_password(
            {"APP_DB_PASSWORD": "s3cret", "ENVIRONMENT": "production"}
        )
        == "s3cret"
    )


@pytest.mark.parametrize("environment", ["production", "staging", "acceptatie"])
def test_faalt_hard_buiten_dev_zonder_wachtwoord(migration_0001: ModuleType, environment: str) -> None:
    with pytest.raises(RuntimeError, match="APP_DB_PASSWORD"):
        migration_0001._resolve_app_role_password({"ENVIRONMENT": environment})


def test_lege_string_telt_als_ontbrekend(migration_0001: ModuleType) -> None:
    with pytest.raises(RuntimeError, match="APP_DB_PASSWORD"):
        migration_0001._resolve_app_role_password({"APP_DB_PASSWORD": "", "ENVIRONMENT": "production"})
