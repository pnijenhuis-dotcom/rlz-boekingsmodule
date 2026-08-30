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

    def test_twee_certificaten_play_app_signing_en_upload_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Play App Signing (30-08): élke Play-install is met Google's key gesigneerd, lokale
        # bundletool-installs met onze upload-key — beide moeten in één statement staan.
        google = "2C:EA:32:F9:44:A7:52:F9:DB:1E:87:B4:0F:DF:87:2C:F7:14:09:20:1D:F1:54:C9:16:70:2C:3D:E3:3E:3F:49"
        upload = "4A:B4:3C:F1:E9:86:EA:58:02:D7:3F:7A:78:13:FB:F5:EF:C0:17:0F:E8:35:00:01:2E:2C:45:02:00:E9:8F:A1"
        monkeypatch.setattr(settings, "android_cert_sha256_vingerafdrukken", [google, upload])
        resp = client.get("/.well-known/assetlinks.json")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["target"]["sha256_cert_fingerprints"] == [google, upload]
        assert "delegate_permission/common.get_login_creds" in body[0]["relation"]
