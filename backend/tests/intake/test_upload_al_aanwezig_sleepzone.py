"""Besluit Peter 18-09: ook de werkvoorraad-SLEEPZONE (`POST /intake/bestand`, tenaamstelling-routing zonder klant)
geeft 409 "al aanwezig" mét verwijzing als dezelfde bytes in de gerouteerde administratie al een document zijn — géén
tweede document. Het detail draagt `bestaand_administratie_id` zodat de zone kan linken (de administratie is daar vooraf
onbekend)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.extractie.splitsing import FactuurSegment
from app.intake import verwerking
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_pdf

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


@pytest.fixture
def blow_routering(
    intake_ai_aan: None, administratie_heet_blow: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> uuid.UUID:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        verwerking.splitsing_extractie,
        "detecteer_facturen",
        lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
            FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-1", 0.95)
        ],
    )
    return administratie_heet_blow


def test_sleepzone_tweede_keer_zelfde_bestand_geeft_409_met_verwijzing(
    gescoopte_gebruiker: uuid.UUID, blow_routering: uuid.UUID, admin_engine: Engine
) -> None:
    pdf = bouw_pdf(1)
    eerste = client.post(
        "/intake/bestand", files={"bestand": ("scan.pdf", pdf, "application/pdf")}, headers=_bearer(gescoopte_gebruiker)
    )
    assert eerste.status_code == 201, eerste.text
    assert eerste.json()["uitkomst"] == "toegewezen"
    tweede = client.post(
        "/intake/bestand",
        files={"bestand": ("scan (1).pdf", pdf, "application/pdf")},
        headers=_bearer(gescoopte_gebruiker),
    )
    assert tweede.status_code == 409, tweede.text
    detail = tweede.json()["detail"]
    assert detail["code"] == "al_aanwezig"
    assert detail["bestaand_document_id"] == eerste.json()["document_id"]
    assert detail["bestaand_administratie_id"] == str(blow_routering)
    with admin_engine.connect() as conn:
        n = conn.scalar(
            text("SELECT count(*) FROM boekhouding.document WHERE administratie_id = :a"), {"a": blow_routering}
        )
    assert n == 1
