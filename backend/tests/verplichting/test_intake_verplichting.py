"""Intake-routing op documentsoort (offerte-matching 04-09, mockup blok 1): AI leest `ds`, CODE
routeert. "verplichting" → eigen documentsoort mét dezelfde tenaamstelling-routing; "onduidelijk" →
verzamelbak mét leesbare reden (nooit stil als factuur); ""/"factuur" → bestaande inkooproute.
Plus de soort-keuze bij het toewijzen vanuit de verzamelbak."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.documenten.models import DocumentSoort, DocumentStatus
from app.extractie import splitsing as splitsing_extractie
from app.extractie.splitsing import FactuurSegment
from app.intake import redenen, verwerking
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_eml, bouw_pdf

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _stub_segment(monkeypatch: pytest.MonkeyPatch, *, documentsoort: str | None) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        verwerking.splitsing_extractie,
        "detecteer_facturen",
        lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
            FactuurSegment(1, 1, "BLOW B.V.", "Confide Bouw", "26140-OFF-01", 0.95, documentsoort=documentsoort)
        ],
    )


def _verwerk_pdf_mail(gescoopte_gebruiker: uuid.UUID) -> verwerking.BijlageResultaat:
    eml = bouw_eml(bijlagen=[("offerte.pdf", bouw_pdf(1), "application", "pdf")])
    resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
    [bijlage] = resultaat.bijlagen
    return bijlage


def _soort_en_status(admin_engine: Engine, document_id: uuid.UUID) -> tuple[str, str]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT soort, status::text FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).one()


class TestSchema:
    def test_ds_is_een_sentinel_string_zonder_union(self):
        """Unionlimiet-regel (bugfix 31-08): nieuwe AI-velden nooit nullable/union."""
        item = splitsing_extractie.SPLITSING_SCHEMA["properties"]["facturen"]["items"]
        assert item["properties"]["ds"] == {"type": "string"}
        assert "ds" in item["required"]

    def test_alleen_de_drie_bekende_waarden_zijn_een_uitspraak(self):
        assert splitsing_extractie.DOCUMENTSOORTEN == ("factuur", "verplichting", "onduidelijk")


class TestRouting:
    def test_verplichting_wordt_toegewezen_als_verplichting(
        self, admin_engine: Engine, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        _stub_segment(monkeypatch, documentsoort="verplichting")
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        assert bijlage.uitkomst == "toegewezen"
        soort, status = _soort_en_status(admin_engine, bijlage.document_id)
        assert soort == DocumentSoort.VERPLICHTING.value
        # Zelfde tenaamstelling-routing + de normale extractieflow (AI-veldextractie staat uit).
        assert status == DocumentStatus.TE_CONTROLEREN.value

    def test_factuur_blijft_een_inkoopfactuur(
        self, admin_engine: Engine, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        _stub_segment(monkeypatch, documentsoort="factuur")
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        soort, _ = _soort_en_status(admin_engine, bijlage.document_id)
        assert soort == DocumentSoort.INKOOPFACTUUR.value

    def test_niet_gelezen_soort_blijft_een_inkoopfactuur(
        self, admin_engine: Engine, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        """Sentinel: geen uitspraak = bestaande route (geen gedragswijziging voor oude clients)."""
        _stub_segment(monkeypatch, documentsoort=None)
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        soort, _ = _soort_en_status(admin_engine, bijlage.document_id)
        assert soort == DocumentSoort.INKOOPFACTUUR.value

    def test_onduidelijk_gaat_naar_de_verzamelbak_met_leesbare_reden(
        self, admin_engine: Engine, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        _stub_segment(monkeypatch, documentsoort="onduidelijk")
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        assert bijlage.uitkomst == "verzamelbak"
        assert bijlage.detail == verwerking.REDEN_DOCUMENTSOORT_ONDUIDELIJK
        soort, status = _soort_en_status(admin_engine, bijlage.document_id)
        assert status == DocumentStatus.NIET_TOEGEWEZEN.value
        # Nooit stil als factuur behandeld: de soort blijft de default tot de mens kiest.
        assert soort == DocumentSoort.INKOOPFACTUUR.value

    def test_reden_vertaling_is_leesbaar(self):
        assert (
            redenen.omschrijf_intake_reden(
                verwerking.REDEN_DOCUMENTSOORT_ONDUIDELIJK, tenaamstelling="BLOW B.V."
            )
            == "factuur of offerte? — kies bij toewijzen"
        )


class TestToewijzenMetSoort:
    def test_toewijzen_als_verplichting(
        self, admin_engine: Engine, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        _stub_segment(monkeypatch, documentsoort="onduidelijk")
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        resp = client.post(
            f"/verzamelbak/{bijlage.document_id}/toewijzen",
            json={"administratie_id": str(administratie_heet_blow), "soort": "verplichting"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        soort, status = _soort_en_status(admin_engine, bijlage.document_id)
        assert soort == DocumentSoort.VERPLICHTING.value
        assert status == DocumentStatus.TE_CONTROLEREN.value

    def test_toewijzen_zonder_soort_laat_de_soort_staan(
        self, admin_engine: Engine, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        _stub_segment(monkeypatch, documentsoort="onduidelijk")
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        resp = client.post(
            f"/verzamelbak/{bijlage.document_id}/toewijzen",
            json={"administratie_id": str(administratie_heet_blow)},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200
        soort, _ = _soort_en_status(admin_engine, bijlage.document_id)
        assert soort == DocumentSoort.INKOOPFACTUUR.value

    def test_niet_toewijsbare_soort_is_422(
        self, administratie_heet_blow, gescoopte_gebruiker, opslag, intake_ai_aan, monkeypatch
    ):
        """Fail-closed: een kassarapport/waarborg komt via een eigen kanaal — hier zou dat een
        stille misroutering zijn."""
        _stub_segment(monkeypatch, documentsoort="onduidelijk")
        bijlage = _verwerk_pdf_mail(gescoopte_gebruiker)
        resp = client.post(
            f"/verzamelbak/{bijlage.document_id}/toewijzen",
            json={"administratie_id": str(administratie_heet_blow), "soort": "kassarapport"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 422


class TestHandmatigeUpload:
    def test_verplichting_via_de_upload_route(
        self, admin_engine: Engine, administratie_id, gescoopte_gebruiker, opslag
    ):
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("offerte.pdf", bouw_pdf(1), "application/pdf")},
            data={"soort": "verplichting"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        soort, status = _soort_en_status(admin_engine, uuid.UUID(resp.json()["document_id"]))
        assert soort == DocumentSoort.VERPLICHTING.value
        assert status == DocumentStatus.TE_CONTROLEREN.value

    def test_een_verplichting_mag_geen_xml_zijn(self, administratie_id, gescoopte_gebruiker, opslag):
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("offerte.xml", b"<Invoice/>", "application/xml")},
            data={"soort": "verplichting"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 415
