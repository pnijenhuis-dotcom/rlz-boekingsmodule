"""Same-origin frontend-serving (F2, app/static_frontend.py): de fallback-regels spiegelen de
dev-proxy (frontend/proxyRegels.ts) — bestand > document-navigatie > API-segment-404 > SPA.
Eigen mini-app per test (geen app.main): geen database, geen lifespan."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_frontend import CACHE_ASSETS, CACHE_OVERIG, activeer_frontend_serving

INDEX_INHOUD = "<!doctype html><title>rlz-spa</title>"

# Dezelfde dubbele voorwaarde als proxyRegels.ts::isDocumentNavigatie.
NAVIGATIE_HEADERS = {"Accept": "text/html,application/xhtml+xml", "Sec-Fetch-Dest": "document"}
FETCH_HEADERS = {"Accept": "application/json", "Sec-Fetch-Dest": "empty"}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX_INHOUD)
    (build / "assets" / "app-abc123.js").write_text("console.log(1)")
    (build / "favicon.svg").write_text("<svg/>")
    (tmp_path / "geheim.txt").write_text("nooit serveren")
    return build


@pytest.fixture
def client(dist: Path) -> TestClient:
    app = FastAPI()

    @app.get("/bank/rekeningen")
    def rekeningen() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/verzamelbak")
    def verzamelbak() -> list[str]:
        return []

    activeer_frontend_serving(app, dist_map=str(dist))
    return TestClient(app)


def test_root_serveert_index_no_cache(client: TestClient) -> None:
    response = client.get("/", headers=NAVIGATIE_HEADERS)
    assert response.status_code == 200
    assert response.text == INDEX_INHOUD
    assert response.headers["cache-control"] == CACHE_OVERIG


def test_hashed_asset_immutable(client: TestClient) -> None:
    response = client.get("/assets/app-abc123.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == CACHE_ASSETS


def test_niet_gehasht_bestand_no_cache(client: TestClient) -> None:
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["cache-control"] == CACHE_OVERIG


def test_echte_api_route_gaat_voor(client: TestClient) -> None:
    response = client.get("/bank/rekeningen", headers=FETCH_HEADERS)
    assert response.json() == {"ok": True}
    response = client.get("/verzamelbak", headers=FETCH_HEADERS)
    assert response.json() == []


def test_fetch_onder_api_segment_geeft_json_404(client: TestClient) -> None:
    """De proxy-bugklasse ('Unexpected token <'): een fetch naar een onbestaand pad ónder een
    API-segment krijgt de JSON-404, nooit stil index.html."""
    response = client.get("/bank/onzin", headers=FETCH_HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_navigatie_onder_api_segment_geeft_spa(client: TestClient) -> None:
    """Randgeval kliktest 2026-08-08 (/bank/ met trailing slash): een document-navigatie hoort
    nooit bij de API uit te komen — zelfde bypass als de dev-proxy."""
    for pad in ("/bank/", "/bank/rekening/123"):
        response = client.get(pad, headers=NAVIGATIE_HEADERS)
        assert response.status_code == 200
        assert response.text == INDEX_INHOUD


def test_kaal_segment_en_spa_route_geven_spa(client: TestClient) -> None:
    """Een top-level pad kan óók een SPA-route zijn (/bank, /instellingen) — identiek aan dev,
    waar segment-keys mét slash gemonteerd zijn en het kale pad bij Vite blijft."""
    for pad in ("/bank", "/instellingen", "/accordeur"):
        response = client.get(pad, headers=FETCH_HEADERS)
        assert response.status_code == 200
        assert response.text == INDEX_INHOUD


def test_traversal_ontsnapt_nooit_aan_dist(client: TestClient, dist: Path) -> None:
    assert (dist.parent / "geheim.txt").exists()
    response = client.get("/..%2Fgeheim.txt", headers=FETCH_HEADERS)
    assert response.status_code == 200
    assert response.text == INDEX_INHOUD  # fallback, nooit het bestand buiten dist


def test_lege_dist_map_doet_niets(dist: Path) -> None:
    app = FastAPI()
    activeer_frontend_serving(app, dist_map="")
    client = TestClient(app)
    assert client.get("/onbekend").status_code == 404


def test_gezette_map_zonder_build_faalt_hard(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="frontend_dist_map"):
        activeer_frontend_serving(FastAPI(), dist_map=str(tmp_path / "leeg"))
