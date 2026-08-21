"""Veld-API (fase 2): HTTP-endpoints voor ZZP'er / uitvoerder / detacheerder — rol- en
voorwaarden-poorten, de mockup-flows (projecten → weken → dag → indienen; te keuren →
akkoord/afkeuren; meerwerk melden mét foto) en de scope-guards over de API-laag heen."""

from __future__ import annotations

import io
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.security.tokens import create_access_token
from app.uren import service as uren_service
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

VANDAAG = date.today()
JAAR, WEEK = VANDAAG.isocalendar()[0], VANDAAG.isocalendar()[1]
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _activeer(gebruiker_id: uuid.UUID) -> None:
    """Voorwaarden-akkoord vastleggen (de fail-closed poort van de veld-endpoints)."""
    voorwaarden.leg_akkoord_vast(gebruiker_id=gebruiker_id)


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    _activeer(zzper)
    return zzper


@pytest.fixture
def uitvoerder_met_scope(uitvoerder, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id
    )
    _activeer(uitvoerder)
    return uitvoerder


class TestPoorten:
    def test_kantoorrol_geweigerd(self, beheerder_id):
        resp = client.get("/uren/zzp/projecten", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 403

    def test_zonder_voorwaarden_akkoord_fail_closed(self, zzper, administratie_id, beheerder_id):
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id
        )
        resp = client.get("/uren/zzp/projecten", headers=_bearer(zzper, rol="zzper"))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "voorwaarden_akkoord_vereist"


class TestZzpFlow:
    def test_volledige_flow_projecten_dag_indienen_historie(
        self, zzper_met_scope, administratie_id, project_id, beheerder_id
    ):
        uren_service.koppel_project(
            administratie_id=administratie_id,
            gebruiker_id=zzper_met_scope,
            project_id=project_id,
            actor_id=beheerder_id,
        )
        headers = _bearer(zzper_met_scope, rol="zzper")

        # projectenlijst: verse koppeling ⇒ de huidige week staat open
        resp = client.get("/uren/zzp/projecten", headers=headers)
        assert resp.status_code == 200, resp.text
        (kaart,) = resp.json()
        assert kaart["project_naam"] == "26014 Eindhoven (BAM)"
        assert kaart["open_weken"] == 1

        # dag zetten
        resp = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
                "datum": MAANDAG.isoformat(),
                "uren": "8.0",
                "m2": "120",
                "opmerking": "steigerbouw gevel B",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        staat = resp.json()
        assert staat["status"] == "concept"
        assert staat["totaal_uren"] == "8.0"

        # wekenoverzicht toont de week met ingevulde dag
        resp = client.get(
            "/uren/zzp/weken",
            params={"administratie_id": str(administratie_id), "project_id": str(project_id)},
            headers=headers,
        )
        assert resp.status_code == 200
        week = next(w for w in resp.json() if w["weeknummer"] == WEEK and w["jaar"] == JAAR)
        assert week["dagen_ingevuld"] == 1
        assert week["status"] == "concept"

        # indienen → historie
        resp = client.post(
            "/uren/zzp/indienen",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ingediend"

        resp = client.get("/uren/zzp/ingediend", headers=headers)
        assert resp.status_code == 200
        (item,) = resp.json()
        assert item["status"] == "ingediend"
        assert item["ingediend_namens"] is False

        # projectenlijst: niets meer open
        resp = client.get("/uren/zzp/projecten", headers=headers)
        assert resp.json()[0]["open_weken"] == 0

    def test_dag_op_bevroren_week_geeft_409(self, zzper_met_scope, administratie_id, project_id, beheerder_id):
        uren_service.koppel_project(
            administratie_id=administratie_id,
            gebruiker_id=zzper_met_scope,
            project_id=project_id,
            actor_id=beheerder_id,
        )
        headers = _bearer(zzper_met_scope, rol="zzper")
        client.post(
            "/uren/zzp/indienen",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
            },
            headers=headers,
        )
        resp = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
                "datum": MAANDAG.isoformat(),
                "uren": "8.0",
            },
            headers=headers,
        )
        assert resp.status_code == 409


class TestDetacheerder:
    def test_namens_flow(self, admin_engine, zzper_met_scope, administratie_id, project_id, beheerder_id):
        uren_service.koppel_project(
            administratie_id=administratie_id,
            gebruiker_id=zzper_met_scope,
            project_id=project_id,
            actor_id=beheerder_id,
        )
        detacheerder = maak_gebruiker(admin_engine, "detacheerder", "Karin S.")
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=detacheerder, administratie_id=administratie_id
        )
        _activeer(detacheerder)
        uren_service.koppel_detacheerder(
            detacheerder_id=detacheerder, zzper_id=zzper_met_scope, actor_id=beheerder_id
        )
        headers = _bearer(detacheerder, rol="detacheerder")

        resp = client.get("/uren/detacheerder/zzpers", headers=headers)
        assert resp.status_code == 200, resp.text
        (kaart,) = resp.json()
        assert kaart["naam"] == "Milan K."
        assert kaart["aantal_projecten"] == 1

        # namens: projecten van de ZZP'er + dag zetten + indienen
        resp = client.get("/uren/zzp/projecten", params={"namens": str(zzper_met_scope)}, headers=headers)
        assert resp.status_code == 200 and len(resp.json()) == 1
        resp = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
                "datum": MAANDAG.isoformat(),
                "uren": "6",
                "namens_zzper_id": str(zzper_met_scope),
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["dagen"][0]["namens"] is True
        assert resp.json()["dagen"][0]["ingevuld_door_naam"] == "Karin S."

    def test_zonder_koppeling_403(self, admin_engine, zzper_met_scope, administratie_id, beheerder_id):
        detacheerder = maak_gebruiker(admin_engine, "detacheerder", "Vreemde D.")
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=detacheerder, administratie_id=administratie_id
        )
        _activeer(detacheerder)
        resp = client.get(
            "/uren/zzp/projecten",
            params={"namens": str(zzper_met_scope)},
            headers=_bearer(detacheerder, rol="detacheerder"),
        )
        assert resp.status_code == 403

    def test_detacheerder_ziet_geen_projectinhoud(
        self, admin_engine, administratie_id, project_id, beheerder_id
    ):
        """Besluit 21-08: geen specs/contract/meerwerk voor de detacheerder — het uitvoerder-
        projectdetail weigert de rol."""
        detacheerder = maak_gebruiker(admin_engine, "detacheerder", "Karin S.")
        _activeer(detacheerder)
        resp = client.get(
            f"/uren/uitvoerder/projecten/{administratie_id}/{project_id}",
            headers=_bearer(detacheerder, rol="detacheerder"),
        )
        assert resp.status_code == 403


class TestUitvoerder:
    def test_te_keuren_en_weekbesluiten(
        self, zzper_met_scope, uitvoerder_met_scope, administratie_id, project_id, beheerder_id
    ):
        for gebruiker in (zzper_met_scope, uitvoerder_met_scope):
            uren_service.koppel_project(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker,
                project_id=project_id,
                actor_id=beheerder_id,
            )
        zzp_headers = _bearer(zzper_met_scope, rol="zzper")
        client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
                "datum": MAANDAG.isoformat(),
                "uren": "8",
                "m2": "120",
            },
            headers=zzp_headers,
        )
        client.post(
            "/uren/zzp/indienen",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
            },
            headers=zzp_headers,
        )

        headers = _bearer(uitvoerder_met_scope, rol="uitvoerder")
        resp = client.get("/uren/uitvoerder/te-keuren", headers=headers)
        assert resp.status_code == 200, resp.text
        (item,) = resp.json()
        assert item["zzper_naam"] == "Milan K."
        weekstaat_id = item["weekstaat_id"]

        # detail is toegankelijk voor de keurder
        resp = client.get(f"/uren/weekstaten/{administratie_id}/{weekstaat_id}", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["dagen"]) == 1

        # afkeuren zonder reden → 422; met reden → corrigeren; daarna opnieuw in en akkoord
        resp = client.post(
            f"/uren/uitvoerder/weekstaten/{administratie_id}/{weekstaat_id}/afkeuren",
            json={"reden": "  "},
            headers=headers,
        )
        assert resp.status_code == 422
        resp = client.post(
            f"/uren/uitvoerder/weekstaten/{administratie_id}/{weekstaat_id}/afkeuren",
            json={"reden": "Wo max 8 uur afgesproken"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "corrigeren"
        client.post(
            "/uren/zzp/indienen",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "jaar": JAAR,
                "weeknummer": WEEK,
            },
            headers=zzp_headers,
        )
        resp = client.post(
            f"/uren/uitvoerder/weekstaten/{administratie_id}/{weekstaat_id}/akkoord", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "goedgekeurd"

        # projectenlijst toont de m²-voortgang uit de goedgekeurde staat
        resp = client.get("/uren/uitvoerder/projecten", headers=headers)
        (project_kaart,) = resp.json()
        assert project_kaart["gebouwd_m2"] == "120.00"
        assert project_kaart["te_keuren"] == 0

    def test_meerwerk_melden_met_foto_en_projectdetail(
        self, uitvoerder_met_scope, administratie_id, project_id, beheerder_id, tmp_path, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path))
        uren_service.koppel_project(
            administratie_id=administratie_id,
            gebruiker_id=uitvoerder_met_scope,
            project_id=project_id,
            actor_id=beheerder_id,
        )
        headers = _bearer(uitvoerder_met_scope, rol="uitvoerder")
        resp = client.post(
            "/uren/uitvoerder/meerwerk",
            data={
                "administratie_id": str(administratie_id),
                "project_id": str(project_id),
                "omschrijving": "Extra trapsteiger achterzijde",
                "aantal": "84",
                "eenheid": "m2",
                "datum_uitgevoerd": "2026-08-12",
                "in_opdracht_van": "J. Timmers (BAM)",
            },
            files={"foto": ("trapsteiger.jpg", io.BytesIO(b"\xff\xd8fake"), "image/jpeg")},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        melding = resp.json()
        assert melding["status"] == "gemeld"
        assert melding["heeft_foto"] is True

        resp = client.get(
            f"/uren/meerwerk/{administratie_id}/{melding['id']}/foto", headers=headers
        )
        assert resp.status_code == 200
        assert resp.content == b"\xff\xd8fake"

        resp = client.get(f"/uren/uitvoerder/projecten/{administratie_id}/{project_id}", headers=headers)
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["project_naam"] == "26014 Eindhoven (BAM)"
        assert len(detail["meerwerk"]) == 1
        assert detail["meerwerk"][0]["omschrijving"] == "Extra trapsteiger achterzijde"

    def test_projectdocument_alleen_met_toewijzing(
        self, admin_engine: Engine, uitvoerder_met_scope, administratie_id, project_id, beheerder_id,
        tmp_path, monkeypatch,
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path))
        from app.documenten.storage import standaard_opslag

        pad = f"projectdocumenten/{administratie_id}/contract.pdf"
        standaard_opslag().opslaan(pad=pad, inhoud=b"%PDF-1.4 contract")
        doc_id = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.project_document "
                    "(id, administratie_id, project_id, soort, titel, opslag_pad, bestandsnaam, geupload_door) "
                    "VALUES (:id, :aid, :pid, 'contract', 'Opdracht / contract', :pad, 'contract.pdf', :door)"
                ),
                {"id": doc_id, "aid": administratie_id, "pid": project_id, "pad": pad, "door": beheerder_id},
            )
        headers = _bearer(uitvoerder_met_scope, rol="uitvoerder")
        # zonder toewijzing: 403
        resp = client.get(f"/uren/projectdocumenten/{administratie_id}/{doc_id}", headers=headers)
        assert resp.status_code == 403
        uren_service.koppel_project(
            administratie_id=administratie_id,
            gebruiker_id=uitvoerder_met_scope,
            project_id=project_id,
            actor_id=beheerder_id,
        )
        resp = client.get(f"/uren/projectdocumenten/{administratie_id}/{doc_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")
