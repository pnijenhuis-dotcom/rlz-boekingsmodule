"""Casus (ad, vervolg 19-09) — kassarapport automatisch typeren (Peter 19-09 "als de module weet dat het verkoopboekingen
zijn, wijzig het dan automatisch"): een ProfX-journaal dat als INKOOPFACTUUR wordt geüpload (werkvoorraad-sleepzone mét
klant, bulk-upload — de soort is dan de default van de upload-plek) wordt DIRECT een kassarapport mét tijdlijnregel + audit
en loopt de deterministische omzetketen (géén AI-call). Tegenproef op de hele gouden set: geen enkele échte inkoop-casus
geeft een parser-treffer — de automatische typering raakt nooit een gewone factuur."""

from __future__ import annotations

import json

from app.documenten.models import DocumentSoort, DocumentStatus
from app.omzet import autotype
from app.omzet import voorstel as voorstel_service
from tests.keten import casussen
from tests.keten import pdf as keten_pdf


def _paginas(bestand: str) -> list:
    return json.loads((casussen.FIXTURES / casussen.AD_OMZET_PROFX / bestand).read_text(encoding="utf-8"))


def test_ad2_profx_upload_als_inkoopfactuur_wordt_automatisch_kassarapport_zonder_ai(keten) -> None:  # noqa: ANN001
    res = keten.upload("Journaal 1-9.pdf", keten_pdf.maak_pdf(_paginas("pdf_tekst.json")))
    assert keten.ai.aanroepen == [], "ProfX is deterministisch — de AI-extractie mag niet zijn aangeroepen"
    doc = keten.document(res.document_id).document
    assert doc.soort == DocumentSoort.KASSARAPPORT.value
    assert doc.status in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.VRAAG_OPEN)
    regels = [g for g in keten.tijdlijn(res.document_id) if autotype.TIJDLIJN_SLEUTEL in g]
    assert len(regels) == 1
    assert regels[0]["reden"] == "type automatisch gewijzigd: inkoopfactuur → kassarapport (ProfX-journaal herkend)"
    data = voorstel_service.haal_omzet_voorstel_op(administratie_id=keten.administratie_id, document_id=res.document_id)
    assert data.automatisch_getypeerd_bron == "profx_journaal" and data.bron == "profx_journaal"
    assert len(data.regels) >= 1


def test_geen_enkele_inkoop_casus_van_de_gouden_set_is_een_parser_treffer() -> None:
    """Tegenproef: alle échte inkoop-PDF's (Universal Nederland, Floor, Spot, BOOT, BDO, DCTE, Kader, Rituals, Zilver,
    telefonie, verlegd-kolomcode …) blijven inkoopfactuur — `autotype.herken` is None; alleen de ProfX-casus treft."""
    treffers: dict[str, str | None] = {}
    for map_ in sorted(p for p in casussen.FIXTURES.iterdir() if p.is_dir()):
        pdf_tekst = map_ / "pdf_tekst.json"
        if not pdf_tekst.exists():
            continue
        paginas = json.loads(pdf_tekst.read_text(encoding="utf-8"))
        treffers[map_.name] = autotype.herken(f"{map_.name}.pdf", keten_pdf.maak_pdf(paginas))
    assert treffers.get(casussen.AD_OMZET_PROFX) == "profx_journaal"
    onterecht = {naam: bron for naam, bron in treffers.items() if bron is not None and naam != casussen.AD_OMZET_PROFX}
    assert onterecht == {}, f"inkoop-casussen mét parser-treffer (zouden automatisch kassarapport worden): {onterecht}"
