"""CreditNote-381-intake (§2d-creditnota's v1.11): herkenning achter de eigen config-gate.
Sinds 2026-08-10 default AAN (golden-case-verificatie geslaagd, activatievolgorde stap 2);
beide standen blijven getest — uit-zetten kan altijd via de env-var."""

from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.db.session import scoped_session
from app.documenten.models import Document
from app.documenten.storage import LokaleBestandsopslag
from app.intake.verwerking import verwerk_eml
from tests.intake.conftest import bouw_eml
from tests.verkoop.conftest import bouw_vastly_creditnote_ubl


def _verwerk(inhoud: bytes, actor_id: uuid.UUID, opslag: LokaleBestandsopslag):
    eml = bouw_eml(bijlagen=[("creditnota.xml", inhoud, "application", "xml")])
    return verwerk_eml(eml, actor_id=actor_id, opslag=opslag)


class TestCreditnoteGate:
    def test_gate_aan_is_de_default_sinds_de_golden_case_verificatie(self) -> None:
        # Activatievolgorde stap 2 (2026-08-10): golden-cases geverifieerd → gate default AAN.
        assert settings.creditnota_381_ingeschakeld is True

    def test_gate_uit_valt_zichtbaar_in_verzamelbak(
        self, monkeypatch: pytest.MonkeyPatch, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        monkeypatch.setattr(settings, "creditnota_381_ingeschakeld", False)
        resultaat = _verwerk(bouw_vastly_creditnote_ubl(), gescoopte_gebruiker, opslag)
        [bijlage] = resultaat.bijlagen
        assert bijlage.uitkomst == "verzamelbak"
        assert "creditnote_381_gate_uit" in (bijlage.detail or "")
        with scoped_session(None) as session:
            document = session.get(Document, bijlage.document_id)
            assert document is not None  # zichtbaar geregistreerd, nooit stil weg
            assert document.soort == "verkoopfactuur"

    def test_gate_aan_routeert_als_verkoopfactuur(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_heet_blow: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        monkeypatch.setattr(settings, "creditnota_381_ingeschakeld", True)
        resultaat = _verwerk(
            bouw_vastly_creditnote_ubl(leverancier="BLOW B.V."), gescoopte_gebruiker, opslag
        )
        [bijlage] = resultaat.bijlagen
        assert bijlage.uitkomst == "toegewezen"
        with scoped_session(administratie_heet_blow) as session:
            document = session.get(Document, bijlage.document_id)
            assert document.soort == "verkoopfactuur"
            assert document.administratie_id == administratie_heet_blow

    def test_gate_aan_zonder_billingreference_blijft_failsafe(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        monkeypatch.setattr(settings, "creditnota_381_ingeschakeld", True)
        resultaat = _verwerk(
            bouw_vastly_creditnote_ubl(gecrediteerd_factuurnummer=None), gescoopte_gebruiker, opslag
        )
        [bijlage] = resultaat.bijlagen
        assert bijlage.uitkomst == "verzamelbak"
        assert "vastly_nlcius_invalide" in (bijlage.detail or "")
