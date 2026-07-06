"""Het dev-only fallback-JWT-secret mag nooit stilzwijgend in productie belanden — zelfde
patroon als test_migration_0001_password_guard.py."""

import pytest

from app.security.tokens import _resolve_jwt_secret


def test_dev_zonder_secret_valt_terug_op_dev_secret() -> None:
    assert _resolve_jwt_secret({}) == "dev-only-insecure-jwt-secret-32-bytes-min"
    assert _resolve_jwt_secret({"ENVIRONMENT": "local"}) == "dev-only-insecure-jwt-secret-32-bytes-min"


def test_expliciet_secret_wint_altijd() -> None:
    assert _resolve_jwt_secret({"JWT_SECRET": "s3cret"}) == "s3cret"
    assert _resolve_jwt_secret({"JWT_SECRET": "s3cret", "ENVIRONMENT": "production"}) == "s3cret"


@pytest.mark.parametrize("environment", ["production", "staging", "acceptatie"])
def test_faalt_hard_buiten_dev_zonder_secret(environment: str) -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _resolve_jwt_secret({"ENVIRONMENT": environment})


def test_lege_string_telt_als_ontbrekend() -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _resolve_jwt_secret({"JWT_SECRET": "", "ENVIRONMENT": "production"})
