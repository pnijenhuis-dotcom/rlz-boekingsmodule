"""`rlz-lezen` (blok 10 run 11-09): lees-only OData-GET als nameting-instrument — weigert Actions/POST, anonimiseert,
honoreert en begrenst --top. Geen DB, geen netwerk: administratie-lookup en client worden geïnjecteerd."""

from __future__ import annotations

import argparse
import io
import json
import uuid

import httpx
import pytest

from app import cli
from app.rlz import lezen_cli
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials
from app.rlz.lezen_cli import LeesOnlyClient, OngeldigPad, SchrijfGeweigerd, anonimiseer, run_rlz_lezen, valideer_pad

ADMIN_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
RLZ_ADMIN = "97ac3a99-da88-4084-b163-06e23d329e05"


def _args(**kw) -> argparse.Namespace:  # noqa: ANN003
    basis = dict(
        commando="rlz-lezen",
        administratie="Nijenhuis C.V.",
        pad="PaymentTransactions",
        expand=None,
        filter=None,
        orderby=None,
        top=5,
        count=False,
        anonimiseer=False,
    )
    basis.update(kw)
    return argparse.Namespace(**basis)


def _zoek_een(_: str):  # noqa: ANN202
    return [(ADMIN_ID, "Administratiekantoor Nijenhuis C.V.", RLZ_ADMIN)]


class _Vastlegger:
    """MockTransport die élk request vastlegt en een klein RLZ-achtig antwoord geeft."""

    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.body = body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, text='{"Message":"Actie niet toegestaan bij huidige gebruikersrechten"}')
        return httpx.Response(200, json=self.body if self.body is not None else {"value": []})


def _client_met(transport: _Vastlegger) -> LeesOnlyClient:
    http = httpx.Client(base_url="https://rlz.test/api/v1", transport=httpx.MockTransport(transport))
    return LeesOnlyClient(username="", password="", admin_id=RLZ_ADMIN, client=http)


# --- pad-validatie: Actions/Download/query nooit ---------------------------------------------------------------


@pytest.mark.parametrize(
    "pad",
    [
        "PaymentTransactions/abc/Actions",
        "paymenttransactions/abc/actions",
        "Remittances/x/ACTIONS/",
        "Files/x/Download",
        "$metadata",
        "PaymentTransactions?$top=5",
        "PaymentTransactions&x",
        "../Administrations",
        "",
        "https://x/y",
        "PaymentTransactions/./x",
    ],
)
def test_valideer_pad_weigert(pad: str) -> None:
    with pytest.raises(OngeldigPad):
        valideer_pad(pad)


@pytest.mark.parametrize(
    "pad",
    [
        "PaymentTransactions",
        "/PaymentTransactions/",
        "PurchaseInvoices/abc-123",
        "Customers/abc/BankRelations",
        "Remittances/x/Export",
    ],
)
def test_valideer_pad_accepteert_leesroutes(pad: str) -> None:
    assert valideer_pad(pad) == pad.strip("/")


def test_actions_pad_geeft_exit_2_zonder_enige_call() -> None:
    transport = _Vastlegger()
    code = run_rlz_lezen(
        _args(pad="PaymentTransactions/abc/Actions"),
        zoek=_zoek_een,
        client_factory=lambda _: _client_met(transport),
        uit=io.StringIO(),
    )
    assert code == 2 and transport.requests == []


# --- de client kan niet schrijven ---------------------------------------------------------------------------------


def test_leesonly_client_weigert_elke_niet_get() -> None:
    transport = _Vastlegger()
    client = _client_met(transport)
    with pytest.raises(SchrijfGeweigerd):
        client.put("PurchaseInvoices/x", {"id": "x"})
    with pytest.raises(SchrijfGeweigerd):
        client.post_action("PaymentTransactions/x", 15, PaymentItemList=[{"id": "y"}])
    with pytest.raises(SchrijfGeweigerd):
        client.request_raw("POST", "PaymentTransactions/x/Actions", json={"Type": 116})
    with pytest.raises(SchrijfGeweigerd):
        client.request_raw("DELETE", "PaymentTransactions/x")
    assert transport.requests == [], "er mag geen enkel HTTP-request ontstaan"
    client.get("PaymentTransactions")
    assert [r.method for r in transport.requests] == ["GET"]


# --- anonimisering -------------------------------------------------------------------------------------------------


def test_anonimiseer_iban_naam_guid_maar_niet_bedrag_of_enum() -> None:
    invoer = {
        "id": "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5",
        "Amount": -41362.85,
        "BookDate": "2025-10-17T00:00:00",
        "CounterAccount": "NL91ABNA0417164300",
        "Name": "Jan de Vries Steigerbouw",
        "Reference": "TOTAAL 26 VZ via NL91ABNA0417164300 doc 4b8fe4e7-1111-2222-3333-444444444444",
        "PaymentBatchId": "RLZEE_CT_20251017_153722_9221_0001",
        "Batch": {"BatchId": "RLZEE_CT_20251017_153722_9221_0001", "FileName": "RLZEE_CT_20251017_153722_9221.xml"},
        "PaymentAccount": {"AccountNumber": "NL91ABNA0417164300", "IBAN": "NL91ABNA0417164300"},
        "Status": {"id": 2, "Name": "Open", "Description": "Openstaand", "ShortDescription": "Open"},
        "Ledger": {"AccountNumber": "1010"},
    }
    uit = anonimiseer(invoer)
    assert uit["id"] == "8dbfb856…"
    assert uit["Amount"] == -41362.85 and uit["BookDate"] == "2025-10-17T00:00:00"
    assert uit["CounterAccount"] == "…4300"
    assert uit["Name"] == "J.D.V.S."
    assert (
        "NL91ABNA0417164300" not in uit["Reference"] and "…4300" in uit["Reference"] and "4b8fe4e7…" in uit["Reference"]
    )
    assert uit["PaymentBatchId"] == "RLZEE_CT_20251017_153722_9221_0001"  # batch-kenmerk blijft leesbaar
    assert uit["Batch"]["FileName"] == "RLZEE_CT_20251017_153722_9221.xml"
    assert uit["PaymentAccount"] == {"AccountNumber": "…4300", "IBAN": "…4300"}
    assert uit["Status"]["Name"] == "Open"  # enum-lid: geen persoon
    assert uit["Ledger"]["AccountNumber"] == "1010"  # grootboeknummer is geen IBAN
    assert anonimiseer([{"Name": "Piet"}, "NL02RABO0123456789"]) == [{"Name": "P."}, "…6789"]
    # Nameting 11-09 (C.V.): een IBAN ín een bestandsnaam eindigt op `_` (woordteken) — moet óók gemaskeerd worden.
    assert anonimiseer({"FileName": "NL91ABNA0417164300_260908205648.xml"}) == {"FileName": "…4300_260908205648.xml"}
    assert anonimiseer("batch NL91ABNA0417164300/2026") == "batch …4300/2026"


def test_uitvoer_is_altijd_geanonimiseerd_ook_zonder_vlag() -> None:
    transport = _Vastlegger(
        body={
            "value": [
                {
                    "id": "1291d13a-aaaa-bbbb-cccc-dddddddddddd",
                    "Name": "Vos Beheer",
                    "CounterAccount": "NL02RABO0123450537",
                    "Amount": 11417.98,
                }
            ]
        }
    )
    uit = io.StringIO()
    code = run_rlz_lezen(
        _args(anonimiseer=False), zoek=_zoek_een, client_factory=lambda _: _client_met(transport), uit=uit
    )
    assert code == 0
    tekst = uit.getvalue()
    assert "1291d13a-aaaa" not in tekst and "Vos Beheer" not in tekst and "NL02RABO0123450537" not in tekst
    data = json.loads(tekst)
    assert data["antwoord"]["value"][0] == {
        "id": "1291d13a…",
        "Name": "V.B.",
        "CounterAccount": "…0537",
        "Amount": 11417.98,
    }
    assert data["rlz_lezen"]["administratie_id"] == "11111111…"


# --- top + params --------------------------------------------------------------------------------------------------


def test_top_expand_filter_gaan_als_odata_params_mee_op_het_admin_pad() -> None:
    transport = _Vastlegger()
    code = run_rlz_lezen(
        _args(
            top=7,
            expand="Batch,PaymentReferenceList($expand=Document)",
            filter="PaymentBatchId ne null",
            orderby="BookDate desc",
            count=True,
        ),
        zoek=_zoek_een,
        client_factory=lambda _: _client_met(transport),
        uit=io.StringIO(),
    )
    assert code == 0 and len(transport.requests) == 1
    req = transport.requests[0]
    assert req.method == "GET" and req.url.path == f"/api/v1/{RLZ_ADMIN}/PaymentTransactions"
    q = dict(req.url.params)
    assert q == {
        "$top": "7",
        "$expand": "Batch,PaymentReferenceList($expand=Document)",
        "$filter": "PaymentBatchId ne null",
        "$orderby": "BookDate desc",
        "$count": "true",
    }


def test_top_default_5_en_boven_50_geweigerd() -> None:
    transport = _Vastlegger()
    assert (
        run_rlz_lezen(_args(), zoek=_zoek_een, client_factory=lambda _: _client_met(transport), uit=io.StringIO()) == 0
    )
    assert dict(transport.requests[0].url.params)["$top"] == "5"
    transport2 = _Vastlegger()
    assert (
        run_rlz_lezen(
            _args(top=51), zoek=_zoek_een, client_factory=lambda _: _client_met(transport2), uit=io.StringIO()
        )
        == 2
    )
    assert (
        run_rlz_lezen(_args(top=0), zoek=_zoek_een, client_factory=lambda _: _client_met(transport2), uit=io.StringIO())
        == 2
    )
    assert transport2.requests == []
    transport3 = _Vastlegger()
    assert (
        run_rlz_lezen(
            _args(top=50), zoek=_zoek_een, client_factory=lambda _: _client_met(transport3), uit=io.StringIO()
        )
        == 0
    )
    assert dict(transport3.requests[0].url.params)["$top"] == "50"


# --- fouten leesbaar -----------------------------------------------------------------------------------------------


def test_niet_eenduidige_administratie_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    twee = lambda _: [(ADMIN_ID, "A", RLZ_ADMIN), (uuid.uuid4(), "B", RLZ_ADMIN)]  # noqa: E731
    assert (
        run_rlz_lezen(_args(), zoek=twee, client_factory=lambda _: pytest.fail("geen client"), uit=io.StringIO()) == 2
    )
    assert "niet eenduidig (2 treffers: A, B)" in capsys.readouterr().err
    assert run_rlz_lezen(_args(), zoek=lambda _: [], client_factory=lambda _: pytest.fail("x"), uit=io.StringIO()) == 2


def test_geen_credential_en_rlz_403_leesbaar_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    def geen(_: str) -> LeesOnlyClient:
        raise GeenRlzCredentials("Administratie draait op Odoo")

    assert run_rlz_lezen(_args(), zoek=_zoek_een, client_factory=geen, uit=io.StringIO()) == 1
    assert "geen Reeleezee-verbinding" in capsys.readouterr().err
    transport = _Vastlegger(status=403)
    assert (
        run_rlz_lezen(
            _args(pad="Remittances"), zoek=_zoek_een, client_factory=lambda _: _client_met(transport), uit=io.StringIO()
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "HTTP 403" in err and "gebruikersrechten" in err


def test_cli_dispatch_kent_rlz_lezen(monkeypatch: pytest.MonkeyPatch) -> None:
    aangeroepen: list[argparse.Namespace] = []
    monkeypatch.setattr(cli, "run_rlz_lezen", lambda args: aangeroepen.append(args) or 0)
    assert cli.main(["rlz-lezen", "--administratie", "x", "--pad", "PaymentTransactions", "--top", "3"]) == 0
    assert aangeroepen[0].top == 3 and aangeroepen[0].pad == "PaymentTransactions"


def test_leesonly_client_geeft_rlz_api_error_door_bij_4xx() -> None:
    client = _client_met(_Vastlegger(status=404))
    with pytest.raises(RlzApiError):
        client.get("Remittances")
    assert lezen_cli.MAX_TOP == 50


def test_recordpad_krijgt_alleen_expand_geen_top(capsys: pytest.CaptureFixture[str]) -> None:
    """Blok 7c 13-09 (STAP-0): `ManualJournals/<guid>` is één record — RLZ weigert `$top`/`$filter` daarop met 400 "The
    requested resource is not a collection"; rlz-lezen laat ze weg en meldt dat, `$expand` gaat wél mee."""
    assert lezen_cli.is_recordpad("ManualJournals/bfae5951-fa8e-4329-ad1d-9c8f228fa8b6")
    assert not lezen_cli.is_recordpad("ManualJournals/bfae5951-fa8e-4329-ad1d-9c8f228fa8b6/Lines")
    assert not lezen_cli.is_recordpad("PaymentTransactions")
    vastlegger = _Vastlegger(body={"id": "bfae5951-fa8e-4329-ad1d-9c8f228fa8b6", "BookDate": "2025-07-15T00:00:00"})
    code = run_rlz_lezen(
        _args(
            pad="ManualJournals/bfae5951-fa8e-4329-ad1d-9c8f228fa8b6",
            expand="DocumentLineList($expand=Account)",
            filter="Status eq 3",
            top=5,
            count=True,
        ),
        zoek=_zoek_een,
        client_factory=lambda _rid: _client_met(vastlegger),
    )
    assert code == 0
    [req] = vastlegger.requests
    assert dict(req.url.params) == {"$expand": "DocumentLineList($expand=Account)"}
    assert "recordpad" in capsys.readouterr().err


def test_record_via_filter_leest_collectie_dan_record_en_lekt_geen_guid(capsys: pytest.CaptureFixture[str]) -> None:
    """Blok 7d 14-09 (STAP-0 zonder GUID's): `--record-via-filter` = collectie-GET met $filter + $top=2 → precies één
    treffer → record-GET met alleen $expand; het id staat nergens in de uitvoer (geanonimiseerd), 0/≥ 2 treffers =
    exit 2."""
    guid = "bfae5951-fa8e-4329-ad1d-9c8f228fa8b6"

    class _TweeStappen(_Vastlegger):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path.endswith(f"/{guid}"):
                return httpx.Response(
                    200,
                    json={
                        "id": guid,
                        "ReceiptNumber": "RLZ-06-00000106",
                        "DocumentLineList": [{"DebitAmount": 175000.0, "CreditAmount": 0.0, "CreditOrDebit": 1}],
                    },
                )
            return httpx.Response(200, json={"value": [{"id": guid, "ReceiptNumber": "RLZ-06-00000106"}]})

    vastlegger = _TweeStappen()
    uit = io.StringIO()
    code = run_rlz_lezen(
        _args(
            pad="ManualJournals",
            expand="DocumentLineList($expand=Account)",
            record_via_filter="ReceiptNumber eq 'RLZ-06-00000106'",
            top=5,
            count=True,
        ),
        zoek=_zoek_een,
        client_factory=lambda _rid: _client_met(vastlegger),
        uit=uit,
    )
    assert code == 0 and len(vastlegger.requests) == 2
    eerste, tweede = vastlegger.requests
    assert eerste.url.path.endswith("/ManualJournals")
    assert dict(eerste.url.params) == {"$top": "2", "$filter": "ReceiptNumber eq 'RLZ-06-00000106'"}
    assert tweede.url.path.endswith(f"/ManualJournals/{guid}")
    assert dict(tweede.url.params) == {"$expand": "DocumentLineList($expand=Account)"}
    tekst = uit.getvalue()
    assert guid not in tekst and "bfae5951…" in tekst
    data = json.loads(tekst)
    assert data["rlz_lezen"]["record_via_filter"] == "ReceiptNumber eq 'RLZ-06-00000106'"
    assert data["antwoord"]["DocumentLineList"][0]["DebitAmount"] == 175000.0
    assert "record gevonden via filter" in capsys.readouterr().err
    # 0 treffers → exit 2, géén record-GET
    leeg = _Vastlegger(body={"value": []})
    assert (
        run_rlz_lezen(
            _args(pad="ManualJournals", record_via_filter="ReceiptNumber eq 'X'"),
            zoek=_zoek_een,
            client_factory=lambda _rid: _client_met(leeg),
            uit=io.StringIO(),
        )
        == 2
    )
    assert len(leeg.requests) == 1 and "precies één vereist" in capsys.readouterr().err
    # twee treffers → exit 2
    twee = _Vastlegger(body={"value": [{"id": guid}, {"id": guid}]})
    assert (
        run_rlz_lezen(
            _args(pad="ManualJournals", record_via_filter="Status eq 3"),
            zoek=_zoek_een,
            client_factory=lambda _rid: _client_met(twee),
            uit=io.StringIO(),
        )
        == 2
    )
    # op een recordpad is de vlag zinloos → exit 2 zonder call
    geen = _Vastlegger()
    assert (
        run_rlz_lezen(
            _args(pad=f"ManualJournals/{guid}", record_via_filter="Status eq 3"),
            zoek=_zoek_een,
            client_factory=lambda _rid: _client_met(geen),
            uit=io.StringIO(),
        )
        == 2
    )
    assert geen.requests == []
    # de parser kent de vlag (dispatch via cli.main, zoals test_cli_dispatch_kent_rlz_lezen)
    gezien: list[argparse.Namespace] = []
    import app.cli as app_cli

    origineel = app_cli.run_rlz_lezen
    app_cli.run_rlz_lezen = lambda a: gezien.append(a) or 0  # type: ignore[assignment]
    try:
        assert (
            app_cli.main(
                [
                    "rlz-lezen",
                    "--administratie",
                    "x",
                    "--pad",
                    "ManualJournals",
                    "--record-via-filter",
                    "ReceiptNumber eq 'a'",
                ]
            )
            == 0
        )
    finally:
        app_cli.run_rlz_lezen = origineel  # type: ignore[assignment]
    assert gezien[0].record_via_filter == "ReceiptNumber eq 'a'"


# --- --root: RLZ-brede enumeraties zonder administratie-prefix (STAP-0 activa 16-09) ---------------------------------


def test_root_leest_zonder_administratie_prefix_en_blijft_lees_only() -> None:
    transport = _Vastlegger(body={"value": [{"id": 1, "Name": "Lineair"}]})
    code = run_rlz_lezen(
        _args(pad="AssetTypes", root=True),
        zoek=_zoek_een,
        client_factory=lambda _: _client_met(transport),
        uit=io.StringIO(),
    )
    assert code == 0
    (req,) = transport.requests
    assert req.method == "GET"
    assert RLZ_ADMIN not in str(req.url), "root-vorm: geen administratie-prefix"
    assert str(req.url).startswith("https://rlz.test/api/v1/AssetTypes")


def test_zonder_root_blijft_het_administratie_prefix_staan() -> None:
    transport = _Vastlegger(body={"value": []})
    run_rlz_lezen(_args(pad="AssetTypes"), zoek=_zoek_een, client_factory=lambda _: _client_met(transport), uit=io.StringIO())
    (req,) = transport.requests
    assert f"/{RLZ_ADMIN}/AssetTypes" in str(req.url)


def test_root_client_weigert_schrijven() -> None:
    transport = _Vastlegger()
    with pytest.raises(SchrijfGeweigerd):
        _client_met(transport).root().put("AssetTypes/x", {"id": "x"})
    assert transport.requests == []
