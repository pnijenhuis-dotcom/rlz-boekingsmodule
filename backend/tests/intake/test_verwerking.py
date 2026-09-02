"""Intake-routing per bijlage (koppelcontract §2d + CLAUDE.md e-mail-intake): elke uitkomst is
zichtbaar — toegewezen, verzamelbak, VGB-genegeerd of splitsingsvoorstel; nooit stil weg."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, text

from app.config import settings
from app.extractie.splitsing import FactuurSegment
from app.intake import verwerking
from tests.intake.conftest import bouw_eml, bouw_pdf, bouw_ubl


def _document_rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT administratie_id, status, soort, tenaamstelling, afzender_hint "
                "FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()


class TestInkoopUblRouting:
    def test_eenduidige_tenaamstelling_wijst_automatisch_toe(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(bijlagen=[("factuur.xml", bouw_ubl(klant="BLOW B.V."), "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert [r.uitkomst for r in resultaat.bijlagen] == ["toegewezen"]
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.administratie_id == administratie_heet_blow
        assert rij.soort == "inkoopfactuur"
        assert rij.tenaamstelling == "BLOW B.V."
        assert rij.afzender_hint == "administratie@bouwmaat.nl"
        # UBL is deterministisch: het document doorloopt meteen de extractie → te_controleren.
        assert rij.status == "te_controleren"

    def test_onbekende_tenaamstelling_valt_in_verzamelbak(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(bijlagen=[("factuur.xml", bouw_ubl(klant="BLOW Holding"), "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert [r.uitkomst for r in resultaat.bijlagen] == ["verzamelbak"]
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.administratie_id is None
        assert rij.status == "niet_toegewezen"

    def test_kapotte_xml_valt_in_verzamelbak(self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        eml = bouw_eml(bijlagen=[("factuur.xml", b"<geen-ubl>", "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert "ubl_invalide" in (resultaat.bijlagen[0].detail or "")


class TestVastlyEnVgbRouting:
    def test_vastly_verkoop_markering_routeert_naar_omzetkant(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        # Verkoopfactuur: ónze entiteit is de LEVERANCIER — de klant is de huurder.
        ubl = bouw_ubl(leverancier="BLOW B.V.", klant="Huurder Jansen", adr_id="VASTLY-VERKOOP")
        eml = bouw_eml(bijlagen=[("verkoop.xml", ubl, "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert [r.uitkomst for r in resultaat.bijlagen] == ["toegewezen"]
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.soort == "verkoopfactuur"
        assert rij.administratie_id == administratie_heet_blow

    def test_vastly_nlcius_invalide_valt_in_verzamelbak_nooit_stil_naar_inkoop(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        # §2d-failsafe: markering aanwezig maar kernvelden incompleet (geen afnemer, geen regels).
        ubl = bouw_ubl(leverancier="BLOW B.V.", klant=None, adr_id="VASTLY-VERKOOP", regels=0)
        eml = bouw_eml(bijlagen=[("verkoop.xml", ubl, "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert "nlcius_invalide" in (resultaat.bijlagen[0].detail or "")
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.soort == "verkoopfactuur"
        assert rij.administratie_id is None

    def test_vgb_prefix_wordt_genegeerd_maar_zichtbaar_geregistreerd(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        ubl = bouw_ubl(buyer_reference="VGB-2026-0001", klant="Kempen Vastgoed B.V.")
        eml = bouw_eml(bijlagen=[("vgb.xml", ubl, "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert [r.uitkomst for r in resultaat.bijlagen] == ["vgb_genegeerd"]
        assert resultaat.bijlagen[0].document_id is None
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'intake_vgb_genegeerd'")
            ).scalar_one()
            detail = conn.execute(
                text("SELECT detail FROM boekhouding.intake_bericht WHERE id = :id"),
                {"id": resultaat.bericht_id},
            ).scalar_one()
        assert audit == 1
        assert detail["bijlagen"][0]["uitkomst"] == "vgb_genegeerd"


class TestPdfRouting:
    def test_intake_ai_gate_uit_stuurt_pdf_naar_verzamelbak(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(bijlagen=[("scan.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert "intake_ai_uitgeschakeld" in (resultaat.bijlagen[0].detail or "")

    def test_meerdere_facturen_geeft_splitsingsvoorstel_ter_controle(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        intake_ai_aan: None,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            verwerking.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 2, "BLOW B.V.", "Bouwmaat", "F-1", 0.95),
                FactuurSegment(3, 3, "Kempen Groep B.V.", "Sligro", "F-2", 0.9),
            ],
        )
        eml = bouw_eml(bijlagen=[("batchscan.pdf", bouw_pdf(3), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "splitsingsvoorstel"
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.status == "niet_toegewezen"  # nooit stil auto-splitsen
        with admin_engine.connect() as conn:
            voorstel = conn.execute(
                text("SELECT voorstel FROM boekhouding.intake_splitsing WHERE bron_document_id = :d"),
                {"d": resultaat.bijlagen[0].document_id},
            ).scalar_one()
        assert len(voorstel["facturen"]) == 2

    def test_een_factuur_met_eenduidige_tenaamstelling_direct_toegewezen(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        intake_ai_aan: None,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            verwerking.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 1, "BLOW B.V.", "Bouwmaat", "F-1", 0.95)
            ],
        )
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.administratie_id == administratie_heet_blow

    def test_ai_fout_valt_terug_op_verzamelbak(
        self, gescoopte_gebruiker: uuid.UUID, intake_ai_aan: None, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        def faal(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            raise RuntimeError("AI plat")

        monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", faal)
        eml = bouw_eml(bijlagen=[("factuur.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert "splitsingsdetectie_mislukt" in (resultaat.bijlagen[0].detail or "")


class TestBerichtVerwerking:
    def test_idempotent_op_message_id(self, gescoopte_gebruiker: uuid.UUID) -> None:
        eml = bouw_eml(
            message_id="<zelfde@test.local>",
            bijlagen=[("factuur.xml", b"<geen-ubl>", "application", "xml")],
        )
        eerste = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        tweede = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert not eerste.al_eerder_verwerkt
        assert tweede.al_eerder_verwerkt
        assert tweede.bericht_id == eerste.bericht_id
        assert tweede.bijlagen == []

    def test_hangend_op_bezig_wordt_herverwerkt_niet_vroeg_teruggekeerd(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Het intake-lek (fix 2026-08-07): een bericht waarvan de run crashte vóór het
        eindresultaat op de rij stond (detail blijft {"verwerking": "bezig"}) moet bij
        her-upload HERVERWERKT worden — zonder de al-geregistreerde bijlage te dupliceren."""
        eml = bouw_eml(
            message_id="<hangend@test.local>",
            bijlagen=[("factuur.xml", bouw_ubl(klant="BLOW Holding"), "application", "xml")],
        )
        eerste = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        # Simuleer de afgebroken run: het eindresultaat is nooit geschreven.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.intake_bericht "
                    'SET detail = \'{"bijlagen": [], "verwerking": "bezig"}\'::jsonb '
                    "WHERE id = :id"
                ),
                {"id": eerste.bericht_id},
            )

        tweede = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert not tweede.al_eerder_verwerkt
        assert tweede.bericht_id == eerste.bericht_id
        assert [r.uitkomst for r in tweede.bijlagen] == ["verzamelbak"]
        # Idempotent op (intake_bericht_id, sha256): zelfde document, geen duplicaat.
        assert tweede.bijlagen[0].document_id == eerste.bijlagen[0].document_id
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.document WHERE intake_bericht_id = :id"),
                {"id": eerste.bericht_id},
            ).scalar_one()
            detail = conn.execute(
                text("SELECT detail FROM boekhouding.intake_bericht WHERE id = :id"),
                {"id": eerste.bericht_id},
            ).scalar_one()
        assert aantal == 1
        assert detail.get("verwerking") != "bezig"
        assert detail["bijlagen"][0]["uitkomst"] == "verzamelbak"

    def test_herverwerking_dupliceert_ook_toegewezen_documenten_niet(
        self, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        eml = bouw_eml(
            message_id="<hangend-toegewezen@test.local>",
            bijlagen=[("factuur.xml", bouw_ubl(klant="BLOW B.V."), "application", "xml")],
        )
        eerste = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert [r.uitkomst for r in eerste.bijlagen] == ["toegewezen"]
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.intake_bericht "
                    'SET detail = \'{"bijlagen": [], "verwerking": "bezig"}\'::jsonb '
                    "WHERE id = :id"
                ),
                {"id": eerste.bericht_id},
            )

        tweede = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert not tweede.al_eerder_verwerkt
        assert tweede.bijlagen[0].document_id == eerste.bijlagen[0].document_id
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.document WHERE intake_bericht_id = :id"),
                {"id": eerste.bericht_id},
            ).scalar_one()
        assert aantal == 1

    def test_onverwerkbaar_bijlagetype_zichtbaar_geregistreerd(self, gescoopte_gebruiker: uuid.UUID) -> None:
        # Sinds punt 2 (25-08 deel 3) zijn afbeeldingen wél documenten — zie test_afbeeldingen.py;
        # een Word-bestand blijft zichtbaar 'niet_verwerkbaar'.
        eml = bouw_eml(bijlagen=[("brief.docx", b"PK fake", "application", "vnd.openxmlformats-officedocument")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
        assert resultaat.bijlagen[0].uitkomst == "niet_verwerkbaar"
        assert resultaat.bijlagen[0].document_id is None


class TestSplitsingsbugProportioneel:
    """Spoedopdracht 02-09 (diagnose punt 1): de intake-keten van eml tot document-rij."""

    class _NepClient:
        def __init__(self, facturen: list[dict]) -> None:
            self.facturen = facturen
            self.opdrachten: list[str] = []

        def extraheer_json_uit_pdf(self, *, pdf_bytes, system, opdracht, json_schema, cache_document=False):
            from app.extractie.client import ClaudeAntwoord

            self.opdrachten.append(opdracht)
            return ClaudeAntwoord(data={"facturen": self.facturen}, afgekapt=False, input_tokens=1, output_tokens=1)

    def _installeer_client(self, monkeypatch, facturen: list[dict]) -> TestSplitsingsbugProportioneel._NepClient:
        from app.extractie import splitsing as splitsing_module

        client = self._NepClient(facturen)
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(splitsing_module, "ClaudeExtractieClient", lambda **kw: client)
        return client

    def test_repro_1_pagina_ep_2_wordt_toegewezen_op_tenaamstelling(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        intake_ai_aan: None,
        monkeypatch,
    ) -> None:
        """De productie-casus: 1-pagina-PDF, AI antwoordt sp=1/ep=2 mét correcte tenaamstelling.
        Vóór de fix: verzamelbak zonder tenaamstelling ("geen tenaamstelling gelezen")."""
        client = self._installeer_client(
            monkeypatch, [{"sp": 1, "ep": 2, "ten": "BLOW B.V.", "lev": "Van Happen", "nr": "226176996", "z": 0.9}]
        )
        eml = bouw_eml(bijlagen=[("226176996.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.administratie_id == administratie_heet_blow
        assert rij.tenaamstelling == "BLOW B.V."
        assert "precies 1 pagina" in client.opdrachten[0]

    def test_1_pagina_onbekende_tenaamstelling_blijft_met_tenaamstelling_in_de_bak(
        self, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, intake_ai_aan: None, monkeypatch
    ) -> None:
        self._installeer_client(
            monkeypatch,
            [{"sp": 1, "ep": 2, "ten": "Belastingbutler B.V.", "lev": "Saleswizard", "nr": "2026-8151", "z": 0.95}],
        )
        eml = bouw_eml(bijlagen=[("2026-8151.pdf", bouw_pdf(1), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert resultaat.bijlagen[0].detail == "tenaamstelling_niet_eenduidig"
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.status == "niet_toegewezen"
        assert rij.tenaamstelling == "Belastingbutler B.V."  # nooit meer verloren

    def test_meerpagina_ongeldig_deel_gaat_met_reden_mee_in_het_voorstel(
        self,
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        intake_ai_aan: None,
        monkeypatch,
    ) -> None:
        self._installeer_client(
            monkeypatch,
            [
                {"sp": 1, "ep": 2, "ten": "BLOW B.V.", "lev": "Bouwmaat", "nr": "F-1", "z": 0.95},
                {"sp": 3, "ep": 7, "ten": "Kempen Groep B.V.", "lev": "Sligro", "nr": "F-2", "z": 0.9},
            ],
        )
        eml = bouw_eml(bijlagen=[("batchscan.pdf", bouw_pdf(3), "application", "pdf")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "splitsingsvoorstel"
        assert "1 deel/delen ongeldig" in (resultaat.bijlagen[0].detail or "")
        document_id = resultaat.bijlagen[0].document_id
        with admin_engine.connect() as conn:
            voorstel = conn.execute(
                text("SELECT voorstel FROM boekhouding.intake_splitsing WHERE bron_document_id = :d"),
                {"d": document_id},
            ).scalar_one()
            reden = conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :d AND naar_status = 'niet_toegewezen'"
                ),
                {"d": document_id},
            ).scalar_one()
        assert voorstel["ongeldig"] == 1
        assert voorstel["facturen"][0]["ongeldig_reden"] is None
        assert voorstel["facturen"][0]["tenaamstelling"] == "BLOW B.V."
        assert voorstel["facturen"][1]["ongeldig_reden"] == "paginabereik 3–7 valt buiten het document (3 pagina's)"
        assert voorstel["facturen"][1]["tenaamstelling"] == "Kempen Groep B.V."  # gelezen, blijft staan
        assert reden.startswith("splitsingsvoorstel_ter_controle: 2 facturen herkend, 1 deel ongeldig")
