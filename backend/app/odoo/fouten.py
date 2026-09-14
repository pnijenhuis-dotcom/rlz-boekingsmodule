"""Leesbare foutvertaling voor Odoo-weigeringen (controlescherm / boek_fout / herstel-CLI) — het
Odoo-equivalent van `vertaal_rlz_boekfout`. Alles wat we niet herkennen blijft de rauwe melding;
nooit informatie wegvertalen."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from app.odoo.client import OdooFout

_LOCK_RE = re.compile(r"lock|vergrendel|afgesloten|locked|closed", re.IGNORECASE)
_BALANS_RE = re.compile(r"niet in balans|not balanced|unbalanced", re.IGNORECASE)
_TAX_RE = re.compile(r"\btax|btw|belasting", re.IGNORECASE)
_COMPANY_RE = re.compile(r"company|bedrijf", re.IGNORECASE)

#: Leesbare labels van de vier Odoo-lock-date-velden op res.company (STAP-0 §3.5).
LOCK_LABELS: dict[str, str] = {
    "hard_lock_date": "harde lock date",
    "fiscalyear_lock_date": "boekjaar-lock date",
    "tax_lock_date": "btw-lock date",
    "purchase_lock_date": "inkoop-lock date",
}


def _nl(datum: date) -> str:
    return datum.strftime("%d-%m-%Y")


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


@dataclass(frozen=True)
class BoekdatumBesluit:
    """Uitkomst van `bepaal_boekdatum`: de boekdatum die WIJ aan Odoo meegeven (`date`), en — alleen bij een
    verschuiving — waarvandaan, door welke lock date en waarom (leesbaar, voor tijdlijn + "Geboekt in Odoo")."""

    boekdatum: date
    verschoven_van: date | None
    lock_veld: str | None
    lock_datum: date | None
    reden: str | None

    @property
    def verschoven(self) -> bool:
        return self.verschoven_van is not None


def bepaal_boekdatum(*, factuurdatum: date, lock_dates: dict[str, date | None]) -> BoekdatumBesluit:
    """Boekdatum-verschuiving (slotstuk 04-09, live bewijs A2 op company 1): valt de factuurdatum op of vóór een
    Odoo-lock date, dan weigert Odoo NIET maar verschuift het `date` STIL naar het maandeinde ná de lock. Wij
    bepalen de boekdatum daarom zelf, deterministisch (code voor cijfers): (hoogste geraakte lock date) + 1 dag =
    de eerste dag van de eerstvolgende open periode — de RLZ-semantiek "TaxSource naar de eerstvolgende open
    periode". `invoice_date` blijft de factuurdatum; de verschuiving is zichtbaar (tijdlijn-detail + regel), nooit
    stil. Geen lock geraakt → boekdatum = factuurdatum. De grens is inclusief: op de lock date zelf = verschoven
    (Odoo's regel is `date <= lock_date`)."""
    geraakt = [(veld, datum) for veld, datum in lock_dates.items() if datum is not None and factuurdatum <= datum]
    if not geraakt:
        return BoekdatumBesluit(
            boekdatum=factuurdatum, verschoven_van=None, lock_veld=None, lock_datum=None, reden=None
        )
    # Hoogste lock date wint; bij gelijke datums de eerste in de vaste veldvolgorde van `lock_dates`.
    lock_veld, lock_datum = max(geraakt, key=lambda paar: paar[1])
    boekdatum = lock_datum + timedelta(days=1)
    return BoekdatumBesluit(
        boekdatum=boekdatum,
        verschoven_van=factuurdatum,
        lock_veld=lock_veld,
        lock_datum=lock_datum,
        reden=(
            f"Factuurdatum {_nl(factuurdatum)} valt in een in Odoo afgesloten periode "
            f"({LOCK_LABELS.get(lock_veld, lock_veld)} t/m {_nl(lock_datum)}; btw-aangifte al gedaan) — boekdatum "
            f"verschoven naar {_nl(boekdatum)}, factuurdatum ongewijzigd"
        ),
    )


def lock_date_melding(*, boekdatum: date, lock_dates: dict[str, date | None]) -> str | None:
    """Poort voor de TEGENBOEKING (reversal, boekdatum vandaag): valt die boekdatum op/vóór een lock date, dan
    is dat een leesbare, blokkerende fout — een correctie in een afgesloten periode verschuiven wij niet stil.
    Het gewone boekpad verschuift sinds 04-09 via `bepaal_boekdatum`. `lock_dates` = {veld: datum|None} zoals
    gelezen van res.company (fiscalyear/tax/purchase/hard)."""
    treffers = [
        f"{LOCK_LABELS.get(veld, veld)} {datum.isoformat()}"
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


# --- verbindings-/HTTP-fouten van de wizard en de probe (punt 4 opdracht 14-09) -------------------------------------

_URL_HINT = "controleer of de URL alleen het domein is (bv. https://naam.odoo.com)"


def _pad_van(exc: httpx.HTTPError) -> str:
    verzoek = getattr(exc, "request", None)
    try:
        return verzoek.url.raw_path.decode() if verzoek is not None else ""
    except Exception:  # noqa: BLE001 — een leesbare melding mag nooit zelf omvallen
        return ""


def vertaal_verbindingsfout(exc: BaseException, *, timeout_s: float | None = None) -> str:
    """Eén leesbare zin voor een fout uit de Odoo-client bij verbinden/proben: HTTP-status + pad + wat te doen —
    NOOIT de exception-naam (kliktest Peter 14-09: "Odoo niet bereikbaar: HTTPStatusError" op een URL mét
    `/odoo`-webclientpad). Onbekende fouten blijven leesbaar generiek mét de fouttekst, zonder klassenaam."""
    if isinstance(exc, OdooFout):
        pad = f"/json/2/{exc.model}/{exc.methode}"
        if exc.status == 401:
            return f"401 op {pad} — Odoo weigert deze API-key, controleer de sleutel"
        if exc.status == 403:
            return f"403 op {pad} — de API-gebruiker mist rechten op dit model in Odoo"
        if exc.status == 404:
            return f"404 op {pad} — {_URL_HINT}"
        if exc.status >= 500:
            return f"{exc.status} op {pad} — Odoo geeft een serverfout, probeer het later opnieuw"
        return f"{exc.status} op {pad} — {(exc.melding or exc.naam or 'onbekende fout')[:200]}"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        pad = _pad_van(exc) or "/"
        if status == 404:
            return f"404 op {pad} — {_URL_HINT}"
        if status in (401, 403):
            return f"{status} op {pad} — Odoo weigert de toegang, controleer de API-key"
        if status >= 500:
            return f"{status} op {pad} — Odoo geeft een serverfout, probeer het later opnieuw"
        if 300 <= status < 400:
            return f"{status} op {pad} — Odoo stuurt door; {_URL_HINT}"
        return f"{status} op {pad} — onverwacht antwoord van Odoo"
    if isinstance(exc, httpx.TimeoutException):
        na = f" na {timeout_s:.0f} s" if timeout_s else ""
        return f"time-out{na} — Odoo antwoordde niet op tijd, probeer het opnieuw"
    if isinstance(exc, httpx.ConnectError):
        return f"geen verbinding met de host — controleer het domein en of de omgeving online is ({str(exc)[:120]})"
    if isinstance(exc, httpx.TransportError):
        return f"netwerkfout richting Odoo ({str(exc)[:120]}) — probeer het opnieuw"
    if isinstance(exc, ValueError):
        return str(exc)[:300]
    return f"onverwachte fout bij het verbinden met Odoo: {str(exc)[:200] or 'geen details'}"
