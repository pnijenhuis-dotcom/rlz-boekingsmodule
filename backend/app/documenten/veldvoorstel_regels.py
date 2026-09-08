"""Lezen van de gelezen factuurregels in een veldvoorstel — ÉÉN bron voor twee regels (blok 4 bundel 08-09,
casus Spot Services 2026-608, Universal Steigerbouw):

1. **Nulregels (tariefstaffels) zijn geen boekingsregels** — praktijkles CLAUDE.md "Creditnota's: negatieve regels
   accepteren, nulregels (tariefstaffels) wegfilteren". Een leverancier drukt zijn tariefkaart mee op de factuur
   (9 van 12 regels: aantal 0, bedrag 0, btw 0). Zo'n regel is als BRON waardevol (tariefkaart, self-billing,
   materiaal-/prijsafspraken lezen het veldvoorstel rechtstreeks) maar als boekingsregel ruis: grootboek/btw/project
   verplicht op een regel die niets boekt. Predicaat: aantal 0 of ontbrekend ÉN netto 0 ÉN btw 0 (of niet gelezen).
   Negatieve regels (korting, credit) blijven — die tellen in de som. Een regel met een aantal > 0 en bedrag 0
   (gratis levering) blijft óók: die zegt iets.
   De extractie (app/extractie/controle.py::bouw_veldvoorstel) MARKEERT elke regel (`tariefstaffel: bool`) en houdt
   de regel in `regels`; wie boekingsregels wil, leest `boekbare_regels(...)`. Oudere veldvoorstellen zonder vlag
   krijgen hetzelfde predicaat live (deterministisch, geen her-extractie).

2. **Kop-projectnummer als default** — blok 10 (07-09) vult regels zonder eigen `proj` met het kop-`proj`. Leest de
   AI het nummer niet in de kop maar op precies één regel (Spot Services: "26049" alleen op regel 1), dan is dat
   het projectnummer van de factuur: `kop_project_tekst` levert kop-`proj`, anders het ENIGE distinct regel-`proj`
   (over de boekbare regels). Twee verschillende regel-nummers = de factuur splitst werken → geen default (regels
   houden hun eigen tekst, de rest blijft leeg — nooit raden).

Pure functies op het veldvoorstel-dict (geen DB, geen AI); geïmporteerd door extractie/controle.py,
documenten/boekvoorstel.py en documenten/boeken.py.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

VLAG_TARIEFSTAFFEL = "tariefstaffel"


def _decimal(waarde: object) -> Decimal | None:
    """Canonieke punt-decimaal (zoals controle.py ze opslaat) of, als vangnet, NL-notatie; rommel = None."""
    if waarde is None:
        return None
    if isinstance(waarde, Decimal):
        return waarde
    if isinstance(waarde, (int, float)):
        return Decimal(str(waarde))
    tekst = str(waarde).strip().replace(" ", "").replace(" ", "")
    if not tekst:
        return None
    if "," in tekst:
        tekst = tekst.replace(".", "").replace(",", ".")
    try:
        return Decimal(tekst)
    except InvalidOperation:
        return None


def parse_hoeveelheid(ruw: object) -> Decimal | None:
    """Hoeveelheid zoals gelezen ("0", "0,00", "12 st", "3x") → getal; niets leesbaars = None (= ontbrekend)."""
    if ruw is None:
        return None
    tekst = str(ruw).strip()
    if not tekst:
        return None
    # Eenheid achter het getal ("12 st", "3x", "40 m2") — alleen het leidende getal telt.
    kop = ""
    for teken in tekst:
        if teken.isdigit() or teken in ",.-":
            kop += teken
        else:
            break
    return _decimal(kop) if kop else None


def is_nulregel(*, netto: Decimal | None, btw: Decimal | None, hoeveelheid: Decimal | None) -> bool:
    """Tariefstaffel-regel: aantal 0 (of ontbrekend) ÉN netto 0 ÉN btw 0 (of niet gelezen). Een regel zonder
    gelezen netto is GEEN nulregel (dan weet je niets — de regelsom-check meldt dat zelf)."""
    if netto is None or netto != 0:
        return False
    if btw is not None and btw != 0:
        return False
    return hoeveelheid is None or hoeveelheid == 0


def is_tariefstaffel_regel(regel: dict) -> bool:
    """Vlag uit de extractie als die er is; anders (ouder veldvoorstel) hetzelfde predicaat live."""
    vlag = regel.get(VLAG_TARIEFSTAFFEL)
    if isinstance(vlag, bool):
        return vlag
    return is_nulregel(
        netto=_decimal(regel.get("netto_bedrag")),
        btw=_decimal(regel.get("btw_bedrag")),
        hoeveelheid=parse_hoeveelheid(regel.get("hoeveelheid")),
    )


def gelezen_regels(veldvoorstel: dict | None) -> list[dict]:
    """Álle gelezen regels (dicts) — de bron, inclusief tariefstaffels."""
    if not veldvoorstel:
        return []
    regels = veldvoorstel.get("regels")
    if not isinstance(regels, list):
        return []
    return [r for r in regels if isinstance(r, dict)]


def boekbare_regels(veldvoorstel: dict | None) -> list[dict]:
    """De regels die een boekingsregel worden: alles behalve tariefstaffels. Zijn ÁLLE regels nulregels, dan
    blijven ze staan (een factuur van louter nullen — nooit stil een leeg voorstel maken; de mens ziet 'm)."""
    alle = gelezen_regels(veldvoorstel)
    boekbaar = [r for r in alle if not is_tariefstaffel_regel(r)]
    return boekbaar if boekbaar else alle


def _genormaliseerd(tekst: str) -> str:
    return " ".join(tekst.strip().lower().split())


def kop_project_tekst(veldvoorstel: dict | None) -> str | None:
    """Kop-`proj`, anders het ENIGE distinct regel-`proj` van de boekbare regels; None bij niets of meerdere."""
    if not veldvoorstel:
        return None
    kop = veldvoorstel.get("project_tekst")
    if isinstance(kop, str) and kop.strip():
        return kop
    teksten: dict[str, str] = {}
    for regel in boekbare_regels(veldvoorstel):
        tekst = regel.get("project_tekst")
        if isinstance(tekst, str) and tekst.strip():
            teksten.setdefault(_genormaliseerd(tekst), tekst)
    if len(teksten) == 1:
        return next(iter(teksten.values()))
    return None
