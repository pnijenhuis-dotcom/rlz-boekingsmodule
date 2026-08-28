"""Opruimrun 28-08 punt 22 — e-mail wijzigen zonder carrousel (casus Haci) + leesbare 409 bij een
uitnodiging op een bestaand (ook gearchiveerd) adres (casus correlatie-id 9ba50485-…, Cloud-log:
UniqueViolation `gebruiker_e_mail_key` op POST /auth/uitnodigingen)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service
from app.db.models import GebruikerRol
from app.main import app
from app.security.tokens import create_access_token

from .conftest import ActieveGebruiker

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _open_uitnodigingen(admin_engine: Engine, gebruiker_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM platform.uitnodiging WHERE gebruiker_id = :id AND gebruikt_op IS NULL "
                "AND soort = 'uitnodiging'"
            ),
            {"id": gebruiker_id},
        ).scalar_one()


def _nodig_uit(beheerder_id: uuid.UUID, naam: str = "Veldwerker Haci") -> service.UitnodigingResultaat:
    return service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam=naam,
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=GebruikerRol.BOEKHOUDING,
        administratie_ids=[],
    )


class TestWijzigEMailZonderCarrousel:
    def test_geblokkeerd_account_mag_adres_wijzigen(
        self, beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
    ) -> None:
        service.blokkeer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id)
        gewijzigd = service.wijzig_e_mail(
            actor_id=beheerder_id, doel_gebruiker_id=actieve_gebruiker.id, nieuw_e_mail="geblokkeerd-nieuw@test.local"
        )
        assert gewijzigd.oud_e_mail == actieve_gebruiker.e_mail
        assert gewijzigd.nieuw_e_mail == "geblokkeerd-nieuw@test.local"
        assert gewijzigd.vernieuwde_uitnodiging is None  # geactiveerd account: alleen de login wijzigt

    def test_gearchiveerd_voor_activatie_krijgt_geen_nieuwe_uitnodiging(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Uitgenodigd → gearchiveerd vóór activatie → e-mail wijzigen: open links vervallen, GEEN
        verse uitnodiging (die zou een gearchiveerd account een werkende activatielink geven)."""
        uitnodiging = _nodig_uit(beheerder_id)
        service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=uitnodiging.gebruiker_id)
        assert _open_uitnodigingen(admin_engine, uitnodiging.gebruiker_id) == 1

        gewijzigd = service.wijzig_e_mail(
            actor_id=beheerder_id, doel_gebruiker_id=uitnodiging.gebruiker_id, nieuw_e_mail="vrij@test.local"
        )
        assert gewijzigd.vernieuwde_uitnodiging is None
        assert _open_uitnodigingen(admin_engine, uitnodiging.gebruiker_id) == 0
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT e_mail, status FROM platform.gebruiker WHERE id = :id"), {"id": uitnodiging.gebruiker_id}
            ).one()
            audit = conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'e_mail_gewijzigd' AND record_id = :id"
                ),
                {"id": uitnodiging.gebruiker_id},
            ).one()
        assert rij.e_mail == "vrij@test.local" and rij.status == "gearchiveerd"
        assert audit.oude_waarde["e_mail"] != "vrij@test.local" and audit.nieuwe_waarde["e_mail"] == "vrij@test.local"
        assert audit.nieuwe_waarde["uitnodiging_vernieuwd"] is False

    def test_router_mailt_niet_bij_gearchiveerd(self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        uitnodiging = _nodig_uit(beheerder_id)
        service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=uitnodiging.gebruiker_id)
        verzonden: list[str] = []
        from app.berichten import uitnodigingsmail

        monkeypatch.setattr(uitnodigingsmail, "verstuur_uitnodigingsmail", lambda **kw: verzonden.append(kw["e_mail"]))
        r = client.patch(
            f"/auth/gebruikers/{uitnodiging.gebruiker_id}/e-mail",
            json={"e_mail": "router-vrij@test.local"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["uitnodiging_vernieuwd"] is False and r.json()["mail_verzonden"] is False
        assert verzonden == []


class TestUitnodigingOpBestaandAdres:
    def test_gearchiveerd_adres_geeft_leesbare_weigering(self, beheerder_id: uuid.UUID) -> None:
        uitnodiging = _nodig_uit(beheerder_id)
        from app.db.models import Gebruiker
        from app.db.session import scoped_session

        with scoped_session(None, actor_id=beheerder_id) as session:
            with_e_mail = session.get(Gebruiker, uitnodiging.gebruiker_id).e_mail
        service.archiveer_gebruiker(actor_id=beheerder_id, doel_gebruiker_id=uitnodiging.gebruiker_id)

        with pytest.raises(service.EMailAlInGebruik, match="gearchiveerd account"):
            service.maak_uitnodiging(
                actor_id=beheerder_id,
                naam="Nieuwe Haci",
                e_mail=with_e_mail,
                rol=GebruikerRol.KLANT_ACCORDEUR,
                administratie_ids=[],
            )

    def test_actief_adres_geeft_leesbare_weigering(
        self, beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker
    ) -> None:
        with pytest.raises(service.EMailAlInGebruik, match="al in gebruik door Actieve Gebruiker"):
            service.maak_uitnodiging(
                actor_id=beheerder_id,
                naam="Dubbel",
                e_mail=actieve_gebruiker.e_mail.upper(),  # normalisatie: hoofdletters zijn hetzelfde adres
                rol=GebruikerRol.BOEKHOUDING,
                administratie_ids=[],
            )

    def test_router_409_in_plaats_van_500(self, beheerder_id: uuid.UUID, actieve_gebruiker: ActieveGebruiker) -> None:
        r = client.post(
            "/auth/uitnodigingen",
            json={
                "naam": "Dubbel",
                "e_mail": actieve_gebruiker.e_mail,
                "rol": "boekhouding",
                "administratie_ids": [],
            },
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 409, r.text
        assert "al in gebruik" in r.json()["detail"] and "code " not in r.json()["detail"]
