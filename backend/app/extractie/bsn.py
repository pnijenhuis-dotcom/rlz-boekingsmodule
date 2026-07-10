from __future__ import annotations

import re

# AVG-hard-principe (CLAUDE.md / registers/conventies.md): BSN's nooit extraheren, indexeren of
# in AI-output. De prompt verbiedt het al; dit is de deterministische post-filter die elke
# 8/9-cijferige reeks die de elfproef doorstaat alsnog verwijdert vóórdat iets gepersisteerd
# wordt. Bewust conservatief: een enkel vals positief (bv. een oud bankrekeningnummer dat
# toevallig de elfproef doorstaat) is acceptabel, een gelekt BSN niet.

MASKER = "[BSN verwijderd]"

# Losse groep van 8 of 9 cijfers, eventueel met spaties/punten/streepjes ertussen, begrensd door
# niet-cijfers — géén substring van een langere cijferreeks (anders wordt elk IBAN/factuurnummer
# stukgeknipt op zoek naar toevallige matches).
_KANDIDAAT = re.compile(r"(?<![\d])(?:\d[ .\-]?){7,8}\d(?![\d])")


def is_bsn(cijfers: str) -> bool:
    """Elfproef voor BSN: (9·c1 + 8·c2 + … + 2·c8 − 1·c9) deelbaar door 11. Een 8-cijferig
    nummer telt mee met een voorloopnul (officieel toegestaan formaat)."""
    if not cijfers.isdigit() or len(cijfers) not in (8, 9):
        return False
    cijfers = cijfers.zfill(9)
    if cijfers == "000000000":
        return False
    som = sum(int(c) * gewicht for c, gewicht in zip(cijfers, range(9, 1, -1), strict=False))
    som -= int(cijfers[-1])
    return som % 11 == 0


def verwijder_bsns(tekst: str) -> tuple[str, int]:
    """Vervangt elke kandidaat die de elfproef doorstaat door MASKER. Retourneert (schone tekst,
    aantal verwijderd) — het aantal mag gelogd/gepersisteerd worden, de nummers zelf nooit."""
    aantal = 0

    def _vervang(match: re.Match[str]) -> str:
        nonlocal aantal
        cijfers = re.sub(r"\D", "", match.group(0))
        if is_bsn(cijfers):
            aantal += 1
            return MASKER
        return match.group(0)

    return _KANDIDAAT.sub(_vervang, tekst), aantal
