from __future__ import annotations

import re

# Deterministische regel-sleutel voor het boekingsgeheugen: dezelfde soort factuurregel moet bij
# elke leverancier telkens op dezelfde sleutel landen, ook als de tekst net anders is opgemaakt
# ("Diesel NEN590 - week 27" vs "diesel NEN590 week 28"? Nee: tokens verschillen dan wél — de
# sleutel normaliseert opmaak, geen betekenis). Volgorde-onafhankelijk (token-set) zodat
# "huur heater 170KW" en "170KW heater huur" dezelfde sleutel geven. De rauwe omschrijving reist
# apart mee (regel_omschrijving_raw) en hoort nooit in logs/URL's.

_GEEN_LETTER_OF_CIJFER = re.compile(r"[^0-9a-zà-ÿ]+")


def normaliseer_regel_sleutel(omschrijving: str | None) -> str | None:
    """Lowercase -> leestekens strippen -> whitespace inklappen -> unieke tokens, gesorteerd
    (volgorde-onafhankelijk) -> met één spatie samengevoegd. Leeg resultaat = None (geen sleutel,
    observatie telt dan alleen op leverancier-niveau mee)."""
    if not omschrijving:
        return None
    tokens = _GEEN_LETTER_OF_CIJFER.split(omschrijving.lower())
    unieke_tokens = sorted({token for token in tokens if token})
    if not unieke_tokens:
        return None
    return " ".join(unieke_tokens)
