"""CORS-headers op álle foutantwoorden (adoptie uit Platform/registers/verbeteringen.md,
vastgoed 2026-07-11): een 4xx én een onverwachte 500 moeten allebei door de CORS-laag naar
buiten — anders ziet de browser een kaal "Failed to fetch" in plaats van de echte fout.
De 500 wordt gemaakt door OnverwachteFoutVangnet (binnenste laag, app/main.py), de headers
door CORSMiddleware (buitenste laag); deze tests pinnen precies die volgorde vast."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

_ORIGIN = settings.cors_allowed_origins[0]


@pytest.fixture(scope="module")
def kapotte_route() -> str:
    """Test-only route die altijd een onafgehandelde exception gooit — het pad dat vóór het
    vangnet als kale 500 zónder CORS-headers naar buiten kwam."""
    pad = "/_test/onverwachte-fout"
    if not any(getattr(route, "path", None) == pad for route in app.routes):

        @app.get(pad)
        def _kapot() -> None:
            raise RuntimeError("geheim intern detail (simulatie)")

    return pad


class TestCorsOpFoutantwoorden:
    def test_4xx_draagt_cors_headers(self) -> None:
        client = TestClient(app)
        response = client.get("/bestaat-niet", headers={"Origin": _ORIGIN})
        assert response.status_code == 404
        assert response.headers.get("access-control-allow-origin") == _ORIGIN

    def test_onverwachte_500_draagt_cors_headers_en_lekt_geen_details(self, kapotte_route: str) -> None:
        # Geen raise_server_exceptions=False nodig: het vangnet hoort de fout af te vangen
        # vóórdat hij Starlette's ServerErrorMiddleware (en dus de TestClient-reraise) bereikt —
        # dat is precies de sterkere bewering die deze test doet.
        client = TestClient(app)
        response = client.get(kapotte_route, headers={"Origin": _ORIGIN})

        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == _ORIGIN
        body = response.json()
        assert "Er ging iets mis bij" in body["detail"]
        assert "code" in body["detail"]  # correlatie-id voor de serverlog
        assert "geheim intern detail" not in response.text
        assert "RuntimeError" not in response.text

    def test_500_traceback_gaat_naar_de_serverlog(
        self, kapotte_route: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = TestClient(app)
        with caplog.at_level("ERROR", logger="app.main"):
            client.get(kapotte_route, headers={"Origin": _ORIGIN})
        assert any("Onverwachte fout" in record.getMessage() for record in caplog.records)
        assert any(record.exc_info is not None for record in caplog.records)
