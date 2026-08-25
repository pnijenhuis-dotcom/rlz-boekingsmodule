"""Harde-checks-tests doorbelasting (opdracht blok 1e) — puur, zonder DB."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.doorbelasting.checks import (
    MappingInvoer,
    VerdeelRegelInvoer,
    check_bedragen_sluiten,
    check_mapping_en_config,
    check_onboarded_doelen_boekbaar,
    check_verdeling_100,
    voer_doorbelasting_checks_uit,
)

D = Decimal
BRON_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
BRON_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
MAP_1 = uuid.UUID("00000000-0000-0000-0000-000000000101")
MAP_2 = uuid.UUID("00000000-0000-0000-0000-000000000102")
GB = uuid.UUID("00000000-0000-0000-0000-000000000901")
TAXRATE = uuid.UUID("00000000-0000-0000-0000-000000000801")


def _regel(
    bron: uuid.UUID = BRON_A,
    mapping: uuid.UUID = MAP_1,
    pct: str = "100",
    netto: str = "100.00",
    deel: str = "100.00",
    doel_gb: uuid.UUID | None = GB,
) -> VerdeelRegelInvoer:
    return VerdeelRegelInvoer(
        bron_regel_id=bron,
        bron_netto=D(netto),
        mapping_id=mapping,
        percentage=D(pct),
        netto_deel=D(deel),
        doel_kosten_ledger_id=doel_gb,
    )


def _mapping(mapping: uuid.UUID = MAP_1, *, actief: bool = True, onboarded: bool = True) -> MappingInvoer:
    return MappingInvoer(
        mapping_id=mapping,
        actief=actief,
        doel_administratie_id=uuid.uuid4() if onboarded else None,
        provisie_kosten_ledger_id=GB if onboarded else None,
    )


class TestVerdeling100:
    def test_ok_bij_exact_100(self) -> None:
        r = check_verdeling_100([_regel(pct="60", deel="60.00"), _regel(mapping=MAP_2, pct="40", deel="40.00")])
        assert r.ok

    def test_blokkeert_onder_100(self) -> None:
        r = check_verdeling_100([_regel(pct="60", deel="60.00")])
        assert not r.ok
        assert "60" in r.melding

    def test_blokkeert_boven_100(self) -> None:
        r = check_verdeling_100([_regel(pct="60"), _regel(mapping=MAP_2, pct="50")])
        assert not r.ok

    def test_blokkeert_zonder_regels(self) -> None:
        assert not check_verdeling_100([]).ok

    def test_per_bron_regel_apart(self) -> None:
        # regel A op 100%, regel B op 90% → blokkeert op B
        r = check_verdeling_100([_regel(bron=BRON_A, pct="100"), _regel(bron=BRON_B, pct="90")])
        assert not r.ok
        assert str(BRON_B) in r.melding


class TestBedragenSluiten:
    def test_ok(self) -> None:
        regels = [
            _regel(pct="50", netto="411.10", deel="205.55"),
            _regel(mapping=MAP_2, pct="50", netto="411.10", deel="205.55"),
        ]
        assert check_bedragen_sluiten(regels, provisie_percentage=D(5)).ok

    def test_blokkeert_bij_kwijtgeraakte_cent(self) -> None:
        regels = [
            _regel(pct="50", netto="411.10", deel="205.55"),
            _regel(mapping=MAP_2, pct="50", netto="411.10", deel="205.54"),
        ]
        r = check_bedragen_sluiten(regels, provisie_percentage=D(5))
        assert not r.ok

    def test_verwachte_totalen_per_doelentiteit(self) -> None:
        regels = [_regel(netto="357.00", deel="357.00")]
        ok = check_bedragen_sluiten(
            regels,
            provisie_percentage=D(5),
            verwachte_totalen_per_mapping={MAP_1: (D("357.00"), D("17.85"))},
        )
        assert ok.ok
        fout = check_bedragen_sluiten(
            regels,
            provisie_percentage=D(5),
            verwachte_totalen_per_mapping={MAP_1: (D("357.00"), D("17.84"))},
        )
        assert not fout.ok


class TestMappingEnConfig:
    def test_ok(self) -> None:
        r = check_mapping_en_config(
            [_regel()], {MAP_1: _mapping()}, btw_taxrate_id=TAXRATE, omzet_ledger_id=GB
        )
        assert r.ok

    def test_blokkeert_zonder_btw_config(self) -> None:
        r = check_mapping_en_config([_regel()], {MAP_1: _mapping()}, btw_taxrate_id=None, omzet_ledger_id=GB)
        assert not r.ok
        assert "btw" in r.melding.lower()

    def test_blokkeert_zonder_omzet_gb(self) -> None:
        r = check_mapping_en_config([_regel()], {MAP_1: _mapping()}, btw_taxrate_id=TAXRATE, omzet_ledger_id=None)
        assert not r.ok

    def test_blokkeert_onbekende_mapping(self) -> None:
        r = check_mapping_en_config([_regel()], {}, btw_taxrate_id=TAXRATE, omzet_ledger_id=GB)
        assert not r.ok
        assert "whitelist" in r.melding

    def test_blokkeert_inactieve_mapping(self) -> None:
        r = check_mapping_en_config(
            [_regel()], {MAP_1: _mapping(actief=False)}, btw_taxrate_id=TAXRATE, omzet_ledger_id=GB
        )
        assert not r.ok


class TestOnboardedDoelenBoekbaar:
    def test_onboarded_zonder_doel_gb_blokkeert(self) -> None:
        r = check_onboarded_doelen_boekbaar([_regel(doel_gb=None)], {MAP_1: _mapping()})
        assert not r.ok

    def test_onboarded_zonder_provisie_gb_blokkeert(self) -> None:
        mapping = MappingInvoer(
            mapping_id=MAP_1, actief=True, doel_administratie_id=uuid.uuid4(), provisie_kosten_ledger_id=None
        )
        r = check_onboarded_doelen_boekbaar([_regel()], {MAP_1: mapping})
        assert not r.ok

    def test_niet_onboarded_doel_is_geen_blokkade(self) -> None:
        # bewust: dat wordt een open spiegel-taak, geen fout (opdracht 1c)
        r = check_onboarded_doelen_boekbaar([_regel(doel_gb=None)], {MAP_1: _mapping(onboarded=False)})
        assert r.ok


def test_rapport_bundelt_alle_checks() -> None:
    rapport = voer_doorbelasting_checks_uit(
        regels=[_regel()],
        mappings={MAP_1: _mapping()},
        provisie_percentage=D(5),
        btw_taxrate_id=TAXRATE,
        omzet_ledger_id=GB,
    )
    assert len(rapport.resultaten) == 6  # incl. project-verplicht-doel (25-08)
    assert not rapport.geblokkeerd
