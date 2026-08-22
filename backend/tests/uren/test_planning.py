"""Planning-agenda steigerbouw (akkoord Peter 22-08, mockup planning-steigerbouw.html):
de harde failsafe persoon×project×dag, besluit A (plannen maakt de projectkoppeling
automatisch aan, geaudit), de dekking-detectie op de weekstaten (buiten-planning-vlag bij de
keuring), de kantoor-signalen (dubbele dag zonder dekking + 30-dagen-teller, besluit C-teller
in de pool) en de RLS-/scope-poorten (opt-in, module-recht, veld-leesroute besluit B)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import app
from app.security.tokens import create_access_token
from app.uren import planning, service
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)

# Vaste ISO-week voor deterministische tests: week 34 van 2026 = ma 17-08 t/m zo 23-08.
JAAR, WEEK = 2026, 34
MA, DI, WO = date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)
VANDAAG = date(2026, 8, 22)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit_acties(admin_engine: Engine, tabel: str) -> list[str]:
    with admin_engine.begin() as conn:
        return list(
            conn.scalars(
                text("SELECT actie FROM platform.audit_event WHERE tabel = :t ORDER BY tijdstip"),
                {"t": tabel},
            )
        )


def _zet_uren(administratie_id, zzper, project_id, datum, uren="8"):
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        datum=datum,
        uren=Decimal(uren),
        actor_id=zzper,
    )


class TestFailsafeUniekeSleutel:
    def test_zelfde_persoon_zelfde_dag_zelfde_project_weigert(self, administratie_id, project_id, zzper, beheerder_id):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        with pytest.raises(service.OngeldigeInvoer, match="al op dit project gepland"):
            planning.plan_toewijzing(
                administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA,
                dagdeel="half", actor_id=beheerder_id,
            )

    def test_meerdere_personen_en_meerdere_projecten_wel_geldig(
        self, administratie_id, project_id, tweede_project_id, zzper, uitvoerder, beheerder_id
    ):
        """Meerdere kaartjes per cel én (via dagdelen) twee projecten op één dag per persoon."""
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA,
            dagdeel="half", actor_id=beheerder_id,
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_id, datum=MA,
            actor_id=beheerder_id,
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=tweede_project_id, datum=MA,
            dagdeel="half", actor_id=beheerder_id,
        )
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        per_project = {rij.project_id: rij for rij in data.projecten}
        assert len(per_project[project_id].per_datum[MA.isoformat()]) == 2
        assert per_project[project_id].week_man == 2
        # Pool-teller (besluit C-voeding): 2× half = 1,0 dag; de uitvoerder 1,0 dag.
        pool = {p.gebruiker_id: p for p in data.pool}
        assert pool[zzper].geplande_dagen == Decimal("1")
        assert pool[uitvoerder].geplande_dagen == Decimal("1")

    def test_alleen_planbare_rollen_en_actieve_projecten(
        self, admin_engine: Engine, administratie_id, project_id, detacheerder, zzper, beheerder_id
    ):
        with pytest.raises(service.OngeldigeInvoer, match="ZZP'ers en uitvoerders"):
            planning.plan_toewijzing(
                administratie_id=administratie_id, gebruiker_id=detacheerder, project_id=project_id, datum=MA,
                actor_id=beheerder_id,
            )
        inactief = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.project_cache (id, administratie_id, naam, is_actief, brondata) "
                    "VALUES (:id, :aid, 'Afgerond project', false, '{}')"
                ),
                {"id": inactief, "aid": administratie_id},
            )
        with pytest.raises(service.OngeldigeInvoer, match="actieve projecten"):
            planning.plan_toewijzing(
                administratie_id=administratie_id, gebruiker_id=zzper, project_id=inactief, datum=MA,
                actor_id=beheerder_id,
            )


class TestBesluitAAutoKoppeling:
    def test_plannen_maakt_de_projectkoppeling_aan_en_audit(
        self, admin_engine: Engine, administratie_id, project_id, zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        # De koppeling bestaat nu — de ZZP'er kan direct uren schrijven op dit project.
        staat = _zet_uren(administratie_id, zzper, project_id, MA)
        assert staat.dagen[0].uren == Decimal("8")
        acties = _audit_acties(admin_engine, "uren_project_toewijzing")
        assert "uren_project_gekoppeld" in acties
        with admin_engine.begin() as conn:
            bron = conn.scalar(
                text(
                    "SELECT nieuwe_waarde->>'bron' FROM platform.audit_event "
                    "WHERE tabel = 'uren_project_toewijzing' AND actie = 'uren_project_gekoppeld'"
                )
            )
        assert bron == "planning"

    def test_bestaande_koppeling_wordt_niet_gedupliceerd(
        self, admin_engine: Engine, administratie_id, project_id, gekoppelde_zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=project_id, datum=MA,
            actor_id=beheerder_id,
        )
        with admin_engine.begin() as conn:
            aantal = conn.scalar(
                text(
                    "SELECT count(*) FROM boekhouding.uren_project_toewijzing "
                    "WHERE administratie_id = :aid AND gebruiker_id = :gid AND project_id = :pid"
                ),
                {"aid": administratie_id, "gid": gekoppelde_zzper, "pid": project_id},
            )
        assert aantal == 1


class TestVerplaatsenEnDagdeel:
    def test_verplaatsen_is_atomair_en_behoudt_dagdeel(
        self, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA,
            dagdeel="half", actor_id=beheerder_id,
        )
        planning.verplaats_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, van_project_id=project_id, van_datum=MA,
            naar_project_id=tweede_project_id, naar_datum=DI, actor_id=beheerder_id,
        )
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        per_project = {rij.project_id: rij for rij in data.projecten}
        assert per_project[project_id].per_datum == {}
        [kaart] = per_project[tweede_project_id].per_datum[DI.isoformat()]
        assert kaart.dagdeel == "half"

    def test_verplaatsen_naar_bezette_cel_weigert(
        self, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=tweede_project_id, datum=DI,
            actor_id=beheerder_id,
        )
        with pytest.raises(service.OngeldigeInvoer, match="doelproject gepland"):
            planning.verplaats_toewijzing(
                administratie_id=administratie_id, gebruiker_id=zzper, van_project_id=project_id, van_datum=MA,
                naar_project_id=tweede_project_id, naar_datum=DI, actor_id=beheerder_id,
            )

    def test_dagdeel_zetten(self, admin_engine: Engine, administratie_id, project_id, zzper, beheerder_id):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        planning.zet_dagdeel(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA,
            dagdeel="half", actor_id=beheerder_id,
        )
        with pytest.raises(service.OngeldigeInvoer, match="dagdeel"):
            planning.zet_dagdeel(
                administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA,
                dagdeel="kwart", actor_id=beheerder_id,
            )
        acties = _audit_acties(admin_engine, "planning_toewijzing")
        assert acties == ["planning_gepland", "planning_dagdeel_gezet"]


class TestDekkingDetectie:
    def test_uren_op_gepland_project_groen_en_buiten_planning_oranje(
        self, administratie_id, project_id, gekoppelde_zzper, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=project_id, datum=MA,
            actor_id=beheerder_id,
        )
        _zet_uren(administratie_id, gekoppelde_zzper, project_id, MA)
        staat = _zet_uren(administratie_id, gekoppelde_zzper, project_id, DI)
        per_datum = {d.datum: d for d in staat.dagen}
        assert per_datum[MA].buiten_planning is False  # gepland → groen
        assert per_datum[DI].buiten_planning is True  # niet gepland → oranje, geen blokkade

    def test_nul_uren_dag_telt_niet_als_buiten_planning(
        self, administratie_id, project_id, gekoppelde_zzper
    ):
        staat = _zet_uren(administratie_id, gekoppelde_zzper, project_id, MA, uren="0")
        assert staat.dagen[0].buiten_planning is False


class TestSignalen:
    def test_dubbele_dag_zonder_dekking_geeft_melding_en_teller(
        self, administratie_id, project_id, tweede_project_id, gekoppelde_zzper, beheerder_id
    ):
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=tweede_project_id,
            actor_id=beheerder_id,
        )
        # Alleen project 1 gepland op WO; uren op béíde projecten die dag.
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=project_id, datum=WO,
            dagdeel="half", actor_id=beheerder_id,
        )
        _zet_uren(administratie_id, gekoppelde_zzper, project_id, WO, uren="4")
        _zet_uren(administratie_id, gekoppelde_zzper, tweede_project_id, WO, uren="4")
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        [melding] = data.dubbele_dagen
        assert melding.gebruiker_id == gekoppelde_zzper
        assert melding.datum == WO
        assert len(melding.project_namen) == 2
        assert melding.ongedekte_project_namen == ["26021 Tilburg (Heijmans)"]
        [teller] = data.dubbele_dag_tellers
        assert (teller.gebruiker_id, teller.aantal) == (gekoppelde_zzper, 1)
        # En het ongedekte project staat ook als losse buiten-planning-melding in de lijst.
        assert [m.project_naam for m in data.buiten_planning] == ["26021 Tilburg (Heijmans)"]

    def test_dubbele_dag_volledig_gedekt_geeft_geen_melding(
        self, administratie_id, project_id, tweede_project_id, gekoppelde_zzper, beheerder_id
    ):
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=tweede_project_id,
            actor_id=beheerder_id,
        )
        for pid in (project_id, tweede_project_id):
            planning.plan_toewijzing(
                administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=pid, datum=WO,
                dagdeel="half", actor_id=beheerder_id,
            )
            _zet_uren(administratie_id, gekoppelde_zzper, pid, WO, uren="4")
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id, vandaag=VANDAAG
        )
        assert data.dubbele_dagen == []
        assert data.dubbele_dag_tellers == []
        assert data.buiten_planning == []

    def test_teller_kijkt_alleen_naar_de_laatste_30_dagen(
        self, administratie_id, project_id, tweede_project_id, gekoppelde_zzper, beheerder_id
    ):
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, project_id=tweede_project_id,
            actor_id=beheerder_id,
        )
        _zet_uren(administratie_id, gekoppelde_zzper, project_id, WO, uren="4")
        _zet_uren(administratie_id, gekoppelde_zzper, tweede_project_id, WO, uren="4")
        buiten_venster = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=beheerder_id,
            vandaag=date(2026, 12, 1),
        )
        assert buiten_venster.dubbele_dag_tellers == []
        # De week-meldingen van de getoonde week blijven wél zichtbaar (die volgen de weekkeuze).
        assert len(buiten_venster.dubbele_dagen) == 1


class TestScopeEnPoorten:
    def test_opt_in_verplicht(self, administratie_zonder_opt_in, zzper, beheerder_id, admin_engine: Engine):
        pid = maak_project(admin_engine, administratie_zonder_opt_in, "Project zonder opt-in")
        with pytest.raises(service.ModuleUitgeschakeld):
            planning.plan_toewijzing(
                administratie_id=administratie_zonder_opt_in, gebruiker_id=zzper, project_id=pid, datum=MA,
                actor_id=beheerder_id,
            )

    def test_module_recht_verplicht_voor_kantoorrol(
        self, admin_engine: Engine, administratie_id, project_id, zzper, beheerder_id
    ):
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Zonder Recht")
        with pytest.raises(service.GeenToegang, match="module-recht"):
            planning.plan_toewijzing(
                administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA,
                actor_id=medewerker,
            )
        with pytest.raises(service.GeenToegang, match="module-recht"):
            planning.planning_overzicht(
                administratie_id=administratie_id, jaar=JAAR, weeknummer=WEEK, actor_id=medewerker, vandaag=VANDAAG
            )

    def test_veldrol_kan_nooit_plannen_via_de_kantoor_api(self, administratie_id, zzper, project_id):
        """Fail-closed: de kantoor-planning-endpoints weigeren een veldrol op rolniveau (de
        sweep in tests/security dekt dit ook, hier expliciet voor het mutatiepad)."""
        resp = client.post(
            "/uren/kantoor/planning",
            json={
                "administratie_id": str(administratie_id),
                "gebruiker_id": str(zzper),
                "project_id": str(project_id),
                "datum": MA.isoformat(),
            },
            headers=_bearer(zzper, rol="zzper"),
        )
        assert resp.status_code == 403

    def test_mijn_planning_alleen_zelf_of_gekoppelde_detacheerder(
        self, admin_engine: Engine, administratie_id, project_id, zzper, detacheerder, beheerder_id
    ):
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=zzper, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        # Detacheerder zónder koppeling → geen toegang.
        with pytest.raises(service.GeenToegang, match="niet aan deze ZZP'er gekoppeld"):
            planning.mijn_planning(veldwerker_id=zzper, actor_id=detacheerder, jaar=JAAR, weeknummer=WEEK)
        # Een andere ZZP'er kan nooit andermans planning lezen.
        andere = maak_gebruiker(admin_engine, "zzper", "Andere ZZP'er")
        with pytest.raises(service.GeenToegang):
            planning.mijn_planning(veldwerker_id=zzper, actor_id=andere, jaar=JAAR, weeknummer=WEEK)
        # Mét koppeling wél (namens-flow, besluit B) — mits de administratie in de scope van de
        # detacheerder zit (accordeur-wachtrij-patroon).
        service.koppel_detacheerder(detacheerder_id=detacheerder, zzper_id=zzper, actor_id=beheerder_id)
        from app.auth import service as auth_service

        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=detacheerder, administratie_id=administratie_id
        )
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
        dagen = planning.mijn_planning(veldwerker_id=zzper, actor_id=detacheerder, jaar=JAAR, weeknummer=WEEK)
        assert [(d.datum, d.dagdeel) for d in dagen] == [(MA, "heel")]
        # En de ZZP'er zelf ziet hetzelfde (alleen-lezen leesroute).
        eigen = planning.mijn_planning(veldwerker_id=zzper, actor_id=zzper, jaar=JAAR, weeknummer=WEEK)
        assert len(eigen) == 1
