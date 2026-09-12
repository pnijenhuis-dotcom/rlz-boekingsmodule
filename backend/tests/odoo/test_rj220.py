# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo/test_router.py)
"""RJ-220-rollen company 6 (run 2 VGG → Odoo, blok 4; migratie 0138, `app/odoo/rj220.py`, CLI `vgg-rekeningen`).

- voorstel-logica op een fixture van company-6-achtige rekeningen (live gelezen 12-09: 356 rekeningen, NL-template):
  vrije nummers 325000/326000/803100/701300, bezette code overgeslagen mét melding, bestaande "Stock 1" gemeld als optie
  maar niet gekozen, ondubbelzinnige naamtreffer = hergebruik, twee naamtreffers = geen gok;
- `maak_rollen_aan` met fake client: kill-switch vóór de eerste call, company-pin, read-only-client geweigerd,
  create-vals dragen `company_ids` (Odoo 19), post-write terug-lezen, analytic Overhead lookup-vóór-create,
  koppeling-rij + audit, idempotente herdraai (code bestaat → geen tweede create);
- `vertaal_grootboek`: zelfde_code (groen) / code_verlengd / rgs (oranje, naam + klasse, precies één) / None;
- `koppeling_voor` weigert een migratiedoel-rij (backend rlz), `rollen_voor` leest 'm wél; `OdooVerbinding` additief;
- CLI-registratie/dispatch + lees-only-run mét fake client, `--maak-aan` achter de kill-switch.
Geen netwerk, geen Odoo-writes."""

from __future__ import annotations

import argparse
import io
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app import cli
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.odoo import cli_rj220, rj220
from app.odoo.credentials import GeenOdooKoppeling, OdooVerbinding, koppeling_voor
from app.odoo.models import OdooKoppeling
from app.security.envelope import wrap_secret
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

COMPANY = 6
PLAN = 1


def _acc(
    odoo_id: int, code: str, naam: str, account_type: str, *, companies: int = 10, reconcile: bool = False
) -> dict:
    return {
        "id": odoo_id,
        "code": code,
        "name": naam,
        "account_type": account_type,
        "reconcile": reconcile,
        "company_ids": list(range(1, companies + 1)),
    }


#: Relevante uitsnede van de live gelezen company 6 (12-09-2026): voorraadreeks, NL-omzet/kostprijs, prepaid/deposit.
COMPANY6 = [
    _acc(121, "110000", "Debtors", "asset_receivable", reconcile=True),
    _acc(2969, "120500", "Prepaid expenses", "asset_current", companies=6),
    _acc(126, "121000", "Deposit", "asset_prepayments"),
    _acc(131, "130000", "Creditors", "liability_payable", reconcile=True),
    _acc(132, "135000", "Payments in transit", "liability_current"),
    _acc(208, "300100", "Raw materials 1", "asset_current"),
    _acc(212, "320000", "Stock 1", "asset_current"),
    _acc(213, "321000", "Stock 2", "asset_current"),
    _acc(214, "330000", "Packaging material", "asset_current"),
    _acc(336, "700100", "Cost price NL trade goods 1", "expense_direct_cost"),
    _acc(340, "700500", "Cost price NL trade goods 2", "expense_direct_cost"),
    _acc(344, "700900", "Cost price NL trade goods 3", "expense_direct_cost"),
    _acc(347, "701200", "Cost Intercompany trade goods 3", "expense_direct_cost"),
    _acc(365, "800100", "Turnover NL trade goods 1", "income"),
    _acc(369, "800500", "Turnover NL services 1", "income"),
    _acc(370, "801100", "Turnover NL trade goods 2", "income"),
    _acc(375, "802100", "Turnover NL trade goods 3", "income"),
    _acc(2154, "802300", "Turnover outside EU trade goods 3", "income", companies=1),
    _acc(380, "804100", "Turnover NL third-party work", "income"),
]


class FakeOdoo:
    """Neemt calls op; `search_read` beantwoordt uit `records` per model met een minimale domain-evaluatie."""

    def __init__(self, records: dict[str, list[dict]], *, company_id: int = COMPANY, read_only: bool = False) -> None:
        self.records = {m: [dict(r) for r in rijen] for m, rijen in records.items()}
        self.company_id = company_id
        self.read_only = read_only
        self.calls: list[tuple[str, str, Any]] = []
        self._volgend_id = 9000

    def _match(self, rij: dict, domain: list) -> bool:
        for veld, op, waarde in domain:
            huidig = rij.get(veld)
            if op == "=":
                if isinstance(huidig, list) and len(huidig) == 2 and isinstance(huidig[0], int):
                    huidig = huidig[0]  # m2o [id, naam]
                if huidig != waarde:
                    return False
            elif op == "in":
                if isinstance(huidig, list):
                    if isinstance(huidig[0] if huidig else None, int) and len(huidig) == 2 and veld == "company_id":
                        huidig = huidig[0]
                    else:
                        if not any(v in huidig for v in waarde):
                            return False
                        continue
                if huidig not in waarde:
                    return False
        return True

    def search_read(self, model: str, domain: list, fields: list[str], *, limit: int | None = None, **kw: Any) -> list:
        self.calls.append((model, "search_read", domain))
        uit = [dict(r) for r in self.records.get(model, []) if self._match(r, domain)]
        return uit[:limit] if limit else uit

    def search_read_alles(self, model: str, domain: list, fields: list[str], **kw: Any) -> list:
        return self.search_read(model, domain, fields)

    def create(self, model: str, vals: dict) -> int:
        if self.read_only:
            raise AssertionError("create op read-only client")
        self.calls.append((model, "create", dict(vals)))
        self._volgend_id += 1
        rij = {"id": self._volgend_id, **vals}
        if "company_ids" in vals:  # Odoo 19 m2m-commando [[6,0,[ids]]] → terug als id-lijst
            rij["company_ids"] = list(vals["company_ids"][0][2])
        if "company_id" in vals and isinstance(vals["company_id"], int):
            rij["company_id"] = [vals["company_id"], "Company"]
        if "plan_id" in vals and isinstance(vals["plan_id"], int):
            rij["plan_id"] = [vals["plan_id"], "Project"]
        rij.setdefault("active", True)
        self.records.setdefault(model, []).append(rij)
        return self._volgend_id

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict | None:
        self.calls.append((model, "read", odoo_id))
        return next((dict(r) for r in self.records.get(model, []) if r["id"] == odoo_id), None)

    def close(self) -> None:
        pass


def _per_rol(voorstellen: list[rj220.RolVoorstel]) -> dict[str, rj220.RolVoorstel]:
    return {v.rol: v for v in voorstellen}


# --------------------------------------------------------------------------- voorstel-logica (lees-only)


class TestRolVoorstellen:
    def test_company6_geeft_vrije_nummers_in_de_templatereeks(self) -> None:
        v = _per_rol(rj220.bepaal_rolvoorstellen(COMPANY6))
        assert [r.rol for r in rj220.bepaal_rolvoorstellen(COMPANY6)] == list(rj220.ROLLEN)
        assert (v["voorraad_panden"].voorstel_code, v["voorraad_panden"].account_type) == ("325000", "asset_current")
        assert v["vooruitbetaald_voorraad"].voorstel_code == "326000"
        assert v["vooruitbetaald_voorraad"].account_type == "asset_current"
        assert (v["opbrengst_panden"].voorstel_code, v["opbrengst_panden"].account_type) == ("803100", "income")
        assert (v["kostprijs_panden"].voorstel_code, v["kostprijs_panden"].account_type) == (
            "701300",
            "expense_direct_cost",
        )
        assert all(r.bestaand_odoo_id is None and not r.is_hergebruik for r in v.values())
        assert v["voorraad_panden"].voorstel_naam == "Voorraad panden"
        assert v["kostprijs_panden"].voorstel_naam == "Kostprijs verkochte panden"

    def test_bestaande_stock_wordt_gemeld_maar_niet_gekozen(self) -> None:
        v = _per_rol(rj220.bepaal_rolvoorstellen(COMPANY6))["voorraad_panden"]
        assert "320000 Stock 1" in v.reden and "gedeeld over 10 companies" in v.reden
        assert "niet gekozen" in v.reden
        assert v.voorstel_code != "320000" and v.bestaand_odoo_id is None
        # Vooruitbetaald: Prepaid expenses en Deposit (ander type) als optie, mét type-markering bij afwijkend type.
        vv = _per_rol(rj220.bepaal_rolvoorstellen(COMPANY6))["vooruitbetaald_voorraad"]
        assert "120500 Prepaid expenses" in vv.reden and "121000 Deposit [asset_prepayments]" in vv.reden

    def test_bezette_kandidaat_wordt_overgeslagen_met_melding(self) -> None:
        bezet = [*COMPANY6, _acc(5000, "325000", "Iets anders", "asset_current", companies=1)]
        v = _per_rol(rj220.bepaal_rolvoorstellen(bezet))["voorraad_panden"]
        assert v.voorstel_code == "322000"
        assert "Bezet en overgeslagen: 325000" in v.reden

    def test_alle_kandidaten_bezet_geeft_geen_code_maar_leesbare_reden(self) -> None:
        bezet = [*COMPANY6] + [
            _acc(6000 + i, c, f"X{i}", "income", companies=1)
            for i, c in enumerate(rj220.KANDIDAAT_CODES_PER_ROL["opbrengst_panden"])
        ]
        v = _per_rol(rj220.bepaal_rolvoorstellen(bezet))["opbrengst_panden"]
        assert v.voorstel_code == "" and "alle kandidaatnummers bezet" in v.reden

    def test_ondubbelzinnige_naamtreffer_met_juist_type_is_hergebruik(self) -> None:
        met = [*COMPANY6, _acc(7001, "325500", "voorraad  PANDEN", "asset_current", companies=1)]
        v = _per_rol(rj220.bepaal_rolvoorstellen(met))["voorraad_panden"]
        assert v.is_hergebruik and v.bestaand_odoo_id == 7001 and v.bestaand_code == "325500"
        assert v.voorstel_code == "325500" and "hergebruik" in v.reden

    def test_naamtreffer_met_verkeerd_type_telt_niet(self) -> None:
        met = [*COMPANY6, _acc(7002, "425000", "Voorraad panden", "expense", companies=1)]
        v = _per_rol(rj220.bepaal_rolvoorstellen(met))["voorraad_panden"]
        assert not v.is_hergebruik and v.voorstel_code == "325000"

    def test_twee_naamtreffers_geen_gok(self) -> None:
        met = [
            *COMPANY6,
            _acc(7003, "325500", "Voorraad panden", "asset_current", companies=1),
            _acc(7004, "325600", "Voorraad panden", "asset_current", companies=1),
        ]
        v = _per_rol(rj220.bepaal_rolvoorstellen(met))["voorraad_panden"]
        assert v.voorstel_code == "" and v.bestaand_odoo_id is None
        assert "2 bestaande rekeningen" in v.reden and "325500, 325600" in v.reden

    def test_stel_rollen_voor_leest_company_via_company_ids(self) -> None:
        fake = FakeOdoo({"account.account": COMPANY6}, read_only=True)
        uit = rj220.stel_rollen_voor(fake, company_id=COMPANY)  # type: ignore[arg-type]
        assert len(uit) == 4 and _per_rol(uit)["opbrengst_panden"].voorstel_code == "803100"
        model, methode, domain = fake.calls[0]
        assert (model, methode) == ("account.account", "search_read")
        assert domain == [["company_ids", "in", [COMPANY]]]
        assert not any(m == "create" for _, m, _ in fake.calls)


# --------------------------------------------------------------------------- aanmaken (fake client, kill-switch)


def _koppeling_rij(aid: uuid.UUID, beheerder: uuid.UUID, **extra: Any) -> None:
    ciphertext, wrapped = wrap_secret(b"GEHEIM")
    with scoped_session(None, actor_id=beheerder) as session:
        session.add(
            OdooKoppeling(
                administratie_id=aid,
                odoo_url="https://universal-steigers.odoo.com",
                company_id=COMPANY,
                company_naam="Vastgoedgroep Nederland B.V.",
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                analytic_plan_id=PLAN,
                aangemaakt_door=beheerder,
                **extra,
            )
        )


@pytest.fixture
def writes_aan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rj220, "_writes_ingeschakeld", lambda: True)


def _fake_met_analytic() -> FakeOdoo:
    return FakeOdoo(
        {
            "account.account": COMPANY6,
            "account.analytic.account": [
                {
                    "id": 105,
                    "name": "Intern",
                    "code": False,
                    "company_id": [6, "VGG"],
                    "plan_id": [1, "Project"],
                    "active": True,
                }
            ],
        }
    )


class TestMaakRollenAan:
    def test_kill_switch_uit_weigert_voor_de_eerste_call(self, administratie_id, beheerder_id) -> None:
        fake = _fake_met_analytic()
        with pytest.raises(rj220.MigratieWritesUit):
            rj220.maak_rollen_aan(
                fake,
                company_id=COMPANY,
                voorstellen=rj220.bepaal_rolvoorstellen(COMPANY6),
                actor_id=beheerder_id,
                administratie_id=administratie_id,
            )
        assert fake.calls == []

    def test_company_pin_en_read_only_geweigerd(self, administratie_id, beheerder_id, writes_aan) -> None:
        voorstellen = rj220.bepaal_rolvoorstellen(COMPANY6)
        ander = FakeOdoo({"account.account": COMPANY6}, company_id=1)
        with pytest.raises(rj220.CompanyPinGeschonden):
            rj220.maak_rollen_aan(
                ander,
                company_id=COMPANY,
                voorstellen=voorstellen,
                actor_id=beheerder_id,
                administratie_id=administratie_id,
            )
        assert ander.calls == []
        ro = FakeOdoo({"account.account": COMPANY6}, read_only=True)
        with pytest.raises(rj220.RolFout, match="alleen-lezen"):
            rj220.maak_rollen_aan(
                ro,
                company_id=COMPANY,
                voorstellen=voorstellen,
                actor_id=beheerder_id,
                administratie_id=administratie_id,
            )
        assert ro.calls == []

    def test_zonder_koppeling_rij_leesbare_fout(self, administratie_id, beheerder_id, writes_aan) -> None:
        fake = _fake_met_analytic()
        with pytest.raises(rj220.RolFout, match="geen odoo_koppeling-rij"):
            rj220.maak_rollen_aan(
                fake,
                company_id=COMPANY,
                voorstellen=rj220.bepaal_rolvoorstellen(COMPANY6),
                actor_id=beheerder_id,
                administratie_id=administratie_id,
            )
        assert fake.calls == []

    def test_koppeling_rij_met_andere_company_is_pin_schending(
        self, administratie_id, beheerder_id, writes_aan
    ) -> None:
        _koppeling_rij(administratie_id, beheerder_id, migratie_doel=True)
        fake = FakeOdoo({"account.account": COMPANY6}, company_id=3)
        with pytest.raises(rj220.CompanyPinGeschonden):
            rj220.maak_rollen_aan(
                fake, company_id=3, voorstellen=rj220.bepaal_rolvoorstellen(COMPANY6), actor_id=beheerder_id,
                administratie_id=administratie_id,
            )  # fmt: skip
        assert fake.calls == []

    def test_aanmaken_vals_company_ids_postwrite_overhead_koppeling_audit(
        self, administratie_id, beheerder_id, writes_aan
    ) -> None:
        _koppeling_rij(administratie_id, beheerder_id, migratie_doel=True)
        fake = _fake_met_analytic()
        voorstellen = rj220.bepaal_rolvoorstellen(COMPANY6)
        uitkomst = rj220.maak_rollen_aan(
            fake, company_id=COMPANY, voorstellen=voorstellen, actor_id=beheerder_id, administratie_id=administratie_id
        )
        creates = [(m, v) for m, methode, v in fake.calls if methode == "create"]
        rekening_creates = [v for m, v in creates if m == "account.account"]
        assert [v["code"] for v in rekening_creates] == ["325000", "326000", "803100", "701300"]
        for v in rekening_creates:
            assert v["company_ids"] == [[6, 0, [COMPANY]]] and v["reconcile"] is False and "company_id" not in v
        assert {v["account_type"] for v in rekening_creates} == {"asset_current", "income", "expense_direct_cost"}
        # Lookup-vóór-create op code, ná elke create een read (post-write-verificatie).
        volgorde = [(m, methode) for m, methode, _ in fake.calls]
        idx_create = volgorde.index(("account.account", "create"))
        assert volgorde[idx_create - 1] == ("account.account", "search_read")
        assert volgorde[idx_create + 1] == ("account.account", "read")
        # Analytic Overhead: lookup (search_read) → create → read.
        analytic = [(methode, v) for m, methode, v in fake.calls if m == "account.analytic.account"]
        assert [methode for methode, _ in analytic] == ["search_read", "create", "read"]
        assert analytic[1][1] == {"name": "Overhead", "plan_id": PLAN, "company_id": COMPANY}
        assert uitkomst.compleet and uitkomst.analytic_overhead is not None
        # Koppeling-rij bijgewerkt en via `rollen_voor` leesbaar; audit oud→nieuw.
        assert rj220.rollen_voor(administratie_id) == uitkomst
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:  # audit-RLS: administratie-scope
            events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tabel == "odoo_koppeling", AuditEvent.actie == "odoo_rj220_rollen_vastgesteld"
                )
            ).all()
            assert len(events) == 1
            ev = events[0]
            assert ev.record_id == administratie_id and ev.administratie_id == administratie_id
            assert ev.oude_waarde["voorraad_panden"] is None
            assert ev.nieuwe_waarde["voorraad_panden"] == uitkomst.voorraad_panden
            assert ev.nieuwe_waarde["codes"]["opbrengst_panden"] == "803100"
            assert ev.nieuwe_waarde["company_id"] == COMPANY
            assert "GEHEIM" not in json.dumps(ev.nieuwe_waarde)

    def test_herdraai_is_idempotent_en_hergebruikt_overhead(self, administratie_id, beheerder_id, writes_aan) -> None:
        _koppeling_rij(administratie_id, beheerder_id, migratie_doel=True)
        fake = _fake_met_analytic()
        voorstellen = rj220.bepaal_rolvoorstellen(COMPANY6)
        eerste = rj220.maak_rollen_aan(
            fake, company_id=COMPANY, voorstellen=voorstellen, actor_id=beheerder_id, administratie_id=administratie_id
        )
        n_creates = sum(1 for _, methode, _ in fake.calls if methode == "create")
        assert n_creates == 5
        # Tweede run mét dezelfde voorstellen: de codes bestaan nu → lookup vindt ze, geen create meer.
        tweede = rj220.maak_rollen_aan(
            fake, company_id=COMPANY, voorstellen=voorstellen, actor_id=beheerder_id, administratie_id=administratie_id
        )
        assert sum(1 for _, methode, _ in fake.calls if methode == "create") == 5
        assert tweede == eerste

    def test_postwrite_company_mismatch_is_fout(self, administratie_id, beheerder_id, writes_aan) -> None:
        _koppeling_rij(administratie_id, beheerder_id, migratie_doel=True)

        class Verkeerd(FakeOdoo):
            def create(self, model: str, vals: dict) -> int:
                nieuw = super().create(model, vals)
                if model == "account.account":
                    self.records[model][-1]["company_ids"] = [1]  # Odoo zette een andere company
                return nieuw

        fake = Verkeerd({"account.account": COMPANY6, "account.analytic.account": []})
        with pytest.raises(rj220.RolFout, match="staat niet in company_ids"):
            rj220.maak_rollen_aan(
                fake,
                company_id=COMPANY,
                voorstellen=rj220.bepaal_rolvoorstellen(COMPANY6),
                actor_id=beheerder_id,
                administratie_id=administratie_id,
            )
        assert rj220.rollen_voor(administratie_id) == rj220.LEEG  # koppeling-rij onaangeroerd

    def test_gearchiveerde_overhead_is_fout_geen_tweede(self, administratie_id, beheerder_id, writes_aan) -> None:
        _koppeling_rij(administratie_id, beheerder_id, migratie_doel=True)
        fake = FakeOdoo(
            {
                "account.account": COMPANY6,
                "account.analytic.account": [
                    {
                        "id": 900,
                        "name": "Overhead",
                        "code": False,
                        "company_id": [6, "VGG"],
                        "plan_id": [1, "P"],
                        "active": False,
                    }
                ],
            }
        )
        with pytest.raises(rj220.RolFout, match="GEARCHIVEERD"):
            rj220.maak_rollen_aan(
                fake,
                company_id=COMPANY,
                voorstellen=rj220.bepaal_rolvoorstellen(COMPANY6),
                actor_id=beheerder_id,
                administratie_id=administratie_id,
            )
        assert not any(m == "account.analytic.account" and methode == "create" for m, methode, _ in fake.calls)


# --------------------------------------------------------------------------- grootboekvertaling


L_4808 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004808")
L_1300 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000001300")
L_8000 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000008000")
L_4400 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004400")
L_1600 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000001600")
L_0100 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000100")

ODOO_GB = [
    {"id": 10, "code": "4808", "name": "Huur materieel (oud)", "account_type": "expense"},
    {"id": 11, "code": "130000", "name": "Creditors", "account_type": "liability_payable"},
    {"id": 12, "code": "803100", "name": "Opbrengst verkoop panden", "account_type": "income"},
    {"id": 13, "code": "440000", "name": "Kantoorkosten", "account_type": "expense"},
    {"id": 14, "code": "441000", "name": "Kantoorkosten", "account_type": "expense"},
    {"id": 15, "code": "160500", "name": "Notariskosten", "account_type": "liability_current"},
    {"id": 16, "code": "", "name": "Zonder code", "account_type": "expense"},
]


class TestVertaalGrootboek:
    def test_zelfde_code_en_code_verlengd_via_mapping(self) -> None:
        uit = rj220.vertaal_grootboek([(L_4808, "4808", "Huur"), (L_1300, "1300", "Crediteuren")], ODOO_GB)
        assert (uit[0].odoo_account_id, uit[0].odoo_code, uit[0].bron) == (10, "4808", "zelfde_code")
        assert (uit[1].odoo_account_id, uit[1].odoo_code, uit[1].bron) == (11, "130000", "code_verlengd")
        assert uit[0].rlz_ledger_id == L_4808 and uit[1].rlz_naam == "Crediteuren"

    def test_rgs_trap_naam_plus_klasse_precies_een(self) -> None:
        [rij] = rj220.vertaal_grootboek([(L_8000, "8000", "  opbrengst VERKOOP panden ")], ODOO_GB)
        assert (rij.odoo_account_id, rij.bron) == (12, "rgs")

    def test_rgs_weigert_bij_twee_kandidaten_of_andere_klasse(self) -> None:
        [twee] = rj220.vertaal_grootboek([(L_4400, "4401", "Kantoorkosten")], ODOO_GB)  # geen code-match
        assert twee.odoo_account_id is None and twee.bron is None
        [klasse] = rj220.vertaal_grootboek([(L_4400, "4402", "Notariskosten")], ODOO_GB)  # 4xxx ↔ 16xxxx
        assert klasse.odoo_account_id is None

    def test_zonder_code_of_naam_geen_gok(self) -> None:
        uit = rj220.vertaal_grootboek(
            [(L_1600, None, "Opbrengst verkoop panden"), (L_0100, "0100", None), (L_0100, "0100", "Onbekend")], ODOO_GB
        )
        assert all(r.odoo_account_id is None and r.bron is None for r in uit)
        assert len(uit) == 3

    def test_code_verlengd_op_onverenigbaar_type_is_geen_voorstel(self) -> None:
        """Live proef 12-09 company 6: RLZ 1300 Debiteuren verlengde naar 130000 Creditors (NL-template) — fout. De
        klasse-/kaartpoort maakt daar None van; met een verenigbaar type blijft code_verlengd staan."""
        template = [
            {"id": 121, "code": "110000", "name": "Debtors", "account_type": "asset_receivable"},
            {"id": 131, "code": "130000", "name": "Creditors", "account_type": "liability_payable"},
            {"id": 400, "code": "400000", "name": "Iets", "account_type": "income"},
            {"id": 401, "code": "410000", "name": "Huur", "account_type": "expense"},
        ]
        deb, kosten, huur, bank = rj220.vertaal_grootboek(
            [
                (L_1300, "1300", "Debiteuren"),
                (L_4400, "4000", "Kantoorkosten"),
                (L_4400, "4100", "Huur"),
                (L_0100, "1100", "Bank"),
            ],
            template,
        )
        assert deb.odoo_account_id is None and deb.bron is None  # 1300 → 130000 Creditors GEWEIGERD
        assert kosten.odoo_account_id is None  # 4000 → 400000 is 'income' → klasse 4 onverenigbaar
        assert (huur.odoo_account_id, huur.bron) == (401, "code_verlengd")  # 4100 → 410000 expense: verenigbaar
        assert bank.odoo_account_id is None  # 1100 → 110000 Debtors: kaartrekening zonder 'debiteur' in de RLZ-naam
        # Mét het juiste type blijft code_verlengd staan; de rgs-trap respecteert dezelfde poort.
        [ok] = rj220.vertaal_grootboek(
            [(L_1300, "1300", "Debiteuren")],
            [{"id": 1, "code": "130000", "name": "Debiteuren", "account_type": "asset_receivable"}],
        )
        assert (ok.odoo_account_id, ok.bron) == (1, "code_verlengd")
        [rgs_fout] = rj220.vertaal_grootboek(
            [(L_1300, "1300", "Debiteuren")],
            [{"id": 3, "code": "135000", "name": "Debiteuren", "account_type": "liability_payable"}],
        )
        assert rgs_fout.odoo_account_id is None
        # Zonder account_type in de Odoo-rij (oudere lezer) valt de poort weg — gedocumenteerd gedrag.
        [zonder] = rj220.vertaal_grootboek([(L_1300, "1300", "Debiteuren")], [{"id": 2, "code": "130000", "name": "X"}])
        assert zonder.bron == "code_verlengd"

    def test_lege_odoo_lijst(self) -> None:
        [rij] = rj220.vertaal_grootboek([(L_4808, "4808", "Huur")], [])
        assert rij.odoo_account_id is None


# --------------------------------------------------------------------------- koppeling-rij + credentials


class TestKoppelingRij:
    def test_rollen_voor_zonder_rij_alles_none(self, administratie_id) -> None:
        assert rj220.rollen_voor(administratie_id) == rj220.LEEG and not rj220.LEEG.compleet

    def test_koppeling_voor_weigert_migratiedoel_rij_maar_rollen_voor_leest(
        self, administratie_id, beheerder_id
    ) -> None:
        _koppeling_rij(
            administratie_id,
            beheerder_id,
            migratie_doel=True,
            rekening_voorraad_panden_id=9001,
            rekening_opbrengst_panden_id=9003,
            analytic_overhead_id=777,
        )
        # Backend 'rlz', niet alleen_lezen, migratie_doel=True → de dagelijkse adapter blijft geweigerd.
        with pytest.raises(GeenOdooKoppeling, match="draait niet op Odoo"):
            koppeling_voor(administratie_id)
        rollen = rj220.rollen_voor(administratie_id)
        assert (rollen.voorraad_panden, rollen.opbrengst_panden, rollen.analytic_overhead) == (9001, 9003, 777)
        assert rollen.vooruitbetaald_voorraad is None and not rollen.compleet

    def test_leesbron_rij_draagt_nieuwe_velden_additief(self, administratie_id, beheerder_id) -> None:
        _koppeling_rij(administratie_id, beheerder_id, alleen_lezen=True, rekening_kostprijs_panden_id=9004)
        verbinding = koppeling_voor(administratie_id)
        assert verbinding.alleen_lezen and verbinding.migratie_doel is False
        assert verbinding.rekening_kostprijs_panden_id == 9004 and verbinding.rekening_voorraad_panden_id is None

    def test_odoo_verbinding_defaults(self) -> None:
        v = OdooVerbinding(
            administratie_id=uuid.uuid4(),
            odoo_url="https://x",
            company_id=6,
            company_naam=None,
            journal_purchase_id=None,
            journal_general_id=None,
            journal_sale_id=None,
            analytic_plan_id=None,
        )
        assert v.migratie_doel is False and v.analytic_overhead_id is None and v.rekening_opbrengst_panden_id is None


# --------------------------------------------------------------------------- CLI


ADMIN = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _args(**kw: Any) -> argparse.Namespace:
    basis: dict[str, Any] = dict(
        commando="vgg-rekeningen", administratie="Vastgoedgroep", company_id=None, maak_aan=False, json_uit=None
    )
    basis.update(kw)
    return argparse.Namespace(**basis)


def _zoek(_: str):  # noqa: ANN202
    return (ADMIN, "Vastgoedgroep Nederland B.V.", "f6d4770f-53fe-41fa-8b35-b675f406841c")


class TestCli:
    def test_cli_dispatch_kent_vgg_rekeningen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aangeroepen: list[argparse.Namespace] = []
        monkeypatch.setattr(cli, "run_vgg_rekeningen", lambda args: aangeroepen.append(args) or 0)
        assert cli.main(["vgg-rekeningen", "--administratie", "Vastgoedgroep", "--company-id", "6"]) == 0
        assert aangeroepen[0].company_id == 6 and aangeroepen[0].maak_aan is False
        assert cli.main(["vgg-rekeningen", "--administratie", "x", "--maak-aan"]) == 0
        assert aangeroepen[1].maak_aan is True

    def test_lees_only_run_print_tabel_en_json(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeOdoo({"account.account": COMPANY6}, read_only=True)
        monkeypatch.setattr(rj220, "rollen_voor", lambda aid: rj220.LEEG)
        uit = io.StringIO()
        json_pad = tmp_path / "rollen.json"
        code = cli_rj220.run_vgg_rekeningen(
            _args(json_uit=str(json_pad)),
            zoek=_zoek,
            client_factory=lambda aid, comp, schrijvend: (fake, COMPANY, PLAN, None),
            uit=uit,
        )
        assert code == 0
        tekst = uit.getvalue()
        assert (
            "lees-only voorstel" in tekst
            and "| voorraad_panden | — | 325000 | Voorraad panden | asset_current |" in tekst
        )
        assert "kostprijs_panden: — (niet vastgesteld)" in tekst
        data = json.loads(json_pad.read_text())
        assert data["company_id"] == COMPANY and data["maak_aan"] is False
        assert [v["voorstel_code"] for v in data["voorstellen"]] == ["325000", "326000", "803100", "701300"]
        assert not any(m == "create" for _, m, _ in fake.calls)

    def test_maak_aan_achter_kill_switch_exit_1(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        fake = _fake_met_analytic()
        monkeypatch.setattr(rj220, "rollen_voor", lambda aid: rj220.LEEG)
        code = cli_rj220.run_vgg_rekeningen(
            _args(maak_aan=True),
            zoek=_zoek,
            client_factory=lambda aid, comp, schrijvend: (fake, COMPANY, PLAN, None),
            uit=io.StringIO(),
        )
        assert code == 1
        assert "migratie_odoo_writes_ingeschakeld staat UIT" in capsys.readouterr().err
        assert not any(m == "create" for _, m, _ in fake.calls)

    def test_weigering_uit_factory_en_onbekende_administratie(self, capsys) -> None:
        code = cli_rj220.run_vgg_rekeningen(
            _args(),
            zoek=_zoek,
            client_factory=lambda aid, comp, s: (None, 0, None, "geen koppeling-rij"),
            uit=io.StringIO(),
        )
        assert code == 2 and "geen koppeling-rij" in capsys.readouterr().err
        assert cli_rj220.run_vgg_rekeningen(_args(), zoek=lambda _: None, uit=io.StringIO()) == 2

    def test_nameting_allowlist_weigert_maak_aan(self) -> None:
        from pathlib import Path

        script = (Path(__file__).resolve().parents[3] / "scripts" / "gcp" / "nameting.sh").read_text()
        assert "vgg-rekeningen" in script.split('ALLOWLIST="', 1)[1].split('"', 1)[0]
        assert '"$CMD" == "vgg-rekeningen"' in script and '"--maak-aan"' in script
