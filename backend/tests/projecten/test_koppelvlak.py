"""Koppelvlak-tests (route A, koppelcontract §5 v1.15): HMAC + replay-venster + nonce +
bericht_id-idempotentie + de harde is_vastgoed-scope, end-to-end door de FastAPI-app heen
(alleen RLZ is nep — de motor, DB-registratie en audit draaien echt)."""

from __future__ import annotations

import secrets as secrets_module
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.db.session import scoped_session
from app.documenten.webhook import _canonical_json, bereken_handtekening
from app.main import app
from app.projecten.models import ProjectAanvraag
from app.projecten.router import _resolve_projectaanvraag_secret
from tests.projecten.conftest import FakeProjectClient

client = TestClient(app)

DEV_SECRET = "dev-only-insecure-projectaanvraag-hmac-secret"
ENDPOINT = "/koppelvlak/vastgoed/projectaanvragen"


def bouw_envelope(
    administratie_id: uuid.UUID,
    *,
    bericht_id: uuid.UUID | None = None,
    pand_referentie: str = "vastly-object-42",
    naam_invoer: str = "Dorpsstraat 1, Zwolle",
    secret: str = DEV_SECRET,
    timestamp: str | None = None,
    nonce: str | None = None,
    schema_version: str = "1.0",
    event: str = "projectaanvraag",
) -> dict[str, Any]:
    data = {
        "bericht_id": str(bericht_id or uuid.uuid4()),
        "administratie_id": str(administratie_id),
        "pand_referentie": pand_referentie,
        "naam_invoer": naam_invoer,
    }
    timestamp = timestamp or datetime.now(UTC).isoformat()
    nonce = nonce or secrets_module.token_hex(16)
    return {
        "schema_version": schema_version,
        "event": event,
        "timestamp": timestamp,
        "nonce": nonce,
        "data": data,
        "handtekening": bereken_handtekening(
            secret=secret, payload_json=_canonical_json(data), timestamp=timestamp, nonce=nonce
        ),
    }


def test_geldige_aanvraag_maakt_project_en_registreert(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    envelope = bouw_envelope(vastgoed_administratie_id)
    resp = client.post(ENDPOINT, json=envelope)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "aangemaakt"
    assert body["projectnaam"] == "Dorpsstraat 1, Zwolle"
    assert fake_rlz.put_project_aanroepen == 1
    with scoped_session(vastgoed_administratie_id) as session:
        rij = session.get(ProjectAanvraag, uuid.UUID(envelope["data"]["bericht_id"]))
        assert rij is not None
        assert str(rij.rlz_project_id) == body["rlz_project_id"]


def test_herlevering_zelfde_bericht_geeft_zelfde_antwoord_zonder_rlz_call(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    envelope = bouw_envelope(vastgoed_administratie_id)
    eerste = client.post(ENDPOINT, json=envelope).json()

    # Herlevering: zelfde bericht, verse timestamp/nonce (de afzender tekent per poging).
    herlevering = bouw_envelope(
        vastgoed_administratie_id, bericht_id=uuid.UUID(envelope["data"]["bericht_id"])
    )
    tweede_resp = client.post(ENDPOINT, json=herlevering)

    assert tweede_resp.status_code == 200
    tweede = tweede_resp.json()
    assert tweede["rlz_project_id"] == eerste["rlz_project_id"]
    assert tweede["status"] == eerste["status"]
    assert fake_rlz.put_project_aanroepen == 1  # géén tweede RLZ-call


def test_zelfde_bericht_id_met_andere_inhoud_is_conflict(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    envelope = bouw_envelope(vastgoed_administratie_id)
    client.post(ENDPOINT, json=envelope)

    ander = bouw_envelope(
        vastgoed_administratie_id,
        bericht_id=uuid.UUID(envelope["data"]["bericht_id"]),
        pand_referentie="vastly-object-999",
    )
    resp = client.post(ENDPOINT, json=ander)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "bericht_conflict"


def test_tweede_pand_aanvraag_zelfde_pand_referentie_is_bestond_al(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    client.post(ENDPOINT, json=bouw_envelope(vastgoed_administratie_id))
    resp = client.post(ENDPOINT, json=bouw_envelope(vastgoed_administratie_id))

    assert resp.status_code == 200
    assert resp.json()["status"] == "bestond_al"
    assert fake_rlz.put_project_aanroepen == 1


def test_foute_handtekening_is_401(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    envelope = bouw_envelope(vastgoed_administratie_id, secret="verkeerd-secret")
    resp = client.post(ENDPOINT, json=envelope)
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "handtekening_ongeldig"
    assert fake_rlz.put_project_aanroepen == 0


def test_timestamp_buiten_replay_venster_is_400(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    oud = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    resp = client.post(ENDPOINT, json=bouw_envelope(vastgoed_administratie_id, timestamp=oud))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "timestamp_buiten_venster"


def test_nonce_hergebruik_onder_ander_bericht_is_409(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    nonce = secrets_module.token_hex(16)
    client.post(ENDPOINT, json=bouw_envelope(vastgoed_administratie_id, nonce=nonce))

    resp = client.post(
        ENDPOINT,
        json=bouw_envelope(vastgoed_administratie_id, nonce=nonce, pand_referentie="vastly-object-2"),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "nonce_hergebruikt"


def test_onbekende_administratie_is_404(fake_rlz: FakeProjectClient) -> None:
    resp = client.post(ENDPOINT, json=bouw_envelope(uuid.uuid4()))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "administratie_onbekend"


def test_niet_vastgoed_administratie_is_403(
    administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    resp = client.post(ENDPOINT, json=bouw_envelope(administratie_id))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "geen_vastgoed_administratie"
    assert fake_rlz.put_project_aanroepen == 0


def test_bag_id_in_naam_is_400(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    resp = client.post(
        ENDPOINT,
        json=bouw_envelope(vastgoed_administratie_id, naam_invoer="Pand 0193010000123456"),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "naam_ongeldig"


def test_onbekende_schema_version_is_400(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    resp = client.post(ENDPOINT, json=bouw_envelope(vastgoed_administratie_id, schema_version="9.9"))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "schema_version_onbekend"


def test_rlz_fout_is_zichtbare_502_en_geen_registratie(
    vastgoed_administratie_id: uuid.UUID, fake_rlz: FakeProjectClient
) -> None:
    fake_rlz.faal_bij_put_project = True
    envelope = bouw_envelope(vastgoed_administratie_id)
    resp = client.post(ENDPOINT, json=envelope)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "rlz_fout"
    with scoped_session(vastgoed_administratie_id) as session:
        assert session.get(ProjectAanvraag, uuid.UUID(envelope["data"]["bericht_id"])) is None

    # Herstel + herhaal met hetzelfde bericht_id: nu slaagt hij alsnog.
    fake_rlz.faal_bij_put_project = False
    herhaal = bouw_envelope(
        vastgoed_administratie_id, bericht_id=uuid.UUID(envelope["data"]["bericht_id"])
    )
    resp2 = client.post(ENDPOINT, json=herhaal)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "aangemaakt"


class TestSecretFailClosed:
    """F4-voorbereiding (2026-08-14): het inkomende kanaal mag buiten dev nooit stil op het
    dev-secret terugvallen — zelfde bewaking als het webhook-/JWT-secret (spiegel van
    tests/documenten/test_webhook.py::TestResolveWebhookSecret)."""

    def test_dev_zonder_secret_valt_terug_op_dev_secret(self) -> None:
        assert _resolve_projectaanvraag_secret({}) == DEV_SECRET
        assert _resolve_projectaanvraag_secret({"ENVIRONMENT": "local"}) == DEV_SECRET

    def test_expliciet_secret_wint_altijd(self) -> None:
        assert _resolve_projectaanvraag_secret({"PROJECTAANVRAAG_HMAC_SECRET": "s3cret"}) == "s3cret"
        assert (
            _resolve_projectaanvraag_secret(
                {"PROJECTAANVRAAG_HMAC_SECRET": "s3cret", "ENVIRONMENT": "production"}
            )
            == "s3cret"
        )

    @pytest.mark.parametrize("environment", ["production", "staging", "iets-anders"])
    def test_faalt_hard_buiten_dev_zonder_secret(self, environment: str) -> None:
        with pytest.raises(RuntimeError):
            _resolve_projectaanvraag_secret({"ENVIRONMENT": environment})

    def test_lege_string_telt_als_ontbrekend(self) -> None:
        with pytest.raises(RuntimeError):
            _resolve_projectaanvraag_secret(
                {"PROJECTAANVRAAG_HMAC_SECRET": "", "ENVIRONMENT": "production"}
            )

    def test_endpoint_weigert_503_zonder_secret_buiten_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-closed op het endpoint zelf: geen secret buiten dev = zichtbare 503
        `niet_geconfigureerd`, vóór élke verwerking van de body — nooit stil verifiëren
        tegen het dev-fallback-secret."""
        monkeypatch.setattr(app_settings, "projectaanvraag_hmac_secret", None)
        monkeypatch.setattr(app_settings, "environment", "production")
        resp = client.post(ENDPOINT, json={})
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "niet_geconfigureerd"
