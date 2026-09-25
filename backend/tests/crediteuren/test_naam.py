"""Blok 2 feedbackrun A 25-09 (FV-21): één crediteurnaam-normalisatie (`app/crediteuren/naam.py`) — puur, geen DB."""

from __future__ import annotations

import pytest

from app.crediteuren.naam import normaliseer_crediteurnaam, zelfde_crediteurnaam
from app.extractie.controle import VendorKandidaat, _genormaliseerd, match_vendor_met_waarschuwing


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Floor Bouwliftenservice", "Floor bouwliftenservice"),  # casus Floor: alleen hoofdletters
        ("Floor Bouwliftenservice", "Floor bouwliftenservice B.V."),  # + rechtsvorm
        ("Universal Nederland B.V.", "Universal nederland B.V."),  # casus Universal Nederland
        ("Universal Nederland B.V.", "UNIVERSAL NEDERLAND BV"),
        ("Wola b.v.", "Wola"),
        ("Jansen Bouw B.V.", "Jansen Bouw B V"),
        ("Café Nöl v.o.f.", "Cafe Nol VOF"),  # diakrieten
        ("Labo-Derva, B.V.", "Labo Derva"),  # leestekens/spaties
    ],
)
def test_zelfde_sleutel_over_schrijfwijzen(a: str, b: str) -> None:
    assert normaliseer_crediteurnaam(a) == normaliseer_crediteurnaam(b)
    assert zelfde_crediteurnaam(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Universal Nederland B.V.", "Universal Verkoop B.V."),  # gelijkend maar ánders
        ("Bouwadvies Oost", "Bouwadvies West"),
        ("BLOW Holding", "BLOW B.V."),  # "Holding" blijft onderscheidend (regel intake 27/28-08)
        ("CVketel Service", "Ketel Service"),  # "cv" binnen een woord is geen rechtsvorm
        ("Floor Bouwliftenservice", "Floor Beheer B.V."),
    ],
)
def test_andere_naam_andere_sleutel(a: str, b: str) -> None:
    assert normaliseer_crediteurnaam(a) != normaliseer_crediteurnaam(b)
    assert not zelfde_crediteurnaam(a, b)


def test_leeg_en_alleen_rechtsvorm_geven_lege_sleutel() -> None:
    assert normaliseer_crediteurnaam(None) == ""
    assert normaliseer_crediteurnaam("   ") == ""
    assert normaliseer_crediteurnaam("B.V.") == ""
    assert not zelfde_crediteurnaam("B.V.", "BV")


def test_extractie_match_gebruikt_dezelfde_sleutel() -> None:
    """De crediteur-match van de extractie (`_genormaliseerd`) leest sinds 25-09 dezelfde functie: een factuur
    "Floor bouwliftenservice B.V." landt exact (score 1.0) op de crediteur "Floor Bouwliftenservice"; "Jansen Holding"
    landt niet stil op "Jansen B.V."."""
    assert _genormaliseerd("Floor bouwliftenservice B.V.") == normaliseer_crediteurnaam("Floor Bouwliftenservice")
    floor = VendorKandidaat(id=__import__("uuid").uuid4(), naam="Floor Bouwliftenservice")
    beheer = VendorKandidaat(id=__import__("uuid").uuid4(), naam="Floor Beheer B.V.")
    vendor_id, match, waarschuwing = match_vendor_met_waarschuwing("Floor bouwliftenservice B.V.", [floor, beheer])
    assert vendor_id == floor.id and match == "fuzzy" and waarschuwing is None
    jansen = VendorKandidaat(id=__import__("uuid").uuid4(), naam="Jansen B.V.")
    assert match_vendor_met_waarschuwing("Jansen Holding", [jansen])[0] is None
