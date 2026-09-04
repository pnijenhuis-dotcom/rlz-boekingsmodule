"""API projectverdeling (blok C 04-09). Router-breed `vereis_kantoorrol` (rollen-gate-lijn 21-08); per
administratie-route bovendien `vereis_administratie_scope`; instellingen Beheerder-only."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.documenten import tegenboeken
from app.documenten.service import DocumentNietGevonden
from app.projectverdeling import data as pv
from app.projectverdeling import schemas, service

router = APIRouter(tags=["projectverdeling"], dependencies=[Depends(vereis_kantoorrol)])


def _deel(d: pv.VerdeelDeel) -> schemas.VerdeelDeelDto:
    return schemas.VerdeelDeelDto(
        project_id=d.project_id,
        project_naam=d.project_naam,
        wijze=d.wijze,
        bedrag=d.bedrag,
        aandeel=d.aandeel,
        omzet=d.omzet,
    )


def naar_dto(
    document_id: uuid.UUID, data: pv.ProjectverdelingData | None, *, beschikbaar: bool = True
) -> schemas.ProjectverdelingDto:
    if data is None:
        return schemas.ProjectverdelingDto(
            document_id=document_id, status="geen", opgeslagen=False, beschikbaar=beschikbaar
        )
    return schemas.ProjectverdelingDto(
        document_id=document_id,
        status=data.status,
        opgeslagen=data.opgeslagen,
        prefill=data.prefill,
        beschikbaar=beschikbaar,
        basisbedrag=data.basisbedrag,
        vaste_regels=[
            schemas.VasteRegelDto(project_id=r.project_id, bedrag=r.bedrag, hint=r.hint, project_naam=r.project_naam)
            for r in data.vaste_regels
        ],
        pro_rato=data.pro_rato,
        pro_rato_periode=data.pro_rato_periode,
        pro_rato_periode_label=pv.periode_label(data.pro_rato_periode) if data.pro_rato_periode else None,
        pro_rato_bedrag=data.pro_rato_bedrag,
        delen=[_deel(d) for d in data.delen],
        omzetstanden=[
            schemas.OmzetstandDto(project_id=s.project_id, project_naam=s.project_naam, omzet=s.omzet)
            for s in data.omzetstanden
        ],
        aantal_projecten_met_omzet=data.aantal_projecten_met_omzet,
        omzet_cache_leeg=data.omzet_cache_leeg,
        compleet=data.compleet,
        blokkade=data.blokkade,
        boek_cyclus=data.boek_cyclus,
        hercontrole=(
            schemas.HercontroleDto(
                op=data.hercontrole.op,  # type: ignore[arg-type]
                afwijking_pct=data.hercontrole.afwijking_pct,
                drempel_pct=data.hercontrole.drempel_pct,
                periode=data.hercontrole.periode,
                signaal=data.hercontrole.signaal,
                nieuwe_verdeling=[_deel(d) for d in data.hercontrole.nieuwe_verdeling],
            )
            if data.hercontrole
            else None
        ),
    )


def _lees(administratie_id: uuid.UUID, document_id: uuid.UUID) -> schemas.ProjectverdelingDto:
    from app.documenten.boekvoorstel import haal_boekvoorstel_op

    try:
        voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # B1/B2 (04-09): 'geen' + beschikbaar=True = leeg maar bruikbaar blok (opt-in = alleen prefill).
    return naar_dto(
        document_id, voorstel.projectverdeling, beschikbaar=service.is_beschikbaar(administratie_id=administratie_id)
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/projectverdeling",
    response_model=schemas.ProjectverdelingDto,
)
def projectverdeling_ophalen(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ProjectverdelingDto:
    return _lees(administratie_id, document_id)


@router.put(
    "/administraties/{administratie_id}/documenten/{document_id}/projectverdeling",
    response_model=schemas.ProjectverdelingDto,
)
def projectverdeling_opslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.ProjectverdelingInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProjectverdelingDto:
    try:
        data = service.sla_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            vaste_regels=[
                pv.VasteRegel(project_id=r.project_id, bedrag=r.bedrag, hint=r.hint) for r in invoer.vaste_regels
            ],
            pro_rato_periode=invoer.pro_rato_periode,
            vervallen=invoer.vervallen,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ProjectverdelingServiceFout as exc:
        code = status.HTTP_409_CONFLICT if "bevroren" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return naar_dto(document_id, data)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/projectverdeling/herverdelen",
    response_model=schemas.HerverdeelResultaatDto,
)
def projectverdeling_herverdelen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.HerverdelenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.HerverdeelResultaatDto:
    """ "Herverdelen…" (⑥): tegenboeken-én-opnieuw-boeken mét de nieuwe verdeling als voorstel — de mens bevestigt
    hier én boekt daarna opnieuw; aangifte-poort onverkort (kan tegenboeken niet → leesbare 409)."""
    try:
        resultaat = service.herverdelen(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id, reden=invoer.reden
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.HerverdelenGeblokkeerd as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.ProjectverdelingServiceFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except tegenboeken.TegenboekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tegenboeken geblokkeerd door harde checks: "
            + "; ".join(f"{r.naam}: {r.melding}" for r in exc.rapport.resultaten if not r.ok),
        ) from exc
    except tegenboeken.RlzTegenboekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.HerverdeelResultaatDto(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        rlz_tegenboeking_id=resultaat.rlz_tegenboeking_id,
        rlz_boekstuknummer=resultaat.rlz_boekstuknummer,
    )


# --- per-leverancier-opt-in (④, Beheerder) -------------------------------------------------------------------


@router.get(
    "/administraties/{administratie_id}/leveranciers-projectverdeling",
    response_model=schemas.LeverancierProRatoLijstDto,
)
def leveranciers_pro_rato_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.LeverancierProRatoLijstDto:
    return schemas.LeverancierProRatoLijstDto(
        leveranciers=[
            schemas.LeverancierProRatoDto(
                vendor_id=r.vendor_id, naam=r.naam, projectverdeling_pro_rato=r.projectverdeling_pro_rato
            )
            for r in service.lijst_leverancier_pro_rato(administratie_id=administratie_id)
        ]
    )


@router.put(
    "/administraties/{administratie_id}/leveranciers/{vendor_id}/projectverdeling-instelling",
    response_model=schemas.LeverancierProRatoDto,
)
def leverancier_pro_rato_zetten(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.LeverancierProRatoInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.LeverancierProRatoDto:
    ingeschakeld = service.zet_leverancier_pro_rato(
        administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor.id, ingeschakeld=invoer.ingeschakeld
    )
    naam = next(
        (
            r.naam
            for r in service.lijst_leverancier_pro_rato(administratie_id=administratie_id)
            if r.vendor_id == vendor_id
        ),
        None,
    )
    return schemas.LeverancierProRatoDto(vendor_id=vendor_id, naam=naam, projectverdeling_pro_rato=ingeschakeld)


# --- Beheerder-instellingen -------------------------------------------------------------------------------------


@router.get("/administraties/{administratie_id}/projectverdeling-instellingen", response_model=schemas.InstellingenDto)
def instellingen_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingenDto:
    try:
        stand = service.haal_instellingen(administratie_id=administratie_id)
    except service.ProjectverdelingServiceFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.InstellingenDto(drempel_pct=stand.drempel_pct, wachtweken=stand.wachtweken)


@router.put("/administraties/{administratie_id}/projectverdeling-instellingen", response_model=schemas.InstellingenDto)
def instellingen_zetten(
    administratie_id: uuid.UUID, invoer: schemas.InstellingenInput, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingenDto:
    try:
        stand = service.zet_instellingen(
            administratie_id=administratie_id,
            actor_id=actor.id,
            drempel_pct=Decimal(invoer.drempel_pct) if invoer.drempel_pct is not None else None,
            wachtweken=invoer.wachtweken,
        )
    except service.ProjectverdelingServiceFout as exc:
        code = status.HTTP_404_NOT_FOUND if "Onbekende" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return schemas.InstellingenDto(drempel_pct=stand.drempel_pct, wachtweken=stand.wachtweken)


# --- kantoorbreed (principe 7 regel 1) -----------------------------------------------------------------------------


@router.get("/projectverdeling/hercontrole-signalen", response_model=schemas.SignaalLijstDto)
def hercontrole_signalen_kantoorbreed(
    pagina: int = Query(1, ge=1), actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.SignaalLijstDto:
    lijst = service.hercontrole_signalen(actor_id=actor.id, rol=actor.rol, pagina=pagina)
    return schemas.SignaalLijstDto(
        rijen=[schemas.SignaalRijDto(**r.__dict__) for r in lijst.rijen],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        administraties=lijst.administraties,
    )
