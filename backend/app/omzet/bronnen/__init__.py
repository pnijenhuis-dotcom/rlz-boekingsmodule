"""Deterministische omzetBRONNEN naast de AI-rapportextractie (Peter 15-09): spreadsheets van een POS/boekingsplatform
worden zonder AI gelezen op celposities/labels mét harde controles (code voor cijfers). Elke bron levert hetzelfde
`veldvoorstel`-dict als `app/extractie/rapport.py::bouw_rapport_veldvoorstel` (soort 'kassarapport', regels per
categorie mét kassabedragen INCLUSIEF btw — de omzetmotor splitst per taxrate) plus `bron` en `bron_detail`
(betaalwijzen, kas, controles, batch), zodat het omzet-controlescherm en de boekmotor ongewijzigd werken.

Bronnen: `zonnestudio_dagstaat` (POS "Daily Sales" .xls) + `zonnestudio_kascheck` (Kascheck .xlsx, wederhelft van
dezelfde dag), `pilates_betalingsexport` (betalingsexport .xlsx, één document per uitbetaling)."""

from __future__ import annotations

from pathlib import PurePosixPath

from app.omzet.bronnen import pilates, zonnestudio
from app.omzet.bronnen.grid import Grid, lees_grid

BRON_ZONNESTUDIO_DAGSTAAT = zonnestudio.BRON_DAGSTAAT
BRON_ZONNESTUDIO_KASCHECK = zonnestudio.BRON_KASCHECK
BRON_PILATES = pilates.BRON

SPREADSHEET_SUFFIXEN = frozenset({".xls", ".xlsx"})


def is_spreadsheet(bestandsnaam: str) -> bool:
    return PurePosixPath(bestandsnaam).suffix.lower() in SPREADSHEET_SUFFIXEN


def herken_bron(bestandsnaam: str, inhoud: bytes) -> str | None:
    """Welke deterministische bron is dit bestand? None = geen bekende omzetbron (dan geen kassarapport-route)."""
    if not is_spreadsheet(bestandsnaam):
        return None
    try:
        grid = lees_grid(bestandsnaam, inhoud)
    except Exception:  # noqa: BLE001 — onleesbaar bestand = geen bron (de aanroeper meldt dat zichtbaar)
        return None
    return herken_bron_in_grid(grid)


def herken_bron_in_grid(grid: Grid) -> str | None:
    if zonnestudio.is_dagstaat(grid):
        return BRON_ZONNESTUDIO_DAGSTAAT
    if zonnestudio.is_kascheck(grid):
        return BRON_ZONNESTUDIO_KASCHECK
    if pilates.is_betalingsexport(grid):
        return BRON_PILATES
    return None


__all__ = [
    "BRON_PILATES",
    "BRON_ZONNESTUDIO_DAGSTAAT",
    "BRON_ZONNESTUDIO_KASCHECK",
    "Grid",
    "herken_bron",
    "herken_bron_in_grid",
    "is_spreadsheet",
    "lees_grid",
    "pilates",
    "zonnestudio",
]
