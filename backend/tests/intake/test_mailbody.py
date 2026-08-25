"""Mail-body bij het boekingsvoorstel (feedbackronde 25-08 deel 3, punt 1): de intake bewaart de
platte mail-tekst op het intake-bericht (1a), het controlescherm toont 'm (1b) en hij gaat als
HINT mee in toewijzing én AI-extractie — tenaamstelling blijft leidend (1c)."""

from __future__ import annotations

import uuid
from email.message import EmailMessage

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.extractie import splitsing as splitsing_extractie
from app.extractie.splitsing import FactuurSegment, met_mail_context
from app.intake import verwerking
from app.intake.eml import parse_eml
from app.intake.mailbody import body_tekst_uit_bericht, html_naar_tekst, strip_ruis
from app.intake.toewijzing import bepaal_toewijzing, vind_administratie_hint_in_tekst
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_eml, bouw_pdf, bouw_ubl

client = TestClient(app)


class TestBodyExtractie:
    def test_platte_tekst_zonder_handtekening(self) -> None:
        m = EmailMessage()
        m.set_content("Hoi Peter,\n\nDit is voor Oirschot.\n\nMet vriendelijke groet,\nJan\n06-12345678\n")
        assert body_tekst_uit_bericht(m) == "Hoi Peter,\n\nDit is voor Oirschot."

    def test_rfc3676_scheider_en_quote_vallen_weg(self) -> None:
        assert strip_ruis("Factuur voor Molenhof.\n-- \nJan de Vries\nAK") == "Factuur voor Molenhof."
        assert strip_ruis("Zie bijlage.\nOp 25 aug 2026 schreef Jan <j@x.nl>:\n> oude tekst") == "Zie bijlage."
        assert strip_ruis("Dank.\n\nVan: Piet\nVerzonden: gisteren\nOnderwerp: re") == "Dank.\n"

    def test_disclaimer_wordt_afgekapt(self) -> None:
        tekst = "Hierbij de factuur.\nDit bericht is uitsluitend bestemd voor de geadresseerde en kan vertrouwelijk"
        assert strip_ruis(tekst) == "Hierbij de factuur."

    def test_html_naar_tekst(self) -> None:
        html = (
            "<html><head><style>p{color:red}</style></head>"
            "<body><p>Hoi,</p><p>Voor <b>Molenhof Beheer</b> &amp; co.</p></body></html>"
        )
        assert html_naar_tekst(html).split() == ["Hoi,", "Voor", "Molenhof", "Beheer", "&", "co."]

    def test_alleen_html_body_wordt_tekst(self) -> None:
        eml = bouw_eml(body=None, body_html="<p>Deze factuur is voor <b>Oirschot</b>.</p><p>-- </p><p>Jan</p>")
        assert parse_eml(eml).body_tekst == "Deze factuur is voor Oirschot."

    def test_plain_gaat_voor_html(self) -> None:
        eml = bouw_eml(body="Platte versie.", body_html="<p>HTML-versie.</p>")
        assert parse_eml(eml).body_tekst == "Platte versie."

    def test_geen_tekstdeel_is_none(self) -> None:
        eml = bouw_eml(body=None, bijlagen=[("f.pdf", bouw_pdf(1), "application", "pdf")])
        assert parse_eml(eml).body_tekst is None

    def test_lange_body_wordt_zichtbaar_begrensd(self) -> None:
        m = EmailMessage()
        m.set_content("x" * 30_000)
        tekst = body_tekst_uit_bericht(m)
        assert tekst is not None and len(tekst) <= 20_000 and tekst.endswith("[… afgekapt]")


class TestBodyOpBericht:
    def test_body_bewaard_en_gedeeld_door_alle_documenten_uit_de_mail(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(
            body="Hoi, twee facturen voor jullie.\n\nGroeten,\nJan",
            bijlagen=[
                ("f1.xml", bouw_ubl(klant="BLOW B.V.", factuurnummer="A-1"), "application", "xml"),
                ("f2.xml", bouw_ubl(klant="BLOW Holding", factuurnummer="A-2"), "application", "xml"),
            ],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert [r.uitkomst for r in resultaat.bijlagen] == ["toegewezen", "verzamelbak"]
        with admin_engine.connect() as conn:
            body = conn.execute(
                text("SELECT body_tekst FROM boekhouding.intake_bericht WHERE id = :id"), {"id": resultaat.bericht_id}
            ).scalar_one()
            koppelingen = conn.execute(
                text("SELECT intake_bericht_id FROM boekhouding.document WHERE intake_bericht_id = :id"),
                {"id": resultaat.bericht_id},
            ).all()
        assert body == "Hoi, twee facturen voor jullie."
        assert len(koppelingen) == 2  # beide documenten delen dezelfde body via de FK

    def test_controlescherm_dto_draagt_herkomst_mail(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        eml = bouw_eml(
            onderwerp="Factuur Bouwmaat augustus",
            body="Dit is voor BLOW.",
            bijlagen=[("f.xml", bouw_ubl(klant="BLOW B.V.", factuurnummer="B-7"), "application", "xml")],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        document_id = resultaat.bijlagen[0].document_id
        resp = client.get(
            f"/administraties/{administratie_heet_blow}/documenten/{document_id}",
            headers={"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"},
        )
        assert resp.status_code == 200
        herkomst = resp.json()["herkomst_mail"]
        assert herkomst == {
            "afzender": "administratie@bouwmaat.nl",
            "onderwerp": "Factuur Bouwmaat augustus",
            "ontvangen_op": "2026-08-07T09:00:00+02:00",
            "body_tekst": "Dit is voor BLOW.",
            "bron": "eml_upload",
        }

    def test_upload_zonder_mail_heeft_geen_herkomst(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        upload = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("los.pdf", b"%PDF-1.4 mailbody-los", "application/pdf")},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
        document_id = upload.json()["document_id"]
        resp = client.get(f"/administraties/{administratie_id}/documenten/{document_id}", headers=headers)
        assert resp.json()["herkomst_mail"] is None


class TestBodyAlsHint:
    def test_body_noemt_administratie_wordt_suggestie_nooit_toewijzing(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        # Tenaamstelling matcht niets (twijfel) → verzamelbak; de body noemt BLOW → suggestie.
        eml = bouw_eml(
            body="Hoi, deze is voor BLOW. Groet, Jan",
            bijlagen=[("f.xml", bouw_ubl(klant="Onbekende Klant B.V."), "application", "xml")],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT administratie_id, toewijzing_suggestie_administratie_id, toewijzing_suggestie_bron "
                    "FROM boekhouding.document WHERE id = :id"
                ),
                {"id": resultaat.bijlagen[0].document_id},
            ).one()
        assert rij.administratie_id is None
        assert rij.toewijzing_suggestie_administratie_id == administratie_heet_blow
        assert rij.toewijzing_suggestie_bron == "mail_body"

    def test_tenaamstelling_blijft_leidend_boven_de_body(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(
            body="Volgens mij is dit voor Iemand Anders.",
            bijlagen=[("f.xml", bouw_ubl(klant="BLOW B.V."), "application", "xml")],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        assert resultaat.bijlagen[0].detail.startswith("tenaamstelling_register")

    def test_gelijkspel_tussen_administraties_geeft_geen_hint(
        self, administratie_heet_blow: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.db.session import scoped_session

        tweede = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.administratie (id, naam, rlz_admin_id, actief) "
                    "VALUES (:id, :naam, :rlz, true)"
                ),
                {"id": tweede, "naam": "BLOW Vastgoed B.V.", "rlz": f"rlz-{tweede}"},
            )
        try:
            with scoped_session(None) as session:
                assert vind_administratie_hint_in_tekst(session, "dit is voor blow") is None  # 2× 'blow' = gelijkspel
                assert vind_administratie_hint_in_tekst(session, "voor BLOW Vastgoed graag") == tweede
                assert vind_administratie_hint_in_tekst(session, "niets herkenbaars") is None
                assert vind_administratie_hint_in_tekst(session, None) is None
                besluit = bepaal_toewijzing(session, tenaamstelling=None, afzender=None, body_hint="voor BLOW Vastgoed")
                assert besluit.administratie_id is None and besluit.suggestie_bron == "mail_body"
        finally:
            with admin_engine.begin() as conn:
                conn.execute(text("DELETE FROM platform.administratie WHERE id = :id"), {"id": tweede})

    def test_body_gaat_bsn_gefilterd_mee_in_de_ai_opdracht(self) -> None:
        opdracht = met_mail_context("Doe iets.", "Factuur voor Oirschot, BSN 111222333 van de medewerker.")
        assert opdracht.startswith("Doe iets.")
        assert "Oirschot" in opdracht and "111222333" not in opdracht
        assert "leidend" in opdracht  # document blijft leidend, mailtekst is hint
        assert met_mail_context("Doe iets.", None) == "Doe iets."
        assert met_mail_context("Doe iets.", "   ") == "Doe iets."
        lang = met_mail_context("X", "a" * 10_000)
        assert len(lang) < 4_300 and lang.endswith(">>>")

    def test_intake_ai_krijgt_de_body_als_context(
        self, intake_ai_aan: None, gescoopte_gebruiker: uuid.UUID, monkeypatch, administratie_heet_blow: uuid.UUID
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        gezien: dict = {}

        def fake(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            gezien["mail_context"] = mail_context
            return [FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-1", 0.95)]

        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", fake)
        monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", fake)
        eml = bouw_eml(
            body="Hoi, voor BLOW graag.\n\nMvg\nJan", bijlagen=[("f.pdf", bouw_pdf(1), "application", "pdf")]
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        assert gezien["mail_context"] == "Hoi, voor BLOW graag."
