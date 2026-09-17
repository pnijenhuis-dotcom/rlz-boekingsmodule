"""`vgg-odoo-migratie` (aanvulling Peter 17-09: "1 boeking testen en als het goed gaat alles meteen definitief boeken"):
concepten → cent-exacte toets op de regels ZOALS ODOO ZE HEEFT → bulk action_post → reconcile, in één run. Rood in de
toets = niets gepost, concepten blijven staan. Op de fake Odoo van test_odoo_schrijf (`_nep_odoo`), uitgebreid met
regels per move zodat de toets echt rekent."""

from __future__ import annotations

import argparse
import subprocess
import uuid
from decimal import Decimal
from typing import Any

import pytest

from app import cli
from app.migratie import odoo_migratie_run as run
from app.migratie.cli_odoo import ODOO_MIGRATIE_COMMANDOS
from app.migratie.odoo_schrijf import GeheugenAudit
from tests.migratie.test_odoo_schrijf import (
    PIN,
    REPO,
    FakeClient,
    _moves,
    _nep_odoo,
    _Replay,
    writes_aan,  # noqa: F401 — fixture
)


def _som_regels(vals: dict[str, Any]) -> Decimal:
    return run.verwachte_factuursom(vals)


def _odoo_met_regels(*, uit_balans: bool = False):
    """Fake Odoo waarin élke aangemaakte move regels krijgt: facturen = factuurregels + één tegenzijde (payable/
    receivable) ter grootte van Σ regels; memoriaal = de line_ids. `uit_balans` zet één cent scheef (toets ROOD)."""
    odoo, basis = _nep_odoo()
    odoo["vals"] = {}

    def handler(model, methode, body):
        if model == "account.move" and methode == "create":
            uit = basis(model, methode, body)
            odoo["vals"][uit[0]] = body["vals_list"][0]
            return uit
        if model == "account.move" and methode == "search_count":
            state = next((t[2] for t in body["domain"] if isinstance(t, list) and t[0] == "state" and t[1] == "="), None)
            return sum(1 for m in odoo["moves"].values() if (state is None and m["state"] != "cancel") or m["state"] == state)
        if model == "account.move.line" and methode == "search_read":
            domein = body["domain"]
            move_id = next((t[2] for t in domein if isinstance(t, list) and t[0] == "move_id"), None)
            met_type_filter = any(isinstance(t, list) and t[0] == "account_id.account_type" for t in domein)
            vals = odoo["vals"].get(move_id)
            if vals is None:
                return basis(model, methode, body)
            regels: list[dict[str, Any]] = []
            if vals.get("move_type") in ("in_invoice", "in_refund", "out_invoice", "out_refund"):
                som = _som_regels(vals)
                inkoop = vals["move_type"].startswith("in_")
                for n, item in enumerate(vals.get("invoice_line_ids") or []):
                    regel = item[2] if isinstance(item, (list, tuple)) else item
                    bedrag = Decimal(str(regel.get("price_unit", 0))) * Decimal(str(regel.get("quantity", 1)))
                    regels.append(
                        {"id": move_id * 10 + n, "account_id": [regel.get("account_id"), "x"], "account_type": "expense",
                         "debit": float(bedrag) if inkoop else 0.0, "credit": 0.0 if inkoop else float(bedrag)}
                    )
                tegen = som + (Decimal("0.01") if uit_balans else Decimal("0"))
                regels.append(
                    {"id": move_id * 10 + 9, "account_id": [130, "130000"], "partner_id": [65, "P"],
                     "account_type": "liability_payable" if inkoop else "asset_receivable",
                     "debit": 0.0 if inkoop else float(tegen), "credit": float(tegen) if inkoop else 0.0}
                )
            else:
                # memoriaal: line_ids; de fixture van test_odoo_schrijf kent alleen invoice_line_ids zonder bedrag → twee
                # nulregels (Σ debet = Σ credit = 0), zodat de toets rekent en niet op "geen regels" strandt
                lijnen = vals.get("line_ids") or [{"account_id": 1, "debit": 0, "credit": 0}, {"account_id": 2, "debit": 0, "credit": 0}]
                for n, item in enumerate(lijnen):
                    regel = item[2] if isinstance(item, (list, tuple)) else item
                    regels.append(
                        {"id": move_id * 10 + n, "account_id": [regel.get("account_id"), "x"], "account_type": "other",
                         "debit": float(regel.get("debit", 0) or 0), "credit": float(regel.get("credit", 0) or 0)}
                    )
            if met_type_filter:
                return [r for r in regels if r["account_type"] in ("asset_receivable", "liability_payable")]
            return regels
        return basis(model, methode, body)

    return odoo, handler


def _draai(handler, *, schrijf: bool = True, moves=None, per_pand=None, posten: bool = True) -> tuple[run.MigratieRapport, FakeClient]:
    c = FakeClient(handler)
    replay = _Replay(moves if moves is not None else _moves())
    if per_pand is not None:
        origineel = replay.dry_run

        def dry_run(aid):  # noqa: ANN001
            r = origineel(aid)
            r.per_pand = per_pand
            return r

        replay.dry_run = dry_run  # type: ignore[method-assign]
    rapport = run.voer_migratie_uit(
        uuid.uuid4(),
        administratie_naam="VGG",
        schrijf=schrijf,
        client_factory=lambda aid: c,
        replay_module=replay,
        audit=GeheugenAudit(),
        writes_aan=True,
        posten=posten,
    )
    return rapport, c


class TestToets:
    def test_factuursom_uit_commands_en_kale_dicts(self) -> None:
        vals = {"invoice_line_ids": [[0, 0, {"price_unit": "100.10", "quantity": 2}], {"price_unit": 0.05}]}
        assert run.verwachte_factuursom(vals) == Decimal("200.25")

    def test_toets_move_cent_exact(self) -> None:
        vals = {"invoice_line_ids": [{"price_unit": 100.0}]}
        groen = [
            {"debit": 100.0, "credit": 0.0, "account_type": "expense"},
            {"debit": 0.0, "credit": 100.0, "account_type": "liability_payable"},
        ]
        assert run.toets_move("in_invoice", vals, groen) == []
        scheef = [dict(groen[0]), {"debit": 0.0, "credit": 100.01, "account_type": "liability_payable"}]
        fouten = run.toets_move("in_invoice", vals, scheef)
        assert any("Σ debet" in f for f in fouten) and any("tegenzijde 100.01 ≠ Σ factuurregels 100.00" in f for f in fouten)
        assert run.toets_move("entry", {}, []) == ["geen regels in Odoo terug te lezen"]

    def test_per_pand_eis(self) -> None:
        assert run.per_pand_sluit([{"pand": "A", "controle": "sluit"}, {"pand": "B", "controle": "— (niet verkocht)"}]) == []
        assert run.per_pand_sluit([{"pand": "C", "controle": "SIGNAAL: sluit niet (Δ 5.00)"}]) == ["pand C: SIGNAAL: sluit niet (Δ 5.00)"]


class TestRun:
    def test_dry_run_schrijft_niets_en_toont_plan(self) -> None:
        odoo, handler = _odoo_met_regels()
        rapport, c = _draai(handler, schrijf=False)
        assert rapport.oordeel == "DRY-RUN" and c.calls == []
        assert rapport.fasen["A. concepten"].tellers["documenten"] > 0
        assert "ZOU: action_post" in rapport.als_markdown()

    def test_groen_schrijft_concepten_toetst_en_post_alles_in_dezelfde_run(self, writes_aan: None) -> None:  # noqa: F811
        odoo, handler = _odoo_met_regels()
        rapport, c = _draai(handler)
        md = rapport.als_markdown()
        assert rapport.fasen["A. concepten"].oordeel == "GROEN", md
        assert rapport.fasen["B. toets"].oordeel == "GROEN", md
        assert rapport.fasen["C. posten"].oordeel == "GROEN", md
        assert rapport.oordeel == "GROEN"
        # álle concepten van deze run zijn gepost — en niets anders
        assert sorted(odoo["posted"]) == sorted(rapport.move_ids.values()) and rapport.gepost == sorted(rapport.move_ids.values())
        assert all(odoo["moves"][i]["state"] == "posted" for i in rapport.move_ids.values())
        # idempotent: een tweede run maakt geen nieuwe concepten (zoek-vóór-create) en post niets opnieuw
        aantal_moves = len(odoo["moves"])
        rapport2, _ = _draai(handler)
        assert len(odoo["moves"]) == aantal_moves and rapport2.oordeel in ("GROEN", "ROOD")
        assert "account.move op de company (posted)" in rapport.stand

    def test_toets_rood_post_niets_en_laat_concepten_staan(self, writes_aan: None) -> None:  # noqa: F811
        odoo, handler = _odoo_met_regels(uit_balans=True)
        rapport, c = _draai(handler)
        assert rapport.fasen["B. toets"].oordeel == "ROOD" and rapport.oordeel == "ROOD"
        assert rapport.fasen["C. posten"].oordeel == "niet uitgevoerd"
        assert "account.move.action_post" not in c.methoden()
        assert odoo["posted"] == [] and rapport.move_ids and all(odoo["moves"][i]["state"] == "draft" for i in rapport.move_ids.values())
        assert any("tegenzijde" in r for r in rapport.fasen["B. toets"].regels)
        assert "NIET gepost: toets ROOD" in rapport.als_markdown()

    def test_pand_eis_rood_post_niets(self, writes_aan: None) -> None:  # noqa: F811
        odoo, handler = _odoo_met_regels()
        rapport, c = _draai(handler, per_pand=[{"pand": "Rijswijkseweg 409", "controle": "SIGNAAL: sluit niet (Δ 1.00)"}])
        assert rapport.oordeel == "ROOD" and "account.move.action_post" not in c.methoden()
        assert "pand Rijswijkseweg 409: SIGNAAL: sluit niet (Δ 1.00)" in rapport.fasen["B. toets"].regels

    def test_geen_posten_vlag_laat_concepten_staan_met_groene_toets(self, writes_aan: None) -> None:  # noqa: F811
        odoo, handler = _odoo_met_regels()
        rapport, c = _draai(handler, posten=False)
        assert rapport.oordeel == "GROEN — niet gepost" and "account.move.action_post" not in c.methoden()

    def test_replay_krijgt_de_odoo_rekeningenlezer_en_het_rapport_meldt_de_mapping(self) -> None:
        """Blok 12 (17-09): zonder lezer vertaalt de replay met een lege rekeningmapping ('élke grootboekregel ongemapt') —
        het bewijspaar was daardoor per definitie niet vertaalbaar en de pand-eis 94× 'niet meetbaar'."""
        gezien: list[Any] = []

        class _ReplayMetLezer:
            def dry_run(self, administratie_id: uuid.UUID, *, odoo_lezer: Any = None) -> Any:
                gezien.append(odoo_lezer)
                let_op = ["Odoo-rekeningen gelezen uit company 6 via de doelkoppeling: 361"]
                return type("R", (), {"moves": _moves(), "let_op": let_op})()

        lezer = object()
        rapport = run.voer_migratie_uit(
            uuid.uuid4(),
            administratie_naam="VGG",
            schrijf=False,
            client_factory=lambda aid: FakeClient(lambda *a: []),
            replay_module=_ReplayMetLezer(),
            audit=GeheugenAudit(),
            writes_aan=False,
            odoo_lezer=lezer,
        )
        assert gezien == [lezer]
        assert any("replay-mapping: Odoo-rekeningen gelezen uit company 6" in m for m in rapport.meldingen)

    def test_replay_zonder_lezer_meldt_dat_zichtbaar(self) -> None:
        rapport, _ = _draai(lambda *a: [], schrijf=False)
        assert any("replay zonder Odoo-rekeningen" in m and "ongemapt" in m for m in rapport.meldingen)

    def test_cli_runner_geeft_de_standaardlezer_door(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.migratie import cli_cmd, odoo_doel
        from app.migratie.rekening_mapping import lees_doelgegevens

        gezien: dict[str, Any] = {}
        monkeypatch.setattr(cli_cmd, "zoek_administratie", lambda naam: (uuid.uuid4(), "VGG", "rlz"))
        monkeypatch.setattr(odoo_doel, "doelclient_voor", lambda aid, read_only=True: None)

        def fake(administratie_id, **kw):  # noqa: ANN001, ANN003
            gezien.update(kw)
            return run.MigratieRapport(administratie_naam="VGG", company_id=6, schrijf=False, fasen={})

        monkeypatch.setattr(run, "voer_migratie_uit", fake)
        assert run.run_odoo_migratie_run(argparse.Namespace(administratie="VGG", dry_run=True, geen_posten=False)) == 0
        assert gezien["odoo_lezer"] is lees_doelgegevens

    def test_kill_switch_uit_valt_terug_op_dry_run(self) -> None:
        odoo, handler = _odoo_met_regels()
        c = FakeClient(handler)
        rapport = run.voer_migratie_uit(
            uuid.uuid4(), administratie_naam="VGG", schrijf=True, client_factory=lambda aid: c,
            replay_module=_Replay(_moves()), audit=GeheugenAudit(), writes_aan=False,
        )
        assert rapport.schrijf is False and c.calls == [] and "kill-switch staat UIT" in rapport.als_markdown()


class TestCli:
    def test_dispatch_en_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gezien: list[argparse.Namespace] = []
        monkeypatch.setattr(cli, "run_odoo_migratie", lambda args: gezien.append(args) or 0)
        assert cli.main([run.MIGRATIE_COMMANDO, "--administratie", "VGG"]) == 0
        assert gezien[0].dry_run is True and gezien[0].geen_posten is False
        assert cli.main([run.MIGRATIE_COMMANDO, "--administratie", "VGG", "--schrijf", "--geen-posten"]) == 0
        assert gezien[1].dry_run is False and gezien[1].geen_posten is True
        assert run.MIGRATIE_COMMANDO in ODOO_MIGRATIE_COMMANDOS

    def test_nameting_sh_weigert_hard(self) -> None:
        script = REPO / "scripts" / "gcp" / "nameting.sh"
        tekst = script.read_text(encoding="utf-8")
        assert run.MIGRATIE_COMMANDO not in next(r for r in tekst.splitlines() if r.startswith("ALLOWLIST="))
        uitkomst = subprocess.run(
            ["bash", str(script), run.MIGRATIE_COMMANDO, "--administratie", "VGG"],
            capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "NAMETING_ENV": "/nonexistent/nameting.env"},
        )
        assert uitkomst.returncode == 2 and f"FOUT: {run.MIGRATIE_COMMANDO} is een schrijvend commando" in uitkomst.stderr

    def test_writes_script_kent_schrijf_d(self) -> None:
        tekst = (REPO / "scripts" / "gcp" / "vgg_blok7_odoo_writes.sh").read_text(encoding="utf-8")
        assert 'execute 1 vgg-odoo-migratie --administratie "$ADMIN" --schrijf' in tekst
        assert "plan_stap vgg-odoo-migratie" in tekst and 'BEWIJSPAAR="${VGG_BEWIJSPAAR:-RLZ-01-00000082}"' in tekst
