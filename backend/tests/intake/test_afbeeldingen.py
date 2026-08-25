"""Afbeeldingsformaten (feedbackronde 25-08 deel 3, punt 2): JPEG/PNG/HEIC via mail én upload →
deterministisch PDF, origineel bewaard, logo-ruis buiten de verzamelbak, onbruikbaar zichtbaar."""

from __future__ import annotations

import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine, text

from app.config import settings
from app.extractie.splitsing import FactuurSegment
from app.intake import verwerking
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_eml

client = TestClient(app)


def _jpeg(breedte: int = 1200, hoogte: int = 1600, kleur=(240, 240, 240)) -> bytes:
    beeld = Image.new("RGB", (breedte, hoogte), kleur)
    buffer = io.BytesIO()
    beeld.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _document(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT administratie_id, status, bestandsnaam, opslag_pad, bron_opslag_pad, bron_bestandsnaam, "
                "bron_content_type, bron FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()


class TestMailbijlagen:
    def test_foto_wordt_pdf_met_origineel_als_brondocument(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, opslag
    ) -> None:
        # Intake-AI staat uit (testconfig-default) → zichtbaar in de verzamelbak, als PDF.
        foto = _jpeg()
        eml = bouw_eml(bijlagen=[("IMG_0412.jpg", foto, "image", "jpeg")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker, opslag=opslag)
        r = resultaat.bijlagen[0]
        assert r.uitkomst == "verzamelbak"
        assert r.bestandsnaam == "IMG_0412.jpg"
        assert r.detail.startswith("omgezet naar IMG_0412.pdf (JPEG) · intake_ai_uitgeschakeld")
        rij = _document(admin_engine, r.document_id)
        assert rij.bestandsnaam == "IMG_0412.pdf" and rij.opslag_pad.endswith(".pdf")
        assert rij.bron_bestandsnaam == "IMG_0412.jpg" and rij.bron_content_type == "image/jpeg"
        assert opslag.lezen(pad=rij.bron_opslag_pad) == foto  # origineel byte-gelijk bewaard
        assert opslag.lezen(pad=rij.opslag_pad).startswith(b"%PDF-1.4")

    def test_zelfde_foto_uit_zelfde_mail_opnieuw_is_idempotent(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, opslag
    ) -> None:
        """Deterministische omzetting → dezelfde sha256 → de herverwerkings-idempotentie werkt."""
        eml = bouw_eml(message_id="<foto-1@test>", bijlagen=[("f.jpg", _jpeg(800, 800), "image", "jpeg")])
        eerste = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker, opslag=opslag)
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.intake_bericht SET detail = CAST(:d AS jsonb) WHERE id = :id"),
                {"id": eerste.bericht_id, "d": '{"verwerking": "bezig"}'},
            )
        tweede = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker, opslag=opslag)
        assert tweede.bijlagen[0].document_id == eerste.bijlagen[0].document_id

    def test_inline_logo_en_te_klein_plaatje_blijven_buiten_de_verzamelbak(
        self, gescoopte_gebruiker: uuid.UUID, opslag
    ) -> None:
        from email.message import EmailMessage

        mail = EmailMessage()
        mail["From"] = "jan@bouwmaat.nl"
        mail["Subject"] = "Factuur"
        mail["Message-ID"] = f"<{uuid.uuid4()}@test>"
        mail.set_content("Zie bijlage.")
        mail.add_alternative('<p>Zie bijlage.</p><img src="cid:logo1">', subtype="html")
        # Inline logo mét Content-ID (groot genoeg, maar inline = handtekening).
        mail.get_payload()[1].add_related(_jpeg(900, 900), "image", "jpeg", cid="<logo1>", filename="logo.jpg")
        mail.add_attachment(_jpeg(200, 80), maintype="image", subtype="jpeg", filename="icoon.jpg")
        mail.add_attachment(_jpeg(1000, 700), maintype="image", subtype="jpeg", filename="bon.jpg")
        resultaat = verwerking.verwerk_eml(mail.as_bytes(), actor_id=gescoopte_gebruiker, opslag=opslag)
        per_naam = {r.bestandsnaam: r for r in resultaat.bijlagen}
        assert per_naam["logo.jpg"].uitkomst == "niet_verwerkbaar" and "inline" in per_naam["logo.jpg"].detail
        assert per_naam["icoon.jpg"].uitkomst == "niet_verwerkbaar" and "te klein" in per_naam["icoon.jpg"].detail
        assert per_naam["bon.jpg"].uitkomst == "verzamelbak" and per_naam["bon.jpg"].document_id is not None

    def test_corrupte_afbeelding_naar_verzamelbak_met_reden(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, opslag
    ) -> None:
        kapot = _jpeg(800, 800)[:300]
        eml = bouw_eml(bijlagen=[("scan.jpg", kapot, "image", "jpeg")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker, opslag=opslag)
        r = resultaat.bijlagen[0]
        assert r.uitkomst == "verzamelbak" and r.detail.startswith("afbeelding_onbruikbaar:")
        rij = _document(admin_engine, r.document_id)
        assert rij.status == "niet_toegewezen" and rij.bestandsnaam == "scan.jpg" and rij.bron_opslag_pad is None
        with admin_engine.connect() as conn:
            reden = conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'niet_toegewezen'"
                ),
                {"id": r.document_id},
            ).scalar_one()
        assert reden.startswith("afbeelding_onbruikbaar: afbeelding niet te decoderen")
        # De verzamelbak-leesroute serveert het origineel als afbeelding, niet als 'xml'.
        resp = client.get(f"/verzamelbak/{r.document_id}/bestand", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("image/jpeg")

    def test_met_intake_ai_gaat_de_pdf_naar_de_splitsingsdetectie_en_wordt_toegewezen(
        self,
        intake_ai_aan: None,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch,
        opslag,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        gezien: dict = {}

        def fake(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            gezien["pdf"] = inhoud
            gezien["paginas"] = paginas
            return [FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-1", 0.95)]

        monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", fake)
        eml = bouw_eml(bijlagen=[("factuurfoto.jpeg", _jpeg(), "image", "jpeg")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker, opslag=opslag)
        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        assert gezien["pdf"].startswith(b"%PDF-1.4") and gezien["paginas"] == 1
        rij = _document(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.administratie_id == administratie_heet_blow
        assert rij.bestandsnaam == "factuurfoto.pdf" and rij.bron_bestandsnaam == "factuurfoto.jpeg"


class TestUploadRoutes:
    def test_klantupload_jpeg_wordt_pdf_en_origineel_is_op_te_halen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        foto = _jpeg(1000, 1400, kleur=(230, 231, 232))
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("bon.JPG", foto, "image/jpeg")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        document_id = resp.json()["document_id"]
        rij = _document(admin_engine, uuid.UUID(document_id))
        assert rij.bestandsnaam == "bon.pdf" and rij.bron_bestandsnaam == "bon.JPG"

        detail = client.get(
            f"/administraties/{administratie_id}/documenten/{document_id}", headers=_bearer(gescoopte_gebruiker)
        )
        assert detail.json()["bron_bestandsnaam"] == "bon.JPG"
        bestand = client.get(
            f"/administraties/{administratie_id}/documenten/{document_id}/bestand", headers=_bearer(gescoopte_gebruiker)
        )
        assert bestand.headers["content-type"] == "application/pdf"
        origineel = client.get(
            f"/administraties/{administratie_id}/documenten/{document_id}/bronbestand",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert origineel.status_code == 200
        assert origineel.headers["content-type"].startswith("image/jpeg") and origineel.content == foto
        assert 'filename="bon.JPG"' in origineel.headers["content-disposition"]

    def test_bronbestand_404_voor_gewone_pdf(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("f.pdf", b"%PDF-1.4 gewone pdf zonder bron", "application/pdf")},
            headers=_bearer(gescoopte_gebruiker),
        )
        document_id = resp.json()["document_id"]
        resp = client.get(
            f"/administraties/{administratie_id}/documenten/{document_id}/bronbestand",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 404

    def test_corrupte_afbeelding_bij_directe_upload_geeft_422(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("kapot.png", b"\x89PNG niet echt", "image/png")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 422 and "Afbeelding onbruikbaar" in resp.json()["detail"]

    def test_heic_kassarapport_mag(self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID) -> None:
        import pillow_heif

        pillow_heif.register_heif_opener()
        buffer = io.BytesIO()
        Image.new("RGB", (700, 900), (250, 250, 250)).save(buffer, format="HEIF", quality=80)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            data={"soort": "kassarapport"},
            files={"bestand": ("kas.heic", buffer.getvalue(), "image/heic")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text

    def test_los_bestand_op_de_werkvoorraad_volgt_de_tenaamstelling_routing(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        from tests.intake.conftest import bouw_ubl

        resp = client.post(
            "/intake/bestand",
            files={"bestand": ("factuur.xml", bouw_ubl(klant="BLOW B.V."), "application/xml")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["uitkomst"] == "toegewezen"
        rij = _document(admin_engine, uuid.UUID(resp.json()["document_id"]))
        assert rij.administratie_id == administratie_heet_blow and rij.bron == "upload"

        # Foto zonder intake-AI → verzamelbak, als PDF mét origineel; geen logo-filter bij een bewuste upload.
        resp = client.post(
            "/intake/bestand",
            files={"bestand": ("klein.jpg", _jpeg(300, 200), "image/jpeg")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 201 and resp.json()["uitkomst"] == "verzamelbak"
        rij = _document(admin_engine, uuid.UUID(resp.json()["document_id"]))
        assert rij.bestandsnaam == "klein.pdf" and rij.bron_bestandsnaam == "klein.jpg" and rij.bron == "upload"

        resp = client.post(
            "/intake/bestand",
            files={"bestand": ("brief.docx", b"PK", "application/octet-stream")},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 415
