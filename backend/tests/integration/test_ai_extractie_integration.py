from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import settings
from app.extractie import controle
from app.extractie.service import extraheer_inkoopfactuur

# Echte Claude-API-aanroep: kost geld en vereist ANTHROPIC_API_KEY (backend/.env) — daarom
# opt-in achter de ai_integration-marker (pyproject addopts sluit hem standaard uit; draaien via
# `make test-ai-integration`). Geen RLZ-verkeer en geen klantdata: de factuur hieronder is
# volledig synthetisch.

pytestmark = pytest.mark.ai_integration


def _mini_pdf(regels: list[str]) -> bytes:
    """Kleinste geldige één-pagina-PDF met Helvetica-tekstregels — genoeg voor een leesbare
    synthetische factuur zonder een PDF-library aan de dev-dependencies toe te voegen."""
    tekst = "BT /F1 12 Tf 50 780 Td 16 TL " + " ".join(f"({r}) Tj T*" for r in regels) + " ET"
    stream = tekst.encode("latin-1")
    objecten = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    uit = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objecten, start=1):
        offsets.append(len(uit))
        uit += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_start = len(uit)
    uit += f"xref\n0 {len(objecten) + 1}\n".encode()
    uit += b"0000000000 65535 f \n"
    for offset in offsets:
        uit += f"{offset:010d} 00000 n \n".encode()
    uit += (
        f"trailer\n<< /Size {len(objecten) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"
    ).encode()
    return bytes(uit)


_FACTUUR_PDF = _mini_pdf(
    [
        "FACTUUR",
        "Testleverancier Integratie B.V.",
        "Factuurnummer: INT-2026-007",
        "Factuurdatum: 1 juli 2026",
        "Vervaldatum: 31 juli 2026",
        "",
        "Omschrijving              Netto     Btw 21%",
        "Advieswerkzaamheden      100,00      21,00",
        "Reiskosten                50,00      10,50",
        "",
        "Totaal excl. btw:  150,00",
        "Btw 21%:            31,50",
        "Totaal incl. btw:  181,50",
    ]
)


@pytest.mark.skipif(not settings.anthropic_api_key, reason="geen ANTHROPIC_API_KEY geconfigureerd")
def test_extractie_tegen_echte_claude_api() -> None:
    extractie = extraheer_inkoopfactuur(_FACTUUR_PDF)

    # Kop: exact voorlezen wat er staat.
    assert extractie.kop["factuurnummer"].waarde == "INT-2026-007"
    assert extractie.kop["leverancier_naam"].waarde is not None
    assert "Testleverancier" in extractie.kop["leverancier_naam"].waarde
    assert extractie.kop["factuurnummer"].zekerheid > 0.5
    assert extractie.bsn_verwijderd == 0

    # De deterministische controlelaag moet de output valide kunnen parsen en de regelsom toetsen.
    voorstel = controle.bouw_veldvoorstel(
        extractie, vendors=[], taxrates=[], zekerheid_drempel=settings.ai_extractie_zekerheid_drempel
    )
    assert voorstel["factuurdatum"] == "2026-07-01"
    assert voorstel["totaal_incl"] is not None
    assert Decimal(voorstel["totaal_incl"]) == Decimal("181.50")
    assert voorstel["regelaantal"] >= 2
    assert voorstel["controle"]["regelsom_wijkt_af"] is False
