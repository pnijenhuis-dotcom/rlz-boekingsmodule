"""Casus (i) — factuur met een eigen leverancier-werknummer: Universal Nederland zet "Werk: 26084 - … (W03611)" op
RLZ-2080143037 — W03611 is hún werknummer, 26084 óns projectnummer. Motor: app/projecten/match.py (exacte code >
bevestigd werknummer (groen) > onbevestigd werknummer (oranje) > fuzzy; meerduidig = nooit invullen)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.projecten.models import LeverancierWerknummer
from app.db.session import scoped_session
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import PROJECT_26084, Keten

CASUS = Casus(casussen.A_UNIVERSAL_NEDERLAND)
PDF = CASUS.pdf_bestandsnaam()


@pytest.fixture
def factuur(keten: Keten) -> uuid.UUID:
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


def _werknummer(keten: Keten, *, bevestigd: bool) -> None:
    with scoped_session(keten.administratie_id, actor_id=keten.actor) as session:
        session.add(
            LeverancierWerknummer(
                administratie_id=keten.administratie_id,
                project_id=PROJECT_26084,
                vendor_id=keten.vendors["universal_nederland"],
                werknummer="W03611",
                bron="factuur",
                bevestigd=bevestigd,
                aangemaakt_door=keten.actor,
            )
        )


class TestWerknummer:
    def test_onbekend_werknummer_vult_niets(self, keten: Keten, factuur: uuid.UUID) -> None:
        voorstel = keten.prefill(factuur)
        assert voorstel.vendor_id == keten.vendors["universal_nederland"]
        assert all(r.project_id is None for r in voorstel.regels)
        assert all(r.project_tekst == "W03611" for r in voorstel.regels)

    def test_onbevestigde_koppeling_is_oranje(self, keten: Keten, factuur: uuid.UUID) -> None:
        _werknummer(keten, bevestigd=False)
        voorstel = keten.prefill(factuur)
        assert all(r.project_id == PROJECT_26084 for r in voorstel.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "factuur_onbevestigd" for r in voorstel.regels)

    def test_bevestigde_koppeling_is_groen_en_checks_zien_het_project(self, keten: Keten, factuur: uuid.UUID) -> None:
        _werknummer(keten, bevestigd=True)
        voorstel = keten.prefill(factuur)
        assert all(r.project_id == PROJECT_26084 for r in voorstel.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "factuur" for r in voorstel.regels)
        keten.open_controlescherm(factuur)
        checks = keten.checks(factuur)
        assert "project" not in checks["Verplichte velden"][1]

    def test_werknummer_tabel_rij(self, keten: Keten, admin_engine: Engine, factuur: uuid.UUID) -> None:
        _werknummer(keten, bevestigd=True)
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.leverancier_werknummer WHERE werknummer = 'W03611'")
            ).scalar_one()
        assert aantal == 1
