"""Run 2 VGG blok 5 — harde company-pin (`CompanyGepindeClient`) en de doelkoppeling (`doelkoppeling_voor`,
`doelclient_voor`). Pin-guards zonder netwerk (httpx.MockTransport telt requests = 0); doelkoppeling tegen de
test-DB."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import scoped_session
from app.migratie import odoo_doel
from app.migratie.odoo_doel import (
    PROBE_SLEUTEL_BANKDAGBOEK,
    CompanyGepindeClient,
    CompanyPinGeschonden,
    GeenMigratieDoel,
    MigratieDoel,
    doelclient_voor,
    doelkoppeling_voor,
    toets_company_pin,
)
from app.odoo.client import OdooAlleenLezen
from app.odoo.models import OdooKoppeling
from app.security.envelope import wrap_secret
from tests.auth.conftest import beheerder_id  # noqa: F401

PIN = 6


class _Transport:
    """Legt elk request vast en antwoordt per pad uit een programmeerbare tabel."""

    def __init__(self, antwoorden: dict[str, object] | None = None) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.antwoorden = antwoorden or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        for suffix, antwoord in self.antwoorden.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=antwoord(body) if callable(antwoord) else antwoord)
        return httpx.Response(200, json=[])

    def methoden(self) -> list[str]:
        return [pad.rsplit("/", 1)[-1] for pad, _ in self.requests]


def _client(transport: _Transport, **kw) -> CompanyGepindeClient:
    http = httpx.Client(base_url="https://odoo.test", transport=httpx.MockTransport(transport))
    return CompanyGepindeClient(
        url="https://odoo.test", api_key="GEHEIM", company_id=PIN, pin=PIN, client=http, min_tussenpoos_s=0, **kw
    )


class TestCompanyPinVoorDeCall:
    """De vier contract-varianten: vals, vals_list[1], domain, context — exception VÓÓR de call, requests == 0."""

    def test_vals_met_andere_company(self) -> None:
        t = _Transport()
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden):
            c.create("account.move", {"company_id": 1, "move_type": "entry"})
        assert t.requests == []

    def test_vals_list_tweede_element(self) -> None:
        t = _Transport()
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden) as exc:
            c.call("account.move", "create", vals_list=[{"company_id": PIN}, {"company_id": 3}])
        assert exc.value.gezien == 3 and "vals_list[1]" in exc.value.plek
        assert t.requests == []

    def test_domain_triple(self) -> None:
        t = _Transport()
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden):
            c.search_read("account.move", [["company_id", "=", 1]], ["id"])
        with pytest.raises(CompanyPinGeschonden):
            c.search_read("account.move", [["company_id", "in", [PIN, 2]]], ["id"])
        with pytest.raises(CompanyPinGeschonden):
            c.search_read("account.move", [["journal_id.company_id", "=", 1]], ["id"])
        # `!=` mét de pin zou juist álle andere companies opleveren
        with pytest.raises(CompanyPinGeschonden):
            c.search_read("account.move", [["company_id", "!=", PIN]], ["id"])
        assert t.requests == []

    def test_context_allowed_company_ids(self) -> None:
        t = _Transport()
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden):
            c.call("account.move", "search_read", domain=[], fields=["id"], context={"allowed_company_ids": [1]})
        with pytest.raises(CompanyPinGeschonden):
            c.call("account.move", "search_read", domain=[], fields=["id"], context={"allowed_company_ids": [PIN, 1]})
        assert t.requests == []

    def test_geneste_regels_en_orm_commandos(self) -> None:
        t = _Transport()
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden):
            c.create("account.move", {"company_id": PIN, "line_ids": [[0, 0, {"company_id": 1, "name": "x"}]]})
        with pytest.raises(CompanyPinGeschonden):
            c.create("res.partner", {"company_ids": [[6, 0, [PIN, 1]]]})
        with pytest.raises(CompanyPinGeschonden):
            c.create("account.move", {"company_id": False})
        assert t.requests == []

    def test_pure_toets_laat_pin_door(self) -> None:
        toets_company_pin(
            "account.move",
            "create",
            {
                "vals_list": [{"company_id": PIN, "line_ids": [[0, 0, {"company_id": PIN}]]}],
                "context": {"allowed_company_ids": [PIN]},
            },
            pin=PIN,
        )
        toets_company_pin(
            "account.move",
            "search_read",
            {"domain": ["|", ["company_id", "=", PIN], ["company_id", "in", [PIN]]]},
            pin=PIN,
        )
        toets_company_pin("account.move", "search_read", {"domain": [["company_id", "=", False]]}, pin=PIN)


class TestPostWriteVerificatie:
    def test_create_leest_company_terug_en_laat_pin_door(self) -> None:
        t = _Transport({"/create": [3049], "/read": [{"id": 3049, "company_id": [PIN, "VGG"]}]})
        c = _client(t)
        assert c.create("account.move", {"company_id": PIN, "move_type": "entry"}) == 3049
        assert t.methoden() == ["create", "read"]
        assert t.requests[1][1]["fields"] == ["company_id"] and t.requests[1][1]["ids"] == [3049]
        assert t.requests[0][1]["context"]["allowed_company_ids"] == [PIN]

    def test_create_met_verkeerde_company_teruggelezen_wordt_geannuleerd(self) -> None:
        t = _Transport({"/create": [77], "/read": [{"id": 77, "company_id": [1, "Universal"]}], "/button_cancel": True})
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden, match="POST-WRITE"):
            c.create("account.move", {"company_id": PIN, "move_type": "entry"})
        assert t.methoden() == ["create", "read", "button_cancel"]
        assert t.requests[2][1]["ids"] == [77]
        assert "unlink" not in t.methoden()
        assert c.laatste_herstel == {"model": "account.move", "odoo_id": 77, "actie": "button_cancel account.move 77"}

    def test_statement_line_mismatch_annuleert_de_move_erachter(self) -> None:
        t = _Transport(
            {
                "/create": [501],
                "/read": [{"id": 501, "company_id": [2, "x"], "move_id": [9001, "BNK1/…"]}],
                "/button_cancel": True,
            }
        )
        c = _client(t)
        with pytest.raises(CompanyPinGeschonden):
            c.create("account.bank.statement.line", {"company_id": PIN, "journal_id": 53, "date": "2025-07-01"})
        assert t.requests[-1][0].endswith("account.move/button_cancel") and t.requests[-1][1]["ids"] == [9001]

    def test_niet_bewaakt_model_krijgt_geen_terug_lees(self) -> None:
        # blok 7: res.partner is sinds de partners-stap óók bewaakt — een niet-bewaakt model is bv. een notitie
        t = _Transport({"/create": [5]})
        c = _client(t)
        assert c.create("mail.message", {"body": "x", "company_id": PIN}) == 5
        assert t.methoden() == ["create"]

    def test_res_partner_is_bewaakt_sinds_de_partners_stap(self) -> None:
        t = _Transport({"/create": [5], "/read": [{"id": 5, "company_id": [PIN, "VGG"]}]})
        c = _client(t)
        assert c.create("res.partner", {"name": "Notaris", "company_id": PIN}) == 5
        assert t.methoden() == ["create", "read"]

    def test_read_only_weigert_ook_remove_move_reconcile(self) -> None:
        t = _Transport()
        c = _client(t, read_only=True)
        with pytest.raises(OdooAlleenLezen):
            c.call("account.move.line", "remove_move_reconcile", ids=[1])
        with pytest.raises(OdooAlleenLezen):
            c.call("account.move", "button_cancel", ids=[1])
        assert t.requests == []

    def test_pin_moet_gelijk_zijn_aan_company(self) -> None:
        with pytest.raises(ValueError):
            CompanyGepindeClient(url="https://odoo.test", api_key="k", company_id=PIN, pin=1)


# --- doelkoppeling (DB) ---------------------------------------------------------------------------------------------


def _administratie(admin_engine: Engine, *, naam: str, backend: str = "rlz") -> uuid.UUID:
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


def _koppeling(
    aid: uuid.UUID, actor_id: uuid.UUID, admin_engine: Engine, *, migratie_doel: bool, alleen_lezen: bool = False
) -> None:
    ciphertext, wrapped = wrap_secret(b"sleutel-6")
    with scoped_session(None, actor_id=actor_id) as session:
        session.add(
            OdooKoppeling(
                administratie_id=aid,
                odoo_url="https://universal-steigers.odoo.com",
                company_id=PIN,
                company_naam="Vastgoedgroep Nederland B.V.",
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                journal_sale_id=48,
                journal_purchase_id=49,
                journal_general_id=50,
                analytic_plan_id=1,
                probe_rapport={"dagboek:bank": "ok (BNK1 id 53)", PROBE_SLEUTEL_BANKDAGBOEK: "53"},
                alleen_lezen=alleen_lezen,
                aangemaakt_door=actor_id,
            )
        )
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.odoo_koppeling SET migratie_doel = :v WHERE administratie_id = :id"),
            {"v": migratie_doel, "id": aid},
        )


class TestDoelkoppeling:
    def test_onbekende_administratie_en_geen_rij(self, admin_engine: Engine) -> None:
        with pytest.raises(GeenMigratieDoel, match="Onbekende"):
            doelkoppeling_voor(uuid.uuid4())
        aid = _administratie(admin_engine, naam="VGG zonder koppeling")
        with pytest.raises(GeenMigratieDoel, match="geen Odoo-koppeling"):
            doelkoppeling_voor(aid)

    def test_gewone_koppeling_is_geen_migratiedoel(self, admin_engine: Engine, beheerder_id: uuid.UUID) -> None:  # noqa: F811
        aid = _administratie(admin_engine, naam="VGG gewone rij")
        _koppeling(aid, beheerder_id, admin_engine, migratie_doel=False)
        with pytest.raises(GeenMigratieDoel, match="migratie_doel=false"):
            doelkoppeling_voor(aid)

    def test_alleen_lezen_rij_is_geen_migratiedoel(self, admin_engine: Engine, beheerder_id: uuid.UUID) -> None:  # noqa: F811
        aid = _administratie(admin_engine, naam="VGG leesbron")
        _koppeling(aid, beheerder_id, admin_engine, migratie_doel=True, alleen_lezen=True)
        with pytest.raises(GeenMigratieDoel, match="alleen-lezen"):
            doelkoppeling_voor(aid)

    def test_migratiedoel_op_rlz_administratie_wordt_gelezen(
        self,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,  # noqa: F811
    ) -> None:  # noqa: F811
        aid = _administratie(admin_engine, naam="Vastgoedgroep Nederland B.V. (test)")
        _koppeling(aid, beheerder_id, admin_engine, migratie_doel=True)
        doel = doelkoppeling_voor(aid)
        assert isinstance(doel, MigratieDoel)
        assert (doel.company_id, doel.journal_sale_id, doel.journal_purchase_id, doel.journal_general_id) == (
            6,
            48,
            49,
            50,
        )
        assert doel.journal_bank_id == 53 and doel.analytic_plan_id == 1 and doel.migratie_doel is True
        # de dagelijkse adapter blijft deze rij weigeren (backend rlz, niet alleen-lezen)
        from app.odoo.credentials import GeenOdooKoppeling, koppeling_voor

        with pytest.raises(GeenOdooKoppeling):
            koppeling_voor(aid)

    def test_doelclient_is_gepind_op_de_company_van_de_rij(self, admin_engine: Engine, beheerder_id: uuid.UUID) -> None:  # noqa: F811
        aid = _administratie(admin_engine, naam="VGG client")
        _koppeling(aid, beheerder_id, admin_engine, migratie_doel=True)
        client = doelclient_voor(aid)
        try:
            assert isinstance(client, CompanyGepindeClient) and client.pin == 6 and client.company_id == 6
            assert client.read_only is False
            with pytest.raises(CompanyPinGeschonden):
                client.create("account.move", {"company_id": 1})
        finally:
            client.close()
        lezer = doelclient_voor(aid, read_only=True)
        try:
            assert lezer.read_only is True
        finally:
            lezer.close()

    def test_bankdagboek_uit_probe_robuust(self) -> None:
        assert odoo_doel._bankdagboek_uit_probe(None) is None
        assert odoo_doel._bankdagboek_uit_probe({PROBE_SLEUTEL_BANKDAGBOEK: "abc"}) is None
        assert odoo_doel._bankdagboek_uit_probe({PROBE_SLEUTEL_BANKDAGBOEK: 53}) == 53
