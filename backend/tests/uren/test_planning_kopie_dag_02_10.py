"""Run B punt 20 (Peter 02-10: "mogelijkheid om ingepland werk op maandag via ctrl-C / ctrl-V bijvoorbeeld naar
vrijdag te kopiëren"; geen migratie) — backend-deel: bulkroute bron `kopie_dag` = dezelfde kaart (project + ploeg,
géén uren) naar een ANDERE dag naar keuze, exact de regels van `kopie_volgende_week` (28-09): afwezig op de doeldag =
OVERGESLAGEN mét reden (niet gepland), elders gepland = conflict (WEL gepland + oranje), bestaande kaart = samengevoegd
(overgeslagen, niets dubbel), idempotent, ongedaan = exact de aangemaakte set terug, audit per (persoon, dag) mét bron;
scope/rolpoort = de bestaande poort van de bulkroute (nooit buiten de eigen administratie)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.main import app
from app.security.tokens import create_access_token
from app.uren import planning, service
from app.uren.service import OngeldigeInvoer
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

MA, DI, WO, DO, VR = (date(2026, 8, d) for d in (17, 18, 19, 20, 21))
VANDAAG = date(2026, 8, 10)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _toewijzingen(admin_engine: Engine, administratie_id: uuid.UUID) -> set[tuple[uuid.UUID, uuid.UUID, date]]:
    with admin_engine.begin() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT gebruiker_id, project_id, datum FROM boekhouding.planning_toewijzing "
                    "WHERE administratie_id = :a"
                ),
                {"a": administratie_id},
            ).all()
        )


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.begin() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"), {"a": actie}
            ).mappings()
        ]


def _kopie_dag(administratie_id, project_id, wie: list[uuid.UUID], doel: date, actor_id):
    return planning.plan_bulk(
        administratie_id=administratie_id,
        items=[(g, project_id, doel, "heel") for g in wie],
        bron="kopie_dag",
        actor_id=actor_id,
        vandaag=VANDAAG,
    )


@pytest.fixture
def tweede_zzper(admin_engine: Engine) -> uuid.UUID:
    return maak_gebruiker(admin_engine, "zzper", "Irfan O.")


class TestKopieDag:
    def test_bron_bestaat_en_onbekende_bron_blijft_geweigerd(self):
        assert planning.BRON_KOPIE_DAG in planning.BULK_BRONNEN
        assert set(planning.KOPIE_BRONNEN) == {"kopie_volgende_week", "kopie_dag"}
        with pytest.raises(OngeldigeInvoer, match="kopie_dag"):
            planning.plan_bulk(
                administratie_id=uuid.uuid4(),
                items=[(uuid.uuid4(), uuid.uuid4(), VR, "heel")],
                bron="kopie_plakken",
                actor_id=uuid.uuid4(),
            )

    def test_maandag_naar_vrijdag_gedaan_bestaand_samengevoegd_idempotent_en_ongedaan(
        self, admin_engine, administratie_id, project_id, zzper, tweede_zzper, beheerder_id
    ):
        for g in (zzper, tweede_zzper):
            planning.plan_toewijzing(
                administratie_id=administratie_id,
                gebruiker_id=g,
                project_id=project_id,
                datum=MA,
                actor_id=beheerder_id,
            )
        # Vrijdag staat zzper al op dit project: samenvoegen, niets dubbel.
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            project_id=project_id,
            datum=VR,
            actor_id=beheerder_id,
        )
        res = _kopie_dag(administratie_id, project_id, [zzper, tweede_zzper], VR, beheerder_id)
        per = {r.gebruiker_id: r for r in res.resultaten}
        assert per[zzper].uitkomst == "overgeslagen" and per[zzper].reden == "stond al op dit project gepland"
        assert per[tweede_zzper].uitkomst == "gedaan"
        assert [r.gebruiker_id for r in res.aangemaakt] == [tweede_zzper]
        assert (tweede_zzper, project_id, VR) in _toewijzingen(admin_engine, administratie_id)
        assert len(_toewijzingen(admin_engine, administratie_id)) == 4
        gepland = [r for r in _audit(admin_engine, "planning_gepland") if r["nieuwe_waarde"].get("bron") == "kopie_dag"]
        assert len(gepland) == 1 and gepland[0]["nieuwe_waarde"]["datum"] == VR.isoformat()
        bulk = _audit(admin_engine, "planning_bulk")[-1]["nieuwe_waarde"]
        assert bulk["bron"] == "kopie_dag" and (bulk["gedaan"], bulk["overgeslagen"], bulk["conflict"]) == (1, 1, 0)
        # Idempotent.
        weer = _kopie_dag(administratie_id, project_id, [zzper, tweede_zzper], VR, beheerder_id)
        assert {r.uitkomst for r in weer.resultaten} == {"overgeslagen"} and weer.aangemaakt == []
        # Ongedaan = exact de aangemaakte set terug; de vooraf bestaande vrijdag-kaart blijft.
        terug = planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(r.gebruiker_id, r.project_id, r.datum, r.dagdeel) for r in res.aangemaakt],
            bron="ongedaan",
            verwijderen=True,
            correlatie_id=res.correlatie_id,
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [r.uitkomst for r in terug.resultaten] == ["gedaan"]
        assert _toewijzingen(admin_engine, administratie_id) == {
            (zzper, project_id, MA),
            (tweede_zzper, project_id, MA),
            (zzper, project_id, VR),
        }

    def test_afwezig_overgeslagen_met_reden_en_elders_gepland_is_conflict(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, tweede_zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            project_id=tweede_project_id,
            datum=DO,
            actor_id=beheerder_id,
        )
        planning.voeg_afwezigheid_toe(
            administratie_id=administratie_id,
            gebruiker_id=tweede_zzper,
            van=DO,
            tot=DO,
            reden="cursus",
            actor_id=beheerder_id,
        )
        res = _kopie_dag(administratie_id, project_id, [zzper, tweede_zzper], DO, beheerder_id)
        per = {r.gebruiker_id: r for r in res.resultaten}
        assert per[zzper].uitkomst == "conflict" and per[zzper].conflict == "project"
        assert per[zzper].conflict_projectnaam == "26021 Tilburg (Heijmans)"
        assert per[tweede_zzper].uitkomst == "overgeslagen" and per[tweede_zzper].conflict == "afwezig"
        assert "afwezig t/m 2026-08-20 (cursus)" in (per[tweede_zzper].reden or "")
        # Afwezig = NIET gepland (zoals de kopie naar volgende week); het conflict wél.
        assert (tweede_zzper, project_id, DO) not in _toewijzingen(admin_engine, administratie_id)
        assert (zzper, project_id, DO) in _toewijzingen(admin_engine, administratie_id)
        assert _audit(admin_engine, "planning_bulk")[-1]["nieuwe_waarde"]["overgeslagen"] == 1

    def test_route_accepteert_de_bron_en_scope_rolpoort_blijft_dicht(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id
    ):
        payload = {
            "administratie_id": str(administratie_id),
            "bron": "kopie_dag",
            "items": [{"gebruiker_id": str(zzper), "project_id": str(project_id), "datum": VR.isoformat()}],
        }
        # Veldrol 403; kantoorrol mét recht maar zónder scope op deze administratie 403 (nooit buiten de eigen scope).
        assert (
            client.post(
                f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
                json=payload,
                headers=_bearer(zzper, rol="zzper"),
            ).status_code
            == 403
        )
        met_recht = maak_gebruiker(admin_engine, "boekhouding", "Met Recht Geen Scope")
        service.zet_meerwerk_recht(gebruiker_id=met_recht, ingeschakeld=True, actor_id=beheerder_id)
        assert (
            client.post(
                f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
                json=payload,
                headers=_bearer(met_recht, rol="boekhouding"),
            ).status_code
            == 403
        )
        assert _toewijzingen(admin_engine, administratie_id) == set()
        # Mét scope: 200 en de uitkomst.
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=met_recht, administratie_id=administratie_id
        )
        resp = client.post(
            f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
            json=payload,
            headers=_bearer(met_recht, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resultaten"][0]["uitkomst"] == "gedaan"
        assert (zzper, project_id, VR) in _toewijzingen(admin_engine, administratie_id)
