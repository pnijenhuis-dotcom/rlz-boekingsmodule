"""Automatisch boeken van OMZETRAPPORTEN (kassarapporten) — opt-in per administratie (GO Peter
01-09; migratie 0096). Het aparte akkoord waar BESLISSINGEN "Autoboek-afweging overige
deterministische paden" (16-08) op wachtte; vaste automatisering-first-patroon.

De drie destijds ontbrekende zekerheden zijn hier zó ingevuld:
(a) de bron is AI-extractie van een PDF — daarom boekt dit pad uitsluitend als de categorie-mapping
    volledig MENS-BEVESTIGD is (élke regel herkomst 'mapping': een eerder door een mens onthouden
    mapping; 'nieuw' = geen mapping = weigeren; een door een mens aangeraakt voorstel = mensenwerk)
    én de deterministische controlelaag van de rapport-extractie alle harde checks doorstaat;
(b) de marge-vs-historie-plausibiliteitscheck is een BLOKKERENDE harde check in de omzet-boekmotor
    (buiten de bandbreedte = geen boeking) — dit pad voegt daar niets aan toe en haalt niets weg;
(c) het twee-documenten-pad (verkoop + kostprijsmemoriaal) mag nooit stil een half_geboekt-geval
    produceren: gebeurt dat hier, dan volgt naast de bestaande zichtbare status óók een audit-event
    `autoboeken_half_geboekt` en een ALERT via het bewakingskanaal (mail) — de omzet-reconciliatie
    blijft het herstelpad.

Poorten (allemaal deterministisch, alleen bij opt-in AAN — anders bewust géén audit-ruis):
1. document is een kassarapport op TE_CONTROLEREN (geen open vraag/afwijzing/wachtrij);
2. geen mogelijk-duplicaat-signaal (zelfde bestandsinhoud);
3. geen door een mens opgeslagen voorstel (opgeslagen = de mens is eigenaar en drukt zelf);
4. volledige kopgegevens (periode + rapporttotalen) en per regel herkomst 'mapping' + GB/btw gevuld,
   voorraad-GB per administratie ingesteld (memoriaal-kant);
5. de omzet-boekmotor draait álle harde checks (verplichte velden, mapping, regelsom, memoriaal-saldo-0,
   duplicaat per periode lokaal + RLZ, marge-plausibiliteit) én de failsafes (boeken-toggle/kill switch,
   volumerem 20/dag) onverkort — de één-transactie-garantie (storno verkoop bij memoriaal-fout,
   half_geboekt-vangnet) is die van de motor.
Elke poging bij opt-in-aan is geauditeerd (`automatisch_geboekt` / `autoboeken_geweigerd` + reden,
bron `omzet_opt_in`); de GEBOEKT-overgang draagt `automatisch_geboekt` (systeem-actor) → zelfde
werkvoorraad-chip/filter/tijdlijn als inkoop en verkoop. Terugweg = storno, als altijd."""

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
from app.omzet.boeken import HalfGeboekt, boek_omzet_document
from app.omzet.voorstel import OmzetVoorstelData, haal_omzet_voorstel_op
from app.rlz.credentials import GeenRlzCredentials

logger = logging.getLogger(__name__)

BRON = "omzet_opt_in"


def _regels_geblokkeerd(voorstel: OmzetVoorstelData) -> str | None:
    """Weiger-reden wanneer het voorstel niet volledig uit mens-bevestigde mapping volgt."""
    if not voorstel.regels:
        return "het rapport leverde geen omzetregels"
    if voorstel.voorraad_ledger_id is None:
        return "geen voorraad-grootboekrekening ingesteld voor deze administratie (kostprijsmemoriaal) — mens kiest"
    for i, regel in enumerate(voorstel.regels, start=1):
        if regel.herkomst != "mapping":
            return (
                f"regel {i} ({regel.categorie}): categorie zonder mens-bevestigde mapping "
                f"(herkomst {regel.herkomst}) — blokkerend + automatische vraag"
            )
        if regel.omzet_ledger_id is None or regel.taxrate_id is None:
            return f"regel {i} ({regel.categorie}): mapping onvolledig (grootboek/btw) — mens kiest"
        if regel.omzet_bedrag is None:
            return f"regel {i} ({regel.categorie}): geen omzetbedrag geëxtraheerd"
        if regel.kostprijs_bedrag is not None and regel.kostprijs_ledger_id is None:
            return f"regel {i} ({regel.categorie}): kostprijs zonder kostprijs-grootboek in de mapping — mens kiest"
    return None


def _weiger(*, administratie_id: uuid.UUID, document_id: uuid.UUID, reden: str) -> AutoboekBesluit:
    logger.info("Omzet-autoboeken geweigerd voor document %s: %s", document_id, reden)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="autoboeken_geweigerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": reden, "bron": BRON},
            administratie_id=administratie_id,
        )
    return AutoboekBesluit(geboekt=False, reden=reden)


def _alarm_half_geboekt(*, administratie_id: uuid.UUID, document_id: uuid.UUID, reden: str) -> None:
    """Zekerheid (c): een automatische poging die half geboekt eindigt is NOOIT stil — audit + alert via
    het bewakingskanaal (mail naar de alert-ontvanger); de omzet-reconciliatie blijft het herstelpad."""
    logger.error("Omzet-autoboeken HALF GEBOEKT voor document %s: %s", document_id, reden)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="autoboeken_half_geboekt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": reden, "bron": BRON},
            administratie_id=administratie_id,
        )
    from app.bewaking import service as bewaking

    bewaking._verzend_alert(  # noqa: SLF001 — bewust het bestaande alertkanaal (één afzender, één ontvanger)
        onderwerp=f"[RLZ] Omzet-autoboeken HALF GEBOEKT — document {document_id}",
        tekst=(
            "Een automatische omzetboeking eindigde half geboekt (verkoopfactuur staat in RLZ, kostprijs-"
            f"memoriaal en storno mislukten).\nAdministratie: {administratie_id}\nDocument: {document_id}\n"
            f"Reden: {reden}\n\nHerstel: `make omzet-reconciliatie` + het controlescherm (status boeken_mislukt)."
        ),
    )


def probeer_omzet_autoboeken_na_extractie(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> AutoboekBesluit | None:
    """Het omzet-autoboek-pad, aangeroepen ná de rapport-extractie (post-commit hook, vóór de
    mapping-autovraag — een weigering laat het document gewoon in de werkvoorraad, daarna stelt de
    autovraag zo nodig de mapping-vraag). Retourneert None wanneer autoboeken per definitie niet aan
    de orde is (geen kassarapport, geen kandidaat-status, opt-in uit — géén audit-ruis), anders een
    AutoboekBesluit (geboekt of geweigerd-met-reden, altijd geauditeerd)."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.KASSARAPPORT.value:
            return None
        if document.status != DocumentStatus.TE_CONTROLEREN:
            return None
        mogelijk_duplicaat = document.mogelijk_duplicaat_van_id is not None
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.omzet_autoboeken_ingeschakeld:
            return None

    # Vanaf hier is autoboeken expliciet aangezet — elke uitkomst wordt geauditeerd.
    if mogelijk_duplicaat:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="mogelijk-duplicaat-signaal op het document (zelfde bestandsinhoud) — mens beoordeelt",
        )
    voorstel = haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.opgeslagen:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="er is al een door een mens opgeslagen voorstel — automatisch boeken doet uitsluitend onaangeraakte rapporten",
        )
    if voorstel.periode_start is None or voorstel.periode_eind is None:
        return _weiger(
            administratie_id=administratie_id, document_id=document_id, reden="de extractie leverde geen volledige periode"
        )
    if voorstel.rapport_totaal_omzet is None:
        return _weiger(
            administratie_id=administratie_id, document_id=document_id, reden="de extractie leverde geen rapporttotaal omzet"
        )
    blokkade = _regels_geblokkeerd(voorstel)
    if blokkade is not None:
        return _weiger(administratie_id=administratie_id, document_id=document_id, reden=blokkade)

    try:
        boek_omzet_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            extra_overgang_detail={"automatisch_geboekt": True, "bron": BRON},
        )
    except BoekenGeblokkeerdDoorChecks as exc:
        geblokkeerd = [f"{r.naam}: {r.melding}" for r in exc.rapport.resultaten if not r.ok]
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="harde checks blokkeren — " + "; ".join(geblokkeerd),
        )
    except (BoekenUitgeschakeld, VolumeremBereikt, OngeldigeBoekpoging, GeenRlzCredentials) as exc:
        return _weiger(administratie_id=administratie_id, document_id=document_id, reden=str(exc))
    except HalfGeboekt as exc:
        _alarm_half_geboekt(administratie_id=administratie_id, document_id=document_id, reden=str(exc))
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden=f"HALF GEBOEKT tijdens autoboeken (alert verstuurd, document staat op boeken_mislukt): {exc}",
        )
    except RlzBoekingMislukt as exc:
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
                "periode_start": voorstel.periode_start.isoformat(),
                "periode_eind": voorstel.periode_eind.isoformat(),
                "totaal_omzet": str(voorstel.rapport_totaal_omzet),
                "bron": BRON,
            },
            administratie_id=administratie_id,
        )
    return AutoboekBesluit(geboekt=True, reden="automatisch geboekt (opt-in omzet-administratie)")
