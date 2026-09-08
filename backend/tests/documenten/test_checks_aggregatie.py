"""Blok 4d (08-09): de melding van "Verplichte velden" aggregeert per veld i.p.v. elke regel op te sommen (Spot
Services: 12 regels × 3 velden = 36 fragmenten). Eén regel houdt de bestaande vorm "(regel i)" (bestaande tests/UI)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.documenten.checks import CheckRegel, _regelplekken, check_verplichte_velden


def _regel(ledger: bool = True, taxrate: bool = True, project: bool = True) -> CheckRegel:
    return CheckRegel(
        ledger_id=uuid.uuid4() if ledger else None,
        taxrate_id=uuid.uuid4() if taxrate else None,
        project_id=uuid.uuid4() if project else None,
        netto_bedrag=Decimal("10"),
        btw_bedrag=Decimal("0"),
    )


def _check(regels: list[CheckRegel]) -> str:
    return check_verplichte_velden(
        vendor_id=uuid.uuid4(),
        referentie="F1",
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal("30"),
        regels=regels,
        project_verplicht=True,
    ).melding


def test_regelplekken() -> None:
    assert _regelplekken([3], 12) == "(regel 3)"
    assert _regelplekken([1, 2, 3], 3) == "(alle 3 regels)"
    assert _regelplekken([1, 3, 5], 12) == "(regel 1, 3, 5)"
    assert _regelplekken([1, 2, 3, 4, 5, 6, 7], 12) == "(7 regels: 1, 2, 3, 4, …)"
    assert _regelplekken([1], 1) == "(regel 1)"


def test_alles_leeg_op_elf_regels_is_drie_fragmenten() -> None:
    melding = _check([_regel(False, False, False) for _ in range(11)])
    assert melding.startswith(
        "Ontbrekend: grootboekrekening (alle 11 regels), btw-code (alle 11 regels), project (alle 11 regels)"
    )
    assert "Verdelen over projecten" in melding
    assert "(regel 1)" not in melding


def test_een_regel_houdt_de_oude_vorm() -> None:
    melding = _check([_regel(), _regel(project=False)])
    assert melding == (
        "Ontbrekend: project (regel 2) — kies per regel een project óf gebruik "
        '"Verdelen over projecten…" onder de boekingsregels'
    )


def test_deel_van_de_regels_noemt_de_nummers() -> None:
    melding = _check([_regel(ledger=False), _regel(), _regel(ledger=False), _regel()])
    assert melding == "Ontbrekend: grootboekrekening (regel 1, 3)"
