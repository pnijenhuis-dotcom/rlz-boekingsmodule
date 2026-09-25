"""FV-05 (feedbackrun A 25-09, gebruikersfeedback Universal): verwijzingen naar bijlagen ("conform bijgevoegd
overzicht", "zie bijlage") worden uit de AUTOMATISCHE kop-omschrijving gestript — deterministische lijst, alleen als
staart van de tekst (een verwijzing midden in een zin blijft staan: knippen zou de betekenis breken), nooit inhoud
verzinnen; blijft er niets over, dan is de volgende bron aan de beurt. Chip "ingekort" via `KopOmschrijving.ingekort`.
Puur — geen database."""

from __future__ import annotations

import pytest

from app.documenten.kop_omschrijving import (
    HERKOMST_AFGELEID,
    HERKOMST_FACTUUR,
    HERKOMST_REGEL,
    bepaal_kop_omschrijving,
    strip_bijlageverwijzingen,
)


@pytest.mark.parametrize(
    ("tekst", "verwacht"),
    [
        ("huur juli conform bijgevoegd overzicht", "huur juli"),
        ("Huur juli (zie bijlage)", "Huur juli"),
        ("huur augustus, zie specificatie", "huur augustus"),
        ("huur juli cfm. overzicht", "huur juli"),
        ("Transport volgens bijlage 2.", "Transport"),
        ("levering 12-07 zie bijgevoegde specificatie voor details", "levering 12-07"),
        ("huur en montage conform onderliggende specificatie", "huur en montage"),
        ("Huur week 34 conform specificatie", "Huur week 34"),
        ("huur juli CONFORM BIJGEVOEGD OVERZICHT", "huur juli"),
        ("montage 10,5m 3 afslagen — zie bijlagen", "montage 10,5m 3 afslagen"),
    ],
)
def test_staart_verwijzing_wordt_gestript(tekst: str, verwacht: str) -> None:
    assert strip_bijlageverwijzingen(tekst) == (verwacht, True)


@pytest.mark.parametrize("tekst", ["zie bijlage", "Bijlage", "bijlagen.", "Zie bijlage:"])
def test_alleen_een_verwijzing_wordt_leeg(tekst: str) -> None:
    assert strip_bijlageverwijzingen(tekst) == (None, True)


@pytest.mark.parametrize(
    "tekst",
    [
        "zie bijlage voor de huur van juli",  # midden in een zin: nooit knippen
        "Steigerhuur week 27 — trappentoren 26014 Amersfoort",
        "overzicht juli",  # geen verwijzingswoord ervoor
        "levering 12-07",
    ],
)
def test_zonder_staartverwijzing_ongewijzigd(tekst: str) -> None:
    assert strip_bijlageverwijzingen(tekst) == (tekst, False)


def test_leeg_blijft_leeg() -> None:
    assert strip_bijlageverwijzingen(None) == (None, False)
    assert strip_bijlageverwijzingen("   ") == (None, False)


def test_regeltekst_ingekort_met_vlag() -> None:
    uit = bepaal_kop_omschrijving(
        regel_omschrijvingen=["huur juli conform bijgevoegd overzicht"],
        betreft=None,
        leverancier_naam="Universal Nederland B.V.",
        referentie="RLZ-2080142898",
    )
    assert (uit.tekst, uit.herkomst, uit.ingekort) == ("huur juli", HERKOMST_REGEL, True)


def test_regeltekst_zonder_verwijzing_geen_vlag() -> None:
    uit = bepaal_kop_omschrijving(regel_omschrijvingen=["huur juli"], betreft=None, leverancier_naam="X", referentie="1")
    assert (uit.tekst, uit.ingekort) == ("huur juli", False)


def test_regel_alleen_verwijzing_valt_door_naar_betreft() -> None:
    uit = bepaal_kop_omschrijving(
        regel_omschrijvingen=["zie bijlage"], betreft="Huur augustus zie specificatie", leverancier_naam="X", referentie="1"
    )
    assert (uit.tekst, uit.herkomst, uit.ingekort) == ("Huur augustus", HERKOMST_FACTUUR, True)


def test_alles_alleen_verwijzing_valt_door_naar_afgeleid() -> None:
    uit = bepaal_kop_omschrijving(
        regel_omschrijvingen=["zie bijlage"], betreft="conform bijlage", leverancier_naam="Floor", referentie="26219"
    )
    assert (uit.tekst, uit.herkomst, uit.ingekort) == ("Floor 26219", HERKOMST_AFGELEID, False)
