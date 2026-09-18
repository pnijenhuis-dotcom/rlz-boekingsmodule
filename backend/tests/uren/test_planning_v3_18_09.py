"""Planning personeel v3 "dag-eerst" — backend (mockup planning-v3-dag-eerst.html, AKKOORD Peter 18-09; migratie 0161).

Bulkroute (vulhandvat / ploeg / ongedaan) in ÉÉN transactie: gedaan | overgeslagen (idempotent) | conflict (WEL gepland,
gemarkeerd — kantoor beslist), echte fout = alles terug, limiet 200, audit per (persoon, dag) mét correlatie-id + één
samenvattende rij; reservering (kaart zonder ploeg) idempotent + geaudit; afwezigheid minimaal (nooit verwijderen,
overlap 409, beëindigen = vervroegen); leesroute draagt reserveringen/afwezigheid/pool.afwezig_tot; rolpoort + scope +
RLS (FORCE, andere scope ziet niets); querytelling: statements onafhankelijk van het aantal items."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text

from app.auth import service as auth_service
from app.db import session as db_session
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.uren import planning, service
from app.uren.models import PlanningReservering, PlanningToewijzing, VeldwerkerAfwezigheid
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, DI, WO, DO, VR = (date(2026, 8, d) for d in (17, 18, 19, 20, 21))
VANDAAG = date(2026, 8, 10)  # vóór de week: geen 'achteraf'


class _Teller:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        self.statements.append(statement)

    def __enter__(self) -> _Teller:
        event.listen(db_session.engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(db_session.engine, "before_cursor_execute", self)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _items(wie: list[uuid.UUID], project_id: uuid.UUID, datums: list[date]) -> list[tuple]:
    return [(g, project_id, d, "heel") for d in datums for g in wie]


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


@pytest.fixture
def tweede_zzper(admin_engine: Engine) -> uuid.UUID:
    return maak_gebruiker(admin_engine, "zzper", "Irfan O.")


class TestBulkVulhandvat:
    def test_kopieert_kaart_plus_ploeg_over_de_week_en_is_idempotent(
        self, admin_engine, administratie_id, project_id, zzper, tweede_zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            project_id=project_id,
            datum=MA,
            actor_id=beheerder_id,
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=tweede_zzper,
            project_id=project_id,
            datum=MA,
            actor_id=beheerder_id,
        )
        res = planning.plan_bulk(
            administratie_id=administratie_id,
            items=_items([zzper, tweede_zzper], project_id, [DI, WO, DO, VR]),
            bron="vulhandvat",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [r.uitkomst for r in res.resultaten] == ["gedaan"] * 8
        assert len(res.aangemaakt) == 8
        assert len(_toewijzingen(admin_engine, administratie_id)) == 10
        # Audit: per (persoon, dag) mét de bulk-correlatie + bron, plus één samenvattende rij.
        gepland = _audit(admin_engine, "planning_gepland")
        bulk_rijen = [r for r in gepland if r["nieuwe_waarde"].get("bulk_correlatie_id") == str(res.correlatie_id)]
        assert len(bulk_rijen) == 8 and all(r["nieuwe_waarde"]["bron"] == "vulhandvat" for r in bulk_rijen)
        samenvatting = _audit(admin_engine, "planning_bulk")
        assert samenvatting[-1]["nieuwe_waarde"]["gedaan"] == 8
        # Dezelfde set nog eens = alles overgeslagen, niets dubbel, geen fout.
        weer = planning.plan_bulk(
            administratie_id=administratie_id,
            items=_items([zzper, tweede_zzper], project_id, [DI, WO, DO, VR]),
            bron="vulhandvat",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert {r.uitkomst for r in weer.resultaten} == {"overgeslagen"} and weer.aangemaakt == []
        assert len(_toewijzingen(admin_engine, administratie_id)) == 10

    def test_ongedaan_maken_verwijdert_exact_de_aangemaakte_set(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id
    ):
        res = planning.plan_bulk(
            administratie_id=administratie_id,
            items=_items([zzper], project_id, [MA, DI, WO]),
            bron="vulhandvat",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert len(_toewijzingen(admin_engine, administratie_id)) == 3
        terug = planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(r.gebruiker_id, r.project_id, r.datum, r.dagdeel) for r in res.aangemaakt]
            + [(zzper, project_id, VR, "heel")],  # bestond niet → overgeslagen
            bron="ongedaan",
            verwijderen=True,
            correlatie_id=res.correlatie_id,
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [r.uitkomst for r in terug.resultaten] == ["gedaan", "gedaan", "gedaan", "overgeslagen"]
        assert _toewijzingen(admin_engine, administratie_id) == set()
        verwijderd = _audit(admin_engine, "planning_verwijderd")
        assert all(r["nieuwe_waarde"]["bulk_correlatie_id"] == str(res.correlatie_id) for r in verwijderd)
        assert all(r["nieuwe_waarde"]["bron"] == "ongedaan" for r in verwijderd)

    def test_conflict_ander_project_en_afwezig_worden_wel_gepland_maar_gemarkeerd(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper, tweede_zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            project_id=tweede_project_id,
            datum=DI,
            actor_id=beheerder_id,
        )
        planning.voeg_afwezigheid_toe(
            administratie_id=administratie_id,
            gebruiker_id=tweede_zzper,
            van=WO,
            tot=DO,
            reden="verlof",
            actor_id=beheerder_id,
        )
        res = planning.plan_bulk(
            administratie_id=administratie_id,
            items=_items([zzper, tweede_zzper], project_id, [DI, WO]),
            bron="vulhandvat",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        per = {(r.gebruiker_id, r.datum): r for r in res.resultaten}
        assert per[(zzper, DI)].uitkomst == "conflict" and per[(zzper, DI)].conflict == "project"
        assert per[(zzper, DI)].conflict_projectnaam == "26021 Tilburg (Heijmans)"
        assert per[(tweede_zzper, WO)].uitkomst == "conflict" and per[(tweede_zzper, WO)].conflict == "afwezig"
        assert "afwezig t/m 2026-08-20 (verlof)" in (per[(tweede_zzper, WO)].reden or "")
        assert per[(zzper, WO)].uitkomst == "gedaan" and per[(tweede_zzper, DI)].uitkomst == "gedaan"
        # Nooit blokkerend: álle vier staan gepland; de audit draagt het conflict.
        assert len(_toewijzingen(admin_engine, administratie_id)) == 5
        assert len(res.aangemaakt) == 4
        conflicten = [r for r in _audit(admin_engine, "planning_gepland") if r["nieuwe_waarde"].get("conflict")]
        assert sorted(r["nieuwe_waarde"]["conflict"] for r in conflicten) == ["afwezig", "project"]

    def test_echte_fout_rolt_alles_terug(self, admin_engine, administratie_id, project_id, zzper, beheerder_id):
        with pytest.raises(service.NietGevonden):
            planning.plan_bulk(
                administratie_id=administratie_id,
                items=_items([zzper], project_id, [MA, DI]) + [(zzper, uuid.uuid4(), WO, "heel")],
                bron="ploeg",
                actor_id=beheerder_id,
                vandaag=VANDAAG,
            )
        assert _toewijzingen(admin_engine, administratie_id) == set()
        assert _audit(admin_engine, "planning_bulk") == []

    def test_limiet_bron_en_dubbel_in_aanroep(self, administratie_id, project_id, zzper, beheerder_id):
        with pytest.raises(service.OngeldigeInvoer, match="Hoogstens 200"):
            planning.plan_bulk(
                administratie_id=administratie_id,
                items=[(zzper, project_id, MA, "heel")] * 201,
                bron="vulhandvat",
                actor_id=beheerder_id,
            )
        with pytest.raises(service.OngeldigeInvoer, match="Onbekende bron"):
            planning.plan_bulk(
                administratie_id=administratie_id,
                items=[(zzper, project_id, MA, "heel")],
                bron="knop",
                actor_id=beheerder_id,
            )
        with pytest.raises(service.OngeldigeInvoer, match="Geen items"):
            planning.plan_bulk(administratie_id=administratie_id, items=[], bron="ploeg", actor_id=beheerder_id)
        res = planning.plan_bulk(
            administratie_id=administratie_id,
            items=[(zzper, project_id, MA, "heel"), (zzper, project_id, MA, "half")],
            bron="ploeg",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [r.uitkomst for r in res.resultaten] == ["gedaan", "overgeslagen"]

    def test_geen_n_plus_1_statements_onafhankelijk_van_aantal_items(
        self, administratie_id, project_id, zzper, tweede_zzper, beheerder_id
    ):
        with _Teller() as klein:
            planning.plan_bulk(
                administratie_id=administratie_id,
                items=_items([zzper], project_id, [MA]),
                bron="vulhandvat",
                actor_id=beheerder_id,
                vandaag=VANDAAG,
            )
        with _Teller() as groot:
            planning.plan_bulk(
                administratie_id=administratie_id,
                items=_items([zzper], project_id, [DI, WO, DO, VR]),
                bron="vulhandvat",
                actor_id=beheerder_id,
                vandaag=VANDAAG,
            )
        # Per item: één INSERT + één audit-INSERT + de melding-rij-lookup/insert (per persoon × week) — de
        # leeswerk-statements
        # (project, persoon, bestaande toewijzingen, afwezigheid, projectnamen) zijn constant.
        per_item_max = 4
        assert len(groot.statements) - len(klein.statements) <= per_item_max * 3, (
            len(klein.statements),
            len(groot.statements),
        )
        selects_klein = sum(1 for s in klein.statements if s.lstrip().upper().startswith("SELECT"))
        selects_groot = sum(1 for s in groot.statements if s.lstrip().upper().startswith("SELECT"))
        # Leeswerk is constant: bestaande toewijzingen in één query, koppeling één keer per (persoon, project).
        assert selects_groot == selects_klein, (selects_klein, selects_groot)


class TestReservering:
    def test_idempotent_geaudit_en_in_de_leesroute(self, admin_engine, administratie_id, project_id, beheerder_id):
        data, nieuw = planning.maak_reservering(
            administratie_id=administratie_id, project_id=project_id, datum=DI, actor_id=beheerder_id
        )
        assert nieuw is True and data.projectnaam == "26014 Eindhoven (BAM)" and data.datum == DI
        weer, nieuw2 = planning.maak_reservering(
            administratie_id=administratie_id, project_id=project_id, datum=DI, actor_id=beheerder_id
        )
        assert nieuw2 is False and weer.id == data.id
        week = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        assert [(r.project_id, r.datum) for r in week.reserveringen] == [(project_id, DI)]
        planning.verwijder_reservering(administratie_id=administratie_id, reservering_id=data.id, actor_id=beheerder_id)
        planning.verwijder_reservering(administratie_id=administratie_id, reservering_id=data.id, actor_id=beheerder_id)
        with admin_engine.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.planning_reservering")).scalar_one() == 0
            acties = list(
                conn.scalars(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'planning_reservering' ORDER BY tijdstip"
                    )
                )
            )
        assert acties == ["planning_gereserveerd", "planning_reservering_verwijderd"]

    def test_inactief_project_weigert(self, admin_engine, administratie_id, beheerder_id):
        pid = maak_project(admin_engine, administratie_id, "26099 Oud")
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.project_cache SET is_actief = false WHERE id = :p"), {"p": pid})
        with pytest.raises(service.OngeldigeInvoer, match="actieve projecten"):
            planning.maak_reservering(
                administratie_id=administratie_id, project_id=pid, datum=MA, actor_id=beheerder_id
            )


class TestAfwezigheid:
    def test_toevoegen_overlap_beeindigen_en_pool_afwezig_tot(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id
    ):
        a = planning.voeg_afwezigheid_toe(
            administratie_id=administratie_id,
            gebruiker_id=zzper,
            van=DI,
            tot=VR,
            reden="  verlof ",
            actor_id=beheerder_id,
        )
        assert a.reden == "verlof"
        with pytest.raises(service.OngeldigeOvergang, match="al afwezig gemeld"):
            planning.voeg_afwezigheid_toe(
                administratie_id=administratie_id,
                gebruiker_id=zzper,
                van=DO,
                tot=date(2026, 8, 25),
                reden=None,
                actor_id=beheerder_id,
            )
        week = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        pool = {p.gebruiker_id: p for p in week.pool}
        assert pool[zzper].afwezig_tot == VR
        assert [(x.gebruiker_id, x.van, x.tot) for x in week.afwezigheid] == [(zzper, DI, VR)]
        # Beëindigen = vervroegen; verlengen weigert; vóór van weigert.
        with pytest.raises(service.OngeldigeInvoer, match="alleen vervroegen"):
            planning.beeindig_afwezigheid(
                administratie_id=administratie_id, afwezigheid_id=a.id, tot=date(2026, 8, 24), actor_id=beheerder_id
            )
        with pytest.raises(service.OngeldigeInvoer, match="vóór de begindatum"):
            planning.beeindig_afwezigheid(
                administratie_id=administratie_id, afwezigheid_id=a.id, tot=MA, actor_id=beheerder_id
            )
        b = planning.beeindig_afwezigheid(
            administratie_id=administratie_id, afwezigheid_id=a.id, tot=WO, actor_id=beheerder_id
        )
        assert b.tot == WO and b.beeindigd_op is not None
        # Nooit verwijderd: de rij bestaat nog; audit oud→nieuw.
        with admin_engine.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.veldwerker_afwezigheid")).scalar_one() == 1
            rij = (
                conn.execute(
                    text(
                        "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                        "WHERE actie = 'afwezigheid_beeindigd'"
                    )
                )
                .mappings()
                .one()
            )
        assert rij["oude_waarde"] == {"tot": VR.isoformat()} and rij["nieuwe_waarde"] == {"tot": WO.isoformat()}
        # Ná het vervroegen is DO weer plan-baar zonder conflict.
        res = planning.plan_bulk(
            administratie_id=administratie_id,
            items=_items([zzper], project_id, [WO, DO]),
            bron="ploeg",
            actor_id=beheerder_id,
            vandaag=VANDAAG,
        )
        assert [(r.datum, r.uitkomst) for r in res.resultaten] == [(WO, "conflict"), (DO, "gedaan")]

    def test_recht_meerwerk_of_veldwerkerbeheer_en_alleen_planbare_personen(
        self, admin_engine, administratie_id, zzper, detacheerder, beheerder_id
    ):
        zonder = maak_gebruiker(admin_engine, "boekhouding", "Zonder Recht")
        with pytest.raises(service.GeenToegang):
            planning.afwezigheid_overzicht(administratie_id=administratie_id, gebruiker_id=None, actor_id=zonder)
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Met Veldwerkerbeheer")
        service.zet_veldwerkerbeheer_recht(gebruiker_id=bp, ingeschakeld=True, actor_id=beheerder_id)
        assert planning.afwezigheid_overzicht(administratie_id=administratie_id, gebruiker_id=zzper, actor_id=bp) == []
        with pytest.raises(service.OngeldigeInvoer, match="Alleen ZZP'ers en uitvoerders"):
            planning.voeg_afwezigheid_toe(
                administratie_id=administratie_id, gebruiker_id=detacheerder, van=MA, tot=MA, reden=None, actor_id=bp
            )


class TestApiEnPoorten:
    def test_bulk_reservering_afwezigheid_via_de_api(
        self, admin_engine, administratie_id, project_id, zzper, tweede_zzper, beheerder_id
    ):
        kop = _bearer(beheerder_id, rol="beheerder")
        resp = client.post(
            f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
            json={
                "administratie_id": str(administratie_id),
                "bron": "vulhandvat",
                "items": [
                    {"gebruiker_id": str(g), "project_id": str(project_id), "datum": d.isoformat()}
                    for d in (MA, DI)
                    for g in (zzper, tweede_zzper)
                ],
            },
            headers=kop,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["aangemaakt"]) == 4 and {r["uitkomst"] for r in body["resultaten"]} == {"gedaan"}
        assert body["resultaten"][0]["dagdeel"] == "heel"
        # Ongedaan via dezelfde route.
        terug = client.post(
            f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
            json={
                "administratie_id": str(administratie_id),
                "bron": "ongedaan",
                "verwijderen": True,
                "correlatie_id": body["correlatie_id"],
                "items": [
                    {k: r[k] for k in ("gebruiker_id", "project_id", "datum", "dagdeel")} for r in body["aangemaakt"]
                ],
            },
            headers=kop,
        )
        assert terug.status_code == 200 and terug.json()["correlatie_id"] == body["correlatie_id"]
        assert _toewijzingen(admin_engine, administratie_id) == set()
        # Limiet via pydantic (201 items) = 422.
        te_veel = client.post(
            f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
            json={
                "administratie_id": str(administratie_id),
                "bron": "ploeg",
                "items": [{"gebruiker_id": str(zzper), "project_id": str(project_id), "datum": MA.isoformat()}] * 201,
            },
            headers=kop,
        )
        assert te_veel.status_code == 422
        # Reservering 201 → 200; lijst draagt 'm; verwijderen 204.
        r1 = client.post(
            f"/uren/kantoor/planning/reservering?administratie_id={administratie_id}",
            json={"administratie_id": str(administratie_id), "project_id": str(project_id), "datum": WO.isoformat()},
            headers=kop,
        )
        assert r1.status_code == 201, r1.text
        r2 = client.post(
            f"/uren/kantoor/planning/reservering?administratie_id={administratie_id}",
            json={"administratie_id": str(administratie_id), "project_id": str(project_id), "datum": WO.isoformat()},
            headers=kop,
        )
        assert r2.status_code == 200 and r2.json()["id"] == r1.json()["id"]
        week = client.get(
            f"/uren/kantoor/planning?administratie_id={administratie_id}&jaar={JAAR}&weeknummer={WEEK}", headers=kop
        )
        assert week.status_code == 200
        assert [r["datum"] for r in week.json()["reserveringen"]] == [WO.isoformat()]
        assert week.json()["afwezigheid"] == [] and week.json()["pool"][0]["afwezig_tot"] is None
        assert (
            client.post(
                f"/uren/kantoor/planning/reservering/verwijderen?administratie_id={administratie_id}",
                json={"administratie_id": str(administratie_id), "id": r1.json()["id"]},
                headers=kop,
            ).status_code
            == 204
        )
        # Afwezigheid: 201, overlap 409, lijst, beëindigen 200.
        a1 = client.post(
            f"/uren/kantoor/afwezigheid?administratie_id={administratie_id}",
            json={
                "administratie_id": str(administratie_id),
                "gebruiker_id": str(zzper),
                "van": DI.isoformat(),
                "tot": DO.isoformat(),
                "reden": "cursus",
            },
            headers=kop,
        )
        assert a1.status_code == 201, a1.text
        a2 = client.post(
            f"/uren/kantoor/afwezigheid?administratie_id={administratie_id}",
            json={
                "administratie_id": str(administratie_id),
                "gebruiker_id": str(zzper),
                "van": DO.isoformat(),
                "tot": VR.isoformat(),
            },
            headers=kop,
        )
        assert a2.status_code == 409 and "al afwezig gemeld" in a2.json()["detail"]
        lijst = client.get(
            f"/uren/kantoor/afwezigheid?administratie_id={administratie_id}&gebruiker_id={zzper}", headers=kop
        )
        assert lijst.status_code == 200 and [x["reden"] for x in lijst.json()] == ["cursus"]
        b = client.post(
            f"/uren/kantoor/afwezigheid/beeindigen?administratie_id={administratie_id}",
            json={"administratie_id": str(administratie_id), "id": a1.json()["id"], "tot": DI.isoformat()},
            headers=kop,
        )
        assert b.status_code == 200 and b.json()["tot"] == DI.isoformat() and b.json()["beeindigd_op"]

    def test_rolpoort_en_scope_fail_closed(self, admin_engine, administratie_id, project_id, zzper, beheerder_id):
        payload = {
            "administratie_id": str(administratie_id),
            "bron": "ploeg",
            "items": [{"gebruiker_id": str(zzper), "project_id": str(project_id), "datum": MA.isoformat()}],
        }
        # Veldrol: 403 op rolniveau.
        assert (
            client.post(
                f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
                json=payload,
                headers=_bearer(zzper, rol="zzper"),
            ).status_code
            == 403
        )
        # Kantoorrol zonder module-recht: 403.
        zonder = maak_gebruiker(admin_engine, "boekhouding", "Zonder Recht")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zonder, administratie_id=administratie_id)
        assert (
            client.post(
                f"/uren/kantoor/planning/bulk?administratie_id={administratie_id}",
                json=payload,
                headers=_bearer(zonder, rol="boekhouding"),
            ).status_code
            == 403
        )
        # Mét recht maar zónder scope op deze administratie: 403 (scope is de poort).
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
        assert (
            client.get(
                f"/uren/kantoor/afwezigheid?administratie_id={administratie_id}",
                headers=_bearer(met_recht, rol="boekhouding"),
            ).status_code
            == 403
        )
        assert _toewijzingen(admin_engine, administratie_id) == set()


class TestRls:
    def test_force_rls_en_andere_scope_ziet_niets(
        self, admin_engine, administratie_id, administratie_zonder_opt_in, project_id, zzper, beheerder_id
    ):
        planning.maak_reservering(
            administratie_id=administratie_id, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        planning.voeg_afwezigheid_toe(
            administratie_id=administratie_id, gebruiker_id=zzper, van=MA, tot=MA, reden=None, actor_id=beheerder_id
        )
        with admin_engine.begin() as conn:
            for tabel in ("planning_reservering", "veldwerker_afwezigheid"):
                rij = conn.execute(
                    text(
                        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'boekhouding' AND c.relname = :t"
                    ),
                    {"t": tabel},
                ).one()
                assert rij == (True, True), tabel
            # Geen DELETE-grant op afwezigheid (niets verdwijnt stil); reservering wél (planningsintentie).
            grants = {
                (r[0], r[1])
                for r in conn.execute(
                    text(
                        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                        "WHERE grantee = 'boekhouding_app' AND table_schema = 'boekhouding' "
                        "AND table_name IN ('planning_reservering', 'veldwerker_afwezigheid')"
                    )
                ).all()
            }
        assert ("veldwerker_afwezigheid", "DELETE") not in grants
        assert ("planning_reservering", "DELETE") in grants
        # De app-rol gescoopt op een ANDERE administratie ziet geen rij (RLS); in de eigen scope wél.
        with scoped_session(administratie_zonder_opt_in, actor_id=beheerder_id) as sessie:
            assert sessie.query(PlanningReservering).count() == 0
            assert sessie.query(VeldwerkerAfwezigheid).count() == 0
            assert sessie.query(PlanningToewijzing).count() == 0
        with scoped_session(administratie_id, actor_id=beheerder_id) as sessie:
            assert sessie.query(PlanningReservering).count() == 1
            assert sessie.query(VeldwerkerAfwezigheid).count() == 1
