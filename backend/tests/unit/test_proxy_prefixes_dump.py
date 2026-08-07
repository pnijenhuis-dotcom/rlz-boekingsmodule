"""Drift-guard router ↔ frontend/proxy-prefixes.json (proxy-bugklasse, derde herhaling
browserreview 2026-08-07). Zelfde patroon als de migratie-metadata-guard: het gegenereerde
bestand is een gecommitte referentie; zodra de router een nieuwe top-level prefix krijgt faalt
deze test met de verversinstructie — de Vite-dev-proxy kan dan nooit meer stil achterlopen."""

from __future__ import annotations

import json

from app.main import app
from app.proxy_prefixes import JSON_PAD, bereken_prefixes


def test_proxy_prefixes_json_in_sync_met_router() -> None:
    assert JSON_PAD.exists(), (
        f"{JSON_PAD} ontbreekt — genereer 'm met: (cd backend && .venv/bin/python -m app.proxy_prefixes)"
    )
    op_schijf = json.loads(JSON_PAD.read_text())
    verwacht = bereken_prefixes(app)
    assert op_schijf == verwacht, (
        "frontend/proxy-prefixes.json loopt uit de pas met de backend-router — "
        "ververs 'm met: (cd backend && .venv/bin/python -m app.proxy_prefixes) "
        "en commit het resultaat mee."
    )


def test_bekende_schermen_gedekt() -> None:
    """Regressie op de twee schermen die op 2026-08-07 stuk waren (bank-overzicht en
    verzamelbak): hun prefixes moeten uit de router blijven rollen."""
    prefixes = bereken_prefixes(app)
    assert "/bank" in prefixes["segmenten"]
    assert "/intake" in prefixes["segmenten"]
    assert "/verzamelbak" in prefixes["exacte_paden"]
