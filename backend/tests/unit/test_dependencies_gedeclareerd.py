"""Requirements-check (feedbackronde 25-08 deel 3, punt 2): élke third-party import in app/ moet
als dependency in pyproject.toml gedeclareerd staan — het productiebeeld installeert uitsluitend
die lijst (backend/Dockerfile), een lokaal 'toevallig' aanwezig pakket (bv. Pillow via een ander
project) zou pas in Cloud Run met een ImportError opvallen."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

# Importnaam → distributienaam waar packages_distributions() het niet zelf kan herleiden.
_BEKENDE_AFWIJKINGEN = {"PIL": "pillow", "pillow_heif": "pillow-heif", "jwt": "pyjwt", "dotenv": "python-dotenv"}


def _normaliseer(naam: str) -> str:
    return re.sub(r"[-_.]+", "-", naam).lower()


def _gedeclareerd() -> set[str]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]
    regels = list(project["dependencies"]) + [d for extra in project["optional-dependencies"].values() for d in extra]
    return {_normaliseer(re.split(r"[\[><=!~; ]", regel, maxsplit=1)[0]) for regel in regels}


def _top_level_imports() -> set[str]:
    namen: set[str] = set()
    for pad in (BACKEND / "app").rglob("*.py"):
        boom = ast.parse(pad.read_text(), filename=str(pad))
        for knoop in ast.walk(boom):
            if isinstance(knoop, ast.Import):
                namen.update(alias.name.split(".")[0] for alias in knoop.names)
            elif isinstance(knoop, ast.ImportFrom) and knoop.module and knoop.level == 0:
                namen.add(knoop.module.split(".")[0])
    return namen - set(sys.stdlib_module_names) - {"app"}


def test_elke_third_party_import_is_gedeclareerd() -> None:
    gedeclareerd = _gedeclareerd()
    distributies = packages_distributions()
    ontbrekend: dict[str, list[str]] = {}
    for importnaam in sorted(_top_level_imports()):
        kandidaten = {_normaliseer(d) for d in distributies.get(importnaam, [])}
        if importnaam in _BEKENDE_AFWIJKINGEN:
            kandidaten.add(_BEKENDE_AFWIJKINGEN[importnaam])
        if not kandidaten & gedeclareerd:
            ontbrekend[importnaam] = sorted(kandidaten)
    assert not ontbrekend, (
        "Third-party imports zonder dependency in backend/pyproject.toml "
        f"(importnaam → geïnstalleerde distributies): {ontbrekend}"
    )


def test_afbeeldingsdependencies_expliciet() -> None:
    gedeclareerd = _gedeclareerd()
    assert {"pillow", "pillow-heif"} <= gedeclareerd
