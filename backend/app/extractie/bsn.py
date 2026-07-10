from __future__ import annotations

import re

# AVG-hard-principe (CLAUDE.md / registers/conventies.md): BSN's nooit extraheren, indexeren of
# in AI-output. De prompt verbiedt het al; dit is de deterministische post-filter vóór
# persistentie. **Detectie is bewust context-vereist** (fix 2026-07-10, na Peters controle van een
# echte factuur): de elfproef alléén laat ~1 op 11 van álle 9-cijferige getallen door — een
# factuurnummer dat toevallig de elfproef doorstaat werd als "[BSN verwijderd]" gemaskeerd en
# vernielde daarmee juist de data die de controleur nodig heeft. Daarom maskeren we alleen een
# losstaande 8/9-cijferige reeks die (a) de elfproef doorstaat én (b) in een échte BSN-context
# staat (nabij "BSN"/"burgerservicenummer"/"sofinummer"), waarbij een dichterbij staand ánder
# label (factuurnummer, IBAN, klantnummer, …) de BSN-context overstemt. Gestructureerde velden
# (factuurnummer, bedragen, datums) komen hier überhaupt niet doorheen — de aanroeper
# (app/extractie/service.py) filtert uitsluitend vrije-tekstvelden.

MASKER = "[BSN verwijderd]"

# Losse groep van 8 of 9 cijfers, eventueel met spaties/punten/streepjes ertussen, begrensd door
# niet-cijfers en niet-letters — géén substring van een langere cijferreeks (IBAN, EAN) en geen
# staart van een alfanumeriek kenmerk (bv. "F202600645").
_KANDIDAAT = re.compile(r"(?<![0-9A-Za-z])(?:\d[ .\-]?){7,8}\d(?![0-9A-Za-z])")

# Positieve context: het getal wordt expliciet als persoonsnummer aangekondigd.
_BSN_CONTEXT = re.compile(
    r"\b(bsn|burger\s?-?\s?servicenummer|burgerservice\s?-?\s?nummer|sofi\s?-?\s?nummer)\b",
    re.IGNORECASE,
)

# Negatieve context: labels van gestructureerde nummers die per definitie geen BSN zijn. Staat
# zo'n label dichter bij het getal dan het BSN-woord, dan hoort het getal bij dát label.
_GEEN_BSN_CONTEXT = re.compile(
    r"\b(iban|factuur(nummer|nr)?|invoice|order(nummer|nr)?|klant(nummer|nr)?|debiteur(nummer|nr)?|"
    r"crediteur(nummer|nr)?|referentie|kenmerk|kvk|btw|vat|artikel(nummer|nr)?|offerte(nummer|nr)?|"
    r"rekening(nummer|nr)?|contract(nummer|nr)?)\b",
    re.IGNORECASE,
)

# Hoe ver (in tekens) een BSN-woord vóór of ná het getal mag staan om nog als context te tellen.
_CONTEXT_VENSTER = 40


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


def _in_bsn_context(tekst: str, start: int, eind: int) -> bool:
    """Waar als het getal op [start:eind) daadwerkelijk als BSN wordt aangekondigd: een BSN-woord
    binnen het venster ervóór (waarbij een later, dus dichterbij, niet-BSN-label wint) of direct
    erachter (bv. "123456782 (BSN)")."""
    voor = tekst[max(0, start - _CONTEXT_VENSTER) : start]
    laatste_bsn = None
    for match in _BSN_CONTEXT.finditer(voor):
        laatste_bsn = match
    if laatste_bsn is not None:
        laatste_ander = None
        for match in _GEEN_BSN_CONTEXT.finditer(voor):
            laatste_ander = match
        if laatste_ander is None or laatste_ander.start() < laatste_bsn.start():
            return True
    na = tekst[eind : eind + _CONTEXT_VENSTER]
    eerste_bsn_na = _BSN_CONTEXT.search(na)
    if eerste_bsn_na is not None:
        eerste_ander_na = _GEEN_BSN_CONTEXT.search(na)
        return eerste_ander_na is None or eerste_bsn_na.start() < eerste_ander_na.start()
    return False


def verwijder_bsns(tekst: str) -> tuple[str, int]:
    """Vervangt elke kandidaat die de elfproef doorstaat ÉN in echte BSN-context staat door
    MASKER. Retourneert (schone tekst, aantal verwijderd) — het aantal mag gelogd/gepersisteerd
    worden, de nummers zelf nooit."""
    aantal = 0

    def _vervang(match: re.Match[str]) -> str:
        nonlocal aantal
        cijfers = re.sub(r"\D", "", match.group(0))
        if is_bsn(cijfers) and _in_bsn_context(tekst, match.start(), match.end()):
            aantal += 1
            return MASKER
        return match.group(0)

    return _KANDIDAAT.sub(_vervang, tekst), aantal
