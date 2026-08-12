#!/usr/bin/env python3
"""Genereert een Word-bestand uit een canonieke markdown-bron (docs/avg/*.md → .docx).

De .md is canoniek; de .docx is een gegenereerd verzend-artefact voor de jurist en wordt
ALLEEN via dit script ververst — nooit met de hand in Word bewerken (een Word-hersave
creëert precies de zwevende-binary-wijziging die dit script oplost; inhoudelijke
opmerkingen van de jurist landen via de md). Route: markdown → HTML → macOS `textutil`
(md-parsing via het python-`markdown`-package uit de backend-dev-venv).

Gebruik (repo-root):

    backend/.venv/bin/python scripts/genereer_avg_docx.py \\
        docs/avg/07-verwerkersovereenkomst-pdl.md \\
        docs/avg/Verwerkersovereenkomst-PDL-concept-2026-08-12.docx
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    bron, doel = Path(sys.argv[1]), Path(sys.argv[2])
    if not bron.is_file():
        print(f"FOUT: bronbestand niet gevonden: {bron}")
        return 1

    try:
        import markdown
    except ImportError:
        print("FOUT: het 'markdown'-package ontbreekt — draai `make install` in backend/ (dev-dependency).")
        return 1

    # smarty: typografische aanhalingstekens (“ ” ’) zoals in de eerder verzonden versie.
    body = markdown.markdown(bron.read_text(encoding="utf-8"), extensions=["tables", "sane_lists", "smarty"])
    titel = bron.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
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
