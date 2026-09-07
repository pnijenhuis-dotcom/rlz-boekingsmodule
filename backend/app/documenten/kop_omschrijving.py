"""Kop-omschrijving van een inkoopfactuur — automatisch, deterministisch in code (blok 9 vervolgrun 07-09,
besluit Peter 07-09 "auto-first").

De omschrijving op documentniveau (RLZ `Description` op de PurchaseInvoice, Odoo `narration`) werd tot 07-09 door
niemand gezet. Sinds blok 9 leidt de module 'm af uit wat er al is — geen AI in deze afleiding, de AI levert
hooguit het VOORGELEZEN veld `betreft` (sentinel-string in het extractieschema, `""` = onbekend → None):

1. precies één échte boekingsregel mét tekst → die regeltekst (herkomst `regel`);
2. anders de betreft-/onderwerpregel van de factuur (`betreft` uit het veldvoorstel; herkomst `factuur`);
3. anders de terugval "‹leveranciersnaam› ‹factuurnummer›" (vendor-cache-naam + referentie; herkomst `afgeleid`);
4. niets bruikbaar → None (RLZ/Odoo krijgen dan geen omschrijving, zoals vóór 07-09).

Een door de mens gezette omschrijving (herkomst `handmatig`) wint ALTIJD en wordt nooit door deze afleiding
overschreven — ook niet bij heropenen of herextractie (app/documenten/boekvoorstel.py bewaart 'm als
tijdlijn-notitie `kop_omschrijving`, zelfde JSON-patroon als de A10-prefill-snapshot; geen kolom/migratie).

Lengte: de RLZ-veldlengte van `Description` staat nergens gedocumenteerd (api-verkenning kent alleen korte
markers); afkap op een veilige `MAX_LENGTE` van 255 tekens met een ellipsis — nooit stil een 400 op de PUT.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_LENGTE = 255
_ELLIPSIS = "…"

HERKOMST_REGEL = "regel"
HERKOMST_FACTUUR = "factuur"
HERKOMST_AFGELEID = "afgeleid"
HERKOMST_HANDMATIG = "handmatig"


@dataclass(frozen=True)
class KopOmschrijving:
    tekst: str | None
    herkomst: str | None


def normaliseer(tekst: object) -> str | None:
    """Witruimte samenvouwen, strippen; leeg (of geen string) = None — de "" -sentinel van de AI én een leeg
    invoerveld van de mens betekenen beide "geen omschrijving"."""
    if tekst is None:
        return None
    if not isinstance(tekst, str):
        tekst = str(tekst)
    schoon = " ".join(tekst.split())
    return schoon or None


def kap_af(tekst: str, *, max_lengte: int = MAX_LENGTE) -> str:
    """Deterministische afkap: past het, ongewijzigd; anders `max_lengte - 1` tekens (rechts gestript) + "…"."""
    if len(tekst) <= max_lengte:
        return tekst
    return tekst[: max_lengte - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


def bepaal_kop_omschrijving(
    *,
    regel_omschrijvingen: list[str | None],
    betreft: str | None,
    leverancier_naam: str | None,
    referentie: str | None,
) -> KopOmschrijving:
    """De automatische kop-omschrijving volgens de volgorde uit de module-docstring. `regel_omschrijvingen` zijn
    de teksten van de ÉCHTE boekingsregels (de synthetische samengevoegde regel "Factuur X — samengevoegd (n
    regels)" telt niet als regeltekst — de aanroeper filtert die eruit)."""
    regels = [normaliseer(r) for r in regel_omschrijvingen]
    if len(regels) == 1 and regels[0]:
        return KopOmschrijving(tekst=kap_af(regels[0]), herkomst=HERKOMST_REGEL)
    betreft_schoon = normaliseer(betreft)
    if betreft_schoon:
        return KopOmschrijving(tekst=kap_af(betreft_schoon), herkomst=HERKOMST_FACTUUR)
    delen = [d for d in (normaliseer(leverancier_naam), normaliseer(referentie)) if d]
    if delen:
        return KopOmschrijving(tekst=kap_af(" ".join(delen)), herkomst=HERKOMST_AFGELEID)
    return KopOmschrijving(tekst=None, herkomst=None)
