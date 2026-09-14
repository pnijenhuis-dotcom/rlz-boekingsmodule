"""Guard (werkloop automatisch 14-09, besluit Peter 14-09): élk CC-eindrapport staat als `docs/rapporten/<jjjj-mm-dd>-<slug>.md`
én als regel in `docs/rapporten/INDEX.md` (nieuwste bovenaan). Een rapport zonder indexregel, een indexregel zonder bestand
of een verkeerde volgorde is rood. Elk rapport draagt de verplichte regel "werkt in productie: ja/nee/niet gemeten"."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MAP = REPO / "docs" / "rapporten"
INDEX = MAP / "INDEX.md"
_NAAM = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9][a-z0-9-]*\.md$")
_REGEL = re.compile(r"^- \[[^\]]+\]\(((\d{4}-\d{2}-\d{2})-[a-z0-9-]+\.md)\)")


def _rapporten() -> list[Path]:
    return sorted(p for p in MAP.glob("*.md") if p.name != "INDEX.md")


def _indexregels() -> list[tuple[str, str]]:
    uit: list[tuple[str, str]] = []
    for regel in INDEX.read_text(encoding="utf-8").splitlines():
        m = _REGEL.match(regel)
        if m:
            uit.append((m.group(1), m.group(2)))
    return uit


def test_rapportnamen_volgen_jjjj_mm_dd_slug() -> None:
    fout = [p.name for p in _rapporten() if not _NAAM.match(p.name)]
    assert fout == [], f"rapportnaam ≠ <jjjj-mm-dd>-<slug>.md: {fout}"


def test_elk_rapport_staat_in_de_index_en_elke_indexregel_bestaat() -> None:
    bestanden = {p.name for p in _rapporten()}
    in_index = {naam for naam, _ in _indexregels()}
    assert bestanden - in_index == set(), f"rapport(en) zonder regel in INDEX.md: {sorted(bestanden - in_index)}"
    assert in_index - bestanden == set(), f"INDEX.md verwijst naar ontbrekend rapport: {sorted(in_index - bestanden)}"


def test_index_nieuwste_bovenaan() -> None:
    datums = [d for _, d in _indexregels()]
    assert datums == sorted(datums, reverse=True), "INDEX.md: nieuwste rapport hoort bovenaan"


def test_elk_rapport_zegt_werkt_in_productie() -> None:
    zonder = [p.name for p in _rapporten() if not re.search(r"werkt in productie", p.read_text(encoding="utf-8"), re.I)]
    assert zonder == [], f"rapport zonder 'werkt in productie: ja/nee/niet gemeten': {zonder}"
