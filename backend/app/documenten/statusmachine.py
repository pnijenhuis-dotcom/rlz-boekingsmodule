from __future__ import annotations

from app.documenten.models import DocumentStatus


class OngeldigeStatusovergang(Exception):
    """Een overgang die niet in de toegestane graaf staat — harde fout, nooit stil negeren."""


# Enige bron van waarheid voor toegestane overgangen — geen losse status-updates elders in de
# app. GEBOEKT is de enige echt terminale status (bewaarplicht: nooit verwijderd, zie
# VERWIJDERD hieronder). Elke andere status — óók AFGEWEZEN — mag naar VERWIJDERD (design-pass
# taak 4, "documenten verwijderen": alléén niet-geboekte documenten). VERWIJDERD zelf mag terug
# naar precies de statussen die er ook naartoe mogen — herstellen (service.py::herstel_document)
# zet het document terug op de status van vóór de verwijdering, uit de tijdlijn.
_NIET_GEBOEKTE_STATUSSEN = frozenset(
    {
        DocumentStatus.ONTVANGEN,
        DocumentStatus.EXTRACTIE_BEZIG,
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.VRAAG_OPEN,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.BOEKEN_MISLUKT,
        DocumentStatus.NIET_TOEGEWEZEN,
    }
)

_TOEGESTANE_OVERGANGEN: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.ONTVANGEN: frozenset(
        {
            DocumentStatus.EXTRACTIE_BEZIG,
            DocumentStatus.NIET_TOEGEWEZEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    DocumentStatus.EXTRACTIE_BEZIG: frozenset(
        {DocumentStatus.TE_CONTROLEREN, DocumentStatus.VRAAG_OPEN, DocumentStatus.AFGEWEZEN, DocumentStatus.VERWIJDERD}
    ),
    DocumentStatus.TE_CONTROLEREN: frozenset(
        {
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VRAAG_OPEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    DocumentStatus.KLAAR_OM_TE_BOEKEN: frozenset(
        {
            DocumentStatus.GEBOEKT,
            DocumentStatus.BOEKEN_MISLUKT,
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    DocumentStatus.VRAAG_OPEN: frozenset(
        {DocumentStatus.TE_CONTROLEREN, DocumentStatus.AFGEWEZEN, DocumentStatus.VERWIJDERD}
    ),
    DocumentStatus.NIET_TOEGEWEZEN: frozenset(
        {DocumentStatus.ONTVANGEN, DocumentStatus.AFGEWEZEN, DocumentStatus.VERWIJDERD}
    ),
    DocumentStatus.BOEKEN_MISLUKT: frozenset(
        {DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.TE_CONTROLEREN, DocumentStatus.VERWIJDERD}
    ),
    DocumentStatus.AFGEWEZEN: frozenset({DocumentStatus.VERWIJDERD}),
    DocumentStatus.GEBOEKT: frozenset(),
    DocumentStatus.VERWIJDERD: _NIET_GEBOEKTE_STATUSSEN,
}


def valideer_overgang(van: DocumentStatus, naar: DocumentStatus) -> None:
    toegestaan = _TOEGESTANE_OVERGANGEN.get(van, frozenset())
    if naar not in toegestaan:
        raise OngeldigeStatusovergang(f"Overgang {van.value} -> {naar.value} is niet toegestaan")
