"""Guard (cc-inbox parallelle-runs 16-09 nacht): nooit twee schrijvers in één werkboom.

Incident 16-09 avond: de inbox-run "omzet-store" (20:24–21:39) en een handmatige CC-sessie (gestart ná 20:24) werkten
parallel; de een committe het werk van de ander (57ca852, c1df300). De detectie van 15-09 (rij (f): `claude`-proces mét cwd
in de repo) was niet stuk — ze kijkt alleen bij de START van een inbox-run. Sinds 16-09 nacht (rij (g)):
  (g1) de lock `opdrachten/.lock` draagt pid / soort (`inbox`|`handmatig`) / starttijd; een levende `handmatig`-lock (gezet
       door `rlz cc`) = zichtbaar wachten;
  (g2) `.git/index.lock` = git bezig → wachten (verweesd ná CC_INBOX_INDEX_LOCK_MAX_S = melden, negeren);
  (g3) vuile werkboom bij start = LET-OP-regel, geen blokkade;
  omgekeerd: `rlz cc` weigert bij een levende `inbox`-lock en zet zelf de `handmatig`-lock; `rlz inbox stop` stuurt TERM.
Het échte script en de échte zsh-functie draaien tegen een wegwerp-repo mét stubs (`claude`, `osascript`); de pull staat uit.
"""

from __future__ import annotations

import os
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

# claude-stub: schrijft de inbox-lock zoals hij 'm op dát moment ziet naar $LOCK_CAPTURE (bewijs dat de wrapper 'm zette)
CLAUDE_STUB = r"""#!/bin/bash
if [[ -n "${LOCK_CAPTURE:-}" ]]; then cat "${LOCK_PAD:-/nonexistent}" > "$LOCK_CAPTURE" 2>/dev/null || echo "GEEN LOCK" > "$LOCK_CAPTURE"; fi
# een afgeronde run laat een rapport achter en commit (rij (j3) 19-09: ongecommit werk = WIP, geen rapport/commit = geen resultaat)
f="docs/rapporten/$(date +%F)-stub-$$.md"; mkdir -p docs/rapporten; echo "rapport stub" > "$f"
if git rev-parse --git-dir >/dev/null 2>&1; then git add -A -- docs >/dev/null 2>&1; git commit -qm "stub: rapport" >/dev/null 2>&1; fi
echo "stub-klaar"; exit 0
"""
OSASCRIPT_STUB = "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$MELDINGEN\"\nexit 0\n"


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
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=GIT_ENV)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "claude").write_text(CLAUDE_STUB, encoding="utf-8")
    (stubs / "osascript").write_text(OSASCRIPT_STUB, encoding="utf-8")
    for s in stubs.iterdir():
        s.chmod(0o755)
    return {"repo": repo, "stubs": stubs, "meldingen": tmp_path / "meldingen.txt", "capture": tmp_path / "lock_capture.txt"}


def _env(w: dict[str, Path], **extra: str) -> dict[str, str]:
    return {
        **GIT_ENV,
        "HOME": str(w["repo"].parent),
        "PATH": f"{w['stubs']}:{os.environ['PATH']}",
        "MELDINGEN": str(w["meldingen"]),
        "LOCK_PAD": str(w["repo"] / "opdrachten" / ".lock"),
        "RLZ_REPO": str(w["repo"]),
        **extra,
    }


def _tick(w: dict[str, Path], **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(w["repo"] / "scripts" / "cc_inbox.sh")],
        cwd=w["repo"], env=_env(w, **extra), capture_output=True, text=True, timeout=60,
    )


def _rlz(w: dict[str, Path], *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    cmd = "source " + str(w["repo"] / "scripts" / "zsh" / "rlz.zsh").replace(" ", r"\ ") + "; rlz " + " ".join(args)
    return subprocess.run(["zsh", "-c", cmd], cwd=w["repo"], env=_env(w, **extra), capture_output=True, text=True, timeout=60)


def _opdracht(w: dict[str, Path], slug: str = "2026-09-16-test") -> Path:
    p = w["repo"] / "opdrachten" / "inbox" / f"{slug}.md"
    p.write_text("OPDRACHT — test\n", encoding="utf-8")
    return p


def _meldingen(w: dict[str, Path]) -> str:
    return w["meldingen"].read_text(encoding="utf-8") if w["meldingen"].exists() else ""


@pytest.fixture
def vreemd_proces() -> subprocess.Popen[bytes]:
    """Een levend proces dat niet van deze tick is (simuleert de andere schrijver)."""
    proc = subprocess.Popen(["/bin/sleep", "60"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    yield proc
    proc.kill()
    proc.wait(timeout=5)


# ---- (g1) lock mét soort ------------------------------------------------------------------------------------------------


def test_handmatige_lock_met_vreemde_levende_pid_geen_start_zichtbaar(werkplaats: dict[str, Path], vreemd_proces) -> None:
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    (repo / "opdrachten" / ".lock").write_text(f"{vreemd_proces.pid}\nhandmatig\n2026-09-16T20:30:00\n", encoding="utf-8")
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert f"wacht — handmatige CC (rlz cc) actief (pid {vreemd_proces.pid}, sinds 2026-09-16T20:30:00)" in uit.stderr
    assert "geen herstel, geen pull, geen start" in uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-16-test.md").is_file()
    assert not (repo / "opdrachten" / "log" / "2026-09-16-test.log").exists()
    assert (repo / "opdrachten" / ".lock").read_text(encoding="utf-8").splitlines()[1] == "handmatig", "lock onaangeroerd"
    assert _meldingen(werkplaats) == ""


def test_inbox_lock_met_vreemde_levende_pid_wacht_zichtbaar(werkplaats: dict[str, Path], vreemd_proces) -> None:
    """Een levende `inbox`-lock = er loopt al een run: niets doen — sinds rij (j2) 19-09 mét één zichtbare wachtregel in het
    launchd-log (vóór 19-09 stil); nooit een tweede run op dezelfde werkboom."""
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    (repo / "opdrachten" / ".lock").write_text(f"{vreemd_proces.pid}\ninbox\n2026-09-16T20:24:06\n", encoding="utf-8")
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert f"wacht — inbox-run actief (pid {vreemd_proces.pid}, sinds 2026-09-16T20:24:06" in uit.stderr
    assert "geen tweede run op dezelfde werkboom" in uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-16-test.md").is_file() and not (repo / "opdrachten" / "log" / "2026-09-16-test.log").exists()
    assert (repo / "opdrachten" / "inbox" / "2026-09-16-test.md").is_file()


def test_dode_lock_met_soort_wordt_opgeruimd_en_nieuwe_lock_draagt_soort_en_tijd(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    dood = subprocess.Popen(["/bin/sleep", "0"])
    dood.wait()
    (repo / "opdrachten" / ".lock").write_text(f"{dood.pid}\nhandmatig\n2026-09-16T10:00:00\n", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats, LOCK_CAPTURE=str(werkplaats["capture"]))
    assert uit.returncode == 0, uit.stderr
    assert f"verweesde lock (pid {dood.pid}, soort handmatig, leeft niet) opgeruimd" in uit.stderr
    regels = werkplaats["capture"].read_text(encoding="utf-8").splitlines()  # lock zoals de claude-stub 'm zag
    assert len(regels) == 3 and regels[0].isdigit() and regels[1] == "inbox" and regels[2].startswith("20"), regels
    assert (repo / "opdrachten" / "gedaan" / "2026-09-16-test.md").is_file()
    assert not (repo / "opdrachten" / ".lock").exists()


# ---- (g2) git bezig -------------------------------------------------------------------------------------------------------


def test_git_index_lock_laat_de_tick_wachten_en_verweesd_wordt_gemeld_maar_niet_verwijderd(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    (repo / ".git" / "index.lock").write_text("", encoding="utf-8")
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "wacht — git bezig in deze werkboom (.git/index.lock" in uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-16-test.md").is_file()
    assert not (repo / "opdrachten" / ".lock").exists()
    # verweesd (ouder dan de grens): gemeld, genegeerd, NIET verwijderd — de run gaat door. De (stub-)run kan door de index.lock
    # niet committen → rij (j3) 19-09: poort niet gehaald, het werk gaat via een eigen tijdelijke index veilig naar wip/<slug>
    # (geen .git/index.lock nodig), de werkboom kan niet schoongemaakt worden (reset weigert) → LET OP, opdracht blijft in lopend/
    uit2 = _tick(werkplaats, CC_INBOX_INDEX_LOCK_MAX_S="0")
    assert uit2.returncode == 4, uit2.stderr
    assert "LET OP — .git/index.lock is" in uit2.stderr and "genegeerd (niet verwijderd" in uit2.stderr
    assert (repo / ".git" / "index.lock").exists(), "nooit verwijderd"
    assert "poort niet gehaald — WIP op branch wip/2026-09-16-test" in uit2.stderr and "werkboom niet schoongemaakt (git reset weigert" in uit2.stderr
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "wip/2026-09-16-test"], capture_output=True, env=GIT_ENV).returncode == 0
    assert (repo / "opdrachten" / "lopend" / "2026-09-16-test.md").is_file()


# ---- (g3) vuile werkboom = zichtbaar, geen blokkade ------------------------------------------------------------------------


def test_vuile_werkboom_bij_start_is_melding_plus_stop_niet_stil_overnemen(werkplaats: dict[str, Path]) -> None:
    """(g3) 16-09 was een LET-OP-regel + starten; sinds rij (j3) 19-09: ongecommit werk bij de start = melding + stop, de
    opdracht blijft in inbox/ tot een mens het werk commit of wegzet (een run laat sinds (j3) zelf nooit meer werk achter)."""
    repo = werkplaats["repo"]
    (repo / "README.md").write_text("gewijzigd door een gestopte run\n", encoding="utf-8")
    _opdracht(werkplaats)
    uit = _tick(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "STOP — werkboom niet schoon bij start (1 bestand(en):  M README.md" in uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-16-test.md").is_file(), "niet gestart"
    assert not (repo / "opdrachten" / "log" / "2026-09-16-test.log").exists()
    assert "CC-inbox gestopt: werkboom niet schoon" in _meldingen(werkplaats)
    assert not (repo / "opdrachten" / ".lock").exists(), "runner-lock weer vrij"
    # tweede tick binnen het uur: zelfde regel, geen tweede melding
    uit2 = _tick(werkplaats)
    assert "STOP — werkboom niet schoon" in uit2.stderr and _meldingen(werkplaats).count("werkboom niet schoon") == 1


# ---- omgekeerd: rlz cc + rlz inbox stop -----------------------------------------------------------------------------------


def test_rlz_cc_zet_handmatig_lock_met_pid_en_ruimt_op(werkplaats: dict[str, Path]) -> None:
    uit = _rlz(werkplaats, "cc", "--vlag", LOCK_CAPTURE=str(werkplaats["capture"]))
    assert uit.returncode == 0, uit.stderr
    regels = werkplaats["capture"].read_text(encoding="utf-8").splitlines()
    assert len(regels) == 3 and regels[0].isdigit() and regels[1] == "handmatig" and regels[2].startswith("20"), regels
    assert "inbox-lock gezet" in uit.stderr and "inbox-lock opgeruimd" in uit.stderr
    assert not (werkplaats["repo"] / "opdrachten" / ".lock").exists()
    assert "stub-klaar" in uit.stdout


def test_rlz_cc_weigert_bij_levende_inbox_lock_en_start_claude_niet(werkplaats: dict[str, Path], vreemd_proces) -> None:
    repo = werkplaats["repo"]
    (repo / "opdrachten" / ".lock").write_text(f"{vreemd_proces.pid}\ninbox\n2026-09-16T20:24:06\n", encoding="utf-8")
    uit = _rlz(werkplaats, "cc", LOCK_CAPTURE=str(werkplaats["capture"]))
    assert uit.returncode == 1
    assert f"inbox-run actief sinds 2026-09-16T20:24:06 (pid {vreemd_proces.pid}) — wacht of `rlz inbox stop`" in uit.stderr
    assert not werkplaats["capture"].exists(), "claude mag niet gestart zijn"
    assert (repo / "opdrachten" / ".lock").read_text(encoding="utf-8").splitlines()[1] == "inbox", "lock van de ander blijft"


def test_rlz_cc_ruimt_dode_lock_op_en_start(werkplaats: dict[str, Path]) -> None:
    dood = subprocess.Popen(["/bin/sleep", "0"])
    dood.wait()
    (werkplaats["repo"] / "opdrachten" / ".lock").write_text(f"{dood.pid}\ninbox\n2026-09-16T01:00:00\n", encoding="utf-8")
    uit = _rlz(werkplaats, "cc", LOCK_CAPTURE=str(werkplaats["capture"]))
    assert uit.returncode == 0, uit.stderr
    assert werkplaats["capture"].read_text(encoding="utf-8").splitlines()[1] == "handmatig"


def test_rlz_inbox_status_en_stop(werkplaats: dict[str, Path]) -> None:
    repo = werkplaats["repo"]
    assert "inbox-lock: geen (niets loopt)" in _rlz(werkplaats, "inbox", "status").stdout
    # een 'inbox-run' die op TERM stopt (zoals cc_inbox.sh via zijn trap)
    proc = subprocess.Popen(["/bin/sleep", "60"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        (repo / "opdrachten" / ".lock").write_text(f"{proc.pid}\ninbox\n2026-09-16T20:24:06\n", encoding="utf-8")
        st = _rlz(werkplaats, "inbox", "status")
        assert f"inbox-lock: inbox actief (pid {proc.pid}, sinds 2026-09-16T20:24:06)" in st.stdout
        uit = _rlz(werkplaats, "inbox", "stop")
        assert uit.returncode == 0, uit.stderr + uit.stdout
        assert f"inbox-run pid {proc.pid} gestopt" in uit.stdout
        for _ in range(50):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None, "TERM niet aangekomen"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    # een handmatige lock stopt `rlz inbox stop` niet (sluit de sessie zelf af)
    eigen = subprocess.Popen(["/bin/sleep", "60"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        (repo / "opdrachten" / ".lock").write_text(f"{eigen.pid}\nhandmatig\n2026-09-16T22:00:00\n", encoding="utf-8")
        uit = _rlz(werkplaats, "inbox", "stop")
        assert uit.returncode == 1 and "lock is van een handmatige sessie" in uit.stderr
        assert eigen.poll() is None
    finally:
        eigen.kill()
        eigen.wait(timeout=5)


def test_scripts_documenteren_de_guard() -> None:
    code = SCRIPT.read_text(encoding="utf-8")
    # 17-09 (rij h): de wachtregel is samengesteld — "wacht — $omschr" mét omschrijving "handmatige CC (rlz cc) actief (pid …"
    for verwacht in ("wacht — $omschr", "handmatige CC (rlz cc) actief (pid $pid, sinds", ".git/index.lock", "werkboom niet schoon bij start", "set -o noclobber; printf '%s\\ninbox\\n%s\\n'"):
        assert verwacht in code, verwacht
    zsh = RLZ_ZSH.read_text(encoding="utf-8")
    for verwacht in ("inbox-run actief sinds", "rlz inbox stop", "handmatig", "RLZ_REPO"):
        assert verwacht in zsh, verwacht


def test_rlz_inbox_vrijgeven_schrijft_de_pid_en_status_toont_de_vrijgave(werkplaats: dict[str, Path], vreemd_proces) -> None:
    """(h3) 17-09: `rlz inbox vrijgeven <pid>` = bewuste keuze van Peter; `rlz inbox status` toont 'm; een dode pid wordt geweigerd."""
    repo = werkplaats["repo"]
    uit = _rlz(werkplaats, "inbox", "vrijgeven", str(vreemd_proces.pid))
    assert uit.returncode == 0, uit.stderr
    assert f"pid {vreemd_proces.pid} vrijgegeven" in uit.stdout and "twee schrijvers in één werkboom" in uit.stdout
    vrijgave = (repo / "opdrachten" / ".vrijgave").read_text(encoding="utf-8").splitlines()
    assert vrijgave[0] == str(vreemd_proces.pid)
    status = _rlz(werkplaats, "inbox", "status")
    assert f"vrijgave: handmatige CC pid {vreemd_proces.pid} houdt de inbox niet tegen" in status.stdout
    dood = _rlz(werkplaats, "inbox", "vrijgeven", "999999")
    assert dood.returncode == 1 and "leeft niet" in dood.stderr
    assert "rlz inbox vrijgeven" in RLZ_ZSH.read_text(encoding="utf-8")


def test_rlz_inbox_status_toont_lopend_als_af_of_gestrand_nooit_als_loopt_zonder_lock(werkplaats: dict[str, Path]) -> None:
    """(i) 18-09 avond: `rlz inbox status` somt lopend/ op — een kopie die al in gedaan/ staat (kopregel 'uitgevoerd') = "af",
    zonder levende lock = "gestrand"; "loopt" verschijnt alleen bij een levende lock. Leeg = "lopend/: leeg"."""
    repo = werkplaats["repo"]
    uit = _rlz(werkplaats, "inbox", "status")
    assert uit.returncode == 0, uit.stderr
    assert "lopend/: leeg" in uit.stdout
    (repo / "opdrachten" / "lopend" / "2026-09-18-af.md").write_text("OPDRACHT — af\n", encoding="utf-8")
    (repo / "opdrachten" / "gedaan" / "2026-09-18-af.md").write_text("uitgevoerd 2026-09-18, rapport: geen\n\nOPDRACHT — af\n", encoding="utf-8")
    (repo / "opdrachten" / "lopend" / "2026-09-18-gestrand.md").write_text("OPDRACHT — gestrand\n", encoding="utf-8")
    uit = _rlz(werkplaats, "inbox", "status")
    assert uit.returncode == 0, uit.stderr
    assert "lopend/: 2026-09-18-af.md — af (staat in gedaan/" in uit.stdout
    assert "lopend/: 2026-09-18-gestrand.md — gestrand (geen levende lock" in uit.stdout
    assert "— loopt (" not in uit.stdout, "zonder levende lock toont geen lopend-bestand 'loopt'"
