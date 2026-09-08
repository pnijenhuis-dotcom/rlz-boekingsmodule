"""Guard gouden set (blok 0 herstelrun 08-09, definitie van AF Peter): wie de intake-/extractie-/documenten-keten of
het controlescherm wijzigt, raakt de gouden set aan — minimaal het weghalen van de eigen xfail. Werkt op de WERKBOOM
(`git diff --name-only HEAD` + untracked): staan er gewijzigde bestanden onder app/intake, app/extractie,
app/documenten of frontend/src/document en géén enkel bestand onder backend/tests/keten → rood, mét de lijst.
Schone werkboom of geen git (CI-artefact) = overslaan met melding."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BEWAAKT = ("backend/app/intake/", "backend/app/extractie/", "backend/app/documenten/", "frontend/src/document/")
GOUDEN_SET = "backend/tests/keten/"


def _gewijzigde_paden() -> list[str] | None:
    """Repo-relatieve paden die afwijken van HEAD (gewijzigd, toegevoegd, verwijderd) plus untracked; None = geen git."""
    try:
        diff = subprocess.run(
            ["git", "-C", str(REPO), "diff", "--name-only", "HEAD"], capture_output=True, text=True, check=True
        ).stdout
        untracked = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted({regel.strip() for regel in (diff + untracked).splitlines() if regel.strip()})


def test_wijziging_in_de_keten_beweegt_de_gouden_set_mee() -> None:
    paden = _gewijzigde_paden()
    if paden is None:
        pytest.skip("geen git-werkboom (CI-artefact) — gouden-set-guard overgeslagen")
    if not paden:
        pytest.skip("schone werkboom — niets te bewaken")
    bewaakt = [p for p in paden if p.startswith(BEWAAKT)]
    gouden = [p for p in paden if p.startswith(GOUDEN_SET)]
    if not bewaakt:
        pytest.skip("geen wijziging onder de bewaakte ketenmappen")
    assert gouden, (
        "De gouden set moet meebewegen: er zijn wijzigingen in de keten zonder één aanraking van backend/tests/keten.\n"
        "Gewijzigd onder de bewaakte mappen:\n  - " + "\n  - ".join(bewaakt) + "\n"
        "Waarom: de gouden set (echte documenten, hele keten) is de verplichte poort van 'af' (Peter 08-09) — raak "
        "minimaal je eigen xfail in tests/keten aan (grep op 'blok N') of voeg de casus toe die jouw gedrag dekt."
    )
