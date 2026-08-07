"""Basis voor request-body-modellen (Vastly-port b, 2026-08-07).

`extra="forbid"`: een onbekend of verkeerd gespeld veld in een request-body is een 422 met
veldnaam, nooit stil genegeerd. Zonder dit slikt pydantic (default `extra="ignore"`) een typefout
als `ingeschekeld` geruisloos door — de aanroeper denkt dat z'n instelling is opgeslagen terwijl
er niets gebeurde; precies de bugklasse die bij Vastly de "checkbox sloeg nooit op"-regressie gaf.

Alle In-/Input-/Patch-/Request-modellen (en Dto's die als PUT-body dienen) erven hiervan;
tests/unit/test_model_repo_drift.py::TestStrikteInvoer dwingt dat af voor nieuwe modellen.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrikteInvoer(BaseModel):
    model_config = ConfigDict(extra="forbid")
