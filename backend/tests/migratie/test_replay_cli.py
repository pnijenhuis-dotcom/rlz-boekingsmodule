"""Blok 6 run 2 VGG (12-09): CLI `vgg-replay` — registratie/dispatch, exit-codes (0 groen / 1 rood / 2 invoer),
`--schrijf-concept` = run 3 → exit 2 zonder enige call, `--odoo-rekeningen`, nameting.sh-allowlist + harde weigering.
Geen DB, geen netwerk: administratie-lookup en client worden geïnjecteerd."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest

from app import cli
from app.migratie import cli_replay
from app.migratie.cli_replay import SCHRIJF_CONCEPT_GEWEIGERD, run_vgg_replay
from tests.migratie.test_replay import ADMIN, ODOO_ACCOUNTS, RLZ_ADMIN, NepClient, mini_vgg

REPO = Path(__file__).resolve().parents[3]
NAMETING = REPO / "scripts" / "gcp" / "nameting.sh"


def _args(**kw) -> argparse.Namespace:  # noqa: ANN003
    basis = dict(
        commando="vgg-replay",
        administratie="Vastgoedgroep",
        dry_run=True,
        json_uit=None,
        tot="2026-09-01",
        odoo_rekeningen=None,
        schrijf_concept=False,
    )
    basis.update(kw)
    return argparse.Namespace(**basis)


def _zoek(_: str):  # noqa: ANN202
    return (ADMIN, "Vastgoedgroep Nederland B.V.", RLZ_ADMIN)


def test_schrijf_concept_is_run_3_exit_2_zonder_enige_call(capsys: pytest.CaptureFixture[str]) -> None:
    aangeroepen: list[str] = []
    assert (
        run_vgg_replay(
            _args(schrijf_concept=True),
            zoek=lambda t: aangeroepen.append(t),
            client_factory=lambda r: aangeroepen.append(r),
        )
        == 2
    )
    assert aangeroepen == []
    assert SCHRIJF_CONCEPT_GEWEIGERD in capsys.readouterr().err
    # óók via de echte parser: de weigering komt vóór élke DB-/RLZ-toegang
    assert cli.main(["vgg-replay", "--administratie", "x", "--schrijf-concept"]) == 2


def test_cli_dispatch_kent_vgg_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    aangeroepen: list[argparse.Namespace] = []
    monkeypatch.setattr(cli, "run_vgg_replay", lambda args: aangeroepen.append(args) or 0)
    assert (
        cli.main(["vgg-replay", "--administratie", "Vastgoedgroep", "--tot", "2026-01-31", "--json-uit", "/tmp/x.json"])
        == 0
    )
    a = aangeroepen[0]
    assert a.commando == "vgg-replay" and a.tot == "2026-01-31" and a.json_uit == "/tmp/x.json"
    assert a.dry_run is True and a.schrijf_concept is False and a.odoo_rekeningen is None
    assert cli_replay.VGG_REPLAY_COMMANDO == "vgg-replay"


def test_groen_exit_0_met_odoo_rekeningen_en_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.migratie import test_replay as tr

    collecties, regels, statements = mini_vgg()
    client = NepClient(collecties, regels, statements)
    rek = tmp_path / "company6.json"
    rek.write_text(json.dumps({"accounts": ODOO_ACCOUNTS}), encoding="utf-8")
    uit = tmp_path / "rapport.json"
    # de CLI kent geen --doel/--rollen/--panden: die komen in productie uit D/C/B — hier via de replay-defaults
    monkeypatch.setattr(tr.replay, "laad_doel", lambda _a: (tr.DOEL, None))
    monkeypatch.setattr(tr.vertaling, "laad_rollen", lambda _a: tr.ROLLEN)
    monkeypatch.setattr(tr.vertaling, "laad_panden", lambda _a, **_k: tr.PANDEN)
    code = run_vgg_replay(
        _args(json_uit=str(uit), odoo_rekeningen=str(rek)), zoek=_zoek, client_factory=lambda _r: client
    )
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "**Oordeel: GROEN**" in out.out and f"JSON geschreven: {uit}" in out.out
    assert client.gesloten is True
    data = json.loads(uit.read_text(encoding="utf-8"))
    assert data["groen"] is True and data["administratie_naam"] == "Vastgoedgroep Nederland B.V."
    assert "regels lezen voor 8 geboekte documenten" in out.err  # voortgang naar stderr


def test_rood_exit_1_bij_ongemapte_rekening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.migratie import test_replay as tr

    collecties, regels, statements = mini_vgg()
    rek = tmp_path / "company6.json"
    rek.write_text(json.dumps([a for a in ODOO_ACCOUNTS if a["code"] != "4400"]), encoding="utf-8")
    monkeypatch.setattr(tr.replay, "laad_doel", lambda _a: (tr.DOEL, None))
    monkeypatch.setattr(tr.vertaling, "laad_rollen", lambda _a: tr.ROLLEN)
    monkeypatch.setattr(tr.vertaling, "laad_panden", lambda _a, **_k: tr.PANDEN)
    code = run_vgg_replay(
        _args(odoo_rekeningen=str(rek)), zoek=_zoek, client_factory=lambda _r: NepClient(collecties, regels, statements)
    )
    out = capsys.readouterr()
    assert code == 1 and "ROOD: 0 verschil(len), 1 niet vertaalbaar" in out.err
    assert "**Oordeel: ROOD**" in out.out


@pytest.mark.parametrize(
    ("kw", "melding"),
    [
        ({"tot": "gisteren"}, "--tot 'gisteren' is geen datum"),
        ({"odoo_rekeningen": "/nonexistent/x.json"}, "--odoo-rekeningen"),
        ({"administratie": "onbekend"}, "administratie 'onbekend' onbekend"),
    ],
)
def test_invoerfouten_exit_2(kw: dict, melding: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_vgg_replay(
        _args(**kw), zoek=lambda t: None if t == "onbekend" else _zoek(t), client_factory=lambda _r: None
    )
    assert code == 2 and melding in capsys.readouterr().err


def test_nameting_sh_allowlist_en_weigering() -> None:
    tekst = NAMETING.read_text(encoding="utf-8")
    allow = next(regel for regel in tekst.splitlines() if regel.startswith("ALLOWLIST="))
    assert " vgg-replay" in allow
    assert 'grep -qx -- "--schrijf-concept"' in tekst and "run 3" in tekst
    # gedrag: mét --schrijf-concept exit 2 vóórdat gcloud aangeroepen wordt (stub-gcloud registreert elke aanroep)
    if os.name != "posix":
        pytest.skip("bash-test alleen op posix")
    with pytest.MonkeyPatch.context() as mp:
        stub = Path(os.environ.get("TMPDIR", "/tmp")) / f"vgg_replay_gcloud_stub_{os.getpid()}"
        stub.mkdir(exist_ok=True)
        (stub / "gcloud").write_text("#!/usr/bin/env bash\necho GCLOUD-AANGEROEPEN >&2; exit 0\n", encoding="utf-8")
        (stub / "gcloud").chmod(0o755)
        mp.setenv("PATH", f"{stub}:{os.environ['PATH']}")
        mp.setenv("NAMETING_ENV", str(stub / "ontbreekt.env"))
        r = subprocess.run(
            ["bash", str(NAMETING), "vgg-replay", "--administratie", "Vastgoedgroep", "--schrijf-concept"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 2 and "run 3" in r.stderr and "GCLOUD-AANGEROEPEN" not in r.stderr
        r2 = subprocess.run(["bash", str(NAMETING), "vgg-odoo-stap0"], capture_output=True, text=True, check=False)
        assert r2.returncode == 2 and "GCLOUD-AANGEROEPEN" not in r2.stderr
