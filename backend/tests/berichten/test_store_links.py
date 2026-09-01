"""Store-link-nazorg (blok F nachtrun 01/02-09): settings STORE_LINK_IOS/ANDROID default leeg = exact het
huidige gedrag (geen spoor in mail of config); gevuld = blok "Download eerst de app" in de uitnodigingsmail
voor app-rollen (nooit voor kantoorrollen) en de links op de publieke config-route, per platform alleen als
zijn link gevuld is."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.berichten import mail, uitnodigingsmail
from app.config import settings
from app.main import app

client = TestClient(app)


def _vang(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    mails: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: mails.append(kw))
    return mails


class TestMail:
    def test_leeg_geen_spoor_ook_niet_voor_app_rol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mails = _vang(monkeypatch)
        uitnodigingsmail.verstuur_uitnodigingsmail(naam="Milan", e_mail="m@x.nl", token="t", verloopt_op=datetime.now(UTC), app_rol=True)
        assert "Download" not in mails[0]["tekst"] and "apps.apple.com" not in mails[0]["tekst"]
        assert uitnodigingsmail.download_blok() == ""

    def test_gevuld_alleen_voor_app_rol_en_alleen_gevulde_platformen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        monkeypatch.setattr(settings, "store_link_android", "")
        mails = _vang(monkeypatch)
        uitnodigingsmail.verstuur_uitnodigingsmail(naam="Milan", e_mail="m@x.nl", token="t", verloopt_op=datetime.now(UTC), app_rol=True)
        tekst = mails[0]["tekst"]
        assert "Download eerst de app" in tekst and "https://apps.apple.com/nl/app/id123" in tekst
        assert "Google Play" not in tekst
        # De activatielink blijft erná staan — het blok gaat ervoor.
        assert tekst.index("Download eerst de app") < tekst.index("/activeren?token=")
        uitnodigingsmail.verstuur_uitnodigingsmail(naam="Demi", e_mail="d@x.nl", token="t2", verloopt_op=datetime.now(UTC), app_rol=False)
        assert "Download" not in mails[1]["tekst"]

    def test_beide_platformen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_link_ios", " https://apps.apple.com/x ")
        monkeypatch.setattr(settings, "store_link_android", "https://play.google.com/y")
        assert uitnodigingsmail.store_links() == [
            ("iPhone/iPad (App Store)", "https://apps.apple.com/x"),
            ("Android (Google Play)", "https://play.google.com/y"),
        ]


class TestConfigRoute:
    def test_leeg_is_null(self) -> None:
        body = client.get("/auth/webauthn/config").json()
        assert body["store_link_ios"] is None and body["store_link_android"] is None

    def test_gevuld_komt_mee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_link_android", "https://play.google.com/y")
        body = client.get("/auth/webauthn/config").json()
        assert body["store_link_ios"] is None and body["store_link_android"] == "https://play.google.com/y"
