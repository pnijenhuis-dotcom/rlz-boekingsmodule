"""Guard (herstel cc-inbox 14-09 avond): élke stop van `scripts/cc_inbox.sh` geeft een logregel + melding, een lange run
draagt een hartslag, en een verweesde opdracht in lopend/ gaat bij de volgende tick terug naar inbox/ (begrensd aantal
pogingen, daarna opdrachten/mislukt/). Aanleiding: de veldwerkers-run van 15:17 stierf ná 22 min op een budgetlimiet;
het log droeg alleen de startregel en de opdracht bleef in lopend/ staan.

Het échte script draait tegen een wegwerp-git-repo mét stubs voor `claude` (gedrag via bestand `claude_gedrag`) en
`osascript` (registreert élke melding in `meldingen.txt`); de pull staat uit (CC_INBOX_GEEN_PULL=1).

Nazorg 15-09 (Cowork, incident 15-09 ochtend: handmatige CC-sessie + inbox-run parallel in dezelfde werkboom): een
`claude`-proces mét cwd in de repo = "wacht — handmatige CC actief" — geen herstel, geen pull, geen start. Gesimuleerd
met een symlink naar /bin/sleep onder de naam `claude` (pgrep -x ziet de procesnaam, lsof de cwd) — nooit een echte
claude."""

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
# een afgeronde run laat een rapport achter en commit (sinds rij (j3) 19-09: exit 0 zonder rapport/commit = "geen resultaat")
klaar() { f="docs/rapporten/$(date +%F)-stub-$$.md"; mkdir -p docs/rapporten; echo "rapport stub" > "$f"; if git rev-parse --git-dir >/dev/null 2>&1; then git add -A -- docs >/dev/null 2>&1; git commit -qm "stub: rapport" >/dev/null 2>&1; fi; }
case "$gedrag" in
  ok) klaar; echo "stub-klaar"; exit 0 ;;
  limiet) echo "You've hit your monthly spend limit. Switch to another model, or manage usage credits" \
             "at claude.ai/admin-settings/usage, to continue."; exit 1 ;;
  fout) echo "stub-fout"; exit 2 ;;
  slaap*) echo "stub-slaapt"; sleep "${gedrag#slaap }"; klaar; echo "stub-wakker"; exit 0 ;;
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
    (repo / "docs" / "rapporten" / "INDEX.md").write_text("# index\n", encoding="utf-8")
    # schone, gecommitte werkboom — sinds rij (j3) 19-09 stopt een tick op ongecommit werk buiten opdrachten/
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=GIT_ENV)
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
    assert uit.returncode == 0, uit.stderr
    assert f"wacht — inbox-run actief (pid {os.getpid()}, sinds ?" in uit.stderr, uit.stderr  # rij (j2) 19-09: zichtbaar, één regel
    assert "herstel" not in uit.stderr.replace("geen herstel", "") and "start " not in uit.stderr
    assert (repo / "opdrachten" / "lopend" / "2026-09-14-handmatig.md").is_file()
    assert _meldingen(werkplaats) == ""


def test_script_documenteert_elke_stop_en_kent_geen_stille_paden() -> None:
    code = SCRIPT.read_text(encoding="utf-8")
    for verwacht in (
        "trap 'bij_signaal TERM' TERM",
        "trap bij_exit EXIT",
        "herstel_verweesd",
        "handmatige_cc",
        "wacht — handmatige CC actief",
        "loopt nog",
        "LIMIET — claude.ai/admin-settings/usage",
        "opdrachten/mislukt/",
    ):
        assert verwacht in code, verwacht


# ---- nazorg 15-09: handmatige CC actief in deze werkboom → wachten ----------------------------------------


def _nep_claude(tmp_path: Path, cwd: Path) -> subprocess.Popen[bytes]:
    """Een proces mét procesnaam `claude` (symlink naar /bin/sleep) en de gegeven cwd — géén echte claude."""
    nep = tmp_path / "nep"
    nep.mkdir(exist_ok=True)
    link = nep / "claude"
    if not link.exists():
        link.symlink_to("/bin/sleep")
    proc = subprocess.Popen([str(link), "60"], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):  # wachten tot pgrep 'm ziet
        gezien = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True).stdout.split()
        if str(proc.pid) in gezien:
            return proc
        time.sleep(0.1)
    proc.kill()
    pytest.fail("nep-claude niet zichtbaar voor pgrep -x claude")


def test_handmatige_cc_in_werkboom_geen_herstel_pull_of_start(werkplaats: dict[str, Path], tmp_path: Path) -> None:
    """Een claude-proces mét cwd in de repo (hier: een submap) → logregel 'wacht', niets aangeraakt: de opdracht blijft
    in inbox/, een verweesde lopend-opdracht blijft in lopend/, geen lock, geen melding, geen pull-poging."""
    repo = werkplaats["repo"]
    (repo / "backend").mkdir()
    _opdracht(werkplaats)
    (repo / "opdrachten" / "lopend" / "2026-09-14-verweesd.md").write_text("OPDRACHT — verweesd\n", encoding="utf-8")
    proc = _nep_claude(tmp_path, repo / "backend")
    try:
        # pull AAN (geen CC_INBOX_GEEN_PULL) — zonder remote zou een pull-poging een 'pull overgeslagen'-regel geven
        uit = _draai(werkplaats, CC_INBOX_GEEN_PULL="")
        assert uit.returncode == 0, uit.stderr
        assert f"wacht — handmatige CC actief (pid {proc.pid}, {repo.resolve() / 'backend'})" in uit.stderr, uit.stderr
        assert "geen herstel, geen pull, geen start" in uit.stderr
        assert "pull" not in uit.stderr.replace("geen pull", ""), uit.stderr
        assert (repo / "opdrachten" / "inbox" / "2026-09-14-test.md").is_file()
        assert (repo / "opdrachten" / "lopend" / "2026-09-14-verweesd.md").is_file()
        assert not (repo / "opdrachten" / ".lock").exists()
        assert not (repo / "opdrachten" / "log" / "2026-09-14-test.log").exists()
        assert _meldingen(werkplaats) == ""
        # tweede tick, proces leeft nog: opnieuw wachten
        uit2 = _draai(werkplaats)
        assert uit2.returncode == 0 and "wacht — handmatige CC actief" in uit2.stderr
    finally:
        proc.kill()
        proc.wait(timeout=5)
    # proces weg → volgende tick pakt gewoon op (verweesde eerst terug naar inbox, dan de oudste)
    uit3 = _draai(werkplaats)
    assert uit3.returncode == 0, uit3.stderr
    assert "wacht — handmatige CC actief" not in uit3.stderr
    assert "verweesd in lopend/" in uit3.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file() or (
        repo / "opdrachten" / "gedaan" / "2026-09-14-verweesd.md"
    ).is_file()


def test_claude_in_andere_map_houdt_de_inbox_niet_op(werkplaats: dict[str, Path], tmp_path: Path) -> None:
    ergens_anders = tmp_path / "ander-project"
    ergens_anders.mkdir()
    _opdracht(werkplaats)
    proc = _nep_claude(tmp_path, ergens_anders)
    try:
        uit = _draai(werkplaats)
    finally:
        proc.kill()
        proc.wait(timeout=5)
    assert uit.returncode == 0, uit.stderr
    assert "wacht — handmatige CC actief" not in uit.stderr
    assert (werkplaats["repo"] / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file()


def test_onleesbare_cwd_telt_als_actief_fail_closed(werkplaats: dict[str, Path], tmp_path: Path) -> None:
    """Faalt lsof (stub op PATH die exit 1 geeft), dan is de cwd van een claude-proces niet te lezen → dat proces
    telt als actief: wachten mét de reden in de logregel, liever een tick te laat dan twee runs door elkaar. Welk
    claude-proces het eerst gezien wordt (het nep-proces of een echte sessie elders op deze Mac) doet er niet toe —
    de pid staat erbij. CC_INBOX_CLAUDE_NAAM is de seam voor de procesnaam (default `claude`)."""
    repo = werkplaats["repo"]
    (werkplaats["stubs"] / "lsof").write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    (werkplaats["stubs"] / "lsof").chmod(0o755)
    _opdracht(werkplaats)
    proc = _nep_claude(tmp_path, repo)
    try:
        uit = _draai(werkplaats, CC_INBOX_CLAUDE_NAAM="claude")
    finally:
        proc.kill()
        proc.wait(timeout=5)
    assert uit.returncode == 0, uit.stderr
    assert "wacht — handmatige CC actief (pid " in uit.stderr, uit.stderr
    assert "cwd niet leesbaar (lsof ontbreekt of faalt) — telt als actief" in uit.stderr, uit.stderr
    assert (repo / "opdrachten" / "inbox" / "2026-09-14-test.md").is_file()
    assert not (repo / "opdrachten" / ".lock").exists()


def test_seam_procesnaam_andere_naam_ziet_de_nep_claude_niet(werkplaats: dict[str, Path], tmp_path: Path) -> None:
    """CC_INBOX_CLAUDE_NAAM stuurt pgrep -x: met een niet-bestaande naam is er per definitie geen handmatige CC en pakt
    de tick de opdracht gewoon op, ook al leeft het nep-claude-proces in de repo."""
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    proc = _nep_claude(tmp_path, repo)
    try:
        uit = _draai(werkplaats, CC_INBOX_CLAUDE_NAAM="cc-inbox-bestaat-niet")
    finally:
        proc.kill()
        proc.wait(timeout=5)
    assert uit.returncode == 0, uit.stderr
    assert "wacht — handmatige CC actief" not in uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file()


# ---- rij (h) 17-09: wachten op een handmatige CC is nooit stil ---------------------------------------------------------


def test_wachtregel_draagt_duur_en_aantal_klare_opdrachten_en_meldt_na_de_drempel(werkplaats: dict[str, Path], tmp_path: Path) -> None:
    """Incident 17-09 (08:19 → 15:20: zes opdrachten klaar, elke tick "wacht — handmatige CC actief (pid 82714, …)", niemand
    zag het): (h1) de regel noemt sinds/duur en het aantal klare opdrachten, (h2) ná CC_INBOX_WACHT_MELDING_S één macOS-
    melding mét de handeling, herhaald op z'n vroegst ná CC_INBOX_WACHT_HERHAAL_S; de stand staat in log/.wacht-<pid>."""
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    _opdracht(werkplaats, "2026-09-14-twee")
    proc = _nep_claude(tmp_path, repo)
    try:
        # drempel 0 s → de eerste tick meldt al; herhaal 3600 s → de tweede tick meldt niet opnieuw
        uit = _draai(werkplaats, CC_INBOX_WACHT_MELDING_S="0", CC_INBOX_WACHT_HERHAAL_S="3600")
        assert uit.returncode == 0, uit.stderr
        assert f"wacht — handmatige CC actief (pid {proc.pid}, {repo.resolve()})" in uit.stderr
        assert "2 opdracht(en) klaar in inbox/" in uit.stderr and "sinds " in uit.stderr and "(0 min)" in uit.stderr
        stand = repo / "opdrachten" / "log" / f".wacht-{proc.pid}"
        assert stand.is_file() and len(stand.read_text().split()) == 2
        meldingen = _meldingen(werkplaats)
        assert f"CC-inbox wacht al 0 min op handmatige CC (pid {proc.pid})" in meldingen
        assert "2 opdracht(en) klaar in inbox/" in meldingen and "rlz inbox vrijgeven" in meldingen
        uit2 = _draai(werkplaats, CC_INBOX_WACHT_MELDING_S="0", CC_INBOX_WACHT_HERHAAL_S="3600")
        assert uit2.returncode == 0 and "wacht — handmatige CC actief" in uit2.stderr
        assert _meldingen(werkplaats).count("CC-inbox wacht al") == 1, "herhaalmelding vóór de herhaaldrempel"
        # standaarddrempel (1800 s) → géén melding bij een korte wacht, wél de regel
        (repo / "opdrachten" / "log" / f".wacht-{proc.pid}").unlink()
        werkplaats["meldingen"].unlink()
        uit3 = _draai(werkplaats)
        assert "wacht — handmatige CC actief" in uit3.stderr and _meldingen(werkplaats) == ""
    finally:
        proc.kill()
        proc.wait(timeout=5)
    # weg → de tick pakt op én ruimt de wachtstand op
    uit4 = _draai(werkplaats)
    assert uit4.returncode == 0 and "wacht — handmatige CC" not in uit4.stderr
    assert not list((repo / "opdrachten" / "log").glob(".wacht-*"))


def test_vrijgave_door_peter_laat_de_inbox_naast_de_handmatige_sessie_starten(werkplaats: dict[str, Path], tmp_path: Path) -> None:
    """(h3) opdrachten/.vrijgave mét de pid = bewuste keuze van Peter (`rlz inbox vrijgeven`): die pid blokkeert niet meer,
    de logregel zegt dat het risico aanvaard is; een andere pid blokkeert nog wél; een dode pid = bestand weg."""
    repo = werkplaats["repo"]
    _opdracht(werkplaats)
    proc = _nep_claude(tmp_path, repo)
    try:
        (repo / "opdrachten" / ".vrijgave").write_text(f"{proc.pid + 100000}\n2026-09-17T15:00:00\n", encoding="utf-8")
        uit = _draai(werkplaats)
        assert "wacht — handmatige CC actief" in uit.stderr, "een andere (dode) pid geeft geen vrijgave"
        assert not (repo / "opdrachten" / ".vrijgave").exists(), "vrijgave van een dode pid wordt opgeruimd"
        (repo / "opdrachten" / ".vrijgave").write_text(f"{proc.pid}\n2026-09-17T15:00:00\n", encoding="utf-8")
        uit2 = _draai(werkplaats)
        assert uit2.returncode == 0, uit2.stderr
        assert f"handmatige CC (pid {proc.pid}, {repo.resolve()}) vrijgegeven door Peter (rlz inbox vrijgeven)" in uit2.stderr
        assert "risico bewust aanvaard" in uit2.stderr
        assert (repo / "opdrachten" / "gedaan" / "2026-09-14-test.md").is_file()
        assert (repo / "opdrachten" / ".vrijgave").is_file(), "de vrijgave blijft zolang de sessie leeft"
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_script_documenteert_rij_h() -> None:
    tekst = SCRIPT.read_text(encoding="utf-8")
    for fragment in ("(h1)", "(h2)", "(h3)", "CC_INBOX_WACHT_MELDING_S", "CC_INBOX_WACHT_HERHAAL_S", "rlz inbox vrijgeven", "opdrachten/.vrijgave", "pid 82714"):
        assert fragment in tekst, fragment


# ---- regels per domein met LEESPLICHT (Peter 17-09) -------------------------------------------------------------------------

PROMPT_STUB = r"""#!/bin/bash
printf '%s\n' "$@" > "$PROMPT_CAPTURE"
f="docs/rapporten/$(date +%F)-stub-$$.md"; mkdir -p docs/rapporten; echo "rapport stub" > "$f"
if git rev-parse --git-dir >/dev/null 2>&1; then git add -A -- docs >/dev/null 2>&1; git commit -qm "stub: rapport" >/dev/null 2>&1; fi
echo "stub-klaar"; exit 0
"""


def _met_prompt_stub(w: dict[str, Path]) -> Path:
    (w["stubs"] / "claude").write_text(PROMPT_STUB, encoding="utf-8")
    (w["stubs"] / "claude").chmod(0o755)
    (w["repo"] / "docs" / "regels").mkdir(parents=True, exist_ok=True)
    (w["repo"] / "docs" / "regels" / "bank.md").write_text("# Regels — Bank\n", encoding="utf-8")
    (w["repo"] / "docs" / "regels" / "omzet.md").write_text("# Regels — Omzet\n", encoding="utf-8")
    (w["repo"] / "docs" / "regels" / "INDEX.md").write_text("# index\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(w["repo"]), "add", "-A"], check=True, env=GIT_ENV)  # schone werkboom bij start (rij j3)
    subprocess.run(["git", "-C", str(w["repo"]), "commit", "-qm", "regels"], check=True, env=GIT_ENV)
    return w["repo"].parent / "prompt_capture.txt"


def test_domeinen_kopregel_geeft_leesplicht_in_de_startprompt(werkplaats: dict[str, Path]) -> None:
    capture = _met_prompt_stub(werkplaats)
    p = _opdracht(werkplaats)
    p.write_text("# OPDRACHT — test\nDomeinen: bank, `omzet`, onbekend-domein\n\ninhoud\n", encoding="utf-8")
    uit = _draai(werkplaats, PROMPT_CAPTURE=str(capture))
    assert uit.returncode == 0, uit.stderr
    prompt = capture.read_text(encoding="utf-8")
    assert "LEESPLICHT (Domeinen-kopregel): lees EERST volledig" in prompt
    assert "docs/regels/bank.md, docs/regels/omzet.md" in prompt and "onbekend-domein" not in prompt.split("LEESPLICHT", 1)[1].split("\n", 1)[0]
    assert '## Gelezen regels' in prompt and "test_rapporten_gelezen_regels.py" in prompt
    assert "leesplicht uit de kopregel Domeinen: docs/regels/bank.md, docs/regels/omzet.md" in uit.stderr


def test_zonder_domeinen_kopregel_leidt_cc_de_domeinen_af_via_de_index(werkplaats: dict[str, Path]) -> None:
    capture = _met_prompt_stub(werkplaats)
    _opdracht(werkplaats)
    uit = _draai(werkplaats, PROMPT_CAPTURE=str(capture))
    assert uit.returncode == 0, uit.stderr
    prompt = capture.read_text(encoding="utf-8")
    assert "LEESPLICHT (geen of onbekende Domeinen-kopregel): leid de domeinen af" in prompt and "docs/regels/INDEX.md" in prompt
    assert "geen (geldige) Domeinen-kopregel" in uit.stderr


def test_lopend_kopie_van_afgeronde_opdracht_wordt_opgeruimd_en_nooit_herstart(werkplaats: dict[str, Path]) -> None:
    """(i) 18-09 avond (inbox-hygiëne): een .md in lopend/ die al in gedaan/ staat mét kopregel 'uitgevoerd …' is werk dat AF
    is (handmatige/parallelle run kopieerde naar gedaan/ zonder lopend/ op te ruimen). De tick ruimt de kopie op mét
    logregel en start NIETS opnieuw — vóór de fix ging zo'n bestand terug naar inbox/ en draaide afgerond werk tot drie keer
    opnieuw."""
    repo = werkplaats["repo"]
    lopend = repo / "opdrachten" / "lopend" / "2026-09-18-af.md"
    lopend.write_text("OPDRACHT — af\n", encoding="utf-8")
    (repo / "opdrachten" / "gedaan" / "2026-09-18-af.md").write_text(
        "uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-af.md\n\nOPDRACHT — af\n", encoding="utf-8"
    )
    (repo / "opdrachten" / "log" / "2026-09-18-af.pogingen").write_text("2\n", encoding="utf-8")
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert not lopend.exists(), "kopie in lopend/ moet weg zijn"
    assert not (repo / "opdrachten" / "inbox" / "2026-09-18-af.md").exists(), "nooit terug naar inbox/"
    assert not (repo / "opdrachten" / "log" / "2026-09-18-af.pogingen").exists(), "teller weg"
    assert (repo / "opdrachten" / "gedaan" / "2026-09-18-af.md").is_file()
    assert "al afgerond (opdrachten/gedaan/ mét kopregel 'uitgevoerd') → kopie in lopend/ opgeruimd, geen herstart" in uit.stderr
    assert "CC HERSTART" not in _meldingen(werkplaats) and "start 2026-09-18-af" not in uit.stderr


def test_lopend_zonder_gedaan_kopregel_blijft_het_herstelpad_volgen(werkplaats: dict[str, Path]) -> None:
    """Tegenproef (i): een gedaan/-bestand ZONDER de kopregel 'uitgevoerd' (bv. handmatig neergezet) telt niet als af — de
    verweesde lopend-opdracht gaat gewoon terug naar inbox/ en wordt opgepakt (bestaand gedrag (e))."""
    repo = werkplaats["repo"]
    (repo / "opdrachten" / "lopend" / "2026-09-18-niet-af.md").write_text("OPDRACHT — niet af\n", encoding="utf-8")
    (repo / "opdrachten" / "gedaan" / "2026-09-18-niet-af.md").write_text("OPDRACHT — niet af (zonder kopregel)\n", encoding="utf-8")
    uit = _draai(werkplaats)
    assert uit.returncode == 0, uit.stderr
    assert "verweesd in lopend/ (run gestopt zonder afronding) → terug naar inbox/, poging 1/3" in uit.stderr
    assert "start 2026-09-18-niet-af" in uit.stderr
    assert (repo / "opdrachten" / "gedaan" / "2026-09-18-niet-af.md").read_text(encoding="utf-8").startswith("uitgevoerd ")
