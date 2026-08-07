"""Documentsoort-routing (migratie 0027): een kassarapport doorloopt dezelfde pipeline, maar
krijgt de rapport-extractie i.p.v. de factuurextractie — met dezelfde AVG-gate."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, text

from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.documenten.storage import LokaleBestandsopslag


class TestUploadKassarapport:
    def test_soort_wordt_vastgelegd_en_status_te_controleren(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="MargeRapport.pdf",
            inhoud=b"%PDF-1.4 rapport",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        )
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT soort, status FROM boekhouding.document WHERE id = :id"),
                {"id": resultaat.document_id},
            ).one()
        assert rij.soort == "kassarapport"
        assert rij.status == "te_controleren"

    def test_avg_gate_uit_slaat_rapport_extractie_zichtbaar_over(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="MargeRapport.pdf",
            inhoud=b"%PDF-1.4 rapport",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        )
        detail = documenten_service.haal_document_op(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
        overgeslagen = [
            g.detail["ai_extractie_overgeslagen"]
            for g in detail.gebeurtenissen
            if g.detail and "ai_extractie_overgeslagen" in g.detail
        ]
        assert overgeslagen == ["ai_extractie_uitgeschakeld"]
        assert detail.veldvoorstel is None

    def test_default_soort_blijft_inkoopfactuur(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 factuur",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with admin_engine.connect() as conn:
            soort = conn.execute(
                text("SELECT soort FROM boekhouding.document WHERE id = :id"), {"id": resultaat.document_id}
            ).scalar_one()
        assert soort == "inkoopfactuur"
