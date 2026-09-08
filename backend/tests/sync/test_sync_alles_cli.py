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


# --- BLOK 1 (bundel 08-09): bank-sync in sync-alles -----------------------------------------------------------


def test_sync_alles_draait_bank_sync_en_rapporteert_per_administratie(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """De nachtelijke lus neemt de bank-sync mee: OK / OVERGESLAGEN (geen RLZ-verbinding, geen fout) / FOUT (exit 1)."""
    from app.bank import sync_run as bank_sync_run

    ok_id, odoo_id, kapot_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(cli.sync_service, "sync_alle_administraties", lambda: {ok_id: _resultaat()})
    monkeypatch.setattr(
        bank_sync_run,
        "sync_alle_via_runs",
        lambda: {
            ok_id: bank_sync_run.BankSyncRunInfo(
                run_id=uuid.uuid4(), status="klaar", overgeslagen=False, laatste_sync_op=None,
                resultaat={"bron": "sync_alles", "mutaties_nieuw": 12, "mutaties_bijgewerkt": 3, "fouten": []},
            ),
            odoo_id: bank_sync_run.BankSyncOvergeslagen("odoo_administratie", "Odoo-administratie — bank loopt niet via Reeleezee"),
            kapot_id: bank_sync_run.BankSyncRunInfo(
                run_id=uuid.uuid4(), status="fout", overgeslagen=False, laatste_sync_op=None, fout_reden="RlzApiError: 503"
            ),
        },
    )
    exit_code = cli.main(["sync-alles"])
    gelezen = capsys.readouterr()
    assert exit_code == 1  # de fout-run maakt de job zichtbaar rood
    assert "Bank-sync (alle actieve administraties):" in gelezen.out
    assert f"OK    bank-sync {ok_id}: mutaties_nieuw=12, mutaties_bijgewerkt=3" in gelezen.out
    assert f"OVERGESLAGEN bank-sync {odoo_id}: odoo_administratie" in gelezen.out
    assert f"FOUT  bank-sync {kapot_id}: fout — RlzApiError: 503" in gelezen.err
    assert "1/3 administraties bank-gesynchroniseerd. (1 overgeslagen: geen Reeleezee-verbinding)" in gelezen.out


def test_sync_alles_bank_overgeslagen_raakt_exit_code_niet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.bank import sync_run as bank_sync_run

    ok_id, seed_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(cli.sync_service, "sync_alle_administraties", lambda: {ok_id: _resultaat()})
    monkeypatch.setattr(
        bank_sync_run,
        "sync_alle_via_runs",
        lambda: {
            ok_id: bank_sync_run.BankSyncRunInfo(
                run_id=uuid.uuid4(), status="klaar", overgeslagen=False, laatste_sync_op=None, resultaat={"bron": "sync_alles"}
            ),
            seed_id: bank_sync_run.BankSyncOvergeslagen("geen_credential", "Geen credential-prefix geregistreerd"),
        },
    )
    assert cli.main(["sync-alles"]) == 0
    assert f"OVERGESLAGEN bank-sync {seed_id}: geen_credential" in capsys.readouterr().out


def test_bank_sync_cli_alle_meldt_geen_credential_als_overgeslagen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`bank-sync` zonder id: GeenRlzCredentials (ook Odoo-sentinel) = OVERGESLAGEN, exit 0 (was: FOUT, exit 1)."""
    from types import SimpleNamespace

    ok_id, seed_id = uuid.uuid4(), uuid.uuid4()
    telling = SimpleNamespace(aangemaakt=0, bijgewerkt=0, open_ververst=0)
    ok = SimpleNamespace(
        rekeningen=telling, mutaties=telling, open_posten=telling, afletteren_geverifieerd=0, vastly_gemeld=0,
        automatisch_geboekt=0, automatisch_afgeletterd=0, automatisch_fouten=[],
    )
    monkeypatch.setattr(
        cli.bank_sync_service,
        "sync_bank_alle_administraties",
        lambda: {ok_id: ok, seed_id: GeenRlzCredentials("Administratie draait op Odoo (odoo:…)")},
    )
    assert cli.main(["bank-sync"]) == 0
    uit = capsys.readouterr().out
    assert f"OVERGESLAGEN {seed_id}" in uit and "1/2 administraties bank-gesynchroniseerd. (1 overgeslagen" in uit
