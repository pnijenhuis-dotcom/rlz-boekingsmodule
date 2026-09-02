"""Bewakingsprobe intake_verwerpingsratio (spoedopdracht 02-09, punt 4): ≥ 50 % verworpen/mislukte
intake-AI-voorstellen bij ≥ 3 pogingen per uur = fout (alert via de bestaande storing-motor)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bewaking.service import _probe_intake_verwerpingsratio
from app.config import settings
from app.db.models import AiGebruik
from app.db.session import scoped_session
from app.documenten import service as documenten_service

PAGINABEREIK = (
    "splitsingsdetectie_mislukt: Splitsingsvoorstel ongeldig: paginabereik 1–2 valt buiten het document (1 pagina's)"
)


def _call(tijdstip: datetime, bron: str = "intake_splitsing") -> None:
    with scoped_session(None) as session:
        session.add(
            AiGebruik(
                id=uuid.uuid4(),
                tijdstip=tijdstip,
                maand=date(tijdstip.year, tijdstip.month, 1),
                model="claude-sonnet-5",
                bron=bron,
                input_tokens=1,
                output_tokens=1,
                cache_schrijf_tokens=0,
                cache_lees_tokens=0,
                kosten_eur=Decimal("0.001"),
            )
        )


def _verzamelbak_rij(admin_engine: Engine, actor: uuid.UUID, reden: str, tijdstip: datetime) -> None:
    document_id = documenten_service.registreer_niet_toegewezen_document(
        bestandsnaam=f"{uuid.uuid4()}.pdf", inhoud=b"%PDF-" + uuid.uuid4().bytes, actor_id=actor, reden=reden
    )
    # De registratie stempelt now(); zet de tijdlijn op het gewenste tijdstip (ver in de toekomst,
    # zodat de rijen van andere tests buiten het venster van deze test vallen). De tijdlijn is
    # append-only voor de app-rol — dus als schema-owner.
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document_gebeurtenis SET tijdstip = :t WHERE document_id = :d"),
            {"t": tijdstip, "d": document_id},
        )


def _venster() -> datetime:
    # Eigen, ver-toekomstig uurvenster per test — de gedeelde test-DB draagt rijen van andere tests.
    return datetime(2100, 1, 1, tzinfo=UTC) + timedelta(days=uuid.uuid4().int % 3000)


class TestIntakeVerwerpingsratio:
    def test_onder_minimum_zwijgt(self, admin_engine: Engine, gescoopte_gebruiker: uuid.UUID) -> None:
        nu = _venster()
        _call(nu - timedelta(minutes=5))
        _verzamelbak_rij(admin_engine, gescoopte_gebruiker, PAGINABEREIK, nu - timedelta(minutes=5))
        uitkomst = _probe_intake_verwerpingsratio(nu)
        assert uitkomst.status == "ok"
        assert "onder minimum" in (uitkomst.detail or "")

    def test_helft_verworpen_bij_drie_pogingen_is_fout(
        self, admin_engine: Engine, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        nu = _venster()
        for _ in range(4):
            _call(nu - timedelta(minutes=10))
        _verzamelbak_rij(admin_engine, gescoopte_gebruiker, PAGINABEREIK, nu - timedelta(minutes=9))
        _verzamelbak_rij(admin_engine, gescoopte_gebruiker, PAGINABEREIK, nu - timedelta(minutes=8))
        # Correcte uitkomsten tellen niet als verworpen.
        _verzamelbak_rij(admin_engine, gescoopte_gebruiker, "tenaamstelling_niet_eenduidig", nu - timedelta(minutes=7))
        uitkomst = _probe_intake_verwerpingsratio(nu)
        assert uitkomst.status == "fout"
        assert "2/4" in (uitkomst.detail or "")

    def test_lage_ratio_is_ok(self, admin_engine: Engine, gescoopte_gebruiker: uuid.UUID) -> None:
        nu = _venster()
        for _ in range(5):
            _call(nu - timedelta(minutes=10))
        _verzamelbak_rij(admin_engine, gescoopte_gebruiker, PAGINABEREIK, nu - timedelta(minutes=9))
        uitkomst = _probe_intake_verwerpingsratio(nu)
        assert uitkomst.status == "ok"
        assert uitkomst.detail == "1/5"

    def test_api_fouten_zonder_usage_rij_tellen_als_poging(
        self, admin_engine: Engine, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        nu = _venster()
        for _ in range(3):
            _verzamelbak_rij(
                admin_engine,
                gescoopte_gebruiker,
                "splitsingsdetectie_mislukt: Claude API-fout: 529",
                nu - timedelta(minutes=3),
            )
        uitkomst = _probe_intake_verwerpingsratio(nu)
        assert uitkomst.status == "fout"
        assert "3/3" in (uitkomst.detail or "")

    def test_buiten_het_uurvenster_telt_niet(self, admin_engine: Engine, gescoopte_gebruiker: uuid.UUID) -> None:
        nu = _venster()
        for _ in range(3):
            _call(nu - timedelta(hours=2))
            _verzamelbak_rij(admin_engine, gescoopte_gebruiker, PAGINABEREIK, nu - timedelta(hours=2))
        assert _probe_intake_verwerpingsratio(nu).status == "ok"

    def test_drempel_is_config(
        self, admin_engine: Engine, gescoopte_gebruiker: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nu = _venster()
        for _ in range(4):
            _call(nu - timedelta(minutes=10))
        _verzamelbak_rij(admin_engine, gescoopte_gebruiker, PAGINABEREIK, nu - timedelta(minutes=9))
        assert _probe_intake_verwerpingsratio(nu).status == "ok"
        monkeypatch.setattr(settings, "bewaking_intake_verwerpingsratio_drempel", 0.25)
        assert _probe_intake_verwerpingsratio(nu).status == "fout"
