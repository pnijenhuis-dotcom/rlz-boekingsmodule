"""Veld-app UX run B, punt 4 — dag-einde herinnering "Nog geen uren voor vandaag" (akkoord Peter 18-09; migratie 0162).

Motor `app/uren/herinnering.py`: alleen werkdagen (NL), ná de administratie-tijd (default 16:30 — geen instelling =
default doorlopen, kernprincipe 7 "geen stille no-op"), vóór 19:00; kandidaten = ZZP'er/uitvoerder mét scope op een
administratie mét opt-in (detacheerder nooit); overslaan zichtbaar geteld (al uren over álle weekstaten, opt-out, al
verzonden = idempotent, stille uren, geen kanaal = claim); push-anders-mail; audit `uren_herinnering_run` per run =
bron van de reconciliatie-teller. Routes: `GET/PUT /uren/zzp/herinnering` (eigen opt-out), `GET/PUT
/uren/beheer/herinnering-tijd/{aid}` (Beheerder-only). Offline-contract: 409 op `PUT /uren/zzp/dag` draagt `code`,
`status` en `server_regel`."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.berichten import verzending
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.main import app
from app.reconciliatie import automatiseringen as auto
from app.security.tokens import create_access_token
from app.uren import herinnering, service
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

# Donderdag 17-09-2026: 16:45 NL = 14:45 UTC (CEST) — ná de default 16:30.
DONDERDAG = date(2026, 9, 17)
NU_1645 = datetime(2026, 9, 17, 14, 45, tzinfo=UTC)
NU_1600 = datetime(2026, 9, 17, 14, 0, tzinfo=UTC)
NU_1915 = datetime(2026, 9, 17, 17, 15, tzinfo=UTC)
ZATERDAG_1645 = datetime(2026, 9, 19, 14, 45, tzinfo=UTC)
JAAR, WEEK = 2026, 38


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def kanaal(monkeypatch):
    """Verzendkanaal gemockt — elke herinnering komt aan via push; de motor is het onderwerp."""
    verzonden: list[dict] = []

    def _nep(gebruiker, *, onderwerp, pushtekst, mailtekst, url, extra_payload=None):
        verzonden.append({"gebruiker_id": gebruiker.id, "onderwerp": onderwerp, "url": url, "mail": mailtekst})
        return verzending.VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.PUSH, {"subscripties": 1}, 0)

    monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _nep)
    return verzonden


@pytest.fixture
def zzper_in_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


@pytest.fixture
def uitvoerder_in_scope(uitvoerder, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=uitvoerder)
    return uitvoerder


def _claims(admin_engine: Engine) -> list[tuple]:
    with admin_engine.begin() as conn:
        return conn.execute(
            text("SELECT gebruiker_id, datum, kanaal FROM boekhouding.uren_herinnering ORDER BY verzonden_op")
        ).all()


def _run_audits(admin_engine: Engine) -> list[dict]:
    with admin_engine.begin() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'uren_herinnering_run' ORDER BY tijdstip")
            ).all()
        ]


def _zet_tijd(admin_engine: Engine, aid: uuid.UUID, t: time | None) -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.administratie SET uren_herinnering_tijd = :t WHERE id = :id"), {"t": t, "id": aid})


class TestMotor:
    @pytest.mark.afwezig_pad("administratie.uren_meerwerk_ingeschakeld")
    def test_geen_tijd_ingesteld_is_default_1630_en_loopt_door(self, kanaal, zzper_in_scope, admin_engine, administratie_id):
        """Geen stille no-op: zonder ingestelde tijd geldt 16:30 en de herinnering gaat gewoon uit."""
        assert herinnering.herinneringstijd(type("A", (), {"uren_herinnering_tijd": None})()) == time(16, 30)
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert (rapport.administraties_met_opt_in, rapport.administraties_tijd_bereikt) == (1, 1)
        assert (rapport.kandidaten, rapport.verwacht, rapport.gedaan, rapport.verzonden_push) == (1, 1, 1, 1)
        assert kanaal[0]["gebruiker_id"] == zzper_in_scope
        assert kanaal[0]["url"] == "/accordeur?uren=vandaag"
        assert kanaal[0]["onderwerp"] == "Nog geen uren voor vandaag"
        assert "⚙ Toegang" in kanaal[0]["mail"]
        assert [(g, d, k) for g, d, k in _claims(admin_engine)] == [(zzper_in_scope, DONDERDAG, "push")]
        audits = _run_audits(admin_engine)
        assert audits[-1]["gedaan"] == 1 and audits[-1]["verwacht"] == 1 and audits[-1]["datum"] == "2026-09-17"

    def test_voor_de_tijd_niets_en_geteld(self, kanaal, zzper_in_scope, admin_engine):
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1600)
        assert (rapport.administraties_tijd_bereikt, rapport.geen_tijd_bereikt, rapport.kandidaten) == (0, 1, 0)
        assert kanaal == [] and _claims(admin_engine) == []
        assert _run_audits(admin_engine)[-1]["geen_tijd_bereikt"] == 1

    def test_eigen_tijd_per_administratie_wint(self, kanaal, zzper_in_scope, admin_engine, administratie_id):
        _zet_tijd(admin_engine, administratie_id, time(15, 30))
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1600)  # 16:00 NL ≥ 15:30
        assert rapport.gedaan == 1 and len(kanaal) == 1

    def test_weekend_en_na_1900_niets(self, kanaal, zzper_in_scope, admin_engine):
        r1 = herinnering.verstuur_dag_einde_herinneringen(nu=ZATERDAG_1645)
        assert r1.werkdag is False and r1.kandidaten == 0
        r2 = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1915)
        assert r2.kandidaten == 0 and r2.geen_tijd_bereikt == -1
        assert kanaal == [] and _claims(admin_engine) == []
        assert len(_run_audits(admin_engine)) == 2  # elke run zichtbaar, ook een lege

    def test_al_uren_vandaag_op_welke_weekstaat_dan_ook_is_overgeslagen(
        self, kanaal, zzper_in_scope, administratie_id, project_id, admin_engine
    ):
        service.zet_dag(
            administratie_id=administratie_id, zzper_id=zzper_in_scope, project_id=project_id, jaar=JAAR,
            weeknummer=WEEK, datum=DONDERDAG, uren=Decimal("4"), actor_id=zzper_in_scope,
        )
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert (rapport.verwacht, rapport.gedaan, rapport.overgeslagen_al_uren) == (1, 0, 1)
        assert kanaal == [] and _claims(admin_engine) == []

    def test_nul_uren_regel_telt_niet_als_uren(self, kanaal, zzper_in_scope, administratie_id, project_id):
        service.zet_dag(
            administratie_id=administratie_id, zzper_id=zzper_in_scope, project_id=project_id, jaar=JAAR,
            weeknummer=WEEK, datum=DONDERDAG, uren=Decimal("0"), actor_id=zzper_in_scope,
        )
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert rapport.gedaan == 1 and len(kanaal) == 1

    def test_opt_out_per_gebruiker(self, kanaal, zzper_in_scope, admin_engine):
        service.zet_herinnering_uit(gebruiker_id=zzper_in_scope, uit=True)
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert (rapport.verwacht, rapport.gedaan, rapport.overgeslagen_opt_out) == (1, 0, 1)
        assert kanaal == []
        with admin_engine.begin() as conn:
            rij = conn.execute(
                text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = 'uren_herinnering_optout'")
            ).one()
        assert (rij[0], rij[1]) == ({"uit": False}, {"uit": True})

    def test_idempotent_tweede_run_zelfde_dag_stuurt_niet_dubbel(self, kanaal, zzper_in_scope, admin_engine):
        herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert (rapport.gedaan, rapport.overgeslagen_al_verzonden) == (0, 1)
        assert len(kanaal) == 1 and len(_claims(admin_engine)) == 1

    def test_detacheerder_krijgt_niets_uitvoerder_wel(
        self, kanaal, detacheerder, uitvoerder_in_scope, administratie_id, beheerder_id
    ):
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=detacheerder, administratie_id=administratie_id)
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert rapport.kandidaten == 1 and rapport.gedaan == 1
        assert [k["gebruiker_id"] for k in kanaal] == [uitvoerder_in_scope]

    def test_zonder_opt_in_geen_kandidaten(self, kanaal, zzper, administratie_zonder_opt_in, beheerder_id):
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_zonder_opt_in
        )
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert rapport.administraties_met_opt_in == 0 and rapport.kandidaten == 0 and kanaal == []

    def test_geen_kanaal_is_claim_en_teller_nooit_stil(self, monkeypatch, zzper_in_scope, admin_engine):
        def _geen(gebruiker, **kw):
            return verzending.VerzendUitkomst(HerinneringStatus.OVERGESLAGEN, None, {"reden": "geen kanaal"}, 0)

        monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _geen)
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert (rapport.gedaan, rapport.overgeslagen_geen_kanaal, rapport.is_fout) == (0, 1, False)
        assert [k for _g, _d, k in _claims(admin_engine)] == ["geen_kanaal"]
        # Tweede run in hetzelfde kwartier: niet opnieuw proberen (claim), morgen wél weer.
        rapport2 = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert rapport2.overgeslagen_al_verzonden == 1

    def test_verzendfout_is_mislukt_zonder_claim(self, monkeypatch, zzper_in_scope, admin_engine):
        def _boem(gebruiker, **kw):
            raise RuntimeError("smtp weg")

        monkeypatch.setattr(verzending, "verstuur_push_anders_mail", _boem)
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        assert rapport.mislukt == 1 and rapport.is_fout and "smtp weg" in rapport.fouten[0]
        assert _claims(admin_engine) == []  # volgende run herkanst

    def test_rapport_regel_en_reconciliatie_teller(self, kanaal, zzper_in_scope, admin_engine):
        rapport = herinnering.verstuur_dag_einde_herinneringen(nu=NU_1645)
        regel = herinnering.rapport_regel(rapport)
        assert "verwacht=1 gedaan=1" in regel and "al_uren=0" in regel
        aid = uuid.uuid4()
        feiten = auto.Feiten(administraties={aid: "X"})
        feiten.audit = [auto.AuditFeit("uren_herinnering_run", NU_1645, None, _run_audits(admin_engine)[-1])]
        tellers = auto.bereken(feiten, nu=datetime(2026, 9, 17, 18, 0, tzinfo=UTC))
        t = next(t for t in tellers if t.sleutel == auto.UREN_HERINNERING)
        assert (t.dag.verwacht, t.dag.gedaan) == (1, 1)
        assert auto.UREN_HERINNERING in auto.VOLGORDE and auto.LABEL[auto.UREN_HERINNERING]
        assert any("Uren-herinnering" in r for r in auto.regels(tellers))

    def test_reconciliatie_teller_geen_kanaal_is_harde_voorwaarde(self):
        aid = uuid.uuid4()
        feiten = auto.Feiten(administraties={aid: "X"})
        nw = {"datum": "2026-09-17", "gedaan": 2, "overgeslagen_al_uren": 3, "overgeslagen_opt_out": 1, "overgeslagen_geen_kanaal": 2}
        feiten.audit = [auto.AuditFeit("uren_herinnering_run", NU_1645, None, nw)]
        t = next(
            t for t in auto.bereken(feiten, nu=datetime(2026, 9, 17, 18, 0, tzinfo=UTC)) if t.sleutel == auto.UREN_HERINNERING
        )
        assert t.dag.gedaan == 2 and t.dag.overgeslagen[auto.AL_UREN] == 3 and t.dag.overgeslagen[auto.GEEN_KANAAL] == 2
        assert t.dag.verwacht == 8
        assert [h.categorie for h in t.harde_voorwaarden] == [auto.GEEN_KANAAL]
        assert t.harde_voorwaarden[0].doel_pad == "/veldwerkers" or t.harde_voorwaarden[0].doel_pad is None


class TestRoutes:
    def test_eigen_opt_out_get_put_en_default_tijd(self, zzper_in_scope, administratie_id, admin_engine):
        h = _bearer(zzper_in_scope, rol="zzper")
        r = client.get("/uren/zzp/herinnering", headers=h)
        assert r.status_code == 200 and r.json() == {"uit": False, "tijd": "16:30"}
        _zet_tijd(admin_engine, administratie_id, time(17, 0))
        r = client.put("/uren/zzp/herinnering", json={"uit": True}, headers=h)
        assert r.status_code == 200 and r.json() == {"uit": True, "tijd": "17:00"}
        assert client.get("/uren/zzp/herinnering", headers=h).json()["uit"] is True

    def test_kantoorrol_mag_niet_op_de_veldroute(self, beheerder_id):
        r = client.get("/uren/zzp/herinnering", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 403

    def test_beheerder_zet_tijd_en_wist_hem(self, beheerder_id, administratie_id, admin_engine):
        h = _bearer(beheerder_id, rol="beheerder")
        r = client.get(f"/uren/beheer/herinnering-tijd/{administratie_id}", headers=h)
        assert r.json() == {"tijd": "16:30", "standaard": True}
        r = client.put(f"/uren/beheer/herinnering-tijd/{administratie_id}", json={"tijd": "15:45"}, headers=h)
        assert r.status_code == 200 and r.json() == {"tijd": "15:45", "standaard": False}
        assert client.put(f"/uren/beheer/herinnering-tijd/{administratie_id}", json={"tijd": "19:30"}, headers=h).status_code == 422
        assert client.put(f"/uren/beheer/herinnering-tijd/{administratie_id}", json={"tijd": "x"}, headers=h).status_code == 422
        r = client.put(f"/uren/beheer/herinnering-tijd/{administratie_id}", json={"tijd": None}, headers=h)
        assert r.json() == {"tijd": "16:30", "standaard": True}
        with admin_engine.begin() as conn:
            rijen = conn.execute(
                text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = 'uren_herinnering_tijd_gewijzigd' ORDER BY tijdstip")
            ).all()
        assert [(a["tijd"], b["tijd"]) for a, b in rijen] == [(None, "15:45"), ("15:45", None)]

    def test_tijd_zetten_is_beheerder_only_en_vereist_opt_in(self, zzper_in_scope, beheerder_id, administratie_zonder_opt_in):
        assert (
            client.put(
                f"/uren/beheer/herinnering-tijd/{uuid.uuid4()}", json={"tijd": "15:00"}, headers=_bearer(zzper_in_scope, rol="zzper")
            ).status_code
            == 403
        )
        r = client.get(f"/uren/beheer/herinnering-tijd/{administratie_zonder_opt_in}", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 409

    def test_409_op_bevroren_week_draagt_code_status_en_server_regel(
        self, zzper_in_scope, uitvoerder_in_scope, administratie_id, project_id
    ):
        service.zet_dag(
            administratie_id=administratie_id, zzper_id=zzper_in_scope, project_id=project_id, jaar=JAAR,
            weeknummer=WEEK, datum=DONDERDAG, uren=Decimal("8"), m2=Decimal("40"), opmerking="opbouwen",
            actor_id=zzper_in_scope,
        )
        service.dien_week_in(
            administratie_id=administratie_id, zzper_id=zzper_in_scope, project_id=project_id, jaar=JAAR,
            weeknummer=WEEK, actor_id=zzper_in_scope,
        )
        r = client.put(
            "/uren/zzp/dag",
            json={
                "administratie_id": str(administratie_id), "project_id": str(project_id), "jaar": JAAR,
                "weeknummer": WEEK, "datum": DONDERDAG.isoformat(), "uren": "6",
            },
            headers=_bearer(zzper_in_scope, rol="zzper"),
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "weekstaat_bevroren" and body["status"] == "ingediend"
        assert body["server_regel"] == {"uren": "8.00", "m2": "40.00", "opmerking": "opbouwen", "doorfactureren": False}
        assert "ingediend" in body["detail"]
