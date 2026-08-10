"""Btw-eenheid en categorie-semantiek van de taxrate-cache (blok A grote opdracht 2026-08-10).

CANONIEKE EENHEID: de FRACTIE, exact het RLZ-bronformaat (`GET TaxRates` → `Percentage: 0.21`
voor 21%; live geverifieerd 2026-07-11, api-verkenning "TaxRate.Percentage").
`taxrate_cache.percentage` draagt dus 0.2100 — nooit 21. UBL (cbc:Percent) draagt daarentegen
een PERCENTAGE (21.00). Elke vergelijking of berekening over die grens gaat via
`ubl_percent_naar_fractie` — nooit een rechtstreekse vergelijking (de btw-automatch-bevinding
2026-08-09, registers/verbeteringen.md: fixtures in bronformaat, normalisatie op de grens).

CATEGORIE-SEMANTIEK (UNCL5305 → RLZ-taxrate-vlaggen, live geverifieerd 2026-07-13,
api-verkenning "TaxRate.Percentage — aanvulling"): een RLZ-tarief dekt een UBL-regel alleen
als categorie én percentage kloppen — nooit op percentage alleen (21% regulier ≠ 21% verlegd):

- `AE` (verlegd)      → `IsRelayed: true` (RLZ-percentage is dan 0.0; het UBL-percentage doet
                        niet mee — EN 16931 BR-AE-05 schrijft 0 voor, maar de vlag is leidend).
- `E`  (vrijgesteld)  → `IsExcempt: true` én niet verlegd.
- `Z`  (nul-tarief)   → percentage 0, niet verlegd, niet vrijgesteld.
- `S`  (standaard)    → percentage exact gelijk (fractie), > 0, niet verlegd, niet vrijgesteld.

Andere UNCL5305-categorieën (K, G, O, L, M) komen in de Vastly-stroom niet voor en resolven
bewust niet deterministisch (mens kiest; de harde btw-check blijft de poort)."""

from __future__ import annotations

from decimal import Decimal

# UNCL5305-categorieën waarvoor de deterministische afleiding bestaat.
ONDERSTEUNDE_CATEGORIEEN = frozenset({"S", "E", "Z", "AE"})

# Categorieën waarvan het tarief per definitie 0 is — een ontbrekend cbc:Percent betekent
# daar gewoon 0, geen onbepaaldheid.
_NUL_CATEGORIEEN = frozenset({"E", "Z", "AE"})


def ubl_percent_naar_fractie(percent: Decimal) -> Decimal:
    """UBL-percentage (21.00) → canonieke fractie (0.21). Dé enige toegestane oversteek."""
    return percent / Decimal(100)


def normaliseer_categorie(categorie: str | None) -> str | None:
    """UBL ClassifiedTaxCategory/cbc:ID → genormaliseerde categoriecode, of None wanneer de
    categorie ontbreekt of niet ondersteund wordt (→ geen deterministische afleiding)."""
    code = (categorie or "").strip().upper()
    return code if code in ONDERSTEUNDE_CATEGORIEEN else None


def factuur_fractie(categorie: str | None, percent: Decimal | None) -> Decimal | None:
    """De canonieke fractie die de factuurregel voorschrijft, of None als die niet bepaalbaar
    is. Voor de nul-categorieën (E/Z/AE) is een ontbrekend percentage gewoon 0."""
    code = normaliseer_categorie(categorie)
    if code is None:
        return None
    if percent is None:
        return Decimal(0) if code in _NUL_CATEGORIEEN else None
    return ubl_percent_naar_fractie(percent)


def taxrate_vlaggen(brondata: dict | None) -> tuple[bool, bool]:
    """(is_verlegd, is_vrijgesteld) uit de RLZ-brondata van een taxrate-cache-rij.
    NB RLZ spelt het veld `IsExcempt` (sic) — live geverifieerd."""
    data = brondata or {}
    return bool(data.get("IsRelayed")), bool(data.get("IsExcempt"))


def taxrate_dekt_factuur_btw(
    *,
    categorie: str | None,
    factuur_pct: Decimal | None,
    taxrate_percentage: Decimal | None,
    is_verlegd: bool,
    is_vrijgesteld: bool,
) -> bool:
    """Dekt dit RLZ-tarief de btw die de factuurregel voorschrijft (categorie + percentage)?
    `factuur_pct` is het UBL-percentage (21.00) — de fractie-normalisatie gebeurt hier."""
    code = normaliseer_categorie(categorie)
    if code is None:
        return False
    if code == "AE":
        return is_verlegd
    if is_verlegd:
        return False
    if code == "E":
        return is_vrijgesteld
    if is_vrijgesteld:
        return False
    fractie = factuur_fractie(code, factuur_pct)
    if fractie is None or taxrate_percentage is None:
        return False
    if code == "Z":
        return taxrate_percentage == 0
    # S: exacte percentage-match, en 0% is per definitie geen standaardtarief.
    return fractie > 0 and taxrate_percentage == fractie
