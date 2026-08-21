from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import CurrentGebruiker, get_current_gebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.zoeken import service

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["zoeken"], dependencies=[Depends(vereis_kantoorrol)])


class VraagHitDto(BaseModel):
    vraag_tekst: str
    antwoord_tekst: str | None
    status: str


class AccorderingHitDto(BaseModel):
    volgnummer: int
    accordeur_naam: str | None
    besluit: str | None
    besluit_bron: str | None
    besloten_op: datetime | None


class DocumentHitDto(BaseModel):
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    soort: str
    status: str
    bestandsnaam: str
    leverancier: str | None
    referentie: str | None
    rlz_boekstuknummer: str | None
    totaalbedrag: Decimal | None
    factuurdatum: date | None
    aangemaakt_op: datetime
    automatisch_geboekt: bool
    vragen: list[VraagHitDto]
    accordering: list[AccorderingHitDto]


class AuditHitDto(BaseModel):
    tijdstip: datetime
    actor_naam: str | None
    actie: str
    administratie_naam: str
    detail: dict | None


class AdministratieHitDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str


class ZoekResponse(BaseModel):
    term: str
    administraties: list[AdministratieHitDto]
    documenten: list[DocumentHitDto]
    audit: list[AuditHitDto]


class ArchiefDocumentDto(BaseModel):
    document_id: uuid.UUID
    soort: str
    bestandsnaam: str
    leverancier: str | None
    referentie: str | None
    rlz_boekstuknummer: str | None
    totaalbedrag: Decimal | None
    factuurdatum: date | None
    geboekt_op: datetime | None
    automatisch_geboekt: bool


class ArchiefResponse(BaseModel):
    documenten: list[ArchiefDocumentDto]


@router.get("/zoeken", response_model=ZoekResponse)
def globaal_zoeken(
    term: str = "",
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> ZoekResponse:
    """Globaal zoeken over alle administraties in de scope van de gebruiker (RLS +
    server-side per administratie — mockup #zoeken)."""
    resultaat = service.zoek(actor_id=actor.id, rol=actor.rol, term=term)
    return ZoekResponse(
        term=resultaat.term,
        administraties=[AdministratieHitDto(**vars(hit)) for hit in resultaat.administraties],
        documenten=[
            DocumentHitDto(
                document_id=hit.document_id,
                administratie_id=hit.administratie_id,
                administratie_naam=hit.administratie_naam,
                soort=hit.soort,
                status=hit.status,
                bestandsnaam=hit.bestandsnaam,
                leverancier=hit.leverancier,
                referentie=hit.referentie,
                rlz_boekstuknummer=hit.rlz_boekstuknummer,
                totaalbedrag=hit.totaalbedrag,
                factuurdatum=hit.factuurdatum,
                aangemaakt_op=hit.aangemaakt_op,
                automatisch_geboekt=hit.automatisch_geboekt,
                vragen=[VraagHitDto(**vars(v)) for v in hit.vragen],
                accordering=[AccorderingHitDto(**vars(a)) for a in hit.accordering],
            )
            for hit in resultaat.documenten
        ],
        audit=[AuditHitDto(**vars(hit)) for hit in resultaat.audit],
    )


@router.get("/administraties/{administratie_id}/archief", response_model=ArchiefResponse)
def archief_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> ArchiefResponse:
    """Geboekte documenten van één administratie (bewaarplicht 7 jaar), mét kopgegevens en
    RLZ-boekstuknummer; de PDF/UBL via het bestaande bestand-endpoint."""
    return ArchiefResponse(
        documenten=[ArchiefDocumentDto(**vars(rij)) for rij in service.archief(administratie_id=administratie_id)]
    )
