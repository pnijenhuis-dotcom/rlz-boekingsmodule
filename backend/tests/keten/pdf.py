"""Deterministische vervang-PDF's voor de gouden set (blok 0 herstelrun 08-09): de échte PDF-bytes uit productie
staan bewust NIET in de repo — per casus staat de kerntekst in `fixtures/<casus>/pdf_tekst.json` en wordt hier een
meerpagina-PDF mét tekstlaag van gegenereerd (zelfde minimale schrijver als tests/extractie/pdf_helper.py, geen
nieuwe dependency). Dezelfde tekst geeft altijd dezelfde bytes: dat maakt sha256-gebaseerde bundeling (ingesloten
PDF ↔ losse bijlage) en byte-identieke-dubbel-casussen reproduceerbaar."""

from __future__ import annotations

Regel = str | list[list[float | str]] | list[tuple[float, str]]


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


def _pagina_inhoud(regels: list[Regel], *, fontgrootte: int) -> bytes:
    inhoud = bytearray(b"BT\n/F1 %d Tf\n" % fontgrootte)
    y = 800
    for regel in regels:
        fragmenten = [(50.0, regel)] if isinstance(regel, str) else [(float(x), str(t)) for x, t in regel]
        for x, tekst in fragmenten:
            inhoud += b"1 0 0 1 %.1f %d Tm " % (x, y) + _pdf_string(tekst) + b" Tj\n"
        y -= fontgrootte + 4
    inhoud += b"ET\n"
    return bytes(inhoud)


def maak_pdf(paginas: list[list[Regel]], *, fontgrootte: int = 10) -> bytes:
    """`paginas`: per pagina een lijst regels (string = begint op x=50; lijst van (x, tekst) = kolommen)."""
    if not paginas:
        paginas = [[""]]
    objecten: list[bytes] = [b"", b""]  # 1 = Catalog, 2 = Pages (achteraf gevuld)
    pagina_refs: list[int] = []
    font_nr = 3
    objecten.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for regels in paginas:
        inhoud = _pagina_inhoud(regels, fontgrootte=fontgrootte)
        inhoud_nr = len(objecten) + 1
        objecten.append(b"<< /Length %d >>\nstream\n" % len(inhoud) + inhoud + b"\nendstream")
        pagina_nr = len(objecten) + 1
        objecten.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (inhoud_nr, font_nr)
        )
        pagina_refs.append(pagina_nr)
    objecten[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objecten[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % nr for nr in pagina_refs),
        len(pagina_refs),
    )
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
