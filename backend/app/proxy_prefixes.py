"""Bron van waarheid voor de Vite-dev-proxy (proxy-bugklasse, derde herhaling browserreview
2026-08-07): een backend-prefix die in vite.config.ts ontbreekt valt in dev stil terug op Vite's
SPA-fallback — de fetch krijgt index.html met status 200 en de fout wordt pas zichtbaar als
JSON.parse faalt ("Unexpected token '<'"). Het handmatige prefixlijstje in vite.config.ts was de
structurele oorzaak; dit module berekent de lijst daarom UIT de router zelf.

Ketting: `python -m app.proxy_prefixes` schrijft frontend/proxy-prefixes.json →
vite.config.ts bouwt daar zijn proxy-map uit → twee guards houden alles in de pas:
- backend: tests/unit/test_proxy_prefixes_dump.py (router ↔ JSON-drift);
- frontend: src/api/proxyDekking.test.ts (élk aangeroepen API-pad ↔ JSON-dekking, automatisch
  over alle bronbestanden — geen handmatig lijstje meer).

`segmenten` worden in vite.config.ts bewust als '/segment/'-keys (mét slash) gemonteerd: een
top-level pad kan óók een SPA-route zijn (/instellingen, /bank) en een document-navigatie mag
nooit naar de backend. Paden die de backend exact op één segment serveert (bv. /verzamelbak)
komen apart mee als `exacte_paden`.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI

JSON_PAD = Path(__file__).resolve().parents[2] / "frontend" / "proxy-prefixes.json"

# Documentatie-/schema-routes die de browser-frontend nooit aanroept.
_UITGESLOTEN = {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}

# Route-pad van de SPA-fallback (app/static_frontend.py, F2 same-origin-serving). Leeft hier
# als constante zodat _alle_paden 'm kan uitsluiten zonder circulaire import: de fallback is
# per definitie géén API-route en zou anders als onzin-segment in de proxy-dump belanden
# zodra iemand frontend_dist_map in dev aanzet.
SPA_FALLBACK_PAD = "/{spa_pad:path}"


def _alle_paden(app: FastAPI) -> set[str]:
    """Alle geregistreerde route-paden, ook die van include_router-subrouters (deze
    FastAPI-versie hangt die als lazy _IncludedRouter in app.routes, zonder eigen .path)."""
    paden: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paden.add(route.path)
        elif hasattr(route, "original_router"):
            prefix = getattr(route.include_context, "prefix", "") or ""
            for sub in route.original_router.routes:
                paden.add(prefix + sub.path)
    # Underscore-prefix = intern/test-only (bv. de /_test-route die de CORS-vangnettest aan de
    # gedeelde app hangt) — hoort nooit in de browser-proxy en zou de drift-guard
    # volgorde-afhankelijk maken. De SPA-fallback (F2) is evenmin een API-route.
    return {pad for pad in paden if not pad.startswith("/_") and pad != SPA_FALLBACK_PAD} - _UITGESLOTEN


def bereken_prefixes(app: FastAPI) -> dict[str, object]:
    paden = _alle_paden(app)
    return {
        "_toelichting": (
            "GEGENEREERD uit de backend-router — nooit met de hand bewerken. "
            "Verversen: (cd backend && .venv/bin/python -m app.proxy_prefixes). "
            "Drift-guards: backend tests/unit/test_proxy_prefixes_dump.py, "
            "frontend src/api/proxyDekking.test.ts."
        ),
        "segmenten": sorted({"/" + pad.split("/")[1] for pad in paden}),
        "exacte_paden": sorted(pad for pad in paden if pad.count("/") == 1),
    }


def schrijf_json() -> Path:
    from app.main import app

    JSON_PAD.write_text(json.dumps(bereken_prefixes(app), indent=2, ensure_ascii=False) + "\n")
    return JSON_PAD


if __name__ == "__main__":
    print(f"Geschreven: {schrijf_json()}")
