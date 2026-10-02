"""Punt 15 run A 02-10 — upload KvK-uittreksel/dossierdocument mét een getypte `geldig_tot` (Peter: "geldig_tot:
Input should be a valid date or datetime, invalid date separator, expected `-`").

Beide upload-routes (veld-app `POST /uren/dossier/upload`, kantoor `POST /uren/kantoor/dossier/{adm}/{gebruiker}/
upload`) accepteren jjjj-mm-dd, dd-mm-jjjj en dd/mm/jjjj via dé ene parser `app.tijd.parse_datum_nl`; een
ongeldige waarde geeft 422 mét een melding in gewone taal ("… schrijf de datum als 31-12-2026") — nooit meer de
Engelse Pydantic-tekst. Guard op het afwezig-pad: zonder `geldig_tot` gedraagt de route zich als vóór 02-10."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.documenten import storage
from app.main import app
from app.security.tokens import create_access_token
from app.tijd import vandaag_nl
from app.uren import service as uren_service
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)
PDF = b"%PDF-1.4 test"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture(autouse=True)
def _lokale_opslag(tmp_path: Path, monkeypatch):
    opslag = storage.LokaleBestandsopslag(tmp_path / "dossier")
    monkeypatch.setattr(storage, "standaard_opslag", lambda: opslag)
    return opslag


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id) -> uuid.UUID:
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zzper, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=zzper)
    return zzper


@pytest.fixture
def boekhouder_met_scope(admin_engine, administratie_id, beheerder_id) -> uuid.UUID:
    boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=administratie_id)
    uren_service.zet_meerwerk_recht(gebruiker_id=boekhouder, ingeschakeld=True, actor_id=beheerder_id)
    return boekhouder


def _over_een_jaar():
    return vandaag_nl() + timedelta(days=365)


def _vormen() -> list[tuple[str, str]]:
    d = _over_een_jaar()
    return [
        ("iso", d.isoformat()),
        ("dd-mm-jjjj", d.strftime("%d-%m-%Y")),
        ("dd/mm/jjjj", d.strftime("%d/%m/%Y")),
    ]


def _kvk_doc(body: dict) -> dict:
    return next(d for d in body["documenten"] if d["code"] == "kvk_uittreksel")


class TestVeldApp:
    @pytest.mark.parametrize(("vorm", "waarde"), _vormen(), ids=[v for v, _ in _vormen()])
    def test_drie_datumvormen_landen_als_dezelfde_kalenderdag(self, administratie_id, zzper_met_scope, vorm, waarde):
        resp = client.post(
            "/uren/dossier/upload",
            data={"administratie_id": str(administratie_id), "type_code": "kvk_uittreksel", "geldig_tot": waarde},
            files={"bestand": ("kvk.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=_bearer(zzper_met_scope, rol="zzper"),
        )
        assert resp.status_code == 200, (vorm, resp.text)
        doc = _kvk_doc(resp.json())
        assert doc["status"] == "ter_controle"
        assert doc["geldig_tot"] == _over_een_jaar().isoformat()

    @pytest.mark.parametrize("waarde", ["31.12.2026", "12/31/2026", "31-02-2027", "volgend jaar"])
    def test_ongeldige_datum_geeft_422_in_gewone_taal(self, administratie_id, zzper_met_scope, waarde):
        resp = client.post(
            "/uren/dossier/upload",
            data={"administratie_id": str(administratie_id), "type_code": "kvk_uittreksel", "geldig_tot": waarde},
            files={"bestand": ("kvk.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=_bearer(zzper_met_scope, rol="zzper"),
        )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert isinstance(detail, str), "één platte NL-melding, geen Pydantic-lijst"
        assert detail.startswith("Geldig tot: ")
        assert "schrijf de datum als 31-12-2026" in detail
        assert "separator" not in detail and "Input should" not in detail
        # Niets opgeslagen.
        headers = _bearer(zzper_met_scope, rol="zzper")
        stand = client.get(f"/uren/dossier?administratie_id={administratie_id}", headers=headers)
        assert stand.status_code == 200 and stand.json()["aantal_ter_controle"] == 0

    def test_afwezig_pad_zonder_geldig_tot_ongewijzigd(self, administratie_id, zzper_met_scope):
        """Guard afwezig-pad: geen `geldig_tot` meesturen → het bestaande 'verplicht'-gedrag van de service
        (kvk_uittreksel vereist een geldig-tot) en géén parser-fout."""
        resp = client.post(
            "/uren/dossier/upload",
            data={"administratie_id": str(administratie_id), "type_code": "kvk_uittreksel"},
            files={"bestand": ("kvk.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=_bearer(zzper_met_scope, rol="zzper"),
        )
        assert resp.status_code == 422, resp.text
        assert "schrijf de datum als" not in resp.json()["detail"]
        # Een leeg veld (zoals een leeggelaten <input type="date">) telt als afwezig.
        resp = client.post(
            "/uren/dossier/upload",
            data={"administratie_id": str(administratie_id), "type_code": "kvk_uittreksel", "geldig_tot": ""},
            files={"bestand": ("kvk.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=_bearer(zzper_met_scope, rol="zzper"),
        )
        assert resp.status_code == 422 and "schrijf de datum als" not in resp.json()["detail"]


class TestKantoor:
    @pytest.mark.parametrize(("vorm", "waarde"), _vormen(), ids=[v for v, _ in _vormen()])
    def test_drie_datumvormen_op_de_kantoorroute(self, administratie_id, zzper, boekhouder_met_scope, vorm, waarde):
        resp = client.post(
            f"/uren/kantoor/dossier/{administratie_id}/{zzper}/upload",
            data={"type_code": "kvk_uittreksel", "geldig_tot": waarde},
            files={"bestand": ("kvk.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=_bearer(boekhouder_met_scope, rol="boekhouding"),
        )
        assert resp.status_code == 200, (vorm, resp.text)
        assert _kvk_doc(resp.json())["geldig_tot"] == _over_een_jaar().isoformat()

    def test_ongeldige_datum_op_de_kantoorroute(self, administratie_id, zzper, boekhouder_met_scope):
        resp = client.post(
            f"/uren/kantoor/dossier/{administratie_id}/{zzper}/upload",
            data={"type_code": "kvk_uittreksel", "geldig_tot": "31.12.2026"},
            files={"bestand": ("kvk.pdf", io.BytesIO(PDF), "application/pdf")},
            headers=_bearer(boekhouder_met_scope, rol="boekhouding"),
        )
        assert resp.status_code == 422, resp.text
        verwacht = "Geldig tot: '31.12.2026' is geen geldige datum — schrijf de datum als 31-12-2026"
        assert resp.json()["detail"] == verwacht
