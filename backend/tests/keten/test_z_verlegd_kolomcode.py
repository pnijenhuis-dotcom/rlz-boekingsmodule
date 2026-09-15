"""Casus (z) — verlegd herkennen op KOLOMCODE "V" zonder het woord verlegd (Peter 15-09, casus Olieman/Bouwadvies
Oost Nederland: factuur 32948, "1e termijn werkzaamheden", 20.000,00 met "V" in de BTW-kolom, "BTW 0,00 % over
20000,00").

(b) De kolomcode op álle regels mét bedrag + factuur-btw 0 → `btw_verlegd_kolom` "V" en de prefill zet het
verlegd-tarief van de administratie voor (oranje `factuur_verlegd`, chip-detail noemt de kolomcode). (c) Ná één
mens-boeking is de leverancier voor deze administratie een verlegd-leverancier: de tweede termijn ZONDER kolomcode wordt
óók verlegd (leverancier-geheugen). Negatief: een vrijgestelde factuur (0 %, kolom "vrij", telecom-leverancier
zonder verlegd-historie)
blijft leeg — 0 % ≠ verlegd. Fixtures: fixtures/z_verlegd_kolomcode_v/ (geanonimiseerd, kolom "V" behouden)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten.models import CrediteurKenmerk, Document, DocumentBron, DocumentSoort, DocumentStatus
from app.documenten.regel_prefill import BTW_BRON_FACTUUR_VERLEGD
from app.geheugen.models import BoekingObservatie
from app.sync.models import VendorCache
from app.verplichting import match as match_motor
from app.verplichting import match_pipeline
from app.verplichting import service as verplichting_service
from app.verplichting.models import Verplichting
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_INHUUR, TAXRATE_VERLEGD_HOOG, Keten

CASUS = Casus(casussen.Z_VERLEGD_KOLOMCODE)
PDF = CASUS.pdf_bestandsnaam()
VENDOR_GRONDWERK = uuid.UUID("33333333-0000-0000-0000-000000000073")


@pytest.fixture
def grondwerk_vendor(keten: Keten) -> uuid.UUID:
    """De leverancier bestaat als crediteur (naam + KvK/btw uit de factuur), zonder enige boekingshistorie."""
    kop = CASUS.ai_antwoord().kop
    with scoped_session(keten.administratie_id) as session:
        session.add(
            VendorCache(
                id=VENDOR_GRONDWERK,
                administratie_id=keten.administratie_id,
                naam="Grondwerken Reeuwijk B.V.",
                brondata={"Name": "Grondwerken Reeuwijk B.V."},
            )
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=keten.administratie_id,
                vendor_id=VENDOR_GRONDWERK,
                btw_nummer=kop["btw_nummer"].waarde,
                btw_nummer_geverifieerd=True,
                btw_nummer_bron="factuur",
                kvk_nummer=kop["kvk_nummer"].waarde,
                kvk_nummer_bron="factuur",
            )
        )
    return VENDOR_GRONDWERK


def _upload(keten: Keten, bestand: str = "ai_antwoord.json", *, naam: str = PDF) -> uuid.UUID:
    pdf = CASUS.pdf()
    if bestand != "ai_antwoord.json":
        pdf = pdf + bestand.encode()  # andere bytes → eigen sha in de AI-stub en geen duplicaat
    keten.ai.registreer(pdf, CASUS.ai_antwoord(bestand))
    return keten.upload(naam, pdf).document_id


class TestKolomcodeV:
    def test_veldvoorstel_draagt_de_kolomcode_en_de_prefill_zet_verlegd_voor(
        self, keten: Keten, grondwerk_vendor: uuid.UUID
    ) -> None:
        document_id = _upload(keten)
        veldvoorstel = keten.document(document_id).veldvoorstel
        assert veldvoorstel["btw_verlegd_vermelding"] is None  # het woord verlegd staat er niet
        assert veldvoorstel["btw_verlegd_kolom"] == "V"
        assert veldvoorstel["regels"][0]["btw_kolom"] == "V" and veldvoorstel["regels"][0]["btw_kolom_verlegd"] is True
        voorstel = keten.prefill(document_id)
        assert voorstel.vendor_id == grondwerk_vendor
        (regel,) = voorstel.regels
        assert (regel.netto_bedrag, regel.taxrate_id, regel.btw_bron) == (
            Decimal("20000.00"),
            TAXRATE_VERLEGD_HOOG,
            BTW_BRON_FACTUUR_VERLEGD,
        )
        assert regel.btw_bron_detail is not None and regel.btw_bron_detail.startswith('kolomcode "V" op alle regels')
        assert regel.project_id is None  # geen project "Uitweg 30 Woerdense Verlaat" in de administratie: nooit raden
        dto = keten.open_controlescherm(document_id)
        assert dto["regels"][0]["taxrate_id"] == str(TAXRATE_VERLEGD_HOOG)
        assert dto["regels"][0]["btw_bron"] == BTW_BRON_FACTUUR_VERLEGD

    def test_tweede_termijn_zonder_kolomcode_is_verlegd_via_het_leverancier_geheugen(
        self, keten: Keten, grondwerk_vendor: uuid.UUID
    ) -> None:
        # Zonder historie én zonder kolomcode: 0 % blijft leeg (vrijgesteld ≠ verlegd).
        tweede = _upload(keten, "ai_antwoord_tweede_termijn.json", naam="Factuur 32971.pdf")
        assert keten.document(tweede).veldvoorstel["btw_verlegd_kolom"] is None
        (regel,) = keten.prefill(tweede).regels
        assert regel.taxrate_id is None
        # Eén eerdere mens-boeking op het verlegd-tarief (het leverancier-geheugen zoals leg_boeking_vast 'm schrijft).
        with scoped_session(keten.administratie_id) as session:
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=keten.administratie_id,
                    vendor_id=grondwerk_vendor,
                    regel_sleutel=None,
                    regel_omschrijving_raw="1e termijn werkzaamheden",
                    gb_id=GB_INHUUR,
                    btw_id=TAXRATE_VERLEGD_HOOG,
                    project_id=None,
                    bron="app",
                    bron_datum=date(2026, 9, 4),
                    boekstuk_ref="RLZ-01-00000001",
                )
            )
        derde = _upload(keten, "ai_antwoord_tweede_termijn.json", naam="Factuur 32971 (2).pdf")
        with scoped_session(keten.administratie_id) as session:
            basis = boekvoorstel.bepaal_verlegd_basis(
                session,
                administratie_id=keten.administratie_id,
                vendor_id=grondwerk_vendor,
                veldvoorstel=keten.document(derde).veldvoorstel,
            )
        assert basis is not None and basis.soort == boekvoorstel.VERLEGD_BASIS_GEHEUGEN
        (regel,) = keten.prefill(derde).regels
        # In de winnaarsvolgorde staat het leverancier-GEHEUGEN (stap 3) vóór factuur-verlegd (stap 4): dezelfde
        # observatie vult het verlegd-tarief al als geheugen-voorstel; (c) is de terugval als de engine niets zegt.
        assert regel.taxrate_id == TAXRATE_VERLEGD_HOOG
        assert (regel.prefill_herkomst or {}).get("btw") in {"leverancier_geheugen", BTW_BRON_FACTUUR_VERLEGD}


class TestVrijgesteldBlijftLeeg:
    def test_nul_procent_zonder_kolomcode_vermelding_of_verlegd_leverancier_blijft_leeg(self, keten: Keten) -> None:
        document_id = _upload(keten, "ai_antwoord_vrijgesteld.json", naam="Factuur VRZ-2026-0915.pdf")
        veldvoorstel = keten.document(document_id).veldvoorstel
        assert veldvoorstel["btw_verlegd_kolom"] is None and veldvoorstel["btw_verlegd_vermelding"] is None
        assert (
            veldvoorstel["regels"][0]["btw_kolom"] == "vrij" and veldvoorstel["regels"][0]["btw_kolom_verlegd"] is False
        )
        voorstel = keten.prefill(document_id)
        assert voorstel.vendor_id == keten.vendors["telecom"]
        (regel,) = voorstel.regels
        assert regel.taxrate_id != TAXRATE_VERLEGD_HOOG and regel.btw_bron != BTW_BRON_FACTUUR_VERLEGD


class TestOfferteMatchOpDeTermijnfactuur:
    """Peter 15-09 (opdracht offerte-match-olieman-stil): dezelfde factuur 32948 mét een Olieman-offerte van € 85.000
    die nog op één accordeur wacht → zichtbaar "gevonden maar niet toetsbaar", ná goedkeuring "binnen, 1e termijn"."""

    def _offerte(self, keten: Keten, vendor_id: uuid.UUID, *, status: DocumentStatus) -> uuid.UUID:
        offerte_id = uuid.uuid4()
        with scoped_session(keten.administratie_id, actor_id=keten.actor) as session:
            session.add(
                Document(
                    id=offerte_id,
                    administratie_id=keten.administratie_id,
                    bron=DocumentBron.UPLOAD,
                    bestandsnaam="offerte-uitweg-30.pdf",
                    sha256_hash="z" * 64,
                    opslag_pad="offertes/uitweg-30.pdf",
                    status=status,
                    soort=DocumentSoort.VERPLICHTING.value,
                   
                )
            )
            session.add(
                Verplichting(
                    document_id=offerte_id,
                    administratie_id=keten.administratie_id,
                    soort_label="offerte",
                    vendor_id=vendor_id,
                    project_id=None,
                    offertenummer="OFF-2026-085",
                    datum=date(2026, 8, 20),
                    totaalbedrag_excl=Decimal("85000.00"),
                    geldig_tot=date(2026, 12, 31),
                    omschrijving="Werk Uitweg 30 Woerdense Verlaat",
                )
            )
        return offerte_id

    def test_wachtende_offerte_zichtbaar_dan_binnen_eerste_termijn(
        self, keten: Keten, grondwerk_vendor: uuid.UUID
    ) -> None:
        offerte = self._offerte(keten, grondwerk_vendor, status=DocumentStatus.TER_ACCORDERING)
        document_id = _upload(keten)
        keten.prefill(document_id)  # autosave → vendor + bedrag bekend
        match_pipeline.bereken_match(administratie_id=keten.administratie_id, document_id=document_id)
        data = verplichting_service.haal_match_op(administratie_id=keten.administratie_id, document_id=document_id)
        assert data.uitkomst == match_motor.NIET_TOETSBAAR
        assert data.verplichting is not None and data.verplichting.document_id == offerte
        assert data.niet_toetsbaar_reden == "nog niet goedgekeurd (wacht op accordering)"
        dto = keten.api.get(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/verplichting-match",
            headers=keten.headers,
        ).json()
        assert dto["uitkomst"] == "niet_toetsbaar" and dto["niet_toetsbaar_reden"] == data.niet_toetsbaar_reden
        assert dto["verplichting"]["offertenummer"] == "OFF-2026-085"

        # Goedkeuring (zoals accordering/service 'm vastlegt) → herberekening → binnen, 1e termijn 20.000 van 85.000.
        with scoped_session(keten.administratie_id, actor_id=keten.actor) as session:
            session.get(Document, offerte).status = DocumentStatus.GEACCORDEERD
            verplichting_service.leg_goedkeuring_vast_in_sessie(
                session, administratie_id=keten.administratie_id, document_id=offerte, actor_id=keten.actor
            )
        match_pipeline.herbereken_na_verplichting_wijziging(
            administratie_id=keten.administratie_id, verplichting_document_id=offerte
        )
        data = verplichting_service.haal_match_op(administratie_id=keten.administratie_id, document_id=document_id)
        assert data.uitkomst == match_motor.BINNEN and data.termijn == 1 and data.percentage_na == 24
        assert data.verbruik_na == Decimal("20000.00") and data.verplichting.totaal_excl == Decimal("85000.00")
        assert "(1e termijn, € 20.000,00)" in data.melding
