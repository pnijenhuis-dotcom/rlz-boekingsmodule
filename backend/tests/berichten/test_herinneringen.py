"""Selectielogica + idempotentie van de dagelijkse accordeur-herinnering (berichten-bouwsteen):
wie krijgt wat wanneer, >0-drempel, idempotent per dag, mislukt-retry, bezig-blijver nooit
dubbel, kanaalkeuze push→e-mail, vervallen subscripties, volumerem, kill-switch."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import Engine, text

from app.auth import webauthn_service
from app.berichten import herinneringen, mail, push
from app.berichten import service as berichten_service
from app.berichten.models import PushSubscriptie
from app.config import settings
from app.db.session import scoped_session
from tests.berichten.conftest import maak_apparaat

VANDAAG = date(2026, 8, 15)


@pytest.fixture
def mail_log(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def _fake(*, naar: str, onderwerp: str, tekst: str) -> None:
        verzonden.append({"naar": naar, "onderwerp": onderwerp, "tekst": tekst})

    monkeypatch.setattr(mail, "verzend_mail", _fake)
    return verzonden


@pytest.fixture
def push_log(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []
    monkeypatch.setattr(push, "is_geconfigureerd", lambda soort="webpush": True)

    def _fake(subscriptie: PushSubscriptie, *, payload: dict) -> None:
        verzonden.append({"endpoint": subscriptie.endpoint, "payload": payload})

    monkeypatch.setattr(push, "verzend_push", _fake)
    return verzonden


def maak_subscriptie(gebruiker_id: uuid.UUID, apparaat_id: uuid.UUID, endpoint: str) -> uuid.UUID:
    data = berichten_service.registreer_subscriptie(
        gebruiker_id=gebruiker_id, apparaat_id=apparaat_id, endpoint=endpoint, p256dh="p", auth="a"
    )
    return data.id


def dagrij(admin_engine: Engine, gebruiker_id: uuid.UUID) -> dict | None:
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT status, kanaal, aantal_open FROM platform.accordeur_herinnering "
                "WHERE gebruiker_id = :gid AND datum = :datum"
            ),
            {"gid": gebruiker_id, "datum": VANDAAG},
        ).first()
    return None if rij is None else {"status": rij[0], "kanaal": rij[1], "aantal_open": rij[2]}


class TestTeksten:
    def test_meervoud_en_link(self) -> None:
        onderwerp, pushtekst, mailtekst = herinneringen.bericht_teksten(3)
        assert pushtekst == "Goedemorgen! Er wachten nog 3 facturen op je akkoord."
        assert "3 facturen" in onderwerp
        assert f"{settings.app_basis_url.rstrip('/')}/accordeur" in mailtekst

    def test_enkelvoud(self) -> None:
        _, pushtekst, _ = herinneringen.bericht_teksten(1)
        assert pushtekst == "Goedemorgen! Er wacht nog 1 factuur op je akkoord."


class TestSelectie:
    def test_geen_open_werk_geen_bericht(
        self, accordeur_1: uuid.UUID, mail_log: list[dict], admin_engine: Engine
    ) -> None:
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert mail_log == []
        assert rapport.geen_open_werk >= 1
        assert not rapport.is_fout
        assert dagrij(admin_engine, accordeur_1) is None

    def test_open_werk_stuurt_mail_met_aantal_en_link(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        mail_log: list[dict],
        admin_engine: Engine,
    ) -> None:
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert rapport.verzonden_mail == 1 and rapport.verzonden_push == 0
        assert len(mail_log) == 1
        assert "1 factuur" in mail_log[0]["tekst"] and "/accordeur" in mail_log[0]["tekst"]
        assert dagrij(admin_engine, accordeur_1) == {"status": "verzonden", "kanaal": "e-mail", "aantal_open": 1}
        # accordeur_2 is niet aan de beurt (laag 1 is van accordeur_1) -> níéts
        assert dagrij(admin_engine, accordeur_2) is None

    def test_idempotent_per_dag(
        self, ter_accordering_bij_1: uuid.UUID, accordeur_1: uuid.UUID, mail_log: list[dict]
    ) -> None:
        eerste = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        tweede = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert eerste.verzonden_mail == 1
        assert tweede.verzonden_mail == 0 and tweede.al_verzonden == 1
        assert len(mail_log) == 1
        assert not tweede.is_fout

    def test_mislukt_wordt_bij_volgende_run_opnieuw_geprobeerd(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _faal(**kwargs: object) -> None:
            raise mail.MailVerzendFout("SMTP down")

        monkeypatch.setattr(mail, "verzend_mail", _faal)
        eerste = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert eerste.mislukt == 1 and eerste.is_fout
        assert dagrij(admin_engine, accordeur_1)["status"] == "mislukt"

        verzonden: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
        tweede = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert tweede.verzonden_mail == 1 and len(verzonden) == 1
        assert dagrij(admin_engine, accordeur_1)["status"] == "verzonden"

    def test_bezig_blijver_wordt_nooit_dubbel_gestuurd(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        mail_log: list[dict],
        admin_engine: Engine,
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.accordeur_herinnering (id, gebruiker_id, datum, aantal_open, status) "
                    "VALUES (:id, :gid, :datum, 1, 'bezig')"
                ),
                {"id": uuid.uuid4(), "gid": accordeur_1, "datum": VANDAAG},
            )
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert mail_log == []
        assert rapport.onafgemaakt == 1 and rapport.is_fout

    def test_volumerem_stopt_zichtbaar(
        self,
        ter_accordering_bij_1: uuid.UUID,
        mail_log: list[dict],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "herinnering_max_berichten_per_run", 0)
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert mail_log == []
        assert rapport.volumerem_bereikt and rapport.is_fout


class TestKanaalkeuze:
    def test_push_boven_mail(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        mail_log: list[dict],
        push_log: list[dict],
    ) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        maak_subscriptie(accordeur_1, apparaat, "https://push.example/abc")
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert rapport.verzonden_push == 1 and rapport.verzonden_mail == 0
        assert mail_log == []
        assert push_log[0]["payload"]["url"] == "/accordeur" and push_log[0]["payload"]["aantal"] == 1
        assert dagrij(admin_engine, accordeur_1)["kanaal"] == "push"

    def test_vervallen_subscriptie_gemarkeerd_en_mail_terugval(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        mail_log: list[dict],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        subscriptie_id = maak_subscriptie(accordeur_1, apparaat, "https://push.example/dood")
        monkeypatch.setattr(push, "is_geconfigureerd", lambda soort="webpush": True)

        def _vervallen(subscriptie: PushSubscriptie, *, payload: dict) -> None:
            raise push.PushSubscriptieVervallen("410")

        monkeypatch.setattr(push, "verzend_push", _vervallen)
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert rapport.verzonden_mail == 1 and rapport.subscripties_vervallen == 1
        assert len(mail_log) == 1
        with scoped_session(None) as session:
            rij = session.get(PushSubscriptie, subscriptie_id)
            assert rij.ingetrokken_op is not None and rij.ingetrokken_reden == "vervallen"

    def test_kill_switch_apparaat_stopt_push(
        self,
        ter_accordering_bij_1: uuid.UUID,
        accordeur_1: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        mail_log: list[dict],
        push_log: list[dict],
    ) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        subscriptie_id = maak_subscriptie(accordeur_1, apparaat, "https://push.example/killed")
        webauthn_service.trek_apparaat_in(actor_id=beheerder_id, apparaat_id=apparaat)
        with scoped_session(None) as session:
            rij = session.get(PushSubscriptie, subscriptie_id)
            assert rij.ingetrokken_op is not None and rij.ingetrokken_reden == "kill_switch"
        rapport = herinneringen.verstuur_dagelijkse_herinneringen(vandaag=VANDAAG)
        assert push_log == []
        assert rapport.verzonden_mail == 1 and len(mail_log) == 1
