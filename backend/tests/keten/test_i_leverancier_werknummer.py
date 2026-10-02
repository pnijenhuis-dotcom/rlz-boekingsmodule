"""Casus (i) — factuur met een eigen leverancier-werknummer: Universal Nederland zet "Werk: 26084 - … (W03611)" op
RLZ-2080143037 — W03611 is hún werknummer, 26084 óns projectnummer. Motor: app/projecten/match.py (exacte code >
bevestigd werknummer (groen) > onbevestigd werknummer (oranje) > fuzzy; meerduidig = nooit invullen)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import scoped_session
from app.geheugen.models import BoekingObservatie
from app.projecten.models import LeverancierWerknummer
from app.tijd import vandaag_nl
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

    def test_niveau3_plaats_opdrachtgever_raadt_niet_op_casus_a(self, keten: Keten, factuur: uuid.UUID) -> None:
        """Run D 02-10 blok B: niveau 3 is deterministisch (plaats-token ÉN opdrachtgever-token). De tekst van casus a
        ("Werk: 26084 - Opdrachtgever A (W03611)", projectnaam "26084 Opdrachtgever A (Universal Nederland)") draagt
        de afzendernaam als opdrachtgever — die telt nooit mee — en geen plaats-token → zonder mapping blijft het veld
        leeg, er wordt nooit op niveau 3 geraden (vóór 02-10 kon de SequenceMatcher-fuzzy hier "lijkt op" zeggen)."""
        voorstel = keten.prefill(factuur)
        assert all(r.project_id is None for r in voorstel.regels)
        assert all(r.project_bron != "factuur_plaats_opdrachtgever" for r in voorstel.regels)
        assert all(r.project_kandidaten is None for r in voorstel.regels)

    def test_werknummer_tabel_rij(self, keten: Keten, admin_engine: Engine, factuur: uuid.UUID) -> None:
        _werknummer(keten, bevestigd=True)
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.leverancier_werknummer WHERE werknummer = 'W03611'")
            ).scalar_one()
        assert aantal == 1


class TestBronvolgordeProject:
    """Blok 3 feedbackrun A 25-09 (FV-02) + punt 4 02-10: het geheugen vult het project NOOIT, alleen zichtbaar."""

    def _geheugen(self, keten: Keten, project_id: uuid.UUID) -> None:
        with scoped_session(keten.administratie_id, actor_id=keten.actor) as session:
            for i in range(2):
                session.add(
                    BoekingObservatie(
                        id=uuid.uuid4(),
                        administratie_id=keten.administratie_id,
                        vendor_id=keten.vendors["universal_nederland"],
                        regel_sleutel=None,
                        gb_id=uuid.uuid4(),
                        btw_id=None,
                        project_id=project_id,
                        bron="app",
                        bron_datum=vandaag_nl(),
                        boekstuk_ref=f"RLZ-25-0000{i}",
                    )
                )

    def test_bevestigd_werknummer_wint_van_het_geheugen(self, keten: Keten, factuur: uuid.UUID) -> None:
        from tests.keten.conftest import PROJECT_26049

        self._geheugen(keten, PROJECT_26049)
        _werknummer(keten, bevestigd=True)
        voorstel = keten.prefill(factuur)
        assert all(r.project_id == PROJECT_26084 and r.project_bron == "factuur" for r in voorstel.regels)

    def test_geheugen_vult_nooit_zonder_factuurbron_maar_zichtbaar(self, keten: Keten, factuur: uuid.UUID) -> None:
        from tests.keten.conftest import PROJECT_26049

        self._geheugen(keten, PROJECT_26049)
        voorstel = keten.prefill(factuur)
        # W03611 is een onbekend werknummer (geen mapping) en geen code in het cache-formaat → geen factuurbron;
        # punt 4 02-10: het geheugen vult dan NIETS (veld leeg), de herkomst "geheugen" blijft zichtbaar als uitleg.
        assert all(r.project_id is None and r.project_bron == "geheugen" for r in voorstel.regels)
        assert all("project" not in (r.prefill_herkomst or {}) for r in voorstel.regels)
