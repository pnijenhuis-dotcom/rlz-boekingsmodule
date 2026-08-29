# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/uren)
"""Geofence-stempels BASIS (bouwrun 28-08 blok C, mockup geofence-stempels.html, migratie 0085):
pure aanwezigheidstoets, fail-closed intake (append-only, nooit namens, alleen projecten mét zone),
eigen stempels, keurings-kolom + oranje vlag > 1,0 u + "onvolledig paar", projectzone-velden."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.projecten import kantoor
from app.security.tokens import create_access_token
from app.uren import service, stempels
from app.uren.stempels import (
    STEMPEL_AFWIJKING_DREMPEL_UREN,
    TIJDZONE,
    StempelInvoer,
    afwijking_boven_drempel,
    bereken_aanwezigheid,
)
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

VANDAAG = date.today()
JAAR, WEEK = VANDAAG.isocalendar()[0], VANDAAG.isocalendar()[1]
MAANDAG = date.fromisocalendar(JAAR, WEEK, 1)


def _t(dag: date, uur: int, minuut: int = 0) -> datetime:
    return datetime(dag.year, dag.month, dag.day, uur, minuut, tzinfo=TIJDZONE)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class TestAanwezigheidPuur:
    D = date(2026, 8, 24)

    def test_paren_sommeren_en_eerste_in_laatste_uit(self) -> None:
        a = bereken_aanwezigheid(
            [
                (_t(self.D, 6, 55), "in"),
                (_t(self.D, 12, 4), "uit"),
                (_t(self.D, 12, 31), "in"),
                (_t(self.D, 15, 10), "uit"),
            ],
            self.D,
        )
        assert a is not None
        assert a.gestempeld_uren == Decimal("7.80")  # 5:09 + 2:39 = 7:48
        assert (a.eerste_in.hour, a.eerste_in.minute) == (6, 55)
        assert (a.laatste_uit.hour, a.laatste_uit.minute) == (15, 10)
        assert a.onvolledig is False

    def test_geen_stempels_is_none_toets_zwijgt(self) -> None:
        assert bereken_aanwezigheid([], self.D) is None
        # Stempels van een andere dag tellen niet mee.
        assert bereken_aanwezigheid([(_t(self.D + timedelta(days=1), 7), "in")], self.D) is None

    def test_ontbrekende_uit_sluit_op_middernacht_met_markering_onvolledig(self) -> None:
        a = bereken_aanwezigheid([(_t(self.D, 20, 0), "in")], self.D)
        assert a is not None
        assert a.gestempeld_uren == Decimal("4.00")  # 20:00 → 24:00, nooit gokken maar wél gemarkeerd
        assert a.onvolledig is True
        assert a.laatste_uit is None

    def test_uit_zonder_in_en_dubbele_in_markeren_onvolledig(self) -> None:
        a = bereken_aanwezigheid(
            [
                (_t(self.D, 12, 0), "uit"),
                (_t(self.D, 13, 0), "in"),
                (_t(self.D, 13, 30), "in"),
                (_t(self.D, 17, 0), "uit"),
            ],
            self.D,
        )
        assert a is not None
        assert a.gestempeld_uren == Decimal("4.00")
        assert a.onvolledig is True

    def test_drempel_1_uur(self) -> None:
        a = bereken_aanwezigheid([(_t(self.D, 7, 0), "in"), (_t(self.D, 12, 0), "uit")], self.D)  # 5,0 u
        assert Decimal("1.0") == STEMPEL_AFWIJKING_DREMPEL_UREN
        assert afwijking_boven_drempel(Decimal("8"), a) is True  # 3 u boven stempels — bespreken
        assert afwijking_boven_drempel(Decimal("5.5"), a) is False  # ruis
        assert afwijking_boven_drempel(Decimal("8"), None) is False  # geen stempels = geen toets
        assert afwijking_boven_drempel(Decimal("0"), a) is False  # 0-urendag = geen claim


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


@pytest.fixture
def project_met_zone(administratie_id, project_id, beheerder_id) -> uuid.UUID:
    kantoor.zet_specificatie(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=beheerder_id,
        locatie_adres="Kanaaldijk 12, Tilburg",
        locatie_lat=Decimal("51.560000"),
        locatie_lon=Decimal("5.083000"),
        zone_straal_m=150,
    )
    return project_id


def _stempel(administratie_id, project_id, tijdstip, soort) -> StempelInvoer:
    return StempelInvoer(administratie_id=administratie_id, project_id=project_id, tijdstip=tijdstip, soort=soort)


class TestIntake:
    def test_zonder_zone_geen_stempels_met_zone_wel_en_idempotent(
        self, administratie_id, project_id, zzper_met_scope, beheerder_id, admin_engine: Engine
    ) -> None:
        nu = datetime.now(UTC)
        with pytest.raises(stempels.StempelFout, match="geen projectzone"):
            stempels.registreer_stempels(
                actor_id=zzper_met_scope,
                apparaat_id=None,
                stempels=[_stempel(administratie_id, project_id, nu - timedelta(hours=2), "in")],
            )
        kantoor.zet_specificatie(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=beheerder_id,
            locatie_lat=Decimal("51.56"),
            locatie_lon=Decimal("5.08"),
            zone_straal_m=150,
        )
        invoer = [
            _stempel(administratie_id, project_id, nu - timedelta(hours=2), "in"),
            _stempel(administratie_id, project_id, nu - timedelta(hours=1), "uit"),
        ]
        assert stempels.registreer_stempels(actor_id=zzper_met_scope, apparaat_id=None, stempels=invoer) == 2
        # Nabezorging van dezelfde stempels telt niet dubbel (append-only, idempotent).
        assert stempels.registreer_stempels(actor_id=zzper_met_scope, apparaat_id=None, stempels=invoer) == 0
        with admin_engine.connect() as conn:
            aantal = conn.execute(text("SELECT count(*) FROM boekhouding.werkstempel")).scalar_one()
            acties = list(
                conn.execute(text("SELECT actie FROM platform.audit_event WHERE tabel='werkstempel'")).scalars()
            )
        assert aantal == 2
        assert acties == ["werkstempels_ontvangen"]

    def test_poorten_toekomst_te_oud_detacheerder_vreemde_administratie(
        self, administratie_id, project_met_zone, zzper_met_scope, administratie_zonder_opt_in, admin_engine
    ) -> None:
        nu = datetime.now(UTC)
        with pytest.raises(service.OngeldigeInvoer, match="toekomst"):
            stempels.registreer_stempels(
                actor_id=zzper_met_scope,
                apparaat_id=None,
                stempels=[_stempel(administratie_id, project_met_zone, nu + timedelta(hours=1), "in")],
            )
        with pytest.raises(service.OngeldigeInvoer, match="te oud"):
            stempels.registreer_stempels(
                actor_id=zzper_met_scope,
                apparaat_id=None,
                stempels=[_stempel(administratie_id, project_met_zone, nu - timedelta(days=30), "in")],
            )
        with pytest.raises(service.GeenToegang):
            stempels.registreer_stempels(
                actor_id=zzper_met_scope,
                apparaat_id=None,
                stempels=[_stempel(administratie_zonder_opt_in, project_met_zone, nu - timedelta(hours=1), "in")],
            )
        detacheerder = maak_gebruiker(admin_engine, "detacheerder", "Karin S.")
        with pytest.raises(service.GeenToegang, match="nooit namens"):
            stempels.registreer_stempels(
                actor_id=detacheerder,
                apparaat_id=None,
                stempels=[_stempel(administratie_id, project_met_zone, nu - timedelta(hours=1), "in")],
            )

    def test_append_only_op_db_niveau(
        self, administratie_id, project_met_zone, zzper_met_scope, app_engine: Engine
    ) -> None:
        nu = datetime.now(UTC)
        stempels.registreer_stempels(
            actor_id=zzper_met_scope,
            apparaat_id=None,
            stempels=[_stempel(administratie_id, project_met_zone, nu - timedelta(hours=1), "in")],
        )
        with pytest.raises(Exception, match="permission denied"), app_engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_administratie_id', :a, true)"), {"a": str(administratie_id)}
            )
            conn.execute(text("DELETE FROM boekhouding.werkstempel"))

    def test_eigen_stempels_en_endpoints(self, administratie_id, project_met_zone, zzper_met_scope) -> None:
        nu = datetime.now(UTC)
        body = {
            "stempels": [
                {
                    "administratie_id": str(administratie_id),
                    "project_id": str(project_met_zone),
                    "tijdstip": (nu - timedelta(hours=3)).isoformat(),
                    "soort": "in",
                },
                {
                    "administratie_id": str(administratie_id),
                    "project_id": str(project_met_zone),
                    "tijdstip": (nu - timedelta(hours=1)).isoformat(),
                    "soort": "uit",
                },
            ]
        }
        resp = client.post("/uren/stempels", json=body, headers=_bearer(zzper_met_scope, rol="zzper"))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"nieuw": 2}
        dag = (nu - timedelta(hours=3)).astimezone(TIJDZONE).date()
        resp = client.get(
            "/uren/stempels", params={"datum": dag.isoformat()}, headers=_bearer(zzper_met_scope, rol="zzper")
        )
        assert resp.status_code == 200, resp.text
        assert [s["soort"] for s in resp.json()] == ["in", "uit"]
        assert resp.json()[0]["project_naam"] == "26014 Eindhoven (BAM)"
        # Kantoor komt niet op het veld-endpoint (veldrol-poort).
        eigen = stempels.eigen_stempels(actor_id=zzper_met_scope, dag=dag)
        assert len(eigen) == 2


class TestKeuring:
    def test_kolom_gestempeld_aanwezig_vlag_en_onvolledig(
        self, administratie_id, project_met_zone, gekoppelde_zzper, zzper_met_scope, beheerder_id
    ) -> None:
        # ma: 8 u opgegeven, 5 u gestempeld → vlag; di: 8 u, 8,1 u → sluit aan; wo: geen stempels → toets zwijgt;
        # do: 4 u, alleen 'in' → onvolledig.
        ma, di, wo, do = (MAANDAG + timedelta(days=i) for i in range(4))
        if do > VANDAAG:
            pytest.skip("Testweek loopt nog — stempels in de toekomst worden bewust geweigerd")
        invoer = [
            _stempel(administratie_id, project_met_zone, _t(ma, 7, 0), "in"),
            _stempel(administratie_id, project_met_zone, _t(ma, 12, 0), "uit"),
            _stempel(administratie_id, project_met_zone, _t(di, 6, 55), "in"),
            _stempel(administratie_id, project_met_zone, _t(di, 15, 1), "uit"),
            _stempel(administratie_id, project_met_zone, _t(do, 6, 58), "in"),
        ]
        stempels.registreer_stempels(actor_id=zzper_met_scope, apparaat_id=None, stempels=invoer)
        for dag, uren in ((ma, "8"), (di, "8"), (wo, "8"), (do, "4")):
            staat = service.zet_dag(
                administratie_id=administratie_id,
                zzper_id=gekoppelde_zzper,
                project_id=project_met_zone,
                jaar=JAAR,
                weeknummer=WEEK,
                datum=dag,
                uren=Decimal(uren),
                actor_id=gekoppelde_zzper,
            )
        per = {d.datum: d for d in staat.dagen}
        assert per[ma].gestempeld_uren == Decimal("5.00") and per[ma].stempel_afwijking is True
        assert per[di].gestempeld_uren == Decimal("8.10") and per[di].stempel_afwijking is False
        assert per[wo].gestempeld_uren is None and per[wo].stempel_afwijking is False
        assert per[do].stempel_onvolledig is True and per[do].stempel_tot is None
        assert (per[ma].stempel_van.hour, per[ma].stempel_tot.hour) == (7, 12)


class TestProjectzone:
    def test_specs_validatie_en_dto(self, administratie_id, project_id, beheerder_id) -> None:
        with pytest.raises(kantoor.OngeldigeInvoer, match="zowel"):
            kantoor.zet_specificatie(
                administratie_id=administratie_id,
                project_id=project_id,
                actor_id=beheerder_id,
                locatie_lat=Decimal("51"),
            )
        with pytest.raises(kantoor.OngeldigeInvoer, match="straal"):
            kantoor.zet_specificatie(
                administratie_id=administratie_id,
                project_id=project_id,
                actor_id=beheerder_id,
                locatie_lat=Decimal("51"),
                locatie_lon=Decimal("5"),
                zone_straal_m=10,
            )
        kantoor.zet_specificatie(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=beheerder_id,
            locatie_adres="Kanaaldijk 12",
            locatie_lat=Decimal("51.560000"),
            locatie_lon=Decimal("5.083000"),
            zone_straal_m=150,
        )
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
        assert detail.specificatie is not None
        assert detail.specificatie.locatie_adres == "Kanaaldijk 12"
        assert detail.specificatie.zone_straal_m == 150
        # Endpoint-vorm: beheerder mag schrijven, DTO draagt de zone.
        resp = client.get(f"/projecten/{administratie_id}/{project_id}", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["specificatie"]["locatie_lat"] == "51.560000"


def test_voorwaardentekst_versie_v2_bevat_werkstempels() -> None:
    assert voorwaarden.AKKOORD_TEKST_VERSIE == "2026-08-28-v2"
    assert "4. Werkstempels" in voorwaarden.AKKOORD_TEKST
    assert "nooit een automatische korting" in voorwaarden.AKKOORD_TEKST


class TestZonesVoorOs:
    """Geofence-native (branch feat/geofence-native): de zones die de native app bij het OS registreert
    = projecten mét zone uit de planning van deze + volgende week van de veldwerker zelf."""

    def test_alleen_geplande_projecten_met_zone_eigen_planning_max_20(
        self, administratie_id, project_met_zone, tweede_project_id, zzper_met_scope, beheerder_id, detacheerder
    ) -> None:
        from app.uren import planning

        # Gepland op een project mét zone én op een project zónder zone; alleen de eerste is een zone.
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper_met_scope,
            project_id=project_met_zone,
            datum=MAANDAG + timedelta(days=2),
            actor_id=beheerder_id,
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper_met_scope,
            project_id=tweede_project_id,
            datum=MAANDAG + timedelta(days=3),
            actor_id=beheerder_id,
        )
        zones = stempels.zones_voor_veldwerker(actor_id=zzper_met_scope)
        assert [z.project_id for z in zones] == [project_met_zone]
        assert zones[0].lat == Decimal("51.560000") and zones[0].lon == Decimal("5.083000")
        assert zones[0].straal_m == 150 and zones[0].administratie_id == administratie_id
        # Planning van drie weken terug telt niet; volgende week wél.
        assert stempels.zones_voor_veldwerker(actor_id=zzper_met_scope, vandaag=MAANDAG - timedelta(days=21)) == []
        assert len(stempels.zones_voor_veldwerker(actor_id=zzper_met_scope, vandaag=MAANDAG - timedelta(days=7))) == 1
        # Nooit namens: een detacheerder heeft geen zones (zelfde poort als de intake).
        with pytest.raises(service.GeenToegang):
            stempels.zones_voor_veldwerker(actor_id=detacheerder)
        assert stempels.MAX_ZONES == 20
        # Endpoint (vereis_veldrol): eigen zones voor de ZZP'er, 403 voor de detacheerder.
        resp = client.get("/uren/stempels/zones", headers=_bearer(zzper_met_scope, rol="zzper"))
        assert resp.status_code == 200, resp.text
        assert resp.json()[0]["project_id"] == str(project_met_zone) and resp.json()[0]["straal_m"] == 150
        resp = client.get("/uren/stempels/zones", headers=_bearer(detacheerder, rol="detacheerder"))
        assert resp.status_code == 403
