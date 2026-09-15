"""Casus (v) — btw-code uit de HISTORIE van de grootboekrekening (vervolg-opdracht Cowork/Peter 14-09; migratie 0143).
Gespeeld op de Floor-PDF (casus b/g: drie regels zónder leesbaar btw-bedrag) in de variant ZONDER leesbaar btw-/incl-
totaal (`casussen.zonder_btw_totaal`, 15-09 — mét totaal wint sinds 15-09 de factuur-afleiding, casus w): het
regel-geheugen zet "Huur materieel" op regel 1 (observatie van Floor zonder btw), RLZ draagt op die rekening géén
PreferentialTaxRate (STAP-0 14-09: overal null), maar ándere leveranciers boekten er in 24 maanden ≥ 5 regels op met
één tarief ≥ 90 % → de nachtelijke afleiding zet de historie-default en de prefill volgt mét herkomst
'grootboek_historie' (ORANJE, chip "meestal op deze rekening (n×)"); de autosave persisteert 'm, checks en DTO zien
dezelfde btw, de grootboek-lijst-DTO draagt de default voor de wissel in het controlescherm. 8/10 = blijft leeg."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.session import scoped_session
from app.documenten.regel_prefill import BTW_BRON_GROOTBOEK_HISTORIE
from app.geheugen import grootboek_btw_historie
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, TAXRATE_HOOG, TAXRATE_VERLEGD_HOOG, Keten

CASUS = Casus(casussen.B_FLOOR)
PDF = CASUS.pdf_bestandsnaam()


def _historie(keten: Keten, *, hoog: int, verlegd: int) -> None:
    """Regel-geheugen voor Floor (zonder btw) + historie van ándere leveranciers op dezelfde rekening."""
    with scoped_session(keten.administratie_id) as session:
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=keten.administratie_id,
                vendor_id=keten.vendors["floor"],
                regel_sleutel=normaliseer_regel_sleutel("Huur per werkdag"),
                gb_id=GB_HUUR_MATERIEEL,
                btw_id=None,  # het geheugen zegt niets over de btw — anders wint het geheugen (stap 3)
                bron="app",
                bron_datum=date(2026, 8, 1),
                boekstuk_ref="RLZ-04-00003100",
            )
        )
        for btw, n in ((TAXRATE_HOOG, hoog), (TAXRATE_VERLEGD_HOOG, verlegd)):
            for i in range(n):
                session.add(
                    BoekingObservatie(
                        id=uuid.uuid4(),
                        administratie_id=keten.administratie_id,
                        vendor_id=keten.vendors["spot"],
                        regel_sleutel=None,
                        gb_id=GB_HUUR_MATERIEEL,
                        btw_id=btw,
                        bron="rlz_seed",
                        bron_datum=date(2026, 3, 1 + i % 20),
                        boekstuk_ref=f"RLZ-04-0000{i:04d}",
                    )
                )
    # De nachtelijke afleiding (sync-alles) — puur code, geen RLZ-call.
    grootboek_btw_historie.herbereken_voor(keten.administratie_id)


@pytest.fixture
def floor_met_historie(keten: Keten) -> uuid.UUID:
    _historie(keten, hoog=9, verlegd=1)  # 9/10 = 90 % → default
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, casussen.zonder_btw_totaal(CASUS.ai_antwoord()))
    return keten.upload(PDF, pdf).document_id


class TestBtwVolgtDeHistorieVanDeRekening:
    def test_prefill_btw_uit_de_historie_oranje_met_detail(self, keten: Keten, floor_met_historie: uuid.UUID) -> None:
        voorstel = keten.prefill(floor_met_historie)
        huur = voorstel.regels[0]
        assert huur.omschrijving == "Huur per werkdag"
        assert huur.ledger_id == GB_HUUR_MATERIEEL and huur.gb_bron == "geheugen"
        assert (huur.taxrate_id, huur.btw_bron) == (TAXRATE_HOOG, BTW_BRON_GROOTBOEK_HISTORIE)
        assert huur.btw_bron_detail == "meestal op deze rekening (10×)"
        assert huur.prefill_herkomst is not None and huur.prefill_herkomst["btw"] == BTW_BRON_GROOTBOEK_HISTORIE
        for regel in voorstel.regels:
            if regel.ledger_id != GB_HUUR_MATERIEEL:
                assert regel.taxrate_id is None

    def test_controlescherm_dto_autosave_checks_en_grootboeklijst(self, keten: Keten, floor_met_historie: uuid.UUID) -> None:
        dto = keten.open_controlescherm(floor_met_historie)
        huur = dto["regels"][0]
        assert huur["taxrate_id"] == str(TAXRATE_HOOG) and huur["btw_bron"] == BTW_BRON_GROOTBOEK_HISTORIE
        assert huur["btw_bron_detail"] == "meestal op deze rekening (10×)"
        assert any(
            "btw regel 1: grootboek_historie" in str(detail) for detail in keten.tijdlijn(floor_met_historie)
        ), "A10-autosave: de herkomst is een trigger"
        ok, melding = keten.checks(floor_met_historie)["Verplichte velden"]
        assert "btw" not in melding.lower(), melding
        assert keten.open_controlescherm(floor_met_historie)["regels"][0]["btw_bron"] == BTW_BRON_GROOTBOEK_HISTORIE
        # De grootboek-lijst draagt de default voor de wissel in het controlescherm (zonder RLZ-default).
        resp = keten.api.get(f"/administraties/{keten.administratie_id}/grootboek", headers=keten.headers)
        assert resp.status_code == 200, resp.text
        rekening = next(r for r in resp.json()["rekeningen"] if r["ledger_id"] == str(GB_HUUR_MATERIEEL))
        assert rekening["standaard_taxrate_id"] is None
        assert (rekening["historie_taxrate_id"], rekening["historie_taxrate_n"]) == (str(TAXRATE_HOOG), 10)

    def test_acht_van_tien_blijft_leeg(self, keten: Keten) -> None:
        _historie(keten, hoog=8, verlegd=2)
        pdf = CASUS.pdf()
        keten.ai.registreer(pdf, casussen.zonder_btw_totaal(CASUS.ai_antwoord()))
        document_id = keten.upload(PDF, pdf).document_id
        huur = keten.prefill(document_id).regels[0]
        assert huur.ledger_id == GB_HUUR_MATERIEEL and huur.taxrate_id is None and huur.btw_bron is None
        resp = keten.api.get(f"/administraties/{keten.administratie_id}/grootboek", headers=keten.headers)
        rekening = next(r for r in resp.json()["rekeningen"] if r["ledger_id"] == str(GB_HUUR_MATERIEEL))
        assert rekening["historie_taxrate_id"] is None and rekening["historie_taxrate_n"] is None
