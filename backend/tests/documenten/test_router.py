from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
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


def test_duplicaat_upload_geeft_bestandsnaam_en_datum_geen_kale_uuid(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    """Design-pass taak 5: de duplicaat-verwijzing moet genoeg zijn voor een klikbare link
    (bestandsnaam + uploaddatum van het origineel), niet alleen een UUID die de gebruiker niets
    zegt."""
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    origineel = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("origineel.pdf", b"%PDF-1.4 zelfde-inhoud", "application/pdf")},
        headers=headers,
    )
    origineel_id = origineel.json()["document_id"]

    duplicaat = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("kopie.pdf", b"%PDF-1.4 zelfde-inhoud", "application/pdf")},
        headers=headers,
    )
    assert duplicaat.status_code == 201, duplicaat.text
    referentie = duplicaat.json()["mogelijk_duplicaat_van"]
    assert referentie is not None
    assert referentie["document_id"] == origineel_id
    assert referentie["bestandsnaam"] == "origineel.pdf"
    assert "aangemaakt_op" in referentie


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


# --- Lijst/detail/bestand ------------------------------------------------------------------


def test_documenten_lijst_zonder_scope_faalt(gescoopte_gebruiker: uuid.UUID) -> None:
    andere_administratie_id = uuid.uuid4()
    resp = client.get(
        f"/administraties/{andere_administratie_id}/documenten", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
    )
    assert resp.status_code == 403


def test_documenten_lijst_bevat_geuploade_documenten(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("lijst-test.pdf", b"%PDF-1.4 lijst-test", "application/pdf")},
        headers=headers,
    )
    resp = client.get(f"/administraties/{administratie_id}/documenten", headers=headers)
    assert resp.status_code == 200, resp.text
    bestandsnamen = [d["bestandsnaam"] for d in resp.json()["documenten"]]
    assert "lijst-test.pdf" in bestandsnamen


def test_documenten_lijst_verrijkt_duplicaat_met_bestandsnaam(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("lijst-origineel.pdf", b"%PDF-1.4 lijst-dup", "application/pdf")},
        headers=headers,
    )
    client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("lijst-kopie.pdf", b"%PDF-1.4 lijst-dup", "application/pdf")},
        headers=headers,
    )
    resp = client.get(f"/administraties/{administratie_id}/documenten", headers=headers)
    kopie = next(d for d in resp.json()["documenten"] if d["bestandsnaam"] == "lijst-kopie.pdf")
    assert kopie["mogelijk_duplicaat_van"]["bestandsnaam"] == "lijst-origineel.pdf"


def test_document_detail_bevat_tijdlijn_en_veldvoorstel(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    ubl = (
        b'<?xml version="1.0"?><Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:'
        b'CommonBasicComponents-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:'
        b'CommonAggregateComponents-2"><cbc:ID>F-1</cbc:ID>'
        b"<cac:LegalMonetaryTotal><cbc:PayableAmount>100.00</cbc:PayableAmount>"
        b"</cac:LegalMonetaryTotal></Invoice>"
    )
    upload = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("detail-test.xml", ubl, "application/xml")},
        headers=headers,
    )
    document_id = upload.json()["document_id"]

    resp = client.get(f"/administraties/{administratie_id}/documenten/{document_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "te_controleren"
    assert body["veldvoorstel"]["factuurnummer"] == "F-1"
    naar_statussen = [g["naar_status"] for g in body["tijdlijn"]]
    assert naar_statussen == ["ontvangen", "extractie_bezig", "te_controleren"]


def test_document_detail_onbekend_document_geeft_404(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    resp = client.get(
        f"/administraties/{administratie_id}/documenten/{uuid.uuid4()}",
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    assert resp.status_code == 404


def test_document_bestand_download(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    inhoud = b"%PDF-1.4 downloadtest-bytes"
    upload = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("download-test.pdf", inhoud, "application/pdf")},
        headers=headers,
    )
    document_id = upload.json()["document_id"]

    resp = client.get(f"/administraties/{administratie_id}/documenten/{document_id}/bestand", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content == inhoud
    assert resp.headers["content-type"] == "application/pdf"


def test_documenten_lijst_cross_tenant_onzichtbaar(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
) -> None:
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("geheim.pdf", b"%PDF-1.4 geheim", "application/pdf")},
        headers=headers,
    )

    andere_administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere', :rlz)"),
            {"id": andere_administratie_id, "rlz": f"rlz-{andere_administratie_id}"},
        )
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=andere_administratie_id
    )

    resp = client.get(f"/administraties/{andere_administratie_id}/documenten", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["documenten"] == []


def _upload(headers: dict[str, str], administratie_id: uuid.UUID, *, bestandsnaam: str = "te-verwijderen.pdf") -> str:
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": (bestandsnaam, b"%PDF-1.4 " + uuid.uuid4().bytes, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


class TestDocumentVerwijderenEnHerstellen:
    def test_verwijderen_geeft_status_verwijderd_en_verdwijnt_uit_de_lijst(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verwijderen",
            json={"reden": "Foute administratie geselecteerd"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"document_id": document_id, "status": "verwijderd"}

        lijst = client.get(f"/administraties/{administratie_id}/documenten", headers=headers).json()["documenten"]
        assert document_id not in {d["id"] for d in lijst}

    def test_verwijderen_zonder_reden_mag(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verwijderen", json={}, headers=headers
        )
        assert resp.status_code == 200, resp.text

    def test_toon_verwijderd_zet_hem_er_weer_bij(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)
        client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verwijderen", json={}, headers=headers
        )

        resp = client.get(f"/administraties/{administratie_id}/documenten?toon_verwijderd=true", headers=headers)
        assert document_id in {d["id"] for d in resp.json()["documenten"]}

    def test_herstellen_zet_hem_terug_op_de_vorige_status(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)
        client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verwijderen", json={}, headers=headers
        )

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/herstellen", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"document_id": document_id, "status": "te_controleren"}

        lijst = client.get(f"/administraties/{administratie_id}/documenten", headers=headers).json()["documenten"]
        assert document_id in {d["id"] for d in lijst}

    def test_herstellen_van_niet_verwijderd_document_geeft_409(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        document_id = _upload(headers, administratie_id)

        resp = client.post(f"/administraties/{administratie_id}/documenten/{document_id}/herstellen", headers=headers)
        assert resp.status_code == 409

    def test_verwijderen_zonder_scope_faalt(self, gescoopte_gebruiker: uuid.UUID) -> None:
        resp = client.post(
            f"/administraties/{uuid.uuid4()}/documenten/{uuid.uuid4()}/verwijderen",
            json={},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403

    def test_verwijderen_onbekend_document_geeft_404(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{uuid.uuid4()}/verwijderen",
            json={},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 404
