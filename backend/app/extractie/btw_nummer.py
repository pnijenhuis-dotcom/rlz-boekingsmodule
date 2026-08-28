"""Deterministische validatie van btw- en KvK-nummers uit de factuur (opruimrun 28-08, punt 14).

Code voor cijfers: de AI leest het nummer alleen vóór, déze module normaliseert en toetst.
- Nederlands btw-nummer: `NL` + 9 cijfers + `B` + 2 cijfers. Elfproef "waar mogelijk": het klassieke
  fiscaal nummer (RSIN/BSN-vorm) voldoet aan de 11-proef (9·d1 + 8·d2 + … + 2·d8 − d9 ≡ 0 mod 11);
  het btw-identificatienummer voor natuurlijke personen (sinds 2020) níét, maar wél aan de mod-97-toets
  over de tekens (N=23, L=21, B=11) — één van beide groen = `geverifieerd`. Vorm goed maar geen enkele
  proef = wél overnemen (het staat zo op de factuur), maar `geverifieerd=False` (oranje chip).
- Buitenlandse nummers: alleen de vorm (landcode + 2–12 alfanumeriek) — nooit geverifieerd genoemd.
- KvK-nummer: precies 8 cijfers (zelfde regel als app/integraties/kvk.geldig_kvk_nummer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NL_BTW = re.compile(r"^NL(\d{9})B(\d{2})$")
_EU_BTW = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,12}$")
_KVK = re.compile(r"^\d{8}$")
_LETTERWAARDE = {chr(c): 10 + c - ord("A") for c in range(ord("A"), ord("Z") + 1)}  # A=10 … Z=35


@dataclass(frozen=True)
class BtwNummer:
    genormaliseerd: str
    nederlands: bool
    geverifieerd: bool


def normaliseer_btw_nummer(ruw: str | None) -> str | None:
    """Hoofdletters, zonder spaties/punten/streepjes; 'BTW-nr.'-prefixen weg. None = leeg/onbruikbaar."""
    if not ruw:
        return None
    tekst = re.sub(r"[\s.\-–]", "", ruw.upper())
    # Langste prefix eerst (alternatie kiest het eerste passende alternatief).
    tekst = re.sub(r"^(BTWNUMMER|BTWNR|BTWID|BTW|VATNUMBER|VATNO|VATID|VAT)[:#]?", "", tekst)
    return tekst or None


def elfproef_ok(negen_cijfers: str) -> bool:
    """Klassieke 11-proef (BSN/RSIN/fiscaal nummer): 9·d1 + … + 2·d8 − 1·d9 ≡ 0 (mod 11)."""
    if len(negen_cijfers) != 9 or not negen_cijfers.isdigit():
        return False
    som = sum(int(c) * gewicht for c, gewicht in zip(negen_cijfers[:8], range(9, 1, -1), strict=True))
    som -= int(negen_cijfers[8])
    return som % 11 == 0


def mod97_ok(nl_btw: str) -> bool:
    """Btw-id natuurlijke personen (2020+): letters → cijfers (N=23, L=21, B=11), getal mod 97 == 1."""
    cijfers = "".join(str(_LETTERWAARDE[c]) if c.isalpha() else c for c in nl_btw)
    return int(cijfers) % 97 == 1


def valideer_btw_nummer(ruw: str | None) -> BtwNummer | None:
    """None = geen bruikbaar btw-nummer (leeg of vorm herkenbaar fout — dan liever niets dan een gok)."""
    genormaliseerd = normaliseer_btw_nummer(ruw)
    if genormaliseerd is None:
        return None
    m = _NL_BTW.match(genormaliseerd)
    if m:
        geverifieerd = elfproef_ok(m.group(1)) or mod97_ok(genormaliseerd)
        return BtwNummer(genormaliseerd=genormaliseerd, nederlands=True, geverifieerd=geverifieerd)
    if _EU_BTW.match(genormaliseerd) and not genormaliseerd.startswith("NL"):
        return BtwNummer(genormaliseerd=genormaliseerd, nederlands=False, geverifieerd=False)
    return None


def normaliseer_kvk_nummer(ruw: str | None) -> str | None:
    """Precies 8 cijfers (na strippen van spaties/punten en een 'KvK'-prefix); anders None."""
    if not ruw:
        return None
    tekst = re.sub(r"[\s.\-]", "", ruw.upper())
    tekst = re.sub(r"^(KVK|KVKNR|KVKNUMMER|HR|COC)[:#]?", "", tekst)
    return tekst if _KVK.match(tekst) else None
