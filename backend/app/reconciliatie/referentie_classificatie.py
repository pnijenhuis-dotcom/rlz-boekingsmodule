"""Referentie-classificatie voor het reconciliatie-blok `rlz_dubbel` (blok 1 vervolgrun 10-09 avond, besluit Peter).

Aanleiding: productie 10-09 06:32 meldde 907 "mogelijk dubbel"-paren over 14 administraties, vrijwel allemaal op een
referentie die géén factuurnummer is — BP Express zet het klantnummer 0817725528 op élke bank-directe boeking (7
boekingen = 21 paren), Food service draagt het eigen IBAN NL86INGB0662462785 als referentie (4 boekingen = 6 paren).
Eén échte casus zat ertussen: 6-Steps Projectbeheersing RLZ-04-00000069/00000072 (beide concept, zelfde dag, zelfde
bedrag).

Deze module is PUUR en deterministisch (geen DB, geen RLZ, geen AI) en zegt per referentiegroep (dezelfde crediteur,
dezelfde genormaliseerde referentie) of die groep als "mogelijk dubbel" toetsbaar is, of om welke reden niet:

- `REDEN_PLACEHOLDER` — de referentie is een plaatsvervanger ("Ingescand document", alleen nullen; blok 7 herstelrun
  08-09, `rlz_dubbel.is_placeholder_referentie`). Zulke documenten hebben `referentie_norm is None`.
- `REDEN_IBAN` — de referentie lijkt op een IBAN: de Nederlandse vorm `NL\\d{2}[A-Z]{4}\\d{10}` (altijd, ook zonder
  checksum — het formaat is onmiskenbaar) of een ander landformaat (2 letters + 2 cijfers + 11–30 alfanumeriek) MÉT
  geldige mod-97-controle (anders zou een factuurnummer als "FA2026000123456" ten onrechte een IBAN zijn). Getoetst op
  de ruwe tekst ná het weghalen van spaties/leestekens én op de genormaliseerde vorm (waar voorloopnullen per
  cijfergroep al weg zijn: "nl86ingb662462785").
- `REDEN_KLANTKENMERK` — dezelfde referentie komt bij dezelfde crediteur ≥ 3× voor mét ≥ 2 verschillende bedragen:
  dat is een klant-/contract-/debiteurnummer dat de leverancier op élke factuur zet, geen factuurnummer. Precies 3×
  met één bedrag = NIET uitgesloten (drie keer hetzelfde bedrag op hetzelfde nummer kan echt dubbel zijn); 2× met
  twee bedragen = NIET uitgesloten (twee exemplaren met een ander bedrag is juist het "verkeerd overgetypt"-geval).

Alle bedragvergelijking gebeurt op `Decimal` (cent-exact, `bedrag_cent_exact` in de lezer), nooit op float."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

REDEN_PLACEHOLDER = "placeholder"
REDEN_IBAN = "iban"
REDEN_KLANTKENMERK = "klantkenmerk"
#: Volgorde = weergavevolgorde in tellers en rapporten.
UITSLUITINGSREDENEN: tuple[str, ...] = (REDEN_PLACEHOLDER, REDEN_IBAN, REDEN_KLANTKENMERK)
REDEN_LABEL = {
    REDEN_PLACEHOLDER: "plaatsvervanger-referentie",
    REDEN_IBAN: "referentie is een IBAN",
    REDEN_KLANTKENMERK: "klant-/contractnummer (≥ 3× met verschillende bedragen)",
}

KLANTKENMERK_MIN_DOCUMENTEN = 3
KLANTKENMERK_MIN_BEDRAGEN = 2

_NIET_ALFANUMERIEK = re.compile(r"[^A-Z0-9]")
_IBAN_NL = re.compile(r"NL\d{2}[A-Z]{4}\d{10}")
#: De genormaliseerde vorm (`normaliseer_referentie`) haalt voorloopnullen per cijfergroep weg: "0662" → "662".
_IBAN_NL_GENORMALISEERD = re.compile(r"NL\d{2}[A-Z]{4}\d{7,10}")
_IBAN_GENERIEK = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")


class _MetReferentieEnBedrag(Protocol):
    referentie: str | None
    referentie_norm: str | None
    bedrag: Decimal | None


def _compact(tekst: str) -> str:
    return _NIET_ALFANUMERIEK.sub("", tekst.upper())


def iban_checksum_geldig(compact: str) -> bool:
    """Mod-97 (ISO 13616): landcode + controlecijfers achteraan, letters → 10..35, rest bij deling door 97 = 1."""
    if len(compact) < 5:
        return False
    herschikt = compact[4:] + compact[:4]
    cijfers = "".join(str(ord(c) - 55) if c.isalpha() else c for c in herschikt)
    try:
        return int(cijfers) % 97 == 1
    except ValueError:
        return False


def lijkt_op_iban(referentie: str | None, referentie_norm: str | None = None) -> bool:
    """Deterministisch: NL-vorm altijd; ander landformaat alleen mét geldige mod-97-controle."""
    for kandidaat in (referentie, referentie_norm):
        if not kandidaat:
            continue
        compact = _compact(str(kandidaat))
        if _IBAN_NL.fullmatch(compact) or _IBAN_NL_GENORMALISEERD.fullmatch(compact):
            return True
        if _IBAN_GENERIEK.fullmatch(compact) and iban_checksum_geldig(compact):
            return True
    return False


def is_klantkenmerk(bedragen: Iterable[Decimal | None], *, aantal_documenten: int) -> bool:
    """≥ 3 documenten mét ≥ 2 verschillende (bekende) bedragen op dezelfde referentie = klant-/contractnummer."""
    if aantal_documenten < KLANTKENMERK_MIN_DOCUMENTEN:
        return False
    verschillend = {b for b in bedragen if b is not None}
    return len(verschillend) >= KLANTKENMERK_MIN_BEDRAGEN


@dataclass(frozen=True)
class Classificatie:
    """Uitkomst per referentiegroep: `reden is None` = toetsbaar als mogelijk-dubbel-cluster."""

    reden: str | None
    aantal_documenten: int
    aantal_bedragen: int

    @property
    def toetsbaar(self) -> bool:
        return self.reden is None


def classificeer_groep(documenten: Sequence[_MetReferentieEnBedrag]) -> Classificatie:
    """Eén groep = documenten van dezelfde crediteur met dezelfde (genormaliseerde) referentie. Volgorde van de
    redenen: placeholder (referentie_norm ontbreekt) → IBAN → klantkenmerk. Een groep van één document is triviaal
    toetsbaar-zonder-treffer; de aanroeper maakt er geen cluster van."""
    bedragen = [d.bedrag for d in documenten]
    aantal_bedragen = len({b for b in bedragen if b is not None})
    n = len(documenten)
    if not documenten:
        return Classificatie(reden=None, aantal_documenten=0, aantal_bedragen=0)
    if all(d.referentie_norm is None for d in documenten):
        return Classificatie(reden=REDEN_PLACEHOLDER, aantal_documenten=n, aantal_bedragen=aantal_bedragen)
    if any(lijkt_op_iban(d.referentie, d.referentie_norm) for d in documenten):
        return Classificatie(reden=REDEN_IBAN, aantal_documenten=n, aantal_bedragen=aantal_bedragen)
    if is_klantkenmerk(bedragen, aantal_documenten=n):
        return Classificatie(reden=REDEN_KLANTKENMERK, aantal_documenten=n, aantal_bedragen=aantal_bedragen)
    return Classificatie(reden=None, aantal_documenten=n, aantal_bedragen=aantal_bedragen)
