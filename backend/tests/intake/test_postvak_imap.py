"""Live IMAP-postvak (F3.4): de bron levert ongelezen berichten, markeert pas als gelezen
NADAT de verwerking slaagde (crash = retry volgende run), en het CLI-commando verwerkt via
exact hetzelfde idempotente codepad als de .eml-upload — met de systeem-actor, nooit stil."""

from __future__ import annotations

import imaplib
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.intake.postvak import ImapPostvakBron, PostvakFout, PostvakNietGeconfigureerd
from tests.intake.conftest import bouw_eml, bouw_pdf


class FakeImap:
    """Minimale IMAP4_SSL-dubbelganger: twee-tuple-responses zoals imaplib ze teruggeeft."""

    def __init__(self, berichten: dict[bytes, bytes], *, login_geweigerd: bool = False) -> None:
        self.berichten = berichten
        self.login_geweigerd = login_geweigerd
        self.gelezen_gemarkeerd: list[bytes] = []
        self.uitgelogd = False

    def login(self, gebruiker: str, wachtwoord: str):
        if self.login_geweigerd:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return ("OK", [b"Logged in"])

    def select(self, postbus: str):
        return ("OK", [str(len(self.berichten)).encode()])

    def uid(self, commando: str, *args):
        if commando == "SEARCH":
            return ("OK", [b" ".join(self.berichten.keys())])
        if commando == "FETCH":
            uid = args[0]
            return ("OK", [(b"1 (UID %s BODY[] {n}" % uid, self.berichten[uid]), b")"])
        if commando == "STORE":
            self.gelezen_gemarkeerd.append(args[0])
            return ("OK", [])
        raise AssertionError(f"onverwacht IMAP-commando {commando}")

    def logout(self):
        self.uitgelogd = True
        return ("BYE", [b""])


@pytest.fixture
def imap_geconfigureerd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "intake_imap_host", "imap.gmail.com")
    monkeypatch.setattr(settings, "intake_imap_gebruiker", "facturen@ak-nijenhuis.nl")
    monkeypatch.setattr(settings, "intake_imap_wachtwoord", "app-wachtwoord")


def _koppel_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeImap) -> None:
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, poort: fake)


class TestImapPostvakBron:
    def test_zonder_settings_expliciet_niet_geconfigureerd(self) -> None:
        # Dev-default: alle drie leeg — de melding benoemt wat er ontbreekt (geen stille no-op).
        with pytest.raises(PostvakNietGeconfigureerd) as excinfo:
            list(ImapPostvakBron().nieuwe_berichten())
        assert "intake_imap_host" in str(excinfo.value)
        assert "intake_imap_wachtwoord" in str(excinfo.value)

    def test_deels_gevuld_is_ook_niet_geconfigureerd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "intake_imap_host", "imap.gmail.com")
        monkeypatch.setattr(settings, "intake_imap_gebruiker", "facturen@ak-nijenhuis.nl")
        with pytest.raises(PostvakNietGeconfigureerd) as excinfo:
            list(ImapPostvakBron().nieuwe_berichten())
        assert "intake_imap_wachtwoord" in str(excinfo.value)

    def test_levert_ongelezen_berichten_en_markeert_na_verwerking(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeImap({b"11": b"eml-een", b"12": b"eml-twee"})
        _koppel_fake(monkeypatch, fake)

        opgehaald = list(ImapPostvakBron().nieuwe_berichten())

        assert opgehaald == [b"eml-een", b"eml-twee"]
        assert fake.gelezen_gemarkeerd == [b"11", b"12"]
        assert fake.uitgelogd

    def test_crash_tijdens_verwerking_laat_bericht_ongelezen(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # De gelezen-vlag valt pas ná een geslaagde verwerking (generator hervat): crasht de
        # aanroeper op het eerste bericht, dan blijft álles ongelezen en is de volgende
        # scheduler-run de retry — verwerk_eml is idempotent op Message-ID, dus nooit dubbel.
        fake = FakeImap({b"11": b"eml-een", b"12": b"eml-twee"})
        _koppel_fake(monkeypatch, fake)

        with pytest.raises(RuntimeError):
            for _ in ImapPostvakBron().nieuwe_berichten():
                raise RuntimeError("verwerking crasht")

        assert fake.gelezen_gemarkeerd == []
        assert fake.uitgelogd  # de finally ruimt de verbinding wél op

    def test_login_geweigerd_is_zichtbare_fout(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeImap({}, login_geweigerd=True)
        _koppel_fake(monkeypatch, fake)

        with pytest.raises(PostvakFout) as excinfo:
            list(ImapPostvakBron().nieuwe_berichten())
        assert "INTAKE_IMAP_WACHTWOORD" in str(excinfo.value)

    def test_leeg_postvak_is_gewoon_klaar(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeImap({})
        _koppel_fake(monkeypatch, fake)
        assert list(ImapPostvakBron().nieuwe_berichten()) == []


class NepBron:
    def __init__(self, berichten: list[bytes]) -> None:
        self._berichten = berichten

    def nieuwe_berichten(self) -> Iterator[bytes]:
        yield from self._berichten


def _cli_met_bron(monkeypatch: pytest.MonkeyPatch, berichten: list[bytes]) -> int:
    monkeypatch.setattr(cli, "ImapPostvakBron", lambda: NepBron(berichten))
    return cli.main(["intake-postvak-verwerken"])


class TestIntakePostvakVerwerkenCli:
    def test_verwerkt_bericht_idempotent_als_systeem_actor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        admin_engine: Engine,
    ) -> None:
        eml = bouw_eml(
            message_id="<imap-livetest@ak-nijenhuis.nl>",
            bijlagen=[("factuur.pdf", bouw_pdf(), "application", "pdf")],
        )

        exit_code = _cli_met_bron(monkeypatch, [eml])
        uitvoer = capsys.readouterr().out
        assert exit_code == 0
        assert "VERWERKT" in uitvoer
        assert "Postvak verwerkt: 1 nieuw, 0 al eerder verwerkt, 0 ongeldig." in uitvoer

        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT bron, verwerkt_door FROM boekhouding.intake_bericht "
                    "WHERE message_id = :mid"
                ),
                {"mid": "<imap-livetest@ak-nijenhuis.nl>"},
            ).one()
        assert rij.bron == "imap"
        assert rij.verwerkt_door == SYSTEEM_ACTOR_ID

        # Zelfde bericht nogmaals (bv. gelezen-vlag verloren of dubbele aflevering):
        # idempotent op Message-ID, zichtbaar AL-VERWERKT, geen tweede rij.
        exit_code = _cli_met_bron(monkeypatch, [eml])
        uitvoer = capsys.readouterr().out
        assert exit_code == 0
        assert "AL-VERWERKT" in uitvoer
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.intake_bericht WHERE message_id = :mid"),
                {"mid": "<imap-livetest@ak-nijenhuis.nl>"},
            ).scalar_one()
        assert aantal == 1

    def test_ongeldig_bericht_zichtbaar_overgeslagen_rest_verwerkt_exit_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        admin_engine: Engine,
    ) -> None:
        geldig = bouw_eml(message_id="<imap-na-kapot@ak-nijenhuis.nl>")
        exit_code = _cli_met_bron(monkeypatch, [b"dit is geen e-mail", geldig])

        gelezen = capsys.readouterr()
        assert exit_code == 1
        assert "FOUT  ongeldig bericht overgeslagen" in gelezen.err
        assert "Postvak verwerkt: 1 nieuw, 0 al eerder verwerkt, 1 ongeldig." in gelezen.out

    def test_niet_geconfigureerd_exit_1_met_melding(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["intake-postvak-verwerken"])
        assert exit_code == 1
        assert "NIET-GECONFIGUREERD" in capsys.readouterr().err
