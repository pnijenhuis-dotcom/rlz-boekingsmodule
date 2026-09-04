"""Detacheerder-filters veld-app (opdracht Peter 04-09 blok A + addendum C): planning stuurt wat je
ziet — weken (A2), projecten per week (A1), werklijst = alleen handelingen (A3), "+ ander project"
maakt de koppeling in dezelfde gang (C1, bron 'weekstaat'), herkomst op het kantoor-overzicht (C2),
en de handmatige koppelroute die als beheer-UI vervalt (C1). Filtergedrag, geen rechtenwijziging (A4)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.security.tokens import create_access_token
from app.uren import overzichten, planning, service
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)

# Vaste ISO-week voor deterministische tests: week 34 van 2026 = ma 17-08 t/m zo 23-08; "vandaag" = za 22-08.
# Venster (OPEN_WEKEN_VENSTER = 6) = weken 29 t/m 34; week 27 (ma 29-06) valt erbuiten.
JAAR, WEEK = 2026, 34
MA, DI = date(2026, 8, 17), date(2026, 8, 18)
VANDAAG = date(2026, 8, 22)
OUD_MA = date(2026, 6, 29)  # week 27
OUD_JAAR, OUD_WEEK = 2026, 27


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.begin() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"), {"a": actie}
            ).mappings()
        ]


def _plan(administratie_id, zzper, project_id, datum, actor):
    planning.plan_toewijzing(
        administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=datum, actor_id=actor
    )


def _uren(administratie_id, zzper, project_id, datum, *, jaar=JAAR, week=WEEK, actor=None, uren="8"):
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=jaar,
        weeknummer=week,
        datum=datum,
        uren=Decimal(uren),
        actor_id=actor or zzper,
    )


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


@pytest.fixture
def detacheerder_met_scope(detacheerder, zzper_met_scope, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=detacheerder, administratie_id=administratie_id
    )
    voorwaarden.leg_akkoord_vast(gebruiker_id=detacheerder)
    service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper_met_scope, actor_id=beheerder_id)
    return detacheerder


class TestWekenFilter:
    def test_alleen_geplande_weken_plus_huidige(
        self, administratie_id, project_id, tweede_project_id, zzper_met_scope, beheerder_id
    ):
        """A2: week 34 (gepland) en de huidige week; week 27 (gepland, buiten het venster) niet."""
        _plan(administratie_id, zzper_met_scope, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper_met_scope, project_id, DI, beheerder_id)
        _plan(administratie_id, zzper_met_scope, tweede_project_id, OUD_MA, beheerder_id)

        weken = overzichten.weken_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope, vandaag=date(2026, 9, 4))
        sleutels = [(w.jaar, w.weeknummer) for w in weken]
        assert sleutels == [(2026, 36), (JAAR, WEEK)]  # huidige week eerst, dan de geplande week
        huidige, w34 = weken
        assert huidige.is_huidige and huidige.te_doen == 0 and huidige.status == "nieuw"
        assert w34.geplande_projecten == 1 and w34.te_doen == 1 and w34.status == "open"

    def test_oude_afgekeurde_week_blijft_tot_afgehandeld(
        self, administratie_id, project_id, zzper_met_scope, uitvoerder, beheerder_id
    ):
        """A2: een corrigeren-staat buiten het venster blijft zichtbaar; ná goedkeuring verdwijnt hij."""
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_id, actor_id=beheerder_id
        )
        staat = _uren(administratie_id, zzper_met_scope, project_id, OUD_MA, jaar=OUD_JAAR, week=OUD_WEEK)
        service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=zzper_met_scope,
            project_id=project_id,
            jaar=OUD_JAAR,
            weeknummer=OUD_WEEK,
            actor_id=zzper_met_scope,
        )
        service.keur_week_af(
            administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder, reden="uren onjuist"
        )
        weken = overzichten.weken_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope, vandaag=VANDAAG)
        assert [(w.jaar, w.weeknummer) for w in weken] == [(JAAR, WEEK), (OUD_JAAR, OUD_WEEK)]
        assert weken[1].te_doen == 1 and weken[1].status == "open"

        service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=zzper_met_scope,
            project_id=project_id,
            jaar=OUD_JAAR,
            weeknummer=OUD_WEEK,
            actor_id=zzper_met_scope,
        )
        service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder)
        weken = overzichten.weken_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope, vandaag=VANDAAG)
        assert [(w.jaar, w.weeknummer) for w in weken] == [(JAAR, WEEK)]

    def test_geplande_week_zonder_handeling_is_bij(
        self, administratie_id, project_id, zzper_met_scope, uitvoerder, beheerder_id
    ):
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_id, actor_id=beheerder_id
        )
        _plan(administratie_id, zzper_met_scope, project_id, MA, beheerder_id)
        _uren(administratie_id, zzper_met_scope, project_id, MA)
        service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=zzper_met_scope,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=zzper_met_scope,
        )
        (week,) = overzichten.weken_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope, vandaag=VANDAAG)
        assert week.te_doen == 0 and week.status == "ingediend" and week.totaal_uren == Decimal("8")


class TestProjectenPerWeek:
    def test_alleen_ingeplande_projecten_plus_projecten_met_staat(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper_met_scope, beheerder_id
    ):
        derde = maak_project(admin_engine, administratie_id, "26030 Venlo (Dura)")
        _plan(administratie_id, zzper_met_scope, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper_met_scope, project_id, DI, beheerder_id)
        # Uren buiten planning op het tweede project (C1: koppeling ontstaat in dezelfde gang).
        _uren(administratie_id, zzper_met_scope, tweede_project_id, MA, uren="4")

        kaarten = overzichten.week_projecten_zzp(
            zzper_id=zzper_met_scope, actor_id=zzper_met_scope, jaar=JAAR, weeknummer=WEEK
        )
        per_project = {k.project_id: k for k in kaarten}
        assert set(per_project) == {project_id, tweede_project_id}  # het derde project niet (A1)
        assert derde not in per_project
        gepland = per_project[project_id]
        assert gepland.gepland and gepland.geplande_dagen == 2 and gepland.status == "nieuw" and gepland.te_doen
        buiten = per_project[tweede_project_id]
        assert not buiten.gepland and buiten.status == "concept" and buiten.te_doen and buiten.dagen_ingevuld == 1
        # Te doen bovenaan, geplande vóór ongeplande.
        assert [k.project_id for k in kaarten] == [project_id, tweede_project_id]

    def test_projecten_keuze_alle_actieve_projecten(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper_met_scope
    ):
        inactief = maak_project(admin_engine, administratie_id, "25001 Afgerond (oud)")
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.project_cache SET is_actief = false WHERE id = :id"), {"id": inactief}
            )
        keuzes = overzichten.projecten_keuze_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope)
        assert {k.project_id for k in keuzes} == {project_id, tweede_project_id}
        assert [k.project_naam for k in keuzes] == ["26014 Eindhoven (BAM)", "26021 Tilburg (Heijmans)"]


class TestKoppelingOntstaatBijWeekstaat:
    def test_ander_project_maakt_koppeling_met_audit_bron_weekstaat(
        self, admin_engine, administratie_id, project_id, zzper_met_scope
    ):
        assert overzichten.mijn_projecten_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope) == []
        _uren(administratie_id, zzper_met_scope, project_id, MA)
        (kaart,) = overzichten.mijn_projecten_zzp(zzper_id=zzper_met_scope, actor_id=zzper_met_scope)
        assert kaart.project_id == project_id
        (event,) = _audit(admin_engine, "uren_project_gekoppeld")
        assert event["nieuwe_waarde"]["bron"] == "weekstaat"
        assert event["nieuwe_waarde"]["gebruiker_id"] == str(zzper_met_scope)
        # Tweede dagregel = geen tweede koppeling/audit (idempotent).
        _uren(administratie_id, zzper_met_scope, project_id, DI)
        assert len(_audit(admin_engine, "uren_project_gekoppeld")) == 1

    def test_namens_door_detacheerder_zelfde_gang(
        self, admin_engine, administratie_id, project_id, zzper_met_scope, detacheerder_met_scope
    ):
        _uren(administratie_id, zzper_met_scope, project_id, MA, actor=detacheerder_met_scope)
        (event,) = _audit(admin_engine, "uren_project_gekoppeld")
        assert event["nieuwe_waarde"] == {
            "gebruiker_id": str(zzper_met_scope),
            "project_id": str(project_id),
            "rol": "zzper",
            "bron": "weekstaat",
        }

    def test_niet_actief_project_weigert(self, admin_engine, administratie_id, zzper_met_scope):
        inactief = maak_project(admin_engine, administratie_id, "25001 Afgerond (oud)")
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.project_cache SET is_actief = false WHERE id = :id"), {"id": inactief}
            )
        with pytest.raises(service.GeenToegang, match="niet .meer. actief"):
            _uren(administratie_id, zzper_met_scope, inactief, MA)

    def test_planning_koppeling_draagt_bron_planning(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id
    ):
        _plan(administratie_id, zzper, project_id, MA, beheerder_id)
        (event,) = _audit(admin_engine, "uren_project_gekoppeld")
        assert event["nieuwe_waarde"]["bron"] == "planning"


class TestWerklijstDetacheerder:
    def test_te_doen_en_niets_te_doen(
        self,
        admin_engine,
        administratie_id,
        project_id,
        tweede_project_id,
        zzper_met_scope,
        detacheerder_met_scope,
        uitvoerder,
        beheerder_id,
    ):
        """A3: Milan heeft 2 handelingen (2 geplande projecten zonder staat); Stefan (gepland, ingediend)
        heeft niets te doen — te_doen 0 → verdwijnt uit de werklijst in de app."""
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_id, actor_id=beheerder_id
        )
        stefan = maak_gebruiker(admin_engine, "zzper", "Stefan B.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=stefan, administratie_id=administratie_id)
        service.koppel_detacheerder(detacheerder_id=detacheerder_met_scope, zzper_id=stefan, actor_id=beheerder_id)

        _plan(administratie_id, zzper_met_scope, project_id, MA, beheerder_id)
        _plan(administratie_id, zzper_met_scope, tweede_project_id, DI, beheerder_id)
        _plan(administratie_id, stefan, project_id, MA, beheerder_id)
        _uren(administratie_id, stefan, project_id, MA)
        service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=stefan,
            project_id=project_id,
            jaar=JAAR,
            weeknummer=WEEK,
            actor_id=stefan,
        )

        kaarten = overzichten.mijn_zzpers(detacheerder_id=detacheerder_met_scope, vandaag=VANDAAG)
        per_naam = {k.naam: k for k in kaarten}
        milan, stefan_k = per_naam["Milan K."], per_naam["Stefan B."]
        assert milan.te_doen == 2 and milan.open_weken == 1 and milan.aantal_projecten == 2
        assert stefan_k.te_doen == 0 and stefan_k.open_weken == 0 and stefan_k.aantal_projecten == 1
        assert stefan_k.laatste_invoer == MA
        assert [k.naam for k in kaarten] == ["Milan K.", "Stefan B."]  # handelingen bovenaan


class TestKantoorHerkomst:
    def test_bron_planning_weekstaat_en_handmatig(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper_met_scope, beheerder_id
    ):
        derde = maak_project(admin_engine, administratie_id, "26030 Venlo (Dura)")
        _plan(administratie_id, zzper_met_scope, project_id, MA, beheerder_id)
        _uren(administratie_id, zzper_met_scope, tweede_project_id, MA)
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=zzper_met_scope, project_id=derde, actor_id=beheerder_id
        )
        (kaart,) = [k for k in overzichten.veldgebruikers_overzicht(actor_id=beheerder_id) if k.naam == "Milan K."]
        bron_per_project = {t.project_id: t.bron for t in kaart.projecten}
        assert bron_per_project == {project_id: "planning", tweede_project_id: "weekstaat", derde: "handmatig"}


class TestVeldApi:
    def test_weken_projecten_keuze_en_weekstaat_lookup_namens(
        self,
        admin_engine,
        administratie_id,
        project_id,
        tweede_project_id,
        zzper_met_scope,
        detacheerder_met_scope,
        beheerder_id,
    ):
        vandaag = date.today()
        jaar, week = vandaag.isocalendar()[0], vandaag.isocalendar()[1]
        maandag = date.fromisocalendar(jaar, week, 1)
        _plan(administratie_id, zzper_met_scope, project_id, maandag, beheerder_id)
        headers = _bearer(detacheerder_met_scope, rol="detacheerder")
        namens = {"namens": str(zzper_met_scope)}

        resp = client.get("/uren/detacheerder/zzpers", headers=headers)
        assert resp.status_code == 200
        (kaart,) = resp.json()
        assert kaart["te_doen"] == 1 and kaart["open_weken"] == 1

        resp = client.get("/uren/zzp/weken-overzicht", params=namens, headers=headers)
        assert resp.status_code == 200, resp.text
        (huidige,) = resp.json()
        assert huidige["is_huidige"] and huidige["weeknummer"] == week and huidige["te_doen"] == 1

        resp = client.get(
            "/uren/zzp/week-projecten", params={**namens, "jaar": jaar, "weeknummer": week}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        (proj,) = resp.json()
        assert proj["project_id"] == str(project_id) and proj["gepland"] and proj["status"] == "nieuw"

        resp = client.get("/uren/zzp/projecten-keuze", params=namens, headers=headers)
        assert resp.status_code == 200
        assert {p["project_id"] for p in resp.json()} == {str(project_id), str(tweede_project_id)}

        # Lookup vóór de eerste dagregel = null (géén koppeling vereist), daarna de staat.
        lookup = {
            **namens,
            "administratie_id": str(administratie_id),
            "project_id": str(tweede_project_id),
            "jaar": jaar,
            "weeknummer": week,
        }
        resp = client.get("/uren/zzp/weekstaat", params=lookup, headers=headers)
        assert resp.status_code == 200 and resp.json()["weekstaat"] is None
        resp = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id),
                "project_id": str(tweede_project_id),
                "jaar": jaar,
                "weeknummer": week,
                "datum": maandag.isoformat(),
                "uren": "6",
                "namens_zzper_id": str(zzper_met_scope),
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        resp = client.get("/uren/zzp/weekstaat", params=lookup, headers=headers)
        assert resp.json()["weekstaat"]["dagen"][0]["buiten_planning"] is True
        # Nu 2 projecten in de week: het geplande (te doen) + het ongeplande concept (te doen).
        resp = client.get(
            "/uren/zzp/week-projecten", params={**namens, "jaar": jaar, "weeknummer": week}, headers=headers
        )
        assert [p["gepland"] for p in resp.json()] == [True, False]

    def test_zonder_koppeling_403_op_alle_nieuwe_routes(
        self, admin_engine, administratie_id, zzper_met_scope, beheerder_id
    ):
        vreemde = maak_gebruiker(admin_engine, "detacheerder", "Vreemde D.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=vreemde, administratie_id=administratie_id)
        voorwaarden.leg_akkoord_vast(gebruiker_id=vreemde)
        headers = _bearer(vreemde, rol="detacheerder")
        namens = {"namens": str(zzper_met_scope)}
        assert client.get("/uren/zzp/weken-overzicht", params=namens, headers=headers).status_code == 403
        assert (
            client.get(
                "/uren/zzp/week-projecten", params={**namens, "jaar": 2026, "weeknummer": 34}, headers=headers
            ).status_code
            == 403
        )
        assert client.get("/uren/zzp/projecten-keuze", params=namens, headers=headers).status_code == 403

    def test_handmatige_koppelroute_vervallen(self, administratie_id, project_id, zzper, beheerder_id):
        """C1: geen nieuwe handmatige koppelingen via de API; ontkoppelen blijft als noodroute."""
        resp = client.post(
            "/uren/beheer/projectkoppelingen",
            json={"administratie_id": str(administratie_id), "gebruiker_id": str(zzper), "project_id": str(project_id)},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code in (404, 405)
