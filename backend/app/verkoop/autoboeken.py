"""Automatisch boeken van VASTLY-VERKOOP-documenten — opt-in per is_vastgoed-administratie
(besluit Peter 2026-08-15, automatisering-first; migratie 0051).

Zelfde principe als het leverancier-autoboeken-pad (app/documenten/autoboeken.py): de enige
menselijke handeling die vervalt is de boek-klik, en alléén wanneer élk oordeel dat die klik
zou vellen al deterministisch vaststaat. Anders dan bij inkoop is er hier geen AI en geen
boekingsgeheugen in het spel: de UBL ís de gestructureerde bron — "volledig groen" betekent
dat het hele voorstel deterministisch uit de UBL volgt:

1. De Beheerder heeft verkoop-autoboeken voor deze administratie expliciet aangezet (default
   UIT, alleen mogelijk voor is_vastgoed-administraties — beheer-service dwingt dat af).
2. De HARDE CHECKS draaien onverkort in de verkoop-boekmotor (verplichte velden, regelsom,
   GB-codes bekend, btw-per-regel-=-factuur-btw, geen ankerdebiteur, duplicaat lokaal + RLZ,
   creditnota-herleiding) — een blokkerende check wint altijd.
3. Elke regel is ondubbelzinnig uit de UBL geresolved: GB-code aanwezig én bekend in het
   rekeningschema ('bekend' — 'ontbreekt' = mens kiest, 'onbekend' = blokkerend + autovraag),
   en de btw VERGRENDELD (bron 'factuur', of 'onthouden' — dat is de eerder door een mens
   bevestigde keuze bij echte ambiguïteit, per administratie; zonder die bevestiging boekt
   ambiguïteit nooit automatisch — zelfde lijn als app-bevestigd geheugen bij inkoop).
4. Geen open vraag, geen afwijzing (statuspoort: alleen TE_CONTROLEREN), geen
   mogelijk-duplicaat-signaal, geen door een mens aangeraakt voorstel (opgeslagen = mensenwerk).
5. Volumerem en boeken-toggle/kill switch gelden onverkort (de verkoop-boekmotor dwingt ze af).
   Een creditnota (381) is geen aparte weigergrond: de herleiding-check (geboekt origineel)
   is de harde poort — elke creditnota-bijzonderheid daarbuiten blokkeert via de checks.

Elke poging bij een administratie mét opt-in wordt geauditeerd (`automatisch_geboekt` /
`autoboeken_geweigerd` + reden, bron `verkoop_opt_in`); de GEBOEKT-overgang draagt
`automatisch_geboekt` (systeem-actor) — zelfde chip/filter als het inkoop-pad. Zonder opt-in
bewust géén audit-ruis. De `factuur_geboekt`-webhook vuurt identiek aan handmatig boeken
(de motor maakt de outbox-rij, ongeacht de actor). Terugweg = storno actie 19, als altijd."""

from __future__ import annotations

import logging
import uuid

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.autoboeken import AutoboekBesluit
from app.documenten.boeken import (
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
)
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.verkoop.boeken import boek_verkoop_document
from app.verkoop.voorstel import VerkoopVoorstelData, haal_verkoop_voorstel_op

logger = logging.getLogger(__name__)

_TOEGESTANE_BTW_BRONNEN = frozenset({"factuur", "onthouden"})


def _regels_geblokkeerd(voorstel: VerkoopVoorstelData) -> str | None:
    """Weiger-reden wanneer het voorstel niet volledig deterministisch uit de UBL volgt.
    De harde checks in de motor toetsen de gekózen waarden nogmaals — hier gaat het om de
    vraag of er überhaupt iets te kiezen overbleef voor een mens."""
    if not voorstel.regels:
        return "de UBL leverde geen boekbare regels"
    for regel in voorstel.regels:
        if regel.netto_bedrag is None:
            return f"regel {regel.volgnummer} heeft geen nettobedrag"
        if regel.gb_code_status != "bekend" or regel.ledger_id is None:
            if regel.gb_code_status == "onbekend":
                return (
                    f"regel {regel.volgnummer}: grootboekcode {regel.gb_code} uit de UBL is "
                    "onbekend in het rekeningschema (blokkerend + automatische vraag)"
                )
            return f"regel {regel.volgnummer}: geen grootboekcode in de UBL — mens kiest"
        if not regel.btw_vergrendeld or regel.taxrate_id is None or regel.btw_bron not in _TOEGESTANE_BTW_BRONNEN:
            if regel.btw_kandidaten and len(regel.btw_kandidaten) > 1:
                return (
                    f"regel {regel.volgnummer}: factuur-btw is ambigu (meerdere dekkende "
                    "RLZ-tarieven) en er is nog geen onthouden keuze voor deze administratie"
                )
            return f"regel {regel.volgnummer}: btw is niet deterministisch uit de UBL bepaald — mens kiest"
    return None


def _weiger(*, administratie_id: uuid.UUID, document_id: uuid.UUID, reden: str) -> AutoboekBesluit:
    logger.info("Verkoop-autoboeken geweigerd voor document %s: %s", document_id, reden)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="autoboeken_geweigerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": reden, "bron": "verkoop_opt_in"},
            administratie_id=administratie_id,
        )
    return AutoboekBesluit(geboekt=False, reden=reden)


def probeer_verkoop_autoboeken_na_intake(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> AutoboekBesluit | None:
    """Het verkoop-autoboek-pad, aangeroepen ná de (deterministische) verwerking van een
    verkoopfactuur-document — zelfde post-commit-hook als het inkoop-pad. Retourneert None
    wanneer autoboeken hier per definitie niet aan de orde is (geen verkoopfactuur, status is
    al geen kandidaat meer, of opt-in uit — bewust géén audit-ruis), anders een AutoboekBesluit
    (geboekt of geweigerd-met-reden, altijd geauditeerd)."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.VERKOOPFACTUUR.value:
            return None
        if document.status != DocumentStatus.TE_CONTROLEREN:
            # Vraag open/afgewezen/wachtrij/verzamelbak: per definitie geen kandidaat.
            return None
        mogelijk_duplicaat = document.mogelijk_duplicaat_van_id is not None
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.verkoop_autoboeken_ingeschakeld:
            return None
        is_vastgoed = administratie.is_vastgoed

    # Vanaf hier is autoboeken expliciet aangezet — elke uitkomst wordt geauditeerd.
    if not is_vastgoed:
        # Kan alleen als is_vastgoed ná de opt-in is teruggedraaid — inconsistente staat,
        # fail-closed en zichtbaar (de Beheerder hoort de opt-in dan ook uit te zetten).
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="opt-in staat aan maar de administratie is geen vastgoed-administratie meer "
            "(is_vastgoed uit) — zet verkoop-autoboeken uit",
        )
    if mogelijk_duplicaat:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="mogelijk-duplicaat-signaal op het document (zelfde bestandsinhoud) — mens beoordeelt",
        )

    voorstel = haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.opgeslagen:
        # Kan alleen bij her-verwerking van een document waar een mens al aan zat — dan is
        # de mens de eigenaar van het voorstel en drukt híj op de knop.
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="er is al een door een mens opgeslagen voorstel — automatisch boeken doet "
            "uitsluitend onaangeraakte documenten",
        )
    if voorstel.factuurnummer is None or voorstel.factuurdatum is None or voorstel.totaalbedrag_incl is None:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="de UBL leverde geen volledige kopgegevens (factuurnummer/datum/totaal)",
        )
    blokkade = _regels_geblokkeerd(voorstel)
    if blokkade is not None:
        return _weiger(administratie_id=administratie_id, document_id=document_id, reden=blokkade)

    try:
        boek_verkoop_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            extra_overgang_detail={"automatisch_geboekt": True, "bron": "verkoop_opt_in"},
        )
    except BoekenGeblokkeerdDoorChecks as exc:
        geblokkeerd = [f"{r.naam}: {r.melding}" for r in exc.rapport.resultaten if not r.ok]
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="harde checks blokkeren — " + "; ".join(geblokkeerd),
        )
    except (BoekenUitgeschakeld, VolumeremBereikt, OngeldigeBoekpoging) as exc:
        return _weiger(administratie_id=administratie_id, document_id=document_id, reden=str(exc))
    except RlzBoekingMislukt as exc:
        # Het document staat nu zichtbaar op boeken_mislukt (de motor zette dat al) — de
        # weigering wordt daarnaast geauditeerd; een mens pakt de retry op.
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden=f"RLZ-boekfout tijdens autoboeken (document staat op boeken_mislukt): {exc}",
        )

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="automatisch_geboekt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "factuurnummer": voorstel.factuurnummer,
                "is_creditnota": voorstel.is_creditnota,
                "bron": "verkoop_opt_in",
            },
            administratie_id=administratie_id,
        )
    return AutoboekBesluit(geboekt=True, reden="automatisch geboekt (opt-in verkoop-administratie)")
