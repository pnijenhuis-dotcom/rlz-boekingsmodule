"""Omzetrekening van een Vastly-verkoopregel = uitsluitend `cbc:AccountingCost` uit de UBL (Peter 01-10: "ik wil gewoon
dat de vastly facturen automatisch per BV op de juiste GB geboekt worden … hou het simpel"; koppelcontract §2d v1.10
"AccountingCost = winnaar" + §2d-notitie 01-10; herziet punt 2 van 29-09).

Per regel (in `verkoop/voorstel.py` + `verkoop/autoboeken.py`):
 (a) `AccountingCost` aanwezig én bekend in het rekeningschema van de administratie → die rekening ('bekend', bron
     'ubl');
 (b) geen code, of een code die niet in het rekeningschema staat → de regel blijft leeg; het autoboek-pad weigert mét
     reden `omzetrekening_ontbreekt` en het reconciliatieblok `vastly_verkoop` maakt per document de bevinding
     `vastly_omzetrekening_ontbreekt` mét alleen "Opnieuw aanbieden" (ná herzending van de UBL door Vastly).

Wat per 01-10 is AFGEZET (de terugval van 29-09, in het koppelcontract vastgelegd als tijdelijke afwijking): de
afleiding
uit de eigen historie en het rekeningschema (`leid_af`), de vaste rij per (administratie, regelsoort) als boekbron en de
Beheerder-instelling "Vastly-omzetrekeningen" (rij + `PUT …/vastly-omzetrekeningen`). De tabel `vastly_omzetrekening`
blijft staan als lees-only historie (meetlat `db-lezen vastly-verkoop-administratie`), geen migratie. Code uit de UBL of
zichtbaar weigeren — niets ertussen. Geen AI, geen RLZ-call."""

from __future__ import annotations

import re

REGELSOORT_HUUR = "huur"
REGELSOORT_SERVICEKOSTEN = "servicekosten"
REGELSOORT_WAARBORG = "waarborg"
REGELSOORT_OVERIG = "overig"
#: Weigerreden voor het autoboek-pad + de bevindingssoort in het reconciliatieblok (geen code óf onbekende code).
REDEN_OMZETREKENING_ONTBREEKT = "omzetrekening_ontbreekt"

_SERVICE = re.compile(r"service\s*kost|servicekost|voorschot|stook|gas|water|elektr|energie|schoonmaak|vve", re.I)
_WAARBORG = re.compile(r"waarborg|borg", re.I)
_HUUR = re.compile(r"\bhuur|kale huur|rent\b|verhuur|indexering|huurverhoging", re.I)


def classificeer_regel(omschrijving: str | None) -> str:
    """Regelsoort uit de UBL-regelomschrijving — pure tekst, alleen nog voor de leesbare weigerreden/bevinding; eerste
    treffer wint in de volgorde waarborg → service → huur (een 'voorschot servicekosten huur' is servicekosten, een
    'waarborg huur' is waarborg)."""
    tekst = (omschrijving or "").strip()
    if not tekst:
        return REGELSOORT_OVERIG
    if _WAARBORG.search(tekst):
        return REGELSOORT_WAARBORG
    if _SERVICE.search(tekst):
        return REGELSOORT_SERVICEKOSTEN
    if _HUUR.search(tekst):
        return REGELSOORT_HUUR
    return REGELSOORT_OVERIG
