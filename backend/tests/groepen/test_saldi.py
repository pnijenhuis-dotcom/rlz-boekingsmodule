# ruff: noqa: F811 — pytest-fixtures als parameters
"""Groepssaldi debiteuren/crediteuren per groep (Peter 16-09): rekening-detectie uit de bron (RGS/naam, Odoo
account_type — nooit 1300/1600 hardgecodeerd), saldo Debit − Credit mét NL-dag-in-UTC-datumgrens, IC-eliminatie
cent-exact (bruto = zonder-IC + IC), gemengd RLZ/Odoo, webfilter = ongeldig per administratie, cache + scope
(Boekhouding-rol ziet "N van M"), onbekende groep leesbaar, CLI-rapport zonder PII."""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import groepen
from app.groepen import saldi
from app.main import app
from app.rlz.client import RlzWebfilterError
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401
from tests.doorbelasting.conftest import maak_administratie

client = TestClient(app)
D = Decimal


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _ledger(id_: str, nummer: str, naam: str, soort: int, *, rgs: str | None = None, totaal: bool = False) -> dict:
    rij = {"id": id_, "AccountNumber": nummer, "Description": naam, "AccountType": soort, "IsTotalAccount": totaal}
    if rgs:
        rij["SystemAccountList"] = [{"Code": f"RGS.{rgs}", "RgsCode": rgs}]
    return rij


class TestRekeningen:
    def test_rgs_wint_en_alleen_de_juiste_balanszijde(self) -> None:
        ledgers = [
            _ledger("d1", "1300", "Debiteuren", 3, rgs="BVorDebHad"),
            _ledger("d2", "1305", "Debiteuren buitenland", 3, rgs="BVorDebHag"),
            _ledger("dt", "13", "Debiteuren totaal", 3, rgs="BVorDeb", totaal=True),
            _ledger("c1", "1600", "Crediteuren", 4, rgs="BSchCreHac"),
            _ledger("x1", "1403", "Vooruit betaalde inkoopfacturen", 3, rgs="BVorVbkVbk"),
            _ledger("x2", "8000", "Omzet debiteuren", 1),
        ]
        assert [r.code for r in saldi.vind_rekeningen_rlz(ledgers, soort="debiteuren")] == ["1300", "1305"]
        assert [r.code for r in saldi.vind_rekeningen_rlz(ledgers, soort="crediteuren")] == ["1600"]

    def test_zonder_rgs_op_naam_en_geen_treffer_is_leeg(self) -> None:
        ledgers = [
            _ledger("d1", "1300", "Handelsdebiteuren", 3),
            _ledger("c1", "1600", "Crediteuren", 4),
            _ledger("c2", "1650", "Crediteuren G-rekening", 4),
            _ledger("k1", "1610", "Nog te ontvangen facturen", 4),
        ]
        assert [r.code for r in saldi.vind_rekeningen_rlz(ledgers, soort="debiteuren")] == ["1300"]
        assert [r.code for r in saldi.vind_rekeningen_rlz(ledgers, soort="crediteuren")] == ["1600", "1650"]
        assert saldi.vind_rekeningen_rlz([_ledger("k1", "1610", "Nog te ontvangen", 4)], soort="debiteuren") == []

    def test_nl_dag_einde_utc_is_de_volgende_nl_middernacht(self) -> None:
        assert saldi.nl_dag_einde_utc(date(2026, 9, 16)) == "2026-09-16T22:00:00Z"  # CEST
        assert saldi.nl_dag_einde_utc(date(2026, 1, 15)) == "2026-01-15T23:00:00Z"  # CET


class NepClient:
    """RLZ-client-stub: Ledgers mét RGS, JournalEntryLines per rekening, open Sales-/PurchaseInvoices per entity."""

    def __init__(self, *, regels: dict[str, list[tuple[str, str]]], verkoop_open: list[dict], inkoop_open: list[dict]):
        self.regels = regels
        self.verkoop_open = verkoop_open
        self.inkoop_open = inkoop_open
        self.calls: list[tuple[str, dict]] = []
        self.gesloten = False

    def get(self, pad: str, params: dict | None = None) -> dict:
        params = params or {}
        self.calls.append((pad, params))
        if pad == "Ledgers":
            assert "SystemAccountList" in params["$expand"]
            # Productie 16→21-09: `AccountType eq 3` in $filter = 400 (enum vs Edm.Int32) — RLZ's gedrag nagespeeld.
            assert "AccountType" not in params["$filter"], params["$filter"]
            assert params["$filter"] == "IsTotalAccount eq false" and "$skip" in params
            if int(params["$skip"]) > 0:
                return {"value": []}
            return {
                "value": [
                    _ledger("d1", "1300", "Debiteuren", 3, rgs="BVorDebHad"),
                    _ledger("x0", "0100", "Gebouwen", 3, rgs="BMvaBegBeg"),  # activa zonder deb-RGS: telt niet
                    _ledger("o1", "8000", "Omzet", 1),  # geen balans: client-side weg
                    _ledger("c1", "1600", "Crediteuren", 4, rgs="BSchCreHac"),
                ]
            }
        if pad == "JournalEntryLines":
            rek = params["$filter"].split("Account/id eq ")[1].split(" ")[0]
            return {"value": [{"DebitAmount": d, "CreditAmount": c} for d, c in self.regels.get(rek, [])]}
        if pad in ("SalesInvoices", "PurchaseInvoices"):
            assert "Status eq 2" in params["$filter"]
            bron = self.verkoop_open if pad == "SalesInvoices" else self.inkoop_open
            ids = re.findall(r"Entity/id eq ([0-9a-f-]{36})", params["$filter"])
            return {"value": [r for r in bron if str(r["Entity"]) in ids]}
        raise AssertionError(pad)

    def close(self) -> None:
        self.gesloten = True


IC_ENTITY = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
IC_ENTITY_CRED = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _nep_client() -> NepClient:
    return NepClient(
        regels={
            "d1": [("1000.00", "0"), ("250.50", "0"), ("0", "100.25")],  # debiteuren 1.150,25
            "c1": [("0", "3000.00"), ("500.00", "0"), ("0", "0.30")],  # crediteuren 2.500,30 (credit − debit)
        },
        verkoop_open=[
            {"Entity": IC_ENTITY, "BaseRemainingAmount": "400.10"},
            {"Entity": IC_ENTITY, "BaseRemainingAmount": "50.00", "IsCreditInvoice": True},
            {"Entity": uuid.uuid4(), "BaseRemainingAmount": "999.00"},  # geen IC — telt niet
        ],
        inkoop_open=[{"Entity": IC_ENTITY_CRED, "BaseRemainingAmount": "1200.00"}],
    )


def _relatie(
    admin_engine: Engine, a: uuid.UUID, b: uuid.UUID, entity: uuid.UUID, richting: str, status: str = "afgeleid"
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.intercompany_relatie (id, administratie_a_id, entity_in_a, "
                "administratie_b_id, richting, basis, status) VALUES (:id, :a, :e, :b, :r, 'kvk', :s)"
            ),
            {"id": uuid.uuid4(), "a": a, "e": entity, "b": b, "r": richting, "s": status},
        )


class TestMeting:
    def test_saldo_ic_en_bruto_is_zonder_ic_plus_ic(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        b = maak_administratie(admin_engine, "Kempen B.V.")
        buiten = maak_administratie(admin_engine, "Buiten de groep B.V.")
        _relatie(admin_engine, administratie_id, b, IC_ENTITY, "debiteur")
        _relatie(admin_engine, administratie_id, b, IC_ENTITY_CRED, "crediteur")
        # Tegenpartij buiten de groep en een uitgesloten relatie tellen NIET als IC.
        _relatie(admin_engine, administratie_id, buiten, uuid.uuid4(), "debiteur")
        _relatie(admin_engine, administratie_id, b, uuid.uuid4(), "debiteur", status="uitgesloten")
        nep = _nep_client()
        rij = saldi.meet_administratie(
            administratie_id,
            "Kempen Facilities",
            groepsleden=[administratie_id, b],
            tot_en_met=None,
            bron=saldi.RlzBron(nep),
        )
        assert rij.status == "ok" and rij.detail is None
        assert (rij.debiteuren, rij.crediteuren) == (D("1150.25"), D("2500.30"))
        assert (rij.ic_debiteuren, rij.ic_crediteuren) == (D("350.10"), D("1200.00"))
        assert rij.debiteuren_zonder_ic + rij.ic_debiteuren == rij.debiteuren
        assert rij.crediteuren_zonder_ic + rij.ic_crediteuren == rij.crediteuren
        assert (rij.debiteuren_rekening, rij.crediteuren_rekening) == ("1300 Debiteuren", "1600 Crediteuren")
        # Geen datumfilter zonder peildatum; mét peildatum de NL-dag-grens als UTC-literal.
        assert all("BookDate" not in p.get("$filter", "") for pad, p in nep.calls if pad == "JournalEntryLines")
        nep2 = _nep_client()
        saldi.meet_administratie(
            administratie_id, "x", groepsleden=[b], tot_en_met=date(2026, 9, 16), bron=saldi.RlzBron(nep2)
        )
        assert any(
            "JournalEntry/BookDate lt 2026-09-16T22:00:00Z" in p["$filter"]
            for pad, p in nep2.calls
            if pad == "JournalEntryLines"
        )
        # Meegegeven bron wordt niet gesloten (de aanroeper beheert 'm); eigen bron wél.
        assert nep.gesloten is False

    def test_geen_rekening_webfilter_overgeslagen_en_fout_zijn_zichtbaar(self, administratie_id: uuid.UUID) -> None:
        class ZonderCrediteuren(saldi.RlzBron):
            def rekeningen(self, soort: str) -> list[saldi.Rekening]:
                return [] if soort == "crediteuren" else [saldi.Rekening("d1", "1300", "Debiteuren")]

        rij = saldi.meet_administratie(
            administratie_id, "A", groepsleden=[], tot_en_met=None, bron=ZonderCrediteuren(_nep_client())
        )
        assert rij.status == "geen_rekening" and rij.detail == "geen crediteurenrekening gevonden"
        assert rij.debiteuren_rekening == "1300 Debiteuren" and rij.debiteuren is None

        class Webfilter(saldi.RlzBron):
            def saldo(self, rekeningen, *, tot_en_met):  # noqa: ANN001, ANN202
                raise RlzWebfilterError(403, "GET", "JournalEntryLines", "<html>webfilter</html>")

        rij = saldi.meet_administratie(
            administratie_id, "A", groepsleden=[], tot_en_met=None, bron=Webfilter(_nep_client())
        )
        assert rij.status == "ongeldig" and "meting ongeldig" in (rij.detail or "")

        class Kapot(saldi.RlzBron):
            def rekeningen(self, soort):  # noqa: ANN001, ANN202
                raise RuntimeError("HTTP 500 van RLZ")

        rij = saldi.meet_administratie(
            administratie_id, "A", groepsleden=[], tot_en_met=None, bron=Kapot(_nep_client())
        )
        assert rij.status == "fout" and rij.detail == "HTTP 500 van RLZ"

    def test_open_bron_zonder_credential_is_overgeslagen(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def geen(_aid):  # noqa: ANN001, ANN202
            raise saldi.BronOvergeslagen(saldi.GEEN_CREDENTIAL)

        monkeypatch.setattr(saldi, "open_bron", geen)
        rij = saldi.meet_administratie(administratie_id, "A", groepsleden=[], tot_en_met=None)
        assert rij.status == "overgeslagen" and rij.detail == saldi.GEEN_CREDENTIAL

    def test_totalen_tellen_alleen_geldige_rijen_cent_exact(self) -> None:
        ok = saldi.AdministratieSaldo(
            uuid.uuid4(),
            "A",
            "ok",
            debiteuren=D("10.10"),
            crediteuren=D("5.05"),
            ic_debiteuren=D("0.10"),
            ic_crediteuren=D("0.05"),
        )
        ok2 = saldi.AdministratieSaldo(
            uuid.uuid4(),
            "B",
            "ok",
            debiteuren=D("0.01"),
            crediteuren=D("0.02"),
            ic_debiteuren=D("0.00"),
            ic_crediteuren=D("0.02"),
        )
        rood = saldi.AdministratieSaldo(uuid.uuid4(), "C", "ongeldig", "webfilter", debiteuren=D("999"))
        t = saldi.totalen([ok, ok2, rood])
        assert (t.debiteuren, t.ic_debiteuren, t.debiteuren_zonder_ic) == (D("10.11"), D("0.10"), D("10.01"))
        assert (t.crediteuren, t.ic_crediteuren, t.crediteuren_zonder_ic) == (D("5.07"), D("0.07"), D("5.00"))
        assert t.debiteuren_zonder_ic + t.ic_debiteuren == t.debiteuren


class NepOdooClient:
    company_id = 6

    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []

    def search_read(self, model: str, domain: list, fields: list, **kw) -> list[dict]:  # noqa: ANN003
        self.calls.append((model, domain))
        if model == "account.account":
            velden = [d[0] for d in domain]
            # Odoo 19: `deprecated` bestaat niet (500 "Invalid field") — productie 16→21-09.
            assert "deprecated" not in velden, domain
            assert ["company_ids", "in", [6]] in domain and ["active", "=", True] in domain, domain
            soort = next(d[2] for d in domain if d[0] == "account_type")
            return (
                [{"id": 41, "code": "130000", "name": "Debiteuren"}]
                if soort == "asset_receivable"
                else [{"id": 61, "code": "160000", "name": "Crediteuren"}]
            )
        if model == "account.move.line":
            account = next(d[2] for d in domain if d[0] == "account_id")
            return [{"balance": "700.00"}, {"balance": "-100.00"}] if account == 41 else [{"balance": "-250.00"}]
        raise AssertionError(model)

    def close(self) -> None:
        return None


class TestGemengd:
    def test_odoo_en_rlz_in_een_groep(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        odoo_aid = maak_administratie(admin_engine, "Odoo Werkmaatschappij B.V.")
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_groep_bulk(
            actor_id=beheerder_id, groep_id=kg.id, toevoegen=[administratie_id, odoo_aid], verwijderen=[]
        )

        class OdooZonderIc(saldi.OdooBron):
            def ic_open(self, entity_ids, *, kant, tot_en_met):  # noqa: ANN001, ANN202
                return saldi.NUL

        def nep_open(aid: uuid.UUID) -> saldi.Bron:
            return OdooZonderIc(aid, NepOdooClient()) if aid == odoo_aid else saldi.RlzBron(_nep_client())

        monkeypatch.setattr(saldi, "open_bron", nep_open)
        uit = saldi.meet_groep_live(saldi.zoek_groep("kempen groep"))
        assert uit.aantal_leden == 2 and [r.status for r in uit.rijen] == ["ok", "ok"]
        odoo = next(r for r in uit.rijen if r.administratie_id == odoo_aid)
        assert (odoo.debiteuren, odoo.crediteuren, odoo.debiteuren_rekening) == (
            D("600.00"),
            D("250.00"),
            "130000 Debiteuren",
        )
        assert uit.totalen.debiteuren == D("1150.25") + D("600.00")
        tekst = saldi.rapport_tekst(uit)
        assert "Kempen groep (KEMPENGROEP)" in tekst and "2 van 2 administraties" in tekst
        assert "€ 1.750,25" in tekst and "TOTAAL (2 geldig)" in tekst
        # Zoeken op code en id werkt ook; onbekend = leesbare melding.
        assert saldi.zoek_groep("KEMPENGROEP").id == kg.id and saldi.zoek_groep(str(kg.id)).id == kg.id
        with pytest.raises(saldi.GroepOnbekend, match="maak hem aan op Instellingen › Administraties"):
            saldi.zoek_groep("Kempen groepje")


class TestStandEnScope:
    def test_nachtstand_cache_en_scope_n_van_m(
        self,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        b = maak_administratie(admin_engine, "Kempen B.V.")
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_groep_bulk(actor_id=beheerder_id, groep_id=kg.id, toevoegen=[administratie_id, b], verwijderen=[])
        monkeypatch.setattr(saldi, "open_bron", lambda aid: saldi.RlzBron(_nep_client()))
        rapport = saldi.meet_en_schrijf_alle(datum=date(2026, 9, 16))
        assert (rapport.groepen, rapport.administraties, rapport.ok, rapport.niet_ok) == (1, 2, 2, [])
        # Tweede run dezelfde dag = upsert (geen dubbele rij).
        saldi.meet_en_schrijf_alle(datum=date(2026, 9, 16))
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM boekhouding.groep_saldo_stand WHERE datum = '2026-09-16'")
            ).scalar_one()
        assert n == 2

        # Beheerder ziet alles; de Boekhouding-rol (scope alleen op administratie_id) ziet 1 van 2 — RLS op de cache.
        alles = saldi.lees_stand_voor_groep(kg.id, actor_id=beheerder_id)
        assert (alles.bron, alles.datum, alles.aantal_leden, alles.aantal_in_scope, len(alles.rijen)) == (
            "stand",
            date(2026, 9, 16),
            2,
            2,
            2,
        )
        deel = saldi.lees_stand_voor_groep(kg.id, actor_id=gescoopte_gebruiker)
        assert (deel.aantal_leden, deel.aantal_in_scope, [r.administratie_id for r in deel.rijen]) == (
            2,
            1,
            [administratie_id],
        )
        assert deel.totalen.debiteuren == D("1150.25") and deel.zonder_stand == 0

        # Route: kantoorrol, 404 leesbaar bij een onbekende groep.
        r = client.get(f"/groepen/{kg.id}/saldi", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert (d["aantal_leden"], d["aantal_in_scope"], d["bron"], d["datum"]) == (2, 1, "stand", "2026-09-16")
        assert d["totalen"] == {
            "debiteuren": "1150.25",
            "debiteuren_ic": "0.00",
            "debiteuren_zonder_ic": "1150.25",
            "crediteuren": "2500.30",
            "crediteuren_ic": "0.00",
            "crediteuren_zonder_ic": "2500.30",
            "aantal_geldig": 1,
        }
        assert d["rijen"][0]["debiteuren_rekening"] == "1300 Debiteuren"
        r404 = client.get(f"/groepen/{uuid.uuid4()}/saldi", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r404.status_code == 404 and "maak hem aan op Instellingen" in r404.json()["detail"]

    def test_zonder_stand_is_zichtbaar(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_administratie_groep(actor_id=beheerder_id, administratie_id=administratie_id, groep_id=kg.id)
        stand = saldi.lees_stand_voor_groep(kg.id, actor_id=beheerder_id)
        assert (stand.aantal_leden, stand.aantal_in_scope, stand.zonder_stand, stand.rijen) == (1, 1, 1, [])


class TestRlzLedgersFilter:
    """BUG 21-09: RLZ weigert `AccountType eq 3` (enum vs int, 400) — de balanszijde wordt client-side getoetst en de
    Ledgers-collectie wordt gepagineerd gelezen ($top/$skip), niet meer met een aangenomen `$top=500`."""

    def test_filter_zonder_accounttype_en_paginering_over_meer_dan_een_pagina(self) -> None:
        class GepagineerdeClient:
            def __init__(self) -> None:
                self.calls: list[dict] = []
                # 2,5 pagina's rekeningen; de debiteurenrekening staat op de LAATSTE pagina.
                self.rijen = [_ledger(f"k{i}", f"{4000 + i}", f"Kosten {i}", 2) for i in range(saldi.PAGINA * 2 + 3)]
                self.rijen.append(_ledger("d1", "1300", "Debiteuren", 3, rgs="BVorDebHad"))
                self.rijen.append(_ledger("c1", "1600", "Crediteuren", 4, rgs="BSchCreHac"))

            def get(self, pad: str, params: dict | None = None) -> dict:
                assert pad == "Ledgers"
                params = params or {}
                self.calls.append(params)
                assert params["$filter"] == "IsTotalAccount eq false", params["$filter"]
                assert "AccountType" not in params["$filter"]
                top, skip = int(params["$top"]), int(params["$skip"])
                return {"value": self.rijen[skip : skip + top]}

        client = GepagineerdeClient()
        bron = saldi.RlzBron(client)
        assert [r.code for r in bron.rekeningen("debiteuren")] == ["1300"]
        assert [r.code for r in bron.rekeningen("crediteuren")] == ["1600"]
        assert len(client.calls) == 3, "drie pagina's (200/200/5), daarna gecachet"
        assert [int(c["$skip"]) for c in client.calls] == [0, saldi.PAGINA, 2 * saldi.PAGINA]

    def test_rlz_400_op_ledgers_blijft_zichtbaar_als_fout(self, administratie_id: uuid.UUID) -> None:
        class Weigert:
            def get(self, pad: str, params: dict | None = None) -> dict:
                raise RuntimeError(
                    "400 A binary operator with incompatible types was detected. Found operand types "
                    "'Reeleezee.DTO.AccountTypeEnum' and 'Edm.Int32'"
                )

            def close(self) -> None:
                return None

        rij = saldi.meet_administratie(
            administratie_id, "X", groepsleden=[], tot_en_met=None, bron=saldi.RlzBron(Weigert())
        )
        assert rij.status == "fout" and "AccountTypeEnum" in (rij.detail or "")


class TestOdooDomein:
    """Guard (opdracht 21-09 C): het Odoo-domein van `OdooBron.rekeningen` gebruikt geen velden buiten de velden die
    `app/odoo/sync.py::lees_grootboek` live bewezen gebruikt op `account.account` (Odoo 19: geen `deprecated`)."""

    @staticmethod
    def _velden_sync() -> set[str]:
        import re as _re
        from pathlib import Path

        bron = Path(saldi.__file__).resolve().parents[1] / "odoo" / "sync.py"
        tekst = bron.read_text(encoding="utf-8")
        start = tekst.index("def lees_grootboek(")
        eind = tekst.index("\ndef ", start + 1)
        blok = tekst[start:eind]
        velden = set(_re.findall(r'"([a-z_]+)"', blok))
        assert "active" in velden and "company_ids" in velden and "account_type" in velden, velden
        assert "deprecated" not in velden
        return velden

    def test_domein_en_leesvelden_binnen_de_sync_veldenlijst(self) -> None:
        class Opnemer:
            company_id = 6

            def __init__(self) -> None:
                self.aanroepen: list[tuple[list, list]] = []

            def search_read(self, model: str, domain: list, fields: list, **kw) -> list[dict]:  # noqa: ANN003
                assert model == "account.account"
                self.aanroepen.append((domain, fields))
                return []

        client = Opnemer()
        bron = saldi.OdooBron(uuid.uuid4(), client)
        assert bron.rekeningen("debiteuren") == [] and bron.rekeningen("crediteuren") == []
        toegestaan = self._velden_sync()
        for domain, fields in client.aanroepen:
            gebruikt = {d[0] for d in domain} | set(fields)
            assert gebruikt <= toegestaan, f"velden buiten odoo/sync.py: {sorted(gebruikt - toegestaan)}"
            assert ["active", "=", True] in domain and "deprecated" not in gebruikt


class TestStandSysteemEnDetector:
    """21-09: `groep-saldi --stand` (nachtelijke cache zonder lezer-scope) en de regressie-detector
    `groep_saldo_fout`."""

    def test_lees_stand_systeem_en_cli_stand(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from app import cli as app_cli

        b = maak_administratie(admin_engine, "Zonder Stand B.V.")
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_groep_bulk(actor_id=beheerder_id, groep_id=kg.id, toevoegen=[administratie_id, b], verwijderen=[])
        saldi.schrijf_stand(
            saldi.AdministratieSaldo(
                administratie_id,
                "A",
                "ok",
                None,
                debiteuren=D("10.00"),
                crediteuren=D("5.00"),
                ic_debiteuren=D("1.00"),
                ic_crediteuren=D("0.00"),
                debiteuren_rekening="1300 Debiteuren",
                crediteuren_rekening="1600 Crediteuren",
            ),
            datum=date(2026, 9, 21),
        )
        uit = saldi.lees_stand_systeem(saldi.zoek_groep("Kempen groep"))
        assert uit.bron == "stand" and uit.aantal_leden == 2 and uit.zonder_stand == 1
        assert [r.status for r in uit.rijen] == ["ok"] and uit.totalen.debiteuren == D("10.00")
        assert saldi.standen_met_fout() == []
        # CLI-vorm uit het meetrecept letterlijk via argparse (les 19-09): `groep-saldi --groep "Kempen groep" --stand`.
        assert app_cli.main(["groep-saldi", "--groep", "Kempen groep", "--stand"]) == 0
        tekst = capsys.readouterr().out
        assert "bron: stand" in tekst and "1 van 2 administraties" in tekst
        assert "1 administratie(s) zonder nachtelijke stand" in tekst
        assert app_cli.main(["groep-saldi", "--groep", "Kempen groepje", "--stand"]) == 2

    def test_fout_in_de_stand_is_een_regressie_let_op_met_audit_categorie(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from datetime import UTC, datetime

        from app.reconciliatie import automatiseringen, run

        b = maak_administratie(admin_engine, "Bonte Hoeve B.V.")
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_groep_bulk(actor_id=beheerder_id, groep_id=kg.id, toevoegen=[administratie_id, b], verwijderen=[])
        # Oude rode stand (16-09) + jongere groene stand: de LAATSTE rij telt → geen fout voor A.
        saldi.schrijf_stand(
            saldi.AdministratieSaldo(administratie_id, "A", "fout", "400 AccountTypeEnum"), datum=date(2026, 9, 16)
        )
        saldi.schrijf_stand(
            saldi.AdministratieSaldo(administratie_id, "A", "ok", None, debiteuren=D("1"), crediteuren=D("1")),
            datum=date(2026, 9, 21),
        )
        saldi.schrijf_stand(
            saldi.AdministratieSaldo(b, "B", "fout", "500 Invalid field account.account.deprecated"),
            datum=date(2026, 9, 21),
        )
        fouten = saldi.standen_met_fout()
        assert [f.naam for f in fouten] == ["Bonte Hoeve B.V."] and fouten[0].groep.id == kg.id
        nu = datetime(2026, 9, 21, 4, 30, tzinfo=UTC)
        kw = automatiseringen.groep_saldi_bevinding(nu=nu)
        assert kw is not None and kw["soort"] == "let_op" and kw["administratie_id"] is None
        assert "1 administratie(s) in 1 groep(en) (Kempen groep)" in kw["tekst"]
        assert "Bonte Hoeve B.V.: 500 Invalid field account.account.deprecated" in kw["tekst"]
        assert automatiseringen.REGRESSIE_TEKST in kw["tekst"]
        assert kw["detail"]["reden"] == automatiseringen.GROEP_SALDO_FOUT
        assert kw["detail"]["doel_pad"] == f"/?groep={kg.id}"
        assert kw["vingerafdruk"] == automatiseringen.groep_saldi_bevinding(nu=nu)["vingerafdruk"]
        # Regressie-classificatie: systeemmail + audit `automatisering_regressie` (run.is_regressie).
        bev = run.Bevinding(
            soort=run.BevindingSoort.LET_OP,
            administratie_id=None,
            blok=kw["blok"],
            vingerafdruk=kw["vingerafdruk"],
            tekst=kw["tekst"],
            detail=kw["detail"],
        )
        assert run.is_regressie(bev) and run.is_beheer_signaal(bev)
        # Groen ná herstel: de LET-OP verdwijnt.
        saldi.schrijf_stand(
            saldi.AdministratieSaldo(b, "B", "ok", None, debiteuren=D("0"), crediteuren=D("0")), datum=date(2026, 9, 22)
        )
        assert automatiseringen.groep_saldi_bevinding(nu=nu) is None

    def test_detector_zonder_groepen_is_stil_en_webfilter_is_geen_regressie(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        from datetime import UTC, datetime

        from app.reconciliatie import automatiseringen

        assert automatiseringen.groep_saldi_bevinding(nu=datetime.now(UTC)) is None
        kg = groepen.maak_groep(actor_id=beheerder_id, naam="Kempen groep")
        groepen.zet_groep_bulk(actor_id=beheerder_id, groep_id=kg.id, toevoegen=[administratie_id], verwijderen=[])
        saldi.schrijf_stand(
            saldi.AdministratieSaldo(administratie_id, "A", "ongeldig", "webfilter"), datum=date(2026, 9, 21)
        )
        assert automatiseringen.groep_saldi_bevinding(nu=datetime.now(UTC)) is None
