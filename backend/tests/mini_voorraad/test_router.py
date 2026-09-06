# ruff: noqa: F811
"""Blok F 06-09 — API: rolpoorten + RLS (echte niet-Beheerder mét scope leest, zonder scope 403), de vier toegestane
handelingen, beschadiging vereist een actief project (422), Beheerder-toggle, en de ⑧-sweep: GEEN mutatie-endpoint."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.documenten import boeken
from app.main import app
from app.mini_voorraad.router import TOEGESTANE_POST_STAARTEN, router
from app.security.tokens import create_access_token
from tests.mini_voorraad.conftest import audit_acties, maak_document, mutaties, regel, standen
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("_opslag_naar_tmp")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def geboekt(mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag) -> uuid.UUID:
    doc = maak_document(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4"), regel("Kanaalplaatvork speciaal", "6")],
        referentie="260630",
    )
    boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
    return doc


def _product_id(aid: uuid.UUID, actor: uuid.UUID, omschrijving: str) -> uuid.UUID:
    resp = client.get(f"/mini-voorraad/{aid}/producten", headers=_bearer(actor, rol="boekhouding"))
    assert resp.status_code == 200, resp.text
    [p] = [p for p in resp.json()["items"] if p["omschrijving"] == omschrijving]
    return uuid.UUID(p["id"])


class TestGeenMutatieEndpoint:
    """⑧ — de router kent uitsluitend GET's en de vier whitelist-POST's; nergens PUT/PATCH/DELETE."""

    def test_routerlijst_alleen_get_en_whitelist_posts(self) -> None:
        gezien = 0
        for route in router.routes:
            assert isinstance(route, APIRoute)
            methodes = route.methods - {"HEAD", "OPTIONS"}
            assert methodes <= {"GET", "POST"}, f"{route.path}: {methodes}"
            if "POST" in methodes:
                assert route.path.endswith(TOEGESTANE_POST_STAARTEN), route.path
                gezien += 1
        assert gezien == 4

    def test_app_kent_geen_schrijfroute_op_mini_voorraad_buiten_de_whitelist(self) -> None:
        for route in app.routes:
            binnen = getattr(route, "original_router", None)
            for r in binnen.routes if binnen is not None else [route]:
                if not isinstance(r, APIRoute) or not r.path.startswith("/mini-voorraad"):
                    continue
                for m in r.methods - {"HEAD", "OPTIONS", "GET"}:
                    assert m == "POST" and r.path.endswith(TOEGESTANE_POST_STAARTEN), f"{m} {r.path}"


class TestLezenEnScope:
    def test_niet_beheerder_met_scope_leest_producten_log_en_stand(
        self, geboekt, administratie_id, gescoopte_gebruiker, admin_engine: Engine
    ) -> None:
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        resp = client.get(f"/mini-voorraad/{administratie_id}/producten", headers=h)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ingeschakeld"] is True and body["totaal"] == 2 and body["nieuw_controleren"] == 2
        assert body["per_pagina"] == 25 and body["pagina"] == 1
        stapelbok = next(p for p in body["items"] if p["omschrijving"] == "Stapelbok 1,25×0,85")
        assert stapelbok["stand"] == "24" and stapelbok["artikelcode"] == "560140.4"
        assert stapelbok["leverancier_naam"] == "Huvanco B.V." and stapelbok["nieuw_controleren"] is True
        assert stapelbok["weergavenaam"] is None and stapelbok["laatste_mutatie_op"] is not None

        pid = uuid.UUID(stapelbok["id"])
        log = client.get(f"/mini-voorraad/{administratie_id}/producten/{pid}/log", headers=h)
        assert log.status_code == 200
        [m] = log.json()["items"]
        assert m["soort"] == "instroom" and m["aantal"] == "24" and m["datum"] == "2026-07-01"
        assert m["document_id"] == str(geboekt) and m["document_referentie"] == "260630"
        assert m["document_leverancier"] == "Huvanco B.V." and m["boek_cyclus"] == 0
        assert m["project_id"] is None and m["gemeld_door_naam"] is None

        stand = client.get(f"/mini-voorraad/{administratie_id}/stand", headers=h)
        assert stand.json() == {"ingeschakeld": True, "producten": 2, "nieuw_controleren": 2}

        # Filters + zoeken server-side.
        assert client.get(f"/mini-voorraad/{administratie_id}/producten?filter=nieuw", headers=h).json()["totaal"] == 2
        assert (
            client.get(f"/mini-voorraad/{administratie_id}/producten?filter=gearchiveerd", headers=h).json()["totaal"]
            == 0
        )
        assert client.get(f"/mini-voorraad/{administratie_id}/producten?q=kanaal", headers=h).json()["totaal"] == 1
        assert client.get(f"/mini-voorraad/{administratie_id}/producten?filter=onzin", headers=h).status_code == 422

    def test_zonder_scope_403_en_extern_403(
        self, geboekt, administratie_id, admin_engine: Engine, beheerder_id
    ) -> None:
        ander = maak_gebruiker(admin_engine, "boekhouding", "Zonder scope")
        resp = client.get(f"/mini-voorraad/{administratie_id}/producten", headers=_bearer(ander, rol="boekhouding"))
        assert resp.status_code == 403
        zzp = maak_gebruiker(admin_engine, "zzper", "Veld")
        assert (
            client.get(f"/mini-voorraad/{administratie_id}/stand", headers=_bearer(zzp, rol="zzper")).status_code == 403
        )
        assert (
            client.get(
                f"/mini-voorraad/{administratie_id}/producten", headers=_bearer(beheerder_id, rol="beheerder")
            ).status_code
            == 200
        )

    def test_opt_in_uit_geeft_lege_lijst_en_409_op_handelingen(
        self, boeken_aan_zonder_mini, administratie_id, gescoopte_gebruiker
    ) -> None:
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        resp = client.get(f"/mini-voorraad/{administratie_id}/producten", headers=h)
        assert resp.status_code == 200 and resp.json()["ingeschakeld"] is False and resp.json()["items"] == []
        assert client.get(f"/mini-voorraad/{administratie_id}/stand", headers=h).json()["ingeschakeld"] is False
        resp = client.post(
            f"/mini-voorraad/{administratie_id}/producten/{uuid.uuid4()}/naam-bevestigen",
            json={"weergavenaam": "x"},
            headers=h,
        )
        assert resp.status_code == 409 and "staat uit" in resp.json()["detail"]
        assert client.get(f"/mini-voorraad/{administratie_id}/materiaallijst", headers=h).status_code == 409


class TestHandelingen:
    def test_naam_bevestigen_wijzigt_alleen_weergavenaam(
        self, geboekt, administratie_id, gescoopte_gebruiker, admin_engine: Engine
    ) -> None:
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        pid = _product_id(administratie_id, gescoopte_gebruiker, "Kanaalplaatvork speciaal")
        resp = client.post(
            f"/mini-voorraad/{administratie_id}/producten/{pid}/naam-bevestigen",
            json={"weergavenaam": "  Kanaalplaatvork   speciaal 1,2 m  "},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        p = resp.json()
        assert p["weergavenaam"] == "Kanaalplaatvork speciaal 1,2 m"
        assert p["omschrijving"] == "Kanaalplaatvork speciaal"  # de sleutel blijft de factuurtekst (⑦)
        assert p["nieuw_controleren"] is False and p["stand"] == "6"
        assert client.get(f"/mini-voorraad/{administratie_id}/stand", headers=h).json()["nieuw_controleren"] == 1
        assert audit_acties(admin_engine, "mini_product_naam_bevestigd") == 1
        assert standen(admin_engine, administratie_id)["Kanaalplaatvork speciaal"] == Decimal("6.000")
        assert (
            client.post(
                f"/mini-voorraad/{administratie_id}/producten/{uuid.uuid4()}/naam-bevestigen",
                json={"weergavenaam": "x"},
                headers=h,
            ).status_code
            == 404
        )

    def test_archiveren_is_beheerder_only_en_omkeerbaar(
        self, geboekt, administratie_id, gescoopte_gebruiker, beheerder_id, admin_engine: Engine
    ) -> None:
        pid = _product_id(administratie_id, gescoopte_gebruiker, "Kanaalplaatvork speciaal")
        pad = f"/mini-voorraad/{administratie_id}/producten/{pid}/archiveren"
        assert (
            client.post(
                pad, json={"reden": "dubbel product"}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
            ).status_code
            == 403
        )
        hb = _bearer(beheerder_id, rol="beheerder")
        assert client.post(pad, json={"reden": "kort"}, headers=hb).status_code == 422
        resp = client.post(pad, json={"reden": "dubbel product"}, headers=hb)
        assert resp.status_code == 200 and resp.json()["gearchiveerd"] is True and resp.json()["stand"] == "6"
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert client.get(f"/mini-voorraad/{administratie_id}/producten", headers=h).json()["totaal"] == 1
        assert (
            client.get(f"/mini-voorraad/{administratie_id}/producten?filter=gearchiveerd", headers=h).json()["totaal"]
            == 1
        )
        assert client.post(pad, json={"reden": "dubbel product"}, headers=hb).status_code == 422  # al gearchiveerd
        resp = client.post(f"/mini-voorraad/{administratie_id}/producten/{pid}/dearchiveren", headers=hb)
        assert resp.status_code == 200 and resp.json()["gearchiveerd"] is False
        assert audit_acties(admin_engine, "mini_product_gearchiveerd") == 1
        assert audit_acties(admin_engine, "mini_product_gedearchiveerd") == 1

    def test_beschadiging_vereist_actief_project_en_telt_negatief(
        self, geboekt, administratie_id, gescoopte_gebruiker, actief_project, inactief_project, admin_engine: Engine
    ) -> None:
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        pid = _product_id(administratie_id, gescoopte_gebruiker, "Stapelbok 1,25×0,85")
        basis = {
            "product_id": str(pid),
            "aantal": "4",
            "datum": "2026-07-02",
            "toelichting": "beschadigd bij demontage",
        }
        # Zonder project = 422 (schema), onbekend/inactief project = 422 (leesbaar), toekomst = 422, 0 = 422.
        assert (
            client.post(f"/mini-voorraad/{administratie_id}/beschadigingen", json=basis, headers=h).status_code == 422
        )
        resp = client.post(
            f"/mini-voorraad/{administratie_id}/beschadigingen",
            json={**basis, "project_id": str(uuid.uuid4())},
            headers=h,
        )
        assert resp.status_code == 422 and "actief project" in resp.json()["detail"]
        resp = client.post(
            f"/mini-voorraad/{administratie_id}/beschadigingen",
            json={**basis, "project_id": str(inactief_project)},
            headers=h,
        )
        assert resp.status_code == 422
        resp = client.post(
            f"/mini-voorraad/{administratie_id}/beschadigingen",
            json={**basis, "project_id": str(actief_project), "datum": str(date(2099, 1, 1))},
            headers=h,
        )
        assert resp.status_code == 422
        resp = client.post(
            f"/mini-voorraad/{administratie_id}/beschadigingen",
            json={**basis, "project_id": str(actief_project), "aantal": "0"},
            headers=h,
        )
        assert resp.status_code == 422
        assert standen(admin_engine, administratie_id)["Stapelbok 1,25×0,85"] == Decimal("24.000")

        resp = client.post(
            f"/mini-voorraad/{administratie_id}/beschadigingen",
            json={**basis, "project_id": str(actief_project)},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        m = resp.json()
        assert m["soort"] == "beschadiging" and m["aantal"] == "-4" and m["datum"] == "2026-07-02"
        assert m["project_id"] == str(actief_project) and m["project_naam"] == "26127 Tilburg (Heijmans)"
        assert m["gemeld_door_naam"] == "Boekhouder" and m["toelichting"] == "beschadigd bij demontage"
        assert m["document_id"] is None
        assert standen(admin_engine, administratie_id)["Stapelbok 1,25×0,85"] == Decimal("20.000")
        [rij] = mutaties(admin_engine, administratie_id, "beschadiging")
        assert rij["project_id"] == actief_project and rij["gemeld_door"] == gescoopte_gebruiker
        assert audit_acties(admin_engine, "mini_voorraad_beschadiging_gemeld") == 1
        log = client.get(f"/mini-voorraad/{administratie_id}/producten/{pid}/log", headers=h).json()
        assert [x["soort"] for x in log["items"]] == ["beschadiging", "instroom"]
        assert client.get(f"/mini-voorraad/{administratie_id}/producten", headers=h).json()["items"][0]["stand"] in (
            "20",
            "6",
        )


class TestToggle:
    def test_patch_mini_voorraad_beheerder_only_met_audit(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine: Engine
    ) -> None:
        pad = f"/administraties/{administratie_id}/mini-voorraad"
        assert (
            client.patch(
                pad, json={"ingeschakeld": True}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
            ).status_code
            == 403
        )
        resp = client.patch(pad, json={"ingeschakeld": True}, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200 and resp.json() == {"ingeschakeld": True}
        lijst = client.get("/instellingen/administraties", headers=_bearer(beheerder_id, rol="beheerder")).json()
        [rij] = [a for a in lijst["administraties"] if a["id"] == str(administratie_id)]
        assert rij["mini_voorraad_ingeschakeld"] is True and rij["voorraad_ingeschakeld"] is False
        assert client.patch(
            pad, json={"ingeschakeld": False}, headers=_bearer(beheerder_id, rol="beheerder")
        ).json() == {"ingeschakeld": False}
        assert audit_acties(admin_engine, "mini_voorraad_ingeschakeld_gewijzigd") == 2
        assert (
            client.patch(
                f"/administraties/{uuid.uuid4()}/mini-voorraad",
                json={"ingeschakeld": True},
                headers=_bearer(beheerder_id, rol="beheerder"),
            ).status_code
            == 404
        )
