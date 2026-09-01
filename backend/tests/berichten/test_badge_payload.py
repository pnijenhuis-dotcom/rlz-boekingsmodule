"""Badge-count app-icoon (D4, 01-09): het aantal openstaande accorderingen reist mee in élke push-payload
— APNs `aps.badge`, FCM `notification_count` + data; web push in de payload — en de aanroepers zetten 'm."""

from __future__ import annotations

import uuid

import pytest

from app.berichten import apns, fcm, push
from app.berichten.models import PushSoort, PushSubscriptie


def _sub(soort: str) -> PushSubscriptie:
    return PushSubscriptie(id=uuid.uuid4(), gebruiker_id=uuid.uuid4(), soort=soort, endpoint="tok", p256dh="p", auth="a")


class TestBadgeHelper:
    def test_alleen_echte_ints(self) -> None:
        assert push._badge({"badge": 3}) == 3
        assert push._badge({"badge": 0}) == 0
        assert push._badge({"badge": True}) is None
        assert push._badge({"badge": "3"}) is None
        assert push._badge({}) is None


class TestAdapterKrijgtBadge:
    def test_apns_en_fcm_krijgen_badge_uit_de_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gezien: dict[str, int | None] = {}
        monkeypatch.setattr(apns, "verzend_apns", lambda token, **kw: gezien.__setitem__("apns", kw.get("badge")))
        monkeypatch.setattr(fcm, "verzend_fcm", lambda token, **kw: gezien.__setitem__("fcm", kw.get("badge")))
        push.verzend_push(_sub(PushSoort.APNS.value), payload={"titel": "t", "tekst": "x", "url": "/accordeur", "badge": 4})
        push.verzend_push(_sub(PushSoort.FCM.value), payload={"titel": "t", "tekst": "x", "url": "/accordeur"})
        assert gezien == {"apns": 4, "fcm": None}


class TestPayloadOpbouw:
    def test_apns_payload_draagt_aps_badge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        verzonden: dict = {}

        class _Antwoord:
            status_code = 200

        class _Client:
            def __init__(self, **kw): ...
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, url, *, content, headers):
                verzonden["body"] = json.loads(content)
                return _Antwoord()

        import httpx

        monkeypatch.setattr(httpx, "Client", _Client)
        monkeypatch.setattr(apns, "is_geconfigureerd", lambda: True)
        monkeypatch.setattr(apns, "_maak_jwt", lambda: "jwt")
        apns.verzend_apns("tok", titel="t", tekst="x", url="/accordeur", badge=2)
        assert verzonden["body"]["aps"]["badge"] == 2
        apns.verzend_apns("tok", titel="t", tekst="x", url="/accordeur")
        assert "badge" not in verzonden["body"]["aps"]

    def test_fcm_payload_draagt_notification_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        verzonden: dict = {}

        class _Antwoord:
            status_code = 200

        import httpx

        monkeypatch.setattr(httpx, "post", lambda url, *, json, headers, timeout: verzonden.update(json) or _Antwoord())
        monkeypatch.setattr(fcm, "is_geconfigureerd", lambda: True)
        monkeypatch.setattr(fcm, "_access_token", lambda: ("tok", "proj"))
        fcm.verzend_fcm("tok", titel="t", tekst="x", url="/accordeur", badge=5)
        assert verzonden["message"]["android"]["notification"]["notification_count"] == 5
        assert verzonden["message"]["data"]["badge"] == "5"
