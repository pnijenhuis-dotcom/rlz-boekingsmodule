"""Blok 8 nazorg 15-09: grote rapporten gedoseerd naar stdout (Cloud Logging liet bij één print ~500 regels vallen —
derde meting 15-09, executie rlz-reconciliatie-k2tpm: 1208 van ~1700 stdout-regels over). Geen DB, geen netwerk."""

from __future__ import annotations

import io

from app.migratie import cli_odoo, cli_replay, uitvoer
from app.migratie.uitvoer import GEDOSEERD_VANAF, print_gedoseerd


def test_klein_rapport_geen_pauze_zelfde_tekst() -> None:
    buf = io.StringIO()
    pauzes: list[float] = []
    tekst = "\n".join(f"regel {i}" for i in range(GEDOSEERD_VANAF - 1))
    n = print_gedoseerd(tekst, bestand=buf, slaap=pauzes.append)
    assert n == GEDOSEERD_VANAF - 1
    assert buf.getvalue() == tekst + "\n"  # identiek aan print(tekst)
    assert pauzes == []


def test_groot_rapport_pauzeert_per_blok_en_verliest_niets() -> None:
    buf = io.StringIO()
    pauzes: list[float] = []
    regels = [f"| RLZ-04-{i:08d} | in_invoice | € 1,00 | grootboek zonder Odoo-rekening: 4501 |" for i in range(1700)]
    tekst = "\n".join(regels)
    n = print_gedoseerd(tekst, bestand=buf, blok=100, pauze=0.2, slaap=pauzes.append)
    assert n == 1700
    assert buf.getvalue().split("\n")[:-1] == regels  # élke regel aanwezig, in volgorde
    assert len(pauzes) == 16  # elke 100 regels, niet ná de laatste
    assert set(pauzes) == {0.2}


def test_default_dosering_is_ruim_onder_de_logagent() -> None:
    # 1.700 regels → ≈ 3,4 s aan pauzes: snel genoeg voor een job, langzaam genoeg voor de agent (≈ 500 regels/s).
    assert uitvoer.BLOK_REGELS / uitvoer.PAUZE_SECONDEN <= 1000
    assert uitvoer.BLOK_REGELS / uitvoer.PAUZE_SECONDEN >= 100


def test_replay_en_stap0_cli_printen_gedoseerd() -> None:
    """Fail-closed: beide rapport-CLI's gebruiken de helper (een kale print van als_markdown() komt terug bij een
    refactor)."""
    import inspect

    for module in (cli_replay, cli_odoo):
        bron = inspect.getsource(module)
        assert "print(rapport.als_markdown())" not in bron, module.__name__
        assert "print_gedoseerd(rapport.als_markdown())" in bron, module.__name__
