"""Geldlogica van de AI-kostenmeter (besluit Peter 2026-08-14) — tests verplicht vóór UI-polish.

Dekt de vier geëiste scenario's: cumulatie, maandgrens-overgang (Europe/Amsterdam, incl.
zomer-/wintertijd), de harde poort die exact op de grens blokkeert, en de eenmaligheid van de
80%-waarschuwing. Plus de deterministische kostenberekening zelf (gepinde prijzen × gepinde
koers, cache-tokens apart geprijsd, afronding naar boven) en fail-closed bij een onbekend model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.aikosten.service import (
    AiKostenLimietBereikt,
    AiKostenModelOnbekend,
    AiVerbruikReferentie,
    bereken_kosten_eur,
    controleer_poort,
    haal_status_op,
    huidige_maand,
    registreer_verbruik,
)


def _zet_limiet(admin_engine: Engine, limiet: Decimal) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.ai_kosten_instelling SET maandlimiet_eur = :limiet"),
            {"limiet": limiet},
        )


class TestKostenberekening:
    def test_sonnet_prijzen_input_en_output(self) -> None:
        # 100k input à $3/Mtok + 10k output à $15/Mtok, koers 1,00 → € 0,30 + € 0,15.
        kosten = bereken_kosten_eur(model="claude-sonnet-5", input_tokens=100_000, output_tokens=10_000)
        assert kosten == Decimal("0.450000")

    def test_cache_tokens_apart_geprijsd(self) -> None:
        # Cache-schrijven 1,25× en cache-lezen 0,10× van de inputprijs — geen input/output-prijs.
        kosten = bereken_kosten_eur(
            model="claude-sonnet-5",
            input_tokens=0,
            output_tokens=0,
            cache_schrijf_tokens=100_000,
            cache_lees_tokens=100_000,
        )
        assert kosten == Decimal("0.375000") + Decimal("0.030000")

    def test_afronding_naar_boven(self) -> None:
        # 1 cache-lees-token sonnet = $0,0000003 — onder de 6-decimalenprecisie, rondt de meter
        # bewust naar bóven af (overschatten, nooit onderschatten).
        kosten = bereken_kosten_eur(model="claude-sonnet-5", input_tokens=0, output_tokens=0, cache_lees_tokens=1)
        assert kosten == Decimal("0.000001")

    def test_onbekend_model_fail_closed(self) -> None:
        with pytest.raises(AiKostenModelOnbekend):
            bereken_kosten_eur(model="claude-onbekend-99", input_tokens=1, output_tokens=1)
        with pytest.raises(AiKostenModelOnbekend):
            controleer_poort(model="claude-onbekend-99")


class TestMaandgrens:
    def test_maandgrens_valt_op_lokale_middernacht_zomertijd(self) -> None:
        # 31 aug 22:30 UTC = 1 sep 00:30 in Amsterdam (CEST, UTC+2) → nieuwe maand.
        assert huidige_maand(datetime(2026, 8, 31, 21, 30, tzinfo=UTC)).month == 8
        assert huidige_maand(datetime(2026, 8, 31, 22, 30, tzinfo=UTC)).month == 9

    def test_maandgrens_valt_op_lokale_middernacht_wintertijd(self) -> None:
        # 31 dec 23:30 UTC = 1 jan 00:30 in Amsterdam (CET, UTC+1) → nieuw jaar.
        assert huidige_maand(datetime(2026, 12, 31, 22, 30, tzinfo=UTC)) == datetime(2026, 12, 1).date()
        assert huidige_maand(datetime(2026, 12, 31, 23, 30, tzinfo=UTC)) == datetime(2027, 1, 1).date()

    def test_verbruik_telt_per_kalendermaand(self, admin_engine: Engine) -> None:
        _zet_limiet(admin_engine, Decimal("100"))
        augustus = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        september = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        registreer_verbruik(model="claude-sonnet-5", input_tokens=1_000_000, output_tokens=0, nu=augustus)
        # Augustus draagt € 3,00; september begint blanco — de poort is daar weer open,
        # ook als augustus vol had gezeten.
        assert haal_status_op(nu=augustus).verbruik_eur == Decimal("3.000000")
        assert haal_status_op(nu=september).verbruik_eur == Decimal("0")
        _zet_limiet(admin_engine, Decimal("3.000000"))
        with pytest.raises(AiKostenLimietBereikt):
            controleer_poort(model="claude-sonnet-5", nu=augustus)
        controleer_poort(model="claude-sonnet-5", nu=september)  # nieuwe maand: geen exception


class TestCumulatieEnPoort:
    def test_cumulatie_over_meerdere_aanroepen(self) -> None:
        nu = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        registreer_verbruik(model="claude-sonnet-5", input_tokens=100_000, output_tokens=0, nu=nu)
        registreer_verbruik(model="claude-opus-5", input_tokens=0, output_tokens=100_000, nu=nu)
        # € 0,30 (sonnet-input) + € 2,50 (opus-output) — Decimal-precies opgeteld.
        assert haal_status_op(nu=nu).verbruik_eur == Decimal("2.800000")

    def test_poort_blokkeert_exact_op_de_grens(self, admin_engine: Engine) -> None:
        nu = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        registreer_verbruik(model="claude-sonnet-5", input_tokens=1_000_000, output_tokens=0, nu=nu)  # € 3,00
        # Nét boven het verbruik (limiet is Numeric(12,2) — hele centen): poort open.
        _zet_limiet(admin_engine, Decimal("3.01"))
        controleer_poort(model="claude-sonnet-5", nu=nu)
        # Exact op de grens (verbruik == limiet): poort dicht — ≥, niet >.
        _zet_limiet(admin_engine, Decimal("3.000000"))
        with pytest.raises(AiKostenLimietBereikt):
            controleer_poort(model="claude-sonnet-5", nu=nu)

    def test_referentie_landt_in_de_log(self, admin_engine: Engine) -> None:
        nu = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        document_id = uuid.uuid4()
        registreer_verbruik(
            model="claude-sonnet-5",
            input_tokens=10,
            output_tokens=10,
            referentie=AiVerbruikReferentie(bron="inkoop_extractie", document_id=document_id),
            nu=nu,
        )
        with admin_engine.connect() as conn:
            rij = conn.execute(text("SELECT bron, document_id, model FROM platform.ai_gebruik")).one()
        assert rij.bron == "inkoop_extractie"
        assert rij.document_id == document_id
        assert rij.model == "claude-sonnet-5"


class TestMeldingen:
    def _audit_acties(self, admin_engine: Engine) -> list[str]:
        with admin_engine.connect() as conn:
            return (
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'ai_kosten_maandstatus' ORDER BY tijdstip"
                    )
                )
                .scalars()
                .all()
            )

    def test_80_procent_melding_eenmalig(self, admin_engine: Engine) -> None:
        _zet_limiet(admin_engine, Decimal("10"))
        nu = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        # 1e call: € 9 = 90% → waarschuwing. 2e call: nog steeds ≥80% → géén tweede melding.
        registreer_verbruik(model="claude-sonnet-5", input_tokens=3_000_000, output_tokens=0, nu=nu)
        registreer_verbruik(model="claude-sonnet-5", input_tokens=100_000, output_tokens=0, nu=nu)
        status = haal_status_op(nu=nu)
        assert status.waarschuwing_80_op is not None
        assert status.limiet_bereikt_op is None
        assert self._audit_acties(admin_engine) == ["ai_kosten_waarschuwing_80"]

    def test_limiet_bereikt_melding_eenmalig_en_blokkeert(self, admin_engine: Engine) -> None:
        _zet_limiet(admin_engine, Decimal("3"))
        nu = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        # Eén grote call springt van 0% over de 80% héén naar ≥100%: béíde meldingen, elk éénmalig.
        registreer_verbruik(model="claude-sonnet-5", input_tokens=1_000_000, output_tokens=0, nu=nu)
        registreer_verbruik(model="claude-sonnet-5", input_tokens=100, output_tokens=0, nu=nu)
        status = haal_status_op(nu=nu)
        assert status.waarschuwing_80_op is not None
        assert status.limiet_bereikt_op is not None
        assert status.geblokkeerd is True
        assert self._audit_acties(admin_engine) == ["ai_kosten_waarschuwing_80", "ai_kosten_limiet_bereikt"]
        with pytest.raises(AiKostenLimietBereikt):
            controleer_poort(model="claude-sonnet-5", nu=nu)
