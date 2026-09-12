"""Run 2 VGG blok 5 — schrijf-primitieven (kill-switch, zoek-vóór-create, post-write, reconcile-route-registry,
annuleren zonder unlink, koppel_los), CLI-registratie + nameting.sh-weigering, migratiedoel-CLI met fake envelope en de
stap-0-cyclus op een fake client. Geen netwerk: `FakeClient` overschrijft `_post` en neemt calls op."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import cli
from app.config import settings
from app.db.session import scoped_session
from app.migratie import cli_odoo
from app.migratie.cli_odoo import (
    MIGRATIEDOEL_COMMANDO,
    STAP0_COMMANDO,
    DagboekProbe,
    MigratiedoelFout,
    lees_dagboeken,
    maak_migratiedoel,
    parse_stappen,
    selecteer_moves,
    voer_stap0_uit,
)
from app.migratie.odoo_doel import (
    PROBE_SLEUTEL_BANKDAGBOEK,
    CompanyGepindeClient,
    CompanyPinGeschonden,
    GeenMigratieDoel,
)
from app.migratie.odoo_schrijf import (
    AnkerMeerduidig,
    ConceptNietDraft,
    GeheugenAudit,
    MigratieWritesUit,
    NietEenConcept,
    annuleer_concept,
    koppel_los,
    maak_concept_move,
    maak_statement_line,
    reconcile,
)
from app.odoo.client import OdooFout
from app.odoo.models import OdooKoppeling
from tests.auth.conftest import beheerder_id  # noqa: F401

PIN = 6
REPO = pathlib.Path(__file__).resolve().parents[3]


class FakeClient(CompanyGepindeClient):
    """Neemt élke call op (model, methode, body) en antwoordt via een programmeerbare handler. De pin-toets en de
    post-write-verificatie van `CompanyGepindeClient` blijven volledig in werking."""

    def __init__(self, handler: Callable[[str, str, dict], Any] | None = None, **kw: Any) -> None:
        super().__init__(url="https://odoo.test", api_key="GEHEIM", company_id=PIN, pin=PIN, min_tussenpoos_s=0, **kw)
        self.calls: list[tuple[str, str, dict]] = []
        self.handler = handler or (lambda model, methode, body: [])

    def _post(self, model: str, methode: str, body: dict) -> Any:  # type: ignore[override]
        self.calls.append((model, methode, body))
        antwoord = self.handler(model, methode, body)
        if isinstance(antwoord, OdooFout):
            raise antwoord
        return antwoord

    def methoden(self) -> list[str]:
        return [f"{m}.{meth}" for m, meth, _ in self.calls]


def _fout(status: int, melding: str = "", model: str = "x", methode: str = "y") -> OdooFout:
    return OdooFout(status, None, melding, model=model, methode=methode)


@pytest.fixture
def writes_aan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "migratie_odoo_writes_ingeschakeld", True)


# --- kill-switch ------------------------------------------------------------------------------------------------------


class TestKillSwitch:
    def test_default_uit_in_code_en_suite(self) -> None:
        assert settings.migratie_odoo_writes_ingeschakeld is False

    def test_elke_primitief_weigert_voor_de_eerste_call(self) -> None:
        c = FakeClient()
        a = GeheugenAudit()
        with pytest.raises(MigratieWritesUit):
            maak_concept_move(c, {"move_type": "entry"}, anker="a", audit=a)
        with pytest.raises(MigratieWritesUit):
            maak_statement_line(c, {"journal_id": 53}, anker="a", audit=a)
        with pytest.raises(MigratieWritesUit):
            reconcile(c, move_line_ids=[1], statement_line_id=2, audit=a)
        with pytest.raises(MigratieWritesUit):
            annuleer_concept(c, 1, reden="x", audit=a)
        with pytest.raises(MigratieWritesUit):
            koppel_los(c, move_line_ids=[1], audit=a)
        assert c.calls == [] and a.regels == []


# --- concept-move -----------------------------------------------------------------------------------------------------


class TestConceptMove:
    def test_zoek_voor_create_bestaand_anker_geen_tweede_create(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode == "search_read":
                assert body["domain"][1] == ["ref", "ilike", "mig:anker-1"]
                return [{"id": 3001, "state": "draft", "company_id": [PIN, "VGG"], "ref": "RLZ-04-1 · mig:anker-1"}]
            raise AssertionError(f"onverwacht {methode}")

        c = FakeClient(handler)
        a = GeheugenAudit()
        assert maak_concept_move(c, {"move_type": "in_invoice", "ref": "RLZ-04-1"}, anker="anker-1", audit=a) == 3001
        assert c.methoden() == ["account.move.search_read"]
        assert a.regels[0]["actie"] == "odoo_migratie_move_bestaat" and a.regels[0]["nieuwe_waarde"]["odoo_id"] == 3001

    def test_create_zet_company_en_marker_en_leest_draft_terug(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode == "search_read":
                return []
            if methode == "create":
                vals = body["vals_list"][0]
                assert vals["company_id"] == PIN and vals["ref"] == "RLZ-04-00000123 · mig:anker-2"
                return [3002]
            if methode == "read":
                return [
                    {
                        "id": 3002,
                        "state": "draft",
                        "company_id": [PIN, "VGG"],
                        "name": "/",
                        "ref": "RLZ-04-00000123 · mig:anker-2",
                    }
                ]
            raise AssertionError(methode)

        c = FakeClient(handler)
        a = GeheugenAudit()
        vals = {
            "move_type": "in_invoice",
            "journal_id": 49,
            "date": "2025-07-03",
            "ref": "RLZ-04-00000123",
            "invoice_line_ids": [[0, 0, {"name": "koopsom", "tax_ids": [[6, 0, []]]}]],
        }
        assert maak_concept_move(c, vals, anker="anker-2", audit=a) == 3002
        assert c.methoden() == [
            "account.move.search_read",
            "account.move.create",
            "account.move.read",
            "account.move.read",
        ]
        laatste = a.regels[-1]
        assert laatste["actie"] == "odoo_migratie_move_aangemaakt"
        assert laatste["nieuwe_waarde"] == {
            "model": "account.move",
            "methode": "create",
            "company": PIN,
            "odoo_id": 3002,
            "anker": "anker-2",
            "move_type": "in_invoice",
            "journal_id": 49,
            "date": "2025-07-03",
            "ref": "RLZ-04-00000123 · mig:anker-2",
            "state": "draft",
        }
        assert vals["ref"] == "RLZ-04-00000123"  # invoer niet gemuteerd

    def test_meerdere_treffers_is_meerduidig(self, writes_aan: None) -> None:
        c = FakeClient(lambda m, meth, b: [{"id": 1, "state": "draft"}, {"id": 2, "state": "draft"}])
        with pytest.raises(AnkerMeerduidig):
            maak_concept_move(c, {}, anker="dubbel", audit=GeheugenAudit())
        assert c.methoden() == ["account.move.search_read"]

    def test_niet_draft_wordt_geannuleerd_nooit_unlink(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode == "search_read":
                return []
            if methode == "create":
                return [3003]
            if methode == "read":
                return [{"id": 3003, "state": "posted", "company_id": [PIN, "VGG"]}]
            if methode == "button_cancel":
                return True
            raise AssertionError(methode)

        c = FakeClient(handler)
        a = GeheugenAudit()
        with pytest.raises(ConceptNietDraft):
            maak_concept_move(c, {"move_type": "entry"}, anker="a3", audit=a)
        assert "account.move.button_cancel" in c.methoden() and not any("unlink" in m for m in c.methoden())
        assert a.regels[-1]["actie"] == "odoo_migratie_move_geannuleerd"

    def test_post_write_company_mismatch_annuleert_en_stopt(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode == "search_read":
                return []
            if methode == "create":
                return [3004]
            if methode == "read":
                return [{"id": 3004, "state": "draft", "company_id": [1, "Universal"]}]
            if methode == "button_cancel":
                return True
            raise AssertionError(methode)

        c = FakeClient(handler)
        with pytest.raises(CompanyPinGeschonden, match="POST-WRITE"):
            maak_concept_move(c, {"move_type": "entry"}, anker="a4", audit=GeheugenAudit())
        assert c.methoden() == [
            "account.move.search_read",
            "account.move.create",
            "account.move.read",
            "account.move.button_cancel",
        ]

    def test_vals_met_andere_company_komt_niet_voorbij_de_pin(self, writes_aan: None) -> None:
        c = FakeClient(lambda m, meth, b: [])
        # `company_id` in vals wordt door de primitief op de pin gezet — maar een regel met een andere company niet
        with pytest.raises(CompanyPinGeschonden):
            maak_concept_move(c, {"line_ids": [[0, 0, {"company_id": 1}]]}, anker="a5", audit=GeheugenAudit())
        assert c.methoden() == ["account.move.search_read"]


# --- statement line ---------------------------------------------------------------------------------------------------


class TestStatementLine:
    def test_create_met_unique_import_id_en_terug_lezen(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode == "search_read":
                assert ["unique_import_id", "=", "mut-1"] in body["domain"] and ["journal_id", "=", 53] in body[
                    "domain"
                ]
                return []
            if methode == "create":
                vals = body["vals_list"][0]
                assert vals["unique_import_id"] == "mut-1" and vals["ref"] == "mut-1" and vals["company_id"] == PIN
                return [501]
            if methode == "read":
                return [
                    {
                        "id": 501,
                        "company_id": [PIN, "VGG"],
                        "move_id": [9001, "BNK1/2025/07/0001"],
                        "is_reconciled": False,
                        "unique_import_id": "mut-1",
                    }
                ]
            raise AssertionError(methode)

        c = FakeClient(handler)
        a = GeheugenAudit()
        vals = {
            "date": "2025-07-01",
            "journal_id": 53,
            "payment_ref": "Notaris X afrekening",
            "amount": -1245.0,
            "partner_name": "Notaris X",
            "account_number": "NL00TEST0123456789",
        }
        assert maak_statement_line(c, vals, anker="mut-1", audit=a) == 501
        nw = a.regels[-1]["nieuwe_waarde"]
        assert a.regels[-1]["actie"] == "odoo_migratie_statement_line_aangemaakt"
        assert nw["move_id"] == 9001 and nw["is_reconciled"] is False and nw["unique_import_id_teruggelezen"] == "mut-1"

    def test_bestaande_regel_geen_tweede_create(self, writes_aan: None) -> None:
        c = FakeClient(lambda m, meth, b: [{"id": 502, "move_id": [9002, "x"], "is_reconciled": True}])
        a = GeheugenAudit()
        assert (
            maak_statement_line(c, {"journal_id": 53, "date": "2025-07-01", "amount": 1.0}, anker="mut-2", audit=a)
            == 502
        )
        assert c.methoden() == ["account.bank.statement.line.search_read"]
        assert a.regels[-1]["actie"] == "odoo_migratie_statement_line_bestaat"


# --- reconcile --------------------------------------------------------------------------------------------------------


class TestReconcileRegistry:
    def _handler_route_ii(self) -> Callable[[str, str, dict], Any]:
        def handler(model, methode, body):
            if model == "account.bank.statement.line" and methode == "set_line_bank_statement_line":
                return _fout(404, "the method does not exist", model=model, methode=methode)
            if model == "account.bank.statement.line" and methode == "read":
                if body["fields"] == ["is_reconciled"]:
                    return [{"id": 501, "is_reconciled": handler.reconciled}]
                return [{"id": 501, "move_id": [9001, "x"], "journal_id": [53, "BNK1"]}]
            if model == "account.journal" and methode == "read":
                return [{"id": 53, "default_account_id": [2175, "103001 Bank"]}]
            if model == "account.move.line" and methode == "search_read":
                return [
                    {"id": 71, "account_id": [2175, "103001 Bank"], "reconciled": False},
                    {"id": 72, "account_id": [398, "103002 Suspense"], "reconciled": False},
                ]
            if model == "account.move.line" and methode == "write":
                assert body["ids"] == [72] and body["vals"] == {"account_id": 110, "partner_id": 65}
                return True
            if model == "account.move.line" and methode == "reconcile":
                assert body["ids"] == [72, 4001]
                handler.reconciled = True
                return {}
            raise AssertionError((model, methode))

        handler.reconciled = False  # type: ignore[attr-defined]
        return handler

    def test_route_i_404_dan_route_ii_werkt(self, writes_aan: None) -> None:
        c = FakeClient(self._handler_route_ii())
        a = GeheugenAudit()
        u = reconcile(c, move_line_ids=[4001], statement_line_id=501, tegenrekening_id=110, partner_id=65, audit=a)
        assert u.route == "ii" and u.geslaagd and u.is_reconciled is True
        assert (
            u.pogingen[0]["route"] == "i"
            and u.pogingen[0]["uitkomst"] == "bestaat niet"
            and u.pogingen[0]["status"] == 404
        )
        assert u.pogingen[1]["route"] == "ii" and u.pogingen[1]["suspense_line_id"] == 72
        assert a.regels[-1]["actie"] == "odoo_migratie_reconcile" and a.regels[-1]["nieuwe_waarde"]["route"] == "ii"
        assert "account.reconcile.model.search_read" not in c.methoden()  # iii niet meer geprobeerd

    def test_geen_route_werkt(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode in ("set_line_bank_statement_line", "action_reconcile"):
                return _fout(403, "private", model=model, methode=methode)
            if model == "account.reconcile.model":
                return [{"id": 13, "name": "Internal Transfers"}]
            if methode == "read":
                return [
                    {
                        "id": 501,
                        "move_id": [9001, "x"],
                        "journal_id": [53, "b"],
                        "default_account_id": [2175, "b"],
                        "is_reconciled": False,
                    }
                ]
            if methode == "search_read":
                return [{"id": 71, "account_id": [2175, "b"]}, {"id": 72, "account_id": [398, "s"]}]
            if methode == "write":
                return True
            if methode == "reconcile":
                return _fout(422, "UserError: niets te reconcilen", model=model, methode=methode)
            raise AssertionError((model, methode))

        c = FakeClient(handler)
        a = GeheugenAudit()
        u = reconcile(c, move_line_ids=[4001], statement_line_id=501, tegenrekening_id=110, audit=a)
        assert u.route is None and not u.geslaagd
        assert [p["uitkomst"] for p in u.pogingen] == ["bestaat niet", "fout", "bestaat niet"]
        assert a.regels[-1]["actie"] == "odoo_migratie_reconcile_geen_route"

    def test_route_ii_zonder_tegenrekening_wordt_overgeslagen(self, writes_aan: None) -> None:
        c = FakeClient(lambda m, meth, b: _fout(404, model=m, methode=meth) if meth != "search_read" else [])
        u = reconcile(c, move_line_ids=[1], statement_line_id=501, audit=GeheugenAudit())
        assert u.route is None and [p["route"] for p in u.pogingen] == ["i", "ii", "iii"]


# --- terugweg ---------------------------------------------------------------------------------------------------------


class TestTerugweg:
    def test_annuleer_is_button_cancel_en_nooit_unlink(self, writes_aan: None) -> None:
        stand = {"state": "draft"}

        def handler(model, methode, body):
            if methode == "read":
                return [{"id": 3001, "state": stand["state"], "name": "/", "ref": "mig:a", "company_id": [PIN, "x"]}]
            if methode == "button_cancel":
                stand["state"] = "cancel"
                return True
            raise AssertionError(methode)

        c = FakeClient(handler)
        a = GeheugenAudit()
        annuleer_concept(c, 3001, reden="STAP-0 terugweg", audit=a)
        assert c.methoden() == ["account.move.read", "account.move.button_cancel", "account.move.read"]
        assert not any("unlink" in m for m in c.methoden())
        assert a.regels[-1]["oude_waarde"]["state"] == "draft" and a.regels[-1]["nieuwe_waarde"]["state"] == "cancel"

    def test_geposte_move_is_geen_concept(self, writes_aan: None) -> None:
        c = FakeClient(lambda m, meth, b: [{"id": 1, "state": "posted", "name": "F/2025/07/0001"}])
        with pytest.raises(NietEenConcept):
            annuleer_concept(c, 1, reden="x", audit=GeheugenAudit())
        assert c.methoden() == ["account.move.read"]

    def test_koppel_los(self, writes_aan: None) -> None:
        def handler(model, methode, body):
            if methode == "remove_move_reconcile":
                assert body["ids"] == [72, 4001]
                return True
            if methode == "read":
                return [{"id": 72, "reconciled": False}, {"id": 4001, "reconciled": False}]
            raise AssertionError(methode)

        c = FakeClient(handler)
        a = GeheugenAudit()
        koppel_los(c, move_line_ids=[72, 4001], audit=a)
        assert c.methoden() == ["account.move.line.remove_move_reconcile", "account.move.line.read"]
        assert a.regels[-1]["nieuwe_waarde"]["reconciled_na"] == {72: False, 4001: False}


# --- CLI-registratie + nameting.sh ------------------------------------------------------------------------------------


class TestCliRegistratie:
    def test_dispatch_kent_beide_commandos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gezien: list[argparse.Namespace] = []
        monkeypatch.setattr(cli, "run_odoo_migratie", lambda args: gezien.append(args) or 0)
        assert (
            cli.main(
                [
                    MIGRATIEDOEL_COMMANDO,
                    "--administratie",
                    "VGG",
                    "--bron-administratie",
                    "Universal Steigerbouw",
                    "--company",
                    "6",
                ]
            )
            == 0
        )
        assert gezien[0].company == 6 and gezien[0].dry_run is True and gezien[0].bijwerken is False
        assert (
            cli.main([STAP0_COMMANDO, "--administratie", "VGG", "--schrijf", "--stap", "1-3", "--max-per-type", "2"])
            == 0
        )
        assert gezien[1].dry_run is False and gezien[1].stap == "1-3" and gezien[1].max_per_type == 2
        assert cli.main([STAP0_COMMANDO, "--administratie", "VGG"]) == 0
        assert gezien[2].dry_run is True

    def test_parse_stappen(self) -> None:
        assert parse_stappen("1-6") == {1, 2, 3, 4, 5, 6}
        assert parse_stappen("1,2,4") == {1, 2, 4}
        with pytest.raises(ValueError):
            parse_stappen("0-9")

    def test_nameting_sh_weigert_beide_hard(self) -> None:
        script = REPO / "scripts" / "gcp" / "nameting.sh"
        tekst = script.read_text(encoding="utf-8")
        allowlist = next(r for r in tekst.splitlines() if r.startswith("ALLOWLIST="))
        for cmd in (MIGRATIEDOEL_COMMANDO, STAP0_COMMANDO):
            assert cmd not in allowlist
            assert (
                f"{cmd}" in tekst
                and "is een schrijvend commando — expliciete opdracht Peter via gcloud run jobs execute" in tekst
            )
            uitkomst = subprocess.run(
                ["bash", str(script), cmd, "--administratie", "VGG"],
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "NAMETING_ENV": "/nonexistent/nameting.env"},
            )
            assert uitkomst.returncode == 2, uitkomst.stderr
            assert f"FOUT: {cmd} is een schrijvend commando" in uitkomst.stderr
            assert "gcloud run jobs execute" in uitkomst.stderr and ">> gcloud run jobs execute" not in uitkomst.stderr


# --- migratiedoel-CLI (DB, fake envelope + fake probe) ----------------------------------------------------------------


def _administratie(admin_engine: Engine, *, naam: str, backend: str) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boekhoud_backend) "
                "VALUES (:id, :naam, :rlz, :backend)"
            ),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}", "backend": backend},
        )
    return aid


def _fake_wrap(plaintext: bytes) -> tuple[bytes, bytes]:
    return b"CT:" + plaintext, b"WK:fake"


def _fake_unwrap(ciphertext: bytes, wrapped: bytes) -> bytes:
    assert wrapped == b"WK:fake" and ciphertext.startswith(b"CT:")
    return ciphertext[3:]


def _groene_probe(client: Any) -> DagboekProbe:
    assert client.read_only is True and client.company_id == PIN
    return DagboekProbe(
        company_naam="Vastgoedgroep Nederland B.V.",
        journal_sale_id=48,
        journal_purchase_id=49,
        journal_general_id=50,
        journal_bank_id=53,
        analytic_plan_id=1,
        rapport={"dagboek:sale": "ok (F id 48)", "dagboek:bank": "ok (BNK1 id 53)"},
    )


class _LeesClientStub:
    def __init__(self, **kw: Any) -> None:
        self.read_only = kw.get("read_only")
        self.company_id = kw.get("company_id")
        assert kw["api_key"] == "geheime-key-universal" and kw["url"] == "https://universal-steigers.odoo.com"

    def __enter__(self) -> _LeesClientStub:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def bron_en_doel(admin_engine: Engine, beheerder_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:  # noqa: F811
    bron = _administratie(admin_engine, naam="Universal Steigerbouw (odoo)", backend="odoo")
    doel = _administratie(admin_engine, naam="Vastgoedgroep Nederland B.V.", backend="rlz")
    ct, wk = _fake_wrap(b"geheime-key-universal")
    with scoped_session(None, actor_id=beheerder_id) as session:
        session.add(
            OdooKoppeling(
                administratie_id=bron,
                odoo_url="https://universal-steigers.odoo.com",
                company_id=1,
                company_naam="Universal Steigerbouw",
                api_gebruiker="module@nijenhuis",
                api_key_ciphertext=ct,
                wrapped_data_key=wk,
                aangemaakt_door=beheerder_id,
            )
        )
    return bron, doel


class TestMigratiedoelCli:
    def test_dry_run_schrijft_niets(self, bron_en_doel: tuple[uuid.UUID, uuid.UUID], admin_engine: Engine) -> None:
        bron, doel = bron_en_doel
        u = maak_migratiedoel(
            doel_id=doel,
            bron_id=bron,
            company_id=6,
            dry_run=True,
            probe=_groene_probe,
            client_factory=_LeesClientStub,
            wrap=_fake_wrap,
            unwrap=_fake_unwrap,
        )
        assert u.geschreven is False and u.probe.groen and "DRY-RUN" in u.als_markdown()
        assert "geheime-key" not in u.als_markdown()
        with admin_engine.begin() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.odoo_koppeling WHERE administratie_id = :id"), {"id": doel}
                ).scalar()
                == 0
            )

    def test_schrijf_maakt_migratiedoel_rij_met_audit_zonder_key(
        self, bron_en_doel: tuple[uuid.UUID, uuid.UUID], admin_engine: Engine
    ) -> None:
        bron, doel = bron_en_doel
        u = maak_migratiedoel(
            doel_id=doel,
            bron_id=bron,
            company_id=6,
            dry_run=False,
            probe=_groene_probe,
            client_factory=_LeesClientStub,
            wrap=_fake_wrap,
            unwrap=_fake_unwrap,
        )
        assert u.geschreven is True and u.bijgewerkt is False
        with admin_engine.begin() as conn:
            rij = conn.execute(
                text(
                    "SELECT company_id, company_naam, api_gebruiker, api_key_ciphertext, wrapped_data_key, "
                    "journal_sale_id, journal_purchase_id, journal_general_id, analytic_plan_id, probe_rapport, "
                    "alleen_lezen, migratie_doel FROM platform.odoo_koppeling WHERE administratie_id = :id"
                ),
                {"id": doel},
            ).one()
            assert (
                rij.company_id == 6
                and rij.company_naam == "Vastgoedgroep Nederland B.V."
                and rij.api_gebruiker == "module@nijenhuis"
            )
            assert (
                bytes(rij.api_key_ciphertext) == b"CT:geheime-key-universal"
                and bytes(rij.wrapped_data_key) == b"WK:fake"
            )
            assert (rij.journal_sale_id, rij.journal_purchase_id, rij.journal_general_id, rij.analytic_plan_id) == (
                48,
                49,
                50,
                1,
            )
            assert (
                rij.probe_rapport[PROBE_SLEUTEL_BANKDAGBOEK] == "53"
                and rij.alleen_lezen is False
                and rij.migratie_doel is True
            )
            audit = (
                conn.execute(
                    text(
                        "SELECT nieuwe_waarde::text FROM platform.audit_event "
                        "WHERE actie = 'odoo_koppeling_migratiedoel_aangemaakt' AND record_id = :id"
                    ),
                    {"id": doel},
                )
                .scalars()
                .all()
            )
        assert len(audit) == 1 and '"company_id": 6' in audit[0] and '"journal_bank_id": 53' in audit[0]
        assert "geheime" not in audit[0] and "CT:" not in audit[0]
        # de doelkoppeling is nu leesbaar voor de migratie — en blijft geweigerd voor de dagelijkse adapter
        from app.migratie.odoo_doel import doelkoppeling_voor
        from app.odoo.credentials import GeenOdooKoppeling, koppeling_voor

        doelk = doelkoppeling_voor(doel)
        assert doelk.company_id == 6 and doelk.journal_bank_id == 53
        with pytest.raises(GeenOdooKoppeling):
            koppeling_voor(doel)
        # tweede keer zonder --bijwerken = weigering; mét = bijgewerkt
        with pytest.raises(MigratiedoelFout, match="--bijwerken"):
            maak_migratiedoel(
                doel_id=doel,
                bron_id=bron,
                company_id=6,
                dry_run=False,
                probe=_groene_probe,
                client_factory=_LeesClientStub,
                wrap=_fake_wrap,
                unwrap=_fake_unwrap,
            )
        u2 = maak_migratiedoel(
            doel_id=doel,
            bron_id=bron,
            company_id=6,
            dry_run=False,
            bijwerken=True,
            probe=_groene_probe,
            client_factory=_LeesClientStub,
            wrap=_fake_wrap,
            unwrap=_fake_unwrap,
        )
        assert u2.bijgewerkt is True

    def test_weigert_odoo_backend_en_rode_probe(
        self, bron_en_doel: tuple[uuid.UUID, uuid.UUID], admin_engine: Engine
    ) -> None:
        bron, doel = bron_en_doel
        odoo_admin = _administratie(admin_engine, naam="Al Odoo", backend="odoo")
        with pytest.raises(MigratiedoelFout, match="draait al op Odoo"):
            maak_migratiedoel(
                doel_id=odoo_admin,
                bron_id=bron,
                company_id=6,
                dry_run=True,
                probe=_groene_probe,
                client_factory=_LeesClientStub,
                wrap=_fake_wrap,
                unwrap=_fake_unwrap,
            )

        def rood(client: Any) -> DagboekProbe:
            return DagboekProbe(
                company_naam="x",
                journal_sale_id=48,
                journal_purchase_id=49,
                journal_general_id=None,
                journal_bank_id=53,
                analytic_plan_id=1,
                rapport={"dagboek:general": "5 general-dagboeken — meerduidig"},
            )

        with pytest.raises(MigratiedoelFout, match="niet groen"):
            maak_migratiedoel(
                doel_id=doel,
                bron_id=bron,
                company_id=6,
                dry_run=False,
                probe=rood,
                client_factory=_LeesClientStub,
                wrap=_fake_wrap,
                unwrap=_fake_unwrap,
            )
        with admin_engine.begin() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.odoo_koppeling WHERE administratie_id = :id"), {"id": doel}
                ).scalar()
                == 0
            )

    def test_lees_dagboeken_kiest_mem_bij_meerdere_general_en_meldt_meerduidig(self) -> None:
        journals = [
            {"id": 48, "code": "F", "name": "Verkoop", "type": "sale"},
            {"id": 49, "code": "LF", "name": "Inkoop", "type": "purchase"},
            {"id": 50, "code": "MEM", "name": "Memoriaal", "type": "general"},
            {"id": 51, "code": "EXCH", "name": "x", "type": "general"},
            {"id": 54, "code": "TAX", "name": "x", "type": "general"},
            {"id": 53, "code": "BNK1", "name": "Bank", "type": "bank"},
        ]

        def handler(model, methode, body):
            if model == "account.journal":
                assert body["domain"] == [["company_id", "=", PIN]]
                return journals
            if model == "account.analytic.plan":
                return [{"id": 1, "name": "Project"}]
            if model == "res.company":
                return [{"id": PIN, "name": "Vastgoedgroep Nederland B.V."}]
            raise AssertionError(model)

        c = FakeClient(handler, read_only=True)
        p = lees_dagboeken(c)
        assert (
            p.journal_sale_id,
            p.journal_purchase_id,
            p.journal_general_id,
            p.journal_bank_id,
            p.analytic_plan_id,
        ) == (48, 49, 50, 53, 1)
        assert p.groen and "gekozen op code" in p.rapport["dagboek:general"]
        journals.append({"id": 60, "code": "BNK2", "name": "Bank 2", "type": "bank"})
        p2 = lees_dagboeken(FakeClient(handler, read_only=True))
        assert p2.journal_bank_id is None and "meerduidig" in p2.rapport["dagboek:bank"] and not p2.groen
        assert all(meth != "create" for _, meth, _ in c.calls)


# --- stap-0-cyclus (fake replay + fake client) ------------------------------------------------------------------------


@dataclass
class _Move:
    anker: str
    rlz_id: str
    boekstuk: str
    move_type: str
    date: str
    vals: dict
    bank: dict | None
    status: str
    reden: str = ""


def _moves() -> list[_Move]:
    def mv(n: int, soort: str, dag: str, status: str = "vertaalbaar", bank: dict | None = None) -> _Move:
        # E's vorm (vertaling.py): bankregel = move_type 'bank', vals = statement-line-vals, bank = extra blok mét
        # `reconcile`
        if bank is not None:
            vals = {
                "date": dag,
                "journal_id": 53,
                "payment_ref": bank.pop("payment_ref"),
                "amount": bank.pop("amount"),
                "ref": f"anker-{soort}-{n}",
            }
            return _Move(
                anker=f"anker-{soort}-{n}",
                rlz_id=f"rlz-{n}",
                boekstuk=f"RLZ-{n:05d}",
                move_type="bank",
                date=dag,
                vals=vals,
                bank=bank,
                status=status,
            )
        return _Move(
            anker=f"anker-{soort}-{n}",
            rlz_id=f"rlz-{n}",
            boekstuk=f"RLZ-{n:05d}",
            move_type=soort,
            date=dag,
            vals={
                "move_type": soort,
                "journal_id": 49,
                "date": dag,
                "ref": f"RLZ-{n:05d}",
                "invoice_line_ids": [[0, 0, {"name": "r", "tax_ids": [[6, 0, []]]}]],
            },
            bank=None,
            status=status,
        )

    return [
        mv(1, "in_invoice", "2025-07-03"),
        mv(2, "in_invoice", "2025-07-01"),
        mv(3, "in_invoice", "2025-07-05"),
        mv(4, "in_invoice", "2025-07-06"),
        mv(5, "in_invoice", "2025-06-30"),  # buiten juli
        mv(6, "entry", "2025-07-02"),
        mv(7, "out_invoice", "2025-07-10"),
        mv(8, "out_invoice", "2025-07-11", status="zonder_pand"),
        mv(
            9,
            "bank",
            "2025-07-02",
            bank={
                "payment_ref": "Notaris X",
                "amount": -1000.0,
                "reconcile": [
                    {
                        "anker": "anker-in_invoice-2",
                        "boekstuk": "RLZ-00002",
                        "move_type": "in_invoice",
                        "bedrag": "-1000.00",
                    }
                ],
            },
        ),
        mv(
            10,
            "bank",
            "2025-07-02",
            bank={"payment_ref": "Bank fee", "amount": -1.5, "tegenregel": [{"account_id": 700, "bedrag": "1.50"}]},
        ),
        mv(11, "bank", "2025-07-09", bank={"payment_ref": "later", "amount": 5.0}),
    ]


class _Replay:
    def __init__(self, moves: list[_Move]) -> None:
        self.moves = moves
        self.aanroepen: list[uuid.UUID] = []

    def dry_run(self, administratie_id: uuid.UUID) -> Any:
        self.aanroepen.append(administratie_id)
        return type("Rapport", (), {"moves": self.moves})()


class TestStap0:
    def test_selectie_juli_max_per_type_en_eerste_bankdag(self) -> None:
        sel = selecteer_moves(_moves(), max_per_type=3)
        assert [m.boekstuk for m in sel["in_invoice"]] == ["RLZ-00002", "RLZ-00001", "RLZ-00003"]
        assert [m.boekstuk for m in sel["entry"]] == ["RLZ-00006"]
        assert [m.boekstuk for m in sel["out_invoice"]] == ["RLZ-00007"]  # zonder_pand niet
        assert [m.boekstuk for m in sel["bank"]] == ["RLZ-00009", "RLZ-00010"]  # alleen 02-07

    def test_e_nog_niet_klaar_wordt_gemeld(self) -> None:
        r = voer_stap0_uit(
            uuid.uuid4(),
            administratie_naam="VGG",
            schrijf=False,
            stappen=range(1, 7),
            max_per_type=3,
            client_factory=lambda aid: FakeClient(),
            replay_module=None,
            audit=GeheugenAudit(),
            writes_aan=False,
        )
        assert r.replay_beschikbaar is False and all(s.oordeel == "niet uitgevoerd" for s in r.stappen.values())
        assert "nog niet beschikbaar" in r.als_markdown()

    def test_laad_replay_geeft_none_zonder_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "app.migratie.replay", None)  # importeren geeft dan ImportError
        assert cli_odoo._laad_replay() is None

    def test_dry_run_doet_geen_odoo_call_en_toont_plan(self) -> None:
        c = FakeClient(read_only=True)
        replay = _Replay(_moves())
        r = voer_stap0_uit(
            uuid.uuid4(),
            administratie_naam="VGG",
            schrijf=False,
            stappen=range(1, 7),
            max_per_type=3,
            client_factory=lambda aid: c,
            replay_module=replay,
            audit=GeheugenAudit(),
            writes_aan=False,
        )
        md = r.als_markdown()
        assert c.calls == [] and r.company_id == PIN and len(replay.aanroepen) == 1
        assert "ZOU aanmaken: RLZ-00002" in md and "ZOU reconcilen" in md and "DRY-RUN" in md
        assert all(s.oordeel == "niet uitgevoerd" for s in r.stappen.values())

    def test_schrijf_zonder_kill_switch_valt_terug_op_dry_run(self) -> None:
        c = FakeClient(read_only=True)
        r = voer_stap0_uit(
            uuid.uuid4(),
            administratie_naam="VGG",
            schrijf=True,
            stappen={1},
            max_per_type=1,
            client_factory=lambda aid: c,
            replay_module=_Replay(_moves()),
            audit=GeheugenAudit(),
            writes_aan=False,
        )
        assert r.schrijf is False and c.calls == [] and any("kill-switch staat UIT" in m for m in r.meldingen)

    def test_geen_migratiedoel_zichtbaar(self) -> None:
        def geen(aid: uuid.UUID) -> CompanyGepindeClient:
            raise GeenMigratieDoel("geen rij")

        r = voer_stap0_uit(
            uuid.uuid4(),
            administratie_naam="VGG",
            schrijf=False,
            stappen={1},
            max_per_type=1,
            client_factory=geen,
            replay_module=_Replay([]),
            audit=GeheugenAudit(),
            writes_aan=False,
        )
        assert any("geen migratiedoel" in m for m in r.meldingen) and r.company_id is None

    def test_schrijf_cyclus_1_tot_6_op_fake_client(self, writes_aan: None) -> None:
        odoo: dict[str, Any] = {"moves": {}, "stl": {}, "volgend": 3000, "reconciled": False}

        def handler(model, methode, body):
            if model == "account.move" and methode == "search_read":
                ref = body["domain"][1][2]
                return [dict(m, id=i) for i, m in odoo["moves"].items() if ref in m["ref"] and m["state"] != "cancel"]
            if model == "account.move" and methode == "create":
                odoo["volgend"] += 1
                vals = body["vals_list"][0]
                odoo["moves"][odoo["volgend"]] = {
                    "state": "draft",
                    "company_id": [PIN, "VGG"],
                    "ref": vals["ref"],
                    "move_type": vals["move_type"],
                    "name": "/",
                }
                return [odoo["volgend"]]
            if model == "account.move" and methode == "read":
                return [dict(odoo["moves"][i], id=i) for i in body["ids"] if i in odoo["moves"]]
            if model == "account.move" and methode == "button_cancel":
                for i in body["ids"]:
                    odoo["moves"][i]["state"] = "cancel"
                return True
            if model == "account.bank.statement.line" and methode == "search_read":
                return []
            if model == "account.bank.statement.line" and methode == "create":
                odoo["volgend"] += 1
                odoo["stl"][odoo["volgend"]] = {
                    "company_id": [PIN, "VGG"],
                    "move_id": [9000 + odoo["volgend"], "BNK1/…"],
                    "journal_id": [53, "BNK1"],
                    "unique_import_id": body["vals_list"][0]["unique_import_id"],
                }
                return [odoo["volgend"]]
            if model == "account.bank.statement.line" and methode == "read":
                return [dict(odoo["stl"][i], id=i, is_reconciled=odoo["reconciled"]) for i in body["ids"]]
            if model == "account.bank.statement.line" and methode == "set_line_bank_statement_line":
                return _fout(403, "private method", model=model, methode=methode)
            if model == "account.move.line" and methode == "search_read":
                if any(t[0] == "account_id.account_type" for t in body["domain"] if isinstance(t, list)):
                    return [{"id": 4001, "account_id": [110, "110000 Debtors"], "partner_id": [65, "Notaris"]}]
                return [
                    {"id": 71, "account_id": [2175, "103001"], "reconciled": False},
                    {"id": 72, "account_id": [398, "103002"], "reconciled": False},
                ]
            if model == "account.journal" and methode == "read":
                return [{"id": 53, "default_account_id": [2175, "103001"]}]
            if model == "account.move.line" and methode == "write":
                return True
            if model == "account.move.line" and methode == "reconcile":
                odoo["reconciled"] = True
                return {}
            if model == "account.move.line" and methode == "remove_move_reconcile":
                odoo["reconciled"] = False
                return True
            if model == "account.move.line" and methode == "read":
                return [{"id": i, "reconciled": False} for i in body["ids"]]
            raise AssertionError((model, methode, body))

        c = FakeClient(handler)
        a = GeheugenAudit()
        r = voer_stap0_uit(
            uuid.uuid4(),
            administratie_naam="VGG",
            schrijf=True,
            stappen=range(1, 7),
            max_per_type=3,
            client_factory=lambda aid: c,
            replay_module=_Replay(_moves()),
            audit=a,
            writes_aan=True,
        )
        assert [r.stappen[n].oordeel for n in range(1, 7)] == ["ja", "ja", "ja", "ja", "ja", "ja"], r.als_markdown()
        assert len(r.stappen[1].odoo_ids) == 3 and len(r.stappen[4].odoo_ids) == 2
        assert "route ii" in r.stappen[5].regels[0]
        assert odoo["moves"][r.stappen[1].odoo_ids[0]]["state"] == "cancel"  # terugweg op het eerste concept
        assert all(m["company_id"][0] == PIN for m in odoo["moves"].values())
        assert not any("unlink" in m for m in c.methoden())
        acties = [x["actie"] for x in a.regels]
        assert (
            acties.count("odoo_migratie_move_aangemaakt") == 5
            and acties.count("odoo_migratie_statement_line_aangemaakt") == 2
        )
        assert (
            "odoo_migratie_reconcile" in acties
            and "odoo_migratie_koppel_los" in acties
            and acties[-1] == "odoo_migratie_move_geannuleerd"
        )
        assert "werkt" not in r.als_markdown().lower() or "| **ja** |" in r.als_markdown()
