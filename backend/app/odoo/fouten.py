"""Leesbare foutvertaling voor Odoo-weigeringen (controlescherm / boek_fout / herstel-CLI) — het
Odoo-equivalent van `vertaal_rlz_boekfout`. Alles wat we niet herkennen blijft de rauwe melding;
nooit informatie wegvertalen."""

from __future__ import annotations

import re
from datetime import date

from app.odoo.client import OdooFout

_LOCK_RE = re.compile(r"lock|vergrendel|afgesloten|locked|closed", re.IGNORECASE)
_BALANS_RE = re.compile(r"niet in balans|not balanced|unbalanced", re.IGNORECASE)
_TAX_RE = re.compile(r"\btax|btw|belasting", re.IGNORECASE)
_COMPANY_RE = re.compile(r"company|bedrijf", re.IGNORECASE)


def vertaal_odoo_fout(exc: Exception) -> str:
    if not isinstance(exc, OdooFout):
        return str(exc)
    melding = exc.melding or ""
    naam = exc.naam or ""
    if exc.status in (401,):
        return "Odoo weigert de API-key (HTTP 401) — controleer/roteer de sleutel in Instellingen › Administraties. "
    if exc.status == 403 or naam.endswith("AccessError"):
        return (
            f"Odoo weigert de handeling (rechten, {exc.model}.{exc.methode}) — geef de API-gebruiker in Odoo "
            f"boekhoudrechten op deze company. Odoo-fout: {melding[:300]}"
        )
    if _LOCK_RE.search(melding):
        return (
            "Odoo weigert de boekdatum: de periode is vergrendeld (lock date). Kies een boekdatum ná de lock date "
            f"of laat de Beheerder de lock date in Odoo aanpassen. Odoo-fout: {melding[:300]}"
        )
    if _BALANS_RE.search(melding):
        return f"Odoo weigert de boeking: niet in balans — controleer de regels. Odoo-fout: {melding[:300]}"
    if _COMPANY_RE.search(melding) and naam.endswith(("UserError", "ValidationError")):
        return (
            "Odoo weigert de combinatie van company en stamgegevens (dagboek/rekening/btw-code van een andere "
            f"company?) — sync de stamgegevens opnieuw. Odoo-fout: {melding[:300]}"
        )
    if _TAX_RE.search(melding) and naam.endswith(("UserError", "ValidationError")):
        return f"Odoo weigert de btw-code op een regel — controleer het tarief. Odoo-fout: {melding[:300]}"
    if exc.status == 422:
        return f"Odoo weigert de boeking: {melding[:400]}"
    return str(exc)


def overgangsdatum_melding(*, factuurdatum: date, overgangsdatum: date | None) -> str | None:
    """Overstap-poort (blok E, migratie 0104): een bestaande RLZ-administratie boekt vanaf de overgangsdatum
    in Odoo — een factuur mét factuurdatum vóór die datum hoort nog in Reeleezee (periode vóór de overstap)
    en wordt leesbaar geweigerd, nooit stil in het verkeerde pakket geboekt. Geen overgangsdatum = geen
    poort (Odoo-administratie zonder RLZ-verleden)."""
    if overgangsdatum is None or factuurdatum >= overgangsdatum:
        return None
    return (
        f"Factuurdatum {factuurdatum.isoformat()} ligt vóór de overgangsdatum {overgangsdatum.isoformat()} van deze "
        "administratie — deze factuur hoort nog in Reeleezee (periode vóór de overstap). Boek 'm dáár, of laat de "
        "Beheerder de overgangsdatum aanpassen op Instellingen › Administraties."
    )


def lock_date_melding(*, boekdatum: date, lock_dates: dict[str, date | None]) -> str | None:
    """Vóór de create: valt de boekdatum op/vóór een lock date, dan is dat een leesbare, blokkerende
    fout (STAP-0 §3.5: Odoo zou de datum anders stil verschuiven of weigeren). `lock_dates` =
    {veld: datum|None} zoals gelezen van res.company (fiscalyear/tax/purchase/hard)."""
    labels = {
        "hard_lock_date": "harde lock date",
        "fiscalyear_lock_date": "boekjaar-lock date",
        "tax_lock_date": "btw-lock date",
        "purchase_lock_date": "inkoop-lock date",
    }
    treffers = [
        f"{labels.get(veld, veld)} {datum.isoformat()}"
        for veld, datum in lock_dates.items()
        if datum is not None and boekdatum <= datum
    ]
    if not treffers:
        return None
    return (
        f"Boekdatum {boekdatum.isoformat()} valt in een in Odoo vergrendelde periode ({', '.join(treffers)}) — "
        "boeken geweigerd. Kies een latere boekdatum (bv. de eerste dag ná de lock date, mét reden in de "
        "tijdlijn) of laat de Beheerder de lock date in Odoo aanpassen."
    )
