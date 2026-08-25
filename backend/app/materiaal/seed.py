"""Seed van de materiaalcatalogus uit Peters bestellijst (verkenning/voorbeelden/
bestellijst-universal-voorbeeld.xlsx, aangeleverd 24-08): blad 1 = steigermateriaal per
categorie mét verpakkingseenheid, blad 2 = trappentoren (RS-onderdelen). De m²-totaalformule
uit het blad — `=(D28*1+D19*2.8+D18*2+D20*3+D21*4+D22*1.4+D23*2)/4.6` — is per product vertaald
naar `m2_lengte` (meter); producten zonder lengte tellen niet mee in de bundel-m².

Deterministisch en idempotent (upsert op leverancier-naam / categorie-naam / product-naam);
nooit verwijderen — een product dat uit de lijst verdwijnt blijft (inactief zetten is klikwerk).
Aanroep: `make materiaal-seed-universal ADMINISTRATIE_ID=… BEHEERDER_ID=…` (CLI) of de
kantoor-knop "Standaardcatalogus laden" (Beheerder)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SeedProduct:
    naam: str
    verpakking: str | None
    m2_lengte: Decimal | None = None
    eenheid: str = "stuks"


@dataclass(frozen=True)
class SeedCategorie:
    naam: str
    bundel: str
    producten: tuple[SeedProduct, ...]


UNIVERSAL_LEVERANCIER = {
    "naam": "Universal Nederland B.V.",
    "bestel_email": "reijer@universalbv.nl",
    "telefoon": "06-51 27 72 51",
    "adres": "Ekkersrijt 2012, 5692 BA Son en Breugel",
}

UNIVERSAL_CATALOGUS: tuple[SeedCategorie, ...] = (
    SeedCategorie(
        "Tubelock",
        "steiger",
        (
            SeedProduct("Steigerbuis tubelock 0,5 mtr", "150 st."),
            SeedProduct("Steigerbuis tubelock 2 mtr", "100 st.", Decimal("2")),
            SeedProduct("Steigerbuis tubelock 2,8 mtr", "50 st.", Decimal("2.8")),
            SeedProduct("Steigerbuis tubelock 3 mtr", "50 st.", Decimal("3")),
            SeedProduct("Steigerbuis tubelock 4 mtr", "50 st.", Decimal("4")),
            SeedProduct("Uitzetkorteling 6 pl.", "75 st.", Decimal("1.4")),
            SeedProduct("Uitschuiver 6+3-planks tube-lock", "75 st.", Decimal("2")),
            SeedProduct("Uitschuifverlenger 1-planks", "250 st."),
        ),
    ),
    SeedCategorie(
        "Ladders",
        "steiger",
        (SeedProduct("Stalen ladder 3 mtr", "st."), SeedProduct("Stalen ladder 4 mtr", "st.")),
    ),
    SeedCategorie(
        "Verankeringen",
        "steiger",
        (
            SeedProduct("Steigerogen met plug (lang)", "100 st."),
            SeedProduct("Ankerbuis layher", "150 st.", Decimal("1")),
            SeedProduct("Verankeringsbuis 1,2 mtr", "100 st."),
            SeedProduct("Ankerbuis + varkensstaartje 1 mtr", "100 st."),
        ),
    ),
    SeedCategorie(
        "Koppelingen",
        "steiger",
        (
            SeedProduct("Kruiskoppeling", "250 st."),
            SeedProduct("Draaikoppeling", "250 st."),
            SeedProduct("Voetplaat tube-lock", "300 st."),
        ),
    ),
    SeedCategorie(
        "Steigerdelen",
        "steiger",
        (
            SeedProduct("Steigerdelen gekramd 0,5 mtr", "100 st."),
            SeedProduct("Steigerdelen gekramd 2 mtr", "50 st."),
            SeedProduct("Steigerdelen gekramd 3 mtr", "50 st."),
            SeedProduct("Steigerdelen gekramd 5 mtr", "50 st."),
            SeedProduct("Pijpstoeltje", "p. st."),
            SeedProduct("Hoge beun", "p. st."),
            SeedProduct("Stempelcontainer ZM", "p. st."),
            SeedProduct("Koppelingscontainer", "p. st."),
        ),
    ),
    SeedCategorie(
        "Tralieliggers",
        "steiger",
        (SeedProduct("Tralieligger 3 mtr", "p. st."), SeedProduct("Tralieligger 4 mtr", "p. st.")),
    ),
    SeedCategorie(
        "Renovatie",
        "steiger",
        (SeedProduct("Schuifkorteling smal 4+3", "p. st."), SeedProduct("Uitzetkorteling smal 4 planks", "p. st.")),
    ),
    SeedCategorie(
        "Diversen",
        "steiger",
        (
            SeedProduct("Metselboy", "p. st."),
            SeedProduct("Binnenleuningklem", "250 st."),
            SeedProduct("Binnenhoekconsole", "18 st."),
            SeedProduct("Steigergaas", "rol", eenheid="rol"),
            SeedProduct("Tie wraps", "100 st."),
        ),
    ),
    # Blad 2: trappentoren (RS-onderdelen) — eigen bundel, geen m²-formule.
    SeedCategorie(
        "RS Staanders",
        "trappentoren",
        (
            SeedProduct("RS Staander 1 mtr", None),
            SeedProduct("RS Staander 2 mtr", None),
            SeedProduct("RS Staander 3 mtr", None),
        ),
    ),
    SeedCategorie(
        "RS Liggers",
        "trappentoren",
        (
            SeedProduct("RS Ligger 1,40 mtr", None),
            SeedProduct("RS Ligger 2,07 mtr", None),
            SeedProduct("RS Ligger 2,57 mtr", None),
        ),
    ),
    SeedCategorie(
        "RS Geveldiagonalen",
        "trappentoren",
        (
            SeedProduct("RS Geveldiagonaal 1,40 x 2,00 mtr", None),
            SeedProduct("RS Geveldiagonaal 2,57 x 2,00 mtr", None),
        ),
    ),
    SeedCategorie(
        "RS Bordestrap",
        "trappentoren",
        (
            SeedProduct("RS Alu Bordestrap 1 mtr", None),
            SeedProduct("RS Bordestrap buitenleuning 1 mtr", None),
            SeedProduct("RS Alu Bordestrap 2,57 x 2,00 mtr met buisoplegging", None),
            SeedProduct("RS Bordestrap buitenleuning 2,57 x 2,00 mtr", None),
            SeedProduct("RS Bordestrap binnenleuning 2,57 x 2,00 mtr", None),
        ),
    ),
    SeedCategorie(
        "RS Diversen",
        "trappentoren",
        (
            SeedProduct("RS Voetspindel 60 cm", None),
            SeedProduct("RS Voetstuk 0,2 mtr", None),
            SeedProduct("RS Vloerdeel buisoplegging 2,57 x 0,32 mtr", None),
            SeedProduct("Consoles", None),
            SeedProduct("RS Buitenleuningadapter", None),
            SeedProduct("Losse borgpen voor staanders", None),
        ),
    ),
)
