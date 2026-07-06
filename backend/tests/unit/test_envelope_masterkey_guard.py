"""De dev-only fallback-masterkey mag nooit stilzwijgend in productie belanden — zelfde patroon
als test_migration_0001_password_guard.py."""

import base64

import pytest

from app.security.envelope import _resolve_master_key


def test_dev_zonder_key_valt_terug_op_dev_key() -> None:
    assert _resolve_master_key({}) == b"\x00" * 32
    assert _resolve_master_key({"ENVIRONMENT": "local"}) == b"\x00" * 32


def test_expliciet_key_wint_altijd() -> None:
    key = base64.b64encode(b"x" * 32).decode()
    assert _resolve_master_key({"TOTP_MASTER_KEY": key}) == b"x" * 32
    assert _resolve_master_key({"TOTP_MASTER_KEY": key, "ENVIRONMENT": "production"}) == b"x" * 32


@pytest.mark.parametrize("environment", ["production", "staging", "acceptatie"])
def test_faalt_hard_buiten_dev_zonder_key(environment: str) -> None:
    with pytest.raises(RuntimeError, match="TOTP_MASTER_KEY"):
        _resolve_master_key({"ENVIRONMENT": environment})


def test_lege_string_telt_als_ontbrekend() -> None:
    with pytest.raises(RuntimeError, match="TOTP_MASTER_KEY"):
        _resolve_master_key({"TOTP_MASTER_KEY": "", "ENVIRONMENT": "production"})
