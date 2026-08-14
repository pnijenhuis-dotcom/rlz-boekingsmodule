"""Cloud-bootstrap-script (scripts/cloud_bootstrap_beheerder.py, GCP_UITROL §F2): failsafes
plus de drie uitkomsten — vers bootstrappen, verse link voor een nog-niet-geactiveerde
Beheerder, en niets-doen bij een al actieve. De service-kern (bootstrap_eerste_beheerder)
heeft zijn eigen tests; hier gaat het om het script-gedrag eromheen."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.auth import service
from app.db.models import Gebruiker, GebruikerStatus, Uitnodiging
from app.db.session import scoped_session

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cloud_bootstrap_beheerder.py"
_spec = importlib.util.spec_from_file_location("cloud_bootstrap_beheerder", _SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

# De failsafe leest alleen de env-var (de engine is in de testrun al aan boekhouding_test
# gebonden door conftest) — een proxy-achtige URL volstaat om de poort langs te komen.
_PROXY_URL = "postgresql+psycopg://boekhouding_app:x@127.0.0.1:5434/boekhouding"


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setenv("APP_DATABASE_URL", _PROXY_URL)
    monkeypatch.setattr("sys.argv", ["cloud_bootstrap_beheerder.py", *argv])
    return script.main()


class TestFailsafes:
    def test_weigert_zonder_expliciete_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("APP_DATABASE_URL", raising=False)
        monkeypatch.setattr("sys.argv", ["cloud_bootstrap_beheerder.py"])
        with pytest.raises(SystemExit, match="FAILSAFE"):
            script.main()

    def test_weigert_de_lokale_pg16_poort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "APP_DATABASE_URL", "postgresql+psycopg://boekhouding_app:x@localhost:5433/boekhouding"
        )
        monkeypatch.setattr("sys.argv", ["cloud_bootstrap_beheerder.py"])
        with pytest.raises(SystemExit, match="5433"):
            script.main()


class TestBootstrapUitkomsten:
    def test_verse_omgeving_maakt_beheerder_en_print_link(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = _run(monkeypatch, "--app-url", "https://voorbeeld.run.app")
        uit = capsys.readouterr().out
        assert exit_code == 0
        assert "https://voorbeeld.run.app/activeren?token=" in uit
        with scoped_session(None) as session:
            beheerder = session.scalars(
                select(Gebruiker).where(Gebruiker.e_mail == script.STANDAARD_EMAIL)
            ).one()
            assert beheerder.status == GebruikerStatus.UITGENODIGD

    def test_herdraai_geeft_verse_link_zolang_niet_geactiveerd(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(monkeypatch) == 0
        capsys.readouterr()
        assert _run(monkeypatch) == 0
        uit = capsys.readouterr().out
        assert "/activeren?token=" in uit
        with scoped_session(None) as session:
            beheerder = session.scalars(
                select(Gebruiker).where(Gebruiker.e_mail == script.STANDAARD_EMAIL)
            ).one()
            aantal = len(
                session.scalars(select(Uitnodiging).where(Uitnodiging.gebruiker_id == beheerder.id)).all()
            )
        assert aantal == 2

    def test_actieve_beheerder_betekent_niets_doen(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], admin_engine
    ) -> None:
        resultaat = service.bootstrap_eerste_beheerder(naam="Peter", e_mail=script.STANDAARD_EMAIL)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.gebruiker SET status = 'actief' WHERE id = :id"),
                {"id": resultaat.gebruiker_id},
            )
        assert _run(monkeypatch) == 0
        uit = capsys.readouterr().out
        assert "niets te doen" in uit
        assert "token=" not in uit
