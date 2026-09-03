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
        DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
    }
)

# Verplaatsen naar een andere administratie (addendum kantoor-run 27-08 punt 5): het document gaat
# terug naar ONTVANGEN in de dóél-administratie, waarna de normale extractieflow opnieuw start
# (zelfde route als een verzamelbak-toewijzing). Alleen vanuit de niet-geboekte kantoorbak-statussen
# — geboekt (storno/tegenboeken is de weg) en ter_accordering (eerst intrekken) kennen dit pad bewust
# niet; app/documenten/verplaatsen.py is de enige aanroeper.
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
            DocumentStatus.ONTVANGEN,  # verplaatsen naar andere administratie (27-08 punt 5)
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VRAAG_OPEN,
            DocumentStatus.AFGEWEZEN,
            # IBAN-wissel vier-ogen-accordering (2026-07-15): een afwijkend IBAN aanbieden
            # blokkeert boeken tot een accordeur ≠ aanvrager besluit — accorderen herstelt de
            # herkomst (iban_accordering.status_voor_accordering), zelfde patroon als
            # vraag_open/afgewezen.
            DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
            DocumentStatus.VERWIJDERD,
            # "Opnieuw extraheren" (timeout-fix 2026-07-10): een mislukte AI-extractie laat het
            # document op te_controleren achter — de her-extractie doorloopt daarna gewoon weer
            # extractie_bezig -> te_controleren, met tijdlijn + audit zoals elke overgang.
            DocumentStatus.EXTRACTIE_BEZIG,
            # Opnieuw extraheren van een gróót document gaat via de wachtrij (async), niet
            # synchroon — zelfde klein-vs-groot-routing als bij de upload.
            DocumentStatus.EXTRACTIE_WACHTRIJ,
            # Nabundel-nazorg dubbelparen (03-09, akkoord Peter): een al toegewezen UBL-DOCUMENT dat
            # naast zijn PDF-tegenhanger in dezelfde administratie staat wordt in dat PDF-document
            # nagebundeld (UBL = data, PDF = beeld) en gaat zelf terminaal naar samengevoegd —
            # uitsluitend via app/intake/nabundelen.py, nooit verwijderd.
            DocumentStatus.SAMENGEVOEGD,
        }
    ),
    DocumentStatus.KLAAR_OM_TE_BOEKEN: frozenset(
        {
            DocumentStatus.ONTVANGEN,  # verplaatsen naar andere administratie (27-08 punt 5)
            DocumentStatus.GEBOEKT,
            DocumentStatus.BOEKEN_MISLUKT,
            DocumentStatus.TE_CONTROLEREN,
            # Klant-accorderingsflow (migratie 0033): administratie met accordering aan —
            # de boekknop wordt "Ter accordering", het document gaat naar de klant.
            DocumentStatus.TER_ACCORDERING,
            # Vragenworkflow (2026-07-14, bewuste uitbreiding op de mockup — zie
            # docs/BESLISSINGEN.md): ook uit een al boekklaar document kan een vraag rijzen;
            # zonder deze overgang moest de controleur eerst kunstmatig terug naar
            # te_controleren. Boeken blijft vanuit vraag_open geblokkeerd.
            DocumentStatus.VRAAG_OPEN,
            # Afwijzen-workflow (2026-07-15, zelfde overweging als vraag_open hierboven): ook
            # een al boekklaar document kan alsnog fout blijken — heropenen herstelt exact deze
            # herkomst (afwijzing.status_voor_afwijzing).
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Beantwoorden/intrekken herstelt de HERKOMST-status van vóór de vraag
    # (vraag.status_voor_vraag — app/documenten/vragen.py), nooit hardgecodeerd te_controleren:
    # daarom staan alle drie de vraag-herkomsten hier als uitgang.
    DocumentStatus.VRAAG_OPEN: frozenset(
        {
            DocumentStatus.ONTVANGEN,  # verplaatsen naar andere administratie (27-08 punt 5)
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.HANDMATIG_AFMAKEN,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Verzamelbak (e-mail-intake, migratie 0028): toewijzen zet het document terug op
    # ontvangen (waarna de normale extractieflow start), "hoort niet bij ons" = afgewezen met
    # verplichte reden, en een bevestigde multi-factuur-splitsing maakt het bron-document
    # terminaal gesplitst (de kinderen doorlopen elk de normale flow).
    DocumentStatus.NIET_TOEGEWEZEN: frozenset(
        {
            DocumentStatus.ONTVANGEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.VERWIJDERD,
            DocumentStatus.GESPLITST,
            DocumentStatus.SAMENGEVOEGD,  # handmatig samenvoegen in de verzamelbak (0098)
        }
    ),
    DocumentStatus.BOEKEN_MISLUKT: frozenset(
        {DocumentStatus.KLAAR_OM_TE_BOEKEN, DocumentStatus.TE_CONTROLEREN, DocumentStatus.VERWIJDERD}
    ),
    # Handmatig afmaken gedraagt zich verder als te_controleren (de controleur vult álles zelf
    # in; de harde checks — project verplicht per regel, regelsom — blijven de poort naar
    # boeken), plus de weg terug naar extractie_bezig voor een nieuwe extractiepoging.
    DocumentStatus.HANDMATIG_AFMAKEN: frozenset(
        {
            DocumentStatus.ONTVANGEN,  # verplaatsen naar andere administratie (27-08 punt 5)
            DocumentStatus.EXTRACTIE_BEZIG,
            # Zelfde reden als bij te_controleren: her-extractie van een groot document is async.
            DocumentStatus.EXTRACTIE_WACHTRIJ,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VRAAG_OPEN,
            DocumentStatus.AFGEWEZEN,
            DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
            DocumentStatus.VERWIJDERD,
            DocumentStatus.SAMENGEVOEGD,  # nabundel-nazorg dubbelparen (03-09), zie te_controleren
        }
    ),
    # Accorderen herstelt de HERKOMST-status van vóór het aanbieden
    # (iban_accordering.status_voor_accordering — app/documenten/iban_accordering.py), daarom
    # alle drie de herkomsten als uitgang. Ná een afwijzing blijft het document op deze status
    # (geblokkeerd, gemarkeerd verdacht); een nieuwe aanvraag is dan de enige weg vooruit —
    # zie docs/ontwerp/iban-wissel-accordering.md.
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING: frozenset(
        {
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.HANDMATIG_AFMAKEN,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Heropenen (afwijzen-workflow 2026-07-15) herstelt de HERKOMST-status van vóór de afwijzing
    # (afwijzing.status_voor_afwijzing — app/documenten/afwijzen.py), nooit hardgecodeerd
    # te_controleren: daarom staan alle drie de afwijs-herkomsten hier als uitgang — zelfde
    # patroon als vraag_open hierboven.
    DocumentStatus.AFGEWEZEN: frozenset(
        {
            DocumentStatus.ONTVANGEN,  # verplaatsen naar andere administratie (27-08 punt 5)
            DocumentStatus.TE_CONTROLEREN,
            DocumentStatus.HANDMATIG_AFMAKEN,
            DocumentStatus.KLAAR_OM_TE_BOEKEN,
            DocumentStatus.VERWIJDERD,
        }
    ),
    # Klant-accordering (migratie 0033): terug naar klaar_om_te_boeken bij het laatste akkoord
    # (waarna de boekmotor met alle harde checks draait) of bij intrekken door het kantoor;
    # afwijzen door de accordeur loopt via datzelfde terugzetten + het bestaande
    # afwijzen-met-verplichte-reden (heropenen brengt het document dan terug in de kantoorbak).
    # Bewust NIET naar VERWIJDERD: een document dat bij de klant ligt haal je eerst terug.
    DocumentStatus.TER_ACCORDERING: frozenset({DocumentStatus.KLAAR_OM_TE_BOEKEN}),
    # Tegenboek-pad (migratie 0061, mockup tegenboek-mockup.html): "tegenboeken én opnieuw
    # boeken" zet het document terug in de werkvoorraad — de ENIGE uitgang uit GEBOEKT, en
    # uitsluitend gebruikt door app/documenten/tegenboeken.py ná een geslaagde tegenboeking in
    # RLZ (aangifte-poort geblokkeerd, verplichte reden, audit). Een kale storno kent het
    # inkooppad nog steeds niet (dat blijft actie 19 in de RLZ-UI + detectie).
    DocumentStatus.GEBOEKT: frozenset({DocumentStatus.TE_CONTROLEREN}),
    DocumentStatus.GESPLITST: frozenset(),
    # Samenvoegen ongedaan maken: een bak-rij gaat terug naar niet_toegewezen (zolang het leidende
    # document nog in de verzamelbak staat of nagebundeld is); een nagebundeld UBL-DOCUMENT (03-09)
    # gaat terug naar de status van vóór de nabundeling (te_controleren/handmatig_afmaken — uit het
    # tijdlijn-detail `vorige_status`, nooit hardgecodeerd). Nooit naar verwijderd.
    DocumentStatus.SAMENGEVOEGD: frozenset(
        {DocumentStatus.NIET_TOEGEWEZEN, DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN}
    ),
    DocumentStatus.VERWIJDERD: _NIET_GEBOEKTE_STATUSSEN,
}


def valideer_overgang(van: DocumentStatus, naar: DocumentStatus) -> None:
    toegestaan = _TOEGESTANE_OVERGANGEN.get(van, frozenset())
    if naar not in toegestaan:
        raise OngeldigeStatusovergang(f"Overgang {van.value} -> {naar.value} is niet toegestaan")
