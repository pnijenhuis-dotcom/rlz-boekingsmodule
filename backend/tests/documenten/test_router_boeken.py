from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.beheer import service as beheer_service
from app.documenten import boeken
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _geen_echte_rlz_aanroepen_voor_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """De boekvoorstel-endpoints (PUT/checks) draaien de harde checks meteen mee, incl. de
    duplicaatcheck (een echte RLZ-aanroep als er geen client meegegeven wordt) — hier altijd een
    lege fake, zodat deze routertests geen echte credentials nodig hebben. De boek-actie zelf
    (TestBoekenEndpoint) geeft altijd zijn eigen client mee via `boeken.client_voor_rlz_admin_id`."""
    monkeypatch.setattr("app.documenten.boekvoorstel.client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _upload(headers: dict[str, str], administratie_id: uuid.UUID, *, bestandsnaam: str = "factuur.pdf") -> str:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": (bestandsnaam, b"%PDF-1.4 " + uuid.uuid4().bytes, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


_REGEL = {
    "ledger_id": str(uuid.uuid4()),
    "taxrate_id": str(uuid.uuid4()),
    "netto_bedrag": "100.00",
    "btw_bedrag": "21.00",
}


class TestBoekvoorstelEndpoints:
    def test_get_zonder_opgeslagen_voorstel_geeft_leeg_niet_opgeslagen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.get(f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["opgeslagen"] is False

    def test_put_slaat_op_en_geeft_checkrapport_terug(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["boekvoorstel"]["opgeslagen"] is True
        assert body["checks"]["geblokkeerd"] is False
        assert {r["naam"] for r in body["checks"]["resultaten"]} == {
            "Verplichte velden",
            "Regeltelling vs totaal",
            "Duplicaatcheck",
        }

    def test_put_met_mismatch_totaal_geeft_geblokkeerd_checkrapport(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "999.00",
                "regels": [_REGEL],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["checks"]["geblokkeerd"] is True

    def test_checks_endpoint_herberekent_zonder_op_te_slaan(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)
        client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": "F-1",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks", headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["geblokkeerd"] is False

    def test_boekvoorstel_op_onbekend_document_geeft_404(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        resp = client.get(
            f"/administraties/{administratie_id}/documenten/{uuid.uuid4()}/boekvoorstel",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 404


class TestBoekenEndpoint:
    def _klaar_document(self, headers: dict[str, str], administratie_id: uuid.UUID) -> str:
        document_id = _upload(headers, administratie_id)
        client.put(
            f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
            headers=headers,
            json={
                "vendor_id": str(uuid.uuid4()),
                "referentie": f"F-{document_id}",
                "factuurdatum": "2026-07-01",
                "totaalbedrag": "121.00",
                "regels": [_REGEL],
            },
        )
        return document_id

    def test_boeken_zonder_toggle_geeft_403(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 403

    def test_boeken_geblokkeerd_door_checks_geeft_409_met_rapport(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)  # geen boekvoorstel -> geblokkeerd

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["checks"]["geblokkeerd"] is True

    def test_boeken_gelukt_geeft_200_met_boekstuknummer(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "geboekt"
        assert body["rlz_boekstuknummer"] == "RLZ-TEST-00001"

    def test_boeken_rlz_fout_geeft_502(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient(faal_op="put"))
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = self._klaar_document(headers, administratie_id)

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/boeken", headers=headers)
        assert resp.status_code == 502
        assert "PUT mislukt" in resp.json()["detail"]

    def test_boeken_zonder_scope_faalt(self, gescoopte_gebruiker: uuid.UUID) -> None:
        resp = client.post(
            f"/administraties/{uuid.uuid4()}/documenten/{uuid.uuid4()}/boeken",
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403
