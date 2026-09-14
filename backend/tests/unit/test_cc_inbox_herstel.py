"""Guard (herstel cc-inbox 14-09 avond): élke stop van `scripts/cc_inbox.sh` geeft een logregel + melding, een lange run
draagt een hartslag, en een verweesde opdracht in lopend/ gaat bij de volgende tick terug naar inbox/ (begrensd aantal
pogingen, daarna opdrachten/mislukt/). Aanleiding: de veldwerkers-run van 15:17 stierf ná 22 min op een budgetlimiet;
het log droeg alleen de startregel en de opdracht bleef in lopend/ staan.

Het échte script draait tegen een wegwerp-git-repo mét stubs voor `claude` (gedrag via bestand `claude_gedrag`) en
`osascript` (registreert élke melding in `meldingen.txt`); de pull staat uit (CC_INBOX_GEEN_PULL=1)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "cc_inbox.sh"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
    "CC_INBOX_GEEN_PULL": "1",
}

CLAUDE_STUB = r"""#!/bin/bash
# gedrag uit $CLAUDE_GEDRAG: "ok" | "limiet" | "fout" | "slaap <s>"
gedrag="$(cat "$CLAUDE_GEDRAG" 2>/dev/null || echo ok)"
case "$gedrag" in
  ok) echo "stub-klaar"; exit 0 ;;
  limiet) echo "You've hit your monthly spend limit. Switch to another model, or manage usage credits" \
             "at claude.ai/admin-settings/usage, to continue."; exit 1 ;;
  fout) echo "stub-fout"; exit 2 ;;
  slaap*) echo "stub-slaapt"; sleep "${gedrag#slaap }"; echo "stub-wakker"; exit 0 ;;
esac
"""

OSASCRIPT_STUB = r"""#!/bin/bash
printf '%s\n' "$*" >> "$MELDINGEN"
exit 0
"""


@pytest.fixture
def werkplaats(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=GIT_ENV)
    (repo / "scripts").mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "cc_inbox.sh")
    for sub in ("inbox", "lopend", "gedaan", "mislukt", "log"):
        (repo / "opdrachten" / sub).mkdir(parents=True)
    (repo / "docs" / "rapporten").mkdir(parents=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "claude").write_text(CLAUDE_STUB, encoding="utf-8")
    (stubs / "osascript").write_text(OSASCRIPT_STUB, encoding="utf-8")
    for s in stubs.iterdir():
        s.chmod(0o755)
    (tmp_path / "claude_gedrag").write_text("ok", encoding="utf-8")
    return {"repo": repo, "stubs": stubs, "gedrag": tmp_path / "claude_gedrag", "meldingen": tmp_path / "meldingen.txt"}


def _env(w: dict[str, Path], **extra: str) -> dict[str, str]:
    return {
        **GIT_ENV,
        "HOME": str(w["repo"].parent),
        "PATH": f"{w['stubs']}:{os.environ['PATH']}",
        "CLAUDE_GEDRAG": str(w["gedrag"]),
        "MELDINGEN": str(w["meldingen"]),
        **extra,
    }


def _draai(w: dict[str, Path], **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(w["repo"] / "scripts" / "cc_inbox.sh")],
        cwd=w["repo"],
        env=_env(w, **extra),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _opdracht(w: dict[str, Path], slug: str = "2026-09-14-test") -> Path:
    p = w["repo"] / "opdrachten" / "inbox" / f"{slug}.md"
    p.write_text("OPDRACHT — test\n", encoding="utf-8")
    return p


def _meldingen(w: dict[str, Path]) -> str:
    return w["meldingen"].read_text(encoding="utf-8") if w["meldingen"].exists() else ""


def _log(w: dict[str, Path], slug: str = "2026-09-14-test") -> str:
    return (w["repo"] / "opdrachten" / "log" / f"{slug}.log").read_text(encoding="utf-8")


def test_geslaagde_run_naar_gedaan_met_melding_en_gewiste_teller(werkplaats: dict[str, Path]) -> None:
    _opdracht(werkplaats)
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    repo = werkplaats["repo"]
    assert (repo / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file()
    assert not (repo / "opdrachten" / "log" / "2026-09-14-test.pogingen").exists(), "teller weg ná succes"
    assert "CC klaar: 2026-09-14-test" in _meldingen(werkplaats)
    log = _log(werkplaats)
    assert "poging 1/3" in log and "claude eindigde met code 0" in log and "melding verstuurd" in log
    assert not (repo / "opdrachten" / ".lock").exists()


def test_budgetlimiet_blijft_in_lopend_met_limiet_regel_en_melding(werkplaats: dict[str, Path]) -> None:
    """Het incident van 15:17: claude -p exit 1 op de spend limit → logregel LIMIET + melding, bestand blijft
    zichtbaar in lopend/."""
    werkplaats["gedrag"].write_text("limiet", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _draai(werkplaats)
    assert uit.returncode == 1
    repo = werkplaats["repo"]
    assert (repo / "opdrachten" / "lopend" / "2026-09-14-test.md").is_file()
    log = _log(werkplaats)
    assert "claude eindigde met code 1" in log
    assert "LIMIET — claude.ai/admin-settings/usage" in log
    assert "blijft in opdrachten/lopend/" in log
    m = _meldingen(werkplaats)
    assert "CC MISLUKT: 2026-09-14-test (code 1, LIMIET" in m
    assert (repo / "opdrachten" / "log" / "2026-09-14-test.pogingen").read_text(encoding="utf-8").strip() == "1"
    assert not (repo / "opdrachten" / ".lock").exists()


def test_verweesde_lopend_opdracht_gaat_terug_naar_inbox_en_wordt_opnieuw_opgepakt(werkplaats: dict[str, Path]) -> None:
    werkplaats["gedrag"].write_text("fout", encoding="utf-8")
    _opdracht(werkplaats)
    assert _draai(werkplaats).returncode == 2
    repo = werkplaats["repo"]
    assert (repo / "opdrachten" / "lopend" / "2026-09-14-test.md").is_file()
    # volgende tick, oorzaak weg: terug naar inbox (poging 2/3) én direct opnieuw opgepakt → gedaan
    werkplaats["gedrag"].write_text("ok", encoding="utf-8")
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "verweesd in lopend/ (run gestopt zonder afronding) → terug naar inbox/, poging 2/3" in uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file()
    assert not (repo / "opdrachten" / "lopend" / "2026-09-14-test.md").exists()
    m = _meldingen(werkplaats)
    assert "CC HERSTART: 2026-09-14-test (poging 2/3)" in m and "CC klaar: 2026-09-14-test" in m
    log = _log(werkplaats)
    assert "start 2026-09-14-test" in log and "poging 2/3" in log


def test_na_max_pogingen_naar_mislukt_met_kopregel_en_geen_herstart(werkplaats: dict[str, Path]) -> None:
    werkplaats["gedrag"].write_text("limiet", encoding="utf-8")
    _opdracht(werkplaats)
    repo = werkplaats["repo"]
    for _ in range(3):  # poging 1, 2, 3 — elke tick zet 'm terug en probeert opnieuw
        uit = _draai(werkplaats)
        assert uit.returncode == 1, uit.stderr
    assert (repo / "opdrachten" / "lopend" / "2026-09-14-test.md").is_file()
    assert (repo / "opdrachten" / "log" / "2026-09-14-test.pogingen").read_text(encoding="utf-8").strip() == "3"
    # vierde tick: teller ≥ 3 → mislukt/, geen nieuwe run
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    mislukt = repo / "opdrachten" / "mislukt" / "2026-09-14-test.md"
    assert mislukt.is_file()
    inhoud = mislukt.read_text(encoding="utf-8")
    assert inhoud.startswith("MISLUKT ná 3 pogingen (") and "spend limit" in inhoud.splitlines()[0]
    assert "OPDRACHT — test" in inhoud
    assert not (repo / "opdrachten" / "lopend" / "2026-09-14-test.md").exists()
    assert not (repo / "opdrachten" / "inbox" / "2026-09-14-test.md").exists()
    assert not (repo / "opdrachten" / "log" / "2026-09-14-test.pogingen").exists()
    assert "→ opdrachten/mislukt/" in uit.stderr
    assert "CC MISLUKT DEFINITIEF: 2026-09-14-test" in _meldingen(werkplaats)
    assert _meldingen(werkplaats).count("CC MISLUKT: 2026-09-14-test") == 3
    # vijfde tick: niets meer te doen, stil
    uit = _draai(werkplaats)
    assert uit.returncode == 0 and uit.stderr.strip() == ""


def test_hartslag_in_het_log_tijdens_een_lange_run(werkplaats: dict[str, Path]) -> None:
    werkplaats["gedrag"].write_text("slaap 3", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _draai(werkplaats, CC_INBOX_HARTSLAG_S="1")
    assert uit.returncode == 0, uit.stderr
    log = _log(werkplaats)
    assert log.count("loopt nog (0 min") >= 2, log
    assert "stub-wakker" in log and "claude eindigde met code 0" in log


def test_signaal_geeft_gestopt_regel_en_melding_en_laat_opdracht_in_lopend(werkplaats: dict[str, Path]) -> None:
    """launchd-stop / kill tijdens de run: logregel GESTOPT + melding, claude-kind beëindigd, lock weg,
    bestand blijft in lopend/."""
    werkplaats["gedrag"].write_text("slaap 30", encoding="utf-8")
    _opdracht(werkplaats)
    proc = subprocess.Popen(
        ["bash", str(werkplaats["repo"] / "scripts" / "cc_inbox.sh")],
        cwd=werkplaats["repo"],
        env=_env(werkplaats),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    repo = werkplaats["repo"]
    logpad = repo / "opdrachten" / "log" / "2026-09-14-test.log"
    for _ in range(100):
        if logpad.exists() and "stub-slaapt" in logpad.read_text(encoding="utf-8"):
            break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("claude-stub kwam niet op gang")
    proc.send_signal(signal.SIGTERM)
    rc = proc.wait(timeout=15)
    assert rc == 143
    log = logpad.read_text(encoding="utf-8")
    assert "GESTOPT door signaal TERM" in log and "blijft in opdrachten/lopend/" in log
    assert "CC GESTOPT: 2026-09-14-test (signaal TERM)" in _meldingen(werkplaats)
    assert (repo / "opdrachten" / "lopend" / "2026-09-14-test.md").is_file()
    assert not (repo / "opdrachten" / ".lock").exists()
    # geen achtergebleven stub-processen uit deze sessie
    time.sleep(0.5)
    rest = subprocess.run(["pgrep", "-g", str(proc.pid)], capture_output=True, text=True)
    assert rest.stdout.strip() == "", f"kinderen leven nog: {rest.stdout}"
    # volgende tick: verweesd → terug naar inbox → poging 2 → klaar
    werkplaats["gedrag"].write_text("ok", encoding="utf-8")
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file()


def test_melding_mislukt_wordt_gelogd_nooit_stil(werkplaats: dict[str, Path]) -> None:
    (werkplaats["stubs"] / "osascript").write_text("#!/bin/bash\nexit 7\n", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "melding mislukt (osascript rc=7) — CC klaar: 2026-09-14-test" in _log(werkplaats)


def test_levende_lock_raakt_lopend_niet_aan(werkplaats: dict[str, Path]) -> None:
    """Een interactieve CC-run die een opdracht in lopend/ bewerkt houdt de lock mét zijn pid vast → de tick doet
    niets."""
    repo = werkplaats["repo"]
    (repo / "opdrachten" / "lopend" / "2026-09-14-handmatig.md").write_text("OPDRACHT — handmatig\n", encoding="utf-8")
    (repo / "opdrachten" / ".lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
    uit = _draai(werkplaats)
    assert uit.returncode == 0 and uit.stderr.strip() == ""
    assert (repo / "opdrachten" / "lopend" / "2026-09-14-handmatig.md").is_file()
    assert _meldingen(werkplaats) == ""


def test_script_documenteert_elke_stop_en_kent_geen_stille_paden() -> None:
    code = SCRIPT.read_text(encoding="utf-8")
    for verwacht in (
        "trap 'bij_signaal TERM' TERM",
        "trap bij_exit EXIT",
        "herstel_verweesd",
        "loopt nog",
        "LIMIET — claude.ai/admin-settings/usage",
        "opdrachten/mislukt/",
    ):
        assert verwacht in code, verwacht
