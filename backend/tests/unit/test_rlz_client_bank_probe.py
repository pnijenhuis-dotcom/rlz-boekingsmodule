"""Regressietests voor de LastBankImport-versheid-probe (kliktest-fix 2026-08-08).

Live geverifieerd gedrag (api-verkenning.md "LastBankImport per rekeningtype"): RLZ geeft
"geen aanlevering" in drie vormen terug — 404, `400 _InvalidData` (kas/verrekeningen/RC-types
en gearchiveerde rekeningen) en HTTP 200 mét een HTML-pagina i.p.v. JSON (bankrekening die
nooit een import zag). Alle drie moeten None opleveren; élke andere fout blijft een echte
exceptie (de sync-failsafe vangt die zichtbaar op, maar de client mag niets maskeren)."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.rlz.client import RlzApiError, RlzClient

_ACCOUNT_ID = uuid.UUID("33f82534-4a00-4337-854b-aad5cd4fee77")


def _client_met_antwoord(status_code: int, *, tekst: str, content_type: str) -> RlzClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=tekst, headers={"Content-Type": content_type})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://apps.reeleezee.nl/api/v1")
    return RlzClient(username="", password="", client=http)


def test_probe_400_invaliddata_betekent_geen_aanlevering() -> None:
    client = _client_met_antwoord(
        400, tekst='{"Message":"_InvalidData","ExceptionMessage":null}', content_type="application/json"
    )
    assert client.get_last_bank_import(_ACCOUNT_ID) is None


def test_probe_404_betekent_geen_aanlevering() -> None:
    client = _client_met_antwoord(404, tekst="", content_type="application/json")
    assert client.get_last_bank_import(_ACCOUNT_ID) is None


def test_probe_html_pagina_betekent_geen_aanlevering() -> None:
    """Bankrekening zonder ooit een import: HTTP 200 met een HTML-foutpagina als body."""
    client = _client_met_antwoord(200, tekst="<!DOCTYPE html>\r\n<html>…</html>", content_type="text/html")
    assert client.get_last_bank_import(_ACCOUNT_ID) is None


def test_probe_geeft_import_gegevens_terug() -> None:
    client = _client_met_antwoord(
        200, tekst='{"FileName":"x.940","ImportedLines":4}', content_type="application/json"
    )
    assert client.get_last_bank_import(_ACCOUNT_ID) == {"FileName": "x.940", "ImportedLines": 4}


def test_probe_andere_400_blijft_een_fout() -> None:
    client = _client_met_antwoord(400, tekst='{"Message":"iets anders"}', content_type="application/json")
    with pytest.raises(RlzApiError):
        client.get_last_bank_import(_ACCOUNT_ID)
