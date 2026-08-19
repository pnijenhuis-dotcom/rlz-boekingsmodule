#!/usr/bin/env python3
"""Genereert een Word-bestand uit een canonieke markdown-bron (docs/avg/*.md → .docx).

De .md is canoniek; de .docx is een gegenereerd verzend-artefact voor de jurist en wordt
ALLEEN via dit script ververst — nooit met de hand in Word bewerken (een Word-hersave
creëert precies de zwevende-binary-wijziging die dit script oplost; inhoudelijke
opmerkingen van de jurist landen via de md). Route: markdown → HTML → macOS `textutil`
(md-parsing via het python-`markdown`-package uit de backend-dev-venv).

Gebruik (repo-root):

    backend/.venv/bin/python scripts/genereer_avg_docx.py [--zonder-statusnoot] \\
        docs/avg/07-verwerkersovereenkomst-pdl.md \\
        docs/avg/Verwerkersovereenkomst-PDL-concept-2026-08-12.docx

`--zonder-statusnoot` laat het status-blockquote direct onder de H1 weg (de "> ✅ …"-noot):
dat levert de schone tekenversie/printversie op; de md blijft canoniek mét de noot.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def strip_statusnoot(tekst: str) -> str:
    """Verwijdert het eerste blockquote-blok direct onder de H1 (de statusnoot)."""
    regels = tekst.splitlines()
    uit: list[str] = []
    i = 0
    # H1 + eventuele lege regels erna ongemoeid overnemen
    while i < len(regels) and not regels[i].startswith(">"):
        if uit and uit[0].startswith("# ") and regels[i].strip() and not regels[i].startswith(">"):
            # eerste niet-lege, niet-blockquote regel ná de H1: er is geen statusnoot
            return tekst
        uit.append(regels[i])
        i += 1
    while i < len(regels) and (regels[i].startswith(">") or not regels[i].strip()):
        i += 1
    return "\n".join(uit + regels[i:])


def main() -> int:
    argv = sys.argv[1:]
    zonder_statusnoot = "--zonder-statusnoot" in argv
    argv = [a for a in argv if a != "--zonder-statusnoot"]
    if len(argv) != 2:
        print(__doc__)
        return 1
    bron, doel = Path(argv[0]), Path(argv[1])
    if not bron.is_file():
        print(f"FOUT: bronbestand niet gevonden: {bron}")
        return 1

    try:
        import markdown
    except ImportError:
        print("FOUT: het 'markdown'-package ontbreekt — draai `make install` in backend/ (dev-dependency).")
        return 1

    tekst = bron.read_text(encoding="utf-8")
    if zonder_statusnoot:
        tekst = strip_statusnoot(tekst)
    # smarty: typografische aanhalingstekens (“ ” ’) zoals in de eerder verzonden versie.
    body = markdown.markdown(tekst, extensions=["tables", "sane_lists", "smarty"])
    titel = tekst.splitlines()[0].lstrip("# ").strip()
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{titel}</title>"
        "<style>body{font-family:'Times New Roman',serif;font-size:11pt;}"
        "h1{font-size:16pt}h2{font-size:13pt}"
        "table{border-collapse:collapse}td,th{border:1px solid #999;padding:4pt}</style>"
        f"</head><body>{body}</body></html>"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as f:
        f.write(html)
        html_pad = Path(f.name)
    try:
        subprocess.run(
            ["textutil", "-convert", "docx", str(html_pad), "-output", str(doel)],
            check=True,
        )
    finally:
        html_pad.unlink(missing_ok=True)
    print(f"Gegenereerd: {doel} (uit {bron})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
