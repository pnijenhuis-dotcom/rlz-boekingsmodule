"""Native push (store-apps fase 3, migratie 0055): subscriptie-soorten (webpush | apns | fcm),
de soort/sleutel-validatie, kill-switch over native subscripties, de adapterdispatch in
push.py en de reason-mapping van de APNs-/FCM-adapters (vervallen ≠ fout)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import Engine

from app.berichten import apns, fcm, push, verzending
from app.berichten import service as berichten_service
from app.berichten.models import HerinneringKanaal, HerinneringStatus, PushSoort, PushSubscriptie
from app.config import settings
from app.db.session import scoped_session
from tests.berichten.conftest import maak_apparaat


def _p8_testsleutel() -> str:
    """Wegwerp-EC-sleutel (P-256) — alleen om pyjwt een geldige ES256-signing te laten doen."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    sleutel = ec.generate_private_key(ec.SECP256R1())
    return sleutel.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class StubAntwoord:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("geen JSON")
        return self._body


class TestSubscriptieSoorten:
    def test_native_subscriptie_zonder_sleutels_ok(self, accordeur_1: uuid.UUID, admin_engine: Engine) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        data = berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1,
            apparaat_id=apparaat,
            endpoint="apns-token-123",
            p256dh=None,
            auth=None,
            soort="apns",
        )
        with scoped_session(None) as session:
            rij = session.get(PushSubscriptie, data.id)
            assert rij.soort == "apns" and rij.p256dh is None and rij.auth is None

    def test_native_met_sleutels_geweigerd(self, accordeur_1: uuid.UUID, admin_engine: Engine) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        with pytest.raises(berichten_service.OngeldigeSubscriptie):
            berichten_service.registreer_subscriptie(
                gebruiker_id=accordeur_1,
                apparaat_id=apparaat,
                endpoint="fcm-token-x",
                p256dh="p",
                auth="a",
                soort="fcm",
            )

    def test_webpush_zonder_sleutels_geweigerd(self, accordeur_1: uuid.UUID, admin_engine: Engine) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        with pytest.raises(berichten_service.OngeldigeSubscriptie):
            berichten_service.registreer_subscriptie(
                gebruiker_id=accordeur_1,
                apparaat_id=apparaat,
                endpoint="https://p/x",
                p256dh=None,
                auth=None,
            )

    def test_onbekende_soort_geweigerd(self, accordeur_1: uuid.UUID, admin_engine: Engine) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        with pytest.raises(berichten_service.OngeldigeSubscriptie):
            berichten_service.registreer_subscriptie(
                gebruiker_id=accordeur_1,
                apparaat_id=apparaat,
                endpoint="t",
                p256dh=None,
                auth=None,
                soort="sms",
            )

    def test_kill_switch_trekt_native_subscriptie_mee_in(
        self, accordeur_1: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """De harde eis uit de opdracht: de kill-switch trekt web én native in — native rijen
        hangen aan dezelfde apparaat-binding, dus trek_apparaat_in raakt ze identiek."""
        from app.auth import webauthn_service

        apparaat = maak_apparaat(admin_engine, accordeur_1)
        data = berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1,
            apparaat_id=apparaat,
            endpoint="apns-token-kill",
            p256dh=None,
            auth=None,
            soort="apns",
        )
        webauthn_service.trek_apparaat_in(actor_id=beheerder_id, apparaat_id=apparaat)
        with scoped_session(None) as session:
            rij = session.get(PushSubscriptie, data.id)
            assert rij.ingetrokken_op is not None and rij.ingetrokken_reden == "kill_switch"
        assert verzending.actieve_subscripties(accordeur_1) == []


class TestAdapterDispatch:
    def _subscriptie(self, soort: str, endpoint: str = "token-1") -> PushSubscriptie:
        return PushSubscriptie(
            gebruiker_id=uuid.uuid4(), apparaat_id=uuid.uuid4(), soort=soort, endpoint=endpoint
        )

    def test_apns_soort_gaat_naar_de_apns_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aangeroepen: dict = {}

        def fake_verzend(token: str, *, titel: str, tekst: str, url: str) -> None:
            aangeroepen.update({"token": token, "titel": titel, "tekst": tekst, "url": url})

        monkeypatch.setattr(apns, "verzend_apns", fake_verzend)
        push.verzend_push(
            self._subscriptie("apns"), payload={"titel": "RLZ", "tekst": "1 factuur", "url": "/accordeur"}
        )
        assert aangeroepen == {"token": "token-1", "titel": "RLZ", "tekst": "1 factuur", "url": "/accordeur"}

    def test_vervallen_token_wordt_uniforme_vervallen_fout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def weiger(token: str, *, titel: str, tekst: str, url: str) -> None:
            raise apns.ApnsTokenVervallen("410")

        monkeypatch.setattr(apns, "verzend_apns", weiger)
        with pytest.raises(push.PushSubscriptieVervallen):
            push.verzend_push(self._subscriptie("apns"), payload={"tekst": "x", "url": "/accordeur"})

    def test_fcm_soort_gaat_naar_de_fcm_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aangeroepen: dict = {}
        monkeypatch.setattr(
            fcm, "verzend_fcm", lambda token, *, titel, tekst, url: aangeroepen.update({"token": token})
        )
        push.verzend_push(self._subscriptie("fcm", "fcm-tok"), payload={"tekst": "x", "url": "/accordeur"})
        assert aangeroepen == {"token": "fcm-tok"}

    def test_is_geconfigureerd_per_soort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert push.is_geconfigureerd(PushSoort.WEBPUSH.value) is False  # geen VAPID in testconfig
        assert push.is_geconfigureerd("apns") is False
        assert push.is_geconfigureerd("fcm") is False
        monkeypatch.setattr(settings, "fcm_service_account_json", "{}")
        assert push.is_geconfigureerd("fcm") is True


class TestApnsAdapter:
    def _configureer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "apns_key_p8", _p8_testsleutel())
        monkeypatch.setattr(settings, "apns_key_id", "SLEUTEL1")
        monkeypatch.setattr(settings, "apple_team_id", "TEAM12345")
        monkeypatch.setattr(apns, "_jwt_cache", None)

    def _stub_client(self, monkeypatch: pytest.MonkeyPatch, antwoord: StubAntwoord) -> dict:
        import httpx

        gezien: dict = {}

        class FakeClient:
            def __init__(self, **kwargs) -> None:
                gezien["client_kwargs"] = kwargs

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *args) -> None:
                return None

            def post(self, url: str, *, content: str, headers: dict) -> StubAntwoord:
                gezien.update({"url": url, "payload": json.loads(content), "headers": headers})
                return antwoord

        monkeypatch.setattr(httpx, "Client", FakeClient)
        return gezien

    def test_niet_geconfigureerd_fail_closed(self) -> None:
        with pytest.raises(apns.ApnsNietGeconfigureerd):
            apns.verzend_apns("tok", titel="t", tekst="x", url="/accordeur")

    def test_verzendt_alert_met_topic_en_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._configureer(monkeypatch)
        gezien = self._stub_client(monkeypatch, StubAntwoord(200))
        apns.verzend_apns("device-tok", titel="RLZ Goedkeuren", tekst="1 factuur", url="/accordeur?document=d1")
        assert gezien["url"].endswith("/3/device/device-tok")
        assert gezien["url"].startswith("https://api.push.apple.com")  # productie, geen sandbox
        assert gezien["headers"]["apns-topic"] == "nl.aknijenhuis.goedkeuren"
        assert gezien["headers"]["authorization"].startswith("bearer ")
        assert gezien["payload"]["aps"]["alert"] == {"title": "RLZ Goedkeuren", "body": "1 factuur"}
        assert gezien["payload"]["url"] == "/accordeur?document=d1"

    def test_bad_device_token_is_vervallen_geen_fout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._configureer(monkeypatch)
        self._stub_client(monkeypatch, StubAntwoord(400, {"reason": "BadDeviceToken"}))
        with pytest.raises(apns.ApnsTokenVervallen):
            apns.verzend_apns("dood", titel="t", tekst="x", url="/accordeur")

    def test_andere_weigering_is_zichtbare_fout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._configureer(monkeypatch)
        self._stub_client(monkeypatch, StubAntwoord(403, {"reason": "InvalidProviderToken"}))
        with pytest.raises(apns.ApnsFout):
            apns.verzend_apns("tok", titel="t", tekst="x", url="/accordeur")


class TestFcmAdapter:
    def test_niet_geconfigureerd_fail_closed(self) -> None:
        with pytest.raises(fcm.FcmNietGeconfigureerd):
            fcm.verzend_fcm("tok", titel="t", tekst="x", url="/accordeur")

    def _configureer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "fcm_service_account_json", '{"project_id": "rlz-test"}')
        monkeypatch.setattr(fcm, "_access_token", lambda: ("oauth-tok", "rlz-test"))

    def test_verzendt_v1_bericht(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        self._configureer(monkeypatch)
        gezien: dict = {}

        def fake_post(url: str, *, json: dict, headers: dict, timeout: int) -> StubAntwoord:
            gezien.update({"url": url, "json": json, "headers": headers})
            return StubAntwoord(200, {})

        monkeypatch.setattr(httpx, "post", fake_post)
        fcm.verzend_fcm("reg-tok", titel="RLZ", tekst="2 facturen", url="/accordeur")
        assert gezien["url"] == "https://fcm.googleapis.com/v1/projects/rlz-test/messages:send"
        assert gezien["json"]["message"]["token"] == "reg-tok"
        assert gezien["json"]["message"]["data"] == {"url": "/accordeur"}
        assert gezien["headers"]["authorization"] == "Bearer oauth-tok"

    def test_unregistered_is_vervallen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        self._configureer(monkeypatch)
        monkeypatch.setattr(
            httpx,
            "post",
            lambda url, *, json, headers, timeout: StubAntwoord(
                404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}
            ),
        )
        with pytest.raises(fcm.FcmTokenVervallen):
            fcm.verzend_fcm("dood", titel="t", tekst="x", url="/accordeur")


class TestVerzendingMetNativeSubscriptie:
    def test_native_push_gelukt_geen_mail(
        self, accordeur_1: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1,
            apparaat_id=apparaat,
            endpoint="apns-tok-a",
            p256dh=None,
            auth=None,
            soort="apns",
        )
        monkeypatch.setattr(apns, "is_geconfigureerd", lambda: True)
        monkeypatch.setattr(apns, "verzend_apns", lambda token, *, titel, tekst, url: None)
        with scoped_session(None) as session:
            from app.db.models import Gebruiker

            gebruiker = session.get(Gebruiker, accordeur_1)
            session.expunge(gebruiker)
        uitkomst = verzending.verstuur_push_anders_mail(
            gebruiker, onderwerp="o", pushtekst="p", mailtekst="m", url="/accordeur"
        )
        assert uitkomst.status == HerinneringStatus.VERZONDEN
        assert uitkomst.kanaal == HerinneringKanaal.PUSH

    def test_vervallen_native_token_wordt_ingetrokken_en_mail_terugval(
        self, accordeur_1: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.berichten import mail

        apparaat = maak_apparaat(admin_engine, accordeur_1)
        data = berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1,
            apparaat_id=apparaat,
            endpoint="apns-tok-dood",
            p256dh=None,
            auth=None,
            soort="apns",
        )
        monkeypatch.setattr(apns, "is_geconfigureerd", lambda: True)

        def weiger(token: str, *, titel: str, tekst: str, url: str) -> None:
            raise apns.ApnsTokenVervallen("410")

        monkeypatch.setattr(apns, "verzend_apns", weiger)
        gemaild: list[str] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda *, naar, onderwerp, tekst: gemaild.append(naar))
        with scoped_session(None) as session:
            from app.db.models import Gebruiker

            gebruiker = session.get(Gebruiker, accordeur_1)
            session.expunge(gebruiker)
        uitkomst = verzending.verstuur_push_anders_mail(
            gebruiker, onderwerp="o", pushtekst="p", mailtekst="m", url="/accordeur"
        )
        assert uitkomst.status == HerinneringStatus.VERZONDEN
        assert uitkomst.kanaal == HerinneringKanaal.E_MAIL
        assert uitkomst.subscripties_vervallen == 1
        assert gemaild
        with scoped_session(None) as session:
            rij = session.get(PushSubscriptie, data.id)
            assert rij.ingetrokken_op is not None and rij.ingetrokken_reden == "vervallen"
