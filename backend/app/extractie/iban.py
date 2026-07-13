from __future__ import annotations

import re

# Deterministische IBAN-validatie (ISO 13616 mod-97) voor de IBAN-wissel-fraudecontrole
# (CLAUDE.md harde checks). Kernprincipe "code voor cijfers": de AI leest het IBAN alleen voor
# (gestructureerd kopveld, net als het factuurnummer expliciet BUITEN het BSN-filter — zie
# app/extractie/service.py::_VRIJE_TEKST_KOP_KEYS); of het klopt en of het afwijkt van de
# vertrouwde set bepaalt uitsluitend deze code. Een ongeldig IBAN wordt gemarkeerd
# (controle.onparseerbaar) en nooit gebruikt — niet als baseline, niet in de vergelijking.

# Landcode + 2 controlecijfers + 1..30 alfanumeriek (BBAN). Lengte per land verifiëren voegt hier
# weinig toe: mod-97 vangt vrijwel elke lees-/tikfout, en een te kort/lang IBAN faalt de proef.
_IBAN_VORM = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$")


def normaliseer_iban(waarde: str | None) -> str | None:
    """Naar de compacte vorm (hoofdletters, zonder spaties/punten/streepjes) of None. Alleen
    normalisatie — geldigheid is aan is_geldig_iban()."""
    if not waarde:
        return None
    compact = re.sub(r"[ .\-]", "", waarde.strip()).upper()
    return compact or None


def is_geldig_iban(waarde: str | None) -> bool:
    """ISO 13616: verplaats de eerste vier tekens naar achteren, letters -> 10..35, en het
    geheel modulo 97 moet 1 zijn. Werkt op de genormaliseerde vorm."""
    iban = normaliseer_iban(waarde)
    if iban is None or not _IBAN_VORM.fullmatch(iban):
        return False
    herschikt = iban[4:] + iban[:4]
    cijfers = "".join(str(int(teken, 36)) for teken in herschikt)
    return int(cijfers) % 97 == 1


def masker_iban(iban: str) -> str:
    """Voor checkmeldingen/UI-teksten: land + bankdeel zichtbaar, rekeninggedeelte grotendeels
    gemaskeerd (privacy: het volledige IBAN hoort niet in meldingen die in logs of
    foutrapportages terecht kunnen komen — de controleur ziet het volledige nummer op de
    factuur-preview zelf)."""
    compact = normaliseer_iban(iban) or ""
    if len(compact) <= 11:
        return compact[:4] + "…"
    return f"{compact[:8]}…{compact[-3:]}"
