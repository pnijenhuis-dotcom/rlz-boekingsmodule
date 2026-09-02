"""Blok A 02-09 — RLZ-export-UBL's leesbaar en boekbaar (casus: 97 IC-facturen Universal Nederland →
Universal Steigerbouw onbruikbaar in de verzamelbak, "geen tenaamstelling gelezen" op élke rij):
(A1) de intake leest de tenaamstelling uit cac:PartyName/cbc:Name; (A2) de in de UBL ingesloten
factuur-PDF is overal het beeld (verzamelbak-preview, administratie-bestandroute, RLZ-bijlage via
`bepaal_beeld`); (A3) de nazorg-herlezing neemt UBL-rijen mee zonder AI-gate, zet het beeld in de
bron-kolommen en wijst toe — of zet met `toewijzen=False` de eenduidige match als suggestie."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, select, text

from app.config import settings
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.beeld import (
    HERKOMST_BRON,
    HERKOMST_HOOFDBESTAND,
    HERKOMST_INGESLOTEN,
    BestandenSnapshot,
    bepaal_beeld,
)
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.intake import herlezen, verwerking, verzamelbak
from app.intake.models import ToewijzingRegel
from tests.intake.conftest import bouw_eml, bouw_pdf, bouw_ubl

FIXTURE = Path(__file__).parent / "fixtures" / "rlz_export_ubl.xml"
SINDS = datetime(2026, 8, 25, tzinfo=UTC)


def _rlz_export(klant: str = "BLOW B.V.") -> bytes:
    return FIXTURE.read_bytes().replace(b"BLOW B.V.", klant.encode())


def _rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT administratie_id, status, tenaamstelling, toewijzing_suggestie_administratie_id, "
                "toewijzing_suggestie_bron, bron_bestandsnaam, bron_content_type "
                "FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()


def _tijdlijn_redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0] or ""
            for r in conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :d ORDER BY tijdstip"
                ),
                {"d": document_id},
            )
        ]


def _pre_fix_verzamelbak_rij(
    actor_id: uuid.UUID,
    *,
    klant: str = "BLOW B.V.",
    naam: str = "Universal Nederland B.V - RLZ-2080143001 - 2026-08-01.xml",
) -> uuid.UUID:
    """Een rij zoals de oude parser 'm achterliet: UBL in de bak, tenaamstelling NULL, geen beeld."""
    return documenten_service.registreer_niet_toegewezen_document(
        bestandsnaam=naam,
        inhoud=_rlz_export(klant),
        actor_id=actor_id,
        reden="tenaamstelling_niet_eenduidig",
        soort=DocumentSoort.INKOOPFACTUUR,
        afzender_hint="administratie@universal-steigerbouw.nl",
        tenaamstelling=None,
    )


class TestIntakeLeestRlzExport:
    def test_ic_factuur_wordt_op_tenaamstelling_toegewezen_met_pdf_als_beeld(
        self, gescoopte_gebruiker: uuid.UUID, administratie_heet_blow: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(
            afzender="administratie@universal-steigerbouw.nl",
            bijlagen=[
                ("Universal Nederland B.V - RLZ-2080143001 - 2026-08-01.xml", _rlz_export(), "application", "xml")
            ],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        (r,) = resultaat.bijlagen
        assert r.uitkomst == "toegewezen", r.detail
        assert "tenaamstelling_register" in (r.detail or "")
        assert "beeld: factuur.pdf (ingesloten_pdf)" in (r.detail or "")
        rij = _rij(admin_engine, r.document_id)
        assert rij.administratie_id == administratie_heet_blow
        assert rij.tenaamstelling == "BLOW B.V."
        assert rij.bron_bestandsnaam == "factuur.pdf" and rij.bron_content_type == "application/pdf"

    def test_onbekende_afnemer_blijft_verzamelbak_met_tenaamstelling(
        self, gescoopte_gebruiker: uuid.UUID, administratie_heet_blow: uuid.UUID
    ) -> None:
        eml = bouw_eml(bijlagen=[("x.xml", _rlz_export("Belastingbutler B.V."), "application", "xml")])
        (r,) = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen
        assert r.uitkomst == "verzamelbak"
        item = next(i for i in verzamelbak.lijst_verzamelbak() if i.document_id == r.document_id)
        # De tenaamstelling ís gelezen — geen "geen tenaamstelling gelezen" meer op deze rij.
        assert item.tenaamstelling == "Belastingbutler B.V."
        assert item.beeld_bestandsnaam == "factuur.pdf"


class TestBeeld:
    def test_bepaal_beeld_drie_herkomsten(self, opslag: LokaleBestandsopslag) -> None:
        opslag.opslaan(pad="a/ubl.xml", inhoud=_rlz_export())
        ingesloten = bepaal_beeld(BestandenSnapshot(bestandsnaam="ubl.xml", opslag_pad="a/ubl.xml"), opslag=opslag)
        assert ingesloten.herkomst == HERKOMST_INGESLOTEN and ingesloten.is_pdf
        assert ingesloten.bestandsnaam == "factuur.pdf" and ingesloten.inhoud.startswith(b"%PDF")

        opslag.opslaan(pad="a/kaal.xml", inhoud=bouw_ubl())
        kaal = bepaal_beeld(BestandenSnapshot(bestandsnaam="kaal.xml", opslag_pad="a/kaal.xml"), opslag=opslag)
        assert kaal.herkomst == HERKOMST_HOOFDBESTAND and not kaal.is_pdf and kaal.bestandsnaam == "kaal.xml"

        opslag.opslaan(pad="a/los.pdf", inhoud=bouw_pdf(1))
        bron = bepaal_beeld(
            BestandenSnapshot(
                bestandsnaam="ubl.xml",
                opslag_pad="a/ubl.xml",
                bron_opslag_pad="a/los.pdf",
                bron_bestandsnaam="los.pdf",
                bron_content_type="application/pdf",
            ),
            opslag=opslag,
        )
        # Bron-kolommen winnen van de ingesloten PDF (de mens/bundeling koos dat beeld bewust).
        assert bron.herkomst == HERKOMST_BRON and bron.bestandsnaam == "los.pdf"

    def test_verzamelbak_preview_serveert_ingesloten_pdf_zonder_bronkolommen(
        self, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker)
        inhoud, naam, content_type = verzamelbak.haal_bijlage_op(document_id=document_id)
        assert content_type == "application/pdf" and naam == "factuur.pdf" and inhoud.startswith(b"%PDF")
        data, data_naam, data_type = verzamelbak.haal_bijlage_op(document_id=document_id, vorm="data")
        assert data_naam.endswith(".xml") and b"<Invoice" in data and "xml" in data_type

    def test_administratie_bestandroute_serveert_ingesloten_pdf(
        self, gescoopte_gebruiker: uuid.UUID, administratie_heet_blow: uuid.UUID
    ) -> None:
        # Een toegewezen UBL-document zónder bron-kolommen (ingang van vóór 0098) → /bestand = de PDF.
        resultaat = documenten_service.upload_document(
            administratie_id=administratie_heet_blow,
            bestandsnaam="ic.xml",
            inhoud=_rlz_export(),
            actor_id=gescoopte_gebruiker,
        )
        inhoud, naam, content_type = documenten_service.haal_bijlage_op(
            administratie_id=administratie_heet_blow, document_id=resultaat.document_id
        )
        assert content_type == "application/pdf" and naam == "factuur.pdf" and inhoud.startswith(b"%PDF")


class TestHerlezenUbl:
    def test_ubl_zonder_tenaamstelling_is_kandidaat_zonder_ai_gate(
        self, gescoopte_gebruiker: uuid.UUID, monkeypatch
    ) -> None:
        document_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker)
        kandidaten = herlezen.vind_kandidaten(sinds=SINDS)
        kandidaat = next(k for k in kandidaten if k.document_id == document_id)
        assert kandidaat.is_ubl and kandidaat.al_herlezen is False
        # Geen intake-AI, geen API-key: een UBL-herlezing is lokale code en mag gewoon door.
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert telling.herlezen >= 1 and telling.gestopt_reden is None

    def test_herlezen_wijst_toe_zet_beeld_en_leert_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_heet_blow: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        document_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert telling.toegewezen == 1 and telling.beeld_gezet == 1 and telling.mislukt == 0
        rij = _rij(admin_engine, document_id)
        assert rij.administratie_id == administratie_heet_blow
        assert rij.status != "niet_toegewezen"
        assert rij.tenaamstelling == "BLOW B.V."
        assert rij.bron_bestandsnaam == "factuur.pdf" and rij.bron_content_type == "application/pdf"
        redenen = _tijdlijn_redenen(admin_engine, document_id)
        assert any("ingesloten factuur-PDF 'factuur.pdf' als beeld gezet" in r for r in redenen)
        assert any(r.startswith("intake_herlezen: toegewezen op tenaamstelling_register") for r in redenen)
        # Systeem-herlezing = geen mens-besluit → het toewijzings-geheugen leert niets.
        with scoped_session(None) as session:
            assert session.scalars(select(ToewijzingRegel).where(ToewijzingRegel.sleutel == "blow")).first() is None
        # Het document is nu een gewoon administratie-document: de bestandroute toont de PDF.
        inhoud, naam, content_type = documenten_service.haal_bijlage_op(
            administratie_id=administratie_heet_blow, document_id=document_id
        )
        assert content_type == "application/pdf" and naam == "factuur.pdf" and inhoud.startswith(b"%PDF")

    def test_zonder_toewijzen_zet_suggestie_en_is_idempotent(
        self, gescoopte_gebruiker: uuid.UUID, administratie_heet_blow: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        document_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS, toewijzen=False)
        assert telling.toegewezen == 0 and telling.tenaamstelling_gezet == 1 and telling.beeld_gezet == 1
        rij = _rij(admin_engine, document_id)
        assert rij.administratie_id is None and rij.status == "niet_toegewezen"
        assert rij.tenaamstelling == "BLOW B.V."
        assert rij.toewijzing_suggestie_administratie_id == administratie_heet_blow
        assert rij.toewijzing_suggestie_bron == "tenaamstelling_register"
        # De verzamelbak-rij draagt nu tenaamstelling + suggestie + beeld — klaar voor bulk-toewijzen.
        item = next(i for i in verzamelbak.lijst_verzamelbak() if i.document_id == document_id)
        assert item.suggestie_administratie_id == administratie_heet_blow and item.beeld_bestandsnaam == "factuur.pdf"
        # Idempotent: tweede run slaat de al-herlezen rij over; `opnieuw` herleest zonder tweede beeld.
        tweede = herlezen.herlees_verzamelbak(sinds=SINDS, toewijzen=False)
        assert tweede.overgeslagen_al_herlezen >= 1 and tweede.herlezen == 0
        derde = herlezen.herlees_verzamelbak(sinds=SINDS, toewijzen=False, opnieuw=True)
        assert derde.herlezen >= 1 and derde.beeld_gezet == 0

    def test_niet_eenduidige_afnemer_krijgt_tenaamstelling_blijft_in_bak(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        document_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker, klant="Belastingbutler B.V.")
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert telling.toegewezen == 0 and telling.tenaamstelling_gezet == 1
        rij = _rij(admin_engine, document_id)
        assert rij.status == "niet_toegewezen" and rij.tenaamstelling == "Belastingbutler B.V."

    def test_kapotte_ubl_is_zichtbaar_mislukt(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        document_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="kapot.xml", inhoud=b"<Invoice>", actor_id=gescoopte_gebruiker, reden="ubl_invalide: x"
        )
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert telling.mislukt == 1
        assert any(
            r.startswith("intake_herlezen_mislukt: ubl_invalide") for r in _tijdlijn_redenen(admin_engine, document_id)
        )
        with scoped_session(None) as session:
            assert session.get(Document, document_id).status == DocumentStatus.NIET_TOEGEWEZEN

    def test_alleen_ubl_laat_pdf_kandidaten_liggen(self, gescoopte_gebruiker: uuid.UUID, monkeypatch) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        ubl_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker)
        pdf_id = documenten_service.registreer_niet_toegewezen_document(
            bestandsnaam="gestrand.pdf",
            inhoud=bouw_pdf(1),
            actor_id=gescoopte_gebruiker,
            reden="splitsingsdetectie_mislukt: paginabereik 1–2 valt buiten het document",
        )
        kandidaten = {k.document_id for k in herlezen.vind_kandidaten(sinds=SINDS)}
        assert {ubl_id, pdf_id} <= kandidaten
        # Zonder --alleen-ubl zou de PDF de AI-gate raken (geen key → IntakeGateDicht); mét de vlag niet.
        telling = herlezen.herlees_verzamelbak(sinds=SINDS, alleen_ubl=True)
        assert telling.kandidaten == 1 and telling.herlezen == 1

    def test_dry_run_telt_alleen(self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        document_id = _pre_fix_verzamelbak_rij(gescoopte_gebruiker)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS, dry_run=True)
        assert telling.kandidaten >= 1 and telling.herlezen == 0
        assert _rij(admin_engine, document_id).bron_bestandsnaam is None


def test_cli_geeft_zonder_toewijzen_door(monkeypatch, capsys) -> None:
    from app import cli

    gezien: dict = {}

    def nep(**kwargs):
        gezien.update(kwargs)
        return herlezen.HerleesTelling(kandidaten=2, herlezen=2, tenaamstelling_gezet=2, beeld_gezet=2)

    monkeypatch.setattr(herlezen, "herlees_verzamelbak", nep)
    assert cli.main(["intake-herlezen", "--sinds", "2026-08-25", "--zonder-toewijzen", "--alleen-ubl"]) == 0
    assert gezien["toewijzen"] is False and gezien["dry_run"] is False and gezien["alleen_ubl"] is True
    assert "2 beeld (ingesloten PDF) gezet" in capsys.readouterr().out
    assert cli.main(["intake-herlezen", "--sinds", "2026-08-25"]) == 0
    assert gezien["toewijzen"] is True
