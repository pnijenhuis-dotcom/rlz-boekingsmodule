"""Blok 7b 13-09 (punt 1b): token-bucket-tempo + webfilter-backoff in de gedeelde `RlzClient`.

Aanleiding: de productienameting 13-09 kreeg ná ~700 losse regel-calls `403` + HTML "Access Denied" (RLZ-webfilter)
op élke route. Puur getest: bucket laat `burst` calls direct door en slaapt daarna 1/cps; webfilter-403 wordt herkend
(HTML-body, niet RLZ's JSON-403), `rlz_webfilter_pogingen`× herhaald met verdubbelende wachttijd en daarna als
`RlzWebfilterError` opgeworpen; `for_administration` deelt de bucket; een gewone 403 blijft `RlzApiError` zonder
retry."""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.rlz import client as rlz_client
from app.rlz.client import RlzApiError, RlzClient, RlzWebfilterError, Tempo, is_webfilter_antwoord

HTML_403 = (
    "<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n<H1>Access Denied</H1>\nYou don't have permission"
)


class Klok:
    def __init__(self) -> None:
        self.t = 1000.0
        self.geslapen: list[float] = []

    def __call__(self) -> float:
        return self.t

    def slaap(self, s: float) -> None:
        self.geslapen.append(s)
        self.t += s


class TestTempo:
    def test_burst_direct_daarna_een_per_interval(self) -> None:
        klok = Klok()
        tempo = Tempo(2.0, 3, slaap=klok.slaap, klok=klok)
        for _ in range(3):
            tempo.wacht()
        assert klok.geslapen == [] and tempo.calls == 3
        tempo.wacht()  # vierde: bucket leeg → wacht 1/cps = 0,5 s
        assert klok.geslapen == [pytest.approx(0.5)] and tempo.calls == 4
        assert tempo.gewacht_seconden == pytest.approx(0.5)

    def test_nul_is_uit(self) -> None:
        klok = Klok()
        tempo = Tempo(0, 1, slaap=klok.slaap, klok=klok)
        for _ in range(50):
            tempo.wacht()
        assert klok.geslapen == [] and tempo.calls == 50

    def test_defaults_uit_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "rlz_max_calls_per_seconde", 7.0)
        monkeypatch.setattr(settings, "rlz_burst_calls", 9)
        tempo = Tempo()
        assert (tempo.calls_per_seconde, tempo.burst) == (7.0, 9)


class TestWebfilter:
    def test_herkenning_html_403_niet_json_403(self) -> None:
        assert is_webfilter_antwoord(403, HTML_403)
        assert is_webfilter_antwoord(403, "<!DOCTYPE html><html>…")
        assert not is_webfilter_antwoord(403, '{"error": {"code": "Forbidden"}}')
        assert not is_webfilter_antwoord(200, HTML_403)

    def _client(self, antwoorden: list[httpx.Response], slaap: list[float]) -> RlzClient:
        def handler(request: httpx.Request) -> httpx.Response:
            return antwoorden.pop(0)

        http = httpx.Client(base_url="https://rlz.test/api/v1", transport=httpx.MockTransport(handler))
        klok = Klok()
        tempo = Tempo(0, 1, slaap=klok.slaap, klok=klok)
        return RlzClient(username="u", password="p", admin_id="A", client=http, tempo=tempo)

    def test_webfilter_backoff_en_dan_fout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "rlz_webfilter_pogingen", 3)
        monkeypatch.setattr(settings, "rlz_webfilter_backoff_seconden", 20.0)
        gewacht: list[float] = []
        monkeypatch.setattr(rlz_client.time, "sleep", lambda s: gewacht.append(s))
        client = self._client([httpx.Response(403, text=HTML_403) for _ in range(3)], gewacht)
        with pytest.raises(RlzWebfilterError):
            client.get("Ledgers")
        assert gewacht == [20.0, 40.0]  # 3 pogingen, verdubbelend
        assert client.tempo.webfilter_treffers == 3 and client.tempo.calls == 3

    def test_webfilter_hervat_waar_gebleven(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "rlz_webfilter_pogingen", 3)
        gewacht: list[float] = []
        monkeypatch.setattr(rlz_client.time, "sleep", lambda s: gewacht.append(s))
        client = self._client(
            [httpx.Response(403, text=HTML_403), httpx.Response(200, json={"value": [{"id": "x"}]})], gewacht
        )
        assert client.get("Ledgers") == {"value": [{"id": "x"}]}
        assert len(gewacht) == 1 and client.tempo.webfilter_treffers == 1

    def test_gewone_403_geen_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gewacht: list[float] = []
        monkeypatch.setattr(rlz_client.time, "sleep", lambda s: gewacht.append(s))
        client = self._client([httpx.Response(403, json={"error": "geen recht"})], gewacht)
        with pytest.raises(RlzApiError) as exc:
            client.get("Ledgers")
        assert not isinstance(exc.value, RlzWebfilterError) and gewacht == []

    def test_for_administration_deelt_de_bucket(self) -> None:
        http = httpx.Client(
            base_url="https://rlz.test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        )
        client = RlzClient(username="u", password="p", client=http)
        ander = client.for_administration("B")
        assert ander.tempo is client.tempo
