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
    assert re.search(
        r"options: \[alles, a, b, c, d, e, reconciliatie, btw-default, doorbelasting-aansluiting, app-bundels, query, projecten-afgesloten\]",
        tekst,
    )
    # Feiten eerst 17-09 (blok D): onderdeel `query` = db-lezen-rapport (input `query`), nooit --sql/--als via de workflow.
    assert re.search(r"query:\s*\n\s*description:", tekst) and "--(sql|als)" in tekst
    assert len(_run_stappen()) >= 2, "verwacht minstens de meet- en de commit-stap als run-blok"


def test_elk_dispatch_onderdeel_staat_in_de_keuzelijst() -> None:
    """Nameting 19-09: `gh workflow run nameting -f onderdeel=projecten-afgesloten` gaf HTTP 422 — het onderdeel stond in de
    if-takken en de beschrijving, maar niet in `options:` (een choice-input weigert élke andere waarde, ook via nameting.sh zonder
    TTY). Élk onderdeel dat de run-stap toetst moet in de keuzelijst staan."""
    tekst = _tekst()
    m = re.search(r"options: \[([^\]]+)\]", tekst)
    assert m, "options-lijst ontbreekt"
    opties = {o.strip() for o in m.group(1).split(",")}
    gebruikt = set(re.findall(r'"\$ONDERDEEL" (?:==|!=) "([a-z-]+)"', tekst))
    assert gebruikt, "geen $ONDERDEEL-vergelijkingen gevonden"
    assert gebruikt <= opties, f"onderdelen zonder keuze-optie (dispatch geeft 422): {sorted(gebruikt - opties)}"


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
    """De bot staget uitsluitend `verkenning/nameting-*.txt` en (Feiten eerst 17-09) `verkenning/lezen-*.txt` — via een
    nullglob-array, want een pathspec zonder treffer maakt `git add` fataal (bot-commit rood op 17-09 zodra er geen
    lezen-rapport lag; de meting was klaar, het bestand kwam nooit op main)."""
    code = _code_regels()
    adds = [r for r in code if re.search(r"git\s+add\b", r)]
    assert adds, "geen git add in de workflow"
    for r in adds:
        assert re.search(r'git\s+add\s+--\s+"\$\{UITKOMSTEN\[@\]\}"', r.strip()), f"git add hoort de nullglob-array te stagen: {r}"
        assert not re.search(r"git\s+add\s+(-A|--all|\.)(\s|$)", r), f"git add -A/. verboden: {r}"
    arr = [r for r in code if re.match(r"UITKOMSTEN=\(", r.strip())]
    assert len(arr) == 1, "precies één UITKOMSTEN-array"
    assert re.fullmatch(r"UITKOMSTEN=\(verkenning/nameting-\*\.txt verkenning/lezen-\*\.txt\)", arr[0].strip()), arr[0]
    assert any(r.strip() == "shopt -s nullglob" for r in code), "nullglob ontbreekt — een leeg glob-patroon wordt anders letterlijk gestaged"
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


# ---- (7) onderdeel doorbelasting-aansluiting (nameting 17-09) -----------------------------------------------------------


def test_onderdeel_doorbelasting_aansluiting_alleen_op_verzoek_en_lees_only() -> None:
    """De KF-aansluiting is een dispatch-onderdeel (niet in "alles": het dagelijkse reconciliatieblok draait hetzelfde), roept
    uitsluitend nameting.sh aan met de lees-only CLI en schrijft naar verkenning/nameting-doorbelasting-aansluiting-<dd-mm>.txt."""
    meet = next(r for r in _run_stappen() if "OORDEEL_BRON" in r)
    assert 'if [[ "$ONDERDEEL" == "doorbelasting-aansluiting" ]]; then' in meet
    assert 'scripts/gcp/nameting.sh doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026' in meet
    assert 'UIT="verkenning/nameting-doorbelasting-aansluiting-$DATUM.txt"' in meet
    # "alles" slaat het onderdeel over: de vgg-tak én de reconciliatie-/btw-takken kennen het niet als "alles"-lid
    assert '"$ONDERDEEL" != "doorbelasting-aansluiting"' in meet
    assert '"$ONDERDEEL" == "alles" || "$ONDERDEEL" == "doorbelasting-aansluiting"' not in meet
    # Cloud Logging lezen mag (logging.viewer), schrijven/uitvoeren niet — gedekt door test_productie_aanroepen_alleen_via_de_nameting_scripts
    assert 'resource.labels.job_name="rlz-sync"' in meet


# ---- (8) onderdeel app-bundels (OTA-nameting 17-09) ---------------------------------------------------------------------


def test_onderdeel_app_bundels_alleen_op_verzoek_en_lees_only(tmp_path: Path) -> None:
    """OTA-nameting: alleen op verzoek (niet in 'alles'), de bundellijst uitsluitend via nameting.sh (lees-only CLI), het
    publieke manifest + de 426-poort via curl, uitkomst in verkenning/nameting-app-bundels-<dd-mm>.txt mét eigen oordeelregel
    die het commitbericht overneemt."""
    meet = next(r for r in _run_stappen() if "OORDEEL_BRON" in r)
    assert 'if [[ "$ONDERDEEL" == "app-bundels" ]]; then' in meet
    assert "scripts/gcp/nameting.sh app-bundels" in meet
    assert 'UIT="verkenning/nameting-app-bundels-$DATUM.txt"' in meet
    assert '"$ONDERDEEL" != "app-bundels"' in meet, "app-bundels moet buiten de VGG-tak blijven"
    assert '"$ONDERDEEL" == "alles" || "$ONDERDEEL" == "app-bundels"' not in meet, "niet in 'alles'"
    assert "/app/update-manifest?runtime=$RUNTIME&platform=ios" in meet
    assert "-H 'X-Native-Client: 1' -H 'X-App-Versie: 0.9'" in meet
    assert "frontend/src/accordeur/appVersie.ts" in meet, "runtime uit dezelfde bron als de deploy-stap"
    assert 'OORDEEL_BRON="verkenning/nameting-app-bundels-$DATUM.txt"' in meet
    oordeel = _draai_oordeel(
        tmp_path,
        "app-bundels",
        {
            "nameting-app-bundels-14-09.txt": "kop\nOordeel: geen bundel voor runtime 1.1 — bucket-stap nog niet gelopen\n",
            "nameting-vgg-replay-14-09.txt": REPLAY,
        },
    )
    assert oordeel.startswith("Oordeel: geen bundel voor runtime 1.1"), oordeel
