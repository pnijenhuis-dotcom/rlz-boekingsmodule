# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 2 bundelrun 24-09 (Peter: "GB's allemaal in het Engels in de module, in Odoo zelf NL"): de hersync via de
BESTAANDE route (`sync_alles_voor_odoo_administratie`, nachtelijk in `sync-alles` en op verzoek via
`odoo-stamgegevens-sync`) overschrijft een Engelse cache-naam met de NL-naam uit de client-respons; de CLI hergebruikt
`odoo_service.eerste_sync` (sync-run-rij) en kent een dry-run zonder Odoo-call."""

from __future__ import annotations

import argparse
import io
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, text

from app.odoo import sync as odoo_sync
from app.odoo import sync_cli
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

LEDGER_ODOO_ID = 4711


@pytest.fixture
def odoo_administratie(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:
    from app.db.session import scoped_session
    from app.odoo.models import OdooKoppeling
    from app.security.envelope import wrap_secret

    ciphertext, wrapped = wrap_secret(b"key")
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET boekhoud_backend = 'odoo', naam = 'Bonte Hoeve' WHERE id = :id"),
            {"id": administratie_id},
        )
    with scoped_session(None, actor_id=beheerder_id) as session:
        session.add(
            OdooKoppeling(
                administratie_id=administratie_id,
                odoo_url="https://test.odoo.com",
                company_id=6,
                company_naam="Bonte Hoeve",
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                aangemaakt_door=beheerder_id,
            )
        )
    return administratie_id


def _grootboek_naam(admin_engine: Engine, aid: uuid.UUID, code: str) -> str | None:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT naam FROM platform.grootboekrekening WHERE administratie_id = :a AND code = :c"),
            {"a": aid, "c": code},
        ).scalar()


def _fake_grootboek(naam: str):  # noqa: ANN202
    def lees(client, vertaler):  # noqa: ANN001
        return [
            {
                "id": str(vertaler.lokaal("account.account", LEDGER_ODOO_ID, f"1300 {naam}")),
                "code": "1300",
                "naam": naam,
                "soort": 3,
                "odoo_id": LEDGER_ODOO_ID,
                "account_type": "asset_receivable",
                "tax_ids": [],
                "standaard_taxrate_id": None,
            }
        ]

    return lees


def _stub_overige_lezers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odoo_sync, "koppeling_voor", lambda aid: SimpleNamespace(company_id=6, analytic_plan_id=None))
    monkeypatch.setattr(odoo_sync, "lees_btw", lambda c, v: [])
    monkeypatch.setattr(odoo_sync, "lees_crediteuren", lambda c, v: [])
    monkeypatch.setattr(odoo_sync, "lees_projecten", lambda c, v, plan_id: [])
    monkeypatch.setattr(odoo_sync, "lees_company_naam", lambda c: None)


def test_hersync_overschrijft_engelse_naam_met_de_nl_naam(
    odoo_administratie: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_overige_lezers(monkeypatch)
    # Eerste sync = de oude stand (client zonder lang → Odoo antwoordde en_US).
    monkeypatch.setattr(odoo_sync, "lees_grootboek", _fake_grootboek("Account Receivable"))
    r1 = odoo_sync.sync_alles_voor_odoo_administratie(administratie_id=odoo_administratie, client=SimpleNamespace())
    assert r1.ledgers.aangemaakt == 1
    assert _grootboek_naam(admin_engine, odoo_administratie, "1300") == "Account Receivable"
    # Hersync mét de taal-poort: dezelfde rekening (zelfde odoo_id → zelfde lokale uuid) krijgt de NL-naam.
    monkeypatch.setattr(odoo_sync, "lees_grootboek", _fake_grootboek("Debiteuren"))
    r2 = odoo_sync.sync_alles_voor_odoo_administratie(administratie_id=odoo_administratie, client=SimpleNamespace())
    assert (r2.ledgers.aangemaakt, r2.ledgers.bijgewerkt, r2.ledgers.verdwenen) == (0, 1, 0)
    assert _grootboek_naam(admin_engine, odoo_administratie, "1300") == "Debiteuren"


class TestCli:
    def _args(self, **kw) -> argparse.Namespace:  # noqa: ANN003
        basis = {"commando": sync_cli.COMMANDO, "administratie": None, "alles": False, "dry_run": False}
        return argparse.Namespace(**{**basis, **kw})

    def test_parser_kent_elke_argumentvorm_uit_het_meetrecept(self) -> None:
        p = argparse.ArgumentParser()
        sync_cli.register(p.add_subparsers(dest="commando"))
        for vorm in (
            ["odoo-stamgegevens-sync", "--administratie", "Bonte Hoeve"],
            ["odoo-stamgegevens-sync", "--administratie", "Bonte Hoeve", "--dry-run"],
            ["odoo-stamgegevens-sync", "--alles", "--dry-run"],
            ["odoo-stamgegevens-sync", "--alles"],
        ):
            args = p.parse_args(vorm)
            assert args.commando == sync_cli.COMMANDO
        with pytest.raises(SystemExit):
            p.parse_args(["odoo-stamgegevens-sync"])  # één van beide doelen is verplicht

    def test_dry_run_toont_kandidaat_zonder_odoo_call(
        self, odoo_administratie: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.odoo import service as odoo_service

        def nooit(**kw):  # noqa: ANN003, ANN202
            raise AssertionError("dry-run mag niet syncen")

        monkeypatch.setattr(odoo_service, "eerste_sync", nooit)
        uit = io.StringIO()
        rc = sync_cli.run(self._args(administratie="Bonte Hoeve", dry_run=True), uit=uit)
        assert rc == 0
        assert "DRY-RUN" in uit.getvalue() and "ZOU SYNCEN  Bonte Hoeve" in uit.getvalue()

    def test_echt_hergebruikt_de_eerste_sync_route_en_toont_bijgewerkt(
        self, odoo_administratie: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_overige_lezers(monkeypatch)
        monkeypatch.setattr(odoo_sync, "lees_grootboek", _fake_grootboek("Account Receivable"))
        odoo_sync.sync_alles_voor_odoo_administratie(administratie_id=odoo_administratie, client=SimpleNamespace())
        monkeypatch.setattr(odoo_sync, "lees_grootboek", _fake_grootboek("Debiteuren"))
        monkeypatch.setattr(odoo_sync, "odoo_client_voor", lambda aid: SimpleNamespace(close=lambda: None))
        uit = io.StringIO()
        rc = sync_cli.run(self._args(administratie="Bonte Hoeve"), uit=uit)
        assert rc == 0, uit.getvalue()
        assert "OK    Bonte Hoeve" in uit.getvalue() and "ledgers=1 bijgewerkt" in uit.getvalue()
        assert _grootboek_naam(admin_engine, odoo_administratie, "1300") == "Debiteuren"
        with admin_engine.connect() as conn:
            runs = conn.execute(
                text("SELECT status FROM boekhouding.administratie_sync_run WHERE administratie_id = :a"),
                {"a": odoo_administratie},
            ).scalars().all()
        assert runs == ["klaar"]

    def test_onbekende_of_niet_eenduidige_administratie_is_exit_2(self, odoo_administratie: uuid.UUID) -> None:
        rc = sync_cli.run(self._args(administratie="bestaat-niet-xyz", dry_run=True), uit=io.StringIO())
        assert rc == 2
