"""Copy-check (opdracht Peter 22-09, casus Bouwadvies: de blokkade ná het laatste akkoord kwam bij Peter als
"Bug"-melding binnen): het woord "bug" komt in geen enkele klant-/kantoortekst voor — niet in de frontend (JSX-tekst en
string-literals van `.ts`/`.tsx` buiten tests/dev-harnassen) en niet in backend-teksten die naar een mens gaan
(reconciliatie-teksten, mails, foutmeldingen in `app/`). Commentaar telt niet (daar staat "Bug 18-09" als
dossierverwijzing). Een technische fout heet in klanttekst "systeemfout — automatisch gemeld", nooit "bug"."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FRONTEND = REPO / "frontend" / "src"
BACKEND = REPO / "backend" / "app"

_WOORD = re.compile(r"\bbugs?\b", re.IGNORECASE)
_TS_COMMENTAAR = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_PY_COMMENTAAR = re.compile(r"(?m)^\s*#[^\n]*|(?<=\s)#[^\n]*")
_PY_DOCSTRING = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'')


def _frontend_bestanden() -> list[Path]:
    uit: list[Path] = []
    for p in FRONTEND.rglob("*.ts*"):
        if ".test." in p.name or "/dev/" in str(p).replace("\\", "/") or p.name.endswith(".d.ts"):
            continue
        uit.append(p)
    return uit


def _backend_bestanden() -> list[Path]:
    return [p for p in BACKEND.rglob("*.py")]


def test_frontend_klanttekst_bevat_het_woord_bug_niet() -> None:
    treffers: list[str] = []
    for p in _frontend_bestanden():
        tekst = _TS_COMMENTAAR.sub("", p.read_text(encoding="utf-8"))
        for i, regel in enumerate(tekst.splitlines(), 1):
            if _WOORD.search(regel):
                treffers.append(f"{p.relative_to(REPO)}:{i}: {regel.strip()[:120]}")
    melding = "het woord 'bug' hoort niet in klanttekst — zeg wat er is en wat de mens kan doen:\n"
    assert treffers == [], melding + "\n".join(treffers)


def test_backend_teksten_bevatten_het_woord_bug_niet() -> None:
    """Alleen string-literals tellen (commentaar en docstrings zijn dossier, geen klanttekst)."""
    treffers: list[str] = []
    for p in _backend_bestanden():
        tekst = _PY_DOCSTRING.sub('""', p.read_text(encoding="utf-8"))
        tekst = _PY_COMMENTAAR.sub("", tekst)
        for i, regel in enumerate(tekst.splitlines(), 1):
            for lit in re.findall(r'"([^"\n]*)"|\'([^\'\n]*)\'', regel):
                waarde = lit[0] or lit[1]
                if _WOORD.search(waarde):
                    treffers.append(f"{p.relative_to(REPO)}:{i}: {waarde[:120]}")
    assert treffers == [], "het woord 'bug' hoort niet in een tekst voor een mens:\n" + "\n".join(treffers)
