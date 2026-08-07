"""Categorie-mapping (app/omzet/mapping.py) + de automatische mapping-vraag (autovraag.py)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.omzet import autovraag
from app.omzet.mapping import (
    actieve_mappings,
    lijst_mappings,
    normaliseer_categorie_sleutel,
    onthoud_mapping,
)
from tests.omzet.conftest import RAPPORT_VELDVOORSTEL, voeg_veldvoorstel_toe


class TestNormaliseerCategorieSleutel:
    def test_voorloopnummering_is_opmaak(self) -> None:
        assert normaliseer_categorie_sleutel("1. Weed") == "weed"
        assert normaliseer_categorie_sleutel("2) Hash") == "hash"
        assert normaliseer_categorie_sleutel("10 - Edibles") == "edibles"

    def test_case_en_leestekens_genormaliseerd(self) -> None:
        assert normaliseer_categorie_sleutel("Weed  Prepacked!") == "weed prepacked"

    def test_volgorde_blijft_betekenis(self) -> None:
        # Anders dan het boekingsgeheugen: geen token-set-sortering — "Prepacked Weed" is een
        # andere rapportcategorie dan "Weed Prepacked" als de klant ze zo voert.
        assert normaliseer_categorie_sleutel("Prepacked Weed") != normaliseer_categorie_sleutel("Weed Prepacked")

    def test_leeg_geeft_none(self) -> None:
        assert normaliseer_categorie_sleutel("") is None
        assert normaliseer_categorie_sleutel("12.") is None
        assert normaliseer_categorie_sleutel(None) is None


class TestOnthoudMapping:
    def test_nieuwe_mapping_wordt_vastgelegd(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        omzet_gb, btw, kostprijs_gb = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            onthoud_mapping(
                session,
                administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                categorie="1. Weed",
                omzet_ledger_id=omzet_gb,
                taxrate_id=btw,
                kostprijs_ledger_id=kostprijs_gb,
            )
        mappings = lijst_mappings(administratie_id=administratie_id)
        assert len(mappings) == 1
        assert mappings[0].categorie_sleutel == "weed"
        assert mappings[0].omzet_ledger_id == omzet_gb

    def test_ongewijzigd_herbevestigen_maakt_geen_nieuwe_rij(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        omzet_gb, btw = uuid.uuid4(), uuid.uuid4()
        for _ in range(2):
            with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
                onthoud_mapping(
                    session,
                    administratie_id=administratie_id,
                    actor_id=gescoopte_gebruiker,
                    categorie="Weed",
                    omzet_ledger_id=omzet_gb,
                    taxrate_id=btw,
                    kostprijs_ledger_id=None,
                )
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.omzet_categorie_mapping WHERE administratie_id = :a"),
                {"a": administratie_id},
            ).scalar_one()
        assert aantal == 1

    def test_wijziging_deactiveert_oude_rij_en_houdt_historie(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        btw = uuid.uuid4()
        eerste_gb, tweede_gb = uuid.uuid4(), uuid.uuid4()
        for gb in (eerste_gb, tweede_gb):
            with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
                onthoud_mapping(
                    session,
                    administratie_id=administratie_id,
                    actor_id=gescoopte_gebruiker,
                    categorie="Weed",
                    omzet_ledger_id=gb,
                    taxrate_id=btw,
                    kostprijs_ledger_id=None,
                )
        with scoped_session(administratie_id) as session:
            actief = actieve_mappings(session, administratie_id=administratie_id)
        assert actief["weed"].omzet_ledger_id == tweede_gb
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT actief, gedeactiveerd_op IS NOT NULL AS gedeactiveerd "
                    "FROM boekhouding.omzet_categorie_mapping WHERE administratie_id = :a ORDER BY aangemaakt_op"
                ),
                {"a": administratie_id},
            ).all()
        assert len(rijen) == 2
        assert rijen[0].actief is False and rijen[0].gedeactiveerd is True


class TestAutovraag:
    @pytest.fixture
    def eigenaar_ingesteld(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET eigenaar_gebruiker_id = :g WHERE id = :a"),
                {"g": gescoopte_gebruiker, "a": administratie_id},
            )

    def test_onbekende_categorieen_uit_veldvoorstel(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        onbekend = autovraag.onbekende_categorieen(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert onbekend == ["1. Weed", "2. Hash", "3. Joints", "4. Edibles", "Weed Prepacked"]

    def test_stelt_vraag_met_systeem_actor_en_categorieen(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        eigenaar_ingesteld: None,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        gesteld = autovraag.stel_mapping_vraag_indien_nodig(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        assert gesteld
        with admin_engine.connect() as conn:
            vraag = conn.execute(
                text(
                    "SELECT gesteld_door, toegewezen_aan, vraag_tekst FROM boekhouding.vraag "
                    "WHERE document_id = :d AND status = 'open'"
                ),
                {"d": kassarapport_document},
            ).one()
            doc_status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :d"), {"d": kassarapport_document}
            ).scalar_one()
        assert vraag.gesteld_door == SYSTEEM_ACTOR_ID
        assert vraag.toegewezen_aan == gescoopte_gebruiker
        assert "Weed Prepacked" in vraag.vraag_tekst
        assert doc_status == "vraag_open"

    def test_geen_tweede_vraag_bij_bestaande_open_vraag(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        eigenaar_ingesteld: None,
    ) -> None:
        assert autovraag.stel_mapping_vraag_indien_nodig(
            administratie_id=administratie_id, document_id=kassarapport_document
        )
        # Tweede aanroep: document staat op vraag_open — gelogde no-op, geen fout.
        assert not autovraag.stel_mapping_vraag_indien_nodig(
            administratie_id=administratie_id, document_id=kassarapport_document
        )

    def test_geen_eigenaar_is_no_op_zonder_fout(
        self, kassarapport_document: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        assert not autovraag.stel_mapping_vraag_indien_nodig(
            administratie_id=administratie_id, document_id=kassarapport_document
        )

    def test_geen_vraag_als_alles_gemapt(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        eigenaar_ingesteld: None,
        opslag,
    ) -> None:
        from app.documenten import service as documenten_service
        from app.documenten.models import DocumentSoort

        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="rapport.pdf",
            inhoud=b"%PDF-1.4 x",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            for categorie in ("1. Weed", "2. Hash", "3. Joints", "4. Edibles", "Weed Prepacked"):
                onthoud_mapping(
                    session,
                    administratie_id=administratie_id,
                    actor_id=gescoopte_gebruiker,
                    categorie=categorie,
                    omzet_ledger_id=uuid.uuid4(),
                    taxrate_id=uuid.uuid4(),
                    kostprijs_ledger_id=uuid.uuid4(),
                )
        voeg_veldvoorstel_toe(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            veldvoorstel=RAPPORT_VELDVOORSTEL,
        )
        assert not autovraag.stel_mapping_vraag_indien_nodig(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
