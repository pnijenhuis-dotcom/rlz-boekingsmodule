"""Besluit Peter 18-09 (bulk-upload BLOW, 180 documenten): een byte-identieke DIRECTE upload in dezelfde administratie
maakt geen tweede document meer — de service weigert binnen de poort van de twee directe routes
(`directe_upload_poort`, `DocumentAlAanwezig`, router 409 `al_aanwezig`), audit `upload_geweigerd_al_aanwezig`. Alleen
een door een mens VERWIJDERD exemplaar telt niet (opnieuw aanbieden mag — het nieuwe document draagt dan de bestaande
mogelijk-duplicaat-vlag). Buiten de poort (mail-/IMAP-intake, splitsing, verzamelbak, CLI's) blijft `upload_document`
de generieke registratie mét de duplicaatvlag — daar kiest geen mens per bestand."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.documenten import service
from app.documenten.models import DocumentBron, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)
BYTES = b"%PDF-1.4 zilver horeca 25-022711"


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _upload(
    administratie_id: uuid.UUID, actor: uuid.UUID, opslag: LokaleBestandsopslag, naam: str = "factuur.pdf", **kw
):
    """Zoals de directe routes: binnen de poort (klantpagina/sleepzone) — buiten de poort blijft de duplicaatvlag het
    pad."""
    with service.directe_upload_poort():
        return service.upload_document(
            administratie_id=administratie_id, bestandsnaam=naam, inhoud=BYTES, actor_id=actor, opslag=opslag, **kw
        )


def _audit_acties(admin_engine: Engine, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                {"id": record_id},
            )
        ]


def test_tweede_directe_upload_weigert_met_verwijzing_en_audit(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> None:
    eerste = _upload(administratie_id, gescoopte_gebruiker, opslag)
    with pytest.raises(service.DocumentAlAanwezig) as exc:
        _upload(administratie_id, gescoopte_gebruiker, opslag, naam="kopie.pdf")
    detail = exc.value.als_detail()
    assert detail["code"] == "al_aanwezig"
    assert detail["bestaand_document_id"] == str(eerste.document_id)
    assert detail["bestaand_administratie_id"] == str(administratie_id)
    assert detail["bestaand_bestandsnaam"] == "factuur.pdf"
    assert "upload_geweigerd_al_aanwezig" in _audit_acties(admin_engine, eerste.document_id)
    with admin_engine.connect() as conn:
        n = conn.scalar(
            text("SELECT count(*) FROM boekhouding.document WHERE sha256_hash = :h"), {"h": service._hash(BYTES)}
        )
    assert n == 1, "er komt geen tweede document bij"


def test_verwijderd_exemplaar_telt_niet_nieuw_document_met_duplicaatvlag(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    eerste = _upload(administratie_id, gescoopte_gebruiker, opslag)
    service.verwijder_document(
        administratie_id=administratie_id,
        document_id=eerste.document_id,
        actor_id=gescoopte_gebruiker,
        reden="per ongeluk geüpload",
    )
    tweede = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="opnieuw.pdf")
    assert tweede.document_id != eerste.document_id
    assert tweede.mogelijk_duplicaat_van_id == eerste.document_id  # de vlag blijft: de mens ziet het oude exemplaar


def test_buiten_de_poort_blijft_de_generieke_registratie_de_duplicaatvlag_geven(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    """Nazorg-CLI's, splitsing en tests roepen `upload_document` zonder poort aan: ongewijzigd gedrag (vlag, geen
    409)."""
    eerste = _upload(administratie_id, gescoopte_gebruiker, opslag)
    tweede = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="kopie.pdf",
        inhoud=BYTES,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert tweede.document_id != eerste.document_id and tweede.mogelijk_duplicaat_van_id == eerste.document_id


def test_mail_intake_blijft_de_duplicaatregel_volgen(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    eerste = _upload(administratie_id, gescoopte_gebruiker, opslag)
    # Zelfde bytes uit een mailbericht: geen 409 (geen mens op de knop) — nieuw document mét mogelijk-duplicaat-vlag,
    # de duplicaten-/nabundelmotor handelt het af.
    via_mail = _upload(
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        naam="factuur.pdf",
        bron=DocumentBron.EMAIL,
        intake_bericht_id=None,
        afzender_hint="leverancier@example.com",
    )
    assert via_mail.document_id != eerste.document_id
    assert via_mail.mogelijk_duplicaat_van_id == eerste.document_id


def test_klantpagina_route_geeft_409_en_maakt_niets_aan(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    headers = _bearer(gescoopte_gebruiker)
    eerste = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("origineel.pdf", BYTES, "application/pdf")},
        headers=headers,
    )
    assert eerste.status_code == 201, eerste.text
    tweede = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("kopie.pdf", BYTES, "application/pdf")},
        headers=headers,
    )
    assert tweede.status_code == 409, tweede.text
    detail = tweede.json()["detail"]
    assert detail["code"] == "al_aanwezig" and detail["bestaand_document_id"] == eerste.json()["document_id"]
    with admin_engine.connect() as conn:
        n = conn.scalar(
            text("SELECT count(*) FROM boekhouding.document WHERE administratie_id = :a AND sha256_hash = :h"),
            {"a": administratie_id, "h": service._hash(BYTES)},
        )
    assert n == 1


def test_geboekt_exemplaar_telt_als_aanwezig(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> None:
    eerste = _upload(administratie_id, gescoopte_gebruiker, opslag)
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": eerste.document_id}
        )
    with pytest.raises(service.DocumentAlAanwezig) as exc:
        _upload(administratie_id, gescoopte_gebruiker, opslag, naam="nog-eens.pdf")
    assert exc.value.status == DocumentStatus.GEBOEKT
