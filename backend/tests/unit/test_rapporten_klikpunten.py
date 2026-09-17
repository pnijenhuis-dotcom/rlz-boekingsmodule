"""Guard (Feiten eerst, Peter 17-09: "geen halve informatie" — drie van drie SCHRIJF-c-opruimpunten bleken onvoldoende onderbouwd):
élke regel onder een kop "Klikpunten"/"Opruimpunten"/"Beslispunten" in een rapport van 17-09 of later die een RLZ-/Odoo-/bank-object
noemt (boekstuknummer `RLZ-xx-xxxxxxxx`, "bankregel", "mutatie", "boekstuk", "concept") draagt een DATUM én een BEDRAG én een
BRON (id/GUID-prefix, link, of een letterlijk citaat van `rlz-feiten`/`db-lezen`) — óf zegt expliciet dat het punt VERVALT/is
INGETROKKEN. Een kaal "RLZ-01-00000006 concept" is rood. Rapporten vóór 17-09 zijn historie en vallen buiten de guard."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MAP = REPO / "docs" / "rapporten"
VANAF = "2026-09-17"
KOPPEN = re.compile(r"^#{1,4}\s.*(klikpunt|opruimpunt|beslispunt)", re.I)
OBJECT = re.compile(r"RLZ-\d{2}-\d{8}|\bbankregel\b|\bmutatie\b|\bboekstuk\b|\bconcept\b|\bOdoo-(document|boekstuk|factuur|move|id)\b", re.I)
DATUM = re.compile(r"\b\d{2}-\d{2}(-\d{4})?\b|\b\d{4}-\d{2}-\d{2}\b")
BEDRAG = re.compile(r"€\s?-?\d")
BRON = re.compile(r"https?://|\b[0-9a-f]{8}\b|\bid\b|guid|citaat|letterlijk|rlz-feiten|db-lezen|verkenning/", re.I)
UITZONDERING = re.compile(r"vervalt|ingetrokken|niet gevonden|bestaat niet|geen mutatie|geen document", re.I)


def _rapporten_vanaf() -> list[Path]:
    return sorted(p for p in MAP.glob("*.md") if p.name != "INDEX.md" and p.name[:10] >= VANAF)


def _regels_onder_klikpunten(tekst: str) -> list[tuple[int, str]]:
    uit: list[tuple[int, str]] = []
    actief = False
    for nr, regel in enumerate(tekst.splitlines(), start=1):
        if regel.startswith("#"):
            actief = bool(KOPPEN.match(regel))
            continue
        if actief and re.match(r"^\s*(\d+\.|-|\*)\s", regel):
            uit.append((nr, regel))
    return uit


def test_klikpunt_met_object_draagt_datum_bedrag_en_bron() -> None:
    fouten: list[str] = []
    for p in _rapporten_vanaf():
        for nr, regel in _regels_onder_klikpunten(p.read_text(encoding="utf-8")):
            if not OBJECT.search(regel) or UITZONDERING.search(regel):
                continue
            ontbreekt = [n for n, rx in (("datum", DATUM), ("bedrag", BEDRAG), ("bron", BRON)) if not rx.search(regel)]
            if ontbreekt:
                fouten.append(f"{p.name}:{nr} mist {', '.join(ontbreekt)}: {regel.strip()[:120]}")
    assert not fouten, "klikpunt/opruimpunt zonder volledige onderbouwing (regel Peter 17-09):\n" + "\n".join(fouten)


def test_guard_ziet_rapporten() -> None:
    assert _rapporten_vanaf(), "geen rapporten ≥ 17-09 gevonden — de guard draait leeg"
