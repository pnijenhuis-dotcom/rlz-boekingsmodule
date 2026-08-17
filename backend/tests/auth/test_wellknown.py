"""Passkey-domeinkoppeling native store-apps (fase 2): de well-known-routes zijn fail-closed
(config leeg = 404, nooit een halve koppeling publiceren) en serveren precies de vorm die
iOS/Android verwachten. Anoniem bereikbaar — het OS haalt ze zonder auth op."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


class TestAppleAppSiteAssociation:
    def test_zonder_team_id_404_fail_closed(self) -> None:
        assert settings.apple_team_id == ""  # code-default (vaste testconfig)
        assert client.get("/.well-known/apple-app-site-association").status_code == 404

    def test_met_team_id_de_webcredentials_vorm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "apple_team_id", "ABCDE12345")
        resp = client.get("/.well-known/apple-app-site-association")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json() == {"webcredentials": {"apps": ["ABCDE12345.nl.aknijenhuis.goedkeuren"]}}


class TestAssetlinks:
    def test_zonder_vingerafdrukken_404_fail_closed(self) -> None:
        assert settings.android_cert_sha256_vingerafdrukken == []
        assert client.get("/.well-known/assetlinks.json").status_code == 404

    def test_met_vingerafdruk_de_assetlinks_vorm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        vingerafdruk = "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"
        monkeypatch.setattr(settings, "android_cert_sha256_vingerafdrukken", [vingerafdruk])
        resp = client.get("/.well-known/assetlinks.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body == [
            {
                "relation": [
                    "delegate_permission/common.handle_all_urls",
                    "delegate_permission/common.get_login_creds",
                ],
                "target": {
                    "namespace": "android_app",
                    "package_name": "nl.aknijenhuis.goedkeuren",
                    "sha256_cert_fingerprints": [vingerafdruk],
                },
            }
        ]
