"""Afschrijvingsrekening deterministisch voorvullen uit de gekozen activarekening (besluit Peter 24-09 07:5x, bundelrun
blok 6: "eens moet kostenrekening van zelfde omschrijving zijn (kantoorinventaris, ICT etc)" — HERZIET de conventie
"code + 1 op 0xxx" van de BUG-run 23-09 avond).

Aanleiding: STAP-0 deel 1 (23-09 avond, Pilates Bloom) bewees dat het échte RLZ-activum een KOSTENrekening (4706
Afschrijvingskosten, AccountType 2) als `DepreciationAccount` draagt — géén 0xxx-balansrekening. De balanskant blijft
`BalanceAccount` (de activarekening zelf); de cumulatieve-afschrijvingsrekening kiest RLZ zelf.

Conventie: de 4xxx-KOSTENrekening (soort 2, niet-verdwenen, niet-totaal, zelfde administratie) waarvan de
genormaliseerde omschrijving — ná het strippen van het voorvoegsel "Afschrijving", "Afschrijvingen" of
"Afschrijvingskosten" (+ optioneel "op"/"van", dubbele punt, streepje) — gelijk is aan de genormaliseerde omschrijving
van de activarekening. 0107 Kantoorinventaris → 4xxx "Afschrijving kantoorinventaris"; 0110 ICT → "Afschrijvingskosten
ICT". Ook de omgekeerde vorm ("Kantoorinventaris afschrijving") telt. Precies één treffer = voorvulling (herkomst
`conventie`); nul of meer dan één = leeg — dan is de rekening op de kaart verplicht (422). Nooit AI, nooit raden.

Puur code, geen DB-call: de aanroeper geeft de rekeningen van de administratie mee (voorstel.bepaal heeft ze al).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.db.models import Grootboekrekening

SOORT_KOSTEN = 2
BRON_CONVENTIE = "conventie"
BRON_INSTELLING = "instelling"
BRON_KOPPELING = "koppeling"

_PREFIX_RE = re.compile(r"^(?:afschrijvingskosten|afschrijvingen|afschrijving)\b(?:\s+(?:op|van))?\s*")
_SUFFIX_RE = re.compile(r"\s*(?:afschrijvingskosten|afschrijvingen|afschrijving)$")


def normaliseer(naam: str | None) -> str:
    """lowercase, diakrieten weg, niet-alfanumeriek → spatie, witruimte samengevouwen."""
    tekst = unicodedata.normalize("NFKD", naam or "")
    tekst = "".join(c for c in tekst if not unicodedata.combining(c)).lower()
    tekst = re.sub(r"[^a-z0-9]+", " ", tekst)
    return " ".join(tekst.split())


def is_afschrijvingsrekening_naam(naam: str | None) -> bool:
    n = normaliseer(naam)
    return bool(_PREFIX_RE.match(n) or _SUFFIX_RE.search(n))


def kern_van_afschrijvingsnaam(naam: str | None) -> str | None:
    """"Afschrijving kantoorinventaris" / "Afschrijvingskosten op ICT" / "Kantoorinventaris afschrijving" →
    "kantoorinventaris" / "ict"; None als de naam geen afschrijvingsrekening is of er niets overblijft."""
    n = normaliseer(naam)
    if _PREFIX_RE.match(n):
        kern = _PREFIX_RE.sub("", n, count=1)
    elif _SUFFIX_RE.search(n):
        kern = _SUFFIX_RE.sub("", n, count=1)
    else:
        return None
    kern = kern.strip()
    return kern or None


def conventie_rekening(
    balans: Grootboekrekening, rekeningen: Iterable[Grootboekrekening]
) -> Grootboekrekening | None:
    """De unieke kostenrekening "Afschrijving(en/skosten) ‹omschrijving activarekening›" voor `balans`, of None."""
    doel = normaliseer(balans.naam)
    if not doel:
        return None
    treffers = [
        r
        for r in rekeningen
        if r.ledger_id != balans.ledger_id
        and r.administratie_id == balans.administratie_id
        and r.verdwenen_uit_bron_op is None
        and not r.is_totaalrekening
        and int(r.soort) == SOORT_KOSTEN
        and (r.code or "").strip().startswith("4")
        and kern_van_afschrijvingsnaam(r.naam) == doel
    ]
    return treffers[0] if len(treffers) == 1 else None
