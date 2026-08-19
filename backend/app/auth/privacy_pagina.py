"""Publieke privacyverklaring-/voorwaardenpagina van de accordeur-app (store-gereedheid A1).

De App Store-/Play-listing (en t.z.t. de [link]-verwijzing in de akkoordtekst zelf) vereist
een publiek bereikbare privacyverklaring-URL. Eén bron van waarheid: deze route rendert
`app.auth.voorwaarden.AKKOORD_TEKST` + versie als statische HTML-pagina — de publieke tekst
kan dus nooit uit de pas lopen met wat de accordeur in de activeringsflow accepteert. De
placeholders die de PWA met de administratienamen vult, worden hier neutraal ingevuld
(publieke pagina, geen klantcontext). Geen auth (patroon app/auth/wellknown.py), geen
secret- of klantmateriaal.

NB dev-gedrag: de Vite-dev-server proxiet alleen fetch/XHR — een browser-navigatie naar
/accordeur/privacy toont in dev de SPA. In productie wint deze route van de SPA-catchall
(app/static_frontend.py registreert als allerlaatste)."""

from __future__ import annotations

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.auth.voorwaarden import AKKOORD_TEKST, AKKOORD_TEKST_VERSIE

router = APIRouter(tags=["privacy"])

# Neutrale invulling van de PWA-placeholders voor de publieke weergave.
_PLACEHOLDERS = {
    "[klantnaam]": "uw organisatie",
    "[Klantnaam]": "Uw organisatie",
    "[administratie]": "uw administratie",
}

_STIJL = """\
:root { color-scheme: light dark; }
body { margin: 0; padding: 2rem 1.25rem 3rem; display: flex; justify-content: center;
       font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #f5f6f5; color: #1d2321; }
main { max-width: 42rem; }
h1 { font-size: 1.45rem; line-height: 1.3; margin: 0 0 .25rem; }
p.sub { margin: 0 0 1.5rem; opacity: .7; font-size: .9rem; }
footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid rgba(125,125,125,.35);
         font-size: .85rem; opacity: .75; }
@media (prefers-color-scheme: dark) {
  body { background: #0e1514; color: #e6ebe9; }
}"""


def _als_html_alineas(tekst: str) -> str:
    for placeholder, invulling in _PLACEHOLDERS.items():
        tekst = tekst.replace(placeholder, invulling)
    return "\n".join(f"<p>{html.escape(alinea)}</p>" for alinea in tekst.split("\n\n"))


@router.get("/accordeur/privacy", include_in_schema=False)
def accordeur_privacy() -> HTMLResponse:
    pagina = f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacyverklaring en gebruiksvoorwaarden — Nijenhuis Boekingsmodule</title>
<style>{_STIJL}</style>
</head>
<body>
<main>
<h1>Privacyverklaring en gebruiksvoorwaarden — Nijenhuis Boekingsmodule</h1>
<p class="sub">Goedkeuringsapp van Administratiekantoor Nijenhuis · tekstversie {html.escape(AKKOORD_TEKST_VERSIE)}</p>
{_als_html_alineas(AKKOORD_TEKST)}
<footer>
Dit is dezelfde tekst die elke gebruiker bij activering van de app leest en accepteert
(vastgelegd met naam, datum, tijdstip en tekstversie). Vragen over uw gegevens of uw
rechten (inzage, correctie, bezwaar)? Neem contact op met Administratiekantoor Nijenhuis
via uw vaste contactpersoon.
</footer>
</main>
</body>
</html>"""
    return HTMLResponse(content=pagina, headers={"Cache-Control": "no-cache"})
