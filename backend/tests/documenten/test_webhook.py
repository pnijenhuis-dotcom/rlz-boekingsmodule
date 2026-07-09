from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.documenten.webhook import (
    FACTUUR_GEBOEKT_EVENT,
    WEBHOOK_SCHEMA_VERSION,
    WebhookRegel,
    _resolve_webhook_secret,
    bereken_handtekening,
    bouw_factuur_geboekt_payload,
    verifieer_handtekening,
)

_NU = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _payload(secret: str = "test-secret") -> dict:
    return bouw_factuur_geboekt_payload(
        secret=secret,
        administratie_id=uuid.uuid4(),
        rlz_admin_id="rlz-admin-1",
        rlz_document_id=uuid.uuid4(),
        rlz_boekstuknummer="RLZ-04-00002001",
        factuurdatum=datetime(2026, 7, 1).date(),
        vendor_id=uuid.uuid4(),
        vendor_naam="Test Leverancier",
        referentie="F-2026-001",
        regels=[
            WebhookRegel(
                ledger_id=uuid.uuid4(),
                grootboek_code="4699",
                project_id=None,
                netto_bedrag=Decimal("100.00"),
                btw_bedrag=Decimal("21.00"),
                omschrijving="Test",
            )
        ],
        nu=_NU,
    )


def test_payload_bevat_schema_version_event_en_handtekeningvelden() -> None:
    payload = _payload()
    assert payload["schema_version"] == WEBHOOK_SCHEMA_VERSION
    assert payload["event"] == FACTUUR_GEBOEKT_EVENT
    assert payload["timestamp"] == _NU.isoformat()
    assert len(payload["nonce"]) == 32  # secrets.token_hex(16)
    assert len(payload["handtekening"]) == 64  # hex-sha256


def test_data_bevat_de_koppelcontract_velden() -> None:
    payload = _payload()
    data = payload["data"]
    for veld in (
        "administratie_id",
        "rlz_admin_id",
        "rlz_document_id",
        "rlz_boekstuknummer",
        "datum",
        "leverancier",
        "referentie",
        "regels",
    ):
        assert veld in data
    assert data["regels"][0]["grootboek_code"] == "4699"
    assert data["regels"][0]["netto_bedrag"] == "100.00"


def test_handtekening_verifieert_met_hetzelfde_secret() -> None:
    payload = _payload(secret="s3cret")
    payload_json = json.dumps(payload["data"], sort_keys=True, separators=(",", ":"), default=str)
    assert verifieer_handtekening(
        secret="s3cret",
        payload_json=payload_json,
        timestamp=payload["timestamp"],
        nonce=payload["nonce"],
        handtekening=payload["handtekening"],
    )


def test_handtekening_faalt_met_ander_secret() -> None:
    payload = _payload(secret="s3cret")
    payload_json = json.dumps(payload["data"], sort_keys=True, separators=(",", ":"), default=str)
    assert not verifieer_handtekening(
        secret="ANDER-secret",
        payload_json=payload_json,
        timestamp=payload["timestamp"],
        nonce=payload["nonce"],
        handtekening=payload["handtekening"],
    )


def test_handtekening_faalt_als_payload_gewijzigd_is() -> None:
    """Manipuleer de data ná ondertekening — de handtekening moet dan niet meer kloppen (dat is
    precies het doel van de HMAC: de ontvanger merkt elke wijziging)."""
    payload = _payload(secret="s3cret")
    gemanipuleerd = dict(payload["data"])
    gemanipuleerd["rlz_boekstuknummer"] = "RLZ-04-99999999"
    gemanipuleerde_json = json.dumps(gemanipuleerd, sort_keys=True, separators=(",", ":"), default=str)
    assert not verifieer_handtekening(
        secret="s3cret",
        payload_json=gemanipuleerde_json,
        timestamp=payload["timestamp"],
        nonce=payload["nonce"],
        handtekening=payload["handtekening"],
    )


def test_twee_aanroepen_hebben_verschillende_nonces() -> None:
    a = _payload()
    b = _payload()
    assert a["nonce"] != b["nonce"]


def test_bereken_handtekening_is_deterministisch_voor_dezelfde_invoer() -> None:
    a = bereken_handtekening(secret="x", payload_json='{"a":1}', timestamp="t", nonce="n")
    b = bereken_handtekening(secret="x", payload_json='{"a":1}', timestamp="t", nonce="n")
    assert a == b


class TestWebhookSecretGuard:
    """Zelfde bewaking als jwt_secret/totp_master_key_b64 — nooit een stil fallback buiten dev."""

    def test_dev_zonder_secret_valt_terug_op_dev_secret(self) -> None:
        assert _resolve_webhook_secret({}) == "dev-only-insecure-webhook-hmac-secret"
        assert _resolve_webhook_secret({"ENVIRONMENT": "local"}) == "dev-only-insecure-webhook-hmac-secret"

    def test_expliciet_secret_wint_altijd(self) -> None:
        assert _resolve_webhook_secret({"WEBHOOK_HMAC_SECRET": "s3cret"}) == "s3cret"
        assert _resolve_webhook_secret({"WEBHOOK_HMAC_SECRET": "s3cret", "ENVIRONMENT": "production"}) == "s3cret"

    @pytest.mark.parametrize("environment", ["production", "staging", "acceptatie"])
    def test_faalt_hard_buiten_dev_zonder_secret(self, environment: str) -> None:
        with pytest.raises(RuntimeError, match="WEBHOOK_HMAC_SECRET"):
            _resolve_webhook_secret({"ENVIRONMENT": environment})

    def test_lege_string_telt_als_ontbrekend(self) -> None:
        with pytest.raises(RuntimeError, match="WEBHOOK_HMAC_SECRET"):
            _resolve_webhook_secret({"WEBHOOK_HMAC_SECRET": "", "ENVIRONMENT": "production"})
