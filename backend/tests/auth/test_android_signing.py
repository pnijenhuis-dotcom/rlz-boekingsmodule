"""Android-signing → assetlinks + WebAuthn-origins (Play App Signing live 30-08).

Kern: assetlinks.json (apex + app-subdomein) en de `android:apk-key-hash:`-origins komen uit ÉÉN
bron (de vingerafdruk-lijst) via code — met de hand afgeleide origins waren de foutbron die het
draaiboek wilde uitsluiten. De drift-test leest deploy.yml én het statische apex-bestand en eist
dat ze op dezelfde twee certificaten staan."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.auth.android_signing import (
    android_webauthn_origins,
    apk_key_hash_origin,
    assetlinks_inhoud,
    assetlinks_json,
    normaliseer_vingerafdruk,
    toegestane_webauthn_origins,
)
from app.config import Settings, settings

REPO = Path(__file__).resolve().parents[3]
DEPLOY_YML = REPO / ".github" / "workflows" / "deploy.yml"
APEX_ASSETLINKS = REPO / "native" / "apex-well-known" / "assetlinks.json"

# Productiecertificaten (geen geheim — publiek in assetlinks.json). Bron: Play Console → App signing
# (30-08) resp. android_keystore.sh (29-08, PLAY_DRAAIBOEK §2).
GOOGLE_APP_SIGNING = "2C:EA:32:F9:44:A7:52:F9:DB:1E:87:B4:0F:DF:87:2C:F7:14:09:20:1D:F1:54:C9:16:70:2C:3D:E3:3E:3F:49"
UPLOAD_KEY = "4A:B4:3C:F1:E9:86:EA:58:02:D7:3F:7A:78:13:FB:F5:EF:C0:17:0F:E8:35:00:01:2E:2C:45:02:00:E9:8F:A1"
# De upload-key-origin zoals android_keystore.sh 'm op 29-08 onafhankelijk (openssl) printte.
UPLOAD_KEY_ORIGIN = "android:apk-key-hash:SrQ88emG6lgC1z96eBP79e_AFw_oNQABLixFAgDpj6E"


class TestAfleiding:
    def test_upload_key_origin_gelijk_aan_de_onafhankelijke_openssl_afleiding(self) -> None:
        assert apk_key_hash_origin(UPLOAD_KEY) == UPLOAD_KEY_ORIGIN

    def test_google_key_origin_base64url_zonder_padding(self) -> None:
        origin = apk_key_hash_origin(GOOGLE_APP_SIGNING)
        assert origin == "android:apk-key-hash:LOoy-USnUvnbHoe0D9-HLPcUCSAd8VTJFnAsPeM-P0k"
        b64 = origin.removeprefix("android:apk-key-hash:")
        assert "=" not in b64 and "+" not in b64 and "/" not in b64
        assert len(b64) == 43  # 32 bytes → 43 tekens base64url

    @pytest.mark.parametrize(
        "invoer",
        [
            UPLOAD_KEY,
            UPLOAD_KEY.lower(),
            UPLOAD_KEY.replace(":", ""),
            f"  {UPLOAD_KEY.lower().replace(':', '')}  ",
        ],
    )
    def test_normalisatie_accepteert_keytool_openssl_en_kleine_letters(self, invoer: str) -> None:
        assert normaliseer_vingerafdruk(invoer) == UPLOAD_KEY

    @pytest.mark.parametrize(
        "invoer",
        [
            "",
            "AA:BB",
            UPLOAD_KEY[:-3],
            UPLOAD_KEY + ":00",
            UPLOAD_KEY.replace("4A", "4G", 1),
            "SrQ88emG6lgC1z96eBP79e_AFw_oNQABLixFAgDpj6E",  # een origin is géén vingerafdruk
        ],
    )
    def test_ongeldige_vingerafdruk_is_een_valueerror(self, invoer: str) -> None:
        with pytest.raises(ValueError, match="Ongeldige SHA-256"):
            normaliseer_vingerafdruk(invoer)

    def test_settings_weigeren_een_kapotte_vingerafdruk_fail_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANDROID_CERT_SHA256_VINGERAFDRUKKEN", json.dumps([UPLOAD_KEY, "niet-een-hash"]))
        with pytest.raises(ValueError, match="Ongeldige SHA-256"):
            Settings(_env_file=None)

    def test_settings_normaliseren_naar_play_console_vorm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANDROID_CERT_SHA256_VINGERAFDRUKKEN", json.dumps([UPLOAD_KEY.lower().replace(":", "")]))
        assert Settings(_env_file=None).android_cert_sha256_vingerafdrukken == [UPLOAD_KEY]

    def test_origins_volgen_de_volgorde_en_dedupliceren(self) -> None:
        assert android_webauthn_origins([GOOGLE_APP_SIGNING, UPLOAD_KEY, UPLOAD_KEY.lower()]) == [
            "android:apk-key-hash:LOoy-USnUvnbHoe0D9-HLPcUCSAd8VTJFnAsPeM-P0k",
            UPLOAD_KEY_ORIGIN,
        ]


class TestToegestaneOrigins:
    def test_zonder_certificaten_alleen_de_geconfigureerde_https_origins(self) -> None:
        assert settings.android_cert_sha256_vingerafdrukken == []  # code-default (vaste testconfig)
        assert toegestane_webauthn_origins() == list(settings.webauthn_origins)

    def test_met_certificaten_komen_beide_apk_key_hash_origins_erbij(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "android_cert_sha256_vingerafdrukken", [GOOGLE_APP_SIGNING, UPLOAD_KEY])
        origins = toegestane_webauthn_origins()
        assert origins[: len(settings.webauthn_origins)] == list(settings.webauthn_origins)
        assert origins[len(settings.webauthn_origins) :] == [
            "android:apk-key-hash:LOoy-USnUvnbHoe0D9-HLPcUCSAd8VTJFnAsPeM-P0k",
            UPLOAD_KEY_ORIGIN,
        ]

    def test_handmatig_geconfigureerde_origin_wordt_niet_verdubbeld(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "android_cert_sha256_vingerafdrukken", [UPLOAD_KEY])
        monkeypatch.setattr(settings, "webauthn_origins", ["https://x.example", UPLOAD_KEY_ORIGIN])
        assert toegestane_webauthn_origins() == ["https://x.example", UPLOAD_KEY_ORIGIN]

    def test_webauthn_service_gebruikt_de_afgeleide_lijst(self) -> None:
        # Regressie: beide verify_*-calls moeten via toegestane_webauthn_origins lopen, niet
        # rechtstreeks settings.webauthn_origins lezen (anders faalt elke Android-assertion).
        bron = (REPO / "backend" / "app" / "auth" / "webauthn_service.py").read_text(encoding="utf-8")
        assert "settings.webauthn_origins" not in bron
        assert bron.count("expected_origin=toegestane_webauthn_origins()") == 2


class TestAssetlinksVorm:
    def test_statement_vorm_met_beide_certificaten(self) -> None:
        inhoud = assetlinks_inhoud("nl.aknijenhuis.goedkeuren", [GOOGLE_APP_SIGNING, UPLOAD_KEY.lower()])
        assert inhoud == [
            {
                "relation": [
                    "delegate_permission/common.handle_all_urls",
                    "delegate_permission/common.get_login_creds",
                ],
                "target": {
                    "namespace": "android_app",
                    "package_name": "nl.aknijenhuis.goedkeuren",
                    "sha256_cert_fingerprints": [GOOGLE_APP_SIGNING, UPLOAD_KEY],
                },
            }
        ]

    def test_json_serialisatie_eindigt_op_newline_en_is_parsebaar(self) -> None:
        tekst = assetlinks_json("nl.aknijenhuis.goedkeuren", [UPLOAD_KEY])
        assert tekst.endswith("\n")
        assert json.loads(tekst)[0]["target"]["sha256_cert_fingerprints"] == [UPLOAD_KEY]


def _vingerafdrukken_uit_deploy_yml() -> list[str]:
    tekst = DEPLOY_YML.read_text(encoding="utf-8")
    hits = re.findall(r"ANDROID_CERT_SHA256_VINGERAFDRUKKEN=(\[[^\]]*\])", tekst)
    assert len(hits) == 1, (
        f"verwacht precies één ANDROID_CERT_SHA256_VINGERAFDRUKKEN in deploy.yml, gevonden {len(hits)}"
    )
    # In de ^@^-lijst staan de aanhalingstekens YAML-escaped als \" — terug naar JSON.
    return json.loads(hits[0].replace('\\"', '"'))


class TestDriftDeployVsApex:
    """De drie plekken die op dezelfde certificaten moeten staan: deploy.yml (backend), het
    statische apex-bestand (bindend voor Android) en de vaste productiewaarden hierboven."""

    def test_deploy_yml_draagt_beide_productiecertificaten_google_eerst(self) -> None:
        assert _vingerafdrukken_uit_deploy_yml() == [GOOGLE_APP_SIGNING, UPLOAD_KEY]

    def test_apex_bestand_is_exact_de_generator_uitvoer_voor_deploy_yml(self) -> None:
        verwacht = assetlinks_json("nl.aknijenhuis.goedkeuren", _vingerafdrukken_uit_deploy_yml())
        assert APEX_ASSETLINKS.read_text(encoding="utf-8") == verwacht, (
            "native/apex-well-known/assetlinks.json loopt uit de pas met deploy.yml — hergenereer met "
            "`python -m app.auth.android_signing <certs…> --schrijf ../native/apex-well-known/assetlinks.json`"
        )

    def test_apex_bestand_en_backend_route_leveren_dezelfde_statement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        monkeypatch.setattr(settings, "android_cert_sha256_vingerafdrukken", _vingerafdrukken_uit_deploy_yml())
        resp = TestClient(app).get("/.well-known/assetlinks.json")
        assert resp.status_code == 200
        assert resp.json() == json.loads(APEX_ASSETLINKS.read_text(encoding="utf-8"))
