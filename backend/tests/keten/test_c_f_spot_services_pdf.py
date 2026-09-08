"""Casus (c) — Spot Services 2026-608 (PDF-scan, upload 07-09, geboekt 08-09 RLZ-04-00003232): 12 gelezen regels
waarvan 9 tariefstaffel-regels (aantal 0, € 0), projectnummer 26049 in de kop, "Verlegd" in het totaalblok, btw 0.
Casus (f) — dezelfde factuur staat al (handmatig) in RLZ: Entity+Reference+bedrag-treffer → afgevoerd mét boekstuk.
Casus (j) — de administratie heeft geen eigenaar: de afvoer loopt door, toewijzing blijft leeg."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine

from app.db.session import scoped_session
from app.documenten.models import DocumentStatus
from app.documenten.regel_prefill import BTW_BRON_FACTUUR_VERLEGD, verlegd_taxrate_voor
from app.geheugen.models import BoekingObservatie
from app.sync.models import TaxRateCache
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_INHUUR, PROJECT_26049, TAXRATE_VERLEGD_HOOG, Keten

CASUS = Casus(casussen.C_SPOT)
PDF = CASUS.pdf_bestandsnaam()
TAXRATE_VERLEGD_LAAG = uuid.UUID("55555555-0000-0000-0000-000000000010")


@pytest.fixture
def spot(keten: Keten) -> uuid.UUID:
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


class TestExtractieEnLijst:
    def test_upload_extractie_en_standaardlijst(self, keten: Keten, spot: uuid.UUID) -> None:
        assert keten.status(spot) == DocumentStatus.TE_CONTROLEREN
        assert len(keten.ai.aanroepen) == 1
        rij = keten.lijst_rij(spot)
        assert rij is not None and rij["status"] == "te_controleren"
        assert Decimal(rij["totaalbedrag"]) == Decimal("2767.00") and rij["factuurdatum"] == "2026-09-07"
        assert rij["leverancier"] in ("Spot Services B.V", "Spot Services B.V.")
        assert rij["duplicaatsignaal"] is not None and rij["duplicaatsignaal"]["uitkomst"] == "geen"
        veldvoorstel = keten.document(spot).veldvoorstel
        assert veldvoorstel["tariefstaffel_aantal"] == 9
        assert veldvoorstel["btw_verlegd_vermelding"] == "Verlegd"


class TestControlescherm:
    def test_prefill_nulregels_weg_project_op_alle_regels_verlegd_oranje(self, keten: Keten, spot: uuid.UUID) -> None:
        dto = keten.open_controlescherm(spot)
        voorstel = keten.prefill(spot)
        assert voorstel.vendor_id == keten.vendors["spot"]  # via btw-nummer, ondanks 'B.V' zonder punt
        assert voorstel.referentie == "2026-608"
        assert voorstel.factuurdatum == date(2026, 9, 7) and voorstel.vervaldatum == date(2026, 9, 14)
        assert voorstel.totaalbedrag == Decimal("2767.00")
        # 4a: tariefstaffel-regels zijn geen boekingsregel — drie échte regels blijven.
        assert [(r.omschrijving, r.netto_bedrag) for r in voorstel.regels] == [
            ("Montage", Decimal("1680.00")),
            ("Regie", Decimal("387.00")),
            ("Net", Decimal("700.00")),
        ]
        # 4b: het ene projectnummer (kop) vult álle regels — exacte code = groen 'factuur'.
        assert all(r.project_id == PROJECT_26049 for r in voorstel.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "factuur" for r in voorstel.regels)
        # 4c: "Verlegd" + btw 0 → het ene NL-verlegd-tarief, oranje herkomst factuur_verlegd.
        assert all(r.taxrate_id == TAXRATE_VERLEGD_HOOG for r in voorstel.regels)
        assert all(r.btw_bron == BTW_BRON_FACTUUR_VERLEGD for r in voorstel.regels)
        # Kop: omschrijving uit 'betreft', periode week 34.
        assert voorstel.omschrijving == "Week 34"
        assert voorstel.periode is not None and (voorstel.periode.week_van, voorstel.periode.week_tot) == (34, 34)
        assert dto["referentie"] == "2026-608" and len(dto["regels"]) == 3

    def test_checks_alleen_grootboek_ontbreekt(self, keten: Keten, spot: uuid.UUID) -> None:
        keten.open_controlescherm(spot)
        checks = keten.checks(spot)
        assert checks["Duplicaatcheck"][0] and checks["Duplicaat (module)"][0]
        assert checks["Regeltelling vs totaal"][0], checks["Regeltelling vs totaal"][1]
        assert checks["Vervaldatum"][0]
        ok, melding = checks["Verplichte velden"]
        assert not ok
        assert melding == "Ontbrekend: grootboekrekening (alle 3 regels)"

    def test_exporteer_frontend_fixture(self, keten: Keten, spot: uuid.UUID) -> None:
        keten.exporteer("c_spot_services", spot, extra={"stamgegevens": {"grootboek_inhuur": str(GB_INHUUR)}})


class TestVerlegdDeterministisch:
    """Blok 6: twee NL-verlegd-tarieven zonder RLZ-favoriet — het voorstel mag niet leeg blijven."""

    def _tweede_verlegd_tarief(self, keten: Keten) -> None:
        with scoped_session(keten.administratie_id) as session:
            session.add(
                TaxRateCache(
                    id=TAXRATE_VERLEGD_LAAG,
                    administratie_id=keten.administratie_id,
                    naam="NL, BTW verlegd (laag)",
                    percentage=Decimal("0"),
                    brondata={"Name": "NL, BTW verlegd (laag)", "IsRelayed": True, "IsFavorite": False},
                )
            )

    def test_huidig_gedrag_meerduidig_verlegd_vult_niets(self, keten: Keten) -> None:
        self._tweede_verlegd_tarief(keten)
        with scoped_session(keten.administratie_id) as session:
            assert verlegd_taxrate_voor(session, administratie_id=keten.administratie_id) is None

    def test_meest_gebruikt_in_historie_wint(self, keten: Keten, spot: uuid.UUID) -> None:
        self._tweede_verlegd_tarief(keten)
        with scoped_session(keten.administratie_id) as session:
            for i in range(3):
                session.add(
                    BoekingObservatie(
                        id=uuid.uuid4(),
                        administratie_id=keten.administratie_id,
                        vendor_id=keten.vendors["spot"],
                        regel_sleutel=None,
                        gb_id=GB_INHUUR,
                        btw_id=TAXRATE_VERLEGD_HOOG,
                        bron="rlz_seed",
                        bron_datum=date(2026, 6, 1 + i),
                        boekstuk_ref=f"RLZ-04-0000300{i}",
                    )
                )
        with scoped_session(keten.administratie_id) as session:
            assert verlegd_taxrate_voor(session, administratie_id=keten.administratie_id) == TAXRATE_VERLEGD_HOOG
        voorstel = keten.prefill(spot)
        assert all(r.taxrate_id == TAXRATE_VERLEGD_HOOG for r in voorstel.regels)


class TestAlInRlz:
    """Casus (f): de factuur staat al in RLZ (handmatig geboekt, boekstuk RLZ-04-00003232)."""

    RLZ_ID = uuid.UUID("3cc216fb-a4c6-52a3-84f3-c52fbafa97a6")

    def _treffer(self, keten: Keten) -> None:
        keten.rlz.duplicaten = [
            {"id": str(self.RLZ_ID), "Reference": "2026-608", "InvoiceNumber": "RLZ-04-00003232", "TotalAmount": 2767.0}
        ]

    def test_pdf_treffer_na_extractie_afgevoerd_met_boekstuk_zonder_toewijzing(self, keten: Keten) -> None:
        self._treffer(keten)
        pdf = CASUS.pdf()
        keten.ai.registreer(pdf, CASUS.ai_antwoord())
        document_id = keten.upload(PDF, pdf).document_id
        assert keten.status(document_id) == DocumentStatus.AFGEVOERD_DUPLICAAT
        assert str(document_id) not in keten.standaardlijst_ids()
        afwijzing = keten.afwijzing(document_id)
        assert afwijzing is not None and afwijzing["automatisch"] is True
        assert afwijzing["duplicaat_van_rlz_document_id"] == self.RLZ_ID
        assert afwijzing["duplicaat_van_document_id"] is None
        assert "RLZ-04-00003232" in afwijzing["reden"]
        assert afwijzing["toegewezen_aan"] is None and keten.rij(document_id)["toegewezen_aan"] is None  # casus j
        rij = keten.lijst_rij(document_id, toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "afgevoerd_duplicaat"

    def test_reden_tekst_al_geboekt_in_rlz_buiten_de_module(self, keten: Keten) -> None:
        self._treffer(keten)
        pdf = CASUS.pdf()
        keten.ai.registreer(pdf, CASUS.ai_antwoord())
        document_id = keten.upload(PDF, pdf).document_id
        afwijzing = keten.afwijzing(document_id)
        assert afwijzing is not None
        assert "al geboekt in RLZ (buiten de module)" in afwijzing["reden"]
        assert "RLZ-04-00003232" in afwijzing["reden"]

    def test_zonder_treffer_blijft_het_werk(self, keten: Keten, spot: uuid.UUID) -> None:
        assert keten.status(spot) == DocumentStatus.TE_CONTROLEREN
        assert keten.afwijzing(spot) is None


class TestUblAlInRlz:
    """Casus (f) UBL-variant (BDO 6088744): de RLZ-bestaanscheck draait al bij intake — geen extractie nodig."""

    def test_ubl_treffer_bij_intake(self, keten: Keten) -> None:
        bdo = Casus(casussen.H_BDO)
        rlz_id = uuid.uuid4()
        keten.rlz.duplicaten = [{"id": str(rlz_id), "Reference": "6088744", "InvoiceNumber": "RLZ-04-00003100"}]
        pdf = bdo.pdf()
        resultaat = keten.mail([(bdo.xml_bestandsnaam(), bdo.xml(ingesloten_pdf=pdf)), (bdo.pdf_bestandsnaam(), pdf)])
        document_id = resultaat.bijlagen[0].document_id
        assert keten.ai.aanroepen == []
        assert keten.status(document_id) == DocumentStatus.AFGEVOERD_DUPLICAAT
        afwijzing = keten.afwijzing(document_id)
        assert afwijzing is not None and afwijzing["duplicaat_van_rlz_document_id"] == rlz_id
        assert "RLZ-04-00003100" in afwijzing["reden"]
        assert str(document_id) not in keten.standaardlijst_ids()


def _admin(admin_engine: Engine) -> Engine:  # pragma: no cover — alleen voor type-lezers
    return admin_engine
