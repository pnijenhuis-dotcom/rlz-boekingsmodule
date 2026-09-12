# ruff: noqa: F811 — pytest-fixtures als parameters
"""Run 2 VGG 12-09 blok 2: dubbel-snede 2 (zelfde crediteur + zelfde bedrag + boekdatum ±3 d, ongeacht referentie)
als LEES-ONLY meetlat in `rlz_dubbel` — bank leidend (CONTRACT_RUN2 besluit 4 + 6).

Puur: paren binnen ±3 dagen wel, 4 dagen niet; zelfde referentie al in cluster → niet; beide module → niet; bank 2/2
→ niet gemeld (teller); bank 1/2 → gemeld; bank niet gelezen → gemeld mét markering. Lezer: `$filter=BookDate ge`,
400 → zonder filter, 403 → None. Guard: de dagelijkse run (snede2=False) leest GEEN PaymentTransactions en meldt niets
van snede 2; de lees-only CLI wél, mét regel per paar, tellers per administratie en totaal."""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app import cli
from app.migratie.bankdekking import BankMutatie
from app.reconciliatie import rlz_dubbel
from app.reconciliatie.rlz_dubbel import (
    LABEL_MODULE_X_NIET,
    LABEL_NIET_X_NIET,
    RlzDocument,
    Snede2Paar,
    lees_payment_transactions,
    naar_rlz_document,
    snede2_uitkomst,
    toets_met_client,
    vind_clusters,
    vind_snede2,
)
from app.rlz.client import RlzApiError
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ZENVOICES = uuid.UUID("d51c26fe-0000-4000-8000-00000000ce5a")
V5_MODULE = uuid.uuid5(uuid.NAMESPACE_URL, "snede2-module")
V5_MODULE_B = uuid.uuid5(uuid.NAMESPACE_URL, "snede2-module-b")


def _v4(n: int) -> uuid.UUID:
    return uuid.UUID(f"bbbbbbbb-0000-4000-8000-{n:012d}")


def _rij(
    rlz_id: uuid.UUID,
    *,
    ref: str | None,
    boekdatum: str,
    datum: str | None = None,
    bedrag: float = 1234.56,
    boekstuk: str = "RLZ-04-00000001",
    entity: uuid.UUID | None = ZENVOICES,
    naam: str = "Bouwbedrijf Jansen en Zonen B.V.",
    status: int = 2,
) -> dict:
    return {
        "id": str(rlz_id),
        "Entity": {"id": str(entity), "Name": naam} if entity else None,
        "Reference": ref,
        "Date": f"{datum or boekdatum}T00:00:00Z",
        "BookDate": f"{boekdatum}T00:00:00Z",
        "BaseInvoiceAmount": bedrag,
        "ReceiptNumber": boekstuk,
        "Status": status,
    }


def _doc(rlz_id: uuid.UUID, *, module_ids: set[uuid.UUID] | None = None, **kw) -> RlzDocument:
    d = naar_rlz_document(_rij(rlz_id, **kw), module_ids=module_ids or set())
    assert d is not None
    return d


def _bank(*mutaties: tuple[str, str]) -> list[BankMutatie]:
    """(bedrag, datum) → afboekingen (teken −1), zoals bij een betaalde inkoopfactuur."""
    return [
        BankMutatie(rlz_id=f"tx{i}", bedrag=Decimal(b), boekdatum=date.fromisoformat(d), teken=-1)
        for i, (b, d) in enumerate(mutaties)
    ]


def _paar_zenvoices_module() -> list[RlzDocument]:
    """Dezelfde factuur twee keer: via Zenvoices (handmatig, referentie F-2026-0042) en via de module (UUIDv5,
    referentie 2026-42 → zelfde genormaliseerde referentie zou snede 1 zijn; hier een ándere referentie)."""
    return [
        _doc(_v4(1), ref="F-2026-0042", boekdatum="2026-06-22", boekstuk="RLZ-04-00000100"),
        _doc(
            V5_MODULE,
            module_ids={V5_MODULE},
            ref="20260042-A",
            boekdatum="2026-06-24",
            boekstuk="RLZ-04-00000107",
        ),
    ]


class TestVindSnede2:
    def test_paar_binnen_drie_dagen_ongeacht_referentie_label_module_x_niet_module(self) -> None:
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=[])
        assert isinstance(p, Snede2Paar)
        assert {p.a.boekstuk, p.b.boekstuk} == {"RLZ-04-00000100", "RLZ-04-00000107"}
        assert p.label == LABEL_MODULE_X_NIET and p.dagen_verschil == 2 and p.bedrag == Decimal("1234.56")
        assert p.bank_gelezen is True and p.bank_mutaties == 0 and p.bank_bevestigd is False

    def test_vier_dagen_is_geen_paar_drie_wel(self) -> None:
        a = _doc(_v4(1), ref="A", boekdatum="2026-06-22")
        assert vind_snede2([a, _doc(_v4(2), ref="B", boekdatum="2026-06-26")], clusters=(), bank=[]) == []
        assert len(vind_snede2([a, _doc(_v4(2), ref="B", boekdatum="2026-06-25")], clusters=(), bank=[])) == 1

    def test_boekdatum_gaat_voor_factuurdatum(self) -> None:
        a = _doc(_v4(1), ref="A", boekdatum="2026-06-22", datum="2026-01-01")
        b = _doc(_v4(2), ref="B", boekdatum="2026-06-23", datum="2026-03-03")
        (p,) = vind_snede2([a, b], clusters=(), bank=[])
        assert p.dagen_verschil == 1

    def test_ander_bedrag_of_andere_crediteur_of_geen_crediteur_is_geen_paar(self) -> None:
        a = _doc(_v4(1), ref="A", boekdatum="2026-06-22")
        assert (
            vind_snede2([a, _doc(_v4(2), ref="B", boekdatum="2026-06-22", bedrag=1234.57)], clusters=(), bank=[]) == []
        )
        andere = _doc(_v4(3), ref="B", boekdatum="2026-06-22", entity=uuid.UUID(int=7))
        assert vind_snede2([a, andere], clusters=(), bank=[]) == []
        assert vind_snede2([a, _doc(_v4(4), ref="B", boekdatum="2026-06-22", entity=None)], clusters=(), bank=[]) == []

    def test_zelfde_referentie_al_in_cluster_wordt_niet_nog_eens_gemeld(self) -> None:
        docs = [
            _doc(_v4(1), ref="2026-118", boekdatum="2026-08-14", boekstuk="RLZ-04-00000069"),
            _doc(_v4(2), ref="2026-118", boekdatum="2026-08-14", boekstuk="RLZ-04-00000072"),
        ]
        clusters = vind_clusters(docs, rlz_admin_id="r").clusters
        assert len(clusters) == 1
        assert vind_snede2(docs, clusters=clusters, bank=[]) == []
        # zonder de cluster-uitsluiting zou het wél een snede-2-paar zijn (guard op de uitsluiting zelf)
        assert len(vind_snede2(docs, clusters=(), bank=[])) == 1

    def test_beide_van_de_module_is_nooit_een_paar(self) -> None:
        ids = {V5_MODULE, V5_MODULE_B}
        docs = [
            _doc(V5_MODULE, module_ids=ids, ref="A", boekdatum="2026-06-22"),
            _doc(V5_MODULE_B, module_ids=ids, ref="B", boekdatum="2026-06-22"),
        ]
        assert vind_snede2(docs, clusters=(), bank=[]) == []
        # één module + één handmatig ís een paar; twee handmatige óók (niet-module×niet-module)
        docs2 = [_doc(_v4(1), ref="A", boekdatum="2026-06-22"), _doc(_v4(2), ref="B", boekdatum="2026-06-22")]
        (p,) = vind_snede2(docs2, clusters=(), bank=[])
        assert p.label == LABEL_NIET_X_NIET

    def test_bank_twee_van_twee_is_bevestigd_en_niet_gemeld_wel_geteld(self) -> None:
        bank = _bank(("1234.56", "2026-06-23"), ("1234.56", "2026-06-25"))
        assert vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bank) == []
        u = snede2_uitkomst(_paar_zenvoices_module(), clusters=(), bank=bank)
        assert u.paren == () and u.bank_bevestigd == 1 and u.bank_gelezen is True
        assert u.tellers() == {"paren": 0, LABEL_MODULE_X_NIET: 0, LABEL_NIET_X_NIET: 0, "bank_bevestigd": 1}

    def test_bank_een_van_twee_is_gemeld_met_k_van_n(self) -> None:
        bank = _bank(("1234.56", "2026-06-23"), ("1234.56", "2026-07-10"))  # tweede buiten het venster
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bank)
        assert p.bank_mutaties == 1 and p.bank_bevestigd is False
        assert p.regel("adm").endswith("| module×niet-module | bank 1/2")

    def test_bank_teken_moet_afboeking_zijn_voor_inkoop(self) -> None:
        bijboekingen = [BankMutatie("t", Decimal("1234.56"), date(2026, 6, 23), 1) for _ in range(2)]
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bijboekingen)
        assert p.bank_mutaties == 0

    def test_bank_niet_gelezen_gemeld_met_markering(self) -> None:
        bank = _bank(("1234.56", "2026-06-23"), ("1234.56", "2026-06-25"))
        assert vind_snede2(_paar_zenvoices_module(), clusters=(), bank=bank) == []
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=None)
        assert p.bank_gelezen is False and p.bank_bevestigd is False
        assert p.regel("adm").endswith("| bank niet gelezen")
        u = snede2_uitkomst(_paar_zenvoices_module(), clusters=(), bank=None)
        assert u.bank_gelezen is False and u.bank_bevestigd == 0 and len(u.paren) == 1

    def test_regel_anonimiseert_crediteur_tot_initialen(self) -> None:
        (p,) = vind_snede2(_paar_zenvoices_module(), clusters=(), bank=[])
        regel = p.regel("adm-1")
        assert regel.startswith(
            "SNEDE2 adm-1 RLZ-04-00000100 + RLZ-04-00000107 | B.J.E.Z. | € 1234.56 | 2026-06-22/2026-06-24 | "
        )
        assert "Jansen" not in regel

    def test_drie_exemplaren_geven_drie_paren_elke_bankmutatie_een_keer(self) -> None:
        docs = [_doc(_v4(i), ref=f"R{i}", boekdatum="2026-06-22", boekstuk=f"RLZ-04-{i:08d}") for i in range(1, 4)]
        bank = _bank(("1234.56", "2026-06-22"))
        paren = vind_snede2(docs, clusters=(), bank=bank)
        assert len(paren) == 3 and all(p.bank_mutaties == 1 for p in paren)
        assert paren == sorted(paren, key=lambda p: (str(p.a.rlz_id), str(p.b.rlz_id)))


# ---- lezer + toets_met_client ------------------------------------------------------------------------------


class _Client:
    """PurchaseInvoices + PaymentTransactions; `bank_filter` = 'ok' | 400 | 403 bepaalt het antwoord op een
    `$filter` op PaymentTransactions."""

    def __init__(self, facturen: list[dict], bank: list[dict], *, bank_filter: str | int = "ok") -> None:
        self.facturen, self.bank, self.bank_filter = facturen, bank, bank_filter
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((path, params))
        rijen = self.facturen if path == "PurchaseInvoices" else self.bank
        if path == "PaymentTransactions":
            if self.bank_filter == 403:
                raise RlzApiError(403, "GET", path, "Forbidden")
            if "$filter" in params and self.bank_filter == 400:
                raise RlzApiError(400, "GET", path, "filter niet ondersteund")
        skip, top = int(params["$skip"]), int(params["$top"])
        return {"value": rijen[skip : skip + top]}

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _tx(bedrag: float, datum: str, id_: str) -> dict:
    return {"id": id_, "Amount": bedrag, "BookDate": f"{datum}T00:00:00", "OpenAmount": 0.0}


class TestLezerEnToets:
    def test_filter_bookdate_eerst(self) -> None:
        client = _Client([], [_tx(-1234.56, "2026-06-23", "a")])
        rijen = lees_payment_transactions(client, vanaf=date(2025, 8, 4))  # type: ignore[arg-type]
        assert rijen == [_tx(-1234.56, "2026-06-23", "a")]
        assert client.calls == [
            ("PaymentTransactions", {"$top": "200", "$skip": "0", "$filter": "BookDate ge 2025-08-04"})
        ]

    def test_400_op_filter_valt_terug_zonder_filter_en_filtert_client_side(self) -> None:
        client = _Client([], [_tx(-1.0, "2024-01-01", "oud"), _tx(-1234.56, "2026-06-23", "a")], bank_filter=400)
        rijen = lees_payment_transactions(client, vanaf=date(2025, 8, 4))  # type: ignore[arg-type]
        assert [r["id"] for r in rijen] == ["a"]
        assert [("$filter" in p) for _, p in client.calls] == [True, False]

    def test_403_is_none_bank_niet_gelezen(self) -> None:
        client = _Client([], [_tx(-1.0, "2026-06-23", "a")], bank_filter=403)
        assert lees_payment_transactions(client, vanaf=date(2025, 8, 4)) is None  # type: ignore[arg-type]

    def test_dagelijkse_run_leest_geen_paymenttransactions_en_kent_geen_snede2(self) -> None:
        client = _Client(
            [_rij(d.rlz_id, ref=d.referentie, boekdatum="2026-06-22") for d in _paar_zenvoices_module()], []
        )
        r = toets_met_client(client, module_ids={V5_MODULE}, vandaag=date(2026, 9, 8))  # type: ignore[arg-type]
        assert r.snede2 is None
        assert all(pad == "PurchaseInvoices" for pad, _ in client.calls)

    def test_lees_only_leest_bank_en_vult_snede2(self) -> None:
        facturen = [
            _rij(_v4(1), ref="F-2026-0042", boekdatum="2026-06-22", boekstuk="RLZ-04-00000100"),
            _rij(V5_MODULE, ref="20260042-A", boekdatum="2026-06-24", boekstuk="RLZ-04-00000107"),
            _rij(_v4(5), ref="X1", boekdatum="2026-07-01", boekstuk="RLZ-04-00000200", bedrag=50.0),
            _rij(_v4(6), ref="X2", boekdatum="2026-07-02", boekstuk="RLZ-04-00000201", bedrag=50.0),
        ]
        bank = [_tx(-50.0, "2026-07-01", "a"), _tx(-50.0, "2026-07-02", "b")]  # het € 50-paar is bank-bevestigd
        client = _Client(facturen, bank)
        r = toets_met_client(client, module_ids={V5_MODULE}, vandaag=date(2026, 9, 8), snede2=True)  # type: ignore[arg-type]
        assert r.snede2 is not None and r.snede2.gedraaid and r.snede2.bank_gelezen
        assert [(p.a.boekstuk, p.b.boekstuk, p.label) for p in r.snede2.paren] == [
            ("RLZ-04-00000100", "RLZ-04-00000107", LABEL_MODULE_X_NIET)
        ] or [(p.b.boekstuk, p.a.boekstuk, p.label) for p in r.snede2.paren] == [
            ("RLZ-04-00000100", "RLZ-04-00000107", LABEL_MODULE_X_NIET)
        ]
        assert r.snede2.bank_bevestigd == 1
        assert any(pad == "PaymentTransactions" for pad, _ in client.calls)

    def test_lees_only_met_geweigerde_bank_markeert(self) -> None:
        facturen = [_rij(d.rlz_id, ref=d.referentie, boekdatum=str(d.boekdatum)) for d in _paar_zenvoices_module()]
        client = _Client(facturen, [], bank_filter=403)
        r = toets_met_client(client, module_ids={V5_MODULE}, vandaag=date(2026, 9, 8), snede2=True)  # type: ignore[arg-type]
        assert r.snede2 is not None and r.snede2.bank_gelezen is False and len(r.snede2.paren) == 1


# ---- CLI (lees-only) ---------------------------------------------------------------------------------------


def _rapport(aid: uuid.UUID, documenten: list[RlzDocument], *, snede2: rlz_dubbel.Snede2Uitkomst | None):
    uitkomst = vind_clusters(documenten, rlz_admin_id="rlz-a")
    return rlz_dubbel.RlzDubbelRapport(
        administratie_id=aid,
        aantal_getoetst=len(documenten),
        aantal_module=sum(1 for d in documenten if d.van_module),
        aantal_zonder_crediteur=0,
        paren=(),
        venster_vanaf=date(2025, 8, 4),
        clusters=uitkomst.clusters,
        uitgesloten=uitkomst.uitgesloten,
        rlz_admin_id="rlz-a",
        snede2=snede2,
    )


class TestCliLeesOnlySnede2:
    def test_lees_only_print_regel_per_paar_tellers_en_totaal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        docs = _paar_zenvoices_module()
        gezien: list[dict] = []

        def toets_alle(**kw):  # noqa: ANN003, ANN202
            gezien.append(kw)
            u = snede2_uitkomst(docs, clusters=(), bank=_bank(("1234.56", "2026-06-23")))
            return rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, docs, snede2=u)}
            )

        monkeypatch.setattr(rlz_dubbel, "toets_alle", toets_alle)
        code = cli.main(
            ["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only", "--administratie", str(administratie_id)]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert gezien == [{"administratie_ids": [administratie_id], "snede2": True}]
        assert (
            f"    - SNEDE2 {administratie_id} RLZ-04-00000100 + RLZ-04-00000107 | B.J.E.Z. | € 1234.56 | "
            "2026-06-22/2026-06-24 | module×niet-module | bank 1/2" in out
        )
        assert (
            f"    SNEDE2 tellers {administratie_id}: paren 1, module×niet-module 1, niet-module×niet-module 0, "
            "bank-bevestigd 0" in out
        )
        assert (
            "SNEDE2 totaal over 1 administratie(s): paren 1, module×niet-module 1, niet-module×niet-module 0, "
            "bank-bevestigd 0. Alleen meetlat — de dagelijkse run meldt snede 2 niet (beslispunt Peter)." in out
        )
        assert "Jansen" not in out

    def test_lees_only_bank_niet_gelezen_zichtbaar_in_tellers_en_totaal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], administratie_id: uuid.UUID
    ) -> None:
        docs = _paar_zenvoices_module()
        u = snede2_uitkomst(docs, clusters=(), bank=None)
        monkeypatch.setattr(
            rlz_dubbel,
            "toets_alle",
            lambda **kw: rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, docs, snede2=u)}
            ),
        )
        assert cli.main(["reconciliatie-alles", "--alleen", "rlz_dubbel", "--lees-only"]) == 0
        out = capsys.readouterr().out
        assert "| module×niet-module | bank niet gelezen" in out
        assert "bank-bevestigd 0 — BANK NIET GELEZEN (PaymentTransactions weigerde; niets gefilterd)" in out
        assert "bank niet gelezen bij 1 administratie(s)" in out

    def test_dagelijkse_run_vraagt_snede2_false_en_print_niets_van_snede2(
        self, monkeypatch: pytest.MonkeyPatch, administratie_id: uuid.UUID
    ) -> None:
        gezien: list[dict] = []

        def toets_alle(**kw):  # noqa: ANN003, ANN202
            gezien.append(kw)
            return rlz_dubbel.RlzDubbelResultaat(
                rapporten={administratie_id: _rapport(administratie_id, _paar_zenvoices_module(), snede2=None)}
            )

        monkeypatch.setattr(rlz_dubbel, "toets_alle", toets_alle)
        uit: list[str] = []
        assert rlz_dubbel.cli_blok(argparse.Namespace(), verzamelaar=None, stdout=uit.append, stderr=uit.append) == 0
        assert gezien == [{"administratie_ids": None, "snede2": False}]
        assert not any("SNEDE2" in r for r in uit)
