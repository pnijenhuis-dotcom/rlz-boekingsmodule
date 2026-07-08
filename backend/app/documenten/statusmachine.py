from __future__ import annotations

from app.documenten.models import DocumentStatus


class OngeldigeStatusovergang(Exception):
    """Een overgang die niet in de toegestane graaf staat — harde fout, nooit stil negeren."""


# Enige bron van waarheid voor toegestane overgangen — geen losse status-updates elders in de
# app. Terminale statussen (afgewezen, geboekt) hebben een lege doelverzameling.
_TOEGESTANE_OVERGANGEN: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.ONTVANGEN: frozenset(
        {DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.NIET_TOEGEWEZEN, DocumentStatus.AFGEWEZEN}
    ),
    DocumentStatus.EXTRACTIE_BEZIG: frozenset(
        {DocumentStatus.TE_CONTROLEREN, DocumentStatus.VRAAG_OPEN, DocumentStatus.AFGEWEZEN}
    ),
    DocumentStatus.TE_CONTROLEREN: frozenset(
        {DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.VRAAG_OPEN, DocumentStatus.AFGEWEZEN}
    ),
    DocumentStatus.KLAAR_OM_TE_BOEKEN: frozenset(
        {DocumentStatus.GEBOEKT, DocumentStatus.BOEKEN_MISLUKT, DocumentStatus.TE_CONTROLEREN}
    ),
    DocumentStatus.VRAAG_OPEN: frozenset({DocumentStatus.TE_CONTROLEREN, DocumentStatus.AFGEWEZEN}),
    DocumentStatus.NIET_TOEGEWEZEN: frozenset({DocumentStatus.ONTVANGEN, DocumentStatus.AFGEWEZEN}),
    DocumentStatus.BOEKEN_MISLUKT: frozenset({DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.TE_CONTROLEREN}),
    DocumentStatus.AFGEWEZEN: frozenset(),
    DocumentStatus.GEBOEKT: frozenset(),
}


def valideer_overgang(van: DocumentStatus, naar: DocumentStatus) -> None:
    toegestaan = _TOEGESTANE_OVERGANGEN.get(van, frozenset())
    if naar not in toegestaan:
        raise OngeldigeStatusovergang(f"Overgang {van.value} -> {naar.value} is niet toegestaan")
