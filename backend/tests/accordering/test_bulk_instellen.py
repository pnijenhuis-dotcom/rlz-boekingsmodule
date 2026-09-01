"""Bulk klant-accordering instellen (mockup bulk-accordering.html, besluiten Peter 01-09):
(1) ontbrekende accordeur-scope aanmaken mét expliciete vink (geauditeerd via de DB-trigger),
zonder vink = BV overgeslagen mét reden; (2) bestaande config wordt vervangen mét vooraf de
telling van de lopende rondes die via het BESTAANDE vervallen-patroon (punt 2a) vervallen;
(3) de bulk zet de klant-accordering-toggle aan waar die uit staat. Server-side is de bulk een
orkestratie over instellingen_opslaan — geen tweede configuratie-schrijver."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.accordering import service
from app.accordering.models import AccorderingStatus
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import document_status, maak_accordeur, zet_schema

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> service.LaagInput:
    return service.LaagInput(
        volgnummer=volgnummer,
        accordeur_gebruiker_id=accordeur,
        bedrag_drempel=Decimal(drempel) if drempel else None,
    )


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    """Tweede BV zónder accorderingsconfiguratie en zónder scope voor de accordeurs — het
    'Molenhof Beheer'-geval uit de mockup (scope ontbreekt, toggle uit)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Bulk Twee B.V.', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _heeft_scope(admin_engine: Engine, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID) -> bool:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT count(*) FROM platform.gebruiker_administratie "
                    "WHERE gebruiker_id = :g AND administratie_id = :a"
                ),
                {"g": gebruiker_id, "a": administratie_id},
            ).scalar_one()
            > 0
        )


class TestPreview:
    def test_preview_benoemt_scope_vervangen_en_telling_zonder_iets_te_wijzigen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        tweede_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        # Admin 1 heeft al een config mét lopende ronde (het ARVUM-geval).
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )

        uitkomsten, scope_ontbreekt = service.bulk_instellen_preview(
            administratie_ids=[administratie_id, tweede_administratie],
            lagen=[_laag(1, accordeur_2, "2500")],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        per_id = {u.administratie_id: u for u in uitkomsten}
        assert per_id[administratie_id].uitkomst == "vervangen"
        assert per_id[administratie_id].rondes_vervallen == 1
        assert per_id[administratie_id].toggle_aangezet is False
        assert per_id[tweede_administratie].uitkomst == "ingesteld"
        assert per_id[tweede_administratie].toggle_aangezet is True
        assert per_id[tweede_administratie].scope_toegevoegd_voor == ["R. Jansen"]
        # Vooraf-melding per accordeur mét de BV-namen (mockup-tekst).
        assert len(scope_ontbreekt) == 1
        assert scope_ontbreekt[0].accordeur_naam == "R. Jansen"
        assert scope_ontbreekt[0].administratie_namen == ["Bulk Twee B.V."]

        # Preview leest alleen: ronde nog open, geen scope-rij, config ongewijzigd.
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert not _heeft_scope(admin_engine, accordeur_2, tweede_administratie)

    def test_zonder_vink_wordt_de_bv_met_ontbrekende_scope_overgeslagen_met_reden(
        self,
        administratie_id: uuid.UUID,
        tweede_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        uitkomsten, _ = service.bulk_instellen_preview(
            administratie_ids=[tweede_administratie],
            lagen=[_laag(1, accordeur_1)],
            scope_toevoegen=False,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert uitkomsten[0].uitkomst == "overgeslagen"
        assert "scope ontbreekt voor S. Bakker" in (uitkomsten[0].reden or "")

    def test_identiek_schema_telt_geen_vervallen_rondes(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        uitkomsten, _ = service.bulk_instellen_preview(
            administratie_ids=[administratie_id],
            lagen=[_laag(1, accordeur_1)],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert uitkomsten[0].uitkomst == "vervangen"
        assert uitkomsten[0].rondes_vervallen == 0

    def test_niet_accordeur_in_de_lagen_is_geweigerd(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
    ) -> None:
        with pytest.raises(service.OngeldigeAanbieding, match="geen klant-accordeur"):
            service.bulk_instellen_preview(
                administratie_ids=[administratie_id],
                lagen=[_laag(1, gescoopte_gebruiker)],
                scope_toevoegen=True,
                actor_id=beheerder_id,
                actor_rol="beheerder",
            )


class TestToepassen:
    def test_toepassen_maakt_scope_vervangt_config_en_laat_rondes_vervallen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        tweede_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )

        uitkomsten = service.bulk_instellen(
            administratie_ids=[administratie_id, tweede_administratie],
            lagen=[_laag(1, accordeur_2, "2500")],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        per_id = {u.administratie_id: u for u in uitkomsten}
        assert per_id[administratie_id].uitkomst == "vervangen"
        assert per_id[administratie_id].rondes_vervallen == 1
        assert per_id[tweede_administratie].uitkomst == "ingesteld"
        assert per_id[tweede_administratie].toggle_aangezet is True

        # Scope-rij aangemaakt (besluit 1) — de aanmaak audit via de DB-trigger.
        assert _heeft_scope(admin_engine, accordeur_2, tweede_administratie)
        with admin_engine.connect() as conn:
            trigger_audits = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'gebruiker_administratie' AND record_id = :g"
                ),
                {"g": accordeur_2},
            ).scalar_one()
        assert trigger_audits >= 1

        # Vervallen via het BESTAANDE patroon (punt 2a): status vervallen, document terug,
        # banner-batch zichtbaar.
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        with admin_engine.connect() as conn:
            statussen = [
                r.status
                for r in conn.execute(
                    text("SELECT status FROM boekhouding.document_accordering WHERE document_id = :id"),
                    {"id": klaar_document},
                )
            ]
        assert statussen == [AccorderingStatus.VERVALLEN.value]
        assert service.vervallen_meldingen(administratie_id=administratie_id)[0].aantal == 1

        # Beide BV's dragen nu de nieuwe config + toggle aan (besluit 3).
        for aid in (administratie_id, tweede_administratie):
            ingeschakeld, lagen, _ = service.instellingen_ophalen(administratie_id=aid)
            assert ingeschakeld is True
            assert [(la.volgnummer, la.accordeur_gebruiker_id) for la in lagen] == [(1, accordeur_2)]

    def test_toepassen_zonder_vink_slaat_bv_over_en_raakt_de_rest_niet(
        self,
        administratie_id: uuid.UUID,
        tweede_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        uitkomsten = service.bulk_instellen(
            administratie_ids=[administratie_id, tweede_administratie],
            lagen=[_laag(1, accordeur_1)],
            scope_toevoegen=False,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        per_id = {u.administratie_id: u for u in uitkomsten}
        # accordeur_1 heeft al scope op administratie_id (conftest) — die BV is gewoon ingesteld.
        assert per_id[administratie_id].uitkomst == "ingesteld"
        assert per_id[tweede_administratie].uitkomst == "overgeslagen"
        assert "scope ontbreekt" in (per_id[tweede_administratie].reden or "")
        assert not _heeft_scope(admin_engine, accordeur_1, tweede_administratie)
        ingeschakeld, _, _ = service.instellingen_ophalen(administratie_id=tweede_administratie)
        assert ingeschakeld is False

    def test_gearchiveerde_administratie_wordt_overgeslagen(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        aid = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.administratie (id, naam, rlz_admin_id, actief) "
                    "VALUES (:id, 'Archief B.V.', :rlz, false)"
                ),
                {"id": aid, "rlz": f"rlz-{aid}"},
            )
        uitkomsten = service.bulk_instellen(
            administratie_ids=[aid],
            lagen=[_laag(1, accordeur_1)],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert uitkomsten[0].uitkomst == "overgeslagen"
        assert uitkomsten[0].reden == "administratie is gearchiveerd"


class TestEndpoints:
    def test_endpoints_zijn_beheerder_only(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        body = {
            "administratie_ids": [str(administratie_id)],
            "lagen": [{"volgnummer": 1, "accordeur_gebruiker_id": str(accordeur_1)}],
            "scope_toevoegen": True,
        }
        for pad in ("/accordering/bulk-instellen/preview", "/accordering/bulk-instellen"):
            respons = client.post(pad, json=body, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
            assert respons.status_code == 403, pad
        respons = client.get(
            "/accordering/accordeur-kandidaten", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert respons.status_code == 403

    def test_preview_en_toepassen_via_de_api(
        self,
        administratie_id: uuid.UUID,
        tweede_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        body = {
            "administratie_ids": [str(tweede_administratie)],
            "lagen": [{"volgnummer": 1, "accordeur_gebruiker_id": str(accordeur_1), "bedrag_drempel": "2500"}],
            "scope_toevoegen": True,
        }
        headers = _bearer(beheerder_id, rol="beheerder")
        preview = client.post("/accordering/bulk-instellen/preview", json=body, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["uitkomsten"][0]["uitkomst"] == "ingesteld"
        assert preview.json()["scope_ontbreekt"][0]["accordeur_naam"] == "S. Bakker"

        toepassen = client.post("/accordering/bulk-instellen", json=body, headers=headers)
        assert toepassen.status_code == 200
        assert toepassen.json()["uitkomsten"][0]["uitkomst"] == "ingesteld"
        assert toepassen.json()["uitkomsten"][0]["toggle_aangezet"] is True
        assert _heeft_scope(admin_engine, accordeur_1, tweede_administratie)

    def test_accordeur_kandidaten_lijst_is_platform_breed_en_alleen_actief(
        self,
        administratie_id: uuid.UUID,
        tweede_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        # Een accordeur die alleen scope op de tweede BV heeft, én een geblokkeerde.
        maak_accordeur(admin_engine, beheerder_id, tweede_administratie, "T. Overzee")
        geblokkeerd = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'G. Blok', :mail, 'klant_accordeur', 'geblokkeerd')"
                ),
                {"id": geblokkeerd, "mail": f"{geblokkeerd}@test.local"},
            )
        respons = client.get("/accordering/accordeur-kandidaten", headers=_bearer(beheerder_id, rol="beheerder"))
        assert respons.status_code == 200
        namen = [k["naam"] for k in respons.json()["kandidaten"]]
        assert "S. Bakker" in namen
        assert "T. Overzee" in namen
        assert "G. Blok" not in namen
