"""Fixtures voor de route-A-projectaanmaak (koppelcontract §5 v1.15): een nep-RlzClient met
het STAP-0-gedrag van de Projects-schrijfroute (poc_projects_schrijf.py, 2026-08-14) — het
project is customer-gebonden, PUT onder een onbekende customer is 404, PUT is create-or-update
en een minimaal aangemaakt project zou IsActive:false krijgen (de motor moet 'm dus expliciet
op true zetten)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401


class FakeProjectClient:
    """Simuleert precies de STAP-0-feiten; telt de schrijfacties zodat idempotentie-tests
    kunnen asserten dat een tweede aanvraag géén tweede PUT doet."""

    def __init__(self) -> None:
        self.customers: dict[str, str] = {}  # id → naam
        self.projects: dict[str, dict[str, Any]] = {}  # id → record
        self.put_project_aanroepen = 0
        self.put_customer_aanroepen = 0
        self.faal_bij_put_project = False
        self.faal_bij_lookup = False
        self.gesloten = False

    # --- leesroutes -----------------------------------------------------------------------
    def get_project(self, project_id: uuid.UUID | str) -> dict[str, Any] | None:
        if self.faal_bij_lookup:
            raise RlzApiError(500, "GET", f"/Projects/{project_id}", "kapot")
        return self.projects.get(str(project_id))

    def find_projects_by_name(self, *, name: str) -> list[dict[str, Any]]:
        return [p for p in self.projects.values() if p.get("Name") == name]

    def find_customers_by_name(self, *, name: str) -> list[dict[str, Any]]:
        return [{"id": cid, "Name": n} for cid, n in self.customers.items() if n == name]

    # --- schrijfroutes --------------------------------------------------------------------
    def put_customer(self, customer_id: uuid.UUID, *, name: str) -> None:
        self.put_customer_aanroepen += 1
        self.customers[str(customer_id)] = name

    def put_customer_project(
        self, customer_id: uuid.UUID, project_id: uuid.UUID, *, name: str, is_active: bool = True
    ) -> None:
        if self.faal_bij_put_project:
            raise RlzApiError(500, "PUT", f"/Customers/{customer_id}/Projects/{project_id}", "kapot")
        if str(customer_id) not in self.customers:
            # STAP-0 §4: PUT onder een niet-bestaande customer → 404, er ontstaat niets.
            raise RlzApiError(404, "PUT", f"/Customers/{customer_id}/Projects/{project_id}", "_NotFound")
        self.put_project_aanroepen += 1
        self.projects[str(project_id)] = {
            "id": str(project_id),
            "Name": name,
            "IsActive": is_active,
            "_customer": str(customer_id),
        }

    def close(self) -> None:
        self.gesloten = True


@pytest.fixture
def fake_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeProjectClient:
    """Eén gedeelde fake voor de hele test: de motor opent zijn client via de credential-
    resolutie — die wordt hier weggepatcht zodat er nooit echte credentials/HTTP nodig zijn."""
    import app.projecten.motor as motor_module

    fake = FakeProjectClient()
    monkeypatch.setattr(motor_module, "rlz_admin_id_voor", lambda admin_id: "fake-admin")
    monkeypatch.setattr(motor_module, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


@pytest.fixture
def vastgoed_administratie_id(administratie_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:  # noqa: F811
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id
