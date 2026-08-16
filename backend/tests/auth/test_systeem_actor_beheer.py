"""Nazorg controls-review 2026-08-16: de systeem-actor (achtergrondverwerking, migratie 0016)
is een technische gebruiker-rij voor FK's op audit/tijdlijn — nooit een beheerbaar account.
Hij hoort niet in Gebruikers & toegang en rol-/scope-mutatie erop moet server-side weigeren
(de UI verbergt hem, maar de server dwingt af). Plus: de dev-stub-passkeyregistratie is
idempotent op (gebruiker, apparaat_naam) — her-activering dupliceerde het apparaat in de
apparaatlijsten."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.auth import service, webauthn_service
from app.config import settings
from app.db.models import GebruikerRol
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401


class TestSysteemActorNietBeheerbaar:
    def test_systeem_actor_blijft_buiten_de_gebruikerslijst(
        self, beheerder_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        # De rij bestaat echt (migratie 0016) — anders test dit niets.
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM platform.gebruiker WHERE id = :id"),
                {"id": SYSTEEM_ACTOR_ID},
            ).scalar_one()
        assert aantal == 1
        assert all(item.id != SYSTEEM_ACTOR_ID for item in service.lijst_gebruikers(actor_id=beheerder_id))

    def test_rol_wijzigen_op_systeem_actor_weigert(self, beheerder_id: uuid.UUID) -> None:  # noqa: F811
        with pytest.raises(service.AuthError, match="systeemgebruiker"):
            service.wijzig_rol(
                actor_id=beheerder_id, doel_gebruiker_id=SYSTEEM_ACTOR_ID, nieuwe_rol=GebruikerRol.BEHEERDER
            )

    def test_scope_muteren_op_systeem_actor_weigert(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID  # noqa: F811
    ) -> None:
        with pytest.raises(service.AuthError, match="systeemgebruiker"):
            service.voeg_scope_toe(
                actor_id=beheerder_id, doel_gebruiker_id=SYSTEEM_ACTOR_ID, administratie_id=administratie_id
            )
        with pytest.raises(service.AuthError, match="systeemgebruiker"):
            service.verwijder_scope(
                actor_id=beheerder_id, doel_gebruiker_id=SYSTEEM_ACTOR_ID, administratie_id=administratie_id
            )


class TestDevStubIdempotent:
    def test_herregistratie_zelfde_stub_apparaat_dupliceert_niet(
        self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch  # noqa: F811
    ) -> None:
        monkeypatch.setattr(settings, "auth_biometrie_dev_stub", True)
        monkeypatch.setattr(settings, "environment", "dev")
        eerste = webauthn_service.voltooi_registratie_stub(
            gebruiker_id=beheerder_id, apparaat_naam="LAN-telefoon (dev-stub)"
        )
        tweede = webauthn_service.voltooi_registratie_stub(
            gebruiker_id=beheerder_id, apparaat_naam="LAN-telefoon (dev-stub)"
        )
        assert tweede.apparaat_id == eerste.apparaat_id
        actief = [a for a in webauthn_service.apparaten_van(gebruiker_id=beheerder_id) if a.ingetrokken_op is None]
        assert len(actief) == 1

    def test_andere_apparaatnaam_blijft_een_eigen_rij(
        self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch  # noqa: F811
    ) -> None:
        monkeypatch.setattr(settings, "auth_biometrie_dev_stub", True)
        monkeypatch.setattr(settings, "environment", "dev")
        eerste = webauthn_service.voltooi_registratie_stub(
            gebruiker_id=beheerder_id, apparaat_naam="LAN-telefoon (dev-stub)"
        )
        tweede = webauthn_service.voltooi_registratie_stub(
            gebruiker_id=beheerder_id, apparaat_naam="iPad (dev-stub)"
        )
        assert tweede.apparaat_id != eerste.apparaat_id
