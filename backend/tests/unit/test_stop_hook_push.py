"""Guard rij (j4) 19-09 — Stop-hook-push mét retry (`scripts/git-hooks/stop-push.sh`; BESLISSINGEN "CC-INBOX — LOCK PER OPDRACHT,
POORT VÓÓR EINDE, PUSH-RETRY (19-09)").

Incident 19-09: de nameting-bot committe op origin/main tijdens een run; de Stop-hook-push faalde `! [rejected] … (fetch first)`,
meldde alleen "push handmatig" op stderr en de deploy stond drie uur stil. Sinds 19-09 doet de hook bij een geweigerde push één
fetch + `git merge --no-ff origin/main` + één retry; een echt conflict = luide blokkade (stderr mét commando's, melding,
opdrachten/.push-geblokkeerd → `rlz inbox status`). Nooit rebase (lokale hashes staan in rapporten), nooit force.
Echte git tegen een bare origin mét een 'mac'- en een 'bot'-kloon; osascript is een stub."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "scripts" / "git-hooks" / "stop-push.sh"
RLZ_ZSH = REPO / "scripts" / "zsh" / "rlz.zsh"
SETTINGS = REPO / ".claude" / "settings.local.json"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def _commit(cwd: Path, naam: str, inhoud: str, bericht: str) -> str:
    (cwd / naam).parent.mkdir(parents=True, exist_ok=True)
    (cwd / naam).write_text(inhoud, encoding="utf-8")
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-qm", bericht)
    return _git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def werkplaats(tmp_path: Path) -> dict[str, Path]:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=GIT_ENV)
    mac = tmp_path / "mac"
    subprocess.run(["git", "clone", "-q", str(origin), str(mac)], check=True, env=GIT_ENV)
    _git(mac, "checkout", "-q", "-b", "main")
    _commit(mac, "README.md", "x\n", "init")
    _commit(mac, "verkenning/nameting-alles-18-09.txt", "oud\n", "nameting 18-09")
    _git(mac, "push", "-q", "-u", "origin", "main")
    for sub in ("inbox", "lopend", "gedaan", "log"):
        (mac / "opdrachten" / sub).mkdir(parents=True)
    (mac / "scripts" / "zsh").mkdir(parents=True)
    shutil.copy(RLZ_ZSH, mac / "scripts" / "zsh" / "rlz.zsh")
    bot = tmp_path / "bot"
    subprocess.run(["git", "clone", "-q", str(origin), str(bot)], check=True, env=GIT_ENV)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "osascript").write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$MELDINGEN\"\nexit 0\n", encoding="utf-8")
    (stubs / "osascript").chmod(0o755)
    return {"origin": origin, "mac": mac, "bot": bot, "stubs": stubs, "meldingen": tmp_path / "meldingen.txt"}


def _env(w: dict[str, Path]) -> dict[str, str]:
    return {**GIT_ENV, "HOME": str(w["mac"].parent), "PATH": f"{w['stubs']}:{os.environ['PATH']}", "MELDINGEN": str(w["meldingen"]), "RLZ_REPO": str(w["mac"])}


def _hook(w: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOK), str(w["mac"]), "test-repo"], cwd=w["mac"], env=_env(w), capture_output=True, text=True, timeout=60)


def _meldingen(w: dict[str, Path]) -> str:
    return w["meldingen"].read_text(encoding="utf-8") if w["meldingen"].exists() else ""


def _status(w: dict[str, Path]) -> str:
    cmd = "source " + str(w["mac"] / "scripts" / "zsh" / "rlz.zsh").replace(" ", r"\ ") + "; rlz inbox status"
    return subprocess.run(["zsh", "-c", cmd], cwd=w["mac"], env=_env(w), capture_output=True, text=True, timeout=60).stdout


def test_niets_te_pushen_is_stil(werkplaats: dict[str, Path]) -> None:
    uit = _hook(werkplaats)
    assert uit.returncode == 0 and uit.stderr == "" and uit.stdout == "", uit


def test_gewone_push_slaagt_en_logt(werkplaats: dict[str, Path]) -> None:
    mac = werkplaats["mac"]
    sha = _commit(mac, "docs/a.md", "a\n", "feat a")
    uit = _hook(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert _git(werkplaats["origin"], "rev-parse", "main") == sha
    assert "push test-repo ok (1 commit(s))" in (mac / "opdrachten" / "log" / "push.log").read_text(encoding="utf-8")


def test_geweigerde_push_door_bot_commit_wordt_merge_no_ff_plus_retry(werkplaats: dict[str, Path]) -> None:
    """De reproductie van 19-09: de bot pusht een nameting-bestand terwijl de Mac lokaal een commit heeft → vóór de fix 'push handmatig',
    nu merge --no-ff (lokale hash blijft) + retry-push; origin bevat beide."""
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    bot_sha = _commit(bot, "verkenning/nameting-alles-19-09.txt", "bot\n", "nameting 19-09 alles")
    _git(bot, "push", "-q", "origin", "HEAD:main")
    lokaal = _commit(mac, "docs/rapporten/2026-09-19-x.md", "rapport\n", "docs(rapport x)")
    uit = _hook(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "origin was gedivergeerd (1 lokaal / 1 remote) → merge --no-ff + push geslaagd" in uit.stderr
    top = _git(werkplaats["origin"], "rev-parse", "main")
    ouders = _git(werkplaats["origin"], "log", "-1", "--format=%P", top).split()
    assert sorted(ouders) == sorted([lokaal, bot_sha]), "merge-commit mét beide ouders — de lokale hash bestaat nog"
    assert "automatisch door de Stop-hook ná een non-fast-forward-push" in _git(werkplaats["origin"], "log", "-1", "--format=%s", top)
    assert "nameting 19-09 alles" in _git(werkplaats["origin"], "log", "-1", "--format=%s", top)
    assert _git(mac, "rev-parse", "HEAD") == top
    log = (mac / "opdrachten" / "log" / "push.log").read_text(encoding="utf-8")
    assert "push test-repo geweigerd" in log and "retry push" in log and "push test-repo ok ná merge (1 + 1 commit(s))" in log
    assert not (mac / "opdrachten" / ".push-geblokkeerd").exists()
    assert _meldingen(werkplaats) == "", "geslaagd = geen melding"
    assert not re.search(r"rebase", _git(mac, "log", "--format=%s", "-3"), re.I) or "nooit rebase" in _git(mac, "log", "-1", "--format=%s")


def test_conflict_is_luide_blokkade_met_commandos_melding_en_statusregel(werkplaats: dict[str, Path]) -> None:
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    _commit(bot, "README.md", "bot-versie\n", "bot wijzigt README")
    _git(bot, "push", "-q", "origin", "HEAD:main")
    lokaal = _commit(mac, "README.md", "mac-versie\n", "mac wijzigt README")
    uit = _hook(werkplaats)
    assert uit.returncode == 1
    assert "Auto-push test-repo naar origin/main mislukt en niet automatisch te herstellen: origin gedivergeerd (1 lokaal / 1 remote) en de merge geeft conflicten" in uit.stderr
    assert "Doe zelf (nooit force, nooit rebase): cd " in uit.stderr and "git merge --no-ff origin/main" in uit.stderr and "git push origin main" in uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == lokaal and _git(mac, "status", "--porcelain", "--untracked-files=no") == "", "merge afgebroken, werkboom als vóór"
    assert not (mac / ".git" / "MERGE_HEAD").exists()
    assert (mac / "README.md").read_text(encoding="utf-8") == "mac-versie\n"
    blok = (mac / "opdrachten" / ".push-geblokkeerd").read_text(encoding="utf-8").splitlines()
    assert blok[0].endswith(" test-repo") and "merge geeft conflicten" in blok[1] and "git merge --no-ff origin/main" in blok[2]
    assert "PUSH GEBLOKKEERD: test-repo" in _meldingen(werkplaats)
    st = _status(werkplaats)
    assert "origin gedivergeerd (1 lokaal / 1 remote) — deploy staat stil" in st and "PUSH GEBLOKKEERD (" in st and "herstel: git merge --no-ff origin/main" in st, st
    # herstel door een mens + geslaagde push ruimt de blokkade op
    _git(mac, "merge", "--no-ff", "-X", "ours", "-m", "merge handmatig", "origin/main")
    uit2 = _hook(werkplaats)
    assert uit2.returncode == 0, uit2.stderr
    assert not (mac / "opdrachten" / ".push-geblokkeerd").exists()
    assert "PUSH GEBLOKKEERD" not in _status(werkplaats)


def test_divergentie_met_vuile_werkboom_merget_niet(werkplaats: dict[str, Path]) -> None:
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    _commit(bot, "verkenning/nameting-alles-19-09.txt", "bot\n", "nameting")
    _git(bot, "push", "-q", "origin", "HEAD:main")
    lokaal = _commit(mac, "docs/b.md", "b\n", "docs b")
    (mac / "README.md").write_text("ongecommit\n", encoding="utf-8")
    uit = _hook(werkplaats)
    assert uit.returncode == 1 and "ongecommitte tracked wijzigingen — merge niet veilig" in uit.stderr, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == lokaal and (mac / "README.md").read_text(encoding="utf-8") == "ongecommit\n"


def test_hook_script_kent_geen_rebase_force_of_stash_commando() -> None:
    code = "\n".join(r for r in HOOK.read_text(encoding="utf-8").splitlines() if not r.lstrip().startswith("#"))
    assert not re.search(r"git\s+(-C\s+\S+\s+)?(pull\b[^\n]*--rebase|rebase\b)", code), "nooit rebase"
    assert not re.search(r"push\b[^\n\"']*(--force|-f\b|\+main)", code), "nooit force"
    assert not re.search(r"git\s+(-C\s+\S+\s+)?stash\b", code), "nooit stash"
    assert "merge --no-ff" in code and "merge --abort" in code and ".push-geblokkeerd" in code
    assert os.access(HOOK, os.X_OK), "uitvoerbaar"


def test_lokale_stop_hook_roept_het_script_aan_voor_beide_repos() -> None:
    """settings.local.json staat niet in git (lokale hook-config); staat hij er, dan moeten beide Stop-hook-entries dit script gebruiken —
    de oude 'push handmatig'-shellregel mag niet terugkomen."""
    if not SETTINGS.is_file():
        pytest.skip("geen lokale .claude/settings.local.json")
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8")).get("hooks", {}).get("Stop", [])
    commando_s = [h["command"] for groep in hooks for h in groep.get("hooks", [])]
    assert len(commando_s) >= 2, commando_s
    assert all("scripts/git-hooks/stop-push.sh" in c for c in commando_s), commando_s
    assert any("Platform" in c for c in commando_s) and any("$CLAUDE_PROJECT_DIR" in c for c in commando_s)
    assert not any("push handmatig" in c for c in commando_s)
