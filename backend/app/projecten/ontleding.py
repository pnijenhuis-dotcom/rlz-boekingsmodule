"""Contract-/offerte-ontleding — voorstel + bevestigen per regel (mockup projecten-invoer.html,
akkoord Peter 22-08). De AI (app/extractie/contract.py) stelt VOOR; bevestigen is een
mens-klik per regel en schrijft pas dán, deterministisch, naar project_specificatie of
project_staffel — er wordt nooit iets automatisch overgenomen (mockup-keuze 1). Zonder AI
blijft alles handmatig invulbaar (de gewone schrijfpaden in app/projecten/kantoor.py).

Gates: de ontleding draait achter de bestaande per-administratie AVG-gate
`administratie.ai_extractie_ingeschakeld` (dezelfde gate als de factuur-extractie — een
projectcontract hoort bij een bekende administratie; de platform-brede intake-gate dekt
alleen nog-niet-toegewezen post) én de AI-kostengrens: de harde kostenpoort zit ín de
Claude-client (app/aikosten/), boven de limiet wordt de call niet gedaan en is dat een
zichtbare fout — nooit stil."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.storage import standaard_opslag
from app.extractie.contract import extraheer_contract
from app.projecten.kantoor import (
    OngeldigeInvoer,
    ProjectNietGevonden,
    _vereis_schrijfrol,
)
from app.projecten.models import OntledingRegelSoort, OntledingRegelStatus, ProjectOntledingRegel
from app.uren.models import MeerwerkEenheid, ProjectDocument, ProjectSpecificatie, ProjectStaffel

_EENHEDEN = tuple(e.value for e in MeerwerkEenheid)


class OntledingUitgeschakeld(Exception):
    """De per-administratie AVG-gate (ai_extractie_ingeschakeld) staat uit, of er is geen
    API-key — handmatig invullen blijft gewoon werken (mockup-notitie)."""


@dataclass(frozen=True)
class OntleedResultaat:
    project_document_id: uuid.UUID
    aantal_regels: int


def _laad_project_document(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, project_document_id: uuid.UUID
) -> ProjectDocument:
    document = session.get(ProjectDocument, project_document_id)
    if document is None or document.administratie_id != administratie_id or document.project_id != project_id:
        raise ProjectNietGevonden("Onbekend projectdocument")
    return document


def ontleed_document(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    project_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    extraheer=extraheer_contract,
) -> OntleedResultaat:
    """Draait de AI-ontleding en vervangt de nog ONBESLISTE voorstel-regels van dit document
    (besliste regels blijven als vastlegging staan). `extraheer` is de test-seam."""
    with scoped_session(administratie_id) as session:
        _vereis_schrijfrol(session, actor_id)
        document = _laad_project_document(
            session, administratie_id=administratie_id, project_id=project_id, project_document_id=project_document_id
        )
        opslag_pad = document.opslag_pad
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.ai_extractie_ingeschakeld:
            raise OntledingUitgeschakeld(
                "AI-extractie staat uit voor deze administratie (AVG-gate) — vul specs en staffels handmatig in"
            )
    if not settings.anthropic_api_key:
        raise OntledingUitgeschakeld("Geen Claude-API-key geconfigureerd — vul specs en staffels handmatig in")

    from app.aikosten.service import AiVerbruikReferentie

    inhoud = standaard_opslag().lezen(pad=opslag_pad)
    regels = extraheer(
        inhoud, verbruik_referentie=AiVerbruikReferentie(bron="contract_ontleding", document_id=project_document_id)
    )

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.execute(
            delete(ProjectOntledingRegel).where(
                ProjectOntledingRegel.administratie_id == administratie_id,
                ProjectOntledingRegel.project_document_id == project_document_id,
                ProjectOntledingRegel.status == OntledingRegelStatus.VOORSTEL.value,
            )
        )
        for regel in regels:
            waarde: dict = {}
            if regel.waarde is not None:
                waarde["waarde"] = regel.waarde
            if regel.eenheid is not None:
                waarde["eenheid"] = regel.eenheid
            if regel.van is not None:
                waarde["van"] = regel.van
            if regel.tot is not None:
                waarde["tot"] = regel.tot
            session.add(
                ProjectOntledingRegel(
                    administratie_id=administratie_id,
                    project_id=project_id,
                    project_document_id=project_document_id,
                    soort=regel.soort,
                    omschrijving=regel.omschrijving,
                    citaat=regel.citaat,
                    waarde=waarde or None,
                    zekerheid=Decimal(str(round(regel.zekerheid, 3))),
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_ontleding_regel",
            record_id=project_document_id,
            actie="contract_ontleed",
            correlatie_id=project_id,
            nieuwe_waarde={"aantal_regels": len(regels)},
            administratie_id=administratie_id,
        )
    return OntleedResultaat(project_document_id=project_document_id, aantal_regels=len(regels))


def _als_decimal(waarde: object) -> Decimal:
    try:
        return Decimal(str(waarde))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OngeldigeInvoer(f"Onbruikbare getalswaarde in het voorstel: {waarde!r}") from exc


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _zorg_voor_spec(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID
) -> ProjectSpecificatie:
    spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
    if spec is None:
        spec = ProjectSpecificatie(project_id=project_id, administratie_id=administratie_id, bijgewerkt_door=actor_id)
        session.add(spec)
    return spec


def beslis_regel(
    *,
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    actor_id: uuid.UUID,
    bevestigen: bool,
    eenheid: str | None = None,
    verrekenbaar: bool = True,
) -> None:
    """✓/✗ per voorstel-regel. Bevestigen schrijft deterministisch door: contract_m2/looptijd/
    huurtijd/doorlopende_huur/opdrachtgever/werknummer → project_specificatie; staffel →
    project_staffel-rij (de mens kiest de eenheid uit de vaste vier — de AI-eenheid is alleen
    het voorstel); boete → alleen vastgelegd (info/projectsignaal, geen spec-veld)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        regel = session.get(ProjectOntledingRegel, regel_id)
        if regel is None or regel.administratie_id != administratie_id:
            raise ProjectNietGevonden("Onbekende voorstel-regel")
        if regel.status != OntledingRegelStatus.VOORSTEL.value:
            raise OngeldigeInvoer("Deze regel is al beslist")

        if bevestigen:
            waarde = regel.waarde or {}
            if regel.soort == OntledingRegelSoort.STAFFEL.value:
                if eenheid not in _EENHEDEN:
                    raise OngeldigeInvoer(
                        f"Kies bij een staffel-regel de eenheid ({', '.join(_EENHEDEN)}) — de "
                        "AI-eenheid is alleen een voorstel"
                    )
                prijs = _als_decimal(waarde.get("waarde"))
                if prijs < 0:
                    raise OngeldigeInvoer("Staffelprijs kan niet negatief zijn")
                session.add(
                    ProjectStaffel(
                        administratie_id=administratie_id,
                        project_id=regel.project_id,
                        omschrijving=regel.omschrijving,
                        eenheid=eenheid,
                        prijs_per_eenheid=prijs,
                        verrekenbaar=verrekenbaar,
                        bron=regel.citaat or "contract-ontleding",
                        aangemaakt_door=actor_id,
                    )
                )
            elif regel.soort == OntledingRegelSoort.CONTRACT_M2.value:
                spec = _zorg_voor_spec(
                    session, administratie_id=administratie_id, project_id=regel.project_id, actor_id=actor_id
                )
                spec.contract_m2 = _als_decimal(waarde.get("waarde"))
                spec.bijgewerkt_door = actor_id
            elif regel.soort == OntledingRegelSoort.LOOPTIJD.value:
                spec = _zorg_voor_spec(
                    session, administratie_id=administratie_id, project_id=regel.project_id, actor_id=actor_id
                )
                van = _als_datum(waarde.get("van"))
                tot = _als_datum(waarde.get("tot"))
                if van is None and tot is None:
                    raise OngeldigeInvoer("Looptijd-voorstel zonder leesbare datums — vul handmatig in")
                if van is not None:
                    spec.looptijd_van = van
                if tot is not None:
                    spec.looptijd_tot = tot
                spec.bijgewerkt_door = actor_id
            elif regel.soort in (
                OntledingRegelSoort.HUURTIJD.value,
                OntledingRegelSoort.DOORLOPENDE_HUUR.value,
                OntledingRegelSoort.OPDRACHTGEVER.value,
                OntledingRegelSoort.WERKNUMMER.value,
            ):
                tekst = waarde.get("waarde")
                if not tekst:
                    raise OngeldigeInvoer("Voorstel zonder leesbare waarde — vul handmatig in")
                spec = _zorg_voor_spec(
                    session, administratie_id=administratie_id, project_id=regel.project_id, actor_id=actor_id
                )
                veld = {
                    OntledingRegelSoort.HUURTIJD.value: "huurtijd_omschrijving",
                    OntledingRegelSoort.DOORLOPENDE_HUUR.value: "doorlopende_huur_omschrijving",
                    OntledingRegelSoort.OPDRACHTGEVER.value: "opdrachtgever",
                    OntledingRegelSoort.WERKNUMMER.value: "werknummer_opdrachtgever",
                }[regel.soort]
                setattr(spec, veld, str(tekst))
                spec.bijgewerkt_door = actor_id
            # BOETE: alleen vastleggen (status bevestigd) — ter info, wordt projectsignaal.

        regel.status = (
            OntledingRegelStatus.BEVESTIGD.value if bevestigen else OntledingRegelStatus.AFGEWEZEN.value
        )
        regel.beslist_door = actor_id
        regel.beslist_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_ontleding_regel",
            record_id=regel_id,
            actie="ontleding_regel_bevestigd" if bevestigen else "ontleding_regel_afgewezen",
            correlatie_id=regel.project_id,
            nieuwe_waarde={"soort": regel.soort, "omschrijving": regel.omschrijving, "eenheid": eenheid},
            administratie_id=administratie_id,
        )


def open_voorstellen(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID
) -> list[ProjectOntledingRegel]:
    return list(
        session.scalars(
            select(ProjectOntledingRegel).where(
                ProjectOntledingRegel.administratie_id == administratie_id,
                ProjectOntledingRegel.project_id == project_id,
                ProjectOntledingRegel.status == OntledingRegelStatus.VOORSTEL.value,
            )
        )
    )
