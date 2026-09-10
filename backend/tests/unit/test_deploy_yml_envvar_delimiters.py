"""Guard (nametingen-run 10-09): een `--set-env-vars`/`--update-env-vars` met een eigen scheidingsteken (`^<t>^…`) in
.github/workflows/deploy.yml mag dat teken NIET in een waarde dragen. Aanleiding: commit 8aeed75 (09-09) koos `^@^`
terwijl INTAKE_POSTVAK_ADRES=facturen@ak-nijenhuis.nl zélf een '@' bevat → gcloud brak die stap af, de workflow stopte
en álle F3-jobs bleven 13 deploys lang (09-09 06:00 → 10-09 17:56) op het beeld van 08-09 terwijl de service wél elke
push kreeg (én INTAKE_POSTVAK_ADRES verloor). Ook zonder eigen scheidingsteken geldt de default ',' als scheider."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEPLOY_YML = REPO / ".github" / "workflows" / "deploy.yml"
_ENV_FLAG = re.compile(r'--(?:set|update)-env-vars\s+"((?:[^"\\]|\\.)*)"')


def env_var_lijsten(tekst: str) -> list[tuple[str, str]]:
    """(scheidingsteken, ruwe lijst) per --set/--update-env-vars-vlag; default-scheider ','."""
    uit: list[tuple[str, str]] = []
    for m in _ENV_FLAG.finditer(tekst):
        ruw = m.group(1)
        d = re.match(r"\^(.)\^(.*)$", ruw, flags=re.S)
        uit.append((d.group(1), d.group(2)) if d else (",", ruw))
    return uit


def paren(scheider: str, lijst: str) -> list[str]:
    return [p for p in lijst.split(scheider) if p != ""]


def test_deploy_yml_heeft_env_var_vlaggen() -> None:
    assert len(env_var_lijsten(DEPLOY_YML.read_text(encoding="utf-8"))) >= 3


def test_elk_env_var_paar_heeft_de_vorm_KEY_is_waarde() -> None:
    fouten: list[str] = []
    for scheider, lijst in env_var_lijsten(DEPLOY_YML.read_text(encoding="utf-8")):
        for paar in paren(scheider, lijst):
            if not re.match(r"^[A-Z][A-Z0-9_]*=", paar):
                fouten.append(f"scheider {scheider!r}: fragment zonder KEY= → {paar[:80]!r} (waarde bevat het scheidingsteken?)")
    assert fouten == [], "\n".join(fouten)


def test_scheidingsteken_komt_niet_voor_in_een_waarde_met_bekende_at_tekens() -> None:
    # De concrete les van 09-09: een e-mailadres als waarde vraagt een scheider ≠ '@'.
    for scheider, lijst in env_var_lijsten(DEPLOY_YML.read_text(encoding="utf-8")):
        if "ak-nijenhuis.nl" in lijst:
            assert scheider != "@", "e-mailadres als waarde mag nooit '@' als scheidingsteken hebben"


def test_zelftest_regressie_8aeed75() -> None:
    kapot = '--update-env-vars "^@^INTAKE_POSTVAK_ADRES=facturen@ak-nijenhuis.nl@STORE_LINK_IOS=https://x" \\'
    [(scheider, lijst)] = env_var_lijsten(kapot)
    assert scheider == "@"
    assert any(not re.match(r"^[A-Z][A-Z0-9_]*=", p) for p in paren(scheider, lijst))
    goed = '--update-env-vars "^|^INTAKE_POSTVAK_ADRES=facturen@ak-nijenhuis.nl|STORE_LINK_IOS=https://x" \\'
    [(scheider, lijst)] = env_var_lijsten(goed)
    assert all(re.match(r"^[A-Z][A-Z0-9_]*=", p) for p in paren(scheider, lijst))
