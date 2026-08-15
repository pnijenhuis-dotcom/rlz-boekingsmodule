"""Mailkanaal (fail-zichtbaar) + push-subscriptie-beheer (apparaatbinding, upsert, intrekken)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine

from app.berichten import mail
from app.berichten import service as berichten_service
from app.berichten.models import PushSubscriptie
from app.berichten.uitnodigingsmail import activeerlink
from app.config import settings
from app.db.session import scoped_session
from tests.berichten.conftest import maak_apparaat


class TestMailKanaal:
    def test_niet_geconfigureerd_faalt_zichtbaar(self) -> None:
        assert not mail.is_geconfigureerd()
        with pytest.raises(mail.MailNietGeconfigureerd):
            mail.verzend_mail(naar="x@test.local", onderwerp="t", tekst="t")

    def test_bericht_bouw(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "berichten_smtp_gebruiker", "berichten@ak-nijenhuis.nl")
        bericht = mail.bouw_bericht(naar="a@test.local", onderwerp="Onderwerp", tekst="Inhoud")
        assert bericht["To"] == "a@test.local"
        assert "berichten@ak-nijenhuis.nl" in bericht["From"]
        assert bericht.get_content().strip() == "Inhoud"

    def test_activeerlink_bestaande_linkvorm(self) -> None:
        assert activeerlink("tok123") == f"{settings.app_basis_url.rstrip('/')}/activeren?token=tok123"


class TestSubscripties:
    def test_zonder_apparaat_geweigerd(self, accordeur_1: uuid.UUID) -> None:
        with pytest.raises(berichten_service.ApparaatVereist):
            berichten_service.registreer_subscriptie(
                gebruiker_id=accordeur_1, apparaat_id=None, endpoint="https://p/x", p256dh="p", auth="a"
            )

    def test_vreemd_apparaat_geweigerd(
        self, accordeur_1: uuid.UUID, accordeur_2: uuid.UUID, admin_engine: Engine
    ) -> None:
        apparaat_van_2 = maak_apparaat(admin_engine, accordeur_2)
        with pytest.raises(berichten_service.ApparaatVereist):
            berichten_service.registreer_subscriptie(
                gebruiker_id=accordeur_1, apparaat_id=apparaat_van_2, endpoint="https://p/x", p256dh="p", auth="a"
            )

    def test_upsert_zelfde_endpoint_heft_intrekking_op(
        self, accordeur_1: uuid.UUID, admin_engine: Engine
    ) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        eerste = berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1, apparaat_id=apparaat, endpoint="https://p/zelfde", p256dh="p1", auth="a1"
        )
        berichten_service.trek_subscriptie_in(gebruiker_id=accordeur_1, endpoint="https://p/zelfde")
        tweede = berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1, apparaat_id=apparaat, endpoint="https://p/zelfde", p256dh="p2", auth="a2"
        )
        assert tweede.id == eerste.id
        with scoped_session(None) as session:
            rij = session.get(PushSubscriptie, eerste.id)
            assert rij.ingetrokken_op is None and rij.p256dh == "p2"

    def test_intrekken_alleen_eigen(
        self, accordeur_1: uuid.UUID, accordeur_2: uuid.UUID, admin_engine: Engine
    ) -> None:
        apparaat = maak_apparaat(admin_engine, accordeur_1)
        berichten_service.registreer_subscriptie(
            gebruiker_id=accordeur_1, apparaat_id=apparaat, endpoint="https://p/eigen", p256dh="p", auth="a"
        )
        with pytest.raises(berichten_service.OnbekendeSubscriptie):
            berichten_service.trek_subscriptie_in(gebruiker_id=accordeur_2, endpoint="https://p/eigen")
        assert berichten_service.heeft_actieve_subscriptie(gebruiker_id=accordeur_1, apparaat_id=apparaat)
