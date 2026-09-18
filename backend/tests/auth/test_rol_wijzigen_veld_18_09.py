"""Gebruikers & toegang › Veldwerkers: rol wijzigen zonder heruitnodiging (Peter 18-09: "Hoe kan ik de rol van Irfan
veranderen van ZZP'er naar uitvoerder?"; opdracht 2026-09-18-veldwerker-rol-wijzigen).

Wissel BINNEN de veldrollen (ZZP'er ↔ uitvoerder ↔ detacheerder) = toegestaan: scope, toestel en account blijven, audit
`rol_wijziging` oud→nieuw (DB-trigger 0002), de volgende token-verversing draagt de nieuwe rol. Wissel kantoor ↔ veld/
accordeur = ander auth-model → `RolWisselNietToegestaan` → HTTP 409 mét leesbare reden."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service
from app.auth.rollen import rolgroep
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token, decode_token

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _nodig_uit(beheerder_id: uuid.UUID, rol: GebruikerRol, administratie_ids: list[uuid.UUID]) -> uuid.UUID:
    return service.maak_uitnodiging(
        actor_id=beheerder_id,
        naam=f"Test {rol.value}",
        e_mail=f"{uuid.uuid4()}@test.local",
        rol=rol,
        administratie_ids=administratie_ids,
    ).gebruiker_id


def _rol(admin_engine: Engine, gebruiker_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT rol FROM platform.gebruiker WHERE id = :id"), {"id": gebruiker_id}
        ).scalar_one()


class TestRolgroep:
    def test_indeling(self) -> None:
        assert {rolgroep(r) for r in (GebruikerRol.ZZPER, GebruikerRol.UITVOERDER, GebruikerRol.DETACHEERDER)} == {
            "veld"
        }
        assert {
            rolgroep(r) for r in (GebruikerRol.BEHEERDER, GebruikerRol.BOEKHOUDING, GebruikerRol.BOEKHOUDING_PROJECTEN)
        } == {"kantoor"}
        assert rolgroep(GebruikerRol.KLANT_ACCORDEUR) == "accordeur"


class TestWisselBinnenVeldrollen:
    def test_zzper_wordt_uitvoerder_met_behoud_van_scope_en_audit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        wie = _nodig_uit(beheerder_id, GebruikerRol.ZZPER, [administratie_id])
        service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=wie, nieuwe_rol=GebruikerRol.UITVOERDER)
        assert _rol(admin_engine, wie) == "uitvoerder"
        with admin_engine.connect() as conn:
            scope = (
                conn.execute(
                    text("SELECT administratie_id FROM platform.gebruiker_administratie WHERE gebruiker_id = :id"),
                    {"id": wie},
                )
                .scalars()
                .all()
            )
            audit = (
                conn.execute(
                    text(
                        "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                        "WHERE tabel = 'gebruiker' AND record_id = :id AND actie = 'rol_wijziging'"
                    ),
                    {"id": wie},
                )
                .mappings()
                .all()
            )
        assert scope == [administratie_id]  # scope blijft
        assert len(audit) == 1
        assert audit[0]["oude_waarde"]["rol"] == "zzper" and audit[0]["nieuwe_waarde"]["rol"] == "uitvoerder"

    def test_uitvoerder_terug_naar_zzper_en_naar_detacheerder(
        self, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        wie = _nodig_uit(beheerder_id, GebruikerRol.UITVOERDER, [])
        service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=wie, nieuwe_rol=GebruikerRol.ZZPER)
        assert _rol(admin_engine, wie) == "zzper"
        service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=wie, nieuwe_rol=GebruikerRol.DETACHEERDER)
        assert _rol(admin_engine, wie) == "detacheerder"

    def test_volgende_tokenverversing_draagt_de_nieuwe_rol(self, beheerder_id: uuid.UUID) -> None:
        """De app leest de rol uit het access-token; ná de wissel geeft de refresh-rotatie een token mét de nieuwe rol
        (geen heractivatie). Server-side geldt de nieuwe rol al per request (deps leest de DB)."""
        wie = _nodig_uit(beheerder_id, GebruikerRol.ZZPER, [])
        with scoped_session(None, actor_id=wie) as session:
            paar = service._issue_token_paar(session, gebruiker_id=wie, rol=GebruikerRol.ZZPER)
        assert decode_token(paar.access_token, expected_type="access")["rol"] == "zzper"
        service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=wie, nieuwe_rol=GebruikerRol.UITVOERDER)
        # De gebruiker moet 'actief' zijn voor een verversing; de uitnodiging staat nog op 'uitgenodigd'.
        with scoped_session(None, actor_id=beheerder_id) as session:
            session.execute(text("UPDATE platform.gebruiker SET status = 'actief' WHERE id = :id"), {"id": wie})
        vers = service.vernieuw_token(refresh_token=paar.refresh_token)
        assert decode_token(vers.access_token, expected_type="access")["rol"] == "uitvoerder"

    def test_api_wissel_binnen_veld_is_204(self, beheerder_id: uuid.UUID, admin_engine: Engine) -> None:
        wie = _nodig_uit(beheerder_id, GebruikerRol.ZZPER, [])
        resp = client.patch(
            f"/auth/gebruikers/{wie}/rol", json={"rol": "uitvoerder"}, headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 204, resp.text
        assert _rol(admin_engine, wie) == "uitvoerder"


class TestWisselTussenGroepenGeweigerd:
    @pytest.mark.parametrize(
        ("van", "naar"),
        [
            (GebruikerRol.ZZPER, GebruikerRol.BOEKHOUDING),
            (GebruikerRol.UITVOERDER, GebruikerRol.BEHEERDER),
            (GebruikerRol.BOEKHOUDING, GebruikerRol.UITVOERDER),
            (GebruikerRol.KLANT_ACCORDEUR, GebruikerRol.ZZPER),
            (GebruikerRol.ZZPER, GebruikerRol.KLANT_ACCORDEUR),
        ],
    )
    def test_service_weigert_met_leesbare_reden(
        self, beheerder_id: uuid.UUID, admin_engine: Engine, van: GebruikerRol, naar: GebruikerRol
    ) -> None:
        wie = _nodig_uit(beheerder_id, van, [])
        with pytest.raises(service.RolWisselNietToegestaan, match="ander inlogmodel"):
            service.wijzig_rol(actor_id=beheerder_id, doel_gebruiker_id=wie, nieuwe_rol=naar)
        assert _rol(admin_engine, wie) == van.value  # niets gewijzigd

    def test_api_geeft_409_met_de_reden(self, beheerder_id: uuid.UUID) -> None:
        wie = _nodig_uit(beheerder_id, GebruikerRol.ZZPER, [])
        resp = client.patch(
            f"/auth/gebruikers/{wie}/rol", json={"rol": "boekhouding"}, headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 409, resp.text
        assert "ander inlogmodel" in resp.json()["detail"]
        assert "zzper (veld)" in resp.json()["detail"] and "boekhouding (kantoor)" in resp.json()["detail"]
