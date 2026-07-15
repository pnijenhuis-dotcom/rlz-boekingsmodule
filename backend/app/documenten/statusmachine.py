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
        DocumentStatus.EXTRACTIE_WACHTRIJ,
        DocumentStatus.EXTRACTIE_BEZIG,
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.VRAAG_OPEN,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.BOEKEN_MISLUKT,
        DocumentStatus.NIET_TOEGEWEZEN,
        DocumentStatus.HANDMATIG_AFMAKEN,
    }
)

_TOEGESTANE_OVERGANGEN: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.ONTVANGEN: frozenset(
        {
            DocumentStatus.EXTRACTIE_BEZIG,
            # Async extractie (migratie 0016): een groot document gaat bij upload direct de
            # achtergrondwachtrij in i.p.v. synchroon te extraheren.
            DocumentStatus.EXTRACTIE_WACHTRIJ,
            DocumentStatus.NIET_TOEGEWEZEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Wachtrij: de worker pakt het op (-> bezig, systeem-actor); verwijderen/afwijzen kan nog
    # gewoon — de worker slaat een document dat intussen niet meer op wachtrij staat over.
    DocumentStatus.EXTRACTIE_WACHTRIJ: frozenset(
        {
            DocumentStatus.EXTRACTIE_BEZIG,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    DocumentStatus.EXTRACTIE_BEZIG: frozenset(
        {
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.VRAAG_OPEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
            # Waarborg projectadministratie (migratie 0015): regelset niet aantoonbaar compleet
            # bij projectplicht — blokkerend, geen (totalen-only) voorstel.
            DocumentStatus.HANDMATIG_AFMAKEN,
            # Herstel na proces-herstart (async extractie): de in-process wachtrij overleeft een
            # herstart niet — een document dat in 'bezig' achterbleef gaat bij startup terug de
            # wachtrij in (systeem-actor, zichtbaar in de tijdlijn), nooit stil blijven hangen.
            DocumentStatus.EXTRACTIE_WACHTRIJ,
        }
    ),
    DocumentStatus.TE_CONTROLEREN: frozenset(
        {
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VRAAG_OPEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
            # "Opnieuw extraheren" (timeout-fix 2026-07-10): een mislukte AI-extractie laat het
            # document op te_controleren achter — de her-extractie doorloopt daarna gewoon weer
            # extractie_bezig -> te_controleren, met tijdlijn + audit zoals elke overgang.
            DocumentStatus.EXTRACTIE_BEZIG,
            # Opnieuw extraheren van een gróót document gaat via de wachtrij (async), niet
            # synchroon — zelfde klein-vs-groot-routing als bij de upload.
            DocumentStatus.EXTRACTIE_WACHTRIJ,
        }
    ),
    DocumentStatus.KLAAR_OM_TE_BOEKEN: frozenset(
        {
            DocumentStatus.GEBOEKT,
            DocumentStatus.BOEKEN_MISLUKT,
            DocumentStatus.TE_CONTROLEREN,
            # Vragenworkflow (2026-07-14, bewuste uitbreiding op de mockup — zie
            # docs/BESLISSINGEN.md): ook uit een al boekklaar document kan een vraag rijzen;
            # zonder deze overgang moest de controleur eerst kunstmatig terug naar
            # te_controleren. Boeken blijft vanuit vraag_open geblokkeerd.
            DocumentStatus.VRAAG_OPEN,
            # Afwijzen-workflow (2026-07-15, zelfde overweging als vraag_open hierboven): ook
            # een al boekklaar document kan alsnog fout blijken — heropenen herstelt exact deze
            # herkomst (afwijzing.status_voor_afwijzing).
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Beantwoorden/intrekken herstelt de HERKOMST-status van vóór de vraag
    # (vraag.status_voor_vraag — app/documenten/vragen.py), nooit hardgecodeerd te_controleren:
    # daarom staan alle drie de vraag-herkomsten hier als uitgang.
    DocumentStatus.VRAAG_OPEN: frozenset(
        {
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.HANDMATIG_AFMAKEN,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    DocumentStatus.NIET_TOEGEWEZEN: frozenset(
        {DocumentStatus.ONTVANGEN, DocumentStatus.AFGEWEZEN, DocumentStatus.VERWIJDERD}
    ),
    DocumentStatus.BOEKEN_MISLUKT: frozenset(
        {DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.TE_CONTROLEREN, DocumentStatus.VERWIJDERD}
    ),
    # Handmatig afmaken gedraagt zich verder als te_controleren (de controleur vult álles zelf
    # in; de harde checks — project verplicht per regel, regelsom — blijven de poort naar
    # boeken), plus de weg terug naar extractie_bezig voor een nieuwe extractiepoging.
    DocumentStatus.HANDMATIG_AFMAKEN: frozenset(
        {
            DocumentStatus.EXTRACTIE_BEZIG,
            # Zelfde reden als bij te_controleren: her-extractie van een groot document is async.
            DocumentStatus.EXTRACTIE_WACHTRIJ,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VRAAG_OPEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Heropenen (afwijzen-workflow 2026-07-15) herstelt de HERKOMST-status van vóór de afwijzing
    # (afwijzing.status_voor_afwijzing — app/documenten/afwijzen.py), nooit hardgecodeerd
    # te_controleren: daarom staan alle drie de afwijs-herkomsten hier als uitgang — zelfde
    # patroon als vraag_open hierboven.
    DocumentStatus.AFGEWEZEN: frozenset(
        {
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.HANDMATIG_AFMAKEN,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    DocumentStatus.GEBOEKT: frozenset(),
    DocumentStatus.VERWIJDERD: _NIET_GEBOEKTE_STATUSSEN,
}


def valideer_overgang(van: DocumentStatus, naar: DocumentStatus) -> None:
    toegestaan = _TOEGESTANE_OVERGANGEN.get(van, frozenset())
    if naar not in toegestaan:
        raise OngeldigeStatusovergang(f"Overgang {van.value} -> {naar.value} is niet toegestaan")
