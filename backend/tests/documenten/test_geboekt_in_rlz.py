"""Blok C 02-09 — 'Geboekt in RLZ · boekstuk <nr> · <tegenpartij>' + vindplaats-hint (Elissen-casus): één
bron uit de boek-events/kolommen voor lijst én detail, geen RLZ-call; verkoop-/omzetdocumenten dragen de
hint 'niet in Verkopen → Facturen'."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import boeken, service
from app.documenten.geboekt_in_rlz import VINDPLAATS_OMZET, VINDPLAATS_VERKOOP, bepaal_geboekt_in_rlz
from app.documenten.models import Document, DocumentSoort
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_boeken import boeken_aan, klaar_document  # noqa: F401 — fixtures

client = TestClient(app)


def _vendor_in_cache(admin_engine: Engine, administratie_id: uuid.UUID, vendor_id: uuid.UUID, naam: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :adm, :naam, '{}'::jsonb) ON CONFLICT DO NOTHING"
            ),
            {"id": vendor_id, "adm": administratie_id, "naam": naam},
        )


def _zet_geboekt(admin_engine: Engine, document_id: uuid.UUID, actor_id: uuid.UUID, detail: str) -> None:
    """Synthetische GEBOEKT-stand (verkoop-/omzetmotor niet doorlopen): status + tijdlijnrij zoals de motoren
    'm schrijven — de bron waar `bepaal_geboekt_in_rlz` uit leest."""
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": document_id})
        conn.execute(
            text(
                "INSERT INTO boekhouding.document_gebeurtenis "
                "(id, document_id, van_status, naar_status, actor_id, detail) VALUES (:id, :d, 'klaar_om_te_boeken', 'geboekt', :a, CAST(:detail AS jsonb))"
            ),
            {"id": uuid.uuid4(), "d": document_id, "a": actor_id, "detail": detail},
        )


class TestInkoop:
    def test_lijst_en_detail_dragen_boekstuk_en_crediteur(
        self,
        klaar_document: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,  # noqa: F811
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with admin_engine.connect() as conn:
            vendor_id = conn.execute(
                text("SELECT vendor_id FROM boekhouding.boekvoorstel WHERE document_id = :id"), {"id": klaar_document}
            ).scalar_one()
        _vendor_in_cache(admin_engine, administratie_id, vendor_id, "Universal Nederland B.V.")
        # Vóór het boeken: niets.
        assert all(i.geboekt_in_rlz is None for i in service.lijst_documenten(administratie_id=administratie_id))

        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )

        item = next(
            i for i in service.lijst_documenten(administratie_id=administratie_id) if i.document.id == klaar_document
        )
        assert item.geboekt_in_rlz is not None
        assert item.geboekt_in_rlz.boekstuknummer == "RLZ-TEST-00001"
        assert item.geboekt_in_rlz.tegenpartij == "Universal Nederland B.V."
        assert item.geboekt_in_rlz.tegenpartij_rol == "crediteur"
        assert item.geboekt_in_rlz.rlz_document_id == str(resultaat.rlz_document_id)
        assert item.geboekt_in_rlz.vindplaats_hint is None  # inkoop staat gewoon onder Inkoop → Facturen
        assert item.geboekt_in_rlz.als_regel() == "Geboekt in RLZ · boekstuk RLZ-TEST-00001 · Universal Nederland B.V."

        detail = service.haal_document_op(administratie_id=administratie_id, document_id=klaar_document)
        assert detail.geboekt_in_rlz == item.geboekt_in_rlz

        # Via de API: kant-en-klare regel op lijst én detail.
        headers = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        lijst = client.get(f"/administraties/{administratie_id}/documenten", headers=headers)
        assert lijst.status_code == 200
        rij = next(d for d in lijst.json()["documenten"] if d["id"] == str(klaar_document))
        assert rij["geboekt_in_rlz"]["regel"].startswith("Geboekt in RLZ · boekstuk RLZ-TEST-00001")
        detail_resp = client.get(f"/administraties/{administratie_id}/documenten/{klaar_document}", headers=headers)
        assert detail_resp.status_code == 200
        assert detail_resp.json()["geboekt_in_rlz"]["tegenpartij"] == "Universal Nederland B.V."


class TestVerkoopEnOmzet:
    def test_verkoopfactuur_draagt_debiteur_en_vindplaats_hint(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, opslag
    ) -> None:
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="vastly-380.xml",
            inhoud=b"<Invoice/>",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.VERKOOPFACTUUR,
        )
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.verkoop_voorstel (document_id, debiteur_naam, factuurnummer) "
                    "VALUES (:d, 'J.G.M. Elissen Holding BV', 'VF-2026-0102')"
                ),
                {"d": r.document_id},
            )
        _zet_geboekt(
            admin_engine,
            r.document_id,
            gescoopte_gebruiker,
            '{"rlz_document_id": "11111111-1111-1111-1111-111111111111", "rlz_boekstuknummer": "RLZ-01-00000442", '
            '"soort": "verkoopfactuur", "reden": "geboekt in RLZ — boekstuk RLZ-01-00000442"}',
        )
        with scoped_session(administratie_id) as session:
            stand = bepaal_geboekt_in_rlz(session, [session.get(Document, r.document_id)])[r.document_id]
        assert stand.boekstuknummer == "RLZ-01-00000442"
        assert stand.tegenpartij == "J.G.M. Elissen Holding BV" and stand.tegenpartij_rol == "debiteur"
        assert stand.vindplaats_hint == VINDPLAATS_VERKOOP
        assert "níét in Verkopen → Facturen" in stand.vindplaats_hint
        assert stand.als_regel() == "Geboekt in RLZ · boekstuk RLZ-01-00000442 · J.G.M. Elissen Holding BV"

    def test_kassarapport_draagt_verkoop_en_memoriaalboekstuk_zonder_tegenpartij(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, opslag
    ) -> None:
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="kassarapport.pdf",
            inhoud=b"%PDF-1.4 kas",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.KASSARAPPORT,
        )
        _zet_geboekt(
            admin_engine,
            r.document_id,
            gescoopte_gebruiker,
            '{"verkoop_rlz_id": "22222222-2222-2222-2222-222222222222", "verkoop_boekstuknummer": "RLZ-01-00000393", '
            '"memoriaal_boekstuknummer": "RLZ-06-00000502", '
            '"reden": "geboekt in RLZ — verkoopboekstuk RLZ-01-00000393"}',
        )
        with scoped_session(administratie_id) as session:
            stand = bepaal_geboekt_in_rlz(session, [session.get(Document, r.document_id)])[r.document_id]
        assert stand.boekstuknummer == "RLZ-01-00000393" and stand.memoriaal_boekstuknummer == "RLZ-06-00000502"
        assert stand.tegenpartij is None and stand.vindplaats_hint == VINDPLAATS_OMZET
        assert stand.als_regel() == "Geboekt in RLZ · boekstuk RLZ-01-00000393 · memoriaal RLZ-06-00000502"

    def test_niet_geboekt_document_heeft_geen_stand(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag
    ) -> None:
        r = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="open.pdf",
            inhoud=b"%PDF-1.4 open",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with scoped_session(administratie_id) as session:
            assert bepaal_geboekt_in_rlz(session, [session.get(Document, r.document_id)]) == {}
