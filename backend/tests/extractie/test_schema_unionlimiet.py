"""Testpoort op Anthropic's union-limiet voor structured outputs (bugfix 31-08).

Sinds de voorraad-v2-deploy (30-08) faalde élke intake-extractie met een 400: het
inkoop-regelschema was met e/p/a gegroeid naar 19 nullable/union-parameters, terwijl
Anthropic er maximaal 16 toestaat ("Schemas contains too many parameters with union
types … limit: 16"). De fix (app/extractie/service.py): tekstvelden verplicht `string`
mét lege string als "onbekend"-sentinel, deterministisch naar None genormaliseerd.

Deze module bewaakt twee dingen:
1. Élk live AI-schema blijft onder de limiet — een volgend veld dat als union wordt
   toegevoegd, faalt hier vóór het de keten platlegt.
2. Elke module die `json_schema=` aan de ClaudeExtractieClient meegeeft, staat in de
   gedekte lijst (fail-closed sweep) — een níéuw AI-schema zonder testpoort is rood.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from app.extractie import service
from app.extractie.schema_poort import (
    ANTHROPIC_UNION_LIMIET,
    controleer_live_schemas,
    live_schemas,
    tel_union_parameters,
)

# Teller, limiet én de schema-lijst leven sinds de bewaking (31-08) runtime in
# app/extractie/schema_poort.py (de AI-probe en de deploy-smoketest draaien dezelfde
# zelftest) — deze module blijft de testpoort en bewaakt dat elke aanroeper gedekt is.
LIVE_SCHEMAS: dict[str, dict[str, Any]] = live_schemas()

# Modules die json_schema= aan de client meegeven; client.py zelf is infra (geeft alleen door).
_GEDEKTE_MODULES = {
    "app/extractie/service.py",
    "app/extractie/rapport.py",
    "app/extractie/splitsing.py",
    "app/extractie/contract.py",
    "app/extractie/verplichting.py",  # verplichting-extractie (04-09), VERPLICHTING_SCHEMA in live_schemas
    "app/extractie/client.py",
    "app/voorraad/normalisatie.py",
    "app/bewaking/service.py",
    "app/geheugen/regel_gb.py",  # regel-GB-classificatie (blok D 04-09), CLASSIFICATIE_SCHEMA in live_schemas
}


def test_teller_herkent_de_unionvormen() -> None:
    """Zelftest van de teller op precies de vormen die Anthropic meetelt — anders bewaakt
    de poort hieronder stilletjes niets."""
    schema = {
        "type": "object",
        "properties": {
            "any_of": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "type_array": {"type": ["string", "null"]},
            "gewoon": {"type": "string"},
            "genest": {
                "type": "object",
                "properties": {"binnen": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
            },
            "lijst": {
                "type": "array",
                "items": {"type": "object", "properties": {"item_union": {"type": ["number", "null"]}}},
            },
        },
    }
    assert tel_union_parameters(schema) == 4


@pytest.mark.parametrize("naam", sorted(LIVE_SCHEMAS))
def test_live_schema_onder_de_anthropic_unionlimiet(naam: str) -> None:
    aantal = tel_union_parameters(LIVE_SCHEMAS[naam])
    assert aantal <= ANTHROPIC_UNION_LIMIET, (
        f"{naam} heeft {aantal} union-/nullable-parameters — boven Anthropic's limiet van "
        f"{ANTHROPIC_UNION_LIMIET}: élke extractie via dit schema faalt dan met een 400 "
        "(zie 30-08). Maak het veld verplicht mét lege-string-sentinel (patroon "
        "app/extractie/service.py) in plaats van nullable."
    )


def test_inkoopschema_is_union_vrij() -> None:
    """Het gefixte factuurschema is volledig sentinel-gebaseerd — 0 unions, maximale marge.
    Groeit dit weer, dan is dat een bewuste keuze die hier zichtbaar hoort te worden."""
    assert tel_union_parameters(service.FACTUUR_SCHEMA) == 0


def test_runtime_zelftest_is_schoon() -> None:
    """De runtime-zelftest (AI-probe + deploy-smoketest) hoort op de huidige schema's niets te
    melden — meldt hij wél iets, dan faalt de parametrized poort hierboven ook."""
    assert controleer_live_schemas() == []


def test_sweep_elke_json_schema_aanroeper_is_gedekt() -> None:
    """Fail-closed: een nieuwe module die `json_schema=` gebruikt zonder dat zijn schema in
    LIVE_SCHEMAS staat, faalt hier — de union-limiet-bug mag niet stil terugkomen via een
    zesde AI-schema."""
    app_root = Path(service.__file__).resolve().parents[1]
    aanroepers = {
        str(pad.relative_to(app_root.parent)).replace("\\", "/")
        for pad in app_root.rglob("*.py")
        if re.search(r"json_schema\s*=", pad.read_text(encoding="utf-8"))
    }
    onbekend = aanroepers - _GEDEKTE_MODULES
    assert not onbekend, (
        f"Nieuwe json_schema-aanroeper(s) zonder union-limiet-testpoort: {sorted(onbekend)} — "
        "voeg het schema toe aan LIVE_SCHEMAS in deze test."
    )
