"""Rekeningcategorieën, termijnen en fiscale signalen voor activa (pure code — geen DB, geen RLZ, geen AI).

Ontwerp §3 (akkoord Peter 21-09, alle defaults §8): lineair, restwaarde 0, termijn per REKENINGCATEGORIE — de categorie
volgt deterministisch uit de rekeningnaam (RLZ kent geen default per rekening). De module berekent NOOIT zelf de
afschrijving (kernprincipe 2): `fiscale_signalen` toetst alleen en signaleert; de adviseur beslist.

`is_mva_rekening` is de bron-toets uit STAP-0 a9 (vlag alleen is te breed): `IsFixedAssetAccount` ÉN AccountType 3 ÉN
code in de 0xxx-reeks — dezelfde regel als `app/activa/nulmeting.py::is_mva_rekening`; de Ledgers-sync schrijft de
uitkomst in `grootboekrekening.is_activa` (migratie 0168).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

MAANDEN_PER_JAAR = 12
MIN_TERMIJN_MAANDEN = 12
MAX_TERMIJN_MAANDEN = 600
#: Fiscale ondergrens: afschrijving max 20 % per jaar (art. 3.30 Wet IB 2001) → termijn ≥ 60 maanden.
FISCALE_ONDERGRENS_MAANDEN = 60
STANDAARD_GRENS = Decimal("450.00")


@dataclass(frozen=True)
class Categorie:
    code: str
    label: str
    default_maanden: int


#: Volgorde = weergavevolgorde in de instelling; `onbekend` sluit af (controleer-chip).
CATEGORIEEN: tuple[Categorie, ...] = (
    Categorie("gebouwen", "Gebouwen en terreinen", 360),
    Categorie("inventaris", "Inventaris", 60),
    Categorie("vervoermiddelen", "Vervoermiddelen", 60),
    Categorie("computers_software", "Computers / software", 36),
    Categorie("machines", "Machines", 60),
    # Besluit Peter 16-09 (avond): steigermateriaal 5 jaar lineair, restwaarde 0 (fiscale ondergrens = default).
    Categorie("steigermateriaal", "Steigermateriaal", 60),
    Categorie("onbekend", "Onbekend — controleer", 60),
)
PER_CODE: dict[str, Categorie] = {c.code: c for c in CATEGORIEEN}
ONBEKEND = "onbekend"

#: Naamdelen per categorie — eerste treffer in DEZE volgorde wint (contract A: steiger vóór alles, gebouwen vóór
#: vervoer, …). Hoofdletterongevoelig, deelwoord-match.
_NAAMDELEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("steigermateriaal", ("steiger",)),
    (
        "gebouwen",
        ("gebouw", "terrein", "pand", "grond", "onroerend", "woning", "straat", "weg", "laan", "plein", "dreef"),
    ),
    ("vervoermiddelen", ("auto", "bus", "bestel", "vervoer", "aanhang", "voertuig", "vrachtwagen")),
    ("computers_software", ("computer", "ict", "software", "hardware", "laptop", "server", "apparatuur")),
    ("machines", ("machine", "installatie", "gereedschap", "verhuurmateriaal")),
    ("inventaris", ("inventaris", "meubil", "kantoor")),
)


def is_mva_rekening(rij: dict[str, Any]) -> bool:
    """RLZ-rekening = MVA: vlag ÉN AccountType 3 ÉN code 0xxx ÉN geen totaalrekening (STAP-0 a9)."""
    code = str(rij.get("AccountNumber") or "")
    return (
        bool(rij.get("IsFixedAssetAccount"))
        and rij.get("AccountType") == 3
        and code.startswith("0")
        and not rij.get("IsTotalAccount")
    )


def bepaal_categorie(code: str, naam: str) -> str:
    """Deterministisch op de REKENINGNAAM; `code` is meegegeven voor de toekomst (RGS-reeksen), nu niet gebruikt
    voor de keuze. Geen treffer → `onbekend` (kaart toont "controleer")."""
    lager = (naam or "").lower()
    for categorie, delen in _NAAMDELEN:
        if any(deel in lager for deel in delen):
            return categorie
    return ONBEKEND


def label_voor(categorie: str) -> str:
    c = PER_CODE.get(categorie)
    return c.label if c is not None else PER_CODE[ONBEKEND].label


def termijn_voor(categorie: str, instelling_termijnen: dict | None) -> int:
    """Instelling per administratie wint; anders de ontwerp-default van de categorie (onbekende categorie → 60)."""
    if instelling_termijnen:
        waarde = instelling_termijnen.get(categorie)
        if waarde is not None:
            try:
                maanden = int(waarde)
            except (TypeError, ValueError):
                maanden = 0
            if maanden > 0:
                return maanden
    c = PER_CODE.get(categorie)
    return c.default_maanden if c is not None else PER_CODE[ONBEKEND].default_maanden


def methode_naam(maanden: int) -> str:
    """RLZ-benaming "Lineair N jaar"; maanden die geen veelvoud van 12 zijn ronden naar boven af."""
    jaren = max(1, -(-int(maanden) // MAANDEN_PER_JAAR))
    return f"Lineair {jaren} jaar"


def termijn_geldig(maanden: object) -> bool:
    """Instelling: 12..600 maanden, veelvoud van 12 (de RLZ-methodes "Lineair N jaar")."""
    return (
        isinstance(maanden, int)
        and not isinstance(maanden, bool)
        and MIN_TERMIJN_MAANDEN <= maanden <= MAX_TERMIJN_MAANDEN
        and maanden % MAANDEN_PER_JAAR == 0
    )


@dataclass(frozen=True)
class Signaal:
    code: str
    tekst: str


def fiscale_signalen(*, categorie: str, termijn_maanden: int, aanschafwaarde: Decimal, grens: Decimal) -> list[Signaal]:
    """Toetsen, nooit rekenen (ontwerp §3). Volgorde is stabiel (kaart-chips)."""
    uit: list[Signaal] = []
    if termijn_maanden < FISCALE_ONDERGRENS_MAANDEN and categorie != "gebouwen":
        uit.append(
            Signaal(
                "afschrijving_boven_20pct",
                "afschrijving > 20 % per jaar (art. 3.30 Wet IB) — termijn controleren",
            )
        )
    if categorie == "gebouwen":
        uit.append(Signaal("bodemwaarde_woz", "gebouw: afschrijven tot de bodemwaarde (WOZ) — controleren"))
    if aanschafwaarde >= grens:
        uit.append(Signaal("kia_mia_mogelijk", "KIA/MIA/Vamil mogelijk van toepassing — adviseur beslist"))
    if categorie == ONBEKEND:
        uit.append(Signaal("categorie_onbekend", "rekeningcategorie niet herkend — controleer termijn en categorie"))
    return uit
