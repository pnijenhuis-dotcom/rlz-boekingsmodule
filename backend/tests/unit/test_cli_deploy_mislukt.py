"""`deploy-mislukt` (ochtendrun 11-09 blok 2.2): één mail per beheer-ontvanger met sha + run-URL; zonder mailkanaal of
ontvangers exit 1 mét melding (nooit stil groen)."""

from __future__ import annotations

import argparse

import pytest

from app import cli
from app.berichten import mail
from app.config import settings


def _args(**kw: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        commando="deploy-mislukt", sha=kw.get("sha"), run_url=kw.get("run_url"), stap=kw.get("stap")
    )


def test_mailt_elke_beheer_ontvanger(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    verzonden: list[dict] = []
    monkeypatch.setattr(mail, "is_geconfigureerd", lambda: True)
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
    monkeypatch.setattr(settings, "reconciliatie_beheer_ontvangers", "a@x.nl, b@x.nl")
    code = cli._deploy_mislukt(
        _args(sha="58feacb99ff2a691ea41f0b3f2d8426de1c13001", run_url="https://gh/run/181", stap="main")
    )
    assert code == 0 and [v["naar"] for v in verzonden] == ["a@x.nl", "b@x.nl"]
    assert verzonden[0]["onderwerp"] == "⛔ RLZ-deploy mislukt (58feacb)"
    assert "https://gh/run/181" in verzonden[0]["tekst"] and "deploy_drift" in verzonden[0]["tekst"]
    assert "melding verstuurd naar a@x.nl" in capsys.readouterr().out


def test_zonder_mailkanaal_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(mail, "is_geconfigureerd", lambda: False)
    monkeypatch.setattr(settings, "reconciliatie_beheer_ontvangers", "a@x.nl")
    assert cli._deploy_mislukt(_args(sha="abc")) == 1
    assert "mailkanaal niet geconfigureerd" in capsys.readouterr().err


def test_mailfout_exit_1_maar_overige_ontvangers_wel(monkeypatch: pytest.MonkeyPatch) -> None:
    verzonden: list[str] = []

    def verzend(*, naar: str, onderwerp: str, tekst: str) -> None:
        if naar == "kapot@x.nl":
            raise mail.MailFout("smtp weigert")
        verzonden.append(naar)

    monkeypatch.setattr(mail, "is_geconfigureerd", lambda: True)
    monkeypatch.setattr(mail, "verzend_mail", verzend)
    monkeypatch.setattr(settings, "reconciliatie_beheer_ontvangers", "kapot@x.nl,goed@x.nl")
    assert cli._deploy_mislukt(_args(sha="abc")) == 1 and verzonden == ["goed@x.nl"]
