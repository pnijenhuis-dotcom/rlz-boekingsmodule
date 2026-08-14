"""VANGNET rond de vervallen systeemanker-debiteur van route A.

Historie: het besluit "Systeemanker route A" (Peter 2026-08-14) hing pand-projecten onder één
anker-debiteur "Pandprojecten (systeem)" per administratie, omdat de toen bekende schrijfroute
(`PUT Customers/{baseId}/Projects/{id}`) een customer afdwong. Diezelfde dag bewees Peters
browsercapture + de Basic-Auth-hertest (api-verkenning "Projects klant-loze schrijfroute") dat
de top-level `PUT {adminId}/Projects/{id}` zónder customer werkt — de motor maakt sindsdien
klant-loze projecten en maakt GEEN ankers meer aan.

Waarom deze module blijft: er kán al een anker-debiteur in RLZ staan (de TEST-administratie
heeft er één; archiveren van een Customer is via de API niet mogelijk — IsArchived/RecordStatus
worden bij PUT stil genegeerd, hertest 2026-08-14 — dus opruimen kan alleen een mens in de
RLZ-UI). Zolang zo'n record bestaat blijft de harde afspraak gelden: **op een anker wordt
nooit geboekt.** De naam-/GUID-toetsen hier voeden de blokkerende checks in de boekpaden
(verkoop-checkrapport, zorg_voor_debiteur-slot, doorbelasting-whitelist-toets); ze slaan per
constructie alleen aan wanneer een boeking daadwerkelijk een anker-record raakt. Het vangnet
sterft dus vanzelf uit met de laatste actieve anker-debiteur — daarna is het dode code die
nooit meer vuurt, en mag het pas wég als geverifieerd is dat geen enkele administratie nog
een anker draagt.

Bewust dependency-arm (alleen rlz_ids) zodat elk boekpad 'm kan importeren zonder de
projecten-motor (RLZ-client, sync-modellen) mee te trekken."""

from __future__ import annotations

import uuid

from app.documenten.rlz_ids import rlz_customer_id

# NOOIT wijzigen — de blokkerende checks toetsen op exact deze naam; bestaande ankers in RLZ
# dragen 'm (aanmaak is per 2026-08-14 uit de motor verdwenen, zie module-docstring).
ANKER_CUSTOMER_NAAM = "Pandprojecten (systeem)"


def _normaliseer(naam: str | None) -> str:
    return " ".join((naam or "").split()).lower()


def is_anker_naam(naam: str | None) -> bool:
    """Case- en whitespace-ongevoelig (zelfde normalisatie als rlz_customer_id): een UBL of
    invoer die het anker nét anders spelt mag er niet langs glippen."""
    return _normaliseer(naam) == _normaliseer(ANKER_CUSTOMER_NAAM)


def anker_customer_id(administratie_id: uuid.UUID) -> uuid.UUID:
    """Het deterministische client-GUID waaronder de motor (tot 2026-08-14) ankers aanmaakte —
    vangnet voor toetsen op GUID (bv. de doorbelasting-whitelist) waar geen naam voorhanden
    is. NB een anker dat handmatig in RLZ is aangemaakt kan een ander GUID dragen; de
    naam-toets blijft daarom overal de eerste poort waar een naam beschikbaar is."""
    return rlz_customer_id(administratie_id, ANKER_CUSTOMER_NAAM)
