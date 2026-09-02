"""Blok B4 (02-09, diagnose punten 2+3): bijlage-paren bundelen (ingesloten-PDF-hash → naamstam →
losse UBL mét ingesloten PDF), handmatig samenvoegen mét poorten en ongedaan maken, en de
begrenzing van het afzender-leren (kantoor-/doorstuurdomeinen + flip-detectie)."""

from __future__ import annotations

import base64
import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentStatus
from app.documenten.ubl import lees_ingesloten_pdf
from app.intake import verwerking, verzamelbak
from app.intake.bundeling import (
    REDEN_INGESLOTEN_ALLEEN,
    REDEN_INGESLOTEN_HASH,
    REDEN_NAAMSTAM,
    BijlagePaar,
    bundel_bijlagen,
)
from app.intake.eml import IntakeBijlage
from app.intake.models import ToewijzingRegel
from app.intake.toewijzing import AFZENDER_MEERDUIDIG_VANAF, afzender_uitgesloten, bepaal_toewijzing, leer_toewijzing
from tests.intake.conftest import bouw_eml, bouw_pdf, bouw_ubl


def bouw_ubl_met_pdf(pdf: bytes, *, naam: str = "factuur.pdf", klant: str = "Onbekend BV") -> bytes:
    ubl = bouw_ubl(klant=klant)
    adr = (
        "<cac:AdditionalDocumentReference><cbc:ID>" + naam + "</cbc:ID>"
        "<cbc:DocumentType>PrimaryImage</cbc:DocumentType><cac:Attachment>"
        '<cbc:EmbeddedDocumentBinaryObject mimeCode="application/pdf" filename="' + naam + '">'
        + base64.b64encode(pdf).decode()
        + "</cbc:EmbeddedDocumentBinaryObject></cac:Attachment></cac:AdditionalDocumentReference>"
    ).encode()
    sluit = b"</Invoice>"
    assert sluit in ubl
    return ubl.replace(sluit, adr + sluit, 1)


def bijlage(naam: str, inhoud: bytes) -> IntakeBijlage:
    ct = "application/pdf" if naam.lower().endswith(".pdf") else "application/xml"
    return IntakeBijlage(bestandsnaam=naam, inhoud=inhoud, content_type=ct)


class TestLeesIngeslotenPdf:
    def test_leest_primary_image(self) -> None:
        pdf = bouw_pdf(1)
        gevonden = lees_ingesloten_pdf(bouw_ubl_met_pdf(pdf, naam="2026-8151.pdf"))
        assert gevonden is not None
        assert gevonden.bestandsnaam == "2026-8151.pdf"
        assert gevonden.inhoud == pdf

    def test_zonder_bijlage_of_kapot_is_none(self) -> None:
        assert lees_ingesloten_pdf(bouw_ubl()) is None
        assert lees_ingesloten_pdf(b"<niet>xml") is None


class TestBundelBijlagen:
    def test_ingesloten_hash_paart_ubl_en_pdf(self) -> None:
        pdf = bouw_pdf(1)
        ubl = bijlage("2026-8151.xml", bouw_ubl_met_pdf(pdf))
        los = bijlage("andere-naam.pdf", pdf)
        items = bundel_bijlagen([los, ubl])
        assert len(items) == 1 and isinstance(items[0], BijlagePaar)
        assert items[0].reden == REDEN_INGESLOTEN_HASH
        assert items[0].pdf is los and items[0].pdf_is_losse_bijlage

    def test_naamstam_alleen_ondubbelzinnig(self) -> None:
        ubl = bijlage("114164.xml", bouw_ubl())
        pdf = bijlage("114164.PDF", bouw_pdf(1))
        items = bundel_bijlagen([ubl, pdf])
        assert len(items) == 1 and isinstance(items[0], BijlagePaar) and items[0].reden == REDEN_NAAMSTAM
        # Twee PDF's met dezelfde stam = twijfel = geen paar (drie losse items).
        pdf2 = bijlage("114164.pdf", bouw_pdf(2))
        items = bundel_bijlagen([ubl, pdf, pdf2])
        assert len(items) == 3 and not any(isinstance(i, BijlagePaar) for i in items)

    def test_losse_ubl_met_ingesloten_pdf_krijgt_beeld(self) -> None:
        items = bundel_bijlagen([bijlage("f.xml", bouw_ubl_met_pdf(bouw_pdf(1)))])
        assert isinstance(items[0], BijlagePaar)
        assert items[0].reden == REDEN_INGESLOTEN_ALLEEN and not items[0].pdf_is_losse_bijlage

    def test_nooit_twee_ubls_of_twee_pdfs(self) -> None:
        items = bundel_bijlagen([bijlage("a.xml", bouw_ubl()), bijlage("b.xml", bouw_ubl()), bijlage("c.pdf", bouw_pdf(1))])
        assert len(items) == 3


class TestVerwerkEmlBundeling:
    def test_ubl_plus_pdf_in_een_mail_wordt_een_document_met_beeld(self, gescoopte_gebruiker: uuid.UUID) -> None:
        pdf = bouw_pdf(1)
        eml = bouw_eml(
            afzender="peter@ak-nijenhuis.nl",
            bijlagen=[
                ("2026-8151.pdf", pdf, "application", "pdf"),
                ("2026-8151.xml", bouw_ubl_met_pdf(pdf, naam="2026-8151.pdf", klant="Belastingbutler B.V."), "application", "xml"),
            ],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        uitkomsten = {r.bestandsnaam: r for r in resultaat.bijlagen}
        assert uitkomsten["2026-8151.xml"].uitkomst == "verzamelbak"
        assert uitkomsten["2026-8151.pdf"].uitkomst == "gebundeld"
        assert uitkomsten["2026-8151.pdf"].document_id == uitkomsten["2026-8151.xml"].document_id
        assert "ingesloten_pdf_hash" in (uitkomsten["2026-8151.xml"].detail or "")

        items = verzamelbak.lijst_verzamelbak()
        assert len(items) == 1
        assert items[0].tenaamstelling == "Belastingbutler B.V."
        assert items[0].beeld_bestandsnaam == "2026-8151.pdf"
        # De verzamelbak-leesroute toont het beeld (PDF); vorm=data geeft de UBL.
        inhoud, naam, ct = verzamelbak.haal_bijlage_op(document_id=items[0].document_id)
        assert ct == "application/pdf" and naam == "2026-8151.pdf" and inhoud == pdf
        inhoud, naam, ct = verzamelbak.haal_bijlage_op(document_id=items[0].document_id, vorm="data")
        assert naam == "2026-8151.xml" and b"Belastingbutler" in inhoud

    def test_ubl_samenvatting_voor_losse_ubl(self, gescoopte_gebruiker: uuid.UUID) -> None:
        eml = bouw_eml(bijlagen=[("f.xml", bouw_ubl(klant="Onbekend BV"), "application", "xml")])
        doc_id = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0].document_id
        s = verzamelbak.ubl_samenvatting(document_id=doc_id)
        assert s.afnemer == "Onbekend BV"
        assert s.leverancier == "Bouwmaat Nederland B.V."
        assert s.factuurnummer == "F-2026-001"
        assert s.regelaantal == 1


class TestSamenvoegen:
    def _twee_rijen(self, actor: uuid.UUID, *, zelfde_mail: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
        pdf_bijlage = ("los.pdf", bouw_pdf(1), "application", "pdf")
        ubl_bijlage = ("anders.xml", bouw_ubl(klant="Onbekend BV"), "application", "xml")
        if zelfde_mail:
            r = verwerking.verwerk_eml(bouw_eml(bijlagen=[pdf_bijlage, ubl_bijlage], message_id="<m1@x>"), actor_id=actor)
            ubl_id = next(b.document_id for b in r.bijlagen if b.bestandsnaam == "anders.xml")
            pdf_id = next(b.document_id for b in r.bijlagen if b.bestandsnaam == "los.pdf")
        else:
            ubl_id = verwerking.verwerk_eml(bouw_eml(bijlagen=[ubl_bijlage], message_id="<m2@x>"), actor_id=actor).bijlagen[0].document_id
            pdf_id = verwerking.verwerk_eml(bouw_eml(bijlagen=[pdf_bijlage], message_id="<m3@x>"), actor_id=actor).bijlagen[0].document_id
        assert ubl_id and pdf_id
        return ubl_id, pdf_id

    def test_samenvoegen_ubl_leidend_pdf_wordt_beeld_en_ongedaan(self, gescoopte_gebruiker: uuid.UUID) -> None:
        ubl_id, pdf_id = self._twee_rijen(gescoopte_gebruiker)
        assert {i.document_id for i in verzamelbak.lijst_verzamelbak()} == {ubl_id, pdf_id}

        r = verzamelbak.voeg_samen(leidend_document_id=ubl_id, ander_document_id=pdf_id, actor_id=gescoopte_gebruiker)
        assert r.beeld_bestandsnaam == "los.pdf" and r.waarschuwingen == []
        items = verzamelbak.lijst_verzamelbak()
        assert [i.document_id for i in items] == [ubl_id]
        assert items[0].beeld_bestandsnaam == "los.pdf"
        assert items[0].samengevoegd_document_id == pdf_id
        with scoped_session(None) as session:
            ander = session.get(Document, pdf_id)
            assert ander is not None
            assert ander.status == DocumentStatus.SAMENGEVOEGD and ander.samengevoegd_in_id == ubl_id
        # Het beeld is de PDF, de data blijft de UBL.
        _, naam, ct = verzamelbak.haal_bijlage_op(document_id=ubl_id)
        assert naam == "los.pdf" and ct == "application/pdf"

        teruggezet = verzamelbak.maak_samenvoegen_ongedaan(document_id=ubl_id, actor_id=gescoopte_gebruiker)
        assert teruggezet == pdf_id
        assert {i.document_id for i in verzamelbak.lijst_verzamelbak()} == {ubl_id, pdf_id}
        with scoped_session(None) as session:
            leidend = session.get(Document, ubl_id)
            assert leidend is not None and leidend.bron_opslag_pad is None

    def test_poorten(self, gescoopte_gebruiker: uuid.UUID) -> None:
        ubl_id, pdf_id = self._twee_rijen(gescoopte_gebruiker, zelfde_mail=False)
        with pytest.raises(verzamelbak.SamenvoegenGeweigerd):
            verzamelbak.voeg_samen(leidend_document_id=ubl_id, ander_document_id=ubl_id, actor_id=gescoopte_gebruiker)
        # Twee PDF's: alleen mét bevestiging.
        pdf2 = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("tweede.pdf", bouw_pdf(2), "application", "pdf")], message_id="<m4@x>"),
            actor_id=gescoopte_gebruiker,
        ).bijlagen[0].document_id
        with pytest.raises(verzamelbak.ZelfdeTypeBevestigingNodig):
            verzamelbak.voeg_samen(leidend_document_id=pdf_id, ander_document_id=pdf2, actor_id=gescoopte_gebruiker)
        # Ander intake-bericht = waarschuwing, geen blokkade.
        r = verzamelbak.voeg_samen(leidend_document_id=ubl_id, ander_document_id=pdf_id, actor_id=gescoopte_gebruiker)
        assert any("verschillende e-mails" in w for w in r.waarschuwingen)
        # Leidend heeft nu een beeld → nogmaals samenvoegen geweigerd; de samengevoegde rij is geen bak-rij meer.
        with pytest.raises(verzamelbak.SamenvoegenGeweigerd):
            verzamelbak.voeg_samen(leidend_document_id=ubl_id, ander_document_id=pdf2, actor_id=gescoopte_gebruiker)
        with pytest.raises(verzamelbak.DocumentNietInVerzamelbak, match="samengevoegd"):
            verzamelbak.wijs_toe(document_id=pdf_id, administratie_id=uuid.uuid4(), actor_id=gescoopte_gebruiker) if False else verzamelbak.hoort_niet_bij_ons(document_id=pdf_id, actor_id=gescoopte_gebruiker, reden="test")


class TestAfzenderLerenBegrensd:
    def test_kantoordomein_is_uitgesloten_incl_subdomein(self) -> None:
        assert afzender_uitgesloten("peter@ak-nijenhuis.nl")
        assert afzender_uitgesloten("iemand@mail.kempengroep.nl")
        assert not afzender_uitgesloten("facturen@bouwmaat.nl")
        assert not afzender_uitgesloten(None)

    def test_uitgesloten_afzender_leert_geen_regel_en_wijst_niet_toe(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            leer_toewijzing(
                session,
                administratie_id=administratie_heet_blow,
                actor_id=gescoopte_gebruiker,
                tenaamstelling=None,
                afzender="peter@ak-nijenhuis.nl",
            )
        with scoped_session(None) as session:
            assert session.scalars(select(ToewijzingRegel).where(ToewijzingRegel.soort == "afzender")).all() == []
            besluit = bepaal_toewijzing(session, tenaamstelling=None, afzender="peter@ak-nijenhuis.nl")
        assert besluit.administratie_id is None and besluit.suggestie_administratie_id is None

    def test_flip_detectie_deactiveert_meerduidige_afzender(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine, monkeypatch
    ) -> None:
        from sqlalchemy import text

        monkeypatch.setattr(settings, "intake_afzender_uitgesloten_domeinen", [])
        # Twee extra administraties als omklap-doelen.
        extra: list[uuid.UUID] = []
        with admin_engine.begin() as conn:
            for naam in ("Doel Twee B.V.", "Doel Drie B.V."):
                nieuw = uuid.uuid4()
                conn.execute(
                    text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
                    {"id": nieuw, "naam": naam, "rlz": f"test-{nieuw}"},
                )
                extra.append(nieuw)
        afzender = "admin@kempenrecreatie.nl"
        doelen = [administratie_heet_blow, extra[0], extra[1]]
        assert AFZENDER_MEERDUIDIG_VANAF == 3
        for doel in doelen:
            with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
                leer_toewijzing(session, administratie_id=doel, actor_id=gescoopte_gebruiker, tenaamstelling=None, afzender=afzender)
        with scoped_session(None) as session:
            regels = session.scalars(
                select(ToewijzingRegel).where(ToewijzingRegel.soort == "afzender", ToewijzingRegel.sleutel == afzender)
            ).all()
            # Eerste leer + één omklap = twee rijen; de derde (meerduidig) staat als INACTIEF spoor
            # (zo blijft de historie meerduidig) en de actieve regel is gedeactiveerd.
            assert len(regels) == 3 and all(not r.actief for r in regels)
            besluit = bepaal_toewijzing(session, tenaamstelling=None, afzender=afzender)
            assert besluit.administratie_id is None
            # Ook terug naar het eerste doel wordt niet meer geleerd (historie blijft meerduidig).
        with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
            leer_toewijzing(session, administratie_id=doelen[0], actor_id=gescoopte_gebruiker, tenaamstelling=None, afzender=afzender)
        with scoped_session(None) as session:
            assert session.scalars(
                select(ToewijzingRegel).where(ToewijzingRegel.sleutel == afzender, ToewijzingRegel.actief.is_(True))
            ).first() is None
