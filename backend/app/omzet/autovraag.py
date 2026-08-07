"""Automatische mapping-vraag (omzetmodule): een kassarapport met categorieën zonder
GB/btw-mapping krijgt na de extractie automatisch een vraag via de bestaande vragenworkflow
("nieuwe categorie zónder mapping → regel blokkerend + automatische vraag", CLAUDE.md-
omzetbesluit). De vraag draagt de systeem-actor als steller en gaat naar de administratie-
eigenaar (de vragen-default). De blokkerende mapping-check op het reviewscherm blijft de harde
poort — deze vraag is de signalering eromheen, dus elke reden om 'm níét te stellen (geen
eigenaar, al een open vraag, status laat het niet toe) is een gelogde no-op, nooit een fout."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import vragen
from app.documenten.models import Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.omzet.mapping import actieve_mappings, normaliseer_categorie_sleutel

logger = logging.getLogger(__name__)


def onbekende_categorieen(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[str]:
    """Categorieën uit het laatste veldvoorstel van dit document zonder actieve mapping."""
    with scoped_session(administratie_id) as session:
        veldvoorstel = next(
            (
                g.detail["veldvoorstel"]
                for g in reversed(
                    list(
                        session.scalars(
                            select(DocumentGebeurtenis)
                            .where(DocumentGebeurtenis.document_id == document_id)
                            .order_by(DocumentGebeurtenis.tijdstip)
                        )
                    )
                )
                if g.detail and "veldvoorstel" in g.detail
            ),
            None,
        )
        if not veldvoorstel or veldvoorstel.get("soort") != "kassarapport":
            return []
        mappings = actieve_mappings(session, administratie_id=administratie_id)

    onbekend: list[str] = []
    for regel in veldvoorstel.get("regels") or []:
        categorie = regel.get("categorie")
        sleutel = normaliseer_categorie_sleutel(categorie)
        if sleutel is not None and sleutel not in mappings and categorie not in onbekend:
            onbekend.append(categorie)
    return onbekend


def stel_mapping_vraag_indien_nodig(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    """Stelt de automatische vraag als het document een kassarapport op te_controleren is mét
    onbekende categorieën. Retourneert of er een vraag gesteld is."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if (
            document is None
            or document.soort != DocumentSoort.KASSARAPPORT.value
            or document.status != DocumentStatus.TE_CONTROLEREN
        ):
            return False

    onbekend = onbekende_categorieen(administratie_id=administratie_id, document_id=document_id)
    if not onbekend:
        return False

    tekst = (
        "Nieuwe rapportcategorie(ën) zonder GB/btw-mapping: "
        + ", ".join(f"‘{c}’" for c in onbekend)
        + ". Stel op het omzetreview-scherm per categorie de omzet-grootboekrekening, btw-code en "
        "kostprijs-rekening in — de mapping wordt daarna onthouden voor volgende rapporten. "
        "Boeken is geblokkeerd tot elke categorie een mapping heeft."
    )
    try:
        vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            vraag_tekst=tekst,
        )
        return True
    except (vragen.ErIsAlEenOpenVraag, OngeldigeStatusovergang):
        # Race met een menselijke vraag of statuswijziging — de blokkerende check dekt het.
        return False
    except vragen.GeenToewijzingMogelijk:
        logger.warning(
            "Automatische mapping-vraag niet gesteld voor document %s: administratie %s heeft geen "
            "eigenaar — de blokkerende mapping-check blijft gelden",
            document_id,
            administratie_id,
        )
        return False
