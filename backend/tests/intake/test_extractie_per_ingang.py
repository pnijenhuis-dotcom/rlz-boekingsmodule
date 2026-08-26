"""AI-scan op ÁLLE upload-ingangen (feedbackronde 26-08 punt 4).

Eén codepad, meerdere ingangen: elke ingang die een document aan een administratie koppelt
loopt via `documenten.service.upload_document` / `start_extractie_na_toewijzing` → dezelfde
AI-veldextractie achter dezelfde gates (per-administratie AVG-gate `ai_extractie_ingeschakeld`,
API-key, AI-kostengrens), zelfde BSN-regels/kostenlogging/tijdlijn-detail. Deze regressietests
bewijzen per ingang dat de extractie aantoonbaar getriggerd wordt — en netjes wordt
overgeslagen mét zichtbare reden als de gate uit staat of de limiet bereikt is.

Ingangen: (1) POST /intake/eml (mail), (2) POST /intake/bestand (werkvoorraad-sleepzone),
(3) POST /administraties/{id}/documenten (klantpagina), (4) verzamelbak → toewijzen,
(5) splitsing bevestigen. De IMAP-fetch deelt codepad (1) (`verwerk_eml`).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.aikosten.service import AiKostenLimietBereikt
from app.beheer import service as beheer_service
from app.config import settings
from app.extractie.splitsing import FactuurSegment
from app.intake import splitsing as splitsing_service
from app.intake import verwerking
from app.intake.splitsing import SplitsDeelInput
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.test_ai_extractie import _fake_extractie
from tests.intake.conftest import bouw_eml, bouw_pdf

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


@pytest.fixture
def intake_ai_met_een_segment(intake_ai_aan: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Intake-AI aan + splitsingsdetectie gestubd op één factuur voor BLOW B.V."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        verwerking.splitsing_extractie,
        "detecteer_facturen",
        lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
            FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-1", 0.95)
        ],
    )


@pytest.fixture
def veldextractie_aan(administratie_heet_blow: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_heet_blow, ingeschakeld=True
    )


@pytest.fixture
def fake_extraheer(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    aanroepen: list[bytes] = []

    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None):
        aanroepen.append(pdf_bytes)
        return _fake_extractie()

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)
    return aanroepen


def _pdf_met_ongelijke_paginas() -> bytes:
    import io

    from pypdf import PdfWriter

    schrijver = PdfWriter()
    schrijver.add_blank_page(width=200, height=200)
    schrijver.add_blank_page(width=300, height=400)
    buffer = io.BytesIO()
    schrijver.write(buffer)
    return buffer.getvalue()


def _laatste_detail(admin_engine: Engine, document_id: uuid.UUID) -> dict | None:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :d "
                "AND naar_status IN ('te_controleren','handmatig_afmaken') ORDER BY tijdstip DESC LIMIT 1"
            ),
            {"d": document_id},
        ).scalars().all()
    return rijen[0] if rijen else None


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :d"), {"d": document_id}
        ).scalar_one()


def _assert_geextraheerd(admin_engine: Engine, document_id: uuid.UUID, fake_extraheer: list[bytes]) -> None:
    assert len(fake_extraheer) == 1, "de AI-veldextractie moet precies één keer getriggerd zijn"
    assert _status(admin_engine, document_id) == "te_controleren"
    detail = _laatste_detail(admin_engine, document_id)
    assert detail is not None and "veldvoorstel" in detail and detail["veldvoorstel"]["bron"] == "ai"


def _assert_overgeslagen(admin_engine: Engine, document_id: uuid.UUID, fake_extraheer: list[bytes], reden: str) -> None:
    assert fake_extraheer == [], "zonder groene gate gaat er géén byte naar de AI"
    assert _status(admin_engine, document_id) == "te_controleren"
    detail = _laatste_detail(admin_engine, document_id)
    assert detail is not None and detail.get("ai_extractie_overgeslagen") == reden


# --- (1) mail -------------------------------------------------------------------------------


class TestMailIngang:
    def test_mail_triggert_veldextractie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_met_een_segment: None,
        veldextractie_aan: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
    ) -> None:
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(1), "application", "pdf")])
        resp = client.post("/intake/eml", files={"bestand": ("m.eml", eml, "message/rfc822")}, headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 201, resp.text
        bijlage = resp.json()["bijlagen"][0]
        assert bijlage["uitkomst"] == "toegewezen"
        _assert_geextraheerd(admin_engine, uuid.UUID(bijlage["document_id"]), fake_extraheer)

    def test_mail_zonder_avg_gate_slaat_zichtbaar_over(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        intake_ai_met_een_segment: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
    ) -> None:
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        _assert_overgeslagen(admin_engine, resultaat.bijlagen[0].document_id, fake_extraheer, "ai_extractie_uitgeschakeld")


# --- (2) werkvoorraad-sleepzone --------------------------------------------------------------


class TestSleepzoneIngang:
    def test_los_bestand_met_eenduidige_tenaamstelling_triggert_veldextractie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        intake_ai_met_een_segment: None,
        veldextractie_aan: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
    ) -> None:
        resp = client.post(
            "/intake/bestand",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["uitkomst"] == "toegewezen"
        _assert_geextraheerd(admin_engine, uuid.UUID(resp.json()["document_id"]), fake_extraheer)

    def test_los_bestand_zonder_tenaamstelling_wacht_in_de_verzamelbak_op_toewijzing(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        veldextractie_aan: None,
        intake_ai_aan: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De sleepzone heeft geen afzender-signaal (bewust): alleen een exacte tenaamstelling wijst
        toe. Onbekende tenaamstelling → verzamelbak, extractie pas ná menselijke toewijzing (4)."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            verwerking.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 1, "Onbekende Klant BV", "Bouwmaat", "F-1", 0.95)
            ],
        )
        resp = client.post(
            "/intake/bestand",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201 and resp.json()["uitkomst"] == "verzamelbak"
        assert fake_extraheer == []
        document_id = uuid.UUID(resp.json()["document_id"])
        resp = client.post(
            f"/verzamelbak/{document_id}/toewijzen",
            json={"administratie_id": str(administratie_heet_blow)},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        _assert_geextraheerd(admin_engine, document_id, fake_extraheer)


# --- (3) klantpagina-upload ------------------------------------------------------------------


class TestKlantpaginaIngang:
    def test_upload_op_klant_triggert_veldextractie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        veldextractie_aan: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        resp = client.post(
            f"/administraties/{administratie_heet_blow}/documenten",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        _assert_geextraheerd(admin_engine, uuid.UUID(resp.json()["document_id"]), fake_extraheer)

    def test_upload_op_klant_zonder_avg_gate_slaat_zichtbaar_over(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        resp = client.post(
            f"/administraties/{administratie_heet_blow}/documenten",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        _assert_overgeslagen(admin_engine, uuid.UUID(resp.json()["document_id"]), fake_extraheer, "ai_extractie_uitgeschakeld")

    def test_upload_op_klant_boven_de_ai_kostengrens_slaat_zichtbaar_over(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        veldextractie_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        def limiet(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None):
            raise AiKostenLimietBereikt("maandlimiet bereikt")

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", limiet)
        resp = client.post(
            f"/administraties/{administratie_heet_blow}/documenten",
            files={"bestand": ("scan.pdf", bouw_pdf(1), "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        document_id = uuid.UUID(resp.json()["document_id"])
        assert _status(admin_engine, document_id) == "te_controleren"
        detail = _laatste_detail(admin_engine, document_id)
        assert detail is not None and detail.get("ai_extractie_overgeslagen") == "ai_limiet_bereikt"


# --- (4) verzamelbak → toewijzen en (5) splitsing bevestigen -------------------------------


class TestVerzamelbakEnSplitsing:
    def test_toewijzen_uit_de_verzamelbak_triggert_veldextractie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        veldextractie_aan: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        # Intake-AI uit → de PDF landt in de verzamelbak (zichtbaar, reden intake_ai_uitgeschakeld).
        eml = bouw_eml(bijlagen=[("scan.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        document_id = resultaat.bijlagen[0].document_id
        assert document_id is not None and fake_extraheer == []

        resp = client.post(
            f"/verzamelbak/{document_id}/toewijzen",
            json={"administratie_id": str(administratie_heet_blow)},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        _assert_geextraheerd(admin_engine, document_id, fake_extraheer)

    def test_splitsing_bevestigen_triggert_veldextractie_per_deel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        intake_ai_aan: None,
        veldextractie_aan: None,
        fake_extraheer: list[bytes],
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            verwerking.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-1", 0.95),
                FactuurSegment(2, 2, "BLOW B.V.", "Sligro", "F-2", 0.9),
            ],
        )
        # Twee ongelijke pagina's: identieke blanco pagina's zouden identieke deel-PDF's (zelfde
        # sha256) geven en dan terecht op de intake-idempotentie van hetzelfde bericht stuiten.
        eml = bouw_eml(bijlagen=[("batch.pdf", _pdf_met_ongelijke_paginas(), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "splitsingsvoorstel"
        assert fake_extraheer == []  # het voorstel gaat éérst ter controle
        with admin_engine.connect() as conn:
            splitsing_id = conn.execute(
                text("SELECT id FROM boekhouding.intake_splitsing WHERE bron_document_id = :d"),
                {"d": resultaat.bijlagen[0].document_id},
            ).scalar_one()

        delen = splitsing_service.bevestig_splitsing(
            splitsing_id=splitsing_id,
            actor_id=gescoopte_gebruiker,
            delen=[
                SplitsDeelInput(start_pagina=1, eind_pagina=1, tenaamstelling="BLOW B.V."),
                SplitsDeelInput(start_pagina=2, eind_pagina=2, tenaamstelling="BLOW B.V."),
            ],
        )
        assert len(delen) == 2
        assert len(fake_extraheer) == 2  # elk deel door hetzelfde extractiepad
        for deel in delen:
            assert _status(admin_engine, deel.document_id) == "te_controleren"
