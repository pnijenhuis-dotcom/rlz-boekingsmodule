"""Minimale, deterministische PDF-writer voor de bestelbon (blok D3) — geen nieuwe dependency
(zelfde lijn als de eigen PDF-writer in app/documenten/afbeelding.py). Eén of meer A4-pagina's,
Helvetica (standaard-14-font, geen embedding), WinAnsi-tekst; regels worden afgebroken en
tabelkolommen uitgelijnd op vaste x-posities. Voldoende voor een nette, leesbare bon; opmaak
is bewust sober (functioneel document richting de leverancier)."""

from __future__ import annotations

from dataclasses import dataclass

A4_BREEDTE = 595
A4_HOOGTE = 842
MARGE = 48
REGELHOOGTE = 14


@dataclass(frozen=True)
class TekstRegel:
    tekst: str
    x: int = MARGE
    grootte: int = 10
    vet: bool = False


def _pdf_tekst(tekst: str) -> str:
    """WinAnsi-veilig maken: haakjes/backslash escapen, niet-encodeerbare tekens vervangen."""
    veilig = tekst.encode("cp1252", errors="replace").decode("cp1252")
    return veilig.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def bouw_pdf(paginas: list[list[TekstRegel]]) -> bytes:
    """Bouw een PDF met per pagina een lijst tekstregels (y loopt van boven naar beneden per
    volgorde, `x` bepaalt de kolom). Objectnummers zijn vast per pagina — output is voor gelijke
    invoer byte-identiek (idempotentie/vergelijkbaarheid)."""
    objecten: list[bytes] = []

    def voeg_toe(inhoud: bytes) -> int:
        objecten.append(inhoud)
        return len(objecten)

    font_regular = voeg_toe(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold = voeg_toe(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pagina_ids: list[int] = []
    pages_id_placeholder = len(objecten) + 1 + 2 * len(paginas)  # ná alle content+page-objecten
    for regels in paginas:
        y = A4_HOOGTE - MARGE
        stream_delen: list[str] = []
        huidige_y_regel: TekstRegel | None = None
        for regel in regels:
            # Regels met dezelfde "rij" (opeenvolgend en x > vorige x) blijven op dezelfde y:
            # een tabelrij wordt aangeleverd als opeenvolgende regels met stijgende x.
            if huidige_y_regel is not None and regel.x > huidige_y_regel.x:
                pass
            else:
                y -= REGELHOOGTE if huidige_y_regel is not None else 0
            huidige_y_regel = regel
            font = "/F2" if regel.vet else "/F1"
            stream_delen.append(f"BT {font} {regel.grootte} Tf {regel.x} {y} Td ({_pdf_tekst(regel.tekst)}) Tj ET")
        stream = "\n".join(stream_delen).encode("cp1252", errors="replace")
        content_id = voeg_toe(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_id = voeg_toe(
            (
                f"<< /Type /Page /Parent {pages_id_placeholder} 0 R /MediaBox [0 0 {A4_BREEDTE} {A4_HOOGTE}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        pagina_ids.append(page_id)
    kids = " ".join(f"{p} 0 R" for p in pagina_ids)
    pages_id = voeg_toe(f"<< /Type /Pages /Kids [{kids}] /Count {len(pagina_ids)} >>".encode())
    assert pages_id == pages_id_placeholder
    catalog_id = voeg_toe(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    uit = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objecten, start=1):
        offsets.append(len(uit))
        uit += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(uit)
    uit += f"xref\n0 {len(objecten) + 1}\n".encode()
    uit += b"0000000000 65535 f \n"
    for o in offsets:
        uit += f"{o:010d} 00000 n \n".encode()
    uit += f"trailer\n<< /Size {len(objecten) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(uit)


def paginering(regels: list[TekstRegel], *, regels_per_pagina: int = 52) -> list[list[TekstRegel]]:
    """Splits in pagina's op basis van het aantal RIJEN (opeenvolgende regels met stijgende x
    tellen als één rij)."""
    paginas: list[list[TekstRegel]] = []
    huidig: list[TekstRegel] = []
    rijen = 0
    vorige: TekstRegel | None = None
    for r in regels:
        nieuwe_rij = vorige is None or r.x <= vorige.x
        if nieuwe_rij and rijen >= regels_per_pagina:
            paginas.append(huidig)
            huidig, rijen = [], 0
        if nieuwe_rij:
            rijen += 1
        huidig.append(r)
        vorige = r
    if huidig:
        paginas.append(huidig)
    return paginas
