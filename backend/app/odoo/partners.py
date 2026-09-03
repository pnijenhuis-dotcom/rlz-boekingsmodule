"""Crediteur (res.partner) aanmaken in Odoo vanuit het controlescherm ("+ Nieuwe crediteur") — de Odoo-kant van
`app/sync/service.py::maak_crediteur_aan` (zelfde schrijf-failsafe: boeken-toggle + kill-switch, getoetst dáár).

Besluit Peter 02-09: partners zijn GROEPSGEDEELD (`company_id = False`) — lookup-vóór-create op btw-nummer →
KvK-nummer → exacte naam, idempotent, nooit per company dupliceren (STAP-0 §2.1). De nieuwe partner wordt direct in
`odoo_id_koppeling` vertaalbaar gemaakt en de vendor-cache-rij komt uit de aanroeper (gedeeld pad)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.db.session import scoped_session
from app.odoo.credentials import koppeling_voor, odoo_client_voor
from app.odoo.ids import odoo_uuid
from app.odoo.sync import MODEL_PARTNER, registreer_id_koppeling


@dataclass(frozen=True)
class OdooPartner:
    vendor_id: uuid.UUID
    odoo_id: int
    naam: str
    gevonden: bool


def zorg_voor_crediteur(
    *,
    administratie_id: uuid.UUID,
    naam: str,
    btw_nummer: str | None = None,
    kvk_nummer: str | None = None,
) -> OdooPartner:
    verbinding = koppeling_voor(administratie_id)
    with odoo_client_voor(administratie_id) as client:
        domein_kandidaten: list[list] = []
        if btw_nummer:
            domein_kandidaten.append([["vat", "=ilike", btw_nummer]])
        if kvk_nummer:
            domein_kandidaten.append([["company_registry", "=", kvk_nummer]])
        domein_kandidaten.append([["name", "=ilike", naam]])
        treffer = None
        for domein in domein_kandidaten:
            rijen = client.search_read(
                MODEL_PARTNER,
                [*domein, ["company_id", "in", [client.company_id, False]], ["active", "in", [True, False]]],
                ["name", "vat", "company_registry", "supplier_rank", "active"],
                limit=5,
            )
            if len(rijen) == 1:
                treffer = rijen[0]
                break
            if len(rijen) > 1:
                # Meerdere partners op dezelfde sleutel: geen gok — de nauwere sleutel hierboven had moeten winnen.
                continue
        gevonden = treffer is not None
        if treffer is None:
            vals = {
                "name": naam,
                "is_company": True,
                "supplier_rank": 1,
                "company_id": False,  # groepsgedeeld (besluit 02-09)
                "country_id": 165,  # Nederland (NL-crediteur; buitenland = handmatig in Odoo)
            }
            if btw_nummer:
                vals["vat"] = btw_nummer
            if kvk_nummer:
                vals["company_registry"] = kvk_nummer
            odoo_id = client.create(MODEL_PARTNER, vals)
            treffer = client.read_een(MODEL_PARTNER, odoo_id, ["name", "supplier_rank", "active"]) or {"id": odoo_id}
        else:
            odoo_id = int(treffer["id"])
            aanpassing: dict = {}
            if not treffer.get("supplier_rank"):
                aanpassing["supplier_rank"] = 1
            if not treffer.get("active", True):
                aanpassing["active"] = True
            if aanpassing:
                client.write(MODEL_PARTNER, [odoo_id], aanpassing)
    with scoped_session(administratie_id) as session:
        vendor_id = registreer_id_koppeling(
            session,
            administratie_id=administratie_id,
            company_id=verbinding.company_id,
            model=MODEL_PARTNER,
            odoo_id=odoo_id,
            naam=str(treffer.get("name") or naam),
        )
    assert vendor_id == odoo_uuid(verbinding.company_id, MODEL_PARTNER, odoo_id)
    return OdooPartner(vendor_id=vendor_id, odoo_id=odoo_id, naam=str(treffer.get("name") or naam), gevonden=gevonden)
