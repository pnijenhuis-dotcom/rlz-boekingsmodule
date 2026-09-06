"""Kantoor-signaal "geplande week zonder weekstaat" (mini-run 06-09 blok A, migratie 0115): berekening
op de venstergrens, concept vs geen staat, afmelden/intrekken, herinnering via het push-anders-mail-
kanaal (dagrem, mislukt telt niet), herinnerde week weer zichtbaar in de veld-app, RLS met een echte
niet-Beheerder mét scope, werkvoorraad-teller en de API-poorten."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.berichten import verzending
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.main import app
from app.security.tokens import create_access_token
from app.uren import overzichten, planning, planning_signaal, service
from app.uren.dossier import AlHerinnerdVandaag, HerinneringMislukt
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)

# "Vandaag" = za 22-08-2026 (ISO-week 34). Venster (OPEN_WEKEN_VENSTER = 6) = weken 29 t/m 34; de oudste
# vensterweek 29 begint op ma 13-07. Week 28 (ma 06-07) en week 27 (ma 29-06) vallen erbuiten.
VANDAAG = date(2026, 8, 22)
WEEK27_MA, WEEK27_DI = date(2026, 6, 29), date(2026, 6, 30)
WEEK28_MA = date(2026, 7, 6)
WEEK29_MA = date(2026, 7, 13)
WEEK34_MA = date(2026, 8, 17)


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


def _plan(administratie_id, zzper, project_id, datum, actor, dagdeel="heel"):
    planning.plan_toewijzing(
        administratie_id=administratie_id,
        gebruiker_id=zzper,
        project_id=project_id,
        datum=datum,
        dagdeel=dagdeel,
        actor_id=actor,
    )


def _uren(administratie_id, zzper, project_id, datum, *, jaar, week, uren="8"):
    return service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=zzper,
        project_id=project_id,
        jaar=jaar,
        weeknummer=week,
        datum=datum,
        uren=Decimal(uren),
        actor_id=zzper,
    )


def _open(actor_id, **kw):
    return [s for s in planning_signaal.signalen_kantoorbreed(actor_id=actor_id, vandaag=VANDAAG, **kw).rijen]


def _sleutel(administratie_id, zzper, project_id, jaar=2026, week=27) -> dict:
    return {
        "administratie_id": administratie_id,
        "gebruiker_id": zzper,
        "project_id": project_id,
        "jaar": jaar,
        "weeknummer": week,
    }


@pytest.fixture
def push_ok(monkeypatch):
    verzonden: list[dict] = []

    def _nep(gebruiker, *, onderwerp, pushtekst, mailtekst, url, extra_payload=None):
        verzonden.append({"gebruiker_id": gebruiker.id, "pushtekst": pushtekst, "mailtekst": mailtekst, "url": url})
        return verzending.VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.PUSH, {"subscripties": 1}, 0)

    monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _nep)
    return verzonden


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


@pytest.fixture
def boekhouder_met_recht(admin_engine, administratie_id, beheerder_id) -> uuid.UUID:
    """Echte niet-Beheerder MÉT scope op de eerste administratie en het module-recht (RLS-les 25-08)."""
    gid = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
    service.zet_meerwerk_recht(gebruiker_id=gid, ingeschakeld=True, actor_id=beheerder_id)
    return gid


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, uren_meerwerk_ingeschakeld) "
                "VALUES (:id, 'Bradwolff (test)', :rlz, true)"
            ),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


class TestBerekening:
    def test_alleen_geplande_weken_ouder_dan_het_venster_zonder_staat(
        self, administratie_id, project_id, zzper, beheerder_id
    ):
        """Week 27 (buiten, 1,5 dag) = signaal 'geen_staat'; week 29 (oudste vensterweek) en week 34 niet."""
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        _plan(administratie_id, zzper, project_id, WEEK27_DI, beheerder_id, dagdeel="half")
        _plan(administratie_id, zzper, project_id, WEEK29_MA, beheerder_id)
        _plan(administratie_id, zzper, project_id, WEEK34_MA, beheerder_id)

        rijen = _open(beheerder_id)
        assert [(s.jaar, s.weeknummer) for s in rijen] == [(2026, 27)]
        s = rijen[0]
        assert s.soort == "geen_staat" and s.status == "open" and s.weekstaat_status is None
        assert s.geplande_dagen == Decimal("1.5")
        assert s.gebruiker_naam == "Milan K." and s.project_naam == "26014 Eindhoven (BAM)"
        assert (s.maandag, s.zondag) == (WEEK27_MA, date(2026, 7, 5))
        assert s.herinneringen == 0 and s.laatste_herinnering is None and s.afmelding is None

    def test_venstergrens_week_28_buiten_week_29_binnen(self, administratie_id, project_id, zzper, beheerder_id):
        assert planning_signaal.oudste_vensterweek(VANDAAG) == (2026, 29)
        _plan(administratie_id, zzper, project_id, WEEK28_MA, beheerder_id)
        _plan(administratie_id, zzper, project_id, WEEK29_MA, beheerder_id)
        assert [(s.jaar, s.weeknummer) for s in _open(beheerder_id)] == [(2026, 28)]
        # Eén bron: zodra "vandaag" een week opschuift, valt week 29 er óók uit.
        later = planning_signaal.signalen_kantoorbreed(actor_id=beheerder_id, vandaag=date(2026, 8, 29)).rijen
        assert [(s.jaar, s.weeknummer) for s in later] == [(2026, 28), (2026, 29)]

    def test_concept_is_signaal_ingediend_niet(self, administratie_id, project_id, zzper, beheerder_id):
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        _uren(administratie_id, zzper, project_id, WEEK27_MA, jaar=2026, week=27)
        rijen = _open(beheerder_id)
        assert len(rijen) == 1 and rijen[0].soort == "concept" and rijen[0].weekstaat_status == "concept"

        service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=27,
            actor_id=zzper,
        )
        assert _open(beheerder_id) == []

    def test_sortering_oudste_week_eerst_en_tellers(
        self, administratie_id, project_id, tweede_project_id, zzper, beheerder_id
    ):
        _plan(administratie_id, zzper, tweede_project_id, WEEK28_MA, beheerder_id)
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        p = planning_signaal.signalen_kantoorbreed(actor_id=beheerder_id, vandaag=VANDAAG)
        assert [(s.weeknummer, s.project_naam) for s in p.rijen] == [
            (27, "26014 Eindhoven (BAM)"),
            (28, "26021 Tilburg (Heijmans)"),
        ]
        assert (p.open, p.afgemeld, p.administraties, p.administraties_in_selectie, p.totaal) == (2, 0, 1, 1, 2)
        assert p.facet_administraties == [(administratie_id, "Universal Steigerbouw (test)", 2)]
        assert p.venster_weken == overzichten.OPEN_WEKEN_VENSTER

    def test_zonder_opt_in_geen_signaal_en_teller_nul(self, admin_engine, administratie_zonder_opt_in, beheerder_id):
        pid = maak_project(admin_engine, administratie_zonder_opt_in, "Zonder opt-in")
        zz = maak_gebruiker(admin_engine, "zzper", "Iemand")
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.planning_toewijzing (administratie_id, gebruiker_id, project_id, datum, "
                    "dagdeel, toegevoegd_door) VALUES (:a, :g, :p, :d, 'heel', :b)"
                ),
                {"a": administratie_zonder_opt_in, "g": zz, "p": pid, "d": WEEK27_MA, "b": beheerder_id},
            )
        assert _open(beheerder_id) == []
        with scoped_session(administratie_zonder_opt_in) as session:
            assert planning_signaal.tel_signalen(session, administratie_zonder_opt_in, vandaag=VANDAAG) == 0


class TestAfmelden:
    def test_afmelden_telt_niet_blijft_zichtbaar_intrekken_telt_weer(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id
    ):
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        planning_signaal.meld_af(
            **_sleutel(administratie_id, zzper, project_id), reden="niet gewerkt, ziek gemeld", actor_id=beheerder_id
        )
        assert _open(beheerder_id) == []
        afgemeld = _open(beheerder_id, filter="afgemeld")
        assert len(afgemeld) == 1 and afgemeld[0].status == "afgemeld"
        assert afgemeld[0].afmelding.reden == "niet gewerkt, ziek gemeld"
        p = planning_signaal.signalen_kantoorbreed(actor_id=beheerder_id, vandaag=VANDAAG, filter="alle")
        assert (p.open, p.afgemeld, p.totaal) == (0, 1, 1)
        with scoped_session(administratie_id) as session:
            assert planning_signaal.tel_signalen(session, administratie_id, vandaag=VANDAAG) == 0

        with pytest.raises(service.OngeldigeOvergang):
            planning_signaal.meld_af(
                **_sleutel(administratie_id, zzper, project_id), reden="nog een keer", actor_id=beheerder_id
            )
        planning_signaal.afmelding_intrekken(**_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id)
        assert len(_open(beheerder_id)) == 1
        assert [a["nieuwe_waarde"]["status"] for a in _audit(admin_engine, "planning_signaal_afgemeld")] == ["afgemeld"]
        assert len(_audit(admin_engine, "planning_signaal_afmelding_ingetrokken")) == 1

    def test_reden_verplicht_en_alleen_op_een_bestaand_signaal(self, administratie_id, project_id, zzper, beheerder_id):
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        with pytest.raises(service.RedenVerplicht):
            planning_signaal.meld_af(**_sleutel(administratie_id, zzper, project_id), reden="ok", actor_id=beheerder_id)
        with pytest.raises(service.OngeldigeOvergang):  # week 34 valt binnen het venster → geen signaal
            planning_signaal.meld_af(
                **_sleutel(administratie_id, zzper, project_id, week=34), reden="lange reden", actor_id=beheerder_id
            )


class TestHerinneren:
    def test_herinnering_via_push_anders_mail_max_een_per_dag(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id, push_ok
    ):
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        r = planning_signaal.stuur_herinnering(
            **_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id, vandaag=VANDAAG
        )
        assert r.kanaal == "push" and r.herinneringen == 1
        assert len(push_ok) == 1 and push_ok[0]["gebruiker_id"] == zzper
        assert "week 27" in push_ok[0]["pushtekst"] and "26014 Eindhoven (BAM)" in push_ok[0]["pushtekst"]
        assert "geen weekstaat ingediend" in push_ok[0]["mailtekst"] and push_ok[0]["url"] == "/accordeur"

        s = _open(beheerder_id)[0]
        assert s.herinneringen == 1 and s.laatste_herinnering is not None and s.laatste_herinnering.kanaal == "push"
        assert s.status == "open"  # herinneren sluit niets af

        with pytest.raises(AlHerinnerdVandaag):
            planning_signaal.stuur_herinnering(
                **_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id, vandaag=VANDAAG
            )
        assert len(push_ok) == 1
        # Volgende dag mag weer; de teller loopt op.
        r2 = planning_signaal.stuur_herinnering(
            **_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id, vandaag=date(2026, 8, 23)
        )
        assert r2.herinneringen == 2 and _open(beheerder_id)[0].herinneringen == 2
        audits = _audit(admin_engine, "planning_signaal_herinnerd")
        assert [a["nieuwe_waarde"]["herinneringen"] for a in audits] == [1, 2]

    def test_mislukte_verzending_telt_niet_en_blokkeert_de_dag_niet(
        self, admin_engine, administratie_id, project_id, zzper, beheerder_id, monkeypatch
    ):
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)

        def _mislukt(gebruiker, **kw):
            return verzending.VerzendUitkomst(HerinneringStatus.MISLUKT, None, {"fout": "SMTP dood"}, 0)

        monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _mislukt)
        with pytest.raises(HerinneringMislukt, match="SMTP dood"):
            planning_signaal.stuur_herinnering(
                **_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id, vandaag=VANDAAG
            )
        assert _open(beheerder_id)[0].herinneringen == 0
        assert len(_audit(admin_engine, "planning_signaal_herinnering_mislukt")) == 1

        def _ok(gebruiker, **kw):
            return verzending.VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.E_MAIL, {}, 0)

        monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _ok)
        r = planning_signaal.stuur_herinnering(
            **_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id, vandaag=VANDAAG
        )
        assert r.kanaal == "e-mail" and r.herinneringen == 1

    def test_afgemeld_signaal_niet_herinneren(self, administratie_id, project_id, zzper, beheerder_id, push_ok):
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        planning_signaal.meld_af(
            **_sleutel(administratie_id, zzper, project_id), reden="niet gewerkt die week", actor_id=beheerder_id
        )
        with pytest.raises(service.OngeldigeOvergang):
            planning_signaal.stuur_herinnering(
                **_sleutel(administratie_id, zzper, project_id), actor_id=beheerder_id, vandaag=VANDAAG
            )
        assert push_ok == []

    def test_herinnerde_week_komt_terug_in_de_veld_app_tot_ingediend(
        self, administratie_id, project_id, zzper_met_scope, beheerder_id, push_ok
    ):
        """Zonder herinnering blijft week 27 buiten de app (venster-besluit A2); ná een verzonden
        herinnering staat hij weer in de wekenlijst als te doen; ingediend = weg; afgemeld = weg."""
        zz = zzper_met_scope
        _plan(administratie_id, zz, project_id, WEEK27_MA, beheerder_id)
        weken = overzichten.weken_zzp(zzper_id=zz, actor_id=zz, vandaag=VANDAAG)
        assert (2026, 27) not in [(w.jaar, w.weeknummer) for w in weken]

        planning_signaal.stuur_herinnering(
            **_sleutel(administratie_id, zz, project_id), actor_id=beheerder_id, vandaag=VANDAAG
        )
        weken = overzichten.weken_zzp(zzper_id=zz, actor_id=zz, vandaag=VANDAAG)
        w27 = next(w for w in weken if (w.jaar, w.weeknummer) == (2026, 27))
        assert w27.te_doen == 1 and w27.geplande_projecten == 1 and w27.status == "open"
        projecten = overzichten.week_projecten_zzp(zzper_id=zz, actor_id=zz, jaar=2026, weeknummer=27)
        assert [p.project_id for p in projecten] == [project_id]

        _uren(administratie_id, zz, project_id, WEEK27_MA, jaar=2026, week=27)
        service.dien_week_in(
            administratie_id=administratie_id, zzper_id=zz, project_id=project_id, jaar=2026, weeknummer=27, actor_id=zz
        )
        weken = overzichten.weken_zzp(zzper_id=zz, actor_id=zz, vandaag=VANDAAG)
        assert (2026, 27) not in [(w.jaar, w.weeknummer) for w in weken]

    def test_afmelding_sluit_herinnerde_week_in_de_app(
        self, administratie_id, project_id, zzper_met_scope, beheerder_id, push_ok
    ):
        zz = zzper_met_scope
        _plan(administratie_id, zz, project_id, WEEK27_MA, beheerder_id)
        planning_signaal.stuur_herinnering(
            **_sleutel(administratie_id, zz, project_id), actor_id=beheerder_id, vandaag=VANDAAG
        )
        planning_signaal.meld_af(
            **_sleutel(administratie_id, zz, project_id), reden="toch niet gewerkt", actor_id=beheerder_id
        )
        weken = overzichten.weken_zzp(zzper_id=zz, actor_id=zz, vandaag=VANDAAG)
        assert (2026, 27) not in [(w.jaar, w.weeknummer) for w in weken]


class TestScopeEnRls:
    def test_niet_beheerder_met_scope_ziet_alleen_eigen_administraties(
        self,
        admin_engine,
        administratie_id,
        tweede_administratie,
        project_id,
        zzper,
        beheerder_id,
        boekhouder_met_recht,
    ):
        pid_b = maak_project(admin_engine, tweede_administratie, "B-project")
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        _plan(tweede_administratie, zzper, pid_b, WEEK27_MA, beheerder_id)

        alles = planning_signaal.signalen_kantoorbreed(actor_id=beheerder_id, vandaag=VANDAAG)
        assert alles.open == 2 and alles.administraties == 2

        eigen = planning_signaal.signalen_kantoorbreed(actor_id=boekhouder_met_recht, vandaag=VANDAAG)
        assert [s.administratie_id for s in eigen.rijen] == [administratie_id]
        assert (eigen.open, eigen.administraties) == (1, 1)
        with pytest.raises(service.GeenToegang):
            planning_signaal.signalen_kantoorbreed(
                actor_id=boekhouder_met_recht, administratie_id=tweede_administratie, vandaag=VANDAAG
            )
        with pytest.raises(service.GeenToegang):
            planning_signaal.meld_af(
                **_sleutel(tweede_administratie, zzper, pid_b), reden="buiten mijn scope", actor_id=boekhouder_met_recht
            )
        # Binnen de eigen scope mag de boekhouder mét recht wél afmelden (kantoorrol + module-recht).
        planning_signaal.meld_af(
            **_sleutel(administratie_id, zzper, project_id), reden="ziek gemeld die week", actor_id=boekhouder_met_recht
        )
        assert planning_signaal.signalen_kantoorbreed(actor_id=boekhouder_met_recht, vandaag=VANDAAG).open == 0

    def test_zonder_module_recht_geen_toegang(self, admin_engine, administratie_id, beheerder_id):
        gid = maak_gebruiker(admin_engine, "boekhouding", "Zonder Recht")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
        with pytest.raises(service.GeenToegang):
            planning_signaal.signalen_kantoorbreed(actor_id=gid, vandaag=VANDAAG)
        resp = client.get("/uren/kantoor/planning-signalen", headers=_bearer(gid, rol="boekhouding"))
        assert resp.status_code == 403


class TestWerkvoorraadTeller:
    def test_planning_signalen_op_de_klantenlijst(
        self, administratie_id, administratie_zonder_opt_in, project_id, zzper, beheerder_id, monkeypatch
    ):
        monkeypatch.setattr(planning_signaal, "_vandaag", lambda: VANDAAG)
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        _plan(administratie_id, zzper, project_id, WEEK28_MA, beheerder_id)
        klanten = documenten_service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "Universal"), (administratie_zonder_opt_in, "Zonder")]
        )
        per_id = {k.administratie_id: k for k in klanten}
        assert per_id[administratie_id].planning_signalen == 2
        assert per_id[administratie_zonder_opt_in].planning_signalen == 0
        assert per_id[administratie_id].te_controleren == 0  # signaal, geen status

        resp = client.get("/werkvoorraad/overzicht", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200
        rij = next(k for k in resp.json()["klanten"] if k["administratie_id"] == str(administratie_id))
        assert rij["planning_signalen"] == 2


class TestApi:
    def test_lijst_acties_en_poorten(
        self,
        admin_engine,
        administratie_id,
        project_id,
        zzper,
        beheerder_id,
        boekhouder_met_recht,
        push_ok,
        monkeypatch,
    ):
        monkeypatch.setattr(planning_signaal, "_vandaag", lambda: VANDAAG)
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        kop = _bearer(boekhouder_met_recht, rol="boekhouding")

        resp = client.get("/uren/kantoor/planning-signalen", headers=kop)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tellers"] == {"open": 1, "afgemeld": 0, "administraties": 1}
        assert body["totaal"] == 1 and body["per_pagina"] == 25 and body["venster_weken"] == 6
        rij = body["rijen"][0]
        assert rij["soort"] == "geen_staat" and rij["status"] == "open" and rij["herinnerd_vandaag"] is False
        assert rij["geplande_dagen"] == "1" and rij["weeknummer"] == 27 and rij["gebruiker_naam"] == "Milan K."
        assert body["facet_administraties"][0]["aantal"] == 1

        sleutel = {
            k: str(v) if isinstance(v, uuid.UUID) else v
            for k, v in _sleutel(administratie_id, zzper, project_id).items()
        }
        resp = client.post("/uren/kantoor/planning-signalen/herinneren", json=sleutel, headers=kop)
        assert resp.status_code == 200, resp.text
        assert resp.json()["kanaal"] == "push" and resp.json()["herinneringen"] == 1
        resp = client.post("/uren/kantoor/planning-signalen/herinneren", json=sleutel, headers=kop)
        assert resp.status_code == 409 and "al een herinnering" in resp.json()["detail"]
        rij = client.get("/uren/kantoor/planning-signalen", headers=kop).json()["rijen"][0]
        assert rij["herinnerd_vandaag"] is True and rij["herinneringen"] == 1

        resp = client.post("/uren/kantoor/planning-signalen/afmelden", json={**sleutel, "reden": "kort"}, headers=kop)
        assert resp.status_code == 422
        resp = client.post(
            "/uren/kantoor/planning-signalen/afmelden", json={**sleutel, "reden": "ziek gemeld die week"}, headers=kop
        )
        assert resp.status_code == 200, resp.text
        assert client.get("/uren/kantoor/planning-signalen", headers=kop).json()["totaal"] == 0
        assert client.get("/uren/kantoor/planning-signalen?filter=afgemeld", headers=kop).json()["totaal"] == 1
        resp = client.post("/uren/kantoor/planning-signalen/afmelden-intrekken", json=sleutel, headers=kop)
        assert resp.status_code == 200
        assert client.get("/uren/kantoor/planning-signalen", headers=kop).json()["totaal"] == 1
        resp = client.post("/uren/kantoor/planning-signalen/afmelden-intrekken", json=sleutel, headers=kop)
        assert resp.status_code == 409

        assert client.get("/uren/kantoor/planning-signalen?filter=raar", headers=kop).status_code == 422
        # Veldrol = 403 (rolpoort), ook mét scope.
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
        assert client.get("/uren/kantoor/planning-signalen", headers=_bearer(zzper, rol="zzper")).status_code == 403
        assert (
            client.post(
                "/uren/kantoor/planning-signalen/afmelden",
                json={**sleutel, "reden": "x" * 6},
                headers=_bearer(zzper, rol="zzper"),
            ).status_code
            == 403
        )

    def test_administratie_is_filter_geen_poort(
        self, admin_engine, administratie_id, tweede_administratie, project_id, zzper, beheerder_id, monkeypatch
    ):
        monkeypatch.setattr(planning_signaal, "_vandaag", lambda: VANDAAG)
        pid_b = maak_project(admin_engine, tweede_administratie, "B-project")
        _plan(administratie_id, zzper, project_id, WEEK27_MA, beheerder_id)
        _plan(tweede_administratie, zzper, pid_b, WEEK28_MA, beheerder_id)
        kop = _bearer(beheerder_id, rol="beheerder")
        alles = client.get("/uren/kantoor/planning-signalen", headers=kop).json()
        assert (
            alles["totaal"] == 2
            and alles["tellers"]["administraties"] == 2
            and alles["administraties_in_selectie"] == 2
        )
        een = client.get(f"/uren/kantoor/planning-signalen?administratie_id={tweede_administratie}", headers=kop).json()
        assert een["totaal"] == 1 and een["rijen"][0]["weeknummer"] == 28
        # De facet blijft kantoorbreed (filter, geen poort): beide administraties zichtbaar als keuze.
        assert len(een["facet_administraties"]) == 2
