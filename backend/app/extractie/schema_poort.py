"""Runtime-zelftest op Anthropic's union-limiet voor structured outputs (bewaking 31-08).

De teller en de limiet leefden sinds de bugfix 31-08 alleen in de testsuite
(tests/extractie/test_schema_unionlimiet.py) — maar de schema-bug van 30-08 stond ruim een dag
onopgemerkt in productie. Daarom leeft de poort sindsdien hiér (runtime aanroepbaar door de
bewakingsprobe én de post-deploy-smoketest); de testsuite importeert dezelfde functies zodat
test en runtime nooit uit de pas lopen.
"""

from __future__ import annotations

from typing import Any

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


def live_schemas() -> dict[str, dict[str, Any]]:
    """Álle live schema's die naar de Claude API gaan — nieuw AI-schema? Hier toevoegen (de
    fail-closed sweep in tests/extractie/test_schema_unionlimiet.py dwingt dat af). Lazy
    imports: deze module moet importeerbaar blijven zonder de hele extractieketen te laden."""
    from app.bewaking.service import AI_PROBE_SCHEMA
    from app.extractie import contract, rapport, service, splitsing
    from app.voorraad import normalisatie

    return {
        "inkoop FACTUUR_SCHEMA": service.FACTUUR_SCHEMA,
        "inkoop KOP_SCHEMA": service.KOP_SCHEMA,
        "inkoop REGELS_SCHEMA": service.REGELS_SCHEMA,
        "kassarapport RAPPORT_SCHEMA": rapport.RAPPORT_SCHEMA,
        "intake SPLITSING_SCHEMA": splitsing.SPLITSING_SCHEMA,
        "contract CONTRACT_SCHEMA": contract.CONTRACT_SCHEMA,
        "voorraad _NORMALISATIE_SCHEMA": normalisatie._NORMALISATIE_SCHEMA,
        "bewaking AI_PROBE_SCHEMA": AI_PROBE_SCHEMA,
    }


def controleer_live_schemas() -> list[str]:
    """Zelftest: geeft per overtreding een leesbare regel terug (leeg = alles onder de limiet).
    Aangeroepen door de bewakings-AI-probe (1×/uur) en de deploy-smoketest — de 30-08-klasse
    (schema boven de limiet = élke extractie faalt met een 400) wordt zo binnen het uur
    respectievelijk vóór de deploy zichtbaar."""
    overtredingen: list[str] = []
    for naam, schema in live_schemas().items():
        aantal = tel_union_parameters(schema)
        if aantal > ANTHROPIC_UNION_LIMIET:
            overtredingen.append(f"{naam}: {aantal} union-parameters (limiet {ANTHROPIC_UNION_LIMIET})")
    return overtredingen
