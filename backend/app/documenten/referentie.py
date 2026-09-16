"""Referentie-normalisatie — DÉ ene vergelijkingsvorm van een factuurreferentie (besluit Peter 07-09 "nooit twee
normalisaties naast elkaar", aangescherpt 16-09 ná de Zenvoices-casus Hello Kitchen / Kempen Facilities).

Casus 16-09: Zenvoices boekte referentie `24594001722`, de module `2 4594 001722` (spaties uit de factuur-opmaak
overgenomen). De RLZ-bestaanscheck vergeleek ongenormaliseerd (`Reference eq '…'`) en zag geen treffer; de eigen
module-normalisatie zou 'm óók gemist hebben omdat ze voorloopnullen per cijfergroep stripte ("001722" → "1722").
Gevolg: twee facturen dubbel geboekt én dubbel betaald.

Regels (deterministisch, geen AI):
1. hoofdletterongevoelig;
2. gangbare voorvoegsels vooraan weg — factuur / factuurnr / factuurnummer / inv / invoice / nr / no / "#", ook
   gecombineerd ("Factuur nr. 42");
3. WITRUIMTE TUSSEN TWEE CIJFERGROEPEN is cijfergroepering en verdwijnt zonder meer: "2 4594 001722" ≡ "24594001722",
   "222 0300 505" ≡ "2220300505" — voorloopnullen ná zo'n spatie blijven cijfers; witruimte ná een WOORD scheidt wél
   een nummerdeel ("document 03" ≡ "document 3"; een IBAN met spaties blijft daardoor bewust ≠ de spatieloze vorm —
   IBAN-referenties sluit `referentie_classificatie` sowieso uit);
4. ANDERE scheidingstekens (-, /, ., :) scheiden nummerdelen: per deel verdwijnen voorloopnullen ("2026-0042" ≡
   "2026-42" ≡ "2026/0042" → "202642"); een aaneengesloten "20260042" blijft "20260042";
5. alles wat geen letter of cijfer is verdwijnt; leeg ná normalisatie (bv. alleen "#") = None = niet toetsbaar.

Gebruikers: harde check "Duplicaat (module)", auto-/bulk-afvoer, backfill, de RLZ-/Odoo-bestaanscheck
(`extern_bestaan.py`), `rlz_dubbel`, de bank-matchmotor (klantreferentie) en de intercompany-factuurmatch. Bewust NIET
afgekapt op 30 tekens (RLZ's Reference-lengte is alleen relevant voor de RLZ-leesroute). Kolom
`boekvoorstel.referentie_norm` (migratie 0147) bewaart deze vorm naast de letterlijke referentie."""

from __future__ import annotations

import re

_REFERENTIE_VOORVOEGSELS = (
    "factuurnummer",
    "factuurnr",
    "factuur",
    "invoice",
    "inv",
    "nr",
    "no",
)
_VOORVOEGSEL_PATROON = re.compile(
    r"^(?:(?:" + "|".join(_REFERENTIE_VOORVOEGSELS) + r")\b\s*[.:#\-]?\s*|#\s*)+",
    re.IGNORECASE,
)
_WITRUIMTE = re.compile(r"\s+")
_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")


def normaliseer_referentie(referentie: str | None) -> str | None:
    """Zie module-docstring. Voorbeelden: "2 4594 001722" → "24594001722"; "Factuur 2026-0042" → "202642";
    "INV #0042" → "42"; "Factuur" → None."""
    if not referentie:
        return None
    tekst = referentie.strip().lower()
    tekst = _VOORVOEGSEL_PATROON.sub("", tekst)
    if not tekst:
        return None
    # Stap 3: witruimte tussen twee cijfergroepen = groepering → aaneenplakken (voorloopnullen intact); andere
    # witruimte scheidt nummerdelen.
    groepen: list[str] = []
    for woord in _WITRUIMTE.split(tekst):
        if not woord:
            continue
        if groepen and woord.isdigit() and groepen[-1].isdigit():
            groepen[-1] += woord
        else:
            groepen.append(woord)
    # Stap 4/5: overige scheidingstekens delen het nummer op; per deel voorloopnullen weg.
    delen: list[str] = []
    for groep in groepen:
        for token in _NIET_ALFANUMERIEK.split(groep):
            if not token:
                continue
            if token.isdigit():
                token = token.lstrip("0") or "0"
            delen.append(token)
    schoon = "".join(delen)
    return schoon or None


def zelfde_referentie(a: str | None, b: str | None) -> bool:
    """Twee referenties zijn gelijk als hun genormaliseerde vorm bestaat en gelijk is."""
    na, nb = normaliseer_referentie(a), normaliseer_referentie(b)
    return na is not None and na == nb
