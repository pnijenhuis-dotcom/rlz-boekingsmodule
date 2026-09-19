"""Guard rij (j) 19-09 — CC-inbox: lock per opdracht, één runner per repo, poort vóór einde (BESLISSINGEN "CC-INBOX — LOCK PER
OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)").

Procesles inbox-run 19-09 12:46: (1) twee runs pakten dezelfde opdracht; (2) twee runs eindigden vóór hun suite, werk bleef
ongecommit in de werkboom; (3) de Stop-hook-push faalde stil (zie test_stop_hook_push.py). Hier:
  (j1) claim = atomische `mv inbox/X lopend/X` — twee processen, één wint; claim-bestand pid/starttijd; dode claim < grens =
       onzeker, ≥ grens = gestrand → herstelpad; `rlz inbox status` toont de claim per lopend-bestand;
  (j2) runner-lock atomisch (noclobber), tweede tick stopt zichtbaar; twee `rlz cc`-starts → één loopt, één stopt mét melding;
  (j3) ongecommit werk ná claude = WIP op branch wip/<slug> (main onaangeraakt), opdracht blijft in lopend/, volgende poging
       begint mét `git merge --squash`; exit 0 zonder rapport/commit = geen resultaat; ongecommit werk bij de start = stop.
Het échte script en de échte zsh-functie draaien tegen een wegwerp-git-repo mét stubs (`claude`, `osascript`); de pull staat uit."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "cc_inbox.sh"
RLZ_ZSH = REPO / "scripts" / "zsh" / "rlz.zsh"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
    "CC_INBOX_GEEN_PULL": "1",
}

# gedrag uit $CLAUDE_GEDRAG:
#   af        → rapport + commit (een afgeronde run)            vuil      → ongecommit bestand, exit 0 (poort niet gehaald)
#   vuil_gedaan → ongecommit bestand + zelf naar gedaan/ mét kopregel, exit 0
#   niets     → exit 0 zonder rapport/commit                     prompt    → prompt naar $PROMPT_CAPTURE + af
#   slaap N   → wacht N s, dan af
CLAUDE_STUB = r"""#!/bin/bash
gedrag="$(cat "$CLAUDE_GEDRAG" 2>/dev/null || echo af)"
af() { f="docs/rapporten/$(date +%F)-stub-$$.md"; echo "rapport stub" > "$f"; git add -A -- docs >/dev/null 2>&1; git commit -qm "stub: rapport" >/dev/null 2>&1; }
case "$gedrag" in
  af) af; echo "stub-klaar"; exit 0 ;;
  vuil) echo "half werk" > backend_nieuw.py; echo "gewijzigd" >> README.md; echo "stub-vuil"; exit 0 ;;
  vuil_gedaan) echo "half werk" > backend_nieuw.py
       l="$(ls opdrachten/lopend/*.md | head -1)"; { echo "uitgevoerd $(date +%F), rapport: geen"; echo; cat "$l"; } > "opdrachten/gedaan/$(basename "$l")"; rm -f "$l"
       echo "stub-vuil-gedaan"; exit 0 ;;
  niets) echo "Ik wacht op de melding."; exit 0 ;;
  prompt) printf '%s\n' "$@" > "$PROMPT_CAPTURE"; af; echo "stub-klaar"; exit 0 ;;
  slaap*) sleep "${gedrag#slaap }"; af; echo "stub-wakker"; exit 0 ;;
esac
"""
OSASCRIPT_STUB = "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$MELDINGEN\"\nexit 0\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


@pytest.fixture
def werkplaats(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=GIT_ENV)
    (repo / "scripts" / "zsh").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "cc_inbox.sh")
    shutil.copy(RLZ_ZSH, repo / "scripts" / "zsh" / "rlz.zsh")
    for sub in ("inbox", "lopend", "gedaan", "mislukt", "log"):
        (repo / "opdrachten" / sub).mkdir(parents=True)
    (repo / "docs" / "rapporten").mkdir(parents=True)
    (repo / "docs" / "rapporten" / "INDEX.md").write_text("# index\n", encoding="utf-8")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "claude").write_text(CLAUDE_STUB, encoding="utf-8")
    (stubs / "osascript").write_text(OSASCRIPT_STUB, encoding="utf-8")
    for s in stubs.iterdir():
        s.chmod(0o755)
    (tmp_path / "gedrag").write_text("af", encoding="utf-8")
    return {"repo": repo, "stubs": stubs, "gedrag": tmp_path / "gedrag", "meldingen": tmp_path / "meldingen.txt", "prompt": tmp_path / "prompt.txt"}


def _env(w: dict[str, Path], **extra: str) -> dict[str, str]:
    return {
        **GIT_ENV,
        "HOME": str(w["repo"].parent),
        "PATH": f"{w['stubs']}:{os.environ['PATH']}",
        "CLAUDE_GEDRAG": str(w["gedrag"]),
        "MELDINGEN": str(w["meldingen"]),
        "PROMPT_CAPTURE": str(w["prompt"]),
        "RLZ_REPO": str(w["repo"]),
        **extra,
    }


def _tick(w: dict[str, Path], **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(w["repo"] / "scripts" / "cc_inbox.sh")], cwd=w["repo"], env=_env(w, **extra), capture_output=True, text=True, timeout=90)


def _rlz(w: dict[str, Path], *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    cmd = "source " + str(w["repo"] / "scripts" / "zsh" / "rlz.zsh").replace(" ", r"\ ") + "; rlz " + " ".join(args)
    return subprocess.run(["zsh", "-c", cmd], cwd=w["repo"], env=_env(w, **extra), capture_output=True, text=True, timeout=90)


def _opdracht(w: dict[str, Path], slug: str = "2026-09-19-test") -> Path:
    p = w["repo"] / "opdrachten" / "inbox" / f"{slug}.md"
    p.write_text("# OPDRACHT — test\n\ninhoud\n", encoding="utf-8")
    return p


def _meldingen(w: dict[str, Path]) -> str:
    return w["meldingen"].read_text(encoding="utf-8") if w["meldingen"].exists() else ""


def _log(w: dict[str, Path], slug: str = "2026-09-19-test") -> str:
    p = w["repo"] / "opdrachten" / "log" / f"{slug}.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ---- (j1) claim per opdracht -------------------------------------------------------------------------------------------


def test_claim_twee_processen_een_wint(werkplaats: dict[str, Path]) -> None:
    """Twee processen claimen tegelijk dezelfde (enige) opdracht: precies één krijgt 'm (mv = rename(2)), de ander meldt dat er niets
    (meer) te claimen is — nooit twee runs op één opdracht."""
    _opdracht(werkplaats)
    env = _env(werkplaats, CC_INBOX_CLAIM_ALLEEN="1")
    procs = [subprocess.Popen(["bash", str(werkplaats["repo"] / "scripts" / "cc_inbox.sh")], cwd=werkplaats["repo"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    uit = [p.communicate(timeout=60) for p in procs]
    winnaars = [o for o, _ in uit if o.startswith("CLAIM 2026-09-19-test.md")]
    assert len(winnaars) == 1, uit
    assert sum(1 for o, _ in uit if o.startswith("GEEN CLAIM")) == 1, uit
    assert (werkplaats["repo"] / "opdrachten" / "lopend" / "2026-09-19-test.md").is_file()
    assert not (werkplaats["repo"] / "opdrachten" / "inbox" / "2026-09-19-test.md").exists()


def test_claim_slaat_een_opdracht_over_die_al_in_lopend_staat(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    _opdracht(werkplaats, "2026-09-19-a")
    (repo / "opdrachten" / "lopend" / "2026-09-19-a.md").write_text("al geclaimd\n", encoding="utf-8")
    time.sleep(1.1)
    _opdracht(werkplaats, "2026-09-19-b")
    uit = _tick(werkplaats, CC_INBOX_CLAIM_ALLEEN="1")
    assert uit.returncode == 0 and uit.stdout.startswith("CLAIM 2026-09-19-b.md"), uit.stdout + uit.stderr
    assert "claim overgeslagen — 2026-09-19-a.md staat al in lopend/" in uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-19-a.md").is_file(), "niet stil overschreven"


def test_run_schrijft_claim_met_pid_en_starttijd_en_ruimt_op(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    werkplaats["gedrag"].write_text("slaap 2", encoding="utf-8")
    _opdracht(werkplaats)
    proc = subprocess.Popen(["bash", str(repo / "scripts" / "cc_inbox.sh")], cwd=repo, env=_env(werkplaats), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    claim = repo / "opdrachten" / "log" / "2026-09-19-test.claim"
    for _ in range(50):
        if claim.exists():
            break
        time.sleep(0.1)
    regels = claim.read_text(encoding="utf-8").splitlines()
    assert len(regels) == 2 and regels[0].isdigit() and regels[1].startswith("20"), regels
    st = _rlz(werkplaats, "inbox", "status")
    assert f"lopend/: 2026-09-19-test.md — loopt (claim pid {regels[0]}, sinds {regels[1]})" in st.stdout, st.stdout
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert not claim.exists() and (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").is_file()
    assert f"claim pid {regels[0]}" in _log(werkplaats)


def test_dode_claim_jonger_dan_grens_is_onzeker_en_ouder_is_gestrand(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    dood = subprocess.Popen(["/bin/sleep", "0"])
    dood.wait()
    (repo / "opdrachten" / "lopend" / "2026-09-19-dood.md").write_text("OPDRACHT\n", encoding="utf-8")
    claim = repo / "opdrachten" / "log" / "2026-09-19-dood.claim"
    claim.write_text(f"{dood.pid}\n2026-09-19T12:00:00\n", encoding="utf-8")
    uit = _tick(werkplaats)  # default grens 1800 s → onzeker, geen herstel
    assert uit.returncode == 0, uit.stderr
    assert f"2026-09-19-dood onzeker — claim pid {dood.pid} leeft niet (0 min, grens 30 min): nog geen herstel" in uit.stderr
    assert (repo / "opdrachten" / "lopend" / "2026-09-19-dood.md").is_file() and claim.exists()
    st = _rlz(werkplaats, "inbox", "status")
    assert f"onzeker (claim pid {dood.pid} leeft niet, 0 min < 30" in st.stdout, st.stdout
    time.sleep(1.2)
    uit2 = _tick(werkplaats, CC_INBOX_GESTRAND_S="1")  # grens verstreken → gestrand → herstelpad (e) mét melding, dan opgepakt
    assert uit2.returncode == 0, uit2.stderr
    assert f"2026-09-19-dood gestrand — claim pid {dood.pid} leeft niet sinds ≥ 0 min" in uit2.stderr
    assert "verweesd in lopend/ (run gestopt zonder afronding) → terug naar inbox/, poging 1/3" in uit2.stderr
    assert "CC HERSTART: 2026-09-19-dood" in _meldingen(werkplaats)
    assert (repo / "opdrachten" / "gedaan" / "2026-09-19-dood.md").is_file()


def test_status_toont_gestrand_bij_dode_claim_ouder_dan_grens(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    dood = subprocess.Popen(["/bin/sleep", "0"])
    dood.wait()
    (repo / "opdrachten" / "lopend" / "2026-09-19-oud.md").write_text("OPDRACHT\n", encoding="utf-8")
    (repo / "opdrachten" / "log" / "2026-09-19-oud.claim").write_text(f"{dood.pid}\n2026-09-19T08:00:00\n", encoding="utf-8")
    time.sleep(1.1)
    st = _rlz(werkplaats, "inbox", "status", CC_INBOX_GESTRAND_S="1")
    assert f"gestrand (claim pid {dood.pid} leeft niet, gestart 2026-09-19T08:00:00" in st.stdout and "nooit stil herstart" in st.stdout, st.stdout


# ---- (j2) één runner per repo -------------------------------------------------------------------------------------------


def test_twee_ticks_tegelijk_een_run_de_ander_stopt_zichtbaar(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    werkplaats["gedrag"].write_text("slaap 2", encoding="utf-8")
    _opdracht(werkplaats, "2026-09-19-a")
    _opdracht(werkplaats, "2026-09-19-b")
    procs = [subprocess.Popen(["bash", str(repo / "scripts" / "cc_inbox.sh")], cwd=repo, env=_env(werkplaats), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    uit = [p.communicate(timeout=60) for p in procs]
    starts = sum(o.count("cc_inbox: start ") for _, o in uit)
    assert starts == 1, uit
    ander = [e for _, e in uit if "cc_inbox: start " not in e][0]
    assert ("wacht — inbox-run actief" in ander) or ("runner-lock net gepakt door pid" in ander), ander
    assert len(list((repo / "opdrachten" / "gedaan").glob("*.md"))) == 1 and len(list((repo / "opdrachten" / "inbox").glob("*.md"))) == 1


def test_runner_lock_wordt_atomisch_genomen_en_dode_lock_weggedraaid(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    dood = subprocess.Popen(["/bin/sleep", "0"])
    dood.wait()
    (repo / "opdrachten" / ".lock").write_text(f"{dood.pid}\ninbox\n2026-09-19T01:00:00\n", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert f"verweesde lock (pid {dood.pid}, soort inbox, leeft niet) opgeruimd" in uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").is_file()
    assert not (repo / "opdrachten" / ".lock").exists() and not list((repo / "opdrachten").glob(".lock.dood.*"))
    code = SCRIPT.read_text(encoding="utf-8")
    assert "set -o noclobber; printf '%s\\ninbox\\n%s\\n'" in code and 'mv "$LOCK" "$LOCK.dood.$$"' in code


def test_twee_rlz_cc_starts_tegelijk_een_loopt_een_stopt_met_melding(werkplaats: dict[str, Path]) -> None:
    """Nameting rij 5 van de opdracht: twee `rlz cc`-starts tegelijk → één loopt, één wacht zichtbaar (stopt mét melding wie 'm heeft)."""
    werkplaats["gedrag"].write_text("slaap 2", encoding="utf-8")
    cmd = "source " + str(werkplaats["repo"] / "scripts" / "zsh" / "rlz.zsh").replace(" ", r"\ ") + "; rlz cc"
    procs = [subprocess.Popen(["zsh", "-c", cmd], cwd=werkplaats["repo"], env=_env(werkplaats), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    uit = [(p.communicate(timeout=60), p.returncode) for p in procs]
    gelopen = [u for u in uit if "stub-wakker" in u[0][0]]
    geweigerd = [u for u in uit if u[1] == 1]
    assert len(gelopen) == 1 and len(geweigerd) == 1, uit
    err = geweigerd[0][0][1]
    assert ("er loopt al een handmatige CC via rlz cc (pid" in err) or ("runner-lock net gepakt door een andere start" in err), err
    assert not (werkplaats["repo"] / "opdrachten" / ".lock").exists()


# ---- (j3) poort vóór einde -----------------------------------------------------------------------------------------------


def test_ongecommit_werk_na_claude_wordt_wip_branch_en_opdracht_blijft_in_lopend(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    head = _git(repo, "rev-parse", "HEAD")
    werkplaats["gedrag"].write_text("vuil", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 4, uit.stderr  # claude gaf 0, de run is niet af
    assert _git(repo, "rev-parse", "HEAD") == head, "main onaangeraakt"
    assert [r for r in _git(repo, "status", "--porcelain").splitlines() if not r.startswith("?? opdrachten/")] == [], "werkboom schoon (op de untracked opdrachten na)"
    assert (repo / "opdrachten" / "lopend" / "2026-09-19-test.md").is_file() and not (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").exists()
    wip = _git(repo, "rev-parse", "wip/2026-09-19-test")
    assert _git(repo, "show", f"{wip}:backend_nieuw.py") == "half werk"
    assert _git(repo, "show", f"{wip}:README.md") == "x\ngewijzigd"
    assert _git(repo, "rev-parse", f"{wip}^") == head
    assert "poort niet gehaald" in _git(repo, "log", "-1", "--format=%s", wip)
    marker = (repo / "opdrachten" / "log" / "2026-09-19-test.wip").read_text(encoding="utf-8").splitlines()
    assert marker[0] == "wip/2026-09-19-test" and wip.startswith(marker[1])
    log = _log(werkplaats)
    assert "poort niet gehaald — WIP op branch wip/2026-09-19-test" in log and "de volgende poging begint met git merge --squash wip/2026-09-19-test" in log
    assert "CC POORT NIET GEHAALD: 2026-09-19-test" in _meldingen(werkplaats)
    assert not (repo / "opdrachten" / "log" / "2026-09-19-test.claim").exists(), "claim weg = herstelpad direct"
    st = _rlz(werkplaats, "inbox", "status")
    assert "poort niet gehaald → WIP op wip/2026-09-19-test" in st.stdout and "wip-branch: wip/2026-09-19-test" in st.stdout, st.stdout


def test_volgende_poging_begint_met_de_wip_branch_in_de_startprompt(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    werkplaats["gedrag"].write_text("vuil", encoding="utf-8")
    _opdracht(werkplaats)
    assert _tick(werkplaats).returncode == 4
    werkplaats["gedrag"].write_text("prompt", encoding="utf-8")
    uit = _tick(werkplaats)  # herstel (e): terug naar inbox, poging 2, direct opgepakt
    assert uit.returncode == 0, uit.stderr
    assert "terug naar inbox/, poging 2/3" in uit.stderr
    prompt = werkplaats["prompt"].read_text(encoding="utf-8")
    assert "VORIGE POGING HAALDE DE POORT NIET" in prompt and "git merge --squash wip/2026-09-19-test" in prompt
    assert "Eindig NOOIT terwijl een suite of achtergrondtaak nog loopt" in prompt
    assert (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").is_file()
    assert not (repo / "opdrachten" / "log" / "2026-09-19-test.wip").exists(), "marker weg ná een afgeronde run"
    assert _git(repo, "rev-parse", "--verify", "wip/2026-09-19-test"), "branch blijft ter controle staan"
    assert "branch wip/2026-09-19-test blijft ter controle staan" in _log(werkplaats)


def test_zelf_naar_gedaan_zonder_commit_gaat_terug_naar_lopend(werkplaats: dict[str, Path]) -> None:
    """'af' zonder commit bestaat niet: zette claude het bestand zelf in gedaan/ maar liet werk ongecommit, dan gaat het terug
    naar lopend/ (zonder kopregel) en het werk naar de WIP-branch."""
    repo = werkplaats["repo"]
    werkplaats["gedrag"].write_text("vuil_gedaan", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 4, uit.stderr
    assert not (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").exists()
    assert (repo / "opdrachten" / "lopend" / "2026-09-19-test.md").read_text(encoding="utf-8") == "# OPDRACHT — test\n\ninhoud\n"
    assert "stond al in gedaan/ maar het werk is niet gecommit → terug naar lopend/" in _log(werkplaats)
    assert _git(repo, "show", "wip/2026-09-19-test:backend_nieuw.py") == "half werk"


def test_exit_0_zonder_rapport_commit_of_afmelding_is_geen_resultaat(werkplaats: dict[str, Path]) -> None:
    """Incident 19-09 16:12: de run eindigde met 'ik wacht op de melding' (code 0) en het script zette 'm mét 'rapport: geen' in gedaan/."""
    repo = werkplaats["repo"]
    werkplaats["gedrag"].write_text("niets", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 4, uit.stderr
    assert (repo / "opdrachten" / "lopend" / "2026-09-19-test.md").is_file() and not (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").exists()
    assert "GEEN RESULTAAT — claude eindigde met code 0 zonder rapport, zonder commit" in _log(werkplaats)
    assert "CC ZONDER RESULTAAT: 2026-09-19-test" in _meldingen(werkplaats)
    assert (repo / "opdrachten" / "log" / "2026-09-19-test.pogingen").read_text(encoding="utf-8").strip() == "1"


def test_afgeronde_run_met_rapport_en_commit_gaat_gewoon_naar_gedaan(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").read_text(encoding="utf-8").startswith("uitgevoerd ")
    assert "rapport: docs/rapporten/" in _log(werkplaats) and "CC klaar: 2026-09-19-test" in _meldingen(werkplaats)
    assert not _git(repo, "for-each-ref", "refs/heads/wip/")


def test_untracked_in_opdrachten_of_scratch_blokkeert_de_start_niet(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    (repo / ".scratch").mkdir()
    (repo / ".scratch" / "notitie.txt").write_text("x\n", encoding="utf-8")
    (repo / "opdrachten" / "gedaan" / "2026-09-18-oud.md").write_text("uitgevoerd 2026-09-18, rapport: geen\n", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "STOP — werkboom niet schoon" not in uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-19-test.md").is_file()


def test_untracked_buiten_opdrachten_bij_start_is_stop(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    (repo / "backend_half.py").write_text("half\n", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 0 and "STOP — werkboom niet schoon bij start (1 bestand(en): ?? backend_half.py" in uit.stderr, uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-19-test.md").is_file()


def test_scripts_documenteren_rij_j() -> None:
    code = SCRIPT.read_text(encoding="utf-8")
    for verwacht in ("(j1) LOCK PER OPDRACHT, ATOMISCH", "(j2) ÉÉN INBOX-RUNNER PER REPO", "(j3) EEN RUN EINDIGT PAS NÁ ZIJN POORT", "(j4) PUSH-CONFLICT",
                     "claim_opdracht()", "neem_runner_lock()", "wip_wegzetten()", "CC_INBOX_CLAIM_ALLEEN", "CC_INBOX_GESTRAND_S", "GEEN RESULTAAT"):
        assert verwacht in code, verwacht
    assert not re.search(r"^\s*git[^#\n]*\bstash\b", code, re.M), "nooit stash"
    zsh = RLZ_ZSH.read_text(encoding="utf-8")
    for verwacht in ("setopt noclobber", "runner-lock net gepakt", ".claim", "_rlz_push_stand", "origin gedivergeerd", "PUSH GEBLOKKEERD", "wip-branch:"):
        assert verwacht in zsh, verwacht
