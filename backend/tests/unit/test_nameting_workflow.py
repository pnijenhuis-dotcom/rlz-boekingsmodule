"""Guard (werkloop automatisch 14-09, besluit Peter 14-09): de nameting-workflow `.github/workflows/nameting.yml` is een
LEES-ONLY instrument onder het nameting-serviceaccount. Bewaakt: (1) uitsluitend `nameting@` als service_account (nooit
`deploy@`), (2) productie-aanroepen alleen via `scripts/gcp/nameting.sh` of `scripts/gcp/vgg_blok7_nameting.sh` — geen
directe `gcloud run jobs execute`/`gcloud run deploy`/`gcloud run jobs deploy` in de workflow, (3) de commit-stap raakt
alleen `verkenning/nameting-*.txt`, (4) dezelfde WIF-provider als deploy.yml, (5) `nameting_env.sh` slaat impersonatie
over onder GITHUB_ACTIONS=true, (6) (werkloop-nazorg 14-09) de oordeelregel in het commitbericht komt uit het rapport
van het GEDRAAIDE onderdeel — reconciliatie → `nameting-reconciliatie-<dd-mm>.txt`, anders replay — en zonder
oordeelregel staat er letterlijk "geen oordeelregel" (run f4c702c droeg de replay-regel bij een reconciliatie-
meting)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "nameting.yml"
DEPLOY = REPO / ".github" / "workflows" / "deploy.yml"
ENV_SH = REPO / "scripts" / "gcp" / "nameting_env.sh"
TOEGESTANE_SCRIPTS = ("scripts/gcp/nameting.sh", "scripts/gcp/vgg_blok7_nameting.sh")


def _tekst() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _run_stappen() -> list[str]:
    """De `run: |`-blokken (zonder PyYAML — geen extra testafhankelijkheid): alles ná `run: |` tot de volgende key op
    stap-niveau (`- name:`/`- uses:`/`env:`/`id:` op dezelfde of lagere inspringing)."""
    stappen: list[str] = []
    regels = _tekst().splitlines()
    i = 0
    while i < len(regels):
        m = re.match(r"^(\s*)run:\s*\|\s*$", regels[i])
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        blok: list[str] = []
        i += 1
        while i < len(regels) and (not regels[i].strip() or len(regels[i]) - len(regels[i].lstrip()) > indent):
            blok.append(regels[i])
            i += 1
        stappen.append("\n".join(blok))
    return stappen


def _code_regels() -> list[str]:
    """Alle run-regels zonder commentaar (een `#`-regel in de workflow mag `gcloud run jobs execute` wél noemen)."""
    regels: list[str] = []
    for run in _run_stappen():
        for regel in run.splitlines():
            kaal = regel.split("#", 1)[0].strip()
            if kaal:
                regels.append(kaal)
    return regels


def test_workflow_bestaat_met_schedule_en_dispatch_onderdeel() -> None:
    tekst = _tekst()
    assert re.search(r'schedule:\s*\n\s*- cron: "30 5 \* \* \*"', tekst), "dagelijks 05:30 UTC ontbreekt"
    assert "workflow_dispatch:" in tekst and "onderdeel:" in tekst
    assert re.search(r"options: \[alles, a, b, c, d, e, reconciliatie\]", tekst)
    assert len(_run_stappen()) >= 2, "verwacht minstens de meet- en de commit-stap als run-blok"


def test_auth_uitsluitend_nameting_sa_nooit_deploy() -> None:
    accounts = re.findall(r"service_account:\s*(\S+)", _tekst())
    assert accounts, "geen service_account in de workflow"
    for acc in accounts:
        assert acc.startswith("nameting@"), f"nameting-workflow mag alleen nameting@ gebruiken, niet {acc}"
    zonder_commentaar = "\n".join(r for r in _tekst().splitlines() if not r.lstrip().startswith("#"))
    assert "deploy@" not in zonder_commentaar, "deploy@ mag alleen in commentaar voorkomen"
    # geen SA-keys: geen credentials_json, geen key-bestand
    assert "credentials_json" not in zonder_commentaar


def test_zelfde_wif_provider_als_deploy_yml() -> None:
    def provider(tekst: str) -> str:
        m = re.search(r"workload_identity_provider:\s*(\S+)", tekst)
        assert m, "geen workload_identity_provider"
        return m.group(1)

    assert provider(_tekst()) == provider(DEPLOY.read_text(encoding="utf-8"))


def test_productie_aanroepen_alleen_via_de_nameting_scripts() -> None:
    fouten: list[str] = []
    for regel in _code_regels():
        if re.search(r"gcloud\s+run\s+(jobs\s+execute|deploy|jobs\s+deploy|jobs\s+update|services\s+update)", regel):
            fouten.append(regel)
        if re.search(r"gcloud\s+(sql|secrets|iam)\b", regel):
            fouten.append(regel)
    assert fouten == [], f"directe productie-aanroepen in nameting.yml (alleen via {TOEGESTANE_SCRIPTS}): {fouten}"
    aanroepen = [r for r in _code_regels() if "scripts/gcp/" in r]
    assert aanroepen, "de workflow roept geen nameting-script aan"
    for r in aanroepen:
        assert any(s in r for s in TOEGESTANE_SCRIPTS), f"onbekend script in de workflow: {r}"


def test_commit_stap_raakt_alleen_verkenning_nameting_txt() -> None:
    adds = [r for r in _code_regels() if re.match(r"git\s+add\b", r)]
    assert adds, "geen git add in de workflow"
    for r in adds:
        assert "verkenning/nameting-*.txt" in r, f"git add buiten verkenning/nameting-*.txt: {r}"
        assert not re.search(r"git\s+add\s+(-A|--all|\.)(\s|$)", r), f"git add -A/. verboden: {r}"
    assert re.search(r'user\.name\s+"nameting-bot"', _tekst())
    assert "nameting@rlz-boekhouding.iam.gserviceaccount.com" in _tekst()
    assert "--force" not in _tekst() and "push -f" not in _tekst()


def test_permissions_contents_write_en_id_token() -> None:
    m = re.search(r"^permissions:\n((?:  .*\n)+)", _tekst(), flags=re.M)
    assert m, "geen permissions-blok"
    regels = {r.split("#", 1)[0].strip() for r in m.group(1).splitlines() if r.strip()}
    assert regels == {"contents: write", "id-token: write"}, regels


def test_nameting_env_slaat_impersonatie_over_onder_github_actions() -> None:
    tekst = ENV_SH.read_text(encoding="utf-8")
    assert 'if [[ "${GITHUB_ACTIONS:-}" == "true" ]]' in tekst
    # de GitHub-tak zet geen impersonatie-vlag en raakt geen key-bestand
    tak = tekst.split('if [[ "${GITHUB_ACTIONS:-}" == "true" ]]', 1)[1].split("elif", 1)[0]
    assert "--impersonate-service-account" not in tak
    assert "activate-service-account" not in tak


# ---- (6) oordeelregel per gedraaid onderdeel ---------------------------------------------------------------------


def _oordeel_fragment() -> str:
    """Het stuk van de meet-stap vanaf de oordeel-berekening t/m de GITHUB_OUTPUT-regels — letterlijk uit de workflow,
    zodat de test het échte shellscript draait en niet een kopie."""
    meet = next(r for r in _run_stappen() if "OORDEEL_BRON" in r)
    regels = meet.splitlines()
    start = next(i for i, r in enumerate(regels) if "OORDEEL_BRON=" in r) - 1  # de if-regel erboven
    assert regels[start].strip().startswith('if [[ "$ONDERDEEL" == "reconciliatie" ]]'), regels[start]
    eind = next(i for i, r in enumerate(regels) if 'echo "oordeel=$OORDEEL"' in r)
    return "\n".join(regels[start : eind + 1])


def _draai_oordeel(tmp_path: Path, onderdeel: str, bestanden: dict[str, str]) -> str:
    (tmp_path / "verkenning").mkdir(exist_ok=True)
    for naam, inhoud in bestanden.items():
        (tmp_path / "verkenning" / naam).write_text(inhoud, encoding="utf-8")
    uit = tmp_path / "github_output"
    uit.write_text("", encoding="utf-8")
    script = "set -uo pipefail\nDATUM=14-09\n" + _oordeel_fragment()
    subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env={**os.environ, "ONDERDEEL": onderdeel, "GITHUB_OUTPUT": str(uit)},
        check=True,
        capture_output=True,
        text=True,
    )
    regels = dict(r.split("=", 1) for r in uit.read_text(encoding="utf-8").splitlines() if "=" in r)
    return regels["oordeel"]


REPLAY = "kop\n**Oordeel: GROEN ZONDER DOEL — groepstoets niet meetbaar**\n"
RECONCILIATIE_ZONDER = (
    "LEES-ONLY: geen run-rij\n71/71 administraties gecontroleerd, 0 afwijking(en) totaal\nLEES-ONLY afgerond\n"
)


def test_oordeel_reconciliatie_neemt_niet_de_replay_regel(tmp_path: Path) -> None:
    """De f4c702c-situatie: replay-rapport van vandaag aanwezig, maar het gedraaide onderdeel is reconciliatie."""
    oordeel = _draai_oordeel(
        tmp_path,
        "reconciliatie",
        {"nameting-vgg-replay-14-09.txt": REPLAY, "nameting-reconciliatie-14-09.txt": RECONCILIATIE_ZONDER},
    )
    assert "GROEN ZONDER DOEL" not in oordeel, oordeel
    assert oordeel.startswith("geen oordeelregel"), oordeel
    assert "2 rapport(en) van 14-09" in oordeel


def test_oordeel_reconciliatie_met_eigen_oordeelregel(tmp_path: Path) -> None:
    oordeel = _draai_oordeel(
        tmp_path,
        "reconciliatie",
        {
            "nameting-vgg-replay-14-09.txt": REPLAY,
            "nameting-reconciliatie-14-09.txt": "x\nOordeel: ROOD — 3 bevindingen\n",
        },
    )
    assert oordeel == "Oordeel: ROOD — 3 bevindingen"


@pytest.mark.parametrize("onderdeel", ["alles", "c", "a"])
def test_oordeel_overige_onderdelen_uit_replay(tmp_path: Path, onderdeel: str) -> None:
    oordeel = _draai_oordeel(
        tmp_path,
        onderdeel,
        {"nameting-vgg-replay-14-09.txt": REPLAY, "nameting-reconciliatie-14-09.txt": "Oordeel: ROOD — niet deze\n"},
    )
    assert oordeel == "Oordeel: GROEN ZONDER DOEL — groepstoets niet meetbaar"


def test_oordeel_zonder_rapport_is_geen_oordeelregel(tmp_path: Path) -> None:
    oordeel = _draai_oordeel(tmp_path, "alles", {})
    assert oordeel == "geen oordeelregel (0 rapport(en) van 14-09)"


def test_commitbericht_draagt_onderdeel_en_oordeel() -> None:
    assert re.search(r'git commit -m "nameting \$DATUM \$ONDERDEEL — \$OORDEEL"', _tekst())
    assert 'OORDEEL_BRON="verkenning/nameting-reconciliatie-$DATUM.txt"' in _tekst()
    assert 'OORDEEL_BRON="verkenning/nameting-vgg-replay-$DATUM.txt"' in _tekst()
