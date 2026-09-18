"""Casus (z) — offerte-verbruik = geboekt + onderweg (Peter 18-09, accordeur-app, Bouwadvies Oost Nederland: "ik
heb net een factuur geaccordeerd van deze partij voor € 20.000, deze boeking zegt nu binnen offerte (50.000 van
bedrag), maar dat moet 20.000 + 50.000 (70.000) zijn, hij moet wel doortellen"). Echte productiegetallen
(leesreplica 18-09 20:50): verplichting zonder nummer € 1.192.922,50, boekstand 0, drie facturen ter accordering
— 32948 € 20.000, 32949 € 50.000, 33122 € 80.000. Puur op de match-motor (`app/verplichting/match.py`): de toets
van 32949 ziet de twee andere als ONDERWEG, het cumulatief ná deze factuur is € 150.000,00 en de kaart zegt
waarom ("waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)"). De DB-keten (statuswissel →
herberekening → tijdlijnregel) staat in `tests/verplichting/test_verbruik.py::TestOnderweg`."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.verplichting import match as m

BOUWADVIES = "vendor:a9b2c4d6-0000-4000-8000-000000032949"
PROJECT = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
OFFERTE_ZONDER_NUMMER = Decimal("1192922.50")


def _kandidaat(*, onderweg: str, aantal: int, ter_accordering: int) -> m.Kandidaat:
    return m.Kandidaat(
        document_id=uuid.UUID("34aaf45b-69b7-41e8-93d7-dbcf1f84c08d"),
        project_id=PROJECT,
        offertenummer=None,
        soort_label="offerte",
        goedgekeurd_bedrag_excl=OFFERTE_ZONDER_NUMMER,
        verbruikt_bedrag_excl=Decimal("0.00"),
        aantal_gematcht=aantal,
        onderweg_bedrag_excl=Decimal(onderweg),
        onderweg_aantal=aantal,
        onderweg_ter_accordering=ter_accordering,
    )


def _factuur_32949() -> m.FactuurFeiten:
    return m.FactuurFeiten(
        document_id=uuid.uuid4(),
        vendor_sleutel=BOUWADVIES,
        project_id=PROJECT,
        bedrag_excl=Decimal("50000.00"),
        factuurdatum=date(2026, 9, 18),
        teksten=("32949", "2e termijn werkzaamheden"),
    )


def test_32949_telt_de_twee_andere_ter_accordering_facturen_mee() -> None:
    uit = m.bepaal_match(_factuur_32949(), [_kandidaat(onderweg="100000.00", aantal=2, ter_accordering=2)])
    assert uit.uitkomst == m.BINNEN
    assert uit.verbruik_voor == Decimal("100000.00")
    assert uit.verbruik_na == Decimal("150000.00")
    assert uit.details["verbruik_geboekt"] == "0.00"
    assert uit.details["verbruik_onderweg"] == "100000.00"
    assert uit.details["onderweg_aantal"] == 2
    assert uit.details["onderweg_ter_accordering"] == 2
    assert uit.details["termijn"] == 3
    assert "€ 150.000,00 van € 1.192.922,50" in uit.melding
    assert "waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)" in uit.melding


def test_peters_moment_20_04_alleen_32948_onderweg_geeft_70_000() -> None:
    # Vóór 33122 binnenkwam (een minuut later): 20.000 onderweg + 50.000 eigen = 70.000 — precies Peters verwachting.
    uit = m.bepaal_match(_factuur_32949(), [_kandidaat(onderweg="20000.00", aantal=1, ter_accordering=1)])
    assert uit.uitkomst == m.BINNEN
    assert uit.verbruik_na == Decimal("70000.00")
    assert "€ 70.000,00 van € 1.192.922,50" in uit.melding
    assert "waarvan € 20.000,00 nog niet geboekt (1 factuur ter accordering)" in uit.melding


def test_stale_matchrij_zonder_onderweg_is_het_oude_gedrag_dat_de_nazorg_cli_herstelt() -> None:
    # Een matchrij van vóór de deploy droeg onderweg 0 → "€ 50.000,00 van …" zonder zin; de CLI
    # `verplichting-match-herberekenen` herberekent die rijen ná de deploy (vervolg-opdracht).
    uit = m.bepaal_match(_factuur_32949(), [_kandidaat(onderweg="0.00", aantal=0, ter_accordering=0)])
    assert uit.verbruik_na == Decimal("50000.00")
    assert "€ 50.000,00 van € 1.192.922,50" in uit.melding
    assert "nog niet geboekt" not in uit.melding
