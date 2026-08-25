"""Verzamelbak-acties (toewijzen mét leren, hoort-niet-bij-ons met verplichte reden) en de
splitsing-ter-controle-flow (bevestigen splitst deterministisch, afwijzen laat het origineel
als één geheel in de bak)."""

from __future__ import annotations

import uuid

import pytest
from pypdf import PdfReader
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.intake import splitsing as splitsing_service
from app.intake import verwerking, verzamelbak
from app.intake.splitsing import SplitsDeelInput
from tests.intake.conftest import bouw_eml, bouw_pdf, bouw_ubl


@pytest.fixture
def verzamelbak_document(gescoopte_gebruiker: uuid.UUID) -> uuid.UUID:
    eml = bouw_eml(bijlagen=[("factuur.xml", bouw_ubl(klant="Onbekend BV"), "application", "xml")])
    resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
    assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
    return resultaat.bijlagen[0].document_id


class TestVerzamelbak:
    def test_lijst_toont_open_items_met_herkomst(
        self, verzamelbak_document: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        items = verzamelbak.lijst_verzamelbak()
        assert [i.document_id for i in items] == [verzamelbak_document]
        assert items[0].tenaamstelling == "Onbekend BV"
        assert items[0].afzender_hint == "administratie@bouwmaat.nl"

    def test_bestand_leesroute_alleen_voor_echte_verzamelbak_documenten(
        self,
        verzamelbak_document: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        """D1 (besluit 25-08): de preview-popup leest het bestand administratie-loos — maar
        uitsluitend zolang het document nog in de verzamelbak staat (fail-closed)."""
        from app.documenten.service import DocumentNietGevonden

        inhoud, bestandsnaam, content_type = verzamelbak.haal_bijlage_op(document_id=verzamelbak_document)
        assert bestandsnaam == "factuur.xml"
        assert content_type == "application/xml"
        assert b"Onbekend BV" in inhoud
        verzamelbak.wijs_toe(
            document_id=verzamelbak_document, administratie_id=administratie_heet_blow, actor_id=gescoopte_gebruiker
        )
        with pytest.raises(DocumentNietGevonden):
            verzamelbak.haal_bijlage_op(document_id=verzamelbak_document)
        with pytest.raises(DocumentNietGevonden):
            verzamelbak.haal_bijlage_op(document_id=uuid.uuid4())

    def test_toewijzen_leert_en_start_extractie(
        self,
        verzamelbak_document: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        eind_status = verzamelbak.wijs_toe(
            document_id=verzamelbak_document,
            administratie_id=administratie_heet_blow,
            actor_id=gescoopte_gebruiker,
        )
        # UBL is deterministisch: na toewijzing meteen door de extractie → te_controleren.
        assert eind_status.value == "te_controleren"
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT administratie_id, status FROM boekhouding.document WHERE id = :id"),
                {"id": verzamelbak_document},
            ).one()
            regels = conn.execute(
                text("SELECT soort, sleutel, administratie_id FROM boekhouding.toewijzing_regel WHERE actief")
            ).all()
        assert rij.administratie_id == administratie_heet_blow
        # Geleerd: tenaamstelling én afzender wijzen voortaan automatisch toe.
        assert {(r.soort, r.administratie_id) for r in regels} == {
            ("tenaamstelling", administratie_heet_blow),
            ("afzender", administratie_heet_blow),
        }
        # En de vólgende mail met deze tenaamstelling gaat automatisch goed.
        with scoped_session(None) as session:
            from app.intake.toewijzing import bepaal_toewijzing

            besluit = bepaal_toewijzing(session, tenaamstelling="Onbekend BV", afzender=None)
        assert besluit.administratie_id == administratie_heet_blow

    def test_hoort_niet_bij_ons_vereist_reden_en_blijft_terugvindbaar(
        self, verzamelbak_document: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        with pytest.raises(verzamelbak.RedenVerplicht):
            verzamelbak.hoort_niet_bij_ons(
                document_id=verzamelbak_document, actor_id=gescoopte_gebruiker, reden="  "
            )
        eind_status = verzamelbak.hoort_niet_bij_ons(
            document_id=verzamelbak_document, actor_id=gescoopte_gebruiker, reden="Factuur van een ander kantoor"
        )
        assert eind_status.value == "afgewezen"
        # Het toewijzings-geheugen leert hier bewust niets.
        with admin_engine.connect() as conn:
            aantal = conn.execute(text("SELECT count(*) FROM boekhouding.toewijzing_regel")).scalar_one()
        assert aantal == 0

    def test_acties_alleen_op_verzamelbak_documenten(
        self,
        verzamelbak_document: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        verzamelbak.wijs_toe(
            document_id=verzamelbak_document,
            administratie_id=administratie_heet_blow,
            actor_id=gescoopte_gebruiker,
        )
        # Na toewijzing is het document administratie-gebonden: vanuit de platform-brede
        # verzamelbak-sessie is het onzichtbaar (RLS) — beide foutvormen betekenen hetzelfde:
        # dit document staat niet meer in de bak.
        from app.documenten.service import DocumentNietGevonden

        with pytest.raises((verzamelbak.DocumentNietInVerzamelbak, DocumentNietGevonden)):
            verzamelbak.hoort_niet_bij_ons(
                document_id=verzamelbak_document, actor_id=gescoopte_gebruiker, reden="x"
            )


@pytest.fixture
def splitsingsvoorstel(
    administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, intake_ai_aan: None, monkeypatch
) -> tuple[uuid.UUID, uuid.UUID]:
    """(bron_document_id, splitsing_id) — een 3-pagina-PDF met twee herkende facturen."""
    from app.config import settings
    from app.extractie.splitsing import FactuurSegment

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        verwerking.splitsing_extractie,
        "detecteer_facturen",
        lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
            FactuurSegment(1, 2, "BLOW B.V.", "Bouwmaat", "F-1", 0.95),
            FactuurSegment(3, 3, "Onbekend BV", "Sligro", "F-2", 0.9),
        ],
    )
    eml = bouw_eml(bijlagen=[("batchscan.pdf", bouw_pdf(3), "application", "pdf")])
    resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
    bron_id = resultaat.bijlagen[0].document_id
    items = verzamelbak.lijst_verzamelbak()
    return bron_id, next(i.splitsing_id for i in items if i.document_id == bron_id)


class TestSplitsing:
    def test_bevestigen_splitst_en_routeert_elk_deel(
        self,
        splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID],
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        opslag,
    ) -> None:
        bron_id, splitsing_id = splitsingsvoorstel
        resultaten = splitsing_service.bevestig_splitsing(
            splitsing_id=splitsing_id,
            actor_id=gescoopte_gebruiker,
            delen=[
                SplitsDeelInput(start_pagina=1, eind_pagina=2, tenaamstelling="BLOW B.V."),
                SplitsDeelInput(start_pagina=3, eind_pagina=3, tenaamstelling="Onbekend BV"),
            ],
        )
        assert [r.uitkomst for r in resultaten] == ["toegewezen", "verzamelbak"]
        with admin_engine.connect() as conn:
            bron_status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": bron_id}
            ).scalar_one()
            kinderen = conn.execute(
                text(
                    "SELECT bestandsnaam, opslag_pad, administratie_id FROM boekhouding.document "
                    "WHERE gesplitst_uit_id = :id ORDER BY bestandsnaam"
                ),
                {"id": bron_id},
            ).all()
        assert bron_status == "gesplitst"  # origineel blijft bestaan en terugvindbaar
        assert len(kinderen) == 2
        assert kinderen[0].administratie_id == administratie_heet_blow
        # Deterministische pagina-verdeling: deel 1 heeft 2 pagina's, deel 2 heeft er 1.
        deel1 = opslag.lezen(pad=kinderen[0].opslag_pad)
        deel2 = opslag.lezen(pad=kinderen[1].opslag_pad)
        assert len(PdfReader(__import__("io").BytesIO(deel1)).pages) == 2
        assert len(PdfReader(__import__("io").BytesIO(deel2)).pages) == 1

    def test_ongeldige_bereiken_geweigerd(
        self, splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID], gescoopte_gebruiker: uuid.UUID
    ) -> None:
        _, splitsing_id = splitsingsvoorstel
        with pytest.raises(splitsing_service.OngeldigeSplitsing):
            splitsing_service.bevestig_splitsing(
                splitsing_id=splitsing_id,
                actor_id=gescoopte_gebruiker,
                delen=[
                    SplitsDeelInput(start_pagina=1, eind_pagina=4, tenaamstelling=None),
                    SplitsDeelInput(start_pagina=2, eind_pagina=3, tenaamstelling=None),
                ],
            )

    def test_afwijzen_laat_origineel_als_geheel_in_de_bak(
        self, splitsingsvoorstel: tuple[uuid.UUID, uuid.UUID], gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        bron_id, splitsing_id = splitsingsvoorstel
        splitsing_service.wijs_splitsing_af(
            splitsing_id=splitsing_id, actor_id=gescoopte_gebruiker, reden="Is één factuur"
        )
        with admin_engine.connect() as conn:
            bron_status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": bron_id}
            ).scalar_one()
        assert bron_status == "niet_toegewezen"
        with pytest.raises(splitsing_service.SplitsingNietOpen):
            splitsing_service.wijs_splitsing_af(splitsing_id=splitsing_id, actor_id=gescoopte_gebruiker)
