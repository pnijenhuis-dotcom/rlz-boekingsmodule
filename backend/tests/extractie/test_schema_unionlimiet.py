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

from app.extractie import contract, rapport, service, splitsing
from app.voorraad import normalisatie

# Anthropic's harde limiet (foutmelding 30-08): max 16 parameters met union types
# (anyOf/oneOf of een type-array met meerdere typen).
ANTHROPIC_UNION_LIMIET = 16


def tel_union_parameters(schema: dict[str, Any]) -> int:
    """Telt zoals Anthropic telt: elke property (op elk nestniveau, array-items meegerekend)
    waarvan het deelschema een union is — `anyOf`/`oneOf`, of `type` als lijst met meer dan
    één type. Elke property telt één keer, ook al genereert een dict-comprehension er twaalf."""

    def is_union(deelschema: Any) -> bool:
        if not isinstance(deelschema, dict):
            return False
        if "anyOf" in deelschema or "oneOf" in deelschema:
            return True
        soort = deelschema.get("type")
        return isinstance(soort, list) and len(soort) > 1

    def loop(deelschema: Any) -> int:
        if not isinstance(deelschema, dict):
            return 0
        aantal = 0
        for prop in (deelschema.get("properties") or {}).values():
            if is_union(prop):
                aantal += 1
            aantal += loop(prop)
        aantal += loop(deelschema.get("items"))
        return aantal

    return loop(schema)


# Álle live schema's die naar de Claude API gaan. Nieuw AI-schema? Hier toevoegen —
# de sweep-test hieronder dwingt dat af.
LIVE_SCHEMAS: dict[str, dict[str, Any]] = {
    "inkoop FACTUUR_SCHEMA": service.FACTUUR_SCHEMA,
    "inkoop KOP_SCHEMA": service.KOP_SCHEMA,
    "inkoop REGELS_SCHEMA": service.REGELS_SCHEMA,
    "kassarapport RAPPORT_SCHEMA": rapport.RAPPORT_SCHEMA,
    "intake SPLITSING_SCHEMA": splitsing.SPLITSING_SCHEMA,
    "contract CONTRACT_SCHEMA": contract.CONTRACT_SCHEMA,
    "voorraad _NORMALISATIE_SCHEMA": normalisatie._NORMALISATIE_SCHEMA,
}

# Modules die json_schema= aan de client meegeven; client.py zelf is infra (geeft alleen door).
_GEDEKTE_MODULES = {
    "app/extractie/service.py",
    "app/extractie/rapport.py",
    "app/extractie/splitsing.py",
    "app/extractie/contract.py",
    "app/extractie/client.py",
    "app/voorraad/normalisatie.py",
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
