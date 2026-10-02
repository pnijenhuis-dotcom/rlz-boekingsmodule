"""Run B punt 24 (Peter 02-10, feedback planning: "als er een transport gepland staat op een werk dan willen wij bij
tabje personeel op dat werk een vrachtwagen icoontje zien, zodat we weten dat daar een planning geleverd staat"; geen
migratie): de planning-weekroute draagt `transporten` = álle niet-geannuleerde transporten van de week (zelfde bron als
de Transport-tab), per project × dag mét soort/tijdstip/status/samenvatting — lees-only (geen status-flow, geen
schrijfpad). Geannuleerd en een andere week tellen niet mee; oudere responses zonder het veld blijven geldig
(default [])."""

from __future__ import annotations

import uuid
from datetime import date, time

from fastapi.testclient import TestClient

from app.main import app
from app.materiaal import service as materiaal
from app.security.tokens import create_access_token

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, WO = date(2026, 8, 17), date(2026, 8, 19)
MA_VOLGENDE_WEEK = date(2026, 8, 24)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _plan(administratie_id, beheerder_id, project_id, leverancier_id, *, datum, tijdstip=None, soort="levering"):
    return materiaal.plan_transport(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        project_id=project_id,
        leverancier_id=leverancier_id,
        soort=soort,
        datum=datum,
        tijdstip=tijdstip,
        regels={},
        omschrijving=None,
    )


class TestTransportIcoonInDePlanningWeek:
    def test_gepland_transport_staat_op_project_x_dag_geannuleerd_en_andere_week_niet(
        self, administratie_id, project_id, tweede_project_id, beheerder_id
    ):
        seed = materiaal.seed_universal(administratie_id=administratie_id, actor_id=beheerder_id)
        leverancier_id = seed.leverancier_id
        kop = _bearer(beheerder_id, rol="beheerder")

        gepland = _plan(administratie_id, beheerder_id, project_id, leverancier_id, datum=MA, tijdstip=time(7, 30))
        retour = _plan(administratie_id, beheerder_id, project_id, leverancier_id, datum=WO, soort="retour")
        geannuleerd = _plan(administratie_id, beheerder_id, tweede_project_id, leverancier_id, datum=MA)
        materiaal.zet_transport_status(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            transport_id=geannuleerd.id,
            nieuwe_status="geannuleerd",
            reden="test: komt niet in de planning",
        )
        _plan(administratie_id, beheerder_id, project_id, leverancier_id, datum=MA_VOLGENDE_WEEK)

        week = client.get(
            f"/uren/kantoor/planning?administratie_id={administratie_id}&jaar={JAAR}&weeknummer={WEEK}", headers=kop
        )
        assert week.status_code == 200, week.text
        transporten = week.json()["transporten"]
        assert [(t["project_id"], t["datum"], t["soort"]) for t in transporten] == [
            (str(project_id), MA.isoformat(), "levering"),
            (str(project_id), WO.isoformat(), "retour"),
        ]
        eerste = transporten[0]
        assert eerste["transport_id"] == str(gepland.id)
        assert eerste["tijdstip"] == "07:30:00"
        assert eerste["status"] == "gereserveerd"
        assert eerste["samenvatting"] == "Levering"  # geen materiaal → kale soort-tekst (bestaande samenvatting)
        assert transporten[1]["transport_id"] == str(retour.id)
        # Geannuleerd (ander project, zelfde dag) en de week erna ontbreken.
        assert all(t["transport_id"] != str(geannuleerd.id) for t in transporten)
        assert all(t["project_id"] != str(tweede_project_id) for t in transporten)

    def test_zonder_transporten_is_het_veld_een_lege_lijst(self, administratie_id, beheerder_id):
        week = client.get(
            f"/uren/kantoor/planning?administratie_id={administratie_id}&jaar={JAAR}&weeknummer={WEEK}",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert week.status_code == 200, week.text
        assert week.json()["transporten"] == []
