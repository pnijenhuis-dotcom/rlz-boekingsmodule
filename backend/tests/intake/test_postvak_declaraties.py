"""Tweede intake-kanaal declaraties@ak-nijenhuis.nl (blok 3 bundel 08-09, B3): dezelfde IMAP-bron met eigen
instellingen (INTAKE_DECLARATIES_IMAP_*), het CLI-commando `intake-postvak-verwerken --kanaal declaraties`, en de
kanaal-markering op het intake-bericht (migratie 0126) — geen stille no-op: niet geconfigureerd = zichtbare melding."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.config import settings
from app.intake import verwerking
from app.intake.postvak import ImapInstellingen, ImapPostvakBron, PostvakNietGeconfigureerd
from tests.intake.conftest import bouw_eml, bouw_pdf
from tests.intake.test_postvak_imap import FakeImap, _koppel_fake


@pytest.fixture
def declaraties_geconfigureerd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "intake_declaraties_imap_host", "imap.gmail.com")
    monkeypatch.setattr(settings, "intake_declaraties_imap_gebruiker", "declaraties@ak-nijenhuis.nl")
    monkeypatch.setattr(settings, "intake_declaraties_imap_wachtwoord", "app-wachtwoord")


class TestInstellingenPerKanaal:
    def test_facturen_kanaal_leest_de_bestaande_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "intake_imap_host", "imap.gmail.com")
        monkeypatch.setattr(settings, "intake_imap_gebruiker", "facturen@ak-nijenhuis.nl")
        monkeypatch.setattr(settings, "intake_imap_wachtwoord", "x")
        i = ImapInstellingen.voor_kanaal("facturen")
        assert (i.host, i.gebruiker, i.env_prefix, i.ontbrekend()) == (
            "imap.gmail.com",
            "facturen@ak-nijenhuis.nl",
            "INTAKE_IMAP",
            [],
        )

    def test_declaraties_kanaal_leest_eigen_settings(self, declaraties_geconfigureerd) -> None:
        i = ImapInstellingen.voor_kanaal("declaraties")
        assert i.gebruiker == "declaraties@ak-nijenhuis.nl"
        assert i.env_prefix == "INTAKE_DECLARATIES_IMAP"
        assert i.ontbrekend() == []

    def test_onbekend_kanaal_is_een_fout(self) -> None:
        with pytest.raises(ValueError, match="Onbekend intake-kanaal"):
            ImapInstellingen.voor_kanaal("bonnetjes")

    def test_declaraties_niet_geconfigureerd_meldt_de_eigen_envs(self) -> None:
        # Code-defaults: het declaraties-postvak staat niet ingesteld → zichtbare melding mét de juiste env-namen.
        with pytest.raises(PostvakNietGeconfigureerd) as exc:
            list(ImapPostvakBron("declaraties").nieuwe_berichten())
        assert "declaraties" in str(exc.value)
        assert "INTAKE_DECLARATIES_IMAP_*" in str(exc.value)
        assert "INTAKE_DECLARATIES_IMAP_WACHTWOORD" in str(exc.value)


class TestCliKanaal:
    def test_cli_declaraties_markeert_het_bericht_en_verwerkt_de_bijlage(
        self, declaraties_geconfigureerd, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine, capsys
    ) -> None:
        message_id = f"<decl-{uuid.uuid4()}@test.example>"
        eml = bouw_eml(
            afzender="medewerker@kempengroep.nl",
            onderwerp="Declaratie tankbon",
            message_id=message_id,
            bijlagen=[("tankbon.pdf", bouw_pdf(), "application", "pdf")],
        )
        fake = FakeImap({b"7": eml})
        _koppel_fake(monkeypatch, fake)
        exit_code = cli.main(["intake-postvak-verwerken", "--kanaal", "declaraties"])
        assert exit_code == 0, capsys.readouterr()
        assert fake.gelezen_gemarkeerd == [b"7"]
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT kanaal, bron FROM boekhouding.intake_bericht WHERE message_id = :m"), {"m": message_id}
            ).one()
        assert (rij.kanaal, rij.bron) == ("declaraties", "imap")

    def test_cli_zonder_kanaal_is_facturen(self, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine) -> None:
        monkeypatch.setattr(settings, "intake_imap_host", "imap.gmail.com")
        monkeypatch.setattr(settings, "intake_imap_gebruiker", "facturen@ak-nijenhuis.nl")
        monkeypatch.setattr(settings, "intake_imap_wachtwoord", "x")
        message_id = f"<fact-{uuid.uuid4()}@test.example>"
        eml = bouw_eml(
            afzender="leverancier@voorbeeld.example",
            onderwerp="Factuur",
            message_id=message_id,
            bijlagen=[("factuur.pdf", bouw_pdf(), "application", "pdf")],
        )
        _koppel_fake(monkeypatch, FakeImap({b"1": eml}))
        assert cli.main(["intake-postvak-verwerken"]) == 0
        with admin_engine.connect() as conn:
            kanaal = conn.execute(
                text("SELECT kanaal FROM boekhouding.intake_bericht WHERE message_id = :m"), {"m": message_id}
            ).scalar_one()
        assert kanaal == "facturen"

    def test_cli_declaraties_niet_geconfigureerd_is_exit_1_met_melding(self, capsys) -> None:
        assert cli.main(["intake-postvak-verwerken", "--kanaal", "declaraties"]) == 1
        assert "NIET-GECONFIGUREERD" in capsys.readouterr().err


class TestVerwerkEmlKanaal:
    def test_onbekend_kanaal_wordt_geweigerd(self) -> None:
        eml = bouw_eml(afzender="a@b.example", onderwerp="x", message_id=None, bijlagen=[])
        with pytest.raises(ValueError, match="Onbekend intake-kanaal"):
            verwerking.verwerk_eml(eml, actor_id=uuid.uuid4(), kanaal="bonnetjes")
