"""Guard op de VORM van de uitnodigingsmail voor app-rollen (Peter 16-09, accordeur-uitnodiging web vs app, blok C):
één genummerde volgorde — 1 installeer de app (store-link alleen als de store-versie de app-auth draagt, anders de
TestFlight-/interne-track-instructie), 2 open déze link op je telefoon, 3 kies een toegangscode — de activatiecode als
terugval eronder, de tekst over "per ongeluk op een computer" en het zelf koppelen van een tweede toestel. Kantoor-mail
ongewijzigd."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.berichten import mail, uitnodigingsmail
from app.config import settings


def _vang(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    mails: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: mails.append(kw))
    return mails


def _app_mail(monkeypatch: pytest.MonkeyPatch) -> str:
    mails = _vang(monkeypatch)
    uitnodigingsmail.verstuur_uitnodigingsmail(
        naam="Sophia",
        e_mail="s@x.nl",
        token="t0k",
        verloopt_op=datetime.now(UTC),
        app_rol=True,
        activatiecode="ABCD-EFGH",
    )
    return mails[0]["tekst"]


class TestVolgorde:
    def test_drie_genummerde_stappen_in_volgorde_met_code_als_terugval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tekst = _app_mail(monkeypatch)
        i1, i2, i3 = (
            tekst.index("1. "),
            tekst.index("2. Open déze link op je telefoon"),
            tekst.index("3. Kies in de app een toegangscode"),
        )
        assert i1 < i2 < i3
        # de link staat in stap 2, de code als terugval ná stap 3
        assert i2 < tekst.index("/activeren?token=t0k") < i3
        assert i3 < tekst.index("activatiecode in: ABCD-EFGH")
        assert "niet op een computer" in tekst and "eenmalig" in tekst
        assert "Opende je de link per ongeluk op een computer" in tekst and "niets vastgelegd" in tekst
        assert "'Telefoon/app koppelen'" in tekst
        # bestaande garanties blijven: op een ander toestel / zelfde geldigheid (test_app_activatie leunt erop)
        assert "op een ander toestel" in tekst and "zelfde geldigheid" in tekst

    def test_kantoor_mail_ongewijzigd_zonder_stappen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mails = _vang(monkeypatch)
        uitnodigingsmail.verstuur_uitnodigingsmail(
            naam="Kantoor", e_mail="k@x.nl", token="t1", verloopt_op=datetime.now(UTC)
        )
        tekst = mails[0]["tekst"]
        assert "Activeer je account via deze link" in tekst and "1. " not in tekst and "toegangscode" not in tekst


class TestStoreVersiePoort:
    def test_ios_store_1_0_geeft_testflight_instructie_geen_app_store_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        assert (
            settings.store_app_versie_ios == "1.0" and settings.store_min_appauth_versie == "1.1"
        )  # code-default 16-09
        tekst = _app_mail(monkeypatch)
        assert "apps.apple.com" not in tekst
        assert "TestFlight" in tekst and "werkt nog met een wachtwoord" in tekst
        assert not uitnodigingsmail.store_versie_geschikt("ios")

    def test_store_versie_1_1_geeft_de_link(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        monkeypatch.setattr(settings, "store_app_versie_ios", "1.1")
        tekst = _app_mail(monkeypatch)
        assert "1. Download eerst de app op je telefoon" in tekst and "https://apps.apple.com/nl/app/id123" in tekst
        assert "TestFlight" not in tekst
        assert uitnodigingsmail.store_versie_geschikt("ios")

    def test_versievergelijking_numeriek(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_app_versie_ios", "1.10")
        assert uitnodigingsmail.store_versie_geschikt("ios")  # 1.10 > 1.1 (numeriek, niet lexicaal)
        monkeypatch.setattr(settings, "store_app_versie_ios", "2.0.3")
        assert uitnodigingsmail.store_versie_geschikt("ios")
        monkeypatch.setattr(settings, "store_app_versie_ios", "")
        assert not uitnodigingsmail.store_versie_geschikt("ios")
        assert not uitnodigingsmail.store_versie_geschikt("android")  # geen listing

    def test_zonder_enige_listing_neutrale_regel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tekst = _app_mail(monkeypatch)
        assert "1. Installeer de app op je telefoon (het kantoor stuurt je de installatielink)." in tekst
        assert "Download" not in tekst and "TestFlight" not in tekst

    def test_herstelmail_volgt_dezelfde_poort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        mails = _vang(monkeypatch)
        uitnodigingsmail.verstuur_herstelmail(
            naam="S", e_mail="s@x.nl", token="t", verloopt_op=datetime.now(UTC), activatiecode="ABCD-EFGH"
        )
        assert "apps.apple.com" not in mails[0]["tekst"] and "TestFlight" in mails[0]["tekst"]


class TestHerstelmailVolgorde:
    """Casus Romy 17-09: de herstelmail = dezelfde genummerde volgorde als de uitnodiging (1 installeer/update mét de
    versie-eis, 2 link op je telefoon — koppelt het toestel opnieuw, 3 nieuwe toegangscode) + activatiecode-blok."""

    def _herstel(self, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        monkeypatch.setattr(settings, "store_app_versie_ios", "1.1")
        mails = _vang(monkeypatch)
        uitnodigingsmail.verstuur_herstelmail(
            naam="Romy", e_mail="r@x.nl", token="t0k", verloopt_op=datetime.now(UTC), activatiecode="ABCD-EFGH"
        )
        return mails[0]["tekst"]

    def test_drie_stappen_store_link_versie_eis_en_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tekst = self._herstel(monkeypatch)
        i1, i2, i3 = tekst.index("1. "), tekst.index("2. "), tekst.index("3. ")
        assert i1 < i2 < i3
        assert "Zo koppel je de app opnieuw" in tekst
        assert "https://apps.apple.com/nl/app/id123" in tekst
        assert "versie 1.1 of hoger nodig" in tekst and "Update 'm dan eerst via de App Store —" in tekst
        assert "koppelt opnieuw het toestel" in tekst and "/activeren?token=t0k&herstel=1" in tekst
        assert "nieuwe toegangscode van 5 cijfers" in tekst
        assert "activatiecode in: ABCD-EFGH" in tekst
        assert "eerdere toestellen worden uitgelogd" in tekst
        # volgorde: store-link (stap 1) vóór de link (stap 2) vóór de code
        assert tekst.index("apps.apple.com") < tekst.index("/activeren?token=") < tekst.index("ABCD-EFGH")

    def test_uitnodiging_draagt_de_versie_eis_ook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/nl/app/id123")
        monkeypatch.setattr(settings, "store_app_versie_ios", "1.1")
        tekst = _app_mail(monkeypatch)
        assert "1. Download eerst de app op je telefoon" in tekst and "versie 1.1 of hoger nodig" in tekst
