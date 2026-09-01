"""Minimale PDF-generator mét tekstlaag voor tests (geen externe dependency): één pagina, Helvetica,
elke regel op een eigen y-positie; `kolommen` zet losse tekstfragmenten op een expliciete x-positie
zodat pypdf's layout-modus echte kolommen ziet. Tekens buiten Latin-1 worden niet ondersteund; het
euroteken gaat als WinAnsi 0x80."""

from __future__ import annotations


def _pdf_string(tekst: str) -> bytes:
    uit = bytearray(b"(")
    for ch in tekst:
        if ch == "€":
            uit += b"\\200"
        elif ch in "()\\":
            uit += b"\\" + ch.encode("latin-1")
        else:
            uit += ch.encode("latin-1", errors="replace")
    uit += b")"
    return bytes(uit)


def maak_tekst_pdf(regels: list[str | list[tuple[float, str]]], *, fontgrootte: int = 10) -> bytes:
    """`regels`: per regel een string (begint op x=50) of een lijst (x, tekst)-fragmenten."""
    inhoud = bytearray(b"BT\n/F1 %d Tf\n" % fontgrootte)
    y = 800
    for regel in regels:
        fragmenten = [(50.0, regel)] if isinstance(regel, str) else regel
        for x, tekst in fragmenten:
            inhoud += b"1 0 0 1 %.1f %d Tm " % (x, y) + _pdf_string(tekst) + b" Tj\n"
        y -= fontgrootte + 4
    inhoud += b"ET\n"
    objecten = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(inhoud) + bytes(inhoud) + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    uit = bytearray(b"%PDF-1.4\n")
    offsets = []
    for nummer, obj in enumerate(objecten, start=1):
        offsets.append(len(uit))
        uit += b"%d 0 obj\n" % nummer + obj + b"\nendobj\n"
    xref = len(uit)
    uit += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objecten) + 1)
    for offset in offsets:
        uit += b"%010d 00000 n \n" % offset
    uit += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objecten) + 1, xref)
    return bytes(uit)
