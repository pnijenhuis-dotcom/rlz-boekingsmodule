"""Guard (BUG 21-09, BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP
(21-09)"): job `rlz-boek-wachtrij` faalde in productie zonder één regel uitvoer ("Application exec likely failed") —
deploy.yml maakte de job op 18-09 zélf aan zónder `--command`, de Dockerfile heeft geen ENTRYPOINT, en f3_jobs.sh zag 'm
daarna als "bestaat al". Regels: (1) élke `gcloud run jobs deploy` in deploy.yml draagt een expliciet `--command`
(python; rlz-migratie alembic) — de deploy is de canonieke config en erft niets van het bootstrap-script; (2) de
Dockerfile krijgt GEEN `ENTRYPOINT ["python"]` (dat zou de service-CMD `sh -c exec uvicorn …` tot `python sh -c …`
maken) — het startcommando van een job staat uitsluitend in de deploy; (3) ná de F3-lus start élke job in die lus één
keer mét `--smoketest` (`execute --wait`), zodat een job die niet start de deploy rood maakt (les 10-09 "service en jobs
uit de pas" geldt ook voor start-baarheid)."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEPLOY_YML = REPO / ".github" / "workflows" / "deploy.yml"
DOCKERFILE = REPO / "backend" / "Dockerfile"


def _shell_regels(tekst: str) -> str:
    return "\n".join(r for r in tekst.splitlines() if not r.lstrip().startswith("#"))


def _deploy_blokken(tekst: str) -> list[tuple[str, str]]:
    """(jobnaam, blok-tekst tot en met --quiet) per `gcloud run jobs deploy`."""
    uit: list[tuple[str, str]] = []
    for m in re.finditer(r"gcloud run jobs deploy\s+(\S+)", tekst):
        blok = tekst[m.start() :]
        blok = blok.split("--quiet", 1)[0]
        uit.append((m.group(1).strip('"'), blok))
    return uit


def test_elke_jobs_deploy_draagt_een_expliciet_command() -> None:
    tekst = _shell_regels(DEPLOY_YML.read_text(encoding="utf-8"))
    blokken = _deploy_blokken(tekst)
    assert len(blokken) >= 3, "verwacht rlz-migratie, de F3-lus en rlz-smoketest"
    zonder = [naam for naam, blok in blokken if not re.search(r"--command\s+\S+", blok)]
    assert zonder == [], f"`gcloud run jobs deploy` zonder --command (de job start dan niet — BUG 21-09): {zonder}"
    per_naam = {naam: re.search(r"--command\s+(\S+)", blok).group(1) for naam, blok in blokken}  # type: ignore[union-attr]
    assert per_naam["rlz-migratie"] == "alembic"
    assert per_naam["rlz-smoketest"] == "python"
    lus = [c for n, c in per_naam.items() if n.startswith('"${NAAM}') or n == "${NAAM}"]
    assert lus == ["python"], f"de F3-lus hoort `--command python` te dragen: {per_naam}"


def test_f3_lus_is_een_array_en_de_boek_wachtrij_staat_erin() -> None:
    tekst = DEPLOY_YML.read_text(encoding="utf-8")
    assert "F3_JOBS=(" in tekst and 'for JOB in "${F3_JOBS[@]}"; do' in tekst
    assert re.search(r'^\s*"rlz-boek-wachtrij\|boek-wachtrij-verwerken\|\d+"', tekst, flags=re.M)


def test_job_smoketest_start_elke_job_uit_de_lus_met_wait() -> None:
    tekst = _shell_regels(DEPLOY_YML.read_text(encoding="utf-8"))
    # Tweede lus over dezelfde array, één `execute --wait` per job mét de no-op-vlag.
    assert tekst.count('for JOB in "${F3_JOBS[@]}"; do') >= 2, "job-smoketest-lus over F3_JOBS ontbreekt"
    m = re.search(
        r'gcloud run jobs execute "\$\{NAAM\}"[^\n]*\n[^\n]*--args="\^\|\^-m\|app\.cli\|--smoketest\|\$\{CLI\}" --wait',
        tekst,
    )
    assert m, 'verwacht `gcloud run jobs execute "${NAAM}" … --args="^|^-m|app.cli|--smoketest|${CLI}" --wait`'
    # Eén job die niet start = stap rood (exit 1), nooit stil.
    assert re.search(r'\[ "\$\{FOUT\}" = "0" \] \|\| \{[^\n]*exit 1', tekst)
    assert "::error::job-smoketest" in tekst


def test_dockerfile_heeft_geen_entrypoint_en_houdt_de_service_cmd() -> None:
    regels = [r for r in DOCKERFILE.read_text(encoding="utf-8").splitlines() if not r.lstrip().startswith("#")]
    assert not any(r.strip().upper().startswith("ENTRYPOINT") for r in regels), (
        'geen ENTRYPOINT: `ENTRYPOINT ["python"]` maakt de service-CMD `python sh -c …`; '
        "het jobcommando staat in deploy.yml"
    )
    assert any(r.strip().startswith("CMD") and "uvicorn" in r for r in regels)


def test_cli_kent_de_smoketest_vlag() -> None:
    cli = (REPO / "backend" / "app" / "cli.py").read_text(encoding="utf-8")
    assert '"--smoketest"' in cli and "def _job_smoketest" in cli
    assert "if args.smoketest:" in cli
