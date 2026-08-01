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
    onderteken_voor_verzending,
    verifieer_handtekening,
)

_NU = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _payload() -> dict:
    return bouw_factuur_geboekt_payload(
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
    )


def _envelope(secret: str = "test-secret", nu: datetime = _NU) -> dict:
    return onderteken_voor_verzending(payload=_payload(), secret=secret, nu=nu)


def test_opgeslagen_payload_is_ongetekend() -> None:
    """De HMAC-timing-fix (OPEN_ITEMS actiepunt 2): de outbox-payload bevat GEEN timestamp/
    nonce/handtekening — die berekent de afleveraar per verzendpoging, anders wijst het
    ~5 min-replay-venster elke uitgestelde aflevering af."""
    payload = _payload()
    assert set(payload.keys()) == {"schema_version", "event", "data"}
    assert payload["schema_version"] == WEBHOOK_SCHEMA_VERSION
    assert payload["event"] == FACTUUR_GEBOEKT_EVENT


def test_envelope_bevat_schema_version_event_en_handtekeningvelden() -> None:
    envelope = _envelope()
    assert envelope["schema_version"] == WEBHOOK_SCHEMA_VERSION
    assert envelope["event"] == FACTUUR_GEBOEKT_EVENT
    assert envelope["timestamp"] == _NU.isoformat()
    assert len(envelope["nonce"]) == 32  # secrets.token_hex(16)
    assert len(envelope["handtekening"]) == 64  # hex-sha256


def test_wire_formaat_ongewijzigd() -> None:
    """Koppelcontract-borging: de envelope die de afleveraar verstuurt heeft exact dezelfde
    velden als de oude, bij-boeken-getekende payload — alleen het moment van tekenen schoof."""
    envelope = _envelope()
    assert set(envelope.keys()) == {"schema_version", "event", "timestamp", "nonce", "data", "handtekening"}


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
    envelope = _envelope(secret="s3cret")
    payload_json = json.dumps(envelope["data"], sort_keys=True, separators=(",", ":"), default=str)
    assert verifieer_handtekening(
        secret="s3cret",
        payload_json=payload_json,
        timestamp=envelope["timestamp"],
        nonce=envelope["nonce"],
        handtekening=envelope["handtekening"],
    )


def test_handtekening_faalt_met_ander_secret() -> None:
    envelope = _envelope(secret="s3cret")
    payload_json = json.dumps(envelope["data"], sort_keys=True, separators=(",", ":"), default=str)
    assert not verifieer_handtekening(
        secret="ANDER-secret",
        payload_json=payload_json,
        timestamp=envelope["timestamp"],
        nonce=envelope["nonce"],
        handtekening=envelope["handtekening"],
    )


def test_handtekening_faalt_als_payload_gewijzigd_is() -> None:
    """Manipuleer de data ná ondertekening — de handtekening moet dan niet meer kloppen (dat is
    precies het doel van de HMAC: de ontvanger merkt elke wijziging)."""
    envelope = _envelope(secret="s3cret")
    gemanipuleerd = dict(envelope["data"])
    gemanipuleerd["rlz_boekstuknummer"] = "RLZ-04-99999999"
    gemanipuleerde_json = json.dumps(gemanipuleerd, sort_keys=True, separators=(",", ":"), default=str)
    assert not verifieer_handtekening(
        secret="s3cret",
        payload_json=gemanipuleerde_json,
        timestamp=envelope["timestamp"],
        nonce=envelope["nonce"],
        handtekening=envelope["handtekening"],
    )


def test_elke_verzendpoging_krijgt_verse_nonce_en_timestamp() -> None:
    """Twee keer tekenen van DEZELFDE opgeslagen payload = twee verschillende (timestamp, nonce,
    handtekening)-tripels — de ontvanger kan per nonce dedupliceren en een oude poging kan nooit
    als replay van de nieuwe gelden."""
    payload = _payload()
    a = onderteken_voor_verzending(payload=payload, secret="x", nu=_NU)
    b = onderteken_voor_verzending(payload=payload, secret="x", nu=datetime(2026, 7, 9, 14, 0, tzinfo=UTC))
    assert a["nonce"] != b["nonce"]
    assert a["timestamp"] != b["timestamp"]
    assert a["handtekening"] != b["handtekening"]
    assert a["data"] == b["data"]


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
