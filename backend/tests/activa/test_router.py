# ruff: noqa: F811 — pytest-fixtures als parameters
"""API activa: DTO-vorm van het contract, 422/409/404, rolpoorten (veldrol 403, boekhouder mét scope 200, instelling-PUT
Beheerder-only), instelling GET/PUT."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.documenten import boeken
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.activa.conftest import GB_0107, GB_0108, GB_0170, koppelingen, maak_factuur, regel
from tests.documenten.fake_rlz_client import FakeBoekClient

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _pad(administratie_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"/administraties/{administratie_id}/documenten/{document_id}/activa-voorstel"


@pytest.fixture
def zzper(admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> uuid.UUID:
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Zzp', :mail, 'zzper', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
    return gid


class TestVoorstelRoutes:
    def test_get_geeft_contract_dto(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        resp = client.get(_pad(administratie_id, factuur), headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200, resp.text
        dto = resp.json()
        assert dto["document_geboekt"] is False and dto["grens"] == "450.00" and dto["grens_bron"] == "instelling"
        assert dto["automatisch_ingeschakeld"] is False and dto["register_leesbaar"] is None
        assert len(dto["kandidaten"]) == 1 and dto["onder_grens"] == []
        k = dto["kandidaten"][0]
        assert k == {
            "regel_volgnummer": 1,
            "ledger_id": str(GB_0107),
            "ledger_code": "0107",
            "ledger_naam": "Inventaris",
            "omschrijving": "Bureau Hoogte-verstelbaar",
            "aanschafwaarde": "1250.00",
            "aanschafdatum": "2026-09-01",
            "categorie": "inventaris",
            "categorie_label": "Inventaris",
            "termijn_maanden": 60,
            "methode_naam": "Lineair 5 jaar",
            "restwaarde": "0.00",
            "afschrijving_ledger_id": str(GB_0108),
            "afschrijving_ledger_code": "4708",
            "afschrijving_bron": "conventie",
            "signalen": [
                {"code": "kia_mia_mogelijk", "tekst": "KIA/MIA/Vamil mogelijk van toepassing — adviseur beslist"}
            ],
            "koppeling": None,
        }
        assert [o["code"] for o in dto["afschrijving_ledger_opties"]] == ["4708", "4400"]

    def test_aanmaken_plant_en_overslaan_vereist_reden(
        self, factuur: uuid.UUID, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        h = _bearer(gescoopte_gebruiker)
        resp = client.post(
            f"{_pad(administratie_id, factuur)}/1/aanmaken", json={"afschrijving_ledger_id": str(GB_0108)}, headers=h
        )
        assert resp.status_code == 200, resp.text
        k = resp.json()["kandidaten"][0]
        assert k["koppeling"]["status"] == "gepland" and k["koppeling"]["herkomst"] == "mens"
        assert k["afschrijving_ledger_id"] == str(GB_0108) and k["afschrijving_ledger_code"] == "4708"
        assert k["koppeling"]["gewijzigd_op"]
        # Zonder body mag ook.
        assert client.post(f"{_pad(administratie_id, factuur)}/1/aanmaken", headers=h).status_code == 200
        resp = client.post(f"{_pad(administratie_id, factuur)}/1/overslaan", json={"reden": ""}, headers=h)
        assert resp.status_code == 422
        resp = client.post(f"{_pad(administratie_id, factuur)}/1/overslaan", json={"reden": "lease"}, headers=h)
        assert resp.status_code == 200 and resp.json()["kandidaten"][0]["koppeling"]["status"] == "overgeslagen"
        assert koppelingen(admin_engine, factuur)[0]["reden"] == "lease"

    def test_422_geen_kandidaat_en_ongeldige_termijn_409_al_aangemaakt_404_onbekend(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        rlz: FakeBoekClient,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        h = _bearer(gescoopte_gebruiker)
        assert client.post(f"{_pad(administratie_id, factuur)}/2/aanmaken", headers=h).status_code == 422
        # BUG 24-09 punt 2 (route-contract, letterlijk): kandidaat zonder voorvulling (0170 → geen 0171) en zonder
        # keuze = 422.
        laptop = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            regels=[regel(GB_0170, "2400.00", "Laptop")],
            referentie="KI-LAPTOP-ROUTE",
        )
        resp = client.post(f"{_pad(administratie_id, laptop)}/1/aanmaken", headers=h)
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "Kies een afschrijvingsrekening — RLZ vereist er één per activum"
        assert koppelingen(admin_engine, laptop) == []  # nooit meer "gepland zonder afschrijvingsrekening"
        assert (
            client.post(
                f"{_pad(administratie_id, laptop)}/1/aanmaken", json={"afschrijving_ledger_id": str(GB_0108)}, headers=h
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"{_pad(administratie_id, factuur)}/1/aanmaken", json={"termijn_maanden": 7}, headers=h
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{_pad(administratie_id, factuur)}/1/aanmaken", json={"onbekend_veld": 1}, headers=h
            ).status_code
            == 422
        )
        assert client.get(_pad(administratie_id, uuid.uuid4()), headers=h).status_code == 404
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        resp = client.post(
            f"{_pad(administratie_id, factuur)}/1/aanmaken", json={"afschrijving_ledger_id": str(GB_0108)}, headers=h
        )
        assert resp.status_code == 200 and resp.json()["document_geboekt"] is True
        assert resp.json()["kandidaten"][0]["koppeling"]["status"] == "aangemaakt"
        assert resp.json()["kandidaten"][0]["koppeling"]["rlz_receipt_number"] == "1"
        resp = client.post(f"{_pad(administratie_id, factuur)}/1/aanmaken", headers=h)
        assert resp.status_code == 409 and "al aangemaakt" in resp.json()["detail"]
        assert (
            client.post(f"{_pad(administratie_id, factuur)}/1/overslaan", json={"reden": "toch"}, headers=h).status_code
            == 409
        )

    def test_veldrol_403_en_zonder_scope_403(
        self,
        factuur: uuid.UUID,
        administratie_id: uuid.UUID,
        zzper: uuid.UUID,
        admin_engine: Engine,
        beheerder_id: uuid.UUID,
    ) -> None:
        assert client.get(_pad(administratie_id, factuur), headers=_bearer(zzper, rol="zzper")).status_code == 403
        gid = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'B', :mail, 'boekhouding', 'actief')"
                ),
                {"id": gid, "mail": f"{gid}@test.local"},
            )
        assert client.get(_pad(administratie_id, factuur), headers=_bearer(gid)).status_code == 403


class TestInstellingRoutes:
    def test_get_voor_kantoorrol_en_put_alleen_beheerder(
        self,
        stamgegevens: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        zzper: uuid.UUID,
    ) -> None:
        pad = f"/administraties/{administratie_id}/activa-instelling"
        resp = client.get(pad, headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200, resp.text
        dto = resp.json()
        assert (
            dto["automatisch_aanmaken_ingeschakeld"] is False
            and dto["effectieve_grens"] == "450.00"
            and dto["grens_rlz"] is None
        )
        assert [c["code"] for c in dto["categorieen"]][:2] == ["gebouwen", "inventaris"]
        assert [r["code"] for r in dto["mva_rekeningen"]] == ["0107", "0170"]
        assert dto["koppelingen_tellers"] == {
            "gepland": 0,
            "aangemaakt": 0,
            "overgeslagen": 0,
            "mislukt": 0,
            "beoordelen": 0,
        }
        body = {
            "automatisch_aanmaken_ingeschakeld": True,
            "activeringsgrens": "600.00",
            "termijnen": {"steigermateriaal": 60, "computers_software": 48},
            "afschrijving_ledgers": {"inventaris": str(GB_0108), "machines": None},
        }
        assert client.put(pad, json=body, headers=_bearer(gescoopte_gebruiker)).status_code == 403
        assert client.get(pad, headers=_bearer(zzper, rol="zzper")).status_code == 403
        resp = client.put(pad, json=body, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200, resp.text
        dto = resp.json()
        assert dto["automatisch_aanmaken_ingeschakeld"] is True and dto["activeringsgrens"] == "600.00"
        assert dto["termijnen"] == {"steigermateriaal": 60, "computers_software": 48}
        assert dto["afschrijving_ledgers"] == {"inventaris": str(GB_0108)}
        # Validatie → 422 mét tekst.
        fout = client.put(
            pad, json={**body, "termijnen": {"inventaris": 13}}, headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert fout.status_code == 422 and "veelvoud van 12" in fout.json()["detail"]
        assert (
            client.get(
                f"/administraties/{uuid.uuid4()}/activa-instelling", headers=_bearer(beheerder_id, rol="beheerder")
            ).status_code
            == 404
        )
