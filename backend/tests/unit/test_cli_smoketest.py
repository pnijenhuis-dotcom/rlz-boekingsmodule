"""Job-smoketest (BUG 21-09): `python -m app.cli --smoketest <commando>` parseert het subcommando, pingt de database
en stopt
zonder werk — deploy.yml start er ná de F3-lus élke job één keer mee. De vlag mag NOOIT de echte dispatcher raken."""

from __future__ import annotations

import pytest

from app import cli as app_cli
from app.documenten import boek_wachtrij


def test_smoketest_parseert_pingt_en_doet_geen_werk(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _nooit(**kw):  # noqa: ANN003, ANN202
        raise AssertionError("de smoketest mag de verwerker niet aanroepen")

    monkeypatch.setattr(boek_wachtrij, "verwerk_boek_wachtrij", _nooit)
    assert app_cli.main(["--smoketest", "boek-wachtrij-verwerken"]) == 0
    uit = capsys.readouterr().out
    assert "job-smoketest ok: commando=boek-wachtrij-verwerken" in uit
    assert "database=bereikbaar" in uit and "geen werk uitgevoerd" in uit


@pytest.mark.parametrize(
    "commando",
    [
        "sync-alles",
        "reconciliatie-alles",
        "extractie-wachtrij-verwerken",
        "bewaking-probe",
        "webhook-afleveren",
        "bank-sync-wachtrij",
        "eerste-sync-wachtrij",
        "terugkerend-herbereken-wachtrij",
        "projecten-cijfers-wachtrij",
        "intake-postvak-verwerken",
        "accordeur-herinneringen",
        "nieuwe-facturen-melden",
        "uren-herinneringen",
        "kantoor-digest",
    ],
)
def test_elk_f3_commando_uit_deploy_yml_parseert_onder_de_vlag(
    commando: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exact de CLI-vormen uit de F3-lus van deploy.yml (zonder extra argumenten) — een job-CLI die een verplicht
    argument zou krijgen, strandt hier op argparse en dus ook in de deploy (les 19-09: élke vorm uit het meetrecept
    letterlijk)."""
    assert app_cli.main(["--smoketest", commando]) == 0
    assert f"commando={commando}" in capsys.readouterr().out


def test_onbekend_commando_faalt_op_argparse_ook_met_vlag() -> None:
    with pytest.raises(SystemExit) as exc:
        app_cli.main(["--smoketest", "bestaat-niet"])
    assert exc.value.code == 2


def test_smoketest_meldt_database_onbereikbaar_als_fout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.db import session as db_session

    class _Kapot:
        def connect(self):  # noqa: ANN202
            raise RuntimeError("geen socket")

    monkeypatch.setattr(db_session, "engine", _Kapot())
    assert app_cli.main(["--smoketest", "boek-wachtrij-verwerken"]) == 1
    assert "database onbereikbaar: geen socket" in capsys.readouterr().err
