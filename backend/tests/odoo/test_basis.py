"""Pure logica van de Odoo-adapter (geen DB, geen HTTP): id-vertaling, sentinel, stamgegevens-mapping,
boekdatum-besluit + tegenboek-lock-poort, foutvertaling, btw-override-tolerantie, marker."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.odoo import sync as odoo_sync
from app.odoo.client import OdooFout
from app.odoo.credentials import OdooVerbinding
from app.odoo.fouten import lock_date_melding, vertaal_odoo_fout
from app.odoo.ids import GEEN_BTW_ODOO_ID, is_odoo_sentinel, odoo_admin_sentinel, odoo_uuid
from app.odoo.inkoop import BTW_OVERRIDE_TOLERANTIE, OdooInkoopPort, marker
from app.odoo.producten import product_code
from app.rlz.credentials import GeenRlzCredentials, resolve_credentials


class TestIds:
    def test_odoo_uuid_is_deterministisch_en_per_company_en_model_verschillend(self) -> None:
        a = odoo_uuid(1, "account.move", 3049)
        assert a == odoo_uuid(1, "account.move", 3049)
        assert a != odoo_uuid(3, "account.move", 3049)
        assert a != odoo_uuid(1, "res.partner", 3049)
        assert a.version == 5

    def test_sentinel_vorm_en_herkenning(self) -> None:
        s = odoo_admin_sentinel("https://universal-steigers.odoo.com/", 1)
        assert s == "odoo:universal-steigers.odoo.com:1"
        assert is_odoo_sentinel(s)
        assert not is_odoo_sentinel("3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac")
        assert not is_odoo_sentinel(None)

    def test_rlz_credential_resolutie_op_sentinel_is_fail_loud(self) -> None:
        with pytest.raises(GeenRlzCredentials, match="draait op Odoo"):
            resolve_credentials(odoo_admin_sentinel("https://x.odoo.com", 7))

    def test_marker_draagt_document_cyclus_en_soort(self) -> None:
        d = uuid.uuid4()
        assert marker(d, 0) == f"AKN:{d}:0:boeking"
        assert marker(d, 2, "tegenboeking") == f"AKN:{d}:2:tegenboeking"

    def test_product_code_deterministisch(self) -> None:
        p = uuid.UUID("12345678-aaaa-bbbb-cccc-000000000000")
        assert product_code(p) == "AKN-12345678"


class TestStamgegevensMapping:
    @pytest.mark.parametrize(
        ("account_type", "soort"),
        [
            ("income", 1),
            ("income_other", 1),
            ("expense", 2),
            ("expense_direct_cost", 2),
            ("expense_depreciation", 2),
            ("asset_current", 3),
            ("asset_receivable", 3),
            ("asset_cash", 3),
            ("liability_payable", 4),
            ("liability_current", 4),
            ("equity", 4),
            ("equity_unaffected", 4),
            ("off_balance", None),
            (None, None),
        ],
    )
    def test_soort_voor_account_type(self, account_type: str | None, soort: int | None) -> None:
        assert odoo_sync.soort_voor_account_type(account_type) == soort

    def test_verlegd_op_negatieve_tax_repartition(self) -> None:
        rep = {
            1: {"repartition_type": "base", "factor_percent": 100.0},
            2: {"repartition_type": "tax", "factor_percent": 100.0},
            3: {"repartition_type": "tax", "factor_percent": -100.0},
        }
        assert odoo_sync.is_verlegd_tarief({"invoice_repartition_line_ids": [1, 2, 3]}, rep)
        assert not odoo_sync.is_verlegd_tarief({"invoice_repartition_line_ids": [1, 2]}, rep)

    @pytest.mark.parametrize(
        ("naam", "favoriet"),
        [("21%", True), ("9%", True), ("21% S", False), ("21% R", False), ("21% O", False), ("0% EX EU", False)],
    )
    def test_favoriet_is_de_kale_percentagecode(self, naam: str, favoriet: bool) -> None:
        assert odoo_sync.is_favoriet_tarief(naam) is favoriet

    def test_lees_btw_geeft_fractie_vlaggen_en_synthetische_nulcode(self) -> None:
        class _Client:
            company_id = 1

            def search_read_alles(self, model, domain, fields, **kw):
                return [
                    {
                        "id": 14,
                        "name": "21%",
                        "amount": 21.0,
                        "amount_type": "percent",
                        "type_tax_use": "purchase",
                        "invoice_label": "21% VAT",
                        "invoice_repartition_line_ids": [1, 2],
                        "active": True,
                    },
                    {
                        "id": 20,
                        "name": "21% R",
                        "amount": 21.0,
                        "amount_type": "percent",
                        "type_tax_use": "purchase",
                        "invoice_label": "21% VAT reverse charge",
                        "invoice_repartition_line_ids": [1, 2, 3],
                        "active": True,
                    },
                    {
                        "id": 99,
                        "name": "vast",
                        "amount": 5.0,
                        "amount_type": "fixed",
                        "type_tax_use": "purchase",
                        "invoice_label": "",
                        "invoice_repartition_line_ids": [],
                        "active": True,
                    },
                ]

            def read(self, model, ids, fields):
                return [
                    {"id": 1, "repartition_type": "base", "factor_percent": 100.0},
                    {"id": 2, "repartition_type": "tax", "factor_percent": 100.0},
                    {"id": 3, "repartition_type": "tax", "factor_percent": -100.0},
                ]

        vertaler = odoo_sync._Vertaler(1)
        records = odoo_sync.lees_btw(_Client(), vertaler)  # type: ignore[arg-type]
        per_id = {r["odoo_id"]: r for r in records}
        assert set(per_id) == {14, 20, GEEN_BTW_ODOO_ID}  # 'fixed' bewust buiten fase 1
        assert per_id[14]["Percentage"] == "0.21" and per_id[14]["IsFavorite"] and not per_id[14]["IsRelayed"]
        assert per_id[20]["IsRelayed"] and per_id[20]["Percentage"] == "0" and not per_id[20]["IsFavorite"]
        assert per_id[GEEN_BTW_ODOO_ID]["synthetisch"] and per_id[GEEN_BTW_ODOO_ID]["Percentage"] == "0"
        assert per_id[14]["id"] == str(odoo_uuid(1, "account.tax", 14))
        assert {(m, o) for m, o, _, _ in vertaler.rijen} == {
            ("account.tax", 14),
            ("account.tax", 20),
            ("account.tax", 0),
        }


class TestPoortenEnFouten:
    def test_lock_date_blokkeert_op_en_voor_de_lock_date(self) -> None:
        lock = {"fiscalyear_lock_date": date(2025, 12, 31), "tax_lock_date": date(2025, 12, 31), "hard_lock_date": None}
        assert lock_date_melding(boekdatum=date(2025, 12, 31), lock_dates=lock) is not None
        assert "2025-12-31" in (lock_date_melding(boekdatum=date(2025, 6, 1), lock_dates=lock) or "")
        assert lock_date_melding(boekdatum=date(2026, 1, 1), lock_dates=lock) is None
        assert lock_date_melding(boekdatum=date(2020, 1, 1), lock_dates={"hard_lock_date": None}) is None

    def test_lock_date_poort_alleen_nog_voor_de_tegenboeking(self) -> None:
        """Slotstuk 04-09: het boekpad verschuift (fouten.bepaal_boekdatum, tests/odoo/test_boekdatum.py); de
        weigering blijft uitsluitend de tegenboek-poort — de adapter kent geen `_toets_overgangsdatum` meer."""
        assert not hasattr(OdooInkoopPort, "_toets_overgangsdatum")
        assert hasattr(OdooInkoopPort, "_toets_lock_dates") and hasattr(OdooInkoopPort, "_bepaal_boekdatum")
        import app.odoo.fouten as fouten

        assert not hasattr(fouten, "overgangsdatum_melding")

    def test_overgangsdatum_is_kanteldatum_geen_poort_op_documenten(self) -> None:
        """Besluit Peter 04-09 "geen blokkade": een document mét factuurdatum vóór de kanteldatum komt gewoon in het
        boekpad — `_move_vals` bouwt de create-vals mét `invoice_date` = factuurdatum en `date` = de meegegeven
        boekdatum; de kanteldatum speelt nergens mee (de dedup over de backend-grens filtert wat al in RLZ stond)."""
        from decimal import Decimal as D

        from app.documenten.boekvoorstel import BoekvoorstelData

        kanteldatum = date(2026, 9, 1)
        verbinding = OdooVerbinding(
            administratie_id=uuid.uuid4(),
            odoo_url="https://x.odoo.com",
            company_id=1,
            company_naam="Universal Steigerbouw",
            journal_purchase_id=7,
            journal_general_id=8,
            journal_sale_id=9,
            analytic_plan_id=2,
            overgangsdatum=kanteldatum,
        )

        class _Client:
            company_id = 1

        port = OdooInkoopPort(verbinding.administratie_id, verbinding, client=_Client())  # type: ignore[arg-type]
        document_id = uuid.uuid4()
        voorstel = BoekvoorstelData(
            document_id=document_id,
            vendor_id=uuid.uuid4(),
            referentie="F-NAKOMER-1",
            factuurdatum=date(2026, 8, 20),  # vóór de kanteldatum
            totaalbedrag=D("121.00"),
            rlz_boekstuknummer=None,
            opgeslagen=True,
            regels=[],
        )
        vals = port._move_vals(document_id=document_id, voorstel=voorstel, partner_id=5, regels=[])
        assert vals["invoice_date"] == "2026-08-20" and vals["date"] == "2026-08-20"
        assert vals["invoice_origin"] == marker(document_id, 0) and vals["company_id"] == 1
        # Mét een verschoven boekdatum (lock date geraakt) blijft de factuurdatum de factuurdatum.
        vals = port._move_vals(
            document_id=document_id, voorstel=voorstel, partner_id=5, regels=[], boekdatum=date(2026, 9, 1)
        )
        assert vals["invoice_date"] == "2026-08-20" and vals["date"] == "2026-09-01"

    def test_vertaal_odoo_fout_herkent_lock_balans_rechten(self) -> None:
        lock = OdooFout(
            422,
            "odoo.exceptions.UserError",
            "You cannot add/modify entries prior to the lock date",
            model="account.move",
            methode="action_post",
        )
        assert "vergrendeld" in vertaal_odoo_fout(lock)
        balans = OdooFout(
            422, "odoo.exceptions.UserError", "De boeking is niet in balans.", model="account.move", methode="create"
        )
        assert "niet in balans" in vertaal_odoo_fout(balans)
        rechten = OdooFout(403, "odoo.exceptions.AccessError", "geen toegang", model="account.move", methode="create")
        assert "rechten" in vertaal_odoo_fout(rechten)
        onbekend = OdooFout(500, "builtins.ValueError", "Invalid field 'x'", model="account.move", methode="create")
        assert "Invalid field" in vertaal_odoo_fout(onbekend)  # nooit informatie wegvertalen
        assert vertaal_odoo_fout(RuntimeError("los")) == "los"

    def test_btw_override_tolerantie_is_twee_cent(self) -> None:
        assert Decimal("0.02") == BTW_OVERRIDE_TOLERANTIE


class TestEigenConceptHerkenning:
    """Live keten-cyclus 04-09: een achtergebleven concept (action_post geweigerd) van hetzelfde document mag de
    duplicaatcheck bij de retry niet blokkeren — de leesfacade meldt het onder het eigen deterministische id."""

    def test_marker_vertaalt_naar_eigen_id(self) -> None:
        from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
        from app.odoo.inkoop import eigen_id_uit_marker

        d = uuid.uuid4()
        assert eigen_id_uit_marker(marker(d, 0)) == str(rlz_herboeking_id(d, 0))
        assert eigen_id_uit_marker(marker(d, 2, "tegenboeking")) == str(rlz_tegenboeking_id(d, 2))

    @pytest.mark.parametrize("origin", [None, False, "", "PO00012", "AKN:niet-een-uuid:0:boeking", "AKN:x"])
    def test_vreemde_origin_geeft_none(self, origin) -> None:
        from app.odoo.inkoop import eigen_id_uit_marker

        assert eigen_id_uit_marker(origin) is None

    def test_lees_projecten_vraagt_alleen_actieve_analytic_accounts(self) -> None:
        gezien: list = []

        class _Client:
            company_id = 1

            def search_read_alles(self, model, domain, fields, **kw):
                gezien.append(domain)
                return []

        class _Vertaler:
            def lokaal(self, model, odoo_id, naam):
                return uuid.uuid4()

        odoo_sync.lees_projecten(_Client(), _Vertaler(), plan_id=1)
        assert ["active", "=", True] in gezien[0]


class TestVerlegdeTaxratesNaOverstap:
    """Generale 04-09 stap 6: ná een overstap staan de RLZ-btw-tarieven nog als `verdwenen_uit_bron_op` in de cache;
    `_verlegde_taxrates` mag die niet meer meenemen (ze dragen geen Odoo-id → "account.tax … niet bekend" op élke
    boeking). Alleen de actuele (Odoo-)verlegd-tarieven tellen."""

    def test_verdwenen_rlz_verlegd_tarief_telt_niet_mee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import types
        from datetime import UTC, datetime

        from app.sync.models import TaxRateCache

        aid = uuid.uuid4()
        rlz_verlegd = TaxRateCache(
            id=uuid.uuid4(), administratie_id=aid, naam="NL, BTW verlegd (hoog)", brondata={"IsRelayed": True}
        )
        rlz_verlegd.verdwenen_uit_bron_op = datetime.now(UTC)
        odoo_verlegd = TaxRateCache(id=uuid.uuid4(), administratie_id=aid, naam="21% R", brondata={"IsRelayed": True})
        odoo_gewoon = TaxRateCache(id=uuid.uuid4(), administratie_id=aid, naam="21%", brondata={})
        rijen = [rlz_verlegd, odoo_verlegd, odoo_gewoon]

        class _Sessie:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def scalars(self, stmt):
                # Emuleer het WHERE-filter `verdwenen_uit_bron_op IS NULL` van de query letterlijk op de rijen.
                sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
                assert "verdwenen_uit_bron_op IS NULL" in sql, sql
                return [r for r in rijen if r.verdwenen_uit_bron_op is None]

        import app.odoo.inkoop as inkoop_mod

        monkeypatch.setattr(inkoop_mod, "scoped_session", lambda *a, **k: _Sessie())
        verbinding = OdooVerbinding(
            administratie_id=aid, odoo_url="https://x", company_id=1, company_naam=None,
            journal_purchase_id=1, journal_general_id=None, journal_sale_id=None, analytic_plan_id=None,
        )  # fmt: skip
        port = OdooInkoopPort(aid, verbinding, client=types.SimpleNamespace(company_id=1))  # type: ignore[arg-type]
        assert port._verlegde_taxrates() == {odoo_verlegd.id}
