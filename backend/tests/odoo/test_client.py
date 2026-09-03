"""OdooClient-transport (httpx.MockTransport): company-context op élke call, read-only-poort, foutparsing,
geen secret in de foutmelding."""

from __future__ import annotations

import json

import httpx
import pytest

from app.odoo.client import OdooAlleenLezen, OdooClient, OdooFout


def _client(handler, **kw) -> OdooClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="https://odoo.test", transport=transport, headers={"Authorization": "bearer GEHEIM-123"}
    )
    return OdooClient(
        url="https://odoo.test", api_key="GEHEIM-123", company_id=3, client=http, min_tussenpoos_s=0, **kw
    )


def test_call_draagt_company_context_en_benoemde_argumenten() -> None:
    gezien: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        gezien.append({"pad": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(200, json=[{"id": 1, "name": "x"}])

    c = _client(handler)
    rijen = c.search_read("res.partner", [["id", "=", 1]], ["name"], limit=5, order="name")
    assert rijen == [{"id": 1, "name": "x"}]
    assert gezien[0]["pad"] == "/json/2/res.partner/search_read"
    body = gezien[0]["body"]
    assert body["context"]["allowed_company_ids"] == [3]
    assert body["domain"] == [["id", "=", 1]] and body["fields"] == ["name"] and body["limit"] == 5
    # eigen context wint niet van de company-poort maar wordt wél samengevoegd
    c.call("res.partner", "search_read", domain=[], fields=["name"], context={"lang": "nl_NL"})
    assert gezien[1]["body"]["context"] == {"allowed_company_ids": [3], "lang": "nl_NL"}


def test_read_only_client_weigert_schrijfmethoden_voor_de_call() -> None:
    aangeroepen = []

    def handler(request: httpx.Request) -> httpx.Response:
        aangeroepen.append(request.url.path)
        return httpx.Response(200, json=[1])

    c = _client(handler, read_only=True)
    with pytest.raises(OdooAlleenLezen):
        c.create("account.move", {"x": 1})
    with pytest.raises(OdooAlleenLezen):
        c.call("account.move", "action_post", ids=[1])
    assert aangeroepen == []
    assert c.search_read("account.move", [], ["name"]) == [1]


def test_fout_parsing_422_user_error_zonder_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "name": "odoo.exceptions.UserError",
                "message": "De boeking is niet in balans.",
                "debug": "Traceback…",
            },
        )

    c = _client(handler)
    with pytest.raises(OdooFout) as exc:
        c.create("account.move", {"line_ids": []})
    fout = exc.value
    assert fout.status == 422 and fout.naam == "odoo.exceptions.UserError"
    assert "niet in balans" in fout.melding
    assert "GEHEIM" not in str(fout)


def test_create_geeft_int_id_en_read_een_geeft_none_bij_lege_lijst() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/create"):
            return httpx.Response(200, json=[3049])
        return httpx.Response(200, json=[])

    c = _client(handler)
    assert c.create("account.move", {"a": 1}) == 3049
    assert c.read_een("account.move", 999, ["name"]) is None


def test_5xx_wordt_herhaald_en_daarna_odoo_fout() -> None:
    pogingen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        pogingen["n"] += 1
        return httpx.Response(503, text="upstream")

    c = _client(handler)
    c._post.retry.wait = lambda *_a, **_k: 0  # type: ignore[attr-defined]
    with pytest.raises(OdooFout) as exc:
        c.search_count("account.move", [])
    assert exc.value.status == 503
    assert pogingen["n"] == 4
