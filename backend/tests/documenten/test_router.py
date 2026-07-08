from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_upload_zonder_authenticatie_faalt(administratie_id: uuid.UUID) -> None:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code in (401, 403)


def test_upload_zonder_scope_op_administratie_faalt(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    andere_administratie_id = uuid.uuid4()
    resp = client.post(
        f"/administraties/{andere_administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", b"%PDF-1.4", "application/pdf")},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 403


def test_upload_met_scope_slaagt(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", b"%PDF-1.4 echte inhoud", "application/pdf")},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "te_controleren"
    assert body["mogelijk_duplicaat_van"] is None


def test_beheerder_kan_altijd_uploaden(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", b"%PDF-1.4 beheerder-upload", "application/pdf")},
        headers=_bearer(beheerder_id, rol="beheerder"),
    )
    assert resp.status_code == 201, resp.text


def test_upload_verkeerd_bestandstype_geeft_415(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.docx", b"iets", "application/msword")},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 415


def test_upload_leeg_bestand_geeft_400(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", b"", "application/pdf")},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 400


def test_upload_te_groot_bestand_geeft_413(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    te_groot = b"0" * (settings.document_max_bytes + 1)
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", te_groot, "application/pdf")},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 413
