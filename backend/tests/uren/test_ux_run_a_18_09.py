"""Veld-app 12 UX-verbeteringen, run A — backend (akkoord Peter 18-09; migratie 0159).

A. Omschrijving-chips per administratie (`administratie.uren_omschrijving_chips`, tekst-lijst, NULL = standaardlijst):
   veld-route `GET /uren/zzp/omschrijving-chips?administratie_id=` (veldrol + scope + opt-in), Beheerder-only
   `GET|PUT /uren/beheer/omschrijving-chips/{aid}` mét validatie (1–10, uniek, ≤ 30 tekens) en audit oud→nieuw.
B. `DagZettenRequest.bron` ('handmatig' | 'kopie') reist mee in het audit-event `weekstaat_dag_gezet`; geen ander
   gedrag.
C. Projectkaart: `laatste_regel` (laatste dagregel op dit project over ÁLLE weken — kopieer-knop), `dagen_zonder_m2`
   (regels in DEZE week zonder m²) en `contract_m2` (projectspecificatie). Set-based: +1 statement per administratie,
   onafhankelijk van het aantal kaarten (meetlat `test_project_eerst_18_09.py::TestQuerytelling` blijft staan)."""

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
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, DI, WO = date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)
# Week 33 (de week ervoor) — voor "laatste regel over álle weken".
MA33, WO33 = date(2026, 8, 10), date(2026, 8, 12)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.begin() as conn:
        rijen = conn.execute(
            text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"),
            {"a": actie},
        ).all()
    return [{"oud": r[0], "nieuw": r[1]} for r in rijen]


def _uren(administratie_id, wie, project_id, datum, *, week=(JAAR, WEEK), uren="8", m2=None, opmerking=None, **kw):  # noqa: ANN001
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=wie,
        project_id=project_id,
        jaar=week[0],
        weeknummer=week[1],
        datum=datum,
        uren=Decimal(uren),
        m2=Decimal(m2) if m2 is not None else None,
        opmerking=opmerking,
        actor_id=wie,
        **kw,
    )


def _spec(admin_engine: Engine, administratie_id, project_id, beheerder_id, *, contract_m2: str) -> None:  # noqa: ANN001
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_specificatie (project_id, administratie_id, soort_werk, contract_m2, "
                "bijgewerkt_door) VALUES (:p, :a, 'gevelsteiger', :m2, :b)"
            ),
            {"p": project_id, "a": administratie_id, "m2": Decimal(contract_m2), "b": beheerder_id},
        )


@pytest.fixture
def uitvoerder_met_scope(uitvoerder, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=uitvoerder)
    return uitvoerder


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


@pytest.fixture
def boekhouder(admin_engine: Engine, administratie_id, beheerder_id) -> uuid.UUID:
    gid = maak_gebruiker(admin_engine, "boekhouding", "Kantoor B.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
    return gid


def _kaarten(wie, **kw):  # noqa: ANN001
    return overzichten.week_projecten_zzp(zzper_id=wie, actor_id=wie, jaar=JAAR, weeknummer=WEEK, **kw)


# --- A. omschrijving-chips --------------------------------------------------------------------------------------------


class TestOmschrijvingChips:
    def test_default_is_de_codelijst_zolang_er_niets_is_opgeslagen(self, administratie_id, beheerder_id):
        chips, is_standaard = service.omschrijving_chips_voor(administratie_id=administratie_id, actor_id=beheerder_id)
        assert (
            chips == ["opbouwen", "afbreken", "ombouwen", "transport", "overig"] == service.STANDAARD_OMSCHRIJVING_CHIPS
        )
        assert is_standaard is True
        resp = client.get(
            f"/uren/beheer/omschrijving-chips/{administratie_id}", headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"chips": service.STANDAARD_OMSCHRIJVING_CHIPS, "is_standaard": True}

    def test_zetten_geeft_de_nieuwe_lijst_terug_en_audit_oud_naar_nieuw(
        self, admin_engine, administratie_id, beheerder_id
    ):
        h = _bearer(beheerder_id, rol="beheerder")
        # 'overig' mag ontbreken; witruimte wordt gestript; volgorde blijft; tekst-lijst, geen enum.
        resp = client.put(
            f"/uren/beheer/omschrijving-chips/{administratie_id}",
            json={"chips": [" opbouwen ", "afbreken", "Hangsteiger", "transport"]},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"chips": ["opbouwen", "afbreken", "Hangsteiger", "transport"], "is_standaard": False}
        resp = client.get(f"/uren/beheer/omschrijving-chips/{administratie_id}", headers=h)
        assert resp.json() == {"chips": ["opbouwen", "afbreken", "Hangsteiger", "transport"], "is_standaard": False}
        # Opslag = JSONB-tekstlijst op de administratie.
        with admin_engine.begin() as conn:
            opgeslagen = conn.execute(
                text("SELECT uren_omschrijving_chips FROM platform.administratie WHERE id = :a"),
                {"a": administratie_id},
            ).scalar_one()
        assert opgeslagen == ["opbouwen", "afbreken", "Hangsteiger", "transport"]
        (event,) = _audit(admin_engine, "uren_omschrijving_chips_gewijzigd")
        assert event["oud"] == {"chips": service.STANDAARD_OMSCHRIJVING_CHIPS, "standaard": True}
        assert event["nieuw"] == {"chips": ["opbouwen", "afbreken", "Hangsteiger", "transport"], "standaard": False}
        # Tweede wijziging: oud = de vorige opgeslagen lijst.
        resp = client.put(
            f"/uren/beheer/omschrijving-chips/{administratie_id}", json={"chips": ["opbouwen"]}, headers=h
        )
        assert resp.status_code == 200 and resp.json()["chips"] == ["opbouwen"]
        assert _audit(admin_engine, "uren_omschrijving_chips_gewijzigd")[-1]["oud"]["chips"] == [
            "opbouwen",
            "afbreken",
            "Hangsteiger",
            "transport",
        ]

    @pytest.mark.parametrize(
        "chips",
        [
            [],  # leeg
            [f"chip{i}" for i in range(11)],  # > 10
            ["opbouwen", "   "],  # lege chip ná strippen
            ["x" * 31],  # > 30 tekens
            ["Opbouwen", "opbouwen"],  # dubbel, hoofdletter-ongevoelig
        ],
        ids=["leeg", "meer-dan-tien", "lege-chip", "te-lang", "dubbel"],
    )
    def test_validatie_422_en_geen_wijziging(self, admin_engine, administratie_id, beheerder_id, chips):
        resp = client.put(
            f"/uren/beheer/omschrijving-chips/{administratie_id}",
            json={"chips": chips},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 422, resp.text
        assert _audit(admin_engine, "uren_omschrijving_chips_gewijzigd") == []
        chips_nu, is_standaard = service.omschrijving_chips_voor(
            administratie_id=administratie_id, actor_id=beheerder_id
        )
        assert chips_nu == service.STANDAARD_OMSCHRIJVING_CHIPS and is_standaard

    def test_grens_tien_chips_en_dertig_tekens_mag(self, administratie_id, beheerder_id):
        chips = [f"chip {i}" for i in range(9)] + ["y" * 30]
        resp = client.put(
            f"/uren/beheer/omschrijving-chips/{administratie_id}",
            json={"chips": chips},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["chips"] == chips

    def test_beheer_route_is_beheerder_only(self, administratie_id, boekhouder, zzper_met_scope):
        for gid, rol in ((boekhouder, "boekhouding"), (zzper_met_scope, "zzper")):
            h = _bearer(gid, rol=rol)
            assert client.get(f"/uren/beheer/omschrijving-chips/{administratie_id}", headers=h).status_code == 403
            resp = client.put(f"/uren/beheer/omschrijving-chips/{administratie_id}", json={"chips": ["x"]}, headers=h)
            assert resp.status_code == 403, f"{rol}: {resp.status_code}"

    def test_veldrol_leest_de_chips_via_de_zzp_route(self, administratie_id, zzper_met_scope, beheerder_id):
        h = _bearer(zzper_met_scope, rol="zzper")
        resp = client.get(f"/uren/zzp/omschrijving-chips?administratie_id={administratie_id}", headers=h)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"chips": service.STANDAARD_OMSCHRIJVING_CHIPS, "is_standaard": True}
        service.zet_omschrijving_chips(
            administratie_id=administratie_id, chips=["opbouwen", "afbreken"], actor_id=beheerder_id
        )
        resp = client.get(f"/uren/zzp/omschrijving-chips?administratie_id={administratie_id}", headers=h)
        assert resp.json() == {"chips": ["opbouwen", "afbreken"], "is_standaard": False}

    def test_zzp_route_vereist_scope_en_opt_in(
        self, administratie_id, administratie_zonder_opt_in, zzper, beheerder_id
    ):
        voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
        h = _bearer(zzper, rol="zzper")
        # Geen scope op de administratie → 403 (scope is de poort).
        assert (
            client.get(f"/uren/zzp/omschrijving-chips?administratie_id={administratie_id}", headers=h).status_code
            == 403
        )
        # Wél scope, maar geen uren-opt-in → 409 (module bestaat daar niet).
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_zonder_opt_in
        )
        resp = client.get(f"/uren/zzp/omschrijving-chips?administratie_id={administratie_zonder_opt_in}", headers=h)
        assert resp.status_code == 409, resp.text
        # Kantoorrol op de veld-route = 403 (bestaande veldrol-poort).
        assert (
            client.get(
                f"/uren/zzp/omschrijving-chips?administratie_id={administratie_id}",
                headers=_bearer(beheerder_id, rol="beheerder"),
            ).status_code
            == 403
        )


# --- B. bron in het audit-event ---------------------------------------------------------------------------------------


class TestDagBron:
    def test_default_handmatig_en_kopie_in_het_audit_event(
        self, admin_engine, administratie_id, project_id, uitvoerder_met_scope
    ):
        wie = uitvoerder_met_scope
        _uren(administratie_id, wie, project_id, MA)
        _uren(administratie_id, wie, project_id, DI, bron="kopie")
        events = _audit(admin_engine, "weekstaat_dag_gezet")
        assert [e["nieuw"]["bron"] for e in events] == ["handmatig", "kopie"]
        assert events[1]["nieuw"]["datum"] == DI.isoformat()

    def test_api_neemt_bron_over_en_weigert_onbekende_bron(
        self, admin_engine, administratie_id, project_id, uitvoerder_met_scope
    ):
        h = _bearer(uitvoerder_met_scope, rol="uitvoerder")
        payload = {
            "administratie_id": str(administratie_id),
            "project_id": str(project_id),
            "jaar": JAAR,
            "weeknummer": WEEK,
            "datum": MA.isoformat(),
            "uren": "8",
        }
        assert client.put("/uren/zzp/dag", json=payload, headers=h).status_code == 200
        assert (
            client.put(
                "/uren/zzp/dag", json={**payload, "datum": DI.isoformat(), "bron": "kopie"}, headers=h
            ).status_code
            == 200
        )
        assert client.put("/uren/zzp/dag", json={**payload, "bron": "ai"}, headers=h).status_code == 422
        events = _audit(admin_engine, "weekstaat_dag_gezet")
        assert [e["nieuw"]["bron"] for e in events] == ["handmatig", "kopie"]
        # Geen ander gedrag: de regel zelf is identiek aan een handmatige regel.
        staat = client.get(
            f"/uren/zzp/weekstaat?administratie_id={administratie_id}&project_id={project_id}&jaar={JAAR}&weeknummer={WEEK}",
            headers=h,
        ).json()["weekstaat"]
        assert [Decimal(d["uren"]) for d in staat["dagen"]] == [Decimal(8), Decimal(8)]


# --- C. laatste_regel / dagen_zonder_m2 / contract_m2 -----------------------------------------------------------------


class TestLaatsteRegel:
    def test_laatste_regel_komt_uit_een_vorige_week(
        self, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope, beheerder_id
    ):
        wie = uitvoerder_met_scope
        _uren(administratie_id, wie, project_id, MA33, week=(2026, 33), uren="8", m2="40", opmerking="opbouwen")
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=wie, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=wie,
            project_id=tweede_project_id,
            datum=MA,
            actor_id=beheerder_id,
        )
        per = {k.project_id: k for k in _kaarten(wie)}
        kaart = per[project_id]
        assert kaart.weekstaat_id is None and kaart.dag_uren == {}  # week 34 zelf heeft nog geen staat
        assert kaart.laatste_regel == overzichten.LaatsteRegel(
            datum=MA33, uren=Decimal("8"), m2=Decimal("40.00"), opmerking="opbouwen", doorfactureren=False
        )
        assert per[tweede_project_id].laatste_regel is None  # nog nooit uren op dit project

    def test_met_twee_regels_wint_de_laatste_datum_ook_over_weken_heen(
        self, administratie_id, project_id, uitvoerder_met_scope, beheerder_id
    ):
        wie = uitvoerder_met_scope
        _uren(administratie_id, wie, project_id, WO33, week=(2026, 33), uren="4", opmerking="afbreken")
        _uren(administratie_id, wie, project_id, MA33, week=(2026, 33), uren="8", opmerking="opbouwen")
        planning.plan_toewijzing(
            administratie_id=administratie_id, gebruiker_id=wie, project_id=project_id, datum=MA, actor_id=beheerder_id
        )
        (kaart,) = _kaarten(wie)
        assert kaart.laatste_regel is not None and kaart.laatste_regel.datum == WO33
        assert kaart.laatste_regel.opmerking == "afbreken" and kaart.laatste_regel.uren == Decimal("4")
        # Een regel in de week zelf ligt later → die wint; de kaart draagt tegelijk de weekvelden.
        _uren(administratie_id, wie, project_id, DI, uren="6", m2="12.5", opmerking="ombouwen", doorfactureren=True)
        (kaart,) = _kaarten(wie)
        assert kaart.laatste_regel == overzichten.LaatsteRegel(
            datum=DI, uren=Decimal("6"), m2=Decimal("12.50"), opmerking="ombouwen", doorfactureren=True
        )
        assert kaart.dag_uren == {DI.isoformat(): Decimal("6")}

    def test_laatste_regel_is_van_deze_gebruiker_alleen(
        self, administratie_id, project_id, uitvoerder_met_scope, zzper_met_scope, beheerder_id
    ):
        _uren(administratie_id, zzper_met_scope, project_id, WO33, week=(2026, 33), uren="7", opmerking="andermans")
        planning.plan_toewijzing(
            administratie_id=administratie_id,
            gebruiker_id=uitvoerder_met_scope,
            project_id=project_id,
            datum=MA,
            actor_id=beheerder_id,
        )
        (kaart,) = _kaarten(uitvoerder_met_scope)
        assert kaart.laatste_regel is None

    def test_dagen_zonder_m2_en_contract_m2_ook_bij_alles(
        self, admin_engine, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope, beheerder_id
    ):
        wie = uitvoerder_met_scope
        _spec(admin_engine, administratie_id, project_id, beheerder_id, contract_m2="1250.50")
        _uren(administratie_id, wie, project_id, MA, uren="8", m2="40")
        _uren(administratie_id, wie, project_id, DI, uren="8")  # zonder m²
        _uren(administratie_id, wie, project_id, WO, uren="4")  # zonder m²
        _uren(administratie_id, wie, project_id, WO33, week=(2026, 33), uren="2")  # vorige week telt NIET mee
        per = {k.project_id: k for k in _kaarten(wie)}
        kaart = per[project_id]
        assert kaart.dagen_zonder_m2 == 2
        assert kaart.contract_m2 == Decimal("1250.50")
        assert kaart.soort_werk == "gevelsteiger"
        assert tweede_project_id not in per
        # `alles=True`: de kaart zonder staat draagt óók de specs (contract_m2) en nul-waarden.
        alle = {k.project_id: k for k in _kaarten(wie, alles=True)}
        assert alle[project_id].dagen_zonder_m2 == 2 and alle[project_id].contract_m2 == Decimal("1250.50")
        assert alle[project_id].laatste_regel is not None and alle[project_id].laatste_regel.datum == WO
        ander = alle[tweede_project_id]
        assert ander.contract_m2 is None and ander.dagen_zonder_m2 == 0 and ander.laatste_regel is None

    def test_api_draagt_de_drie_velden(
        self, admin_engine, administratie_id, project_id, uitvoerder_met_scope, beheerder_id
    ):
        wie = uitvoerder_met_scope
        _spec(admin_engine, administratie_id, project_id, beheerder_id, contract_m2="800")
        _uren(administratie_id, wie, project_id, MA33, week=(2026, 33), uren="8", m2="30", opmerking="opbouwen")
        _uren(administratie_id, wie, project_id, MA, uren="6")
        resp = client.get(
            f"/uren/zzp/week-projecten?jaar={JAAR}&weeknummer={WEEK}", headers=_bearer(wie, rol="uitvoerder")
        )
        assert resp.status_code == 200, resp.text
        (kaart,) = resp.json()
        laatste = kaart["laatste_regel"]
        assert laatste["datum"] == MA.isoformat() and Decimal(laatste["uren"]) == Decimal("6")
        assert laatste["m2"] is None and laatste["opmerking"] is None and laatste["doorfactureren"] is False
        assert kaart["dagen_zonder_m2"] == 1
        assert Decimal(kaart["contract_m2"]) == Decimal("800")

    def test_querytelling_laatste_regel_is_een_constante(
        self, admin_engine, administratie_id, project_id, tweede_project_id, uitvoerder_met_scope, beheerder_id
    ):
        """+1 statement per administratie, ongeacht het aantal kaarten (meetlat project-eerst blijft staan)."""
        from tests.uren.conftest import maak_project
        from tests.uren.test_project_eerst_18_09 import _Teller

        wie = uitvoerder_met_scope
        _uren(administratie_id, wie, project_id, MA33, week=(2026, 33), uren="8")
        _uren(administratie_id, wie, tweede_project_id, MA, uren="4")
        with _Teller() as klein:
            assert len(_kaarten(wie)) == 1  # project_id heeft in week 34 (nog) geen kaart
        for i in range(4):
            p = maak_project(admin_engine, administratie_id, f"2607{i} Extra {i}")
            _uren(administratie_id, wie, p, WO33, week=(2026, 33), uren="3")
            _uren(administratie_id, wie, p, DI, uren="2")
        with _Teller() as groot:
            assert len(_kaarten(wie)) == 5
        assert len(groot.statements) == len(klein.statements), (len(klein.statements), len(groot.statements))
