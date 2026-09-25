"""Blok 4 feedbackrun A 25-09 (FV-16): LET-OP in de doorbelastingspreview als één van beide kanten (bron-verkoop of
doel-spiegel) op de factuurdatum in een ingediende btw-aangifte valt — beide kanten boeken hetzelfde tijdvak; nooit
blokkerend, credential-/leesfouten zichtbaar als "niet toetsbaar"."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.doorbelasting import boeken
from app.main import app
from app.rlz.credentials import GeenRlzCredentials
from app.security.tokens import create_access_token
from tests.doorbelasting.conftest import DoorbelastingOpzet, FakeDoorbelastingClient

INGEDIEND_ALLES = {"Status": 2, "StartDate": "2000-01-01T00:00:00", "Date": "2099-12-31T00:00:00"}
CONCEPT_ALLES = {"Status": 1, "StartDate": "2000-01-01T00:00:00", "Date": "2099-12-31T00:00:00"}


class TestAangifteLetOp:
    def test_ic_paar_een_kant_ingediend_is_let_op_andere_kant_vrij(self, onboarded_opzet: DoorbelastingOpzet) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(aangiften=[CONCEPT_ALLES])
        doel = FakeDoorbelastingClient(aangiften=[INGEDIEND_ALLES])
        kanten = boeken.aangifte_letop_voor_document(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            bron_client=bron,
            doel_client_factory=lambda _aid: doel,
        )
        assert [t.toegestaan for t in kanten] == [True, False]
        assert kanten[0].kant.startswith("verkoopfactuur")
        assert "spiegel-inkoopfactuur" in kanten[1].kant and "ingediende btw-aangifte" in (kanten[1].reden or "")
        assert kanten[1].periode_start is not None

    def test_beide_kanten_open_is_geen_let_op(self, onboarded_opzet: DoorbelastingOpzet) -> None:
        opzet = onboarded_opzet
        kanten = boeken.aangifte_letop_voor_document(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            bron_client=FakeDoorbelastingClient(),
            doel_client_factory=lambda _aid: FakeDoorbelastingClient(),
        )
        assert kanten and all(t.toegestaan for t in kanten)

    def test_geen_credentials_doel_is_zichtbaar_niet_toetsbaar_nooit_500(
        self, onboarded_opzet: DoorbelastingOpzet
    ) -> None:
        opzet = onboarded_opzet

        def geen(_aid: uuid.UUID) -> FakeDoorbelastingClient:
            raise GeenRlzCredentials("geen login (simulatie)")

        kanten = boeken.aangifte_letop_voor_document(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            bron_client=FakeDoorbelastingClient(),
            doel_client_factory=geen,
        )
        assert kanten[0].toegestaan and not kanten[1].toegestaan
        assert "geen RLZ-credentials" in (kanten[1].reden or "") and kanten[1].periode_start is None

    def test_route_geeft_leesbare_let_op_regels(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, monkeypatch
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(aangiften=[INGEDIEND_ALLES])
        doel = FakeDoorbelastingClient()
        origineel = boeken.aangifte_letop_voor_document
        monkeypatch.setattr(
            boeken,
            "aangifte_letop_voor_document",
            lambda **kw: origineel(**kw, bron_client=bron, doel_client_factory=lambda _aid: doel),
        )
        client = TestClient(app)
        resp = client.get(
            f"/doorbelasting/{opzet.administratie_id}/documenten/{opzet.document_id}/aangifte-letop",
            headers={"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["let_op"]) == 1 and "beide kanten zelfde tijdvak" in body["let_op"][0]
        assert "verkoopfactuur (bron-administratie)" in body["let_op"][0]
        assert [k["toegestaan"] for k in body["kanten"]] == [False, True]
