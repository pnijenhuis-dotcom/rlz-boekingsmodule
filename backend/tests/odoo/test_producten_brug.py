# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo)
"""Materiaalcatalogus → product.product-brug (`app/odoo/producten.py::leg_brug`) ZONDER uren-&-meerwerk-opt-in
(Odoo-afrondingsrun 04-09 blok B): `koppeling_voor` is de enige poort; catalogus vullen op een Odoo-administratie
werkt zonder opt-in; brug idempotent (lookup op default_code, aanmaak éénmalig, audit per aanmaak); RLZ zonder
Odoo = fail-loud `GeenOdooKoppeling`; alleen-lezen client = zichtbaar overgeslagen, geen crash. Nep-client —
geen netwerk, geen Odoo-writes."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text

from app.db.session import scoped_session
from app.materiaal import service as materiaal
from app.odoo import producten
from app.odoo.client import OdooAlleenLezen
from app.odoo.credentials import GeenOdooKoppeling
from app.odoo.models import OdooProductKoppeling
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.materiaal.test_catalogus_toegang import administratie_leesbron, administratie_odoo  # noqa: F401
from tests.uren.conftest import administratie_id  # noqa: F401


class NepOdooClient:
    """Minimale product.template/product.product-simulatie: default_code-lookup, naam-lookup, aanmaak."""

    def __init__(self, *, read_only: bool = False) -> None:
        self.company_id = 1
        self.read_only = read_only
        self.producten: dict[int, dict[str, Any]] = {}
        self.creates: list[dict[str, Any]] = []
        self.gesloten = False
        self._n = 100

    def search_read(self, model: str, domain: list, fields: list[str], **_: Any) -> list[dict[str, Any]]:
        if model == "uom.uom":
            return [{"id": 1, "name": "Units"}, {"id": 8, "name": "m"}, {"id": 10, "name": "m²"}]
        if model == "product.category":
            return []
        assert model == "product.product"
        veld, _op, waarde = domain[0]
        if veld == "default_code":
            return [p for p in self.producten.values() if p["default_code"] == waarde]
        if veld == "name":
            return [p for p in self.producten.values() if p["name"].casefold() == str(waarde).casefold()]
        if veld == "product_tmpl_id":
            return [p for p in self.producten.values() if p["product_tmpl_id"][0] == waarde]
        return []

    def create(self, model: str, vals: dict[str, Any]) -> int:
        if self.read_only:
            raise OdooAlleenLezen("read-only")
        assert model == "product.template"
        assert vals["company_id"] == self.company_id and vals["type"] == "consu" and vals["purchase_ok"] is True
        self._n += 1
        tmpl = self._n
        pid = tmpl + 1000
        self.producten[pid] = {
            "id": pid,
            "name": vals["name"],
            "default_code": vals["default_code"],
            "product_tmpl_id": [tmpl, vals["name"]],
        }
        self.creates.append(vals)
        return tmpl

    def close(self) -> None:
        self.gesloten = True


def _aantal_koppelingen(aid: uuid.UUID, actor: uuid.UUID) -> int:
    with scoped_session(aid, actor_id=actor) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(OdooProductKoppeling)
                .where(OdooProductKoppeling.administratie_id == aid)
            )
            or 0
        )


def _audit_acties(admin_engine: Engine, aid: uuid.UUID) -> list[str]:
    with admin_engine.begin() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event "
                    "WHERE administratie_id = :aid AND tabel = 'odoo_product_koppeling'"
                ),
                {"aid": aid},
            )
        ]


class TestBrugZonderUrenOptIn:
    def test_catalogus_vullen_en_brug_leggen_zonder_uren_optin_idempotent(
        self, administratie_odoo, beheerder_id, admin_engine
    ):
        # Stap 5 van de live keten 04-09: dit vereiste vóór blok B de uren-opt-in.
        materiaal.seed_universal(administratie_id=administratie_odoo, actor_id=beheerder_id)
        nep = NepOdooClient()
        u1 = producten.leg_brug(administratie_id=administratie_odoo, actor_id=beheerder_id, client=nep)
        assert (u1.aangemaakt, u1.gevonden, u1.overgeslagen) == (53, 0, [])
        assert nep.gesloten is False  # meegegeven client wordt niet gesloten
        assert _aantal_koppelingen(administratie_odoo, beheerder_id) == 53
        assert all(v["default_code"].startswith("AKN-") for v in nep.creates)
        assert {v["uom_id"] for v in nep.creates} <= {1, 8, 10}
        assert _audit_acties(admin_engine, administratie_odoo).count("odoo_product_aangemaakt") == 53
        # Tweede run: alles al gekoppeld → gevonden, niets aangemaakt.
        u2 = producten.leg_brug(administratie_id=administratie_odoo, actor_id=beheerder_id, client=nep)
        assert (u2.aangemaakt, u2.gevonden, len(nep.creates)) == (0, 53, 53)

    def test_bestaand_odoo_product_op_default_code_wordt_gevonden_niet_aangemaakt(
        self, administratie_odoo, beheerder_id
    ):
        lid = materiaal.zet_leverancier(
            administratie_id=administratie_odoo,
            actor_id=beheerder_id,
            leverancier_id=None,
            naam="Floor Liften",
            bestel_email=None,
            telefoon=None,
            adres=None,
            vendor_id=None,
        )
        cid = materiaal.zet_categorie(
            administratie_id=administratie_odoo,
            actor_id=beheerder_id,
            leverancier_id=lid,
            categorie_id=None,
            naam="Liften",
            bundel="overig",
            volgorde=1,
        )
        pid = materiaal.zet_product(
            administratie_id=administratie_odoo,
            actor_id=beheerder_id,
            leverancier_id=lid,
            product_id=None,
            categorie_id=cid,
            naam="Bouwlift 500 kg",
            verpakking="st.",
            eenheid="stuks",
            m2_lengte=None,
            volgorde=1,
        )
        nep = NepOdooClient()
        nep.producten[5001] = {
            "id": 5001,
            "name": "Bouwlift 500 kg (Odoo)",
            "default_code": producten.product_code(pid),
            "product_tmpl_id": [4001, "x"],
        }
        u = producten.leg_brug(administratie_id=administratie_odoo, actor_id=beheerder_id, client=nep)
        assert (u.gevonden, u.aangemaakt, nep.creates) == (1, 0, [])
        with scoped_session(administratie_odoo, actor_id=beheerder_id) as session:
            k = session.scalars(
                select(OdooProductKoppeling).where(OdooProductKoppeling.materiaal_product_id == pid)
            ).one()
            assert (k.odoo_product_id, k.odoo_template_id, k.bron) == (5001, 4001, "gevonden")

    def test_rlz_administratie_zonder_odoo_koppeling_is_fail_loud(self, administratie_id, beheerder_id):
        with pytest.raises(GeenOdooKoppeling):
            producten.leg_brug(administratie_id=administratie_id, actor_id=beheerder_id, client=NepOdooClient())

    def test_leesbron_koppeling_lookup_mag_aanmaak_zichtbaar_overgeslagen(self, administratie_leesbron, beheerder_id):
        """Alleen-lezen koppeling (blok D) = read-only client: `koppeling_voor` laat 'm door, bestaande producten
        worden gekoppeld, aanmaak wordt per product zichtbaar overgeslagen — nooit een stille crash."""
        lid = materiaal.zet_leverancier(
            administratie_id=administratie_leesbron,
            actor_id=beheerder_id,
            leverancier_id=None,
            naam="Floor Liften",
            bestel_email=None,
            telefoon=None,
            adres=None,
            vendor_id=None,
        )
        cid = materiaal.zet_categorie(
            administratie_id=administratie_leesbron,
            actor_id=beheerder_id,
            leverancier_id=lid,
            categorie_id=None,
            naam="Liften",
            bundel="overig",
            volgorde=1,
        )
        for naam in ("Bouwlift 500 kg", "Bouwlift 1000 kg"):
            materiaal.zet_product(
                administratie_id=administratie_leesbron,
                actor_id=beheerder_id,
                leverancier_id=lid,
                product_id=None,
                categorie_id=cid,
                naam=naam,
                verpakking="st.",
                eenheid="stuks",
                m2_lengte=None,
                volgorde=1,
            )
        nep = NepOdooClient(read_only=True)
        nep.producten[7001] = {
            "id": 7001,
            "name": "Bouwlift 500 kg",
            "default_code": "X",
            "product_tmpl_id": [6001, "x"],
        }
        u = producten.leg_brug(administratie_id=administratie_leesbron, actor_id=beheerder_id, client=nep)
        assert (u.gevonden, u.aangemaakt) == (1, 0)
        assert u.overgeslagen == ["Bouwlift 1000 kg: alleen-lezen Odoo-koppeling — niet aangemaakt"]
        assert _aantal_koppelingen(administratie_leesbron, beheerder_id) == 1
