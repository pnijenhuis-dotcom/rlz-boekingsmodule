"""Guard (Peter 17-09, BESLISSINGEN "CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT"): de volledige domeinregels leven in
`docs/regels/<domein>.md`; CLAUDE.md is de harde kern + per domein één blok mét LEESPLICHT. Fail-closed:
(1) élk pakket onder `backend/app/` en élke map onder `frontend/src/` is in `docs/regels/INDEX.md` aan precies één domein
gekoppeld (een nieuw pakket zonder domein = rood); (2) élke LEESPLICHT-verwijzing in CLAUDE.md wijst naar een bestaand
regelsbestand en élk regelsbestand heeft een LEESPLICHT-blok in CLAUDE.md; (3) omvang CLAUDE.md > 120k tekens = rood,
> 90k = waarschuwing (in het rapport melden); (4) élk regelsbestand draagt de LEESPLICHT-kop en niets is leeg."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLAUDE_MD = REPO / "CLAUDE.md"
REGELS = REPO / "docs" / "regels"
INDEX = REGELS / "INDEX.md"
BACKEND_APP = REPO / "backend" / "app"
FRONTEND_SRC = REPO / "frontend" / "src"

OMVANG_ROOD = 120_000
OMVANG_WAARSCHUWING = 90_000


def _index_rijen() -> list[tuple[str, str, list[str]]]:
    rijen: list[tuple[str, str, list[str]]] = []
    for regel in INDEX.read_text(encoding="utf-8").splitlines():
        if not regel.startswith("| ") or regel.startswith("| Domein") or regel.startswith("|---"):
            continue
        cellen = [c.strip() for c in regel.strip().strip("|").split("|")]
        assert len(cellen) == 3, regel
        bestand = cellen[1].strip("`")
        paden = re.findall(r"`([^`]+)`", cellen[2])
        rijen.append((cellen[0], bestand, paden))
    assert rijen, "INDEX.md zonder domeinrijen"
    return rijen


def _pad_dekt(patroon: str, pad: str) -> bool:
    """`backend/app/bank/**` dekt `backend/app/bank`; `backend/app/cli.py` exact; `frontend/src/*.tsx` = bestanden in de map."""
    if patroon.endswith("/**"):
        return pad == patroon[:-3] or pad.startswith(patroon[:-3] + "/")
    if "*" in patroon:
        return re.fullmatch(re.escape(patroon).replace(r"\*", "[^/]*"), pad) is not None
    return pad == patroon


def test_elk_pakket_en_elke_frontend_map_heeft_precies_een_domein() -> None:
    rijen = _index_rijen()
    patronen = [(dom, p) for dom, _b, paden in rijen for p in paden]
    kandidaten: list[str] = []
    for d in sorted(BACKEND_APP.iterdir()):
        if d.is_dir() and d.name != "__pycache__":
            kandidaten.append(f"backend/app/{d.name}")
        elif d.is_file() and d.suffix == ".py" and d.name not in ("__init__.py", "schemas_basis.py", "proxy_prefixes.py", "static_frontend.py"):
            kandidaten.append(f"backend/app/{d.name}")
    for d in sorted(FRONTEND_SRC.iterdir()):
        if d.is_dir():
            kandidaten.append(f"frontend/src/{d.name}")
    fouten: list[str] = []
    for pad in kandidaten:
        treffers = sorted({dom for dom, p in patronen if _pad_dekt(p, pad)})
        if len(treffers) != 1:
            fouten.append(f"{pad} → {treffers or 'GEEN domein'}")
    assert fouten == [], "élk pakket/élke map hoort bij precies één domein in docs/regels/INDEX.md: " + "; ".join(fouten)


def test_index_bestanden_bestaan_en_dragen_leesplicht() -> None:
    for dom, bestand, _ in _index_rijen():
        p = REPO / bestand
        assert p.is_file(), f"{dom}: {bestand} ontbreekt"
        tekst = p.read_text(encoding="utf-8")
        assert "LEESPLICHT" in tekst[:800], f"{bestand}: LEESPLICHT-kop ontbreekt"
        assert "## Regels (woordelijk uit CLAUDE.md" in tekst, f"{bestand}: regelsblok ontbreekt"
        assert len(tekst) > 1500, f"{bestand}: verdacht leeg ({len(tekst)} tekens)"


def test_claude_md_leesplichten_wijzen_naar_bestaande_bestanden_en_dekken_alle_domeinen() -> None:
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    verwijzingen = set(re.findall(r"docs/regels/([a-z0-9-]+)\.md", claude))
    assert verwijzingen, "CLAUDE.md verwijst naar geen enkel regelsbestand"
    for slug in verwijzingen:
        assert (REGELS / f"{slug}.md").is_file(), f"CLAUDE.md verwijst naar ontbrekend docs/regels/{slug}.md"
    index_slugs = {Path(b).stem for _, b, _ in _index_rijen()}
    assert index_slugs <= verwijzingen, f"domeinen zonder LEESPLICHT-blok in CLAUDE.md: {index_slugs - verwijzingen}"
    leesplichten = re.findall(r"\*\*LEESPLICHT: lees `docs/regels/([a-z0-9-]+)\.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen\.\*\*", claude)
    assert set(leesplichten) == index_slugs, f"LEESPLICHT-blokken ≠ INDEX-domeinen: {set(leesplichten) ^ index_slugs}"


def test_claude_md_omvang_onder_de_grens() -> None:
    omvang = len(CLAUDE_MD.read_text(encoding="utf-8").encode("utf-8"))
    assert omvang < OMVANG_ROOD, f"CLAUDE.md is {omvang} tekens (> {OMVANG_ROOD}): verhuis volledige tekst naar docs/regels/<domein>.md"
    if omvang > OMVANG_WAARSCHUWING:
        warnings.warn(f"CLAUDE.md is {omvang} tekens (> {OMVANG_WAARSCHUWING}) — in het rapport melden en opschonen", stacklevel=1)
