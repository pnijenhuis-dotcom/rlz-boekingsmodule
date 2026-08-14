"""Productie-config-gedrag (GCP-draaiboek F2.4): het refresh-cookie krijgt buiten dev/local
daadwerkelijk het Secure-attribuut, en de in-process webhook-afleveraar start niet in
production (Cloud Run-jobs leveren daar af, F3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Response

from app.auth.router import _set_refresh_cookie
from app.config import settings
from app.documenten import webhook_afleveraar


def _cookie_header(response: Response) -> str:
    return response.headers["set-cookie"]


def _paar() -> SimpleNamespace:
    return SimpleNamespace(refresh_token="token-x", refresh_ttl_seconds=60)


def test_refresh_cookie_secure_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    response = Response()
    _set_refresh_cookie(response, _paar())
    cookie = _cookie_header(response)
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()


def test_refresh_cookie_niet_secure_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "dev")
    response = Response()
    _set_refresh_cookie(response, _paar())
    assert "Secure" not in _cookie_header(response)


def test_afleveraar_start_niet_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "webhook_doel_url", "https://voorbeeld.test/webhooks/rlz")
    webhook_afleveraar.start_in_process_afleveraar()
    assert webhook_afleveraar._afleveraar is None


def test_afleveraar_start_wel_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "webhook_doel_url", "https://voorbeeld.test/webhooks/rlz")
    webhook_afleveraar.start_in_process_afleveraar()
    try:
        assert webhook_afleveraar._afleveraar is not None
    finally:
        webhook_afleveraar.stop_in_process_afleveraar()
