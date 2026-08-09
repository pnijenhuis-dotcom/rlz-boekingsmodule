"""Automatische vraag bij een onbekende AccountingCost-code (§2d-GB-uitbreiding v1.10:
"onbekende code = blokkerende check + vraag, nooit stil een andere rekening kiezen") — zelfde
patroon als de omzet-mappingvraag (app/omzet/autovraag.py): systeem-actor, bestaande
vragenworkflow, en alle nee-redenen zijn no-ops — de blokkerende GB-code-check op het
reviewscherm blijft de harde poort, de vraag is de signalering eromheen."""

from __future__ import annotations

import logging
import uuid

from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import vragen
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.verkoop.voorstel import GeenVerkoopfactuur, haal_verkoop_voorstel_op

logger = logging.getLogger(__name__)


def onbekende_gb_codes(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[str]:
    try:
        voorstel = haal_verkoop_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except GeenVerkoopfactuur:
        return []
    codes = sorted({r.gb_code for r in voorstel.regels if r.gb_code_status == "onbekend" and r.gb_code})
    return codes


def stel_gb_code_vraag_indien_nodig(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    """Ná de extractie van een verkoopfactuur: draagt de UBL een GB-code die niet in het
    rekeningschema van deze administratie bestaat, stel dan automatisch een vraag aan de
    eigenaar. Retourneert True als er een vraag gesteld is."""
    codes = onbekende_gb_codes(administratie_id=administratie_id, document_id=document_id)
    if not codes:
        return False
    tekst = (
        "Vastly-verkoopfactuur draagt grootboekcode(s) die niet in het rekeningschema van deze "
        f"administratie bestaan: {', '.join(codes)}. Controleer de GB-mapping aan de Vastly-kant "
        "of kies handmatig de juiste rekening op het reviewscherm — de boeking blijft geblokkeerd "
        "tot dit is opgelost (koppelcontract §2d)."
    )
    try:
        vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            vraag_tekst=tekst,
        )
    except (vragen.ErIsAlEenOpenVraag, OngeldigeStatusovergang):
        return False
    except vragen.GeenToewijzingMogelijk:
        logger.warning(
            "GB-code-vraag voor verkoopdocument %s kon niet toegewezen worden (geen eigenaar) — "
            "de blokkerende check blijft de poort",
            document_id,
        )
        return False
    return True
