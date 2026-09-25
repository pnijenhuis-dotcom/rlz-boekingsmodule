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

import re
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
    # FV-05 (feedbackrun A 25-09): True = uit de bron is een verwijzing naar een bijlage gestript ("huur juli conform
    # bijgevoegd overzicht" → "huur juli"); chip "ingekort" op het controlescherm. Nooit op een handmatige tekst.
    ingekort: bool = False


# FV-05 (feedbackrun A 25-09, Universal: "huur juli conform bijgevoegd overzicht"): verwijzingen naar bijlagen zeggen
# niets over de boeking en worden uit de automatische kop-omschrijving gestript. DETERMINISTISCHE lijst — alleen als
# STAART van de tekst (met wat er nog achter kan staan: een punt, haakjes, "voor details"), nooit midden in een zin:
# "zie bijlage voor de huur van juli" blijft staan (strippen zou de betekenis breken). Hoofdletterongevoelig.
_BIJLAGE_KERN = (
    r"(?:conform|volgens|cf\.?|cfm\.?|zie|als per|per|o\.?b\.?v\.?|op basis van|overeenkomstig)\s+"
    r"(?:de\s+|het\s+|onze\s+|uw\s+)?"
    r"(?:bijgevoegd(?:e)?\s+|meegezonden\s+|meegestuurde\s+|aangehechte\s+|bijgesloten\s+)?"
    r"(?:overzicht(?:en)?|specificatie(?:s)?|bijlage(?:n)?|opgave|urenstaat|urenoverzicht|werkbon(?:nen)?|"
    r"onderliggende\s+specificatie)"
    r"(?:\s+\d+)?"
)
_BIJLAGE_STAART = re.compile(
    r"(?:^|[\s,;:(\-–—])" + _BIJLAGE_KERN + r"(?:\s*\)|[\s.,;:)]*)?(?:\s+voor\s+(?:de\s+)?details)?[\s.,;:)]*$",
    re.IGNORECASE,
)
_ALLEEN_BIJLAGE = re.compile(r"^\s*(?:zie\s+)?bijlage(?:n)?[\s.:]*$", re.IGNORECASE)
_LOSSE_HAAKJES = re.compile(r"\s*\(\s*\)\s*")


def strip_bijlageverwijzingen(tekst: str | None) -> tuple[str | None, bool]:
    """(geschoonde tekst, gestript?) — verwijzingen naar een bijlage aan de STAART van de tekst weg ("huur juli conform
    bijgevoegd overzicht" → "huur juli", "Huur juli (zie bijlage)" → "Huur juli"); een tekst die niets anders is dan zo'n
    verwijzing wordt leeg (None) zodat de volgende bron aan de beurt komt. Nooit iets verzinnen, nooit midden in een
    zin knippen. Herhaalt zich zolang er een staart te strippen is ("… zie specificatie, conform bijlage")."""
    schoon = normaliseer(tekst)
    if schoon is None:
        return None, False
    if _ALLEEN_BIJLAGE.match(schoon):
        return None, True
    gestript = False
    for _ in range(3):
        nieuw = _BIJLAGE_STAART.sub("", schoon, count=1)
        nieuw = normaliseer(_LOSSE_HAAKJES.sub(" ", nieuw)) or ""
        nieuw = nieuw.rstrip(" ,;:-–—(").strip()
        if nieuw == schoon:
            break
        gestript = True
        schoon = nieuw
    if not schoon:
        return None, gestript
    return schoon, gestript


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
        # FV-05: bijlageverwijzing van de staart; blijft er niets over → volgende bron.
        regel_schoon, regel_ingekort = strip_bijlageverwijzingen(regels[0])
        if regel_schoon:
            return KopOmschrijving(tekst=kap_af(regel_schoon), herkomst=HERKOMST_REGEL, ingekort=regel_ingekort)
    betreft_schoon, betreft_ingekort = strip_bijlageverwijzingen(betreft)
    if betreft_schoon:
        return KopOmschrijving(tekst=kap_af(betreft_schoon), herkomst=HERKOMST_FACTUUR, ingekort=betreft_ingekort)
    delen = [d for d in (normaliseer(leverancier_naam), normaliseer(referentie)) if d]
    if delen:
        return KopOmschrijving(tekst=kap_af(" ".join(delen)), herkomst=HERKOMST_AFGELEID)
    return KopOmschrijving(tekst=None, herkomst=None)
