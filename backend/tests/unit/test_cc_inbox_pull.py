"""Guard (werkloop-nazorg 14-09): `scripts/cc_inbox.sh` doet vóór het oppakken van een opdracht én bij elke
launchd-tick zonder werk een `git pull --ff-only origin main` in de repo-root — zodat de bot-commits van de
nameting-workflow op de Mac landen — maar ALLEEN als er geen lock is en de werkboom schoon is; anders overslaan mét
logregel. Nooit rebase/merge/stash: een gedivergeerde stand blijft staan. Het échte script draait hier tegen
wegwerp-git-repo's (een 'Mac'-kloon, een 'bot'-kloon en een bare 'origin'); de inbox blijft leeg zodat `claude` nooit
wordt gestart (één test zet een claude-stub neer)."""

from __future__ import annotations

import os
import shutil
import subprocess
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
    "HOME": "",  # geen ~/.gitconfig (hooks, signing) in de wegwerp-repo's
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(cwd: Path, naam: str, inhoud: str, bericht: str) -> str:
    (cwd / naam).parent.mkdir(parents=True, exist_ok=True)
    (cwd / naam).write_text(inhoud, encoding="utf-8")
    _git(cwd, "add", naam)
    _git(cwd, "commit", "-q", "-m", bericht)
    return _git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def werkplaats(tmp_path: Path) -> dict[str, Path]:
    """origin (bare) ← mac (kloon mét het script op scripts/cc_inbox.sh en een lege inbox) ← bot (kloon die pusht)."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    zaad = tmp_path / "zaad"
    _git(tmp_path, "clone", "-q", str(origin), str(zaad))
    _git(zaad, "checkout", "-q", "-b", "main")
    (zaad / "scripts").mkdir()
    shutil.copy(SCRIPT, zaad / "scripts" / "cc_inbox.sh")
    for sub in ("inbox", "lopend", "gedaan"):
        (zaad / "opdrachten" / sub).mkdir(parents=True)
        (zaad / "opdrachten" / sub / ".gitkeep").write_text("", encoding="utf-8")
    (zaad / ".gitignore").write_text("opdrachten/log/\nopdrachten/.lock\n", encoding="utf-8")
    (zaad / "verkenning").mkdir()
    (zaad / "verkenning" / "README.txt").write_text("nametingen\n", encoding="utf-8")
    _git(zaad, "add", "-A")
    _git(zaad, "commit", "-q", "-m", "zaad")
    _git(zaad, "push", "-q", "-u", "origin", "main")
    mac = tmp_path / "mac"
    _git(tmp_path, "clone", "-q", str(origin), str(mac))
    bot = tmp_path / "bot"
    _git(tmp_path, "clone", "-q", str(origin), str(bot))
    return {"origin": origin, "mac": mac, "bot": bot}


def _bot_pusht(bot: Path, naam: str = "verkenning/nameting-reconciliatie-14-09.txt") -> str:
    sha = _commit(bot, naam, "LEES-ONLY afgerond\n", f"nameting 14-09 — {naam}")
    _git(bot, "push", "-q", "origin", "main")
    return sha


def _draai_script(mac: Path) -> subprocess.CompletedProcess[str]:
    # PATH zonder `claude`/`osascript` is prima: met een lege inbox eindigt het script vóór die tools nodig zijn.
    return subprocess.run(
        ["bash", str(mac / "scripts" / "cc_inbox.sh")],
        cwd=mac,
        env={**GIT_ENV, "HOME": str(mac.parent)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_tick_zonder_werk_haalt_bot_commit_binnen_ff_only(werkplaats: dict[str, Path]) -> None:
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    sha = _bot_pusht(bot)
    assert _git(mac, "rev-parse", "HEAD") != sha
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == sha, uit.stderr
    assert (mac / "verkenning" / "nameting-reconciliatie-14-09.txt").is_file()
    assert "pull ff-only 1 commit(s) binnen" in uit.stderr, uit.stderr
    assert not (mac / "opdrachten" / ".lock").exists()
    # geen merge-commit: HEAD is exact de bot-commit, lineair
    assert _git(mac, "rev-list", "--merges", "--count", "HEAD") == "0"


def test_tick_zonder_werk_en_zonder_nieuws_logt_niets(werkplaats: dict[str, Path]) -> None:
    mac = werkplaats["mac"]
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert uit.stderr.strip() == "", uit.stderr  # geen "Already up to date" om de vijf minuten


def test_pull_overgeslagen_bij_vuile_werkboom(werkplaats: dict[str, Path]) -> None:
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    voor = _git(mac, "rev-parse", "HEAD")
    sha = _bot_pusht(bot)
    (mac / "verkenning" / "README.txt").write_text("lokaal gewijzigd, niet gecommit\n", encoding="utf-8")
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == voor != sha, "pull had overgeslagen moeten worden"
    # sinds rij (j3) 19-09 stopt de tick al vóór de pull: ongecommit werk = melding + stop (geen pull, geen start)
    assert "STOP — werkboom niet schoon bij start (1 bestand(en):  M verkenning/README.txt" in uit.stderr, uit.stderr
    assert "pull ff-only" not in uit.stderr
    assert (mac / "verkenning" / "README.txt").read_text(encoding="utf-8").startswith("lokaal gewijzigd"), "nooit stash"


def test_untracked_opdracht_in_inbox_houdt_pull_niet_tegen(werkplaats: dict[str, Path]) -> None:
    """Een nieuwe opdracht in inbox/ is untracked; die mag de pull niet blokkeren (anders komt de bot-commit nooit
    binnen zolang er werk staat). Het script pakt daarna wél de opdracht op — daarom een `claude`-stub die direct
    stopt."""
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    sha = _bot_pusht(bot)
    (mac / "opdrachten" / "inbox" / "2026-09-14-test.md").write_text("OPDRACHT — test\n", encoding="utf-8")
    stubs = mac.parent / "stubs"
    stubs.mkdir()
    (stubs / "claude").write_text(  # afgeronde run = rapport + commit (rij (j3) 19-09)
        "#!/bin/bash\n" + """f="docs/rapporten/$(date +%F)-stub-$$.md"; mkdir -p docs/rapporten; echo "rapport stub" > "$f"
if git rev-parse --git-dir >/dev/null 2>&1; then git add -A -- docs >/dev/null 2>&1; git commit -qm "stub: rapport" >/dev/null 2>&1; fi\necho stub-klaar\nexit 0\n""", encoding="utf-8"
    )
    (stubs / "osascript").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for s in stubs.iterdir():
        s.chmod(0o755)
    uit = subprocess.run(
        ["bash", str(mac / "scripts" / "cc_inbox.sh")],
        cwd=mac,
        env={**GIT_ENV, "HOME": str(mac.parent), "PATH": f"{stubs}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD~1") == sha, uit.stderr  # bot-commit binnen; daarbovenop de commit van de (stub-)run
    assert (mac / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file(), "de opdracht is ná de pull gewoon opgepakt"


def test_untracked_buiten_inbox_houdt_pull_niet_tegen(werkplaats: dict[str, Path]) -> None:
    """Nazorg 15-09: 'schoon' = geen gewijzigde/gestagede TRACKED bestanden. Untracked bestanden búiten inbox/ (een
    gedaan-opdracht die nog niet gecommit is, een lokale `.claude/`-map met runtime-artefacten) tellen niet — git
    weigert een ff-pull die zo'n bestand zou overschrijven toch zelf. Zonder werk in inbox/ blijft de tick verder
    stil."""
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    sha = _bot_pusht(bot, "verkenning/nameting-replay-15-09.txt")
    (mac / "opdrachten" / "gedaan" / "2026-09-14-dummy.md").write_text("uitgevoerd, rapport: geen\n", encoding="utf-8")
    (mac / ".claude").mkdir()
    (mac / ".claude" / "scheduled_tasks.lock").write_text("{}\n", encoding="utf-8")
    assert _git(mac, "status", "--porcelain").count("??") == 2, "opzet: twee untracked paden, niets tracked gewijzigd"
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == sha, uit.stderr
    assert (mac / "verkenning" / "nameting-replay-15-09.txt").is_file()
    assert "pull ff-only 1 commit(s) binnen" in uit.stderr, uit.stderr
    assert "overgeslagen" not in uit.stderr, uit.stderr
    # de untracked bestanden staan er nog precies zo (nooit stash/clean)
    assert (mac / "opdrachten" / "gedaan" / "2026-09-14-dummy.md").is_file()
    assert (mac / ".claude" / "scheduled_tasks.lock").is_file()


def test_gestaged_tracked_bestand_telt_als_vuil(werkplaats: dict[str, Path]) -> None:
    """Een gestagede (nog niet gecommitte) wijziging aan een tracked bestand is wél vuil — een ff-pull zou daar
    overheen kunnen lopen; overslaan mét logregel, index blijft staan."""
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    voor = _git(mac, "rev-parse", "HEAD")
    _bot_pusht(bot)
    (mac / "verkenning" / "README.txt").write_text("gestaged\n", encoding="utf-8")
    _git(mac, "add", "verkenning/README.txt")
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == voor
    assert "STOP — werkboom niet schoon bij start (1 bestand(en): M  verkenning/README.txt" in uit.stderr, uit.stderr  # rij (j3) 19-09
    assert _git(mac, "diff", "--cached", "--name-only") == "verkenning/README.txt", "index onaangeraakt"


def test_pull_overgeslagen_bij_gedivergeerde_stand_nooit_merge(werkplaats: dict[str, Path]) -> None:
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    lokaal = _commit(mac, "docs/lokaal.md", "lokaal werk\n", "lokaal, nog niet gepusht")
    _bot_pusht(bot)
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == lokaal, "een ff-only-fout mag de lokale stand niet veranderen"
    assert "pull overgeslagen — ff-only mislukt" in uit.stderr, uit.stderr
    assert _git(mac, "rev-list", "--merges", "--count", "HEAD") == "0"
    assert _git(mac, "status", "--porcelain", "--untracked-files=no") == ""


def test_levende_lock_doet_niets_ook_geen_pull(werkplaats: dict[str, Path]) -> None:
    mac, bot = werkplaats["mac"], werkplaats["bot"]
    voor = _git(mac, "rev-parse", "HEAD")
    _bot_pusht(bot)
    (mac / "opdrachten" / ".lock").write_text(f"{os.getpid()}\n", encoding="utf-8")  # pid van pytest = leeft
    uit = _draai_script(mac)
    assert uit.returncode == 0, uit.stderr
    assert _git(mac, "rev-parse", "HEAD") == voor
    assert "wacht — inbox-run actief (pid" in uit.stderr and "pull" not in uit.stderr  # rij (j2) 19-09: zichtbaar, nooit een pull


def test_script_gebruikt_ff_only_en_nooit_rebase_merge_stash() -> None:
    """De pull is ff-only en het script rebaset/stasht/merget nooit. Sinds rij (j3) 19-09 zet het script ongecommit werk als
    WIP-commit weg via plumbing (tijdelijke index, commit-tree, update-ref) en maakt de werkboom daarna schoon met
    `reset --hard HEAD` — dat raakt alleen werk dat zojuist veilig op de wip/-branch is gezet, nooit main. 'git merge' komt
    alleen voor als advies-tekst voor een mens (rlz.zsh), niet als commando in dit script."""
    code = "\n".join(r.split("#", 1)[0] for r in SCRIPT.read_text(encoding="utf-8").splitlines())
    assert "pull --ff-only origin main" in code
    assert "status --porcelain --untracked-files=no" in code, "schoon = alleen tracked bestanden (nazorg 15-09)"
    for verboden in ("git stash", "pull --rebase", "git rebase", "checkout --", "push --force", "push -f"):
        assert verboden not in code, verboden
    import re as _re
    assert not _re.search(r"git -C \"\$REPO\" merge\b", code), "geen merge-commando in het inbox-script (de Stop-hook merget, zichtbaar)"
    assert code.count("reset -q --hard HEAD") == 1 and "update-ref \"refs/heads/$branch\"" in code, "reset alleen ná de WIP-commit"
