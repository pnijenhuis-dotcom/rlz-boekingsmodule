"""Omzetvoorstel-servicelaag: prefill uit veldvoorstel + mapping, opslaan mét mapping-leren,
checks-orkestratie (fail-closed RLZ-duplicaatcheck) en de bevriezingsregels."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.omzet import voorstel as voorstel_service
from app.omzet.mapping import onthoud_mapping
from app.omzet.models import OmzetBoeking, OmzetBoekingStatus
from app.omzet.voorstel import memoriaal_referentie
from tests.omzet.conftest import FakeOmzetClient, sla_compleet_voorstel_op


class TestPrefill:
    def test_prefill_uit_veldvoorstel_met_mapping_toegepast(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        omzet_gb, btw = uuid.uuid4(), uuid.uuid4()
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            onthoud_mapping(
                session,
                administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                categorie="Weed",  # sleutel 'weed' — moet ook "1. Weed" uit het rapport matchen
                omzet_ledger_id=omzet_gb,
                taxrate_id=btw,
                kostprijs_ledger_id=None,
            )

        data = voorstel_service.haal_omzet_voorstel_op(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert data.periode_start == date(2025, 9, 15)
        assert data.periode_eind == date(2025, 9, 21)
        assert data.rapport_totaal_omzet == Decimal("22463.36")
        assert data.marge_pct == Decimal("160.3")
        assert not data.opgeslagen

        weed = next(r for r in data.regels if r.categorie == "1. Weed")
        assert weed.omzet_ledger_id == omzet_gb
        assert weed.herkomst == "mapping"
        hash_regel = next(r for r in data.regels if r.categorie == "2. Hash")
        assert hash_regel.omzet_ledger_id is None
        assert hash_regel.herkomst == "nieuw"

    def test_geen_kassarapport_geeft_domeinfout(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag
    ) -> None:
        from app.documenten import service as documenten_service

        gewoon = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 f",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(voorstel_service.GeenKassarapport):
            voorstel_service.haal_omzet_voorstel_op(
                administratie_id=administratie_id, document_id=gewoon.document_id
            )


class TestOpslaan:
    def test_opslaan_leert_mapping_en_voorraadinstelling(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        omzet_gb, btw, kostprijs_gb, voorraad_gb = (uuid.uuid4() for _ in range(4))
        data = sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=omzet_gb,
            taxrate_id=btw,
            kostprijs_ledger_id=kostprijs_gb,
            voorraad_ledger_id=voorraad_gb,
        )
        assert data.opgeslagen
        assert data.voorraad_ledger_id == voorraad_gb
        assert all(r.omzet_ledger_id == omzet_gb for r in data.regels)

        # De mapping is geleerd: een vólgend rapport prefillt dezelfde categorieën als 'mapping'.
        from app.omzet.mapping import lijst_mappings

        sleutels = {m.categorie_sleutel for m in lijst_mappings(administratie_id=administratie_id)}
        assert sleutels == {"weed", "hash", "joints", "edibles", "weed prepacked"}

    def test_mapping_onthouden_uit_laat_mapping_ongemoeid(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        voorstel_service.sla_omzet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            rapport_totaal_omzet=Decimal("100"),
            rapport_totaal_kostprijs=None,
            regels=[
                voorstel_service.OmzetRegelInput(
                    categorie="Weed",
                    omzet_bedrag=Decimal("100"),
                    kostprijs_bedrag=None,
                    omzet_ledger_id=uuid.uuid4(),
                    taxrate_id=uuid.uuid4(),
                    kostprijs_ledger_id=None,
                )
            ],
            voorraad_ledger_id=None,
            mapping_onthouden=False,
        )
        from app.omzet.mapping import lijst_mappings

        assert lijst_mappings(administratie_id=administratie_id) == []


class TestChecksOrkestratie:
    def test_volledig_voorstel_passeert_alle_checks(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=uuid.uuid4(),
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=FakeOmzetClient()
        )
        assert not rapport.geblokkeerd, [r.melding for r in rapport.resultaten if not r.ok]

    def test_rlz_duplicaat_hit_blokkeert(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=uuid.uuid4(),
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        client = FakeOmzetClient(
            memoriaal_duplicaten=[
                {"id": str(uuid.uuid4()), "Reference": memoriaal_referentie(date(2025, 9, 15), date(2025, 9, 21))}
            ]
        )
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=client
        )
        duplicaat = next(r for r in rapport.resultaten if r.naam == "Duplicaat per periode")
        assert not duplicaat.ok

    def test_rlz_receipts_duplicaat_hit_blokkeert(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        """Receipts-verkenning: de verkoop-kant is op afstand te bevragen — een vreemde Receipt
        met onze periode-omschrijving blokkeert; onze eigen (retry-)boeking niet."""
        from app.documenten.rlz_ids import rlz_sales_invoice_id
        from app.omzet.voorstel import verkoop_omschrijving

        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=uuid.uuid4(),
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        omschrijving = verkoop_omschrijving(date(2025, 9, 15), date(2025, 9, 21))
        # Eigen GUID met dezelfde omschrijving (retry-scenario) telt NIET als duplicaat…
        eigen = FakeOmzetClient()
        eigen.sales_invoices[str(rlz_sales_invoice_id(kassarapport_document))] = {
            "id": str(rlz_sales_invoice_id(kassarapport_document)),
            "Description": omschrijving,
        }
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=eigen
        )
        duplicaat = next(r for r in rapport.resultaten if r.naam == "Duplicaat per periode")
        assert duplicaat.ok
        # …een vreemde Receipt met die omschrijving wél.
        vreemd = FakeOmzetClient(receipt_duplicaten=[{"id": str(uuid.uuid4()), "Description": omschrijving}])
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=vreemd
        )
        duplicaat = next(r for r in rapport.resultaten if r.naam == "Duplicaat per periode")
        assert not duplicaat.ok
        assert "verkoopboeking" in duplicaat.melding

    def test_rlz_fout_blokkeert_fail_closed_zonder_crash(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=uuid.uuid4(),
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            client=FakeOmzetClient(faal_op="duplicaatcheck"),
        )
        duplicaat = next(r for r in rapport.resultaten if r.naam == "Duplicaat per periode")
        assert not duplicaat.ok
        assert "kon niet uitgevoerd worden" in duplicaat.melding

    def test_lokale_periode_overlap_blokkeert(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=uuid.uuid4(),
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                OmzetBoeking(
                    administratie_id=administratie_id,
                    document_id=kassarapport_document if False else _ander_document(session, administratie_id),
                    periode_start=date(2025, 9, 18),
                    periode_eind=date(2025, 9, 24),
                    totaal_omzet=Decimal("1"),
                    totaal_kostprijs=Decimal("1"),
                    verkoop_rlz_id=uuid.uuid4(),
                    status=OmzetBoekingStatus.GEBOEKT.value,
                    geboekt_door=gescoopte_gebruiker,
                )
            )
        rapport = voorstel_service.voer_omzet_checks_uit(
            administratie_id=administratie_id, document_id=kassarapport_document, client=FakeOmzetClient()
        )
        duplicaat = next(r for r in rapport.resultaten if r.naam == "Duplicaat per periode")
        assert not duplicaat.ok
        assert "overlapt" in duplicaat.melding


def _ander_document(session, administratie_id: uuid.UUID) -> uuid.UUID:
    """Een tweede kassarapport-document als drager van de bestaande periode-boeking."""
    from app.documenten.models import Document, DocumentBron, DocumentSoort

    doc = Document(
        id=uuid.uuid4(),
        administratie_id=administratie_id,
        bron=DocumentBron.UPLOAD,
        soort=DocumentSoort.KASSARAPPORT.value,
        bestandsnaam="eerder-rapport.pdf",
        sha256_hash="x" * 64,
        opslag_pad="n.v.t.",
    )
    session.add(doc)
    session.flush()
    return doc.id
