"""BUG 18-09 (Peter, live bij Bouwadvies Oost Nederland): "Administraties toevoegen…" bij een klant-accordeur liep over de
bulk-instelroute en verving de drie bestaande lagen door één laag mét die accordeur. Regel sinds 18-09: TOEGANG ≠ LAAG.

(1) Toegang geven = uitsluitend de bestaande scope-route `POST /auth/gebruikers/{id}/scope`: geen laag, geen
    `accordering_schema_gewijzigd`-audit, geen herberekening van lopende rondes — alleen de trigger-audit `scope_toegevoegd`.
(2) De bulk vervangt bestaande lagen alleen ná een expliciete bevestiging per administratie (`vervangen_bevestigd`);
    zonder = 'overgeslagen' mét reden en de lagen blijven staan.
(3) De preview draagt de huidige lagen als namen (`bestaande_lagen`) zodat de dialoog "vervangt 3 lagen: …" kan tonen.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.accordering import service
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import maak_accordeur, zet_schema

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _laag(volgnummer: int, accordeur: uuid.UUID) -> service.LaagInput:
    return service.LaagInput(volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)


def _accordeur_zonder_scope(admin_engine: Engine, naam: str) -> uuid.UUID:
    """Klant-accordeur van het kantoor zónder scope op de administratie — het Romy-geval."""
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, :naam, :mail, 'klant_accordeur', 'actief')"
            ),
            {"id": gid, "naam": naam, "mail": f"{gid}@test.local"},
        )
    return gid


def _audit_tellingen(admin_engine: Engine, administratie_id: uuid.UUID) -> dict[str, int]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT actie, count(*) AS n FROM platform.audit_event "
                "WHERE actie IN ('accordering_schema_gewijzigd', 'accordering_ronde_herberekend') "
                "AND (administratie_id = :a OR administratie_id IS NULL) GROUP BY actie"
            ),
            {"a": administratie_id},
        ).all()
    return {r.actie: int(r.n) for r in rijen}


def _lagen(administratie_id: uuid.UUID) -> list[tuple[int, uuid.UUID]]:
    _, lagen, _ = service.instellingen_ophalen(administratie_id=administratie_id)
    return [(la.volgnummer, la.accordeur_gebruiker_id) for la in lagen]


def _stappen(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[int, uuid.UUID, str | None]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT s.volgnummer, s.accordeur_gebruiker_id, s.besluit FROM boekhouding.accordering_stap s "
                "JOIN boekhouding.document_accordering a ON a.id = s.accordering_id "
                "WHERE a.document_id = :d ORDER BY s.volgnummer"
            ),
            {"d": document_id},
        ).all()
    return [(int(r.volgnummer), r.accordeur_gebruiker_id, r.besluit) for r in rijen]


class TestToegangIsGeenLaag:
    def test_scope_only_laat_drie_lagen_en_de_lopende_ronde_staan_en_schrijft_geen_schema_audit(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        # Bouwadvies-geval: drie lagen + een lopende ronde.
        accordeur_3 = maak_accordeur(admin_engine, beheerder_id, administratie_id, "Kempen Facilities")
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2), _laag(3, accordeur_3)],
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        lagen_voor = _lagen(administratie_id)
        stappen_voor = _stappen(admin_engine, klaar_document)
        audits_voor = _audit_tellingen(admin_engine, administratie_id)
        assert len(lagen_voor) == 3 and len(stappen_voor) == 3

        romy = _accordeur_zonder_scope(admin_engine, "Romy v. Lambalgen")
        respons = client.post(
            f"/auth/gebruikers/{romy}/scope",
            json={"administratie_id": str(administratie_id)},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert respons.status_code == 204

        # Toegang ≠ laag: lagen, lopende ronde en schema-audit ongewijzigd; alleen de scope-trigger-audit is erbij.
        assert _lagen(administratie_id) == lagen_voor
        assert _stappen(admin_engine, klaar_document) == stappen_voor
        assert _audit_tellingen(admin_engine, administratie_id) == audits_voor
        kandidaten = service.accordeur_kandidaten(administratie_id=administratie_id)
        assert romy in {k.id for k in kandidaten}
        with admin_engine.connect() as conn:
            scope_audits = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'gebruiker_administratie' AND actie = 'scope_toegevoegd' AND record_id = :g"
                ),
                {"g": romy},
            ).scalar_one()
        assert scope_audits == 1

    def test_bulk_vervangt_bestaande_lagen_alleen_na_expliciete_bevestiging_en_preview_toont_ze(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        lagen_voor = _lagen(administratie_id)
        romy = _accordeur_zonder_scope(admin_engine, "Romy v. Lambalgen")
        headers = _bearer(beheerder_id, rol="beheerder")
        body = {
            "administratie_ids": [str(administratie_id)],
            "lagen": [{"volgnummer": 1, "accordeur_gebruiker_id": str(romy), "bedrag_drempel": None}],
            "scope_toevoegen": True,
        }

        # (3) Preview: de huidige stand als namen, op volgnummer.
        preview = client.post("/accordering/bulk-instellen/preview", json=body, headers=headers)
        assert preview.status_code == 200
        uitkomst = preview.json()["uitkomsten"][0]
        assert uitkomst["uitkomst"] == "vervangen"
        assert uitkomst["bestaande_lagen"] == ["S. Bakker", "R. Jansen"]

        # (2a) Toepassen ZONDER bevestiging: overgeslagen mét reden, lagen én scope onaangeroerd.
        zonder = client.post("/accordering/bulk-instellen", json=body, headers=headers)
        assert zonder.status_code == 200
        assert zonder.json()["uitkomsten"][0]["uitkomst"] == "overgeslagen"
        assert zonder.json()["uitkomsten"][0]["reden"] == service.VERVANGEN_NIET_BEVESTIGD_REDEN
        assert zonder.json()["uitkomsten"][0]["bestaande_lagen"] == ["S. Bakker", "R. Jansen"]
        assert _lagen(administratie_id) == lagen_voor
        assert romy not in {k.id for k in service.accordeur_kandidaten(administratie_id=administratie_id)}

        # (2b) Mét bevestiging: het bestaande bulk-gedrag (vervangen + scope + audit).
        met = client.post(
            "/accordering/bulk-instellen",
            json={**body, "vervangen_bevestigd": [str(administratie_id)]},
            headers=headers,
        )
        assert met.status_code == 200
        assert met.json()["uitkomsten"][0]["uitkomst"] == "vervangen"
        assert _lagen(administratie_id) == [(1, romy)]
