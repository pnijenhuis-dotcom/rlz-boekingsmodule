"""Nazorg-CLI intake-herlezen (spoedopdracht 02-09, punt 5): gestrande verzamelbak-PDF's opnieuw
door de gefixte keten — idempotent, poorten ongewijzigd, al verwerkte rijen nooit geraakt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.config import settings
from app.extractie.client import AiExtractieFout
from app.extractie.splitsing import FactuurSegment
from app.intake import herlezen, verwerking, verzamelbak
from tests.intake.conftest import bouw_eml, bouw_pdf

SINDS = datetime(2026, 8, 25, tzinfo=UTC)


def _faal(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
    raise AiExtractieFout("Splitsingsvoorstel ongeldig: paginabereik 1–2 valt buiten het document (1 pagina's)")


@pytest.fixture
def gestrand_document(gescoopte_gebruiker: uuid.UUID, intake_ai_aan: None, monkeypatch) -> uuid.UUID:
    """Een 1-pagina-PDF die op de oude validatie strandde: verzamelbak, tenaamstelling NULL."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(verwerking.splitsing_extractie, "detecteer_facturen", _faal)
    eml = bouw_eml(bijlagen=[("226176996.pdf", bouw_pdf(1), "application", "pdf")])
    resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)
    assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
    return resultaat.bijlagen[0].document_id


def _rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT administratie_id, status, tenaamstelling FROM boekhouding.document WHERE id = :id"),
            {"id": document_id},
        ).one()


def _tijdlijn_redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :d ORDER BY tijdstip"
                ),
                {"d": document_id},
            )
        ]


class TestKandidaten:
    def test_gestrande_rij_is_kandidaat_al_toegewezen_niet(
        self, gestrand_document: uuid.UUID, administratie_heet_blow: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        kandidaten = herlezen.vind_kandidaten(sinds=SINDS)
        assert [k.document_id for k in kandidaten if k.document_id == gestrand_document]
        kandidaat = next(k for k in kandidaten if k.document_id == gestrand_document)
        assert kandidaat.al_herlezen is False
        assert (kandidaat.reden or "").startswith("splitsingsdetectie_mislukt")
        # Eenmaal handmatig toegewezen (zoals de twaalf Deel-documenten) → geen kandidaat meer.
        verzamelbak.wijs_toe(
            document_id=gestrand_document, administratie_id=administratie_heet_blow, actor_id=gescoopte_gebruiker
        )
        assert gestrand_document not in {k.document_id for k in herlezen.vind_kandidaten(sinds=SINDS)}

    def test_sinds_filter(self, gestrand_document: uuid.UUID) -> None:
        morgen = datetime.now(UTC) + timedelta(days=1)
        assert gestrand_document not in {k.document_id for k in herlezen.vind_kandidaten(sinds=morgen)}

    def test_niet_eenduidig_rij_alleen_met_alle_redenen(
        self, gescoopte_gebruiker: uuid.UUID, intake_ai_aan: None, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            verwerking.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 1, None, None, None, 0.3)
            ],
        )
        eml = bouw_eml(bijlagen=[("leeg.pdf", bouw_pdf(1), "application", "pdf")])
        document_id = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker).bijlagen[0].document_id
        assert document_id not in {k.document_id for k in herlezen.vind_kandidaten(sinds=SINDS)}
        assert document_id in {k.document_id for k in herlezen.vind_kandidaten(sinds=SINDS, alle_redenen=True)}


class TestHerlezen:
    def test_dry_run_telt_zonder_ai_call(self, gestrand_document: uuid.UUID, monkeypatch) -> None:
        def nooit(*a, **kw):
            raise AssertionError("dry-run mag geen AI-call doen")

        monkeypatch.setattr(herlezen.splitsing_extractie, "detecteer_facturen", nooit)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS, dry_run=True)
        assert telling.kandidaten >= 1
        assert telling.herlezen == 0

    def test_gate_dicht_stopt_zichtbaar(self, gestrand_document: uuid.UUID, monkeypatch) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        with pytest.raises(herlezen.IntakeGateDicht):
            herlezen.herlees_verzamelbak(sinds=SINDS)

    def test_eenduidig_wordt_toegewezen_en_is_daarna_geen_kandidaat(
        self,
        gestrand_document: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        admin_engine: Engine,
        monkeypatch,
    ) -> None:
        aanroepen: list[dict] = []

        def gefixt(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            aanroepen.append({"paginas": paginas, "bron": verbruik_referentie.bron})
            return [FactuurSegment(1, 1, "BLOW B.V.", "Van Happen", "226176996", 0.9)]

        monkeypatch.setattr(herlezen.splitsing_extractie, "detecteer_facturen", gefixt)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)

        assert telling.toegewezen >= 1 and telling.mislukt == 0
        assert aanroepen and aanroepen[0]["bron"] == "intake_herlezen"
        rij = _rij(admin_engine, gestrand_document)
        assert rij.administratie_id == administratie_heet_blow
        assert rij.tenaamstelling == "BLOW B.V."
        assert rij.status != "niet_toegewezen"
        redenen = _tijdlijn_redenen(admin_engine, gestrand_document)
        assert any(r and r.startswith("intake_herlezen: toegewezen op tenaamstelling_register") for r in redenen)
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE record_id = :d AND actie = 'intake_herlezen_toegewezen'"
                ),
                {"d": gestrand_document},
            ).scalar_one()
        assert audit == 1
        # Het toewijzings-geheugen leert hier bewust niets (geen mens-besluit).
        with admin_engine.connect() as conn:
            regels = conn.execute(
                text("SELECT count(*) FROM boekhouding.toewijzing_regel WHERE sleutel = 'blow bv' AND actief")
            ).scalar_one()
        assert regels == 0
        assert gestrand_document not in {k.document_id for k in herlezen.vind_kandidaten(sinds=SINDS)}

    def test_niet_eenduidig_zet_tenaamstelling_en_is_idempotent(
        self, gestrand_document: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        tellers = {"calls": 0}

        def gefixt(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            tellers["calls"] += 1
            return [FactuurSegment(1, 1, "Belastingbutler B.V.", "Saleswizard", "2026-8151", 0.95)]

        monkeypatch.setattr(herlezen.splitsing_extractie, "detecteer_facturen", gefixt)
        eerste = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert eerste.tenaamstelling_gezet >= 1
        rij = _rij(admin_engine, gestrand_document)
        assert rij.status == "niet_toegewezen"
        assert rij.tenaamstelling == "Belastingbutler B.V."
        item = {i.document_id: i for i in verzamelbak.lijst_verzamelbak()}[gestrand_document]
        assert item.reden == "intake_herlezen: tenaamstelling 'Belastingbutler B.V.' gelezen, niet eenduidig"
        assert item.reden_label == "opnieuw gelezen: tenaamstelling matcht geen administratie of geleerde regel"

        calls_na_eerste = tellers["calls"]
        tweede = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert tellers["calls"] == calls_na_eerste  # al herlezen = overgeslagen, geen tweede AI-call
        assert tweede.overgeslagen_al_herlezen >= 1
        derde = herlezen.herlees_verzamelbak(sinds=SINDS, opnieuw=True)
        assert tellers["calls"] > calls_na_eerste and derde.herlezen >= 1

    def test_ai_fout_wordt_tijdlijnregel_rij_blijft(
        self, gestrand_document: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        def plat(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            raise RuntimeError("AI plat")

        monkeypatch.setattr(herlezen.splitsing_extractie, "detecteer_facturen", plat)
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert telling.mislukt >= 1
        rij = _rij(admin_engine, gestrand_document)
        assert rij.status == "niet_toegewezen" and rij.tenaamstelling is None
        assert "intake_herlezen_mislukt: AI plat" in _tijdlijn_redenen(admin_engine, gestrand_document)

    def test_meerdere_facturen_geeft_splitsingsvoorstel(
        self, gestrand_document: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            herlezen.splitsing_extractie,
            "detecteer_facturen",
            lambda inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None: [
                FactuurSegment(1, 1, "A", None, None, 0.9),
                FactuurSegment(
                    2, 2, "B", None, None, 0.9, ongeldig_reden="paginabereik 2–2 valt buiten het document (1 pagina's)"
                ),
            ],
        )
        telling = herlezen.herlees_verzamelbak(sinds=SINDS)
        assert telling.splitsingsvoorstel >= 1
        item = {i.document_id: i for i in verzamelbak.lijst_verzamelbak()}[gestrand_document]
        assert item.splitsing_id is not None
        assert item.splitsing_voorstel["ongeldig"] == 1
        # Mét open voorstel is de rij geen kandidaat meer (eerst de splitsing beoordelen).
        assert gestrand_document not in {k.document_id for k in herlezen.vind_kandidaten(sinds=SINDS)}
