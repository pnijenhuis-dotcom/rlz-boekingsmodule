"""`python -m app.cli sync-alles` — exit-code-gedrag per resultaatsoort (F3, GCP-uitrol).

Een administratie zonder geregistreerde credential (store noch .env) is niet-onboarded, geen
fout: de cloud-seed-testadministratie (SEED-PASSKEYTEST) zou anders de nachtelijke Cloud
Run-job permanent op exit 1 zetten en de F3.2-job-failure-alerting elke nacht laten afgaan.
Zichtbaar blijft het wél (OVERGESLAGEN-regel — niets verdwijnt stil); een échte
credential-/API-fout blijft exit 1.
"""

from __future__ import annotations

import uuid

import pytest

from app import cli
from app.rlz.credentials import GeenRlzCredentials
from app.sync.service import SyncResultaat


def _resultaat() -> SyncResultaat:
    return SyncResultaat(ledgers=3, taxrates=2, vendors=1, projects=0)


def test_niet_onboarded_administratie_is_zichtbaar_overgeslagen_geen_fout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gelukt_id, seed_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        cli.sync_service,
        "sync_alle_administraties",
        lambda: {
            gelukt_id: _resultaat(),
            seed_id: GeenRlzCredentials("Geen credential-prefix geregistreerd voor RLZ-adminId 'SEED-PASSKEYTEST'"),
        },
    )

    exit_code = cli.main(["sync-alles"])

    uitvoer = capsys.readouterr().out
    assert exit_code == 0
    assert f"OVERGESLAGEN {seed_id}" in uitvoer
    assert "1/2 administraties gesynchroniseerd. (1 overgeslagen: geen credential geregistreerd)" in uitvoer


def test_echte_fout_blijft_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    kapot_id = uuid.uuid4()
    monkeypatch.setattr(
        cli.sync_service,
        "sync_alle_administraties",
        lambda: {kapot_id: "RLZ antwoordde 401 op Ledgers (credential ongeldig?)"},
    )

    exit_code = cli.main(["sync-alles"])

    gelezen = capsys.readouterr()
    assert exit_code == 1
    assert f"FOUT  {kapot_id}" in gelezen.err
