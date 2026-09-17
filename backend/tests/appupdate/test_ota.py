# ruff: noqa: F811 — pytest-fixtures als parameters
"""OTA (Peter 16-09, migratie 0152): manifest geeft nooit een bundel van een andere runtime/platform, kill-switch (env én
DB), cohort deterministisch, verplicht reist mee, bundel-download + sha256, rollback-melding = audit `ota_rollback`,
toestelstand per request (X-App-Versie/X-Bundel-Id), 426-poort voor te oude aangekondigde schillen mét store-link (niet
voor kantoor-web, niet zonder aankondiging, niet op /health en het manifest), Beheerder-routes, CLI registreren."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import cli
from app.appupdate import service
from app.config import settings
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.auth.test_app_activatie import SLOT, _geactiveerd

client = TestClient(app)
SHA = hashlib.sha256(b"bundel").hexdigest()


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _reg(bundel_id: str, runtime: str = "1.1", platform: str = "alle", **kw):  # noqa: ANN003
    return service.registreer_bundel(bundel_id=bundel_id, runtime=runtime, pad=f"bundels/{runtime}/{bundel_id}.zip", sha256=SHA, bytes_=1234, platform=platform, **kw)


def _ouder(bundel_id: str, minuten: int, admin_engine) -> None:  # noqa: ANN001
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.app_bundel SET aangemaakt_op = now() - make_interval(mins => :m) WHERE bundel_id = :b"), {"m": minuten, "b": bundel_id})


class TestManifest:
    def test_alleen_bundels_van_de_eigen_runtime_en_platform(self, admin_engine) -> None:  # noqa: ANN001
        _reg("b-11-oud", "1.1"); _ouder("b-11-oud", 10, admin_engine)
        _reg("b-11-nieuw", "1.1")
        _reg("b-12", "1.2")
        _reg("b-11-android", "1.1", platform="android")
        m = service.manifest(runtime="1.1", platform="ios", huidig="builtin")
        assert not m.geen_update and m.bundel_id == "b-11-nieuw" and m.runtime == "1.1" and m.sha256 == SHA
        assert m.url.endswith("/app/bundels/b-11-nieuw.zip") and m.verplicht is False
        # android: de platform-specifieke bundel is nieuwer → die wint; nooit b-12
        ma = service.manifest(runtime="1.1", platform="android", huidig=None)
        assert ma.bundel_id == "b-11-android"
        assert service.manifest(runtime="1.3", platform="ios", huidig=None).reden == "geen bundel voor deze runtime"
        assert service.manifest(runtime="1.1", platform="ios", huidig="b-11-nieuw").reden == "actueel"
        assert service.manifest(runtime="abc", platform="ios", huidig=None).reden == "runtime onbekend"
        assert service.manifest(runtime="1.1", platform="web", huidig=None).reden == "platform onbekend"

    def test_kill_switch_env_en_db(self, monkeypatch, beheerder_id) -> None:  # noqa: ANN001
        _reg("b-1", "1.1")
        monkeypatch.setattr(settings, "ota_uitgeschakeld", True)
        assert service.manifest(runtime="1.1", platform="ios", huidig=None).reden == "uitgeschakeld"
        monkeypatch.setattr(settings, "ota_uitgeschakeld", False)
        assert not service.manifest(runtime="1.1", platform="ios", huidig=None).geen_update
        service.zet_instelling(actor_id=beheerder_id, uitgeschakeld=True)
        assert service.manifest(runtime="1.1", platform="ios", huidig=None).reden == "uitgeschakeld"
        with scoped_session(None) as s:
            assert s.scalar(select(AuditEvent).where(AuditEvent.actie == "app_update_instelling_gewijzigd")) is not None

    def test_cohort_deterministisch_en_verplicht(self, beheerder_id) -> None:  # noqa: ANN001
        _reg("b-v", "1.1", verplicht=True)
        service.zet_instelling(actor_id=beheerder_id, percentage=50)
        binnen = [t for t in (f"toestel-{i}" for i in range(40)) if service.in_cohort(t, 50)]
        assert 5 < len(binnen) < 35
        m1 = service.manifest(runtime="1.1", platform="ios", huidig=None, toestel=binnen[0])
        m2 = service.manifest(runtime="1.1", platform="ios", huidig=None, toestel=binnen[0])
        assert not m1.geen_update and m1.verplicht is True and m1 == m2
        buiten = next(t for t in (f"toestel-{i}" for i in range(40)) if not service.in_cohort(t, 50))
        assert service.manifest(runtime="1.1", platform="ios", huidig=None, toestel=buiten).reden.startswith("buiten cohort")
        assert service.in_cohort("x", 100) and not service.in_cohort("x", 0)
        with pytest.raises(service.AppUpdateFout):
            service.zet_instelling(actor_id=beheerder_id, percentage=101)

    def test_registreren_idempotent_en_terugtrekken(self, beheerder_id) -> None:  # noqa: ANN001
        a = _reg("b-x", "1.1")
        b = _reg("b-x", "1.1")
        assert a.id == b.id
        service.zet_bundel_actief(bundel_id="b-x", actief=False, actor_id=beheerder_id)
        assert service.manifest(runtime="1.1", platform="ios", huidig=None).reden == "geen bundel voor deze runtime"
        with pytest.raises(service.AppUpdateFout):
            _reg("b-y", "1.1", platform="windows")
        with pytest.raises(service.AppUpdateFout):
            service.registreer_bundel(bundel_id="b-z", runtime="1.1", pad="p", sha256="kort", bytes_=1)

    def test_manifest_route_en_bundel_download(self, tmp_path, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setattr(settings, "app_bundel_opslag_basismap", str(tmp_path))
        inhoud = b"PK\x03\x04zipje"
        (tmp_path / "bundels" / "1.1").mkdir(parents=True)
        (tmp_path / "bundels" / "1.1" / "b-dl.zip").write_bytes(inhoud)
        service.registreer_bundel(bundel_id="b-dl", runtime="1.1", pad="bundels/1.1/b-dl.zip", sha256=hashlib.sha256(inhoud).hexdigest(), bytes_=len(inhoud))
        r = client.get("/app/update-manifest", params={"runtime": "1.1", "platform": "ios", "huidig": "builtin"})
        assert r.status_code == 200 and r.json()["bundel_id"] == "b-dl" and r.json()["url"].endswith("/app/bundels/b-dl.zip")
        d = client.get("/app/bundels/b-dl.zip")
        assert d.status_code == 200 and d.content == inhoud and d.headers["x-bundel-sha256"] == hashlib.sha256(inhoud).hexdigest()
        assert client.get("/app/bundels/onbekend.zip").status_code == 404
        assert client.get("/app/update-manifest", params={"runtime": "9.9", "platform": "ios"}).json()["geen_update"] is True
        # Nameting 17-09: achter de Cloud Run-proxy gaf het manifest `http://…` (base_url volgt de proxy-hop) — de
        # downloadlink volgt X-Forwarded-Proto, anders weigert iOS (ATS) de zip en blijft de OTA stil uit.
        r2 = client.get("/app/update-manifest", params={"runtime": "1.1", "platform": "ios"}, headers={"X-Forwarded-Proto": "https"})
        assert r2.json()["url"].startswith("https://") and r2.json()["url"].endswith("/app/bundels/b-dl.zip")
        assert r.json()["url"].startswith("http://")  # zonder header: het schema van de request zelf


class TestToestel:
    def test_rollback_melding_is_audit_en_toestelstand_per_request(self, beheerder_id, admin_engine) -> None:  # noqa: ANN001
        app_info, sessie = _geactiveerd(beheerder_id)
        h = {"Authorization": f"Bearer {sessie['access_token']}", **SLOT, "X-App-Versie": "1.2", "X-Bundel-Id": "b-abc"}
        r = client.post("/app/update-melding", headers=h, json={"bundel_id": "b-kapot", "reden": "notifyAppReady niet binnen 10 s", "app_versie": "1.2"})
        assert r.status_code == 204, r.text
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as s:
            ev = s.scalar(select(AuditEvent).where(AuditEvent.actie == "ota_rollback"))
            assert ev is not None and ev.nieuwe_waarde["bundel_id"] == "b-kapot"
        with admin_engine.begin() as conn:
            rij = conn.execute(text("SELECT app_versie, bundel_id, bundel_gezien_op FROM platform.webauthn_credential WHERE gebruiker_id = :g AND soort = 'toestel'"), {"g": uuid.UUID(app_info["gebruiker_id"])}).first()
        assert rij[0] == "1.2" and rij[1] == "b-abc" and rij[2] is not None
        lijst = client.get("/instellingen/app-updates/toestellen", headers=_bearer(beheerder_id)).json()
        assert lijst and lijst[0]["bundel_id"] == "b-abc" and lijst[0]["app_versie"] == "1.2"


class TestMinimumVersiePoort:
    def test_te_oude_schil_krijgt_426_met_store_link(self, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setattr(settings, "app_min_runtime_versie", "1.2")
        monkeypatch.setattr(settings, "store_link_ios", "https://apps.apple.com/app/x")
        r = client.get("/accordering/wachtrij", headers={"X-Native-Client": "1", "X-App-Versie": "1.1", "X-App-Platform": "ios"})
        assert r.status_code == 426
        body = r.json()
        assert body["code"] == "app_update_nodig" and body["min_versie"] == "1.2" and body["store_url"] == "https://apps.apple.com/app/x"
        # nieuw genoeg → geen 426 (401 door ontbrekend token — de poort ligt vóór de auth)
        assert client.get("/accordering/wachtrij", headers={"X-Native-Client": "1", "X-App-Versie": "1.2"}).status_code == 401
        # zonder aankondiging (oude schil ≤ 1.1 build 140) en kantoor-web zonder X-Native-Client: nooit 426
        assert client.get("/accordering/wachtrij", headers={"X-Native-Client": "1"}).status_code == 401
        assert client.get("/accordering/wachtrij", headers={"X-App-Versie": "0.1"}).status_code == 401
        # het manifest en /health blijven bereikbaar voor een te oude schil (die kan dan wél zijn winkelroute zien)
        assert client.get("/health", headers={"X-Native-Client": "1", "X-App-Versie": "1.1"}).status_code == 200
        assert client.get("/app/update-manifest", params={"runtime": "1.1", "platform": "ios"}, headers={"X-Native-Client": "1", "X-App-Versie": "1.1"}).status_code == 200
        assert service.schil_te_oud("rommel") is False and service.schil_te_oud("1.1", minimum="1.1") is False


class TestBeheer:
    def test_instelling_routes_beheerder_only(self, beheerder_id, admin_engine) -> None:  # noqa: ANN001
        r = client.get("/instellingen/app-updates", headers=_bearer(beheerder_id))
        assert r.status_code == 200 and r.json() == {"percentage": 100, "uitgeschakeld": False, "env_uitgeschakeld": False, "min_runtime_versie": settings.app_min_runtime_versie}
        r = client.put("/instellingen/app-updates", headers=_bearer(beheerder_id), json={"percentage": 25, "uitgeschakeld": True})
        assert r.status_code == 200 and r.json()["percentage"] == 25 and r.json()["uitgeschakeld"] is True
        _reg("b-lijst", "1.1")
        lijst = client.get("/instellingen/app-updates/bundels", headers=_bearer(beheerder_id)).json()
        assert lijst[0]["bundel_id"] == "b-lijst" and lijst[0]["actief"] is True
        r = client.put("/instellingen/app-updates/bundels/b-lijst", headers=_bearer(beheerder_id), json={"actief": False})
        assert r.status_code == 200 and r.json()["actief"] is False
        assert client.put("/instellingen/app-updates/bundels/nope", headers=_bearer(beheerder_id), json={"actief": True}).status_code == 404
        # niet-Beheerder: 403
        boekhouder = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(text("INSERT INTO platform.gebruiker (id, e_mail, naam, rol, status) VALUES (:id, 'b@x.nl', 'B', 'boekhouding', 'actief')"), {"id": boekhouder})
        assert client.get("/instellingen/app-updates", headers=_bearer(boekhouder, rol="boekhouding")).status_code == 403


class TestCli:
    def test_registreren_en_lijst(self, capsys) -> None:  # noqa: ANN001
        assert cli.main(["app-bundel-registreren", "--runtime", "1.1", "--bundel-id", "b-cli", "--pad", "bundels/1.1/b-cli.zip", "--sha256", SHA, "--bytes", "99", "--verplicht"]) == 0
        assert cli.main(["app-bundels", "--runtime", "1.1"]) == 0
        uit = capsys.readouterr().out
        assert "GEREGISTREERD bundel=b-cli" in uit and "VERPLICHT" in uit
        assert cli.main(["app-bundel-registreren", "--runtime", "x", "--bundel-id", "b", "--pad", "p", "--sha256", SHA, "--bytes", "1"]) == 2
