"""RLZ-tekstvelden ontknippen (run 2 VGG 12-09, blok 0 — STAP-0 lees-only op 120 VGG-records, api-verkenning
"Regelknip op 32 tekens in Description/Reference — STAP-0 12-09").

Feit: bank-geïmporteerde omschrijvingen staan in RLZ's `Description` (documenten) en `Reference` (PaymentTransactions)
als
regels van PRECIES 32 tekens, gescheiden door `\\n`; een spatie op de regelgrens is door RLZ weggestript
("…Gelderstraat 60\\nte
Almere"), een woord kan midden in de knip staan ("Oo\\nsterdiepswal"). De module vouwde `\\n` overal tot een spatie
(`" ".join(w.split())`) — dát was de "spatie op positie 32" uit de nameting 11-09 ("Oo sterdiepswal", "Utrec", "Heerl
en").
Regels ≠ 32 tekens zijn échte regelovergangen (betaalkenmerk-regel + documentregel) en blijven een spatie.

Deterministische samenvoegregel op een 32-grens (a = laatste teken vóór, b = eerste teken ná de knip):
- letter|letter, cijfer|cijfer → aaneen ("Oo|sterdiepswal", "2025.07|8957.01", "Bornholmstraat 4|9");
- cijfer|één hoofdletter gevolgd door niet-letter → aaneen (huisnummer-toevoeging "123|B te Kerkrade");
- cijfer|woord → spatie ("60|te Almere", "44|Kerkrade" — de gestripte spatie komt terug);
- letter|cijfer → spatie (ambigu; adresherkenning heeft "straat 70" nodig, een terminal-id niet);
- leesteken `.`, `:`, `/`, `-`, `'` aan één van beide kanten → aaneen ("dossier:2025.|079527.01", "'|s-Gravenhage");
- `,` of `;` vóór de knip → spatie (", Almere").
Bewust geen woordenboek: de regel is toetsbaar en identiek voor documenten en bankregels. `ontknip` is idempotent op
tekst zonder `\\n`."""

from __future__ import annotations

import re

KNIPLENGTE = 32
_AANEEN_LEESTEKENS = frozenset(".:/-'’")
_SPATIE_LEESTEKENS = frozenset(",;")
_TOEVOEGING = re.compile(r"^[A-Z](?![A-Za-z])")


def _voeg(a: str, b: str) -> str:
    """Scheidingsteken op een 32-grens: '' (aaneen) of ' '."""
    if not a or not b:
        return " "
    la, lb = a[-1], b[0]
    if la in _SPATIE_LEESTEKENS:
        return " "
    if la in _AANEEN_LEESTEKENS or lb in _AANEEN_LEESTEKENS:
        return ""
    if la.isalpha() and lb.isalpha():
        return ""
    if la.isdigit() and lb.isdigit():
        return ""
    if la.isdigit() and _TOEVOEGING.match(b):
        return ""
    return " "


def ontknip(tekst: str | None) -> str | None:
    """`\\n`-regels samenvoegen: een regel van exact 32 tekens opent de knip-modus; daarbinnen telt ook een regel van
    31 tekens als knip (RLZ stripte een spatie aan het regelbegin/-einde, "te Almere, ons dossier: 2025.07" = 31); een
    kortere regel sluit de modus (échte regelovergang → spatie). Dubbele witruimte samengevouwen. None/leeg → None."""
    if not isinstance(tekst, str):
        return None
    regels = tekst.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    uit = regels[0]
    in_knip = len(regels[0]) == KNIPLENGTE
    for vorige, volgende in zip(regels, regels[1:], strict=False):
        in_knip = len(vorige) == KNIPLENGTE or (in_knip and len(vorige) == KNIPLENGTE - 1)
        uit = uit + (_voeg(vorige, volgende) if in_knip else " ") + volgende
    uit = " ".join(uit.split())
    return uit or None


def ontknip_velden(rij: dict, *velden: str) -> str | None:
    """Eerste gevulde veld uit `velden`, ontknipt — de vaste omschrijvingsbron voor schoonlijst en pandenregister."""
    for veld in velden:
        w = ontknip(rij.get(veld))
        if w:
            return w
    return None
