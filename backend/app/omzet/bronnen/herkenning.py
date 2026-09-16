"""Eén registry van omzetbron-herkenning (blok A1 ProfX-opdracht 16-09): élke bron heeft precies één
herkenningsregel — spreadsheets op rasterinhoud (zonnestudio/pilates, 15-09), PDF's op de TEKSTLAAG (ProfX Journaal en
Margerapport). Herkenning gaat op INHOUD, vóór de AI-classificatie; afzender en onderwerp zijn alleen hint (regel
15-08). Fail-closed sweep: `tests/omzet/test_profx.py::test_elke_bron_heeft_een_herkenningsregel` eist voor élke
BRON_* een regel + test."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.omzet.bronnen import pilates, profx, zonnestudio
from app.omzet.bronnen.grid import Grid


@dataclass(frozen=True)
class Regel:
    bron: str
    soort: str  # 'spreadsheet' | 'pdf_tekst'
    herken: Callable[..., bool]


REGELS: tuple[Regel, ...] = (
    Regel(zonnestudio.BRON_DAGSTAAT, "spreadsheet", zonnestudio.is_dagstaat),
    Regel(zonnestudio.BRON_KASCHECK, "spreadsheet", zonnestudio.is_kascheck),
    Regel(pilates.BRON, "spreadsheet", pilates.is_betalingsexport),
    Regel(profx.BRON_JOURNAAL, "pdf_tekst", profx.is_journaal),
    Regel(profx.BRON_MARGE, "pdf_tekst", profx.is_margerapport),
)

ALLE_BRONNEN: tuple[str, ...] = tuple(r.bron for r in REGELS)
PDF_BRONNEN: frozenset[str] = frozenset(r.bron for r in REGELS if r.soort == "pdf_tekst")


def herken_grid(grid: Grid) -> str | None:
    for regel in REGELS:
        if regel.soort == "spreadsheet" and regel.herken(grid):
            return regel.bron
    return None


def herken_pdf_tekst(regels: list[str] | tuple[str, ...]) -> str | None:
    """Bron uit de tekstlaag van een PDF; None = geen bekende omzetbron (dan de normale inkoop-/AI-route)."""
    lijst = list(regels)
    for regel in REGELS:
        if regel.soort == "pdf_tekst" and regel.herken(lijst):
            return regel.bron
    return None


def herken_pdf(pdf_bytes: bytes) -> str | None:
    """Bron uit de PDF-bytes (pypdf-tekstlaag, zelfde helper als de template-terugval); geen tekstlaag = None."""
    from app.extractie.template_terugval import lees_tekstlaag

    laag = lees_tekstlaag(pdf_bytes)
    if laag is None:
        return None
    return herken_pdf_tekst(laag.regels)
