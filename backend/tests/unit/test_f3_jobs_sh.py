"""Guard (BUG 21-09 — scheduler rlz-boek-wachtrij stond GEPAUZEERD, job zonder startcommando gezien als "bestaat al"):
`scripts/gcp/f3_jobs.sh` (1) is geldige bash, (2) toetst bij "bestaat al" het startcommando en zet `--command python`
bij als het ontbreekt, (3) zet de vangnet-schedulers (boek-wachtrij, extractie-wachtrij, bank-sync, bewaking,
afleveraar) direct op ENABLED (resume alleen bij PAUSED — idempotent, notificatie-cadansen houden hun bewuste pauze),
(4) eindigt met een luide lijst "GEPAUZEERD: …" mét het resume-commando en "ZONDER STARTCOMMANDO: …" mét het
update-commando."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "gcp" / "f3_jobs.sh"


def _tekst() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash ontbreekt")
def test_script_is_geldige_bash() -> None:
    uit = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert uit.returncode == 0, uit.stderr


def test_bestaat_al_toetst_en_zet_het_startcommando_bij() -> None:
    t = _tekst()
    # De describe-vóór-create-tak leest het commando uit de job-template …
    assert "value(spec.template.spec.template.spec.containers[0].command)" in t
    # … en zet het bij als het leeg is (Peters herstel van 21-09 als vast onderdeel).
    assert re.search(r'gcloud run jobs update "\$\{NAAM\}" --region="\$\{REGION\}" --command python', t)
    assert "had GEEN startcommando" in t


def test_vangnet_schedulers_worden_hervat_en_notificaties_niet_geraakt() -> None:
    t = _tekst()
    m = re.search(r"VANGNET_SCHEDULERS=\(([^)]*)\)", t)
    assert m, "VANGNET_SCHEDULERS-array ontbreekt"
    namen = set(m.group(1).split())
    assert {"rlz-boek-wachtrij", "rlz-extractie-wachtrij", "rlz-bank-sync"} <= namen
    # Alleen resume bij PAUSED (idempotent), nooit een notificatie-cadans in deze lijst.
    assert re.search(r'PAUSED\)\s+gcloud scheduler jobs resume "\$\{NAAM\}"', t)
    assert not namen & {"rlz-accordeur-herinneringen", "rlz-nieuwe-facturen", "rlz-intake-imap"}


def test_script_eindigt_met_luide_lijsten_en_herstelcommando() -> None:
    t = _tekst()
    slot = t.split("== 12. Slotcontrole", 1)[1]
    assert 'echo "   GEPAUZEERD: ${GEPAUZEERD[*]}"' in slot
    assert "gcloud scheduler jobs resume ${NAAM} --location=${REGION}" in slot
    assert "ZONDER STARTCOMMANDO" in slot
    assert "gcloud run jobs update ${NAAM} --region=${REGION} --command python" in slot
