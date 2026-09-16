"""Run 2 VGG blok 8 (15-09, STAP 1): expliciete rekeningmapping — tabel-guard (1012 → outstanding payments, fase a;
1001 = SCHRIJF-b-markering), lees-only resolutie van de outstanding-rekening (dagboek → company → klikpunt), toepassing
op de grootboekvertaling, groepstoets (1012 in de bankgroep + modelpunt 1001 zichtbaar), voorstel-kolom bij ongemapte
rekeningen en de replay die de Odoo-rekeningen zelf via de doelkoppeling leest. Geen netwerk, geen DB."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.migratie import rekening_mapping as rm
from app.migratie import replay
from app.migratie.rapport import als_markdown
from app.migratie.vertaling import Context, Doel, GrootboekVertaling, RolRekeningen
from tests.migratie.test_replay import ADMIN, DOEL, ODOO_ACCOUNTS, NepClient, _run, mini_vgg


class _Client:
    """Programmeerbare read-only Odoo-client: (model, methode, kwargs) → antwoord. Weigert élke schrijfmethode."""

    def __init__(self, antwoorden: dict[tuple[str, str], Any], company_velden: dict[str, Any] | None = None) -> None:
        self.antwoorden = antwoorden
        self.company_velden = company_velden if company_velden is not None else {}
        self.calls: list[tuple[str, str]] = []
        self.read_only = True
        self.company_id = 6

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        self.calls.append((model, "read"))
        rijen = self.antwoorden.get((model, "read"), {})
        return [dict(rijen[i]) for i in ids if i in rijen]

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict[str, Any] | None:
        rijen = self.read(model, [odoo_id], fields)
        return rijen[0] if rijen else None

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict[str, dict]:
        self.calls.append((model, "fields_get"))
        return dict(self.company_velden) if model == "res.company" else {}

    def create(self, *a: Any, **kw: Any) -> None:  # pragma: no cover — mag nooit
        raise AssertionError("write op een lees-only client")

    write = create


ACCOUNTS = {
    2175: {"id": 2175, "code": "103001", "name": "Bank"},
    398: {"id": 398, "code": "103002", "name": "Bank Suspense Account"},
    2177: {"id": 2177, "code": "103004", "name": "Outstanding Payments"},
    2178: {"id": 2178, "code": "103005", "name": "Outstanding Payments (alt)"},
}
JOURNAL_MET_REGELS = {53: {"id": 53, "code": "BNK1", "outbound_payment_method_line_ids": [7, 8]}}


class TestTabelGuard:
    def test_tabel_kent_precies_1012_en_1001_met_de_afgesproken_fasen(self) -> None:
        assert set(rm.EXPLICIETE_MAPPING) == {"1012", "1001"}
        m12, m01 = rm.EXPLICIETE_MAPPING["1012"], rm.EXPLICIETE_MAPPING["1001"]
        assert (m12.doel, m12.groep, m12.schrijf_fase) == (rm.DOEL_OUTSTANDING_PAYMENTS, "bank", rm.FASE_A)
        assert (m01.doel, m01.groep, m01.schrijf_fase) == (rm.DOEL_BANK_STATEMENT_LINES, "bank", rm.FASE_B)
        for m in rm.EXPLICIETE_MAPPING.values():
            assert m.rlz_code.isdigit() and len(m.rlz_code) == 4 and m.toelichting and m.rlz_code == m.rlz_code.strip()
        # geen nieuwe RJ-220-rol: 1012 is een afletter-rekening, geen rol
        from app.odoo.rj220 import ROLLEN

        assert not any("1012" in r or "onderweg" in r for r in ROLLEN)

    def test_groep_en_modelpunten(self) -> None:
        assert rm.expliciete_codes_voor_groep("bank") == frozenset({"1012", "1001"})
        assert rm.expliciete_codes_voor_groep("crediteuren") == frozenset()
        punten = rm.modelpunten_voor_groep("bank")
        assert len(punten) == 1 and punten[0].startswith("RLZ 1001: modelpunt SCHRIJF b")
        assert "statement line" in punten[0] and "85.376,31" in punten[0]
        assert rm.modelpunten_voor_groep("debiteuren") == []


class TestOutstandingPayments:
    def test_gevonden_op_de_betaalmethoderegels_van_het_dagboek(self) -> None:
        c = _Client(
            {
                ("account.journal", "read"): JOURNAL_MET_REGELS,
                ("account.payment.method.line", "read"): {
                    7: {"id": 7, "name": "Manual", "payment_account_id": [2177, "103004 Outstanding Payments"]},
                    8: {"id": 8, "name": "SEPA", "payment_account_id": [2177, "103004 Outstanding Payments"]},
                },
                ("account.account", "read"): ACCOUNTS,
            }
        )
        u = rm.los_outstanding_payments_op(c, journal_bank_id=53, company_id=6)
        assert u.gevonden and (u.account_id, u.code, u.naam, u.route) == (
            2177,
            "103004",
            "Outstanding Payments",
            rm.ROUTE_JOURNAL,
        )
        assert "BNK1" in u.melding and "2 uitgaande betaalmethode-regel" in u.melding
        assert ("res.company", "fields_get") not in c.calls  # dagboek wint, company niet geraadpleegd

    def test_meerduidig_wordt_niet_gekozen(self) -> None:
        c = _Client(
            {
                ("account.journal", "read"): JOURNAL_MET_REGELS,
                ("account.payment.method.line", "read"): {
                    7: {"id": 7, "payment_account_id": [2177, "x"]},
                    8: {"id": 8, "payment_account_id": [2178, "y"]},
                },
                ("account.account", "read"): ACCOUNTS,
            }
        )
        u = rm.los_outstanding_payments_op(c, journal_bank_id=53, company_id=6)
        assert not u.gevonden and "meerduidig" in u.melding and len(u.kandidaten) == 2 and "mens beslist" in u.melding

    def test_company_default_als_het_veld_bestaat(self) -> None:
        c = _Client(
            {
                ("account.journal", "read"): {53: {"id": 53, "code": "BNK1", "outbound_payment_method_line_ids": [7]}},
                ("account.payment.method.line", "read"): {7: {"id": 7, "payment_account_id": False}},
                ("res.company", "read"): {6: {"id": 6, rm.COMPANY_VELD_OUTSTANDING_PAYMENTS: [2177, "x"]}},
                ("account.account", "read"): ACCOUNTS,
            },
            company_velden={rm.COMPANY_VELD_OUTSTANDING_PAYMENTS: {"type": "many2one"}},
        )
        u = rm.los_outstanding_payments_op(c, journal_bank_id=53, company_id=6)
        assert u.gevonden and u.account_id == 2177 and u.route == rm.ROUTE_COMPANY and "company-default" in u.melding

    def test_niets_ingesteld_is_klikpunt_met_kandidaten_nooit_de_bankrekening(self) -> None:
        c = _Client(
            {
                ("account.journal", "read"): {53: {"id": 53, "code": "BNK1", "outbound_payment_method_line_ids": []}},
                ("account.account", "read"): ACCOUNTS,
            },
            company_velden={},  # veld bestaat niet in deze Odoo-versie
        )
        u = rm.los_outstanding_payments_op(c, journal_bank_id=53, company_id=6, rekeningen=list(ACCOUNTS.values()))
        assert not u.gevonden and u.melding.startswith("KLIKPUNT PETER")
        assert "bestaat niet in deze Odoo-versie" in u.melding
        assert u.kandidaten == ("103004 Outstanding Payments (id 2177)", "103005 Outstanding Payments (alt) (id 2178)")
        assert "103001" not in u.melding  # de bankrekening zelf is nooit een kandidaat

    def test_zonder_bankdagboek_geen_call(self) -> None:
        c = _Client({})
        u = rm.los_outstanding_payments_op(c, journal_bank_id=None, company_id=6)
        assert not u.gevonden and "geen bankdagboek" in u.melding and c.calls == []


L_1012, L_1001, L_4000 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
LEDGERS_IDX = {
    L_1012: ("1012", "Betalingen onderweg", 3),
    L_1001: ("1001", "ING NL95INGB0114119295", 3),
    L_4000: ("4000", "Brutosalarissen", 2),
}
GEVONDEN = rm.OutstandingUitkomst(2177, "103004", "Outstanding Payments", rm.ROUTE_JOURNAL, "gevonden op dagboek BNK1")
NIET_GEVONDEN = rm.OutstandingUitkomst(None, None, None, None, "KLIKPUNT PETER: geen 'Outstanding Payments'-rekening")


def _vert(lid: str, odoo: int | None = None) -> GrootboekVertaling:
    code, naam, _t = LEDGERS_IDX[lid]
    return GrootboekVertaling(lid, code, naam, odoo, str(odoo) if odoo else None, "zelfde_code" if odoo else None)


class TestPasToe:
    def test_1012_gemapt_1001_alleen_gemarkeerd(self) -> None:
        gb = {L_1012: _vert(L_1012), L_1001: _vert(L_1001, 2175), L_4000: _vert(L_4000)}
        nieuw, rapport = rm.pas_expliciete_mapping_toe(gb, LEDGERS_IDX, outstanding=GEVONDEN)
        assert nieuw[L_1012].odoo_account_id == 2177 and nieuw[L_1012].bron == rm.BRON_EXPLICIET
        assert nieuw[L_1001] == gb[L_1001] and nieuw[L_4000] == gb[L_4000]  # ongewijzigd
        assert gb[L_1012].odoo_account_id is None  # invoer niet gemuteerd
        per_code = {r["rlz_code"]: r for r in rapport}
        assert per_code["1012"]["odoo_account_id"] == 2177 and per_code["1012"]["stand"].startswith("gemapt → 103004")
        assert (
            per_code["1001"]["stand"].startswith("gemarkeerd (SCHRIJF b)")
            and per_code["1001"]["odoo_account_id"] is None
        )

    def test_zonder_uitkomst_of_niet_gevonden_blijft_1012_ongemapt_met_reden(self) -> None:
        gb = {L_1012: _vert(L_1012)}
        nieuw, rapport = rm.pas_expliciete_mapping_toe(gb, LEDGERS_IDX, outstanding=None)
        assert nieuw[L_1012].odoo_account_id is None and rapport[0]["stand"].startswith("niet opgezocht")
        nieuw, rapport = rm.pas_expliciete_mapping_toe(gb, LEDGERS_IDX, outstanding=NIET_GEVONDEN)
        assert nieuw[L_1012].odoo_account_id is None and rapport[0]["stand"].startswith("KLIKPUNT PETER")

    def test_rlz_rekening_afwezig_in_administratie(self) -> None:
        _n, rapport = rm.pas_expliciete_mapping_toe({}, {L_4000: LEDGERS_IDX[L_4000]}, outstanding=GEVONDEN)
        assert all(r["stand"] == "RLZ-rekening niet in deze administratie" and not r["in_rlz"] for r in rapport)


class TestVoorstelTegenhanger:
    ODOO = [
        {"id": 1, "code": "400000", "name": "Salaries", "account_type": "expense"},
        {"id": 2, "code": "410600", "name": "Schoonmaakkosten", "account_type": "expense"},
    ]

    def test_tabelregels(self) -> None:
        assert rm.voorstel_tegenhanger("1001", "ING", 3, self.ODOO, outstanding=GEVONDEN).startswith(
            "modelpunt SCHRIJF b"
        )
        assert rm.voorstel_tegenhanger(
            "1012", "Betalingen onderweg", 3, self.ODOO, outstanding=NIET_GEVONDEN
        ).startswith("KLIKPUNT PETER")
        assert "niet opgezocht" in rm.voorstel_tegenhanger("1012", "x", 3, self.ODOO, outstanding=None)

    def test_naamkandidaat_code_vrij_en_code_bezet(self) -> None:
        assert rm.voorstel_tegenhanger("4106", "Schoonmaakkosten", 2, self.ODOO, outstanding=None).startswith(
            "kandidaat 410600 Schoonmaakkosten (id 2)"
        )
        bezet = rm.voorstel_tegenhanger("4000", "Brutosalarissen", 2, self.ODOO, outstanding=None)
        assert bezet.startswith(
            "aanmaken als 400000 (expense) NIET mogelijk — code bezet door Salaries (id 1, expense)"
        )
        vrij = rm.voorstel_tegenhanger("4200", "Huur inventaris", 2, self.ODOO, outstanding=None)
        assert vrij == "aanmaken als 420000 'Huur inventaris' (expense) — code vrij; mens bevestigt"
        assert "asset_fixed" in rm.voorstel_tegenhanger("0113", "Computersoftware", 3, self.ODOO, outstanding=None)
        assert "mens kiest" in rm.voorstel_tegenhanger("0500", "Aandelenkapitaal", 4, self.ODOO, outstanding=None)


class TestGroepstoets:
    def test_1012_telt_in_de_bankgroep_en_het_1001_modelpunt_is_zichtbaar(self) -> None:
        ctx = Context(
            administratie_id=ADMIN,
            doel=Doel(),
            grootboek={},
            ledgers=dict(LEDGERS_IDX),
            rollen=RolRekeningen(),
            panden={},
        )
        groepen = replay.afletter_groepen(ctx, lambda lid: f"ongemapt:{LEDGERS_IDX[lid][0]}" if lid else "?")
        assert {"ongemapt:1012", "ongemapt:1001"} <= groepen["bank"]["sleutels"]
        assert "ongemapt:4000" not in groepen["bank"]["sleutels"]
        assert groepen["bank"]["modelpunten"] == rm.modelpunten_voor_groep("bank")
        assert groepen["crediteuren"]["modelpunten"] == []


class TestReplayLeestOdooZelf:
    def test_met_doelkoppeling_leest_de_replay_de_rekeningen_via_de_lezer(self) -> None:
        collecties, regels, statements = mini_vgg()
        gezien: list[tuple[uuid.UUID, int | None, int | None]] = []

        def lezer(aid: uuid.UUID, journal_bank_id: int | None, company_id: int | None) -> rm.DoelGegevens:
            gezien.append((aid, journal_bank_id, company_id))
            return rm.DoelGegevens(odoo_accounts=list(ODOO_ACCOUNTS), outstanding=GEVONDEN)

        rapport = _run(NepClient(collecties, regels, statements), odoo_accounts=None, odoo_lezer=lezer)
        assert gezien == [(ADMIN, DOEL.journal_bank_id, 6)]
        assert rapport.doel_afwezig is False and rapport.groen is True
        assert any("gelezen uit company 6 via de doelkoppeling: 7" in x for x in rapport.let_op)
        assert not any("geen Odoo-rekeningen meegegeven" in x for x in rapport.let_op)
        assert any("RLZ 1012 Betalingen onderweg → outstanding payments: gevonden" in x for x in rapport.let_op)
        assert {r["rlz_code"] for r in rapport.expliciete_mapping} == {"1012", "1001"}
        assert all(r["stand"] == "RLZ-rekening niet in deze administratie" for r in rapport.expliciete_mapping)
        md = als_markdown(rapport)
        assert "#### Expliciete rekeningmapping (blok 8" in md and "(voorstel = mens beslist, blok 8 1b)" in md
        bank = next(g for g in rapport.afletter_groepen if g["groep"] == "bank")
        assert bank["modelpunten"] and "- Modelpunt bankgroep: RLZ 1001: modelpunt SCHRIJF b" in md

    def test_lezer_melding_is_let_op_en_valt_terug_op_ongemapt(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(
            NepClient(collecties, regels, statements),
            odoo_accounts=None,
            odoo_lezer=lambda *_a: rm.DoelGegevens(melding="Odoo-rekeningen niet gelezen: GeenMigratieDoel: x"),
        )
        assert any(x.startswith("Odoo-rekeningen niet gelezen") for x in rapport.let_op)
        assert any("--odoo-rekeningen" in x for x in rapport.let_op)
        assert rapport.doel_afwezig is True
        assert all("voorstel" in o and o["voorstel"] for o in rapport.ongemapt)

    def test_zonder_lezer_ongewijzigd_gedrag(self) -> None:
        collecties, regels, statements = mini_vgg()
        rapport = _run(NepClient(collecties, regels, statements), odoo_accounts=None)
        assert any("--odoo-rekeningen" in x for x in rapport.let_op) and rapport.doel_afwezig is True

    def test_lees_doelgegevens_zonder_migratiedoel_is_melding_geen_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.migratie import odoo_doel

        def geen(_aid: uuid.UUID, *, read_only: bool = False) -> None:
            raise odoo_doel.GeenMigratieDoel("Administratie X heeft geen Odoo-koppeling")

        monkeypatch.setattr(odoo_doel, "doelclient_voor", geen)
        g = rm.lees_doelgegevens(ADMIN, 53, 6)
        assert g.melding and "geen Odoo-koppeling" in g.melding and g.odoo_accounts == [] and g.outstanding is None
        assert rm.lees_doelgegevens(ADMIN, 53, None).melding.startswith("geen company")


class TestCliDoorgifte:
    def test_run_vgg_replay_geeft_de_lezer_door(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import argparse

        from app.migratie import cli_replay

        gezien: dict[str, Any] = {}
        origineel = replay.dry_run

        def nep_dry_run(aid: uuid.UUID, **kw: Any) -> Any:
            gezien.update(kw)
            kw.pop("odoo_lezer", None)
            return origineel(aid, **{**kw, "odoo_accounts": list(ODOO_ACCOUNTS), "doel": DOEL})

        monkeypatch.setattr(replay, "dry_run", nep_dry_run)
        args = argparse.Namespace(
            commando="vgg-replay",
            administratie="Vastgoedgroep",
            dry_run=True,
            json_uit=None,
            tot=None,
            odoo_rekeningen=None,
            schrijf_concept=False,
        )
        lezer = lambda *_a: rm.DoelGegevens(melding="x")  # noqa: E731
        rc = cli_replay.run_vgg_replay(
            args,
            zoek=lambda _t: (ADMIN, "Vastgoedgroep Nederland B.V.", "rlz-x"),
            client_factory=lambda _r: NepClient(*mini_vgg()),
            odoo_lezer=lezer,
        )
        assert rc == 0 and gezien["odoo_lezer"] is lezer
        # zonder expliciete lezer én mét geïnjecteerde client (tests) wordt de productie-lezer NIET ingehangen
        cli_replay.run_vgg_replay(
            args,
            zoek=lambda _t: (ADMIN, "Vastgoedgroep Nederland B.V.", "rlz-x"),
            client_factory=lambda _r: NepClient(*mini_vgg()),
        )
        assert gezien["odoo_lezer"] is None
