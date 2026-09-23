"""Afschrijvingsrekening deterministisch voorvullen uit de gekozen activarekening (BUG-opdracht 24-09, casus BLOw 23-09:
twee keer "Aanmaken ná boeken" zonder afschrijvingsrekening → `mislukt`, niemand zag het; vraag Peter "kunnen wij de
afschrijvingsregel ook niet automatiseren obv de gekozen activa-regel?" — ja, deterministisch, nooit AI).

Conventie (RGS-gebruik, BLOw: 0101→0102, 0103→0104, …, 0115→0116, 0001→0002): de rekening van dezelfde administratie mét
(a) code = balansrekening-code + 1 in dezelfde 0xxx-reeks (zelfde lengte, blijft met '0' beginnen) ÉN (b) een naam die
begint met "Afschrijving"; alleen niet-verdwenen, niet-totaalrekeningen, soort 3 (activa). Precies één treffer = de
voorvulling (herkomst `conventie`); nul of meer dan één = leeg — dan is de rekening op de kaart verplicht (422).

Puur code, geen DB-call: de aanroeper geeft de rekeningen van de administratie mee (voorstel.bepaal heeft ze al).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.db.models import Grootboekrekening

SOORT_ACTIVA = 3
NAAM_PREFIX = "afschrijving"
BRON_CONVENTIE = "conventie"
BRON_INSTELLING = "instelling"
BRON_KOPPELING = "koppeling"


def volgende_code(code: str) -> str | None:
    """`0107` → `0108`, `0001` → `0002`, `01100` → `01101`. None als de code niet numeriek is, niet met '0' begint, of
    de opvolger de 0xxx-reeks/lengte verlaat (`0999` → None)."""
    code = (code or "").strip()
    if not code.isdigit() or not code.startswith("0") or len(code) < 2:
        return None
    volgende = str(int(code) + 1).zfill(len(code))
    if len(volgende) != len(code) or not volgende.startswith("0"):
        return None
    return volgende


def is_afschrijvingsrekening_naam(naam: str | None) -> bool:
    return (naam or "").strip().lower().startswith(NAAM_PREFIX)


def conventie_rekening(
    balans: Grootboekrekening, rekeningen: Iterable[Grootboekrekening]
) -> Grootboekrekening | None:
    """De unieke conventie-treffer voor `balans`, of None."""
    doel = volgende_code(balans.code)
    if doel is None:
        return None
    treffers = [
        r
        for r in rekeningen
        if r.ledger_id != balans.ledger_id
        and r.administratie_id == balans.administratie_id
        and r.verdwenen_uit_bron_op is None
        and not r.is_totaalrekening
        and int(r.soort) == SOORT_ACTIVA
        and (r.code or "").strip() == doel
        and is_afschrijvingsrekening_naam(r.naam)
    ]
    return treffers[0] if len(treffers) == 1 else None
