"""Guard (blok 14 vervolgrun 07-09): élke `BESLISSINGEN "<sectie>"`-verwijzing in CLAUDE.md moet in docs/BESLISSINGEN.md
bestaan als kop (`## `/`### `) óf als registerrij-titel (`| **<titel>`), case-insensitief en op het BEGIN van die kop/titel.
Aanleiding: CLAUDE.md verwees naar "KEMPEN-DOORBELASTING" terwijl die kop alleen als archiefkop "Domeinbeslissingen —
Kempen-doorbelasting" bestaat. Een `archief "<naam>"`-verwijzing moet als substring in een archief-subkop
("VERPLAATST UIT CLAUDE.md") voorkomen. De omvang-regel (CLAUDE.md < 150k tekens) wordt hier ook bewaakt."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLAUDE_MD = REPO / "CLAUDE.md"
BESLISSINGEN = REPO / "docs" / "BESLISSINGEN.md"

_VERWIJZING = re.compile(r'BESLISSINGEN\s+((?:"[^"]+"(?:\s*(?:,|\+|en|/)\s*)?)+)')
_ARCHIEF = re.compile(r'archief\s+"([^"]+)"')


def _norm(tekst: str) -> str:
    return re.sub(r"\s+", " ", tekst.replace("…", "").replace("'", '"').replace("’", '"')).strip().lower()


def verwijzingen(claude_md: str) -> set[str]:
    uit: set[str] = set()
    for m in _VERWIJZING.finditer(claude_md):
        uit.update(re.findall(r'"([^"]+)"', m.group(1)))
    return uit


def koppen_en_rijtitels(beslissingen: str) -> list[str]:
    uit: list[str] = []
    for regel in beslissingen.splitlines():
        if regel.startswith("#"):
            uit.append(_norm(regel.lstrip("#")))
        elif regel.startswith("| **"):
            uit.append(_norm(regel[4:].split("**", 1)[0]))
    return uit


def archief_koppen(beslissingen: str) -> list[str]:
    return [_norm(r.lstrip("#")) for r in beslissingen.splitlines() if r.startswith("### ") and "ed6d176" in r]


def test_claude_md_blijft_onder_de_150k_tekens_limiet() -> None:
    assert len(CLAUDE_MD.read_text(encoding="utf-8")) < 150_000


def test_elke_beslissingen_verwijzing_in_claude_md_bestaat_als_kop_of_registerrij() -> None:
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    doelen = koppen_en_rijtitels(BESLISSINGEN.read_text(encoding="utf-8"))
    ontbrekend = sorted(
        ref for ref in verwijzingen(claude) if not any(doel.startswith(_norm(ref)) for doel in doelen)
    )
    assert not ontbrekend, f"CLAUDE.md verwijst naar BESLISSINGEN-secties die niet als kop/registerrij bestaan: {ontbrekend}"


def test_elke_archief_verwijzing_in_claude_md_bestaat_als_archiefkop() -> None:
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    koppen = archief_koppen(BESLISSINGEN.read_text(encoding="utf-8"))
    ontbrekend = sorted(ref for ref in _ARCHIEF.findall(claude) if not any(_norm(ref) in kop for kop in koppen))
    assert not ontbrekend, f"CLAUDE.md verwijst naar archiefblokken die niet als subkop bestaan: {ontbrekend}"
