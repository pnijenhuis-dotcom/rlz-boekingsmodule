"""Leesbare foutvertaling voor RLZ-boekweigeringen (was `boeken.vertaal_rlz_boekfout`; verhuisd bij de
port-introductie 03-09 zodat de RLZ-adapter 'm kan gebruiken zonder kringimport — boeken.py
re-exporteert de naam)."""

from __future__ import annotations

import re

from app.rlz.client import RlzApiError

# Casus Labo Derva 31-08 (api-verkenning "EU-tarieven op PurchaseInvoice-Actions"): RLZ weigert de
# boekactie (17) met deze 400-tekst wanneer de CREDITEURKAART in RLZ geen land/btw-nummer draagt bij een
# EU-/buitenland-tarief — crediteur-datakwaliteit, geen tarief-fout.
_ONGELDIG_TARIEF_RE = re.compile(r"ongeldig belastingtarief\s*'([^']*)'(?:\s*op regel\s*(\d+))?", re.IGNORECASE)


def vertaal_rlz_boekfout(exc: RlzApiError) -> str:
    """Leesbare melding mét handelingsperspectief voor bekende RLZ-boekweigeringen; alles wat we niet
    herkennen blijft de rauwe `str(exc)` — nooit informatie wegvertalen. Eén vertaalpunt voor
    controlescherm, accordering-`boek_fout` én de accordering-herstel-CLI."""
    match = _ONGELDIG_TARIEF_RE.search(exc.body or "")
    if exc.status_code == 400 and match:
        tarief = f" ('{match.group(1)}')" if match.group(1) else ""
        regel = f"regel {match.group(2)}" if match.group(2) else "een regel"
        return (
            f"RLZ weigert het btw-tarief{tarief} op {regel} — controleer land en btw-nummer van de "
            f"crediteur in RLZ en probeer opnieuw (een crediteurkaart zonder land/btw-nummer geeft "
            f"precies deze weigering bij EU-/buitenland-tarieven). RLZ-fout: {exc.body[:300]}"
        )
    return str(exc)
