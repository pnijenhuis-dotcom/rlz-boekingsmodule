"""Run B 02-10, punt 26 — planningstab uitvoerder (herziet "geen planningstab" 18-09 blok D uitsluitend voor de rol
uitvoerder): `GET /uren/uitvoerder/dagplanning?datum=` geeft álle geplande projecten van die dag binnen de scope —
project, opdrachtgever, plaats, ploeg (naam/dagdeel), transport-icoon (Transport-tab, status ≠ geannuleerd),
werkopdracht; reservering zonder ploeg telt mee als "gereserveerd"; andere dag = leeg; buiten scope = niets;
ZZP'er = 403. Alleen-lezen: plannen doet het kantoor."""

# ruff: noqa: F811 — pytest-fixtures uit tests/uren/conftest als parameters (zelfde patroon als tests/projecten/test_kantoorbreed.py)
from __future__ import annotations

import uuid
from datetime import time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.materiaal import service as materiaal
from app.security.tokens import create_access_token
from app.tijd import vandaag_nl
from app.uren import planning
from app.uren import service as uren_service
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.uren.conftest import (  # noqa: F401
    administratie_id,
    maak_gebruiker,
    maak_project,
    project_id,
    tweede_project_id,
    uitvoerder,
    zzper,
)

client = TestClient(app)

VANDAAG = vandaag_nl()
# Een werkdag ≥ vandaag (geen "achteraf"-melding nodig): de eerstvolgende maandag.
DAG = VANDAAG + timedelta(days=(7 - VANDAAG.weekday()) % 7 or 7)
ANDERE_DAG = DAG + timedelta(days=1)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _spec(admin_engine: Engine, aid: uuid.UUID, pid: uuid.UUID, door: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_specificatie "
                "(project_id, administratie_id, opdrachtgever, werknummer_opdrachtgever, "
                "locatie_adres, bijgewerkt_door) "
                "VALUES (:pid, :aid, 'BAM', 'W-4711', 'Hoofddorp, Kruisweg 12', :door)"
            ),
            {"pid": pid, "aid": aid, "door": door},
        )


@pytest.fixture
def uitvoerder_met_scope(uitvoerder, administratie_id, beheerder_id) -> uuid.UUID:  # noqa: F811
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=uitvoerder)
    return uitvoerder


@pytest.fixture
def dagplanning(
    admin_engine: Engine,
    administratie_id,
    project_id,
    tweede_project_id,
    uitvoerder_met_scope,
    zzper,
    beheerder_id,  # noqa: F811
) -> dict:
    """Project 1: ploeg (uitvoerder heel + ZZP'er half) + transport levering 07:30; project 2: alleen reservering."""
    _spec(admin_engine, administratie_id, project_id, beheerder_id)
    planning.plan_toewijzing(
        administratie_id=administratie_id,
        gebruiker_id=uitvoerder_met_scope,
        project_id=project_id,
        datum=DAG,
        actor_id=beheerder_id,
    )
    planning.plan_toewijzing(
        administratie_id=administratie_id,
        gebruiker_id=zzper,
        project_id=project_id,
        datum=DAG,
        dagdeel="half",
        actor_id=beheerder_id,
    )
    planning.maak_reservering(
        administratie_id=administratie_id, project_id=tweede_project_id, datum=DAG, actor_id=beheerder_id
    )
    leverancier_id = materiaal.seed_universal(administratie_id=administratie_id, actor_id=beheerder_id).leverancier_id
    transport = materiaal.plan_transport(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        project_id=project_id,
        leverancier_id=leverancier_id,
        soort="levering",
        datum=DAG,
        tijdstip=time(7, 30),
        regels={},
        omschrijving=None,
    )
    return {"transport_id": transport.id}


class TestService:
    def test_alle_projecten_van_de_dag_met_ploeg_transport_en_reservering(
        self,
        dagplanning,
        administratie_id,
        project_id,
        tweede_project_id,
        uitvoerder_met_scope,
        zzper,  # noqa: F811
    ):
        rijen = planning.dagplanning_uitvoerder(uitvoerder_id=uitvoerder_met_scope, datum=DAG)
        assert [r.project_id for r in rijen] == sorted(
            [project_id, tweede_project_id], key=lambda pid: {project_id: "26014", tweede_project_id: "26021"}[pid]
        )
        p1 = next(r for r in rijen if r.project_id == project_id)
        assert (p1.opdrachtgever, p1.werknummer_opdrachtgever, p1.plaats) == ("BAM", "W-4711", "Hoofddorp, Kruisweg 12")
        # Ploeg: uitvoerder eerst, dan de ZZP'er (halve dag); namen uit platform.gebruiker.
        assert [(p.naam, p.dagdeel, p.is_uitvoerder) for p in p1.ploeg] == [
            ("Ben v. Dijk", "heel", True),
            ("Milan K.", "half", False),
        ]
        assert p1.gereserveerd is False
        assert p1.transport is not None
        assert (p1.transport.soort, p1.transport.tijdstip, p1.transport.status) == (
            "levering",
            time(7, 30),
            "gereserveerd",
        )
        p2 = next(r for r in rijen if r.project_id == tweede_project_id)
        assert p2.gereserveerd is True and p2.ploeg == [] and p2.transport is None

    def test_andere_dag_is_leeg_en_geannuleerd_transport_telt_niet(
        self,
        admin_engine: Engine,
        dagplanning,
        administratie_id,
        project_id,
        uitvoerder_met_scope,  # noqa: F811
    ):
        assert planning.dagplanning_uitvoerder(uitvoerder_id=uitvoerder_met_scope, datum=ANDERE_DAG) == []
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.materiaal_transport SET status = 'geannuleerd', "
                    "status_reden = 'test' WHERE id = :id"
                ),
                {"id": dagplanning["transport_id"]},
            )
        p1 = next(
            r
            for r in planning.dagplanning_uitvoerder(uitvoerder_id=uitvoerder_met_scope, datum=DAG)
            if r.project_id == project_id
        )
        assert p1.transport is None

    def test_buiten_scope_niets_en_zzper_geen_toegang(
        self,
        admin_engine: Engine,
        dagplanning,
        administratie_id,
        zzper,
        beheerder_id,  # noqa: F811
    ):
        # Een tweede uitvoerder zónder scope op de administratie ziet niets (scope is de poort, niet de koppeling).
        andere = maak_gebruiker(admin_engine, "uitvoerder", "Andere uitvoerder")
        assert planning.dagplanning_uitvoerder(uitvoerder_id=andere, datum=DAG) == []
        # De ZZP'er heeft zijn eigen alleen-lezen weekplanning (18-09) — niet de dagplanning van de uitvoerder.
        with pytest.raises(uren_service.GeenToegang, match="rol uitvoerder"):
            planning.dagplanning_uitvoerder(uitvoerder_id=zzper, datum=DAG)


class TestRoute:
    def test_route_geeft_dagplanning_en_weigert_zzper(
        self, dagplanning, uitvoerder_met_scope, zzper, administratie_id, project_id
    ):  # noqa: F811
        resp = client.get(
            f"/uren/uitvoerder/dagplanning?datum={DAG.isoformat()}",
            headers=_bearer(uitvoerder_met_scope, rol="uitvoerder"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 2
        p1 = next(r for r in body if r["project_id"] == str(project_id))
        assert p1["transport"] == {"soort": "levering", "tijdstip": "07:30:00", "status": "gereserveerd"}
        assert p1["plaats"] == "Hoofddorp, Kruisweg 12" and p1["opdrachtgever"] == "BAM"
        assert [p["naam"] for p in p1["ploeg"]] == ["Ben v. Dijk", "Milan K."]
        assert p1["gereserveerd"] is False
        leeg = client.get(
            f"/uren/uitvoerder/dagplanning?datum={ANDERE_DAG.isoformat()}",
            headers=_bearer(uitvoerder_met_scope, rol="uitvoerder"),
        )
        assert leeg.status_code == 200 and leeg.json() == []
        voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
        geweigerd = client.get(
            f"/uren/uitvoerder/dagplanning?datum={DAG.isoformat()}", headers=_bearer(zzper, rol="zzper")
        )
        assert geweigerd.status_code == 403
