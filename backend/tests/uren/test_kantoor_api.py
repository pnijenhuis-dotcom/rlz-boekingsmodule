"""Kantoor-API (fase 3): module-recht-poort op élk kantoor-endpoint (menu/standen/API —
zonder recht verdwijnt de module overal), klantscope eronder, beoordeel-acties, contract-
toets-voorstel, stand-tellers en het Beheerder-only koppelingen-/recht-beheer."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.uren import service as uren_service
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def melding(administratie_id, project_id, uitvoerder, beheerder_id):
    uren_service.koppel_project(
        administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=project_id, actor_id=beheerder_id
    )
    return uren_service.meld_meerwerk(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=uitvoerder,
        omschrijving="Extra trapsteiger achterzijde",
        aantal=Decimal("84"),
        eenheid="m2",
        datum_uitgevoerd=date(2026, 8, 12),
        in_opdracht_van="J. Timmers (BAM)",
    )


class TestModuleRechtPoort:
    def test_zonder_recht_403_met_recht_200(self, admin_engine: Engine, administratie_id, melding, beheerder_id):
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=medewerker, administratie_id=administratie_id
        )
        headers = _bearer(medewerker, rol="boekhouding")
        resp = client.get("/uren/kantoor/meerwerk", params={"administratie_id": str(administratie_id)}, headers=headers)
        assert resp.status_code == 403  # geen module-recht → geen data, ook niet via de API
        resp = client.put(
            "/uren/beheer/module-recht",
            json={"gebruiker_id": str(medewerker), "ingeschakeld": True},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        resp = client.get("/uren/kantoor/meerwerk", params={"administratie_id": str(administratie_id)}, headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_klantscope_blijft_gelden_onder_het_recht(
        self, admin_engine: Engine, administratie_id, melding, beheerder_id
    ):
        """Recht wél, scope níét → 403 (klantscope blijft leidend — geen scope = geen data)."""
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Zonder Scope")
        uren_service.zet_meerwerk_recht(gebruiker_id=medewerker, ingeschakeld=True, actor_id=beheerder_id)
        resp = client.get(
            "/uren/kantoor/meerwerk",
            params={"administratie_id": str(administratie_id)},
            headers=_bearer(medewerker, rol="boekhouding"),
        )
        assert resp.status_code == 403

    def test_recht_zetten_is_beheerder_only_en_nooit_op_beheerder(
        self, admin_engine: Engine, beheerder_id
    ):
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        resp = client.put(
            "/uren/beheer/module-recht",
            json={"gebruiker_id": str(medewerker), "ingeschakeld": True},
            headers=_bearer(medewerker, rol="boekhouding"),
        )
        assert resp.status_code == 403
        resp = client.put(
            "/uren/beheer/module-recht",
            json={"gebruiker_id": str(beheerder_id), "ingeschakeld": True},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 422  # Beheerder heeft het recht altijd — niet instelbaar


class TestBeoordelen:
    def test_beoordeel_flow_met_contract_toets(
        self, administratie_id, project_id, melding, beheerder_id
    ):
        headers = _bearer(beheerder_id, rol="beheerder")
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            from app.uren.models import ProjectStaffel

            session.add(
                ProjectStaffel(
                    administratie_id=administratie_id,
                    project_id=project_id,
                    omschrijving="Trapsteigers",
                    eenheid="m2",
                    prijs_per_eenheid=Decimal("9.20"),
                    bron="§ 4.2",
                    aangemaakt_door=beheerder_id,
                )
            )
        resp = client.get(
            f"/uren/kantoor/meerwerk/{administratie_id}/{melding.id}/contract-toets", headers=headers
        )
        assert resp.status_code == 200
        (regel,) = resp.json()
        assert regel["prijs_per_eenheid"] == "9.20"

        resp = client.post(
            f"/uren/kantoor/meerwerk/{administratie_id}/{melding.id}/goedkeuren",
            json={"prijs_per_eenheid": "9.20", "bedrag": "772.80", "facturatie_notitie": "termijn 4"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "goedgekeurd"

        resp = client.post(
            f"/uren/kantoor/meerwerk/{administratie_id}/{melding.id}/doorbelast",
            json={"verkoopfactuur_referentie": "VF-2608"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["verkoopfactuur_referentie"] == "VF-2608"

    def test_afwijzen_zonder_reden_422(self, administratie_id, melding, beheerder_id):
        resp = client.post(
            f"/uren/kantoor/meerwerk/{administratie_id}/{melding.id}/afwijzen",
            json={"reden": " "},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 422

    def test_stand_tellers(self, administratie_id, melding, beheerder_id):
        resp = client.get(
            "/uren/kantoor/stand",
            params={"administratie_id": str(administratie_id)},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200
        stand = resp.json()
        assert stand["meerwerk_te_beoordelen"] == 1
        assert stand["urenstaten_wachten_op_keuring"] == 0

    def test_stand_zonder_opt_in_409(self, administratie_zonder_opt_in, beheerder_id):
        resp = client.get(
            "/uren/kantoor/stand",
            params={"administratie_id": str(administratie_zonder_opt_in)},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 409


class TestBeheerKoppelingen:
    def test_veldgebruikers_overzicht_met_koppelingen(
        self, admin_engine: Engine, administratie_id, project_id, zzper, detacheerder, beheerder_id
    ):
        headers = _bearer(beheerder_id, rol="beheerder")
        resp = client.post(
            "/uren/beheer/projectkoppelingen",
            json={
                "administratie_id": str(administratie_id),
                "gebruiker_id": str(zzper),
                "project_id": str(project_id),
            },
            headers=headers,
        )
        assert resp.status_code == 204, resp.text
        resp = client.post(
            "/uren/beheer/detacheerderkoppelingen",
            json={"detacheerder_id": str(detacheerder), "zzper_id": str(zzper)},
            headers=headers,
        )
        assert resp.status_code == 204

        resp = client.get("/uren/beheer/veldgebruikers", headers=headers)
        assert resp.status_code == 200
        per_naam = {g["naam"]: g for g in resp.json()}
        assert per_naam["Milan K."]["projecten"][0]["project_naam"] == "26014 Eindhoven (BAM)"
        assert per_naam["Karin S."]["zzpers"][0]["naam"] == "Milan K."

        # ontkoppelen (Beheerder-only) — idempotent
        resp = client.post(
            "/uren/beheer/projectkoppelingen/verwijderen",
            json={
                "administratie_id": str(administratie_id),
                "gebruiker_id": str(zzper),
                "project_id": str(project_id),
            },
            headers=headers,
        )
        assert resp.status_code == 204
        resp = client.get("/uren/beheer/veldgebruikers", headers=headers)
        assert resp.json() and per_naam["Milan K."]["gebruiker_id"] in [g["gebruiker_id"] for g in resp.json()]
        assert next(g for g in resp.json() if g["naam"] == "Milan K.")["projecten"] == []

    def test_beheer_is_beheerder_only(self, admin_engine: Engine, administratie_id):
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        resp = client.get("/uren/beheer/veldgebruikers", headers=_bearer(medewerker, rol="boekhouding"))
        assert resp.status_code == 403


class TestOptInBeheer:
    def test_opt_in_endpoint_en_effect(self, administratie_zonder_opt_in, beheerder_id):
        headers = _bearer(beheerder_id, rol="beheerder")
        resp = client.get(
            f"/administraties/{administratie_zonder_opt_in}/uren-meerwerk-instelling", headers=headers
        )
        assert resp.status_code == 200 and resp.json() == {"ingeschakeld": False}
        resp = client.put(
            f"/administraties/{administratie_zonder_opt_in}/uren-meerwerk-instelling",
            json={"ingeschakeld": True},
            headers=headers,
        )
        assert resp.status_code == 200 and resp.json() == {"ingeschakeld": True}
        # nu geeft de stand geen 409 meer
        resp = client.get(
            "/uren/kantoor/stand",
            params={"administratie_id": str(administratie_zonder_opt_in)},
            headers=headers,
        )
        assert resp.status_code == 200


class TestAfwijkingsLogging:
    """Afwijkings-logging (besluit Peter 2026-08-22): de opgetelde uren-afwijking per ZZP'er
    is zichtbaar voor het kantoor op het veldwerkers-overzicht (Beheerder-only) — en bestaat
    bewust nergens in de veld-API."""

    def test_veldgebruikers_dragen_uren_afwijking(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id
    ):
        maandag = date.fromisocalendar(2026, 34, 1)
        uren_service.zet_dag(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=34,
            datum=maandag,
            uren=Decimal("10"),
            actor_id=gekoppelde_zzper,
        )
        staat = uren_service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=34,
            actor_id=gekoppelde_zzper,
        )
        uren_service.keur_week_af(
            administratie_id=administratie_id,
            weekstaat_id=staat.id,
            actor_id=gekoppelde_uitvoerder,
            reden="Max 8 uur afgesproken",
            correcties=[uren_service.DagCorrectieInvoer(datum=maandag, uren=Decimal("8"))],
        )
        resp = client.get("/uren/beheer/veldgebruikers", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200
        milan = next(g for g in resp.json() if g["gebruiker_id"] == str(gekoppelde_zzper))
        assert milan["uren_afwijking_aantal"] == 1
        assert Decimal(milan["uren_afwijking_som"]) == Decimal("2")
        # ná de correctieronde + goedkeuring telt het wérkelijk goedgekeurde totaal
        uren_service.zet_dag(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=34,
            datum=maandag,
            uren=Decimal("9"),
            actor_id=gekoppelde_zzper,
        )
        uren_service.dien_week_in(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=34,
            actor_id=gekoppelde_zzper,
        )
        uren_service.keur_week_goed(
            administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=gekoppelde_uitvoerder
        )
        resp = client.get("/uren/beheer/veldgebruikers", headers=_bearer(beheerder_id, rol="beheerder"))
        milan = next(g for g in resp.json() if g["gebruiker_id"] == str(gekoppelde_zzper))
        assert Decimal(milan["uren_afwijking_som"]) == Decimal("1")  # 10 ingediend − 9 goedgekeurd

    def test_veld_api_exposeert_geen_afwijkingsstatistiek(
        self, administratie_id, project_id, gekoppelde_zzper
    ):
        from app.auth import voorwaarden

        voorwaarden.leg_akkoord_vast(gebruiker_id=gekoppelde_zzper)
        maandag = date.fromisocalendar(2026, 34, 1)
        uren_service.zet_dag(
            administratie_id=administratie_id,
            zzper_id=gekoppelde_zzper,
            project_id=project_id,
            jaar=2026,
            weeknummer=34,
            datum=maandag,
            uren=Decimal("8"),
            actor_id=gekoppelde_zzper,
        )
        resp = client.get("/uren/zzp/projecten", headers=_bearer(gekoppelde_zzper, rol="zzper"))
        assert resp.status_code == 200
        assert "afwijking" not in resp.text
