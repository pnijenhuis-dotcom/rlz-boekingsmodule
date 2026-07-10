from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.models import Document, DocumentStatus
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

    def test_verwijderd_document_is_ook_bevroren(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-verwijderd.pdf",
            inhoud=b"%PDF-1.4 verwijderd",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

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

    def test_geboekt_document_blijft_byte_voor_byte_ongewijzigd_na_een_put_poging(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        """Niet alleen 'de aanroep faalt' — de opgeslagen kop/regels mogen ook echt niet
        aangeraakt zijn (kliktest: het boekvoorstel bleek nog bewerkbaar na boeken)."""
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-ongewijzigd.pdf",
            inhoud=b"%PDF-1.4 ongewijzigd",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        oorspronkelijke_vendor_id = uuid.uuid4()
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=oorspronkelijke_vendor_id,
            referentie="ORIGINEEL",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("60.50"),
            regels=[_regel(omschrijving="Origineel")],
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
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
                referentie="GEPOOGDE-WIJZIGING",
                factuurdatum=date(2026, 6, 1),
                totaalbedrag=Decimal("999.99"),
                regels=[_regel(omschrijving="Gepoogde wijziging")],
            )

        na_de_poging = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
        assert na_de_poging.vendor_id == oorspronkelijke_vendor_id
        assert na_de_poging.referentie == "ORIGINEEL"
        assert na_de_poging.totaalbedrag == Decimal("60.50")
        assert [r.omschrijving for r in na_de_poging.regels] == ["Origineel"]


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

    def test_geboekt_document_blokkeert_ook_de_checks_endpoint(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-checks-geboekt.pdf",
            inhoud=b"%PDF-1.4 checks-geboekt",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, resultaat.document_id)
            assert document is not None
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
            _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker)

        with pytest.raises(boekvoorstel.BoekvoorstelFout):
            boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=resultaat.document_id)

    def test_verwijderd_document_blokkeert_ook_de_checks_endpoint(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-checks-verwijderd.pdf",
            inhoud=b"%PDF-1.4 checks-verwijderd",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        with pytest.raises(boekvoorstel.BoekvoorstelFout):
            boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=resultaat.document_id)


class TestSamengevoegdeRegel:
    """Fix 3 (2026-07-10): de deterministisch berekende één-regel-variant. Pure functie op het
    veldvoorstel-dict — geld = code, dus elk rekenpad expliciet getest."""

    def test_gebruikt_gelezen_totalen_en_telt_regels_in_de_omschrijving(self) -> None:
        regel = boekvoorstel._samengevoegde_regel(
            {
                "factuurnummer": "F-2026-042",
                "totaal_excl": "100.00",
                "totaal_incl": "121.00",
                "btw_bedrag": "21.00",
                "regels": [
                    {"netto_bedrag": "60.00", "btw_bedrag": "12.60", "taxrate_id": None},
                    {"netto_bedrag": "40.00", "btw_bedrag": "8.40", "taxrate_id": None},
                ],
            }
        )
        assert regel is not None
        assert regel.netto_bedrag == Decimal("100.00")
        assert regel.btw_bedrag == Decimal("21.00")
        assert regel.omschrijving == "Factuur F-2026-042 — samengevoegd (2 regels)"
        assert regel.ledger_id is None  # boekingsgeheugen = latere sessie, geen GB-gok

    def test_btw_valt_terug_op_incl_min_excl(self) -> None:
        regel = boekvoorstel._samengevoegde_regel({"totaal_excl": "1526.20", "totaal_incl": "1846.70"})
        assert regel is not None
        assert regel.netto_bedrag == Decimal("1526.20")
        assert regel.btw_bedrag == Decimal("320.50")

    def test_vangnet_som_van_regels_alleen_bij_volledig_geparste_bedragen(self) -> None:
        compleet = boekvoorstel._samengevoegde_regel(
            {
                "regels": [
                    {"netto_bedrag": "60.00", "btw_bedrag": "12.60"},
                    {"netto_bedrag": "40.00", "btw_bedrag": "8.40"},
                ]
            }
        )
        assert compleet is not None
        assert compleet.netto_bedrag == Decimal("100.00")
        assert compleet.btw_bedrag == Decimal("21.00")

        # Eén onparseerbaar regelbedrag: nooit een gedeeltelijke som doorgeven.
        onvolledig = boekvoorstel._samengevoegde_regel({"regels": [{"netto_bedrag": "60.00"}, {"netto_bedrag": None}]})
        assert onvolledig is None

    def test_btw_code_alleen_bij_uniforme_suggestie_over_alle_regels(self) -> None:
        taxrate_id = uuid.uuid4()
        uniform = boekvoorstel._samengevoegde_regel(
            {
                "totaal_excl": "100.00",
                "totaal_incl": "121.00",
                "regels": [
                    {"netto_bedrag": "60.00", "taxrate_id": str(taxrate_id)},
                    {"netto_bedrag": "40.00", "taxrate_id": str(taxrate_id)},
                ],
            }
        )
        assert uniform is not None and uniform.taxrate_id == taxrate_id

        gemengd = boekvoorstel._samengevoegde_regel(
            {
                "totaal_excl": "100.00",
                "totaal_incl": "121.00",
                "regels": [
                    {"netto_bedrag": "60.00", "taxrate_id": str(taxrate_id)},
                    {"netto_bedrag": "40.00", "taxrate_id": str(uuid.uuid4())},
                ],
            }
        )
        assert gemengd is not None and gemengd.taxrate_id is None

    def test_zonder_bruikbare_totalen_geen_samengevoegde_regel(self) -> None:
        assert boekvoorstel._samengevoegde_regel({}) is None
        assert boekvoorstel._samengevoegde_regel({"totaal_excl": "geen bedrag"}) is None


class TestRegelsSamenvoegen:
    """Fix 3: standaard één samengevoegde boekingsregel, keuze per (administratie, crediteur)
    onthouden; projectplicht blijft hard per-regel."""

    def _upload_ubl(
        self, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str
    ) -> uuid.UUID:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam=naam,
            inhoud=_VOORBEELD_UBL + f"<!-- {naam} -->".encode(),
            actor_id=actor_id,
            opslag=opslag,
        )
        return resultaat.document_id

    def test_default_samengevoegd_met_berekende_een_regel_variant(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = self._upload_ubl(administratie_id, gescoopte_gebruiker, opslag, "default.xml")
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.regels_samenvoegen is True
        assert data.samenvoegen_toegestaan is True
        assert data.samengevoegde_regel is not None
        # De voorbeeld-UBL: excl 1526.20, incl 1846.70 (zie test_ubl.py).
        assert data.samengevoegde_regel.netto_bedrag == Decimal("1526.20")
        assert data.samengevoegde_regel.btw_bedrag == Decimal("320.50")

    def test_voorkeur_wordt_per_crediteur_onthouden_over_documenten_heen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        vendor_id = uuid.uuid4()
        doc1 = self._upload_ubl(administratie_id, gescoopte_gebruiker, opslag, "voorkeur-1.xml")
        doc2 = self._upload_ubl(administratie_id, gescoopte_gebruiker, opslag, "voorkeur-2.xml")

        # Controleur splitst bij document 1 → voorkeur voor deze crediteur wordt "gesplitst".
        na_splitsen = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=doc1,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
            regels_samenvoegen=False,
        )
        assert na_splitsen.regels_samenvoegen is False

        # Document 2, zelfde crediteur, keuze niet meegegeven (None) → de onthouden voorkeur telt.
        ander_document = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=doc2,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="F-2",
            factuurdatum=date(2026, 7, 2),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
        )
        assert ander_document.regels_samenvoegen is False

        # Terug naar samenvoegen bij document 1 → geldt ook weer voor document 2.
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=doc1,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
            regels_samenvoegen=True,
        )
        opnieuw = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc2)
        assert opnieuw.regels_samenvoegen is True

    def test_projectplicht_blokkeert_samenvoegen_hard(
        self,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
        document_id = self._upload_ubl(administratie_id, gescoopte_gebruiker, opslag, "projectplicht.xml")
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.samenvoegen_toegestaan is False
        assert data.regels_samenvoegen is False
        assert data.samengevoegde_regel is None

    def test_projectplicht_negeert_de_meegegeven_keuze_bij_opslaan(
        self,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        """Bij projectplicht wordt géén voorkeur-rij gezet — gaat de plicht later uit, dan geldt
        gewoon de default (samenvoegen aan), niet een stiekem opgeslagen keuze."""
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
        vendor_id = uuid.uuid4()
        document_id = self._upload_ubl(administratie_id, gescoopte_gebruiker, opslag, "plicht-keuze.xml")
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=vendor_id,
            referentie="F-1",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
            regels_samenvoegen=False,
        )
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=False)
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.regels_samenvoegen is True  # geen voorkeur-rij ontstaan tijdens de projectplicht

    def test_alleen_een_echte_voorkeurwijziging_krijgt_een_audit_event(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        document_id = self._upload_ubl(administratie_id, gescoopte_gebruiker, opslag, "audit.xml")

        def _sla_op(samenvoegen: bool) -> None:
            boekvoorstel.sla_boekvoorstel_op(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                vendor_id=vendor_id,
                referentie="F-1",
                factuurdatum=date(2026, 7, 1),
                totaalbedrag=Decimal("121.00"),
                regels=[_regel()],
                regels_samenvoegen=samenvoegen,
            )

        _sla_op(False)
        _sla_op(False)  # herhaalde opslaan-actie met dezelfde stand = geen handeling op de voorkeur
        _sla_op(True)

        with admin_engine.connect() as conn:
            events = conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'leverancier_voorkeur_samenvoegen_gewijzigd' AND record_id = :rid "
                    "ORDER BY tijdstip"
                ),
                {"rid": vendor_id},
            ).all()
        assert len(events) == 2
