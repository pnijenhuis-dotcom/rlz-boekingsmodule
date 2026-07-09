from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.models import DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.statusmachine import valideer_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.sync import service as sync_service
from tests.documenten.test_ubl import _VOORBEELD_UBL
from tests.sync.conftest import FakeRlzClient


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("50.00"),
        btw_bedrag=Decimal("10.50"),
        omschrijving=None,
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


class TestPrefillZonderOpgeslagenVoorstel:
    def test_pdf_zonder_ubl_geeft_volledig_leeg_voorstel(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 x",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert data.opgeslagen is False
        assert data.vendor_id is None
        assert data.regels == []

    def test_ubl_vult_referentie_datum_totaal_en_een_regel_voor(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert data.opgeslagen is False
        assert data.referentie == "2026-0642"
        assert data.factuurdatum is not None
        assert data.totaalbedrag is not None
        assert len(data.regels) == 1
        regel = data.regels[0]
        assert regel.netto_bedrag is not None and regel.btw_bedrag is not None
        assert (regel.netto_bedrag + regel.btw_bedrag) == data.totaalbedrag

    def test_ubl_raadt_vendor_bij_exacte_naammatch(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        vendor_id = uuid.uuid4()
        sync_service.sync_vendors(
            administratie_id=administratie_id,
            client=FakeRlzClient(
                {"Vendors": [{"id": str(vendor_id), "Name": "Bouwmaat Nederland B.V.", "IsArchived": False}]}
            ),
        )
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        # De voorbeeld-UBL heeft leverancier "Bouwmaat Nederland B.V." (zie test_ubl.py).
        assert data.vendor_id == vendor_id

    def test_geen_gok_bij_meerdere_gelijknamige_vendors(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        sync_service.sync_vendors(
            administratie_id=administratie_id,
            client=FakeRlzClient(
                {
                    "Vendors": [
                        {"id": str(uuid.uuid4()), "Name": "Bouwmaat Nederland B.V.", "IsArchived": False},
                        {"id": str(uuid.uuid4()), "Name": "bouwmaat nederland b.v.", "IsArchived": False},
                    ]
                }
            ),
        )
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert data.vendor_id is None


class TestOpslaanEnOphalen:
    def test_roundtrip_bewaart_kop_en_regels_in_volgorde(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 y",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        vendor_id = uuid.uuid4()
        eerste_regel, tweede_regel = _regel(omschrijving="Eerste"), _regel(omschrijving="Tweede")

        opgeslagen = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="F-123",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[eerste_regel, tweede_regel],
        )
        assert opgeslagen.opgeslagen is True
        assert opgeslagen.vendor_id == vendor_id
        assert [r.omschrijving for r in opgeslagen.regels] == ["Eerste", "Tweede"]

        opnieuw_opgehaald = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
        assert [r.omschrijving for r in opnieuw_opgehaald.regels] == ["Eerste", "Tweede"]

    def test_opnieuw_opslaan_vervangt_de_regels_volledig(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 z",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("100.00"),
            regels=[_regel(omschrijving="Oud-1"), _regel(omschrijving="Oud-2")],
        )
        opnieuw = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("50.00"),
            regels=[_regel(omschrijving="Nieuw")],
        )
        assert [r.omschrijving for r in opnieuw.regels] == ["Nieuw"]

    def test_geboekt_document_is_bevroren(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 bevroren",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            from app.documenten.models import Document

            document = session.get(Document, resultaat.document_id)
            assert document is not None
            valideer_overgang(document.status, DocumentStatus.KLAAR_OM_TE_BOEKEN)
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
            _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker)

        with pytest.raises(boekvoorstel.BoekvoorstelFout):
            boekvoorstel.sla_boekvoorstel_op(
                administratie_id=administratie_id,
                document_id=resultaat.document_id,
                actor_id=gescoopte_gebruiker,
                vendor_id=uuid.uuid4(),
                referentie="F-1",
                factuurdatum=date(2026, 7, 1),
                totaalbedrag=Decimal("1.00"),
                regels=[_regel()],
            )

    def test_onbekend_document_geeft_documentnietgevonden(self, administratie_id: uuid.UUID) -> None:
        with pytest.raises(service.DocumentNietGevonden):
            boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=uuid.uuid4())


class TestVoerChecksUit:
    def test_gebruikt_het_opgeslagen_voorstel_niet_de_ubl_prefill(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        """Zodra de controleur iets opslaat (ook een expres leeg veld), telt dát — niet de UBL-
        prefill die er nog "onder" zit."""
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie=None,
            factuurdatum=None,
            totaalbedrag=None,
            regels=[],
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=resultaat.document_id, client=FakeRlzClient({})
        )
        assert rapport.geblokkeerd

    def test_geen_credentials_geeft_checkrapport_geen_kale_exception(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        """De `administratie_id`-fixture heeft een willekeurig rlz_admin_id zonder geregistreerde
        credentials (app/rlz/credentials.py::BEKENDE_ADMINISTRATIES) — zonder expliciete client
        opent voer_checks_uit() er zelf een, en dat resolven faalt hier altijd. Dat mag nooit een
        onafgevangen GeenRlzCredentials worden (de bug uit de kliktest): de twee lokale checks
        moeten gewoon hun echte oordeel geven, en de duplicaatcheck wordt een herkenbaar,
        blokkerend checkresultaat."""
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 geen-credentials",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"))],
        )

        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=resultaat.document_id)

        assert [r.naam for r in rapport.resultaten] == ["Verplichte velden", "Regeltelling vs totaal", "Duplicaatcheck"]
        verplichte_velden, regeltelling, duplicaatcheck = rapport.resultaten
        assert verplichte_velden.ok  # lokale check, draait gewoon door zonder RLZ
        assert regeltelling.ok  # lokale check, draait gewoon door zonder RLZ
        assert not duplicaatcheck.ok
        assert "kon niet uitgevoerd worden" in duplicaatcheck.melding
        assert rapport.geblokkeerd
