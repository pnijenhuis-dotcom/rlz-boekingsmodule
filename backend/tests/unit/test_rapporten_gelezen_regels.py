"""Guard (Peter 17-09, BESLISSINGEN "CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT"): élk CC-eindrapport in `docs/rapporten/`
draagt een sectie "## Gelezen regels" mét de gelezen regelsbestanden (`docs/regels/<domein>.md`) en hun regelaantal —
zodat "niet gelezen = niet beginnen" toetsbaar is en niet een hoop. Geldt voor rapporten vanaf de invoering (bestandsdatum
≥ 2026-09-18) plus de rapporten van de invoeringsrun zelf (expliciet hieronder); oudere rapporten blijven zoals ze zijn.
Een genoemd bestand moet bestaan; het regelaantal mag afwijken van de huidige stand (het bestand groeit), maar moet een getal
zijn. Een rapport zonder gelezen regels mag dat zeggen ("geen domeinregels gelezen — reden: …") — nooit stil weglaten."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RAPPORTEN = REPO / "docs" / "rapporten"
REGELS = REPO / "docs" / "regels"

VANAF = date(2026, 9, 18)
#: Rapporten van de invoeringsrun (17-09 middag/avond) — dragen de sectie al.
INVOERINGSRUN = {
    "2026-09-17-apple-1-2-xcode-cloud-nameting.md",
    "2026-09-17-herstellink-app-versie-update-eerst.md",
    "2026-09-17-leesreplica-afronden.md",
    "2026-09-17-native-ota-nameting-3.md",
    "2026-09-17-vgg-vijfde-meting-en-auto-posten.md",
    "2026-09-17-claude-md-regels-per-domein.md",
    "2026-09-17-cc-inbox-wacht-nooit-stil.md",
    "2026-09-17-inbox-afgewerkt-2.md",
}
SECTIE = re.compile(r"^## Gelezen regels\s*$", re.M)
REGEL = re.compile(r"`docs/regels/([a-z0-9-]+)\.md`\s*(?:\(|—|:)\s*(\d+)\s*regels")
GEEN = re.compile(r"geen domeinregels gelezen — reden:", re.I)


def _verplicht() -> list[Path]:
    uit: list[Path] = []
    for p in sorted(RAPPORTEN.glob("*.md")):
        if p.name in ("INDEX.md",):
            continue
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})-", p.name)
        if not m:
            continue
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d >= VANAF or p.name in INVOERINGSRUN:
            uit.append(p)
    return uit


def test_invoeringsrun_rapporten_bestaan() -> None:
    ontbrekend = sorted(n for n in INVOERINGSRUN if not (RAPPORTEN / n).is_file())
    assert ontbrekend == [], f"rapporten van de invoeringsrun ontbreken: {ontbrekend}"


def test_elk_rapport_vanaf_de_invoering_draagt_gelezen_regels() -> None:
    fouten: list[str] = []
    for p in _verplicht():
        tekst = p.read_text(encoding="utf-8")
        m = SECTIE.search(tekst)
        if not m:
            fouten.append(f"{p.name}: sectie '## Gelezen regels' ontbreekt")
            continue
        sectie = tekst[m.end():]
        nxt = re.search(r"^## ", sectie, flags=re.M)
        sectie = sectie[: nxt.start()] if nxt else sectie
        gevonden = REGEL.findall(sectie)
        if not gevonden and not GEEN.search(sectie):
            fouten.append(f"{p.name}: geen `docs/regels/<domein>.md` (N regels) en geen 'geen domeinregels gelezen — reden: …'")
        for slug, _n in gevonden:
            if not (REGELS / f"{slug}.md").is_file():
                fouten.append(f"{p.name}: docs/regels/{slug}.md bestaat niet")
    assert fouten == [], "; ".join(fouten)
