"""Guard (BUG Peter 21-09, checks-cache-invalidatie op de bron): élk schrijfpad naar `boekhouding.leverancier_iban` — élke
module die een `LeverancierIban(`-rij construeert — roept in dezelfde module `checks_extern.maak_ongeldig_voor_vendor(`
aan. Een nieuw schrijfpad zonder invalidatie zou het gecachte externe rapport (0165) tot 15 min lang de oude vertrouwde set
laten dragen: een mens-akkoord dat nergens doorwerkt. De lijst van bekende schrijvers is expliciet: een nieuwe schrijver
moet hier bewust worden toegevoegd (én de invalidatie dragen)."""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
MODEL = APP / "documenten" / "models.py"
BEKENDE_SCHRIJVERS = {
    "app/documenten/leverancier_iban.py",  # _voeg_toe: seed, baseline, bevestig_iban
    "app/documenten/iban_accordering.py",  # accordeer (vier ogen)
    "app/crediteuren/service.py",  # verhuis_ibans (crediteur-samenvoegen)
}
_CONSTRUCTIE = re.compile(r"\bLeverancierIban\(")
_INVALIDATIE = "maak_ongeldig_voor_vendor("


def _schrijvers() -> dict[str, str]:
    uit: dict[str, str] = {}
    for p in APP.rglob("*.py"):
        if p == MODEL:
            continue
        tekst = p.read_text(encoding="utf-8")
        if _CONSTRUCTIE.search(tekst):
            uit[p.relative_to(APP.parent).as_posix()] = tekst
    return uit


def test_bekende_schrijvers_zijn_precies_de_modules_die_een_rij_construeren() -> None:
    assert set(_schrijvers()) == BEKENDE_SCHRIJVERS, (
        "nieuw/verdwenen schrijfpad naar leverancier_iban — voeg 'm bewust toe aan BEKENDE_SCHRIJVERS én laat 'm "
        "checks_extern.maak_ongeldig_voor_vendor aanroepen"
    )


def test_elke_schrijver_maakt_de_checks_cache_ongeldig() -> None:
    zonder = sorted(pad for pad, tekst in _schrijvers().items() if _INVALIDATIE not in tekst)
    assert zonder == [], f"schrijfpad naar leverancier_iban zonder cache-invalidatie: {zonder}"


def test_vingerafdruk_draagt_de_vertrouwde_set() -> None:
    """Tweede slot: de set-hash staat in `checks_extern.vingerafdruk` en `voer_checks_uit` geeft 'm mee."""
    ce = (APP / "documenten" / "checks_extern.py").read_text(encoding="utf-8")
    assert "vertrouwde_ibans: Iterable[str] = ()" in ce
    bv = (APP / "documenten" / "boekvoorstel.py").read_text(encoding="utf-8")
    assert "vingerafdruk(**vf_basis, vertrouwde_ibans=vertrouwd_live)" in bv
    assert "vertrouwde_ibans=vertrouwd_live | set(ext.vertrouwde_ibans)" in bv
