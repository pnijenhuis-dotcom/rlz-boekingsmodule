"""Synthetische bewaking (31-08): de storing-statemachine (alert bij 2 opeenvolgende fouten,
idempotent per storing, herstelmelding éénmalig) en de kwartier-/uurcadans van voer_probes_uit.
De probes zelf worden hier gestubd — de motor en de alert-idempotentie zijn de geldlogica."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.bewaking import service
from app.bewaking.models import BewakingProbeRun, BewakingStoring
from app.bewaking.service import ProbeUitkomst, _verwerk_uitkomst, voer_probes_uit
from app.db.session import scoped_session


@pytest.fixture()
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def nep_verzend(*, onderwerp: str, tekst: str) -> bool:
        verzonden.append({"onderwerp": onderwerp, "tekst": tekst})
        return True

    monkeypatch.setattr(service, "_verzend_alert", nep_verzend)
    return verzonden


def _vers_tijdstip() -> datetime:
    """Een tijdstip ná álle bestaande probe-runs in de gedeelde test-DB — de uurvenster-logica
    (_ai_beurt) kijkt naar de jongste run, dus elke cadans-test krijgt zijn eigen verse venster."""
    with scoped_session(None) as session:
        laatste = session.scalars(select(func.max(BewakingProbeRun.gestart_op))).one()
    nu = datetime.now(UTC)
    basis = laatste if laatste is not None and laatste > nu else nu
    return basis + timedelta(days=1)


def _storing(soort: str) -> BewakingStoring | None:
    with scoped_session(None) as session:
        rij = session.scalars(
            select(BewakingStoring)
            .where(BewakingStoring.soort == soort)
            .order_by(BewakingStoring.begonnen_op.desc())
        ).first()
        if rij is not None:
            session.expunge(rij)
        return rij


def _fout(soort: str, detail: str = "kapot") -> ProbeUitkomst:
    return ProbeUitkomst(soort=soort, status="fout", detail=detail)


def _ok(soort: str) -> ProbeUitkomst:
    return ProbeUitkomst(soort=soort, status="ok")


class TestStoringStatemachine:
    def test_alert_pas_bij_tweede_fout_en_daarna_nooit_dubbel(self, mails: list[dict]) -> None:
        soort = f"test-{uuid.uuid4().hex[:8]}"
        nu = datetime.now(UTC)
        _verwerk_uitkomst(_fout(soort, "eerste hik"), nu=nu)
        assert mails == []  # geen ruis bij één hik
        _verwerk_uitkomst(_fout(soort, "nog steeds"), nu=nu)
        assert len(mails) == 1
        assert soort in mails[0]["onderwerp"]
        assert "⛔" in mails[0]["onderwerp"]
        assert "nog steeds" in mails[0]["tekst"]
        _verwerk_uitkomst(_fout(soort), nu=nu)
        _verwerk_uitkomst(_fout(soort), nu=nu)
        assert len(mails) == 1  # idempotent per storing — geen mailstorm
        rij = _storing(soort)
        assert rij is not None
        assert rij.opeenvolgende_fouten == 4
        assert rij.alert_verzonden_op is not None
        assert rij.hersteld_op is None

    def test_herstelmelding_eenmalig_en_alleen_na_een_alert(self, mails: list[dict]) -> None:
        soort = f"test-{uuid.uuid4().hex[:8]}"
        nu = datetime.now(UTC)
        # Eén hik → herstel: storing sluit stil, geen enkele mail.
        _verwerk_uitkomst(_fout(soort), nu=nu)
        _verwerk_uitkomst(_ok(soort), nu=nu)
        assert mails == []
        assert _storing(soort).hersteld_op is not None
        # Echte storing (2 fouten → alert) → herstel: precies één herstelmelding.
        _verwerk_uitkomst(_fout(soort), nu=nu)
        _verwerk_uitkomst(_fout(soort), nu=nu)
        _verwerk_uitkomst(_ok(soort), nu=nu)
        _verwerk_uitkomst(_ok(soort), nu=nu)
        assert [m["onderwerp"][:1] for m in mails] == ["⛔", "✅"]
        assert soort in mails[1]["onderwerp"]

    def test_mislukte_alertmail_wordt_volgende_run_opnieuw_geprobeerd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        soort = f"test-{uuid.uuid4().hex[:8]}"
        nu = datetime.now(UTC)
        pogingen: list[str] = []
        lukt = {"waarde": False}

        def wisselend(*, onderwerp: str, tekst: str) -> bool:
            pogingen.append(onderwerp)
            return lukt["waarde"]

        monkeypatch.setattr(service, "_verzend_alert", wisselend)
        _verwerk_uitkomst(_fout(soort), nu=nu)
        _verwerk_uitkomst(_fout(soort), nu=nu)  # mail faalt → kolom blijft None
        assert _storing(soort).alert_verzonden_op is None
        lukt["waarde"] = True
        _verwerk_uitkomst(_fout(soort), nu=nu)  # volgende run: opnieuw geprobeerd
        assert _storing(soort).alert_verzonden_op is not None
        assert len(pogingen) == 2

    def test_overgeslagen_raakt_de_staat_niet(self, mails: list[dict]) -> None:
        soort = f"test-{uuid.uuid4().hex[:8]}"
        nu = datetime.now(UTC)
        _verwerk_uitkomst(_fout(soort), nu=nu)
        _verwerk_uitkomst(ProbeUitkomst(soort=soort, status="overgeslagen"), nu=nu)
        rij = _storing(soort)
        assert rij.opeenvolgende_fouten == 1
        assert rij.hersteld_op is None
        assert mails == []


class TestProbeRunCadans:
    @pytest.fixture()
    def stub_probes(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
        tellers = {"ai": 0}

        def stub(soort: str) -> ProbeUitkomst:
            return ProbeUitkomst(soort=soort, status="ok")

        monkeypatch.setattr(service, "_probe_health", lambda: stub("health"))
        monkeypatch.setattr(service, "_probe_database", lambda: stub("database"))
        monkeypatch.setattr(service, "_probe_documentopslag", lambda: stub("documentopslag"))
        monkeypatch.setattr(service, "_probe_mailkanaal", lambda: stub("mailkanaal"))
        monkeypatch.setattr(service, "_probe_rlz", lambda: stub("rlz"))

        def ai_stub() -> ProbeUitkomst:
            tellers["ai"] += 1
            return stub("ai")

        monkeypatch.setattr(service, "_probe_ai", ai_stub)
        monkeypatch.setattr(service, "_probe_extractie_foutratio", lambda nu: stub("extractie_foutratio"))
        monkeypatch.setattr(service, "_verzend_alert", lambda **kw: True)
        return tellers

    def test_ai_probe_draait_hooguit_eens_per_uur(self, stub_probes: dict[str, int]) -> None:
        nu = _vers_tijdstip()
        eerste = voer_probes_uit(nu=nu)
        assert eerste["ai"] == "ok"
        assert stub_probes["ai"] == 1
        # Kwartier later: uur-probes overgeslagen — geen tweede echte AI-call.
        tweede = voer_probes_uit(nu=nu + timedelta(minutes=15))
        assert tweede["ai"] == "overgeslagen"
        assert stub_probes["ai"] == 1
        # Ná het uurvenster draait hij weer mee.
        derde = voer_probes_uit(nu=nu + timedelta(minutes=61))
        assert derde["ai"] == "ok"
        assert stub_probes["ai"] == 2

    def test_run_legt_statusrij_vast_met_uitkomst_per_soort(self, stub_probes: dict[str, int]) -> None:
        nu = _vers_tijdstip()
        voer_probes_uit(nu=nu)
        with scoped_session(None) as session:
            rij = session.scalars(
                select(BewakingProbeRun).where(BewakingProbeRun.gestart_op == nu)
            ).one()
            assert rij.alles_ok is True
            assert rij.met_ai is True
            assert set(rij.uitkomsten) == {
                "health",
                "database",
                "documentopslag",
                "mailkanaal",
                "rlz",
                "ai",
                "extractie_foutratio",
            }
            assert rij.uitkomsten["health"]["status"] == "ok"

    def test_kapotte_probe_wordt_fout_uitkomst_geen_crash(
        self, stub_probes: dict[str, int], monkeypatch: pytest.MonkeyPatch, mails: list[dict]
    ) -> None:
        def ontploft() -> ProbeUitkomst:
            raise RuntimeError("verbinding geweigerd")

        monkeypatch.setattr(service, "_probe_health", ontploft)
        nu = _vers_tijdstip()
        statussen = voer_probes_uit(nu=nu)
        assert statussen["health"] == "fout"
        statussen = voer_probes_uit(nu=nu + timedelta(minutes=15))
        assert statussen["health"] == "fout"
        assert any("health" in m["onderwerp"] and "⛔" in m["onderwerp"] for m in mails)
