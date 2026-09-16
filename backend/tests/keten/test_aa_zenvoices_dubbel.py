"""Casus (aa) — Zenvoices-dubbel 16-09 (Peter): Hello Kitchen Duiven 24594001722 (€ 12.600,00, 10-08-2026) stond via
Zenvoices al in RLZ als RLZ-04-00004314 (Status 3); de module las de UBL/factuur als "2 4594 001722" (spaties uit de
factuur-opmaak) en de bestaanscheck vergeleek letterlijk → tweede boeking én tweede betaling (productie Kempen
Facilities, docs e7845955/9ea6ca98). Doelgedrag blok B: genormaliseerd vergelijken over de crediteur-identiteit in een
datumvenster — bij intake al afgevoerd mét het RLZ-boekstuknummer; een concept blokkeert de boeking; zelfde bedrag/datum
met een ander nummer is een oranje signaal. Fixture: zie fixtures/aa_zenvoices_dubbel/bron.json."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.documenten import duplicaat_afvoer
from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

CASUS = Casus(casussen.AA_ZENVOICES_DUBBEL)
XML = "Hello Kitchen Duiven B.V - 2 4594 001722 - 2026-08-10.xml"
ZENVOICES_ID = str(uuid.UUID("bfa1949e-0000-4000-8000-000000000001"))


def _zenvoices_rij(*, status: int, referentie: str = "24594001722", bedrag: float = 12600.0, datum: str = "2026-08-10"):
    return {
        "id": ZENVOICES_ID,
        "Reference": referentie,
        "InvoiceReference": referentie,
        "ReceiptNumber": "RLZ-04-00004314",
        "Status": status,
        "BaseInvoiceAmount": bedrag,
        "Date": f"{datum}T00:00:00",
        "Description": "Hello Kitchen Duiven B.V. 24594001722 door te belasten mantelzorg",
    }


class TestZenvoicesExemplaarGeboekt:
    @pytest.fixture
    def intake(self, keten: Keten):
        keten.rlz.kandidaten = [_zenvoices_rij(status=3)]
        return keten.mail([(XML, CASUS.xml())], onderwerp="Factuur Hello Kitchen")

    def test_ubl_bij_intake_direct_afgevoerd_met_rlz_boekstuknummer(self, keten: Keten, intake) -> None:
        document_id = intake.bijlagen[0].document_id
        assert keten.status(document_id) is DocumentStatus.AFGEVOERD_DUPLICAAT
        afwijzing = keten.afwijzing(document_id)
        assert afwijzing is not None and afwijzing["automatisch"] is True
        assert "RLZ-04-00004314" in afwijzing["reden"] and "24594001722" in afwijzing["reden"]
        assert "buiten de module" in afwijzing["reden"]
        assert str(afwijzing["duplicaat_van_rlz_document_id"]) == ZENVOICES_ID
        assert str(document_id) not in keten.standaardlijst_ids()

    def test_prefill_droeg_de_letterlijke_referentie_en_de_genormaliseerde_vorm(self, keten: Keten, intake) -> None:
        document_id = intake.bijlagen[0].document_id
        voorstel = keten.prefill(document_id)
        assert voorstel.referentie == "2 4594 001722"
        with keten.admin_engine.connect() as conn:
            norm = conn.execute(
                text("SELECT referentie_norm FROM boekhouding.boekvoorstel WHERE document_id = :id"),
                {"id": document_id},
            ).scalar_one()
        # Migratie 0147: de vergelijkingsvorm reist mee met de letterlijke referentie.
        assert norm == "24594001722"

    def test_stand_toont_het_externe_origineel(self, keten: Keten, intake) -> None:
        document_id = intake.bijlagen[0].document_id
        stand = duplicaat_afvoer.stand_voor_document(administratie_id=keten.administratie_id, document_id=document_id)
        assert stand.afgevoerd_als_duplicaat_van is not None
        assert str(stand.afgevoerd_als_duplicaat_van.rlz_document_id) == ZENVOICES_ID
        assert stand.afgevoerd_als_duplicaat_van.buiten_de_module  # geen app-document: het origineel leeft in RLZ
        assert stand.afgevoerd_als_duplicaat_van.referentie == "24594001722"


class TestZenvoicesExemplaarConcept:
    def test_concept_blokkeert_de_boeking_met_boekstuk_maar_voert_niet_direct_af(self, keten: Keten) -> None:
        keten.rlz.kandidaten = [_zenvoices_rij(status=1)]
        document_id = keten.mail([(XML, CASUS.xml())]).bijlagen[0].document_id
        # Concept = twijfelgeval onder de dagrem (blok 4 08-09, beslispunt 1): niet direct af, wél zichtbaar.
        assert keten.status(document_id) in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.AFGEVOERD_DUPLICAAT)
        if keten.status(document_id) is DocumentStatus.TE_CONTROLEREN:
            checks = keten.checks(document_id)
            ok, melding = checks["Duplicaatcheck"]
            assert ok is False
            assert "RLZ-04-00004314" in melding and "concept" in melding


class TestAnderNummerZelfdeBedrag:
    def test_zelfde_bedrag_en_datum_ander_nummer_is_oranje_signaal_geen_blokkade(self, keten: Keten) -> None:
        keten.rlz.kandidaten = [_zenvoices_rij(status=3, referentie="24594001731", datum="2026-08-14")]
        document_id = keten.mail([(XML, CASUS.xml())]).bijlagen[0].document_id
        assert keten.status(document_id) is DocumentStatus.TE_CONTROLEREN
        ok, melding = keten.checks(document_id)["Duplicaatcheck"]
        assert ok is True and "hetzelfde bedrag rond dezelfde datum" in melding and "RLZ-04-00004314" in melding


class TestGeenExemplaar:
    def test_zonder_extern_exemplaar_gewoon_te_controleren_en_check_groen(self, keten: Keten) -> None:
        keten.rlz.kandidaten = []
        document_id = keten.mail([(XML, CASUS.xml())]).bijlagen[0].document_id
        assert keten.status(document_id) is DocumentStatus.TE_CONTROLEREN
        ok, _ = keten.checks(document_id)["Duplicaatcheck"]
        assert ok is True
