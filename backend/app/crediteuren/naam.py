"""Crediteurnaam-normalisatie — één bron (blok 2 feedbackrun A 25-09, FV-21 "crediteurnamen in meerdere
schrijfwijzen": `Floor Bouwliftenservice` / `Floor bouwliftenservice`, `Universal Nederland B.V.` /
`Universal nederland B.V.`).

Puur en deterministisch, bewust zonder imports uit andere domeinmodules (wordt gelezen door de dubbelen-motor in
`app/documenten/crediteur_kenmerk.py`, de crediteur-match in `app/extractie/controle.py` en de lees-only CLI
`crediteuren-naamclusters`). Regels:

- casefold (hoofdletterongevoelig) én diakrieten weg ("Café" ≡ "Cafe");
- rechtsvorm-afkortingen weg: b.v. / bv / b v, n.v. / nv, v.o.f. / vof, c.v. / cv — alleen als los token;
- "holding" blijft ONDERSCHEIDEND (regel intake 27/28-08: "BLOW Holding" ≠ "BLOW B.V.") — dat woord wordt nooit
  gestript;
- leestekens én spaties weg: de sleutel is één aaneengesloten string van letters/cijfers ("floorbouwliftenservice").

Een gelijkende-maar-andere naam ("Universal Nederland" vs "Universal Verkoop", "Bouwadvies Oost" vs "Bouwadvies West")
levert dus een ándere sleutel — clusteren gebeurt uitsluitend op een IDENTIEKE sleutel, nooit fuzzy.
"""

from __future__ import annotations

import re
import unicodedata

#: Rechtsvorm-tokens: alleen als los woord (\b), met of zonder punten/spaties ("B.V.", "BV", "B V", "b.v").
_RECHTSVORM = re.compile(r"\b(b\.?\s?v\.?|n\.?\s?v\.?|v\.?\s?o\.?\s?f\.?|c\.?\s?v\.?)(?=\s|$|[^a-z0-9])", re.IGNORECASE)
_NIET_ALFANUMERIEK = re.compile(r"[^a-z0-9]+")


def _zonder_diakrieten(tekst: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(c))


def normaliseer_crediteurnaam(naam: str | None) -> str:
    """Genormaliseerde vergelijkingssleutel voor een crediteurnaam; "" voor een lege/onbruikbare naam."""
    if not naam:
        return ""
    laag = _zonder_diakrieten(str(naam)).casefold()
    zonder_rechtsvorm = _RECHTSVORM.sub(" ", laag)
    return _NIET_ALFANUMERIEK.sub("", zonder_rechtsvorm)


def zelfde_crediteurnaam(a: str | None, b: str | None) -> bool:
    """True als beide namen dezelfde (niet-lege) genormaliseerde sleutel dragen."""
    sa, sb = normaliseer_crediteurnaam(a), normaliseer_crediteurnaam(b)
    return bool(sa) and sa == sb
