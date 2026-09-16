# ruff: noqa: F811 — pytest-fixtures als parameters
"""Rekening-courant-aansluiting (blok C, Peter 16-09): pure toets (sluit / 1 ontbrekend / 2 kandidaten zelfde bedrag
/ niet herleidbaar / tolerantie), lezers met fake clients (RLZ-paginering mét `$count` + 400-terugval zonder,
Odoo `search_read`), querytelling (calls per rekening onafhankelijk van het aantal regels onder één paginagrens),
`rc_stand`-upsert + venster (DB) en de blokfunctie tegen de tabel (rekening_b NULL = let_op, webfilter = FOUT)."""

from __future__ import annotations

import argparse
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select

from app import tijd
from app.db.session import scoped_session
from app.intercompany import rekening_courant as rc
from app.intercompany.models import RcKoppeling, RcStand
from app.reconciliatie import teksten
from app.reconciliatie.run import Verzamelaar
from app.rlz.client import RlzApiError, RlzWebfilterError
from tests.auth.conftest import administratie_id  # noqa: F401
from tests.doorbelasting.conftest import maak_administratie

D = Decimal
VANDAAG = date(2026, 9, 16)


def m(id: str, datum: str, bedrag: str, omschrijving: str | None = None, boekstuk: str | None = None) -> rc.RcMutatie:
    return rc.RcMutatie.maak(
        id=id, datum=date.fromisoformat(datum), bedrag=D(bedrag), omschrijving=omschrijving, boekstuk=boekstuk
    )


# ---- pure toets -----------------------------------------------------------------------------------


class TestToetsPaar:
    def test_sluit_cent_exact(self) -> None:
        u = rc.toets_paar(saldo_a=D("12500.00"), saldo_b=D("-12500.00"), mutaties_a=[], mutaties_b=[])
        assert u.sluit is True and u.delta == 0 and not u.ontbreekt_bij_a and not u.ontbreekt_bij_b

    def test_een_mutatie_ontbreekt_bij_b(self) -> None:
        a = [
            m("a1", "2026-09-05", "5000.00", "huur augustus", "RLZ-05-00000401"),
            m("a2", "2026-09-12", "1250.00", "huur september", "RLZ-05-00000412"),
        ]
        b = [m("b1", "2026-09-06", "-5000.00", "Huur augustus")]
        u = rc.toets_paar(saldo_a=D("12500.00"), saldo_b=D("-11250.00"), mutaties_a=a, mutaties_b=b)
        assert u.sluit is False and u.delta == D("1250.00") and u.niet_herleidbaar is False
        assert [x.id for x in u.ontbreekt_bij_b] == ["a2"] and u.ontbreekt_bij_a == ()
        assert u.regels_bij_b() == ["12-09 € 1.250,00 'huur september' (RLZ-05-00000412)"]
        assert u.gematcht == 1

    def test_een_mutatie_ontbreekt_bij_a(self) -> None:
        b = [m("b1", "2026-09-12", "-800.00", "doorbelasting", "ODOO/2026/0012")]
        u = rc.toets_paar(saldo_a=D("1000.00"), saldo_b=D("-1800.00"), mutaties_a=[], mutaties_b=b)
        assert u.delta == D("-800.00") and u.verklaard
        assert u.regels_bij_a() == ["12-09 € -800,00 'doorbelasting' (ODOO/2026/0012)"]

    def test_twee_kandidaten_zelfde_bedrag_worden_allemaal_genoemd(self) -> None:
        # Twee A-mutaties € 1.250,00 vlak bij elkaar, B heeft er één zonder herkenbare kern → niet raden.
        a = [
            m("a1", "2026-09-10", "1250.00", "huur", "RLZ-05-00000410"),
            m("a2", "2026-09-12", "1250.00", "servicekosten", "RLZ-05-00000412"),
        ]
        b = [m("b1", "2026-09-11", "-1250.00", "overboeking")]
        u = rc.toets_paar(saldo_a=D("2500.00"), saldo_b=D("-1250.00"), mutaties_a=a, mutaties_b=b)
        assert u.verklaard and len(u.ontbreekt_bij_b) == 1
        (regel,) = u.regels_bij_b()
        assert regel.startswith("één van 2 met hetzelfde bedrag: ")
        assert "RLZ-05-00000410" in regel and "RLZ-05-00000412" in regel

    def test_zelfde_kern_wint_en_kandidaat_is_dan_eenduidig(self) -> None:
        a = [
            m("a1", "2026-09-10", "1250.00", "huur september", "RLZ-05-00000410"),
            m("a2", "2026-09-12", "1250.00", "servicekosten", "RLZ-05-00000412"),
        ]
        b = [m("b1", "2026-09-11", "-1250.00", "September huur")]
        u = rc.toets_paar(saldo_a=D("2500.00"), saldo_b=D("-1250.00"), mutaties_a=a, mutaties_b=b)
        assert [x.id for x in u.ontbreekt_bij_b] == ["a2"]
        assert u.regels_bij_b() == ["12-09 € 1.250,00 'servicekosten' (RLZ-05-00000412)"]

    def test_niet_herleidbaar(self) -> None:
        a = [m("a1", "2026-09-05", "5000.00", "huur")]
        b = [m("b1", "2026-09-05", "-5000.00", "huur")]
        u = rc.toets_paar(saldo_a=D("1000.37"), saldo_b=D("-1000.00"), mutaties_a=a, mutaties_b=b)
        assert u.sluit is False and u.niet_herleidbaar is True and u.delta == D("0.37")
        assert u.tekst_niet_herleidbaar() == (
            "Δ € 0,37 niet herleidbaar tot losse mutaties — vermoedelijk afronding/koers; controleer handmatig"
        )

    def test_tolerantie_dagen(self) -> None:
        a = [m("a1", "2026-09-01", "100.00", "x")]
        b = [m("b1", "2026-09-07", "-100.00", "x")]  # 6 dagen
        u5 = rc.toets_paar(saldo_a=D("100.00"), saldo_b=D("0.00"), mutaties_a=a, mutaties_b=b, tolerantie_dagen=5)
        u6 = rc.toets_paar(saldo_a=D("100.00"), saldo_b=D("0.00"), mutaties_a=a, mutaties_b=b, tolerantie_dagen=6)
        assert u5.gematcht == 0 and u5.niet_herleidbaar is True  # rest 100 + −100 = 0 ≠ Δ 100
        assert u6.gematcht == 1 and u6.niet_herleidbaar is True  # geen rest, Δ blijft 100 → handmatig

    def test_elke_mutatie_hoogstens_een_keer(self) -> None:
        a = [m("a1", "2026-09-01", "100.00"), m("a2", "2026-09-02", "100.00")]
        b = [m("b1", "2026-09-01", "-100.00")]
        u = rc.toets_paar(saldo_a=D("200.00"), saldo_b=D("-100.00"), mutaties_a=a, mutaties_b=b)
        assert u.gematcht == 1 and len(u.ontbreekt_bij_b) == 1 and u.verklaard


class TestEuroEnRegel:
    def test_euro_nl(self) -> None:
        assert rc.euro_nl(D("1250")) == "€ 1.250,00"
        assert rc.euro_nl(D("-11250.5")) == "€ -11.250,50"
        assert rc.euro_nl(D("0.37")) == "€ 0,37"

    def test_regel_zonder_omschrijving_en_boekstuk(self) -> None:
        assert m("x", "2026-01-03", "5.00").regel() == "03-01 € 5,00"


# ---- lezers ----------------------------------------------------------------------------------------


def _rlz_rij(i: int, datum: str, debet: float = 0.0, credit: float = 0.0, omschrijving: str = "huur") -> dict:
    return {
        "id": f"{i:08d}-0000-0000-0000-000000000000",
        "DebitAmount": debet,
        "CreditAmount": credit,
        "VatAmount": 0.0,
        "Description": omschrijving,
        "JournalEntry": {"id": "je", "BookDate": f"{datum}T00:00:00", "DocumentType": 20, "EventID": 22},
    }


class FakeRlz:
    """Pagineert `JournalEntryLines` op $top/$skip; `met_count` = `@odata.count` in het antwoord; `weiger_count` =
    400 op élke call met `$count` (terugval-pad)."""

    def __init__(self, rijen: list[dict], *, met_count: bool = True, weiger_count: bool = False) -> None:
        self.rijen, self.met_count, self.weiger_count = rijen, met_count, weiger_count
        self.calls: list[dict] = []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        assert path == "JournalEntryLines"
        params = params or {}
        self.calls.append(params)
        if self.weiger_count and "$count" in params:
            raise RlzApiError(400, "GET", path, "The query parameter '$count' is not supported")
        assert params["$filter"].startswith("Account/id eq ")
        top, skip = int(params["$top"]), int(params["$skip"])
        uit = {"value": self.rijen[skip : skip + top]}
        if self.met_count and "$count" in params:
            uit["@odata.count"] = len(self.rijen)
        return uit


LEDGER = uuid.UUID("11111111-1111-1111-1111-111111111300")


class TestLezerRlz:
    def test_saldo_en_venster_uit_een_leesreeks(self) -> None:
        rijen = [
            _rlz_rij(1, "2025-01-10", debet=5000.0, omschrijving="oud"),
            _rlz_rij(2, "2026-09-05", debet=1250.0),
            _rlz_rij(3, "2026-09-06", credit=250.0),
        ]
        client = FakeRlz(rijen)
        saldo, mutaties = rc.saldo_en_mutaties_rlz(client, ledger_id=LEDGER, vanaf=date(2026, 9, 1))
        assert saldo == D("6000.00")  # Σ over ÁLLE regels
        assert [(x.datum.isoformat(), x.bedrag) for x in mutaties] == [
            ("2026-09-05", D("1250.00")),
            ("2026-09-06", D("-250.00")),
        ]
        assert mutaties[0].kern == "huur" and mutaties[0].boekstuk is None
        assert len(client.calls) == 1 and client.calls[0]["$expand"] == "JournalEntry"

    @pytest.mark.parametrize(("aantal", "calls"), [(20, 1), (200, 1), (201, 2), (400, 2), (401, 3)])
    def test_querytelling_met_count(self, aantal: int, calls: int) -> None:
        client = FakeRlz([_rlz_rij(i, "2026-09-01", debet=1.0) for i in range(aantal)])
        saldo, mutaties = rc.saldo_en_mutaties_rlz(client, ledger_id=LEDGER, vanaf=None)
        assert saldo == D(aantal) and len(mutaties) == aantal
        assert len(client.calls) == calls

    def test_400_op_count_valt_terug_zonder_count_en_op_paginalengte(self) -> None:
        client = FakeRlz([_rlz_rij(i, "2026-09-01", debet=1.0) for i in range(200)], weiger_count=True)
        saldo, mutaties = rc.saldo_en_mutaties_rlz(client, ledger_id=LEDGER, vanaf=None)
        assert saldo == D(200) and len(mutaties) == 200
        # 1 geweigerde call mét $count, daarna zonder: pagina 1 (200) + pagina 2 (leeg) = 3 calls totaal.
        assert [("$count" in c) for c in client.calls] == [True, False, False]

    def test_zonder_odata_count_stopt_op_paginalengte(self) -> None:
        client = FakeRlz([_rlz_rij(i, "2026-09-01", debet=1.0) for i in range(20)], met_count=False)
        rc.saldo_en_mutaties_rlz(client, ledger_id=LEDGER, vanaf=None)
        assert len(client.calls) == 1

    def test_webfilter_gaat_door(self) -> None:
        class Webfilter(FakeRlz):
            def get(self, path, *, params=None):  # noqa: ANN001
                raise RlzWebfilterError(403, "GET", path, "<HTML>Access Denied</HTML>")

        with pytest.raises(RlzWebfilterError):
            rc.saldo_en_mutaties_rlz(Webfilter([]), ledger_id=LEDGER, vanaf=None)


class FakeOdoo:
    company_id = 6

    def __init__(self, rijen: list[dict]) -> None:
        self.rijen = rijen
        self.calls: list[tuple] = []

    def search_read(self, model, domain, fields, *, limit=None, offset=0, order=None):  # noqa: ANN001
        self.calls.append((model, domain, tuple(fields), limit, offset))
        assert model == "account.move.line"
        assert ["company_id", "=", 6] in domain and ["parent_state", "=", "posted"] in domain
        return self.rijen[offset : offset + (limit or len(self.rijen))]


class TestLezerOdoo:
    def test_saldo_en_venster(self) -> None:
        rijen = [
            {
                "id": 1,
                "date": "2025-02-01",
                "debit": 0.0,
                "credit": 3000.0,
                "balance": -3000.0,
                "name": "oud",
                "ref": False,
                "move_name": "MISC/2025/0001",
            },
            {
                "id": 2,
                "date": "2026-09-12",
                "debit": 0.0,
                "credit": 1250.0,
                "balance": -1250.0,
                "name": "huur september",
                "ref": "RC",
                "move_name": "MISC/2026/0412",
            },
        ]
        client = FakeOdoo(rijen)
        saldo, mutaties = rc.saldo_en_mutaties_odoo(client, account_id=132, vanaf=date(2026, 9, 1))
        assert saldo == D("-4250.00")
        assert len(mutaties) == 1 and mutaties[0].bedrag == D("-1250.00")
        assert mutaties[0].boekstuk == "MISC/2026/0412"
        assert ["account_id", "=", 132] in client.calls[0][1]
        assert len(client.calls) == 1

    def test_paginering(self) -> None:
        rijen = [{"id": i, "date": "2026-09-01", "balance": 1.0, "name": "x", "move_name": "M"} for i in range(1001)]
        client = FakeOdoo(rijen)
        saldo, mutaties = rc.saldo_en_mutaties_odoo(client, account_id=1, vanaf=None)
        assert saldo == D(1001) and len(mutaties) == 1001 and len(client.calls) == 3


# ---- DB: rc_stand + venster + blokfunctie tegen de tabel -----------------------------------------


@pytest.fixture
def administratie_b_id(admin_engine: Engine) -> uuid.UUID:
    return maak_administratie(admin_engine, "Kempen Facilities B.V.")


@pytest.fixture
def paar(administratie_id: uuid.UUID, administratie_b_id: uuid.UUID, klok_vandaag) -> tuple[uuid.UUID, uuid.UUID]:
    """(A, B) mét de klok op 16-09-2026 — de vaste basis van de DB-tests."""
    return administratie_id, administratie_b_id


@pytest.fixture
def klok_vandaag(monkeypatch: pytest.MonkeyPatch):
    from datetime import UTC, datetime

    monkeypatch.setattr(tijd, "_klok", lambda: datetime(2026, 9, 16, 10, 0, tzinfo=UTC))


def _maak_koppeling(a: uuid.UUID, b: uuid.UUID, *, rekening_b: uuid.UUID | None) -> uuid.UUID:
    with scoped_session(None) as session:
        k = RcKoppeling(
            administratie_a_id=a,
            rekening_a=uuid.UUID("11111111-1111-1111-1111-111111111300"),
            rekening_a_code="1300",
            rekening_a_naam="Rekening-courant Kempen Facilities",
            administratie_b_id=b,
            rekening_b=rekening_b,
            rekening_b_code="1600" if rekening_b else None,
            rekening_b_naam="Rekening-courant Kempen B.V." if rekening_b else None,
            basis="naam",
            status="afgeleid",
        )
        session.add(k)
        session.commit()
        return k.id


REKENING_B = uuid.UUID("22222222-2222-2222-2222-222222221600")


class TestRcStand:
    def test_upsert_een_rij_per_dag_en_venster(self, paar) -> None:
        administratie_id, administratie_b_id = paar
        kid = _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        assert rc.venster_vanaf(kid) == VANDAAG - timedelta(days=rc.VENSTER_DAGEN)
        d3, d2 = VANDAAG - timedelta(days=3), VANDAAG - timedelta(days=2)
        rc.schrijf_stand(koppeling_id=kid, saldo_a=D("100.00"), saldo_b=D("-90.00"), sluit=False, datum=d3)
        rc.schrijf_stand(koppeling_id=kid, saldo_a=D("100.00"), saldo_b=D("-100.00"), sluit=True, datum=d2)
        rc.schrijf_stand(koppeling_id=kid, saldo_a=D("120.00"), saldo_b=D("-100.00"), sluit=False, datum=VANDAAG)
        rc.schrijf_stand(koppeling_id=kid, saldo_a=D("130.00"), saldo_b=D("-100.00"), sluit=False, datum=VANDAAG)
        with scoped_session(None) as session:
            rijen = session.scalars(select(RcStand).where(RcStand.koppeling_id == kid).order_by(RcStand.datum)).all()
            assert [(r.datum, r.sluit, r.saldo_a) for r in rijen] == [
                (d3, False, D("100.00")),
                (d2, True, D("100.00")),
                (VANDAAG, False, D("130.00")),
            ]
        # venster = dag ná de laatste GROENE stand vóór vandaag
        assert rc.venster_vanaf(kid) == VANDAAG - timedelta(days=1)

    def test_groene_stand_van_vandaag_verkleint_venster_niet(self, paar) -> None:
        administratie_id, administratie_b_id = paar
        kid = _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        rc.schrijf_stand(koppeling_id=kid, saldo_a=D("1.00"), saldo_b=D("-1.00"), sluit=True, datum=VANDAAG)
        assert rc.venster_vanaf(kid) == VANDAAG - timedelta(days=rc.VENSTER_DAGEN)


class TestCliBlok:
    def _patch_lezer(self, monkeypatch: pytest.MonkeyPatch, standen: dict[uuid.UUID, tuple]) -> list[tuple]:
        gezien: list[tuple] = []

        def lees(aid, ledger_id, *, vanaf):  # noqa: ANN001
            gezien.append((aid, ledger_id, vanaf))
            uit = standen[aid]
            if isinstance(uit, Exception):
                raise uit
            return uit

        monkeypatch.setattr(rc, "lees_kant", lees)
        return gezien

    def test_geen_koppelingen_is_ok_met_teller_nul(self, capsys) -> None:
        v = Verzamelaar()
        v.start_blok(rc.BLOK)
        assert rc.cli_blok(argparse.Namespace(), v) == 0
        assert v.blokken[rc.BLOK].gecontroleerd == 0 and not v.bevindingen
        assert "geen actieve rekening-courant-koppelingen" in capsys.readouterr().out

    def test_sluit_geeft_ok_en_stand_zonder_bevinding(self, paar, monkeypatch) -> None:
        administratie_id, administratie_b_id = paar
        kid = _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        self._patch_lezer(monkeypatch, {administratie_id: (D("500.00"), []), administratie_b_id: (D("-500.00"), [])})
        v = Verzamelaar()
        v.start_blok(rc.BLOK)
        assert rc.cli_blok(argparse.Namespace(), v) == 0
        assert v.blokken[rc.BLOK].gecontroleerd == 1 and v.bevindingen == []
        with scoped_session(None) as session:
            stand = session.get(RcStand, (kid, VANDAAG))
            assert stand is not None and stand.sluit is True and stand.saldo_b == D("-500.00")

    def test_sluit_niet_wordt_afwijking_met_verklaring(self, paar, monkeypatch) -> None:
        administratie_id, administratie_b_id = paar
        kid = _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        mutatie = m("a1", "2026-09-12", "1250.00", "huur september", "RLZ-05-00000412")
        gezien = self._patch_lezer(
            monkeypatch, {administratie_id: (D("12500.00"), [mutatie]), administratie_b_id: (D("-11250.00"), [])}
        )
        v = Verzamelaar()
        v.start_blok(rc.BLOK)
        assert rc.cli_blok(argparse.Namespace(), v) == 1
        assert [g[2] for g in gezien] == [VANDAAG - timedelta(days=400)] * 2
        (b,) = v.bevindingen
        assert b.soort == "afwijking" and b.administratie_id == administratie_id
        assert b.detail["afwijking_soort"] == "rc_sluit_niet" and b.detail["record_id"] == str(kid)
        assert b.detail["detail"] == "rekening_a=1300 rekening_b=1600 delta=1250.00"
        assert b.detail["ontbreekt_bij_b"] == ["12-09 € 1.250,00 'huur september' (RLZ-05-00000412)"]
        assert b.detail["administratie_b_naam"] == "Kempen Facilities B.V."
        lb = teksten.leesbaar(b, administratie_naam="Scope-test")
        assert lb.titel == "RC wijkt € 1.250,00 af — Scope-test ↔ Kempen Facilities B.V."
        assert lb.wat == (
            "Het saldo van 1300 Rekening-courant Kempen Facilities in Scope-test is € 12.500,00; de tegenrekening "
            "1600 Rekening-courant Kempen B.V. in Kempen Facilities B.V. staat op € -11.250,00 — 1 mutatie "
            "ontbreekt bij Kempen Facilities B.V.: 12-09 € 1.250,00 'huur september' (RLZ-05-00000412)."
        )
        assert lb.doe == "Boek de ontbrekende mutatie bij Kempen Facilities B.V., of accepteer met reden."
        assert not teksten.bevat_technische_sleutel(lb.titel + lb.wat + lb.doe)
        with scoped_session(None) as session:
            stand = session.get(RcStand, (kid, VANDAAG))
            assert stand is not None and stand.sluit is False

    def test_rekening_b_null_is_let_op(self, paar, monkeypatch) -> None:
        administratie_id, administratie_b_id = paar
        _maak_koppeling(administratie_id, administratie_b_id, rekening_b=None)
        gezien = self._patch_lezer(monkeypatch, {})
        v = Verzamelaar()
        v.start_blok(rc.BLOK)
        assert rc.cli_blok(argparse.Namespace(), v) == 0
        assert gezien == []
        (b,) = v.bevindingen
        assert b.soort == "let_op" and b.detail["afwijking_soort"] == "rc_zonder_tegenrekening"
        lb = teksten.leesbaar(b, administratie_naam="Scope-test")
        assert lb.titel.startswith("RC zonder tegenrekening — Scope-test")
        assert "geen tegenrekening gevonden" in lb.wat and "Instellingen › Boeken" in lb.doe
        assert not teksten.bevat_technische_sleutel(lb.titel + lb.wat + lb.doe)

    def test_webfilter_is_fout_meting_ongeldig(self, paar, monkeypatch, capsys) -> None:
        administratie_id, administratie_b_id = paar
        kid = _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        fout = RlzWebfilterError(403, "GET", "JournalEntryLines", "<HTML>Access Denied")
        self._patch_lezer(monkeypatch, {administratie_id: fout})
        v = Verzamelaar()
        v.start_blok(rc.BLOK)
        assert rc.cli_blok(argparse.Namespace(), v) == 1
        (b,) = v.bevindingen
        assert b.soort == "fout" and rc.MELDING_METING_ONGELDIG in b.tekst
        assert "meting ongeldig" in capsys.readouterr().err
        with scoped_session(None) as session:
            assert session.get(RcStand, (kid, VANDAAG)) is None

    def test_kant_niet_leesbaar_is_zichtbare_fout(self, paar, monkeypatch) -> None:
        administratie_id, administratie_b_id = paar
        _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        fout = rc.KantNietLeesbaar("geen RLZ-credentials")
        self._patch_lezer(monkeypatch, {administratie_id: (D("1.00"), []), administratie_b_id: fout})
        v = Verzamelaar()
        v.start_blok(rc.BLOK)
        assert rc.cli_blok(argparse.Namespace(), v) == 1
        (b,) = v.bevindingen
        assert b.soort == "fout" and "geen RLZ-credentials" in b.tekst

    def test_lees_only_schrijft_geen_stand(self, paar, monkeypatch, capsys) -> None:
        administratie_id, administratie_b_id = paar
        kid = _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        self._patch_lezer(monkeypatch, {administratie_id: (D("5.00"), []), administratie_b_id: (D("-5.00"), [])})
        assert rc.cli_blok(argparse.Namespace(), None) == 0
        assert "sluit" in capsys.readouterr().out
        with scoped_session(None) as session:
            assert session.get(RcStand, (kid, VANDAAG)) is None

    def test_administratie_filter(self, paar, monkeypatch) -> None:
        administratie_id, administratie_b_id = paar
        _maak_koppeling(administratie_id, administratie_b_id, rekening_b=REKENING_B)
        standen = {administratie_id: (D("5.00"), []), administratie_b_id: (D("-5.00"), [])}
        gezien = self._patch_lezer(monkeypatch, standen)
        assert rc.cli_blok(argparse.Namespace(administratie_ids=[uuid.uuid4()]), None) == 0
        assert gezien == []
        assert rc.cli_blok(argparse.Namespace(administratie_ids=[administratie_b_id]), None) == 0
        assert len(gezien) == 2


class TestKetenRegistratie:
    def test_blok_in_run_en_cli_en_teksten(self) -> None:
        from app.reconciliatie import run as run_service

        assert rc.BLOK in run_service.BLOKKEN
        volgorde = run_service.BLOKKEN
        assert volgorde.index("documenten") < volgorde.index(rc.BLOK) < volgorde.index("rlz_dubbel")
        assert teksten._BLOK_AFWIJKING[rc.BLOK] is teksten._rekening_courant

    def test_niet_herleidbaar_tekst(self) -> None:
        from app.reconciliatie.run import Bevinding

        detail = {
            "afwijking_soort": "rc_sluit_niet",
            "administratie_a_naam": "Kempen B.V.",
            "administratie_b_naam": "Kempen Facilities",
            "rekening_a_code": "1300",
            "rekening_b_code": "1600",
            "saldo_a": "1000.37",
            "saldo_b": "-1000.00",
            "delta": "0.37",
            "ontbreekt_bij_a": [],
            "ontbreekt_bij_b": [],
            "niet_herleidbaar": True,
        }
        b = Bevinding(
            blok=rc.BLOK,
            soort="afwijking",
            administratie_id=uuid.uuid4(),
            vingerafdruk="x",
            tekst="AFWIJKING x",
            detail=detail,
        )
        lb = teksten.leesbaar(b)
        assert lb.titel == "RC wijkt € 0,37 af — Kempen B.V. ↔ Kempen Facilities"
        assert lb.wat.endswith(
            "— Δ € 0,37 niet herleidbaar tot losse mutaties — vermoedelijk afronding/koers; controleer handmatig."
        )
        assert lb.doe.startswith("Controleer handmatig op afronding/koers")
