"""Harde omzet-checks (app/omzet/checks.py) — pure geldlogica, zonder DB of RLZ."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.omzet.checks import (
    MemoriaalRegel,
    OmzetCheckRegel,
    bereken_marge_pct,
    check_categorie_mapping,
    check_duplicaat_periode,
    check_marge_plausibiliteit,
    check_memoriaal_saldo_0,
    check_regelsom_omzet,
    check_verplichte_velden_omzet,
    voer_omzet_checks_uit,
)


def _regel(**overrides) -> OmzetCheckRegel:
    basis = dict(
        categorie="Weed",
        omzet_bedrag=Decimal("13655.33"),
        kostprijs_bedrag=Decimal("8585.32"),
        omzet_ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        kostprijs_ledger_id=uuid.uuid4(),
    )
    basis.update(overrides)
    return OmzetCheckRegel(**basis)


class TestVerplichteVelden:
    def test_compleet_is_ok(self) -> None:
        resultaat = check_verplichte_velden_omzet(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            regels=[_regel()],
            voorraad_ledger_id=uuid.uuid4(),
        )
        assert resultaat.ok

    def test_ontbrekende_periode_en_voorraad_blokkeren(self) -> None:
        resultaat = check_verplichte_velden_omzet(
            periode_start=None, periode_eind=None, regels=[_regel()], voorraad_ledger_id=None
        )
        assert not resultaat.ok
        assert "periode-begindatum" in resultaat.melding
        assert "voorraad-tegenrekening" in resultaat.melding

    def test_omgekeerde_periode_blokkeert(self) -> None:
        resultaat = check_verplichte_velden_omzet(
            periode_start=date(2025, 9, 21),
            periode_eind=date(2025, 9, 15),
            regels=[_regel()],
            voorraad_ledger_id=uuid.uuid4(),
        )
        assert not resultaat.ok

    def test_zonder_kostprijs_geen_voorraadeis(self) -> None:
        resultaat = check_verplichte_velden_omzet(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            regels=[_regel(kostprijs_bedrag=None, kostprijs_ledger_id=None)],
            voorraad_ledger_id=None,
        )
        assert resultaat.ok


class TestCategorieMapping:
    def test_complete_mapping_is_ok(self) -> None:
        assert check_categorie_mapping(regels=[_regel()]).ok

    def test_nieuwe_categorie_zonder_mapping_blokkeert_met_naam(self) -> None:
        resultaat = check_categorie_mapping(
            regels=[_regel(categorie="Edibles", omzet_ledger_id=None, taxrate_id=None)]
        )
        assert not resultaat.ok
        assert "Edibles" in resultaat.melding
        assert "omzet-GB" in resultaat.melding

    def test_kostprijs_zonder_kostprijs_gb_blokkeert(self) -> None:
        resultaat = check_categorie_mapping(regels=[_regel(kostprijs_ledger_id=None)])
        assert not resultaat.ok
        assert "kostprijs-GB" in resultaat.melding

    def test_geen_kostprijs_dan_geen_kostprijs_gb_nodig(self) -> None:
        assert check_categorie_mapping(
            regels=[_regel(kostprijs_bedrag=Decimal("0"), kostprijs_ledger_id=None)]
        ).ok


class TestRegelsom:
    def test_sluitende_sommen_zijn_ok(self) -> None:
        resultaat = check_regelsom_omzet(
            regels=[
                _regel(omzet_bedrag=Decimal("100.00"), kostprijs_bedrag=Decimal("60.00")),
                _regel(omzet_bedrag=Decimal("50.00"), kostprijs_bedrag=Decimal("40.00")),
            ],
            rapport_totaal_omzet=Decimal("150.00"),
            rapport_totaal_kostprijs=Decimal("100.00"),
        )
        assert resultaat.ok

    def test_cent_afronding_valt_binnen_tolerantie(self) -> None:
        resultaat = check_regelsom_omzet(
            regels=[_regel(omzet_bedrag=Decimal("100.01"), kostprijs_bedrag=Decimal("60.00"))],
            rapport_totaal_omzet=Decimal("100.00"),
            rapport_totaal_kostprijs=Decimal("60.00"),
        )
        assert resultaat.ok

    def test_afwijkende_omzetsom_blokkeert(self) -> None:
        resultaat = check_regelsom_omzet(
            regels=[_regel(omzet_bedrag=Decimal("100.00"))],
            rapport_totaal_omzet=Decimal("150.00"),
            rapport_totaal_kostprijs=Decimal("8585.32"),
        )
        assert not resultaat.ok

    def test_geen_rapport_totaal_blokkeert(self) -> None:
        resultaat = check_regelsom_omzet(
            regels=[_regel()], rapport_totaal_omzet=None, rapport_totaal_kostprijs=None
        )
        assert not resultaat.ok

    def test_half_aangeleverde_kostprijs_blokkeert(self) -> None:
        resultaat = check_regelsom_omzet(
            regels=[_regel(kostprijs_bedrag=Decimal("60.00"), omzet_bedrag=Decimal("100.00"))],
            rapport_totaal_omzet=Decimal("100.00"),
            rapport_totaal_kostprijs=None,
        )
        assert not resultaat.ok


class TestMemoriaalSaldo0:
    def test_sluitend_memoriaal_is_ok(self) -> None:
        resultaat = check_memoriaal_saldo_0(
            regels=[
                MemoriaalRegel(debet_bedrag=Decimal("8585.32")),
                MemoriaalRegel(debet_bedrag=Decimal("2668.82")),
                MemoriaalRegel(credit_bedrag=Decimal("11254.14")),
            ]
        )
        assert resultaat.ok

    def test_niet_sluitend_blokkeert_zonder_tolerantie(self) -> None:
        # Bewust géén afrondingstolerantie: het memoriaal is eigen constructie — één cent
        # verschil is een bug, geen afronding.
        resultaat = check_memoriaal_saldo_0(
            regels=[
                MemoriaalRegel(debet_bedrag=Decimal("100.00")),
                MemoriaalRegel(credit_bedrag=Decimal("99.99")),
            ]
        )
        assert not resultaat.ok
        assert "0.01" in resultaat.melding

    def test_leeg_memoriaal_blokkeert(self) -> None:
        assert not check_memoriaal_saldo_0(regels=[]).ok


class TestDuplicaatPeriode:
    def test_vrije_periode_is_ok(self) -> None:
        resultaat = check_duplicaat_periode(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            bestaande_periodes=[(date(2025, 9, 8), date(2025, 9, 14))],
            rlz_memoriaal_hits=0,
            rlz_verkoop_hits=0,
        )
        assert resultaat.ok

    def test_overlappende_periode_blokkeert(self) -> None:
        resultaat = check_duplicaat_periode(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            bestaande_periodes=[(date(2025, 9, 20), date(2025, 9, 26))],
            rlz_memoriaal_hits=0,
            rlz_verkoop_hits=0,
        )
        assert not resultaat.ok
        assert "2025-09-20" in resultaat.melding

    def test_rlz_memoriaal_hit_blokkeert(self) -> None:
        resultaat = check_duplicaat_periode(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            bestaande_periodes=[],
            rlz_memoriaal_hits=1,
            rlz_verkoop_hits=0,
        )
        assert not resultaat.ok

    def test_rlz_check_niet_uitvoerbaar_blokkeert_fail_closed(self) -> None:
        resultaat = check_duplicaat_periode(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            bestaande_periodes=[],
            rlz_memoriaal_hits=None,
            rlz_verkoop_hits=0,
        )
        assert not resultaat.ok

    def test_zonder_periode_blokkeert(self) -> None:
        resultaat = check_duplicaat_periode(
            periode_start=None, periode_eind=None, bestaande_periodes=[], rlz_memoriaal_hits=0, rlz_verkoop_hits=0
        )
        assert not resultaat.ok

    def test_rlz_verkoop_hit_blokkeert(self) -> None:
        """Receipts-verkenning: de verkoop-kant is sindsdien wél op afstand te bevragen — een
        vreemde Receipt met onze periode-omschrijving blokkeert."""
        resultaat = check_duplicaat_periode(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            bestaande_periodes=[],
            rlz_memoriaal_hits=0,
            rlz_verkoop_hits=1,
        )
        assert not resultaat.ok
        assert "verkoopboeking" in resultaat.melding

    def test_rlz_verkoop_check_niet_uitvoerbaar_blokkeert_fail_closed(self) -> None:
        resultaat = check_duplicaat_periode(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            bestaande_periodes=[],
            rlz_memoriaal_hits=0,
            rlz_verkoop_hits=None,
        )
        assert not resultaat.ok
        assert "kon niet uitgevoerd worden" in resultaat.melding


class TestMargePlausibiliteit:
    def test_marge_binnen_bandbreedte_is_ok(self) -> None:
        # Mockup-casus: marge 160% bij historisch gemiddeld 157% — binnen bandbreedte.
        resultaat = check_marge_plausibiliteit(
            totaal_omzet=Decimal("22463.36"),
            totaal_kostprijs=Decimal("14017.29"),
            historische_marges=[Decimal("157.0")],
            bandbreedte_procentpunt=Decimal("30"),
        )
        assert resultaat.ok
        assert "160.3" in resultaat.melding

    def test_marge_buiten_bandbreedte_blokkeert(self) -> None:
        resultaat = check_marge_plausibiliteit(
            totaal_omzet=Decimal("30000.00"),
            totaal_kostprijs=Decimal("10000.00"),  # 300%
            historische_marges=[Decimal("157.0"), Decimal("163.0")],
            bandbreedte_procentpunt=Decimal("30"),
        )
        assert not resultaat.ok

    def test_zonder_historie_ok_met_voorbehoud(self) -> None:
        resultaat = check_marge_plausibiliteit(
            totaal_omzet=Decimal("100"),
            totaal_kostprijs=Decimal("50"),
            historische_marges=[],
            bandbreedte_procentpunt=Decimal("30"),
        )
        assert resultaat.ok
        assert "eerste boeking" in resultaat.melding

    def test_zonder_kostprijs_geen_margecontrole(self) -> None:
        resultaat = check_marge_plausibiliteit(
            totaal_omzet=Decimal("100"),
            totaal_kostprijs=None,
            historische_marges=[Decimal("157.0")],
            bandbreedte_procentpunt=Decimal("30"),
        )
        assert resultaat.ok

    def test_bereken_marge_pct_deelt_nooit_door_nul(self) -> None:
        assert bereken_marge_pct(totaal_omzet=Decimal("100"), totaal_kostprijs=Decimal("0")) is None


class TestVoerOmzetChecksUit:
    def test_alle_zes_rijen_altijd_aanwezig(self) -> None:
        rapport = voer_omzet_checks_uit(
            periode_start=None,
            periode_eind=None,
            regels=[],
            voorraad_ledger_id=None,
            memoriaal_regels=[],
            rapport_totaal_omzet=None,
            rapport_totaal_kostprijs=None,
            bestaande_periodes=[],
            rlz_memoriaal_hits=0,
            rlz_verkoop_hits=0,
            historische_marges=[],
            bandbreedte_procentpunt=Decimal("30"),
        )
        assert len(rapport.resultaten) == 6
        assert rapport.geblokkeerd

    def test_zonder_kostprijs_is_saldo_check_ok_zonder_memoriaal(self) -> None:
        rapport = voer_omzet_checks_uit(
            periode_start=date(2025, 9, 15),
            periode_eind=date(2025, 9, 21),
            regels=[_regel(kostprijs_bedrag=None, kostprijs_ledger_id=None, omzet_bedrag=Decimal("100.00"))],
            voorraad_ledger_id=None,
            memoriaal_regels=[],
            rapport_totaal_omzet=Decimal("100.00"),
            rapport_totaal_kostprijs=None,
            bestaande_periodes=[],
            rlz_memoriaal_hits=0,
            rlz_verkoop_hits=0,
            historische_marges=[],
            bandbreedte_procentpunt=Decimal("30"),
        )
        saldo = next(r for r in rapport.resultaten if r.naam == "Memoriaal-saldo 0")
        assert saldo.ok
        assert not rapport.geblokkeerd
