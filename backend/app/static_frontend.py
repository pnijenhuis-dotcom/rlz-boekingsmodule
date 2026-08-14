"""Same-origin frontend-serving (GCP-draaiboek F2.2, beslispunt 4): de backend serveert de
Vite-build zelf, zodat productie hetzelfde één-origin-padmodel heeft als dev (waar de
Vite-proxy dat doet). CORS verdwijnt, het refresh-cookie en de WebAuthn-origins worden één
domein, en de accordeur-PWA en de API delen één host.

De fallback-regels spiegelen bewust frontend/proxyRegels.ts (de dev-proxy) — één gedragsmodel,
geen productie-verrassingen op paden die in dev werkten:
- een bestaand build-bestand wordt geserveerd (hashed /assets/* immutable — de naam verandert
  bij elke build; al het niet-gehashte, incl. index.html en de PWA-manifest, no-cache);
- een document-NAVIGATIE (Accept: text/html én Sec-Fetch-Dest: document, zelfde dubbele
  voorwaarde als isDocumentNavigatie in proxyRegels.ts) krijgt áltijd de SPA — ook op
  /bank/ of een diepe link onder een API-segment (randgeval kliktest 2026-08-08);
- een fetch/XHR naar een onbekend pad ónder een API-segment (/bank/onzin) krijgt de JSON-404
  van de API, nooit stil index.html (de proxy-bugklasse: "Unexpected token '<'");
- al het overige (SPA-routes als /instellingen, onbekende top-level paden) valt terug op
  index.html — identiek aan Vite's SPA-fallback in dev.

De route registreert als allerlaatste catch-all: élke echte API-route matcht eerst. De
API-segmentenlijst komt uit dezelfde bron als de dev-proxy (app/proxy_prefixes.py), berekend
op het moment van activeren — dus altijd in de pas met de router, nooit een handmatig lijstje.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import settings
from app.proxy_prefixes import SPA_FALLBACK_PAD, bereken_prefixes

logger = logging.getLogger(__name__)

# Hashed assets: naam verandert bij elke build → een jaar immutable is veilig én maximaal snel.
CACHE_ASSETS = "public, max-age=31536000, immutable"
# Niet-gehasht (index.html, manifest, favicon, icons): no-cache = altijd hervalideren (ETag/
# Last-Modified van FileResponse), zodat een nieuwe deploy meteen de nieuwe index oplevert.
CACHE_OVERIG = "no-cache"


def is_document_navigatie(request: Request) -> bool:
    """Zelfde dubbele voorwaarde als proxyRegels.ts::isDocumentNavigatie: downloads via
    <a download> hebben dest 'empty', fetch/XHR stuurt geen text/html-accept."""
    accept = request.headers.get("accept", "")
    dest = request.headers.get("sec-fetch-dest", "")
    return "text/html" in accept and dest == "document"


def activeer_frontend_serving(app: FastAPI, dist_map: str | None = None) -> None:
    """Hang de SPA-fallback-route aan de app — aanroepen ná álle include_router-calls (de
    catch-all mag nooit vóór een echte route matchen). `dist_map`-parameter alleen voor tests;
    productie stuurt op settings.frontend_dist_map (leeg = dev, geen serving)."""
    map_setting = dist_map if dist_map is not None else settings.frontend_dist_map
    if not map_setting:
        return
    dist = Path(map_setting).resolve()
    index = dist / "index.html"
    if not index.is_file():
        # Fail-fast: een gezette map zonder build is een verpakkingsfout — luid weigeren bij
        # startup, nooit een draaiende service die op elk pad een kale 404 geeft.
        raise RuntimeError(f"frontend_dist_map wijst niet naar een Vite-build: {index} ontbreekt")

    api_segmenten = set(bereken_prefixes(app)["segmenten"])

    def _index_response() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": CACHE_OVERIG})

    @app.get(SPA_FALLBACK_PAD, include_in_schema=False, name="spa_fallback")
    def spa_fallback(spa_pad: str, request: Request) -> FileResponse:
        if spa_pad:
            bestand = (dist / spa_pad).resolve()
            # resolve + is_relative_to = traversal-guard: niets buiten de build-map serveren.
            if bestand.is_relative_to(dist) and bestand.is_file():
                cache = CACHE_ASSETS if spa_pad.startswith("assets/") else CACHE_OVERIG
                return FileResponse(bestand, headers={"Cache-Control": cache})
        if is_document_navigatie(request):
            return _index_response()
        if "/" in spa_pad and f"/{spa_pad.split('/', 1)[0]}" in api_segmenten:
            # Fetch naar een onbestaand pad ónder een API-segment: dezelfde JSON-404 als de
            # API zelf zou geven — nooit stil index.html (JSON.parse-bugklasse).
            raise HTTPException(status_code=404, detail="Not Found")
        return _index_response()

    logger.info("Frontend-serving actief vanuit %s (%d API-segmenten uitgesloten)", dist, len(api_segmenten))
