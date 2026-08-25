"""Same-origin frontend-serving (F2, app/static_frontend.py): de fallback-regels spiegelen de
dev-proxy (frontend/proxyRegels.ts) — bestand > document-navigatie > API-segment-404 > SPA.
Eigen mini-app per test (geen app.main): geen database, geen lifespan."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
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

    @app.get("/instellingen/administraties")
    def instellingen_administraties() -> JSONResponse:
        # Nabootsing van de echte beheer-route (auth-poort): zonder token 401-JSON.
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

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


def test_navigatie_op_pad_dat_ook_api_route_is_geeft_spa(client: TestClient) -> None:
    """Bugfix 2026-08-25 (kliktest Peter): verse load/refresh op /instellingen/administraties
    gaf de kale JSON "Not authenticated" — het SPA-pad viel exact samen met de beheer-route
    `GET /instellingen/administraties`, en een echte route wint altijd van de catch-all. De
    navigatie-middleware zit daarom VÓÓR de routing: navigatie → SPA, fetch → gewoon de API."""
    response = client.get("/instellingen/administraties", headers=NAVIGATIE_HEADERS)
    assert response.status_code == 200
    assert response.text == INDEX_INHOUD
    assert response.headers["cache-control"] == CACHE_OVERIG
    # De API zelf blijft onaangeroerd voor fetch/XHR.
    response = client.get("/instellingen/administraties", headers=FETCH_HEADERS)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_navigatie_naar_build_bestand_blijft_bestand(client: TestClient) -> None:
    """Een rechtstreeks geopend build-bestand (favicon, asset) is geen SPA-route."""
    response = client.get("/favicon.svg", headers=NAVIGATIE_HEADERS)
    assert response.status_code == 200
    assert response.text == "<svg/>"
    response = client.get("/assets/app-abc123.js", headers=NAVIGATIE_HEADERS)
    assert response.headers["cache-control"] == CACHE_ASSETS


def _vul_padparameters(pad: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", "x", pad)


def test_regressiesweep_elke_backend_get_route_geeft_bij_navigatie_de_spa(dist: Path) -> None:
    """Deze bugklasse mag niet terugkomen bij een volgende subpagina: voor ÉLKE GET-route uit de
    echte router (incl. alle huidige en toekomstige /instellingen/<sectie>-botsingen) levert een
    document-navigatie de SPA. Gebouwd op een verse app mét dezelfde paden als dummy-routes
    (zodat een echte route vóór de catch-all matcht — precies het productiegeval) en zónder
    database; faalt zodra de navigatie-middleware ontbreekt of een pad overslaat."""
    from app.main import app as echte_app
    from app.proxy_prefixes import _alle_paden

    # Élk router-pad als GET-dummy (strenger dan alleen de echte GET-routes: ook een pad dat
    # vandaag alleen POST is kan morgen een GET krijgen).
    get_paden = sorted(_alle_paden(echte_app))
    assert "/instellingen/administraties" in get_paden

    proef = FastAPI()
    for pad in get_paden:
        proef.add_api_route(
            pad,
            lambda: JSONResponse({"detail": "Not authenticated"}, status_code=401),
            methods=["GET"],
            name=f"dummy_{pad}",
        )
    activeer_frontend_serving(proef, dist_map=str(dist))
    client = TestClient(proef)

    fouten = []
    for pad in get_paden:
        concreet = _vul_padparameters(pad)
        response = client.get(concreet, headers=NAVIGATIE_HEADERS)
        if response.status_code != 200 or response.text != INDEX_INHOUD:
            fouten.append(f"{concreet} → {response.status_code}")
    assert not fouten, "Navigatie kwam bij de API uit i.p.v. de SPA:\n" + "\n".join(fouten)
    # Tegenproef: als fetch blijft de API-route gewoon de API.
    assert client.get("/instellingen/administraties", headers=FETCH_HEADERS).status_code == 401
