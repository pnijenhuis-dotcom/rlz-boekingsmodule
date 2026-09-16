"""Casus (ad) ProfX Journaal + Margerapport (coffeeshop-kassa, Peter 16-09, screenshot De Bazar Apeldoorn) door de echte
keten: één intake-mail "Facturen - Inboeking journaal en marge raport" mét twee PDF's → herkenning op INHOUD vóór de
AI-classificatie (géén AI-call) → documentsoort kassarapport, toegewezen op de tenaamstelling uit het rapport (afzender =
alleen hint, regel 15-08) → deterministische parser → veldvoorstel per ARTIKELGROEP (niet de artikellijst) → het
margerapport van dezelfde kassadag bundelt in het journaal (kostprijs gevuld, wederhelft `samengevoegd`) → omzet-DTO mét
zeven groepen die cent-exact sluiten op € 10.998,16. De diepe parser-asserts staan in tests/omzet/test_profx.py;
fixtures/ad_omzet_profx_journaal/bron.json beschrijft de herkomst (afzender-mail weggelaten = PII)."""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import text

from app.documenten.models import DocumentSoort, DocumentStatus
from app.omzet import voorstel as voorstel_service
from app.omzet.bronnen import profx
from tests.keten import casussen
from tests.keten import pdf as keten_pdf

BEDRIJF = "De Bazar Apeldoorn B.V."


def _paginas(bestand: str) -> list:
    return json.loads((casussen.FIXTURES / casussen.AD_OMZET_PROFX / bestand).read_text(encoding="utf-8"))


def test_ad_profx_mail_wordt_kassarapport_zonder_ai_en_marge_bundelt(keten) -> None:  # noqa: ANN001
    # De testadministratie krijgt de tenaamstelling van het rapport (register-match op genormaliseerde naam).
    with keten.admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = :naam WHERE id = :id"),
            {"naam": BEDRIJF, "id": keten.administratie_id},
        )
    res = keten.mail(
        [
            ("journaal.pdf", keten_pdf.maak_pdf(_paginas("pdf_tekst.json"))),
            ("marge.pdf", keten_pdf.maak_pdf(_paginas("marge_tekst.json"))),
        ],
        afzender="kassa@coffeeshop.example",  # onbekende afzender: routering op de tenaamstelling ín het rapport
        onderwerp="Facturen - Inboeking journaal en marge raport",
    )
    per_naam = {b.bestandsnaam: b for b in res.bijlagen}
    journaal = per_naam["journaal.pdf"]
    marge = per_naam["marge.pdf"]
    assert journaal.uitkomst == "toegewezen" and journaal.document_id is not None
    assert marge.uitkomst == "toegewezen" and marge.document_id is not None
    assert keten.ai.aanroepen == [], "ProfX is deterministisch — de AI-extractie mag niet zijn aangeroepen"

    doc_j = keten.document(journaal.document_id).document
    doc_m = keten.document(marge.document_id).document
    assert doc_j.soort == DocumentSoort.KASSARAPPORT.value and doc_j.administratie_id == keten.administratie_id
    assert doc_j.status in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.VRAAG_OPEN)
    # Zelfde kassadag → het margerapport is de wederhelft: samengevoegd in het journaal, nooit een tweede omzetboeking.
    assert (doc_m.status, doc_m.samengevoegd_in_id) == (DocumentStatus.SAMENGEVOEGD, journaal.document_id)

    data = voorstel_service.haal_omzet_voorstel_op(
        administratie_id=keten.administratie_id, document_id=journaal.document_id
    )
    assert data.bron == profx.BRON_JOURNAAL
    assert (data.periode_start.isoformat(), data.periode_eind.isoformat()) == ("2026-09-11", "2026-09-11")
    assert [r.categorie for r in data.regels] == ["Dranken", "Edible", "Hash", "Headshop", "Joints", "Snacks", "Wiet"]
    assert sum(r.omzet_bedrag for r in data.regels) == Decimal("10998.16") == data.rapport_totaal_omzet
    assert data.rapport_totaal_kostprijs == Decimal("6295.23") and data.bron_detail["marge"]["stand"] == "gebundeld"
    # Tegenzijde uit blad 3 (kas + PIN), artikellijst (blad 2) wordt niet geboekt.
    assert {k.lower() for k in data.bron_detail["betaalwijzen"]} >= {"cash", "pin"}
    # De lijst-DTO toont het document als kassarapport in de standaardlijst (kantoorwerk).
    rij = keten.lijst_rij(journaal.document_id)
    assert rij is not None and rij["soort"] == "kassarapport"
    assert keten.lijst_rij(marge.document_id) is None  # afgehandeld (samengevoegd) staat niet in de standaardlijst
