# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Live IMAP-postvak (F3.4; herzien 23-09, Peter 22-09 "er zijn facturen gemaild die niet in onze module staan"):
de bron leest ALLE berichten in het venster (gelezen én ongelezen) uit INBOX én de spam-map, haalt eerst alleen de kop
(Message-ID) en slaat over wat al in de verwerkt-administratie staat; de gelezen-vlag wordt pas ná verwerking gezet en
is alleen nog een bijproduct. Het CLI-commando verwerkt via exact hetzelfde idempotente codepad als de .eml-upload —
met de systeem-actor, registreert élk bericht in `intake_bericht_verwerkt` en schrijft één audit per run. Nooit stil."""

from __future__ import annotations

import imaplib
import re
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.intake.postvak import (
    INBOX,
    ImapPostvakBron,
    PostvakFout,
    PostvakNietGeconfigureerd,
    PostvakVerbinding,
    imap_datum,
)
from tests.intake.conftest import bouw_eml, bouw_pdf

SPAM = "[Gmail]/Spam"


class FakeImap:
    """IMAP4_SSL-dubbelganger mét mappen, vlaggen en de twee FETCH-vormen (kop / hele body) zoals imaplib ze teruggeeft.
    `berichten` = {map: {uid(bytes): eml(bytes)}}; `gelezen` = set van (map, uid) die al \\Seen dragen."""

    def __init__(
        self,
        berichten: dict[str, dict[bytes, bytes]] | dict[bytes, bytes],
        *,
        login_geweigerd: bool = False,
        gelezen: set[tuple[str, bytes]] | None = None,
        ontbrekende_mappen: set[str] | None = None,
    ) -> None:
        if berichten and all(isinstance(k, bytes) for k in berichten):
            berichten = {INBOX: berichten}  # oude vorm: alleen INBOX
        self.berichten: dict[str, dict[bytes, bytes]] = {INBOX: {}, SPAM: {}, **berichten}  # type: ignore[dict-item]
        self.login_geweigerd = login_geweigerd
        self.gelezen: set[tuple[str, bytes]] = set(gelezen or set())
        self.ontbrekende_mappen = ontbrekende_mappen or set()
        self.gelezen_gemarkeerd: list[tuple[str, bytes]] = []
        self.gefetcht_body: list[tuple[str, bytes]] = []
        self.zoekopdrachten: list[tuple[str, tuple]] = []
        self.uitgelogd = False
        self._map = INBOX

    def login(self, gebruiker: str, wachtwoord: str):
        if self.login_geweigerd:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return ("OK", [b"Logged in"])

    def select(self, postbus: str):
        naam = postbus.strip('"')
        if naam in self.ontbrekende_mappen:
            return ("NO", [b"[NONEXISTENT] Unknown Mailbox"])
        self._map = naam
        return ("OK", [str(len(self.berichten.get(naam, {}))).encode()])

    def uid(self, commando: str, *args):
        map_ = self._map
        inhoud = self.berichten.get(map_, {})
        if commando == "SEARCH":
            self.zoekopdrachten.append((map_, args[1:]))
            uids = list(inhoud.keys())
            if "UNSEEN" in args:
                uids = [u for u in uids if (map_, u) not in self.gelezen]
            return ("OK", [b" ".join(uids)])
        if commando == "FETCH":
            uid = args[0]
            eml = inhoud[uid]
            if "HEADER.FIELDS" in args[1]:
                kop = eml.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
                velden = [r for r in re.split(rb"\r?\n(?!\s)", kop) if r.split(b":", 1)[0].lower() in (b"message-id", b"from", b"subject", b"date", b"references", b"in-reply-to")]
                header = b"\r\n".join(velden) + b"\r\n\r\n"
                flags = b"(\\Seen)" if (map_, uid) in self.gelezen else b"()"
                return ("OK", [(b"1 (UID %s FLAGS %s BODY[HEADER.FIELDS (...)] {n}" % (uid, flags), header), b")"])
            self.gefetcht_body.append((map_, uid))
            return ("OK", [(b"1 (UID %s BODY[] {n}" % uid, eml), b")"])
        if commando == "STORE":
            self.gelezen_gemarkeerd.append((map_, args[0]))
            self.gelezen.add((map_, args[0]))
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


def _eml(message_id: str, *, afzender: str = "leverancier@voorbeeld.example") -> bytes:
    return bouw_eml(afzender=afzender, message_id=message_id, bijlagen=[("factuur.pdf", bouw_pdf(), "application", "pdf")])


class TestImapDatum:
    def test_rfc3501_notatie_locale_onafhankelijk(self) -> None:
        assert imap_datum(date(2026, 9, 9)) == "09-Sep-2026"
        assert imap_datum(date(2026, 12, 31)) == "31-Dec-2026"


class TestImapPostvakBron:
    def test_zonder_settings_expliciet_niet_geconfigureerd(self) -> None:
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

    def test_leest_gelezen_en_ongelezen_uit_inbox_en_spam_en_markeert_na_verwerking(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Het gat van vóór 23-09: een al-gelezen bericht (uid 11) en een spam-bericht (uid 31) werden nooit gezien.
        fake = FakeImap(
            {INBOX: {b"11": _eml("<a@x>"), b"12": _eml("<b@x>")}, SPAM: {b"31": _eml("<c@x>")}},
            gelezen={(INBOX, b"11")},
        )
        _koppel_fake(monkeypatch, fake)

        bron = ImapPostvakBron(bekend=lambda sleutel: False, sinds=date(2026, 9, 1))
        opgehaald = list(bron.nieuwe_berichten())

        assert [(b.kop.map, b.kop.uid, b.kop.message_id, b.kop.gelezen) for b in opgehaald] == [
            (INBOX, "11", "<a@x>", True),
            (INBOX, "12", "<b@x>", False),
            (SPAM, "31", "<c@x>", False),
        ]
        assert opgehaald[2].uit_spam and not opgehaald[0].uit_spam
        # SEARCH = ALL sinds het venster (géén UNSEEN meer), in beide mappen.
        assert fake.zoekopdrachten == [(INBOX, ("SINCE", "01-Sep-2026")), (SPAM, ("SINCE", "01-Sep-2026"))]
        assert fake.gelezen_gemarkeerd == [(INBOX, b"11"), (INBOX, b"12"), (SPAM, b"31")]
        assert (bron.telling.gezien, bron.telling.gezien_spam, bron.telling.opgehaald) == (3, 1, 3)
        assert fake.uitgelogd

    def test_bekende_berichten_worden_op_de_kop_overgeslagen_zonder_body_fetch(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeImap({INBOX: {b"11": _eml("<bekend@x>"), b"12": _eml("<nieuw@x>")}})
        _koppel_fake(monkeypatch, fake)

        bron = ImapPostvakBron(bekend=lambda sleutel: sleutel == "<bekend@x>")
        opgehaald = list(bron.nieuwe_berichten())

        assert [b.sleutel for b in opgehaald] == ["<nieuw@x>"]
        assert fake.gefetcht_body == [(INBOX, b"12")]  # de body van het bekende bericht is nooit opgehaald
        assert fake.gelezen_gemarkeerd == [(INBOX, b"12")]  # en zijn vlag blijft zoals de mens 'm liet
        assert bron.telling.overgeslagen_bekend == 1

    def test_zonder_message_id_is_de_sleutel_map_plus_uid(self, imap_geconfigureerd: None, monkeypatch) -> None:
        eml = bouw_eml(message_id="<weg@x>").replace(b"Message-ID: <weg@x>\r\n", b"").replace(b"Message-ID: <weg@x>\n", b"")
        assert b"Message-ID" not in eml
        fake = FakeImap({INBOX: {b"7": eml}})
        _koppel_fake(monkeypatch, fake)
        [b] = list(ImapPostvakBron(bekend=lambda s: False).nieuwe_berichten())
        assert b.kop.message_id is None and b.sleutel == "uid:INBOX:7"

    def test_crash_tijdens_verwerking_laat_bericht_ongelezen(
        self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeImap({b"11": _eml("<a@x>"), b"12": _eml("<b@x>")})
        _koppel_fake(monkeypatch, fake)

        with pytest.raises(RuntimeError):
            for _ in ImapPostvakBron(bekend=lambda s: False).nieuwe_berichten():
                raise RuntimeError("verwerking crasht")

        assert fake.gelezen_gemarkeerd == []
        assert fake.uitgelogd  # de finally ruimt de verbinding wél op

    def test_login_geweigerd_is_zichtbare_fout(self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeImap({}, login_geweigerd=True)
        _koppel_fake(monkeypatch, fake)
        with pytest.raises(PostvakFout) as excinfo:
            list(ImapPostvakBron().nieuwe_berichten())
        assert "INTAKE_IMAP_WACHTWOORD" in str(excinfo.value)

    def test_spam_map_die_ontbreekt_is_een_fout_nooit_stil(self, imap_geconfigureerd: None, monkeypatch) -> None:
        # Een spam-map die stil ontbreekt zou precies het gat van vóór 23-09 terugbrengen.
        fake = FakeImap({INBOX: {b"11": _eml("<a@x>")}}, ontbrekende_mappen={SPAM})
        _koppel_fake(monkeypatch, fake)
        with pytest.raises(PostvakFout, match=r"SELECT \[Gmail\]/Spam"):
            list(ImapPostvakBron(bekend=lambda s: False).nieuwe_berichten())

    def test_leeg_postvak_is_gewoon_klaar(self, imap_geconfigureerd: None, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeImap({})
        _koppel_fake(monkeypatch, fake)
        assert list(ImapPostvakBron(bekend=lambda s: False).nieuwe_berichten()) == []

    def test_standaard_venster_is_vandaag_min_venster_dagen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "intake_postvak_venster_dagen", 14)
        bron = ImapPostvakBron()
        assert (datetime.now(UTC).date() - bron.venster_vanaf()).days == 14
        assert PostvakVerbinding.standaard_mappen() == (INBOX, SPAM)


def _cli(monkeypatch: pytest.MonkeyPatch, fake: FakeImap, *argv: str) -> int:
    _koppel_fake(monkeypatch, fake)
    return cli.main(["intake-postvak-verwerken", *argv])


class TestIntakePostvakVerwerkenCli:
    def test_verwerkt_bericht_registreert_op_message_id_en_slaat_tweede_run_over(
        self,
        imap_geconfigureerd: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        admin_engine: Engine,
    ) -> None:
        mid = f"<imap-livetest-{uuid.uuid4()}@ak-nijenhuis.nl>"
        fake = FakeImap({INBOX: {b"5": _eml(mid)}})

        assert _cli(monkeypatch, fake) == 0
        uitvoer = capsys.readouterr().out
        assert "VERWERKT" in uitvoer
        assert "Postvak verwerkt (facturen): 1 nieuw, 0 al eerder verwerkt, 0 ongeldig; 1 in het venster gezien" in uitvoer

        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT bron, verwerkt_door, kanaal FROM boekhouding.intake_bericht WHERE message_id = :mid"),
                {"mid": mid},
            ).one()
            verwerkt = conn.execute(
                text(
                    "SELECT kanaal, uid, postvak_map, uitkomst, intake_bericht_id IS NOT NULL AS gekoppeld "
                    "FROM boekhouding.intake_bericht_verwerkt WHERE message_id = :mid"
                ),
                {"mid": mid},
            ).one()
            audit = conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'intake_postvak_run' ORDER BY tijdstip DESC LIMIT 1")
            ).scalar_one()
        assert (rij.bron, rij.verwerkt_door, rij.kanaal) == ("imap", SYSTEEM_ACTOR_ID, "facturen")
        assert tuple(verwerkt) == ("facturen", "5", INBOX, "verwerkt", True)
        assert audit["kanaal"] == "facturen" and audit["verwerkt"] == 1 and audit["gezien"] == 1

        # Tweede run: het bericht staat in de verwerkt-administratie → op de kop overgeslagen, body nooit opgehaald,
        # ook al zou een mens de gelezen-vlag intussen weggehaald hebben.
        fake.gelezen.clear()
        fake.gefetcht_body.clear()
        assert _cli(monkeypatch, fake) == 0
        uitvoer = capsys.readouterr().out
        assert "0 nieuw, 0 al eerder verwerkt, 0 ongeldig; 1 in het venster gezien (0 in spam), 1 al bekend overgeslagen" in uitvoer
        assert fake.gefetcht_body == []
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.intake_bericht WHERE message_id = :mid"), {"mid": mid}
            ).scalar_one()
        assert aantal == 1

    def test_al_gelezen_bericht_wordt_alsnog_verwerkt(self, imap_geconfigureerd, monkeypatch, admin_engine, capsys) -> None:
        # Peter 22-09: "een mens die de mailbox open heeft zet berichten op gelezen vóór de intake ze ziet" — was verlies.
        mid = f"<gelezen-{uuid.uuid4()}@x>"
        fake = FakeImap({INBOX: {b"9": _eml(mid)}}, gelezen={(INBOX, b"9")})
        assert _cli(monkeypatch, fake) == 0
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text("SELECT detail FROM boekhouding.intake_bericht_verwerkt WHERE message_id = :m"), {"m": mid}
            ).scalar_one()
        assert detail["gelezen_vooraf"] is True

    def test_spam_bericht_verwerkt_met_markering(self, imap_geconfigureerd, monkeypatch, admin_engine, capsys) -> None:
        mid = f"<spam-{uuid.uuid4()}@x>"
        fake = FakeImap({SPAM: {b"41": _eml(mid, afzender="facturen@strikte-dmarc.example")}})
        assert _cli(monkeypatch, fake) == 0
        uit = capsys.readouterr().out
        assert "[SPAM]" in uit and "1 uit spam verwerkt" in uit
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT v.postvak_map, b.detail->>'postvak_map' AS bericht_map FROM boekhouding.intake_bericht_verwerkt v "
                    "JOIN boekhouding.intake_bericht b ON b.id = v.intake_bericht_id WHERE v.message_id = :m"
                ),
                {"m": mid},
            ).one()
        assert (rij.postvak_map, rij.bericht_map) == (SPAM, SPAM)

    def test_ongeldig_bericht_geregistreerd_als_niet_verwerkbaar_rest_verwerkt_exit_1(
        self, imap_geconfigureerd, monkeypatch, capsys, admin_engine
    ) -> None:
        geldig = _eml(f"<imap-na-kapot-{uuid.uuid4()}@x>")
        fake = FakeImap({INBOX: {b"1": b"dit is geen e-mail", b"2": geldig}})
        exit_code = _cli(monkeypatch, fake)
        gelezen = capsys.readouterr()
        assert exit_code == 1
        assert "NIET-VERWERKBAAR uid:INBOX:1" in gelezen.err
        assert "1 nieuw, 0 al eerder verwerkt, 1 ongeldig" in gelezen.out
        with admin_engine.connect() as conn:
            uitkomst = conn.execute(
                text("SELECT uitkomst FROM boekhouding.intake_bericht_verwerkt WHERE message_id = 'uid:INBOX:1'")
            ).scalar_one()
        assert uitkomst == "niet_verwerkbaar"
        # Volgende run: het kapotte bericht is bekend → geen eeuwige retry-lus, geen tweede FOUT.
        assert _cli(monkeypatch, fake) == 0

    def test_sinds_overschrijft_het_venster_voor_de_herstelrun(self, imap_geconfigureerd, monkeypatch, capsys) -> None:
        fake = FakeImap({})
        assert _cli(monkeypatch, fake, "--sinds", "2026-07-01") == 0
        assert "venster vanaf 2026-07-01" in capsys.readouterr().out
        assert fake.zoekopdrachten[0] == (INBOX, ("SINCE", "01-Jul-2026"))

    def test_niet_geconfigureerd_exit_1_met_melding(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["intake-postvak-verwerken"]) == 1
        assert "NIET-GECONFIGUREERD" in capsys.readouterr().err
