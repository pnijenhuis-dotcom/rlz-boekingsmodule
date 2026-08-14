"""Systeemanker-debiteur van route A (besluit Peter 2026-08-14, BESLISSINGEN "Route A"):
de RLZ-schrijfroute `PUT Customers/{baseId}/Projects/{id}` dwingt een customer af, dus elke
administratie met pand-projecten krijgt één idempotent aangemaakt anker "Pandprojecten
(systeem)". Het anker is uitsluitend een route-technisch ophangpunt — **er wordt nooit op
geboekt** (harde afspraak bij het besluit). Deze module is de ene plek die dat afdwingbaar
maakt: naam- en GUID-toetsen voor de blokkerende checks in de boekpaden (verkoop,
doorbelasting) en het fail-closed-slot in de debiteur-aanmaak.

Bewust dependency-arm (alleen rlz_ids) zodat elk boekpad 'm kan importeren zonder de
projecten-motor (RLZ-client, sync-modellen) mee te trekken."""

from __future__ import annotations

import uuid

from app.documenten.rlz_ids import rlz_customer_id

# NOOIT wijzigen zonder migratiepad — de motor-lookup én de blokkerende checks toetsen op
# exact deze naam (app/projecten/motor.py hangt de projecten eronder).
ANKER_CUSTOMER_NAAM = "Pandprojecten (systeem)"


def _normaliseer(naam: str | None) -> str:
    return " ".join((naam or "").split()).lower()


def is_anker_naam(naam: str | None) -> bool:
    """Case- en whitespace-ongevoelig (zelfde normalisatie als rlz_customer_id): een UBL of
    invoer die het anker nét anders spelt mag er niet langs glippen."""
    return _normaliseer(naam) == _normaliseer(ANKER_CUSTOMER_NAAM)


def anker_customer_id(administratie_id: uuid.UUID) -> uuid.UUID:
    """Het deterministische client-GUID waaronder de motor het anker aanmaakt — vangnet voor
    toetsen op GUID (bv. de doorbelasting-whitelist) waar geen naam voorhanden is. NB een
    anker dat al in RLZ bestond vóór de motor kan een ander GUID dragen; de naam-toets blijft
    daarom overal de eerste poort waar een naam beschikbaar is."""
    return rlz_customer_id(administratie_id, ANKER_CUSTOMER_NAAM)
