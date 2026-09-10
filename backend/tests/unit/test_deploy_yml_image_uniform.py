"""Guard (ochtendrun 11-09 blok 2.3): service en álle Cloud Run-jobs in .github/workflows/deploy.yml komen van
ÉÉN beeld-variabele — `"${IMAGE}:${GITHUB_SHA}"` — nooit een afwijkend pad of een vaste tag per job. Plus de
blok-2.2-besluiten: geen `--allow-unauthenticated`-vlag meer (IAM-binding staat; smoketest toetst publiek 200),
de deploy-drift-probe en de smoketest dragen BEWAKING_SERVICE_RESOURCE, en een rode run mailt het beheer
(`if: failure()` → job rlz-bewaking `deploy-mislukt`)."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEPLOY_YML = REPO / ".github" / "workflows" / "deploy.yml"
VERPLICHT_BEELD = '"${IMAGE}:${GITHUB_SHA}"'
#: Jobs die de deploy-drift-probe in productie vergelijkt — allemaal uit deze workflow (F3-lus + losse blokken).
VERWACHTE_JOBS = {
    "rlz-migratie",
    "rlz-sync",
    "rlz-reconciliatie",
    "rlz-intake-imap",
    "rlz-accordeur-herinneringen",
    "rlz-nieuwe-facturen",
    "rlz-kantoor-digest",
    "rlz-projecten-cijfers",
    "rlz-bank-sync",
    "rlz-extractie-wachtrij",
    "rlz-eerste-sync",
    "rlz-terugkerend-herbereken",
    "rlz-bewaking",
    "rlz-webhook-afleveraar",
    "rlz-smoketest",
}


def _tekst() -> str:
    return DEPLOY_YML.read_text(encoding="utf-8")


def _commando_regels(tekst: str) -> list[str]:
    """Alleen shell-regels (geen YAML-commentaar)."""
    return [r for r in tekst.splitlines() if not r.lstrip().startswith("#")]


def test_elke_image_vlag_is_dezelfde_variabele() -> None:
    beelden = re.findall(r"--image\s+(\S+)", "\n".join(_commando_regels(_tekst())))
    assert len(beelden) >= 5, beelden
    assert set(beelden) == {VERPLICHT_BEELD}, f"afwijkend beeld in deploy.yml: {set(beelden) - {VERPLICHT_BEELD}}"


def test_service_en_alle_jobs_worden_uitgerold() -> None:
    tekst = "\n".join(_commando_regels(_tekst()))
    assert re.search(r"gcloud run deploy rlz-backend\b", tekst)
    jobs_los = set(re.findall(r"gcloud run jobs deploy\s+(rlz-[a-z-]+)", tekst))
    lus = set(re.findall(r'^\s*"(rlz-[a-z-]+)\|[a-z-]+\|\d+"', tekst, flags=re.M))
    assert lus, "F3-lus met job|cli|timeout-regels niet gevonden"
    gevonden = jobs_los | lus
    assert gevonden >= VERWACHTE_JOBS, f"jobs zonder deploy-stap: {VERWACHTE_JOBS - gevonden}"
    # Elke `gcloud run jobs deploy`/`gcloud run deploy` draagt de beeld-vlag (geen job zonder --image).
    blokken = re.split(r"gcloud run (?:jobs )?deploy ", tekst)[1:]
    for blok in blokken:
        kop = blok.split("\n", 1)[0]
        assert "--image" in blok.split("--quiet", 1)[0], f"deploy-blok zonder --image: {kop}"


def test_geen_allow_unauthenticated_vlag_meer() -> None:
    regels = [r for r in _commando_regels(_tekst()) if "--allow-unauthenticated" in r]
    assert regels == [], "de allUsers-binding staat eenmalig (f2_services.sh); de vlag faalde dagelijks op setIamPolicy"


def test_smoketest_toetst_publiek_200_en_zelfde_beeld() -> None:
    tekst = _tekst()
    assert 'PUBLIEK="$(curl' in tekst and '[ "${PUBLIEK}" = "200" ]' in tekst
    # De smoketest-job én de bewaking dragen de service-resource voor de drift-toets.
    envs = re.findall(
        r"BEWAKING_SERVICE_RESOURCE=projects/\$\{PROJECT_ID\}/locations/\$\{REGION\}/services/rlz-backend", tekst
    )
    assert len(envs) >= 2, "BEWAKING_SERVICE_RESOURCE hoort op rlz-bewaking én rlz-smoketest"


def test_rode_run_mailt_het_beheer_via_de_bewakingsjob() -> None:
    tekst = _tekst()
    m = re.search(r"if: failure\(\)\n\s+run: \|\n(?P<body>(?:\s{10,}.*\n)+)", tekst)
    assert m, "geen `if: failure()`-stap"
    body = m.group("body")
    assert "gcloud run jobs execute rlz-bewaking" in body and "deploy-mislukt" in body
    assert "github.run_id" in body, "de mail hoort de run-URL te dragen"
    # Args-override met eigen scheidingsteken: het teken mag in geen waarde voorkomen (les 10-09).
    args = re.search(r'--args="\^(.)\^(.*?)" ', body)
    assert args and args.group(1) == "|", "args-override hoort het ^|^-scheidingsteken te dragen"
    assert "^" not in args.group(2) and all(deel for deel in args.group(2).split("|")), args.group(2)
