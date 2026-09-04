"""API documenttype "verplichting" + factuur↔verplichting-match (wens Peter 04-09).

Router-breed `vereis_kantoorrol` (rollen-gate-lijn 21-08); per administratie-route bovendien
`vereis_administratie_scope`. Het accorderen zelf loopt via de BESTAANDE accordering-endpoints —
hier staan uitsluitend het reviewscherm (voorstel/checks/vervallen), de match (lezen/koppelen) en de
kantoorbrede Inzicht-lijst.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.documenten.checks import CheckResultaat
from app.documenten.service import DocumentNietGevonden
from app.verplichting import kantoorbreed, schemas, service

router = APIRouter(tags=["verplichting"], dependencies=[Depends(vereis_kantoorrol)])


def _check_dto(resultaat: CheckResultaat) -> schemas.CheckDto:
    """Vier standen op de rij (UX-norm "onzichtbaar tot relevant"): blokkerend (rood), signaal
    (oranje), niet_van_toepassing (grijs) of ok (groen)."""
    if not resultaat.ok:
        stand = "blokkerend"
    elif resultaat.signaal:
        stand = "signaal"
    elif "niet van toepassing" in resultaat.melding.lower():
        stand = "niet_van_toepassing"
    else:
        stand = "ok"
    return schemas.CheckDto(naam=resultaat.naam, status=stand, melding=resultaat.melding)


def _voorstel_dto(voorstel: service.VerplichtingVoorstel) -> schemas.VerplichtingVoorstelDto:
    return schemas.VerplichtingVoorstelDto(
        document_id=voorstel.document_id,
        status=voorstel.status,
        soort_label=voorstel.soort_label,
        vendor_id=voorstel.vendor_id,
        vendor_naam=voorstel.vendor_naam,
        project_id=voorstel.project_id,
        project_naam=voorstel.project_naam,
        offertenummer=voorstel.offertenummer,
        datum=voorstel.datum,
        totaalbedrag_excl=voorstel.totaalbedrag_excl,
        geldig_tot=voorstel.geldig_tot,
        omschrijving=voorstel.omschrijving,
        opgeslagen=voorstel.opgeslagen,
        herkomst=voorstel.herkomst,
        zekerheid=voorstel.zekerheid,
        zekerheid_drempel=voorstel.zekerheid_drempel,
        vendor_suggestie=(
            schemas.SuggestieDto(
                vendor_id=voorstel.vendor_suggestie.id,
                naam=voorstel.vendor_suggestie.naam,
                match=voorstel.vendor_suggestie.match,
            )
            if voorstel.vendor_suggestie
            else None
        ),
        project_suggestie=(
            schemas.SuggestieDto(
                project_id=voorstel.project_suggestie.id,
                naam=voorstel.project_suggestie.naam,
                match=voorstel.project_suggestie.match,
            )
            if voorstel.project_suggestie
            else None
        ),
        goedgekeurd=(
            schemas.GoedgekeurdDto(**voorstel.goedgekeurd.__dict__) if voorstel.goedgekeurd else None
        ),
        verbruik=schemas.VerbruikDto(**voorstel.verbruik.__dict__) if voorstel.verbruik else None,
        vervallen=schemas.VervallenDto(**voorstel.vervallen.__dict__) if voorstel.vervallen else None,
        gekoppelde_facturen=[
            schemas.GekoppeldeFactuurDto(**f.__dict__) for f in voorstel.gekoppelde_facturen
        ],
        checks=[_check_dto(c) for c in voorstel.checks],
        ai_overgeslagen_reden=voorstel.ai_overgeslagen_reden,
    )


def _vertaal(exc: service.VerplichtingFout) -> HTTPException:
    if isinstance(exc, service.OngeldigeInvoer):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# --- reviewscherm ---------------------------------------------------------------------------------


@router.get(
    "/administraties/{administratie_id}/verplichtingen/documenten/{document_id}/voorstel",
    response_model=schemas.VerplichtingVoorstelDto,
)
def voorstel_ophalen(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.VerplichtingVoorstelDto:
    try:
        return _voorstel_dto(service.haal_voorstel_op(administratie_id=administratie_id, document_id=document_id))
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.VerplichtingFout as exc:
        raise _vertaal(exc) from exc


@router.put(
    "/administraties/{administratie_id}/verplichtingen/documenten/{document_id}/voorstel",
    response_model=schemas.VerplichtingVoorstelDto,
)
def voorstel_opslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.VerplichtingVoorstelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerplichtingVoorstelDto:
    """De mens slaat de gecontroleerde kopvelden op; de documentstatus blijft ongewijzigd (de weg
    naar de klant is de bestaande "Ter accordering"-route)."""
    try:
        voorstel = service.sla_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            soort_label=invoer.soort_label,
            vendor_id=invoer.vendor_id,
            project_id=invoer.project_id,
            offertenummer=invoer.offertenummer,
            datum=invoer.datum,
            totaalbedrag_excl=invoer.totaalbedrag_excl,
            geldig_tot=invoer.geldig_tot,
            omschrijving=invoer.omschrijving,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.VerplichtingFout as exc:
        raise _vertaal(exc) from exc
    return _voorstel_dto(voorstel)


@router.post(
    "/administraties/{administratie_id}/verplichtingen/documenten/{document_id}/checks",
    response_model=schemas.ChecksDto,
)
def checks_draaien(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ChecksDto:
    try:
        rapport = service.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.VerplichtingFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ChecksDto(
        checks=[_check_dto(r) for r in rapport.resultaten], geblokkeerd=rapport.geblokkeerd
    )


@router.post(
    "/administraties/{administratie_id}/verplichtingen/documenten/{document_id}/vervallen",
    response_model=schemas.VerplichtingVoorstelDto,
)
def verplichting_laten_vervallen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.VervallenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerplichtingVoorstelDto:
    """⑥: vervallen stopt nieuwe matches; al gematchte/verrekende facturen blijven ongemoeid. Het
    document blijft geaccordeerd (bewaarplicht) — verplichte reden, tijdlijn + audit."""
    try:
        voorstel = service.laat_vervallen(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id, reden=invoer.reden
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.VerplichtingFout as exc:
        raise _vertaal(exc) from exc
    return _voorstel_dto(voorstel)


# --- match op het inkoop-controlescherm -----------------------------------------------------------


def _match_dto(data: service.MatchData) -> schemas.VerplichtingMatchDto:
    return schemas.VerplichtingMatchDto(
        document_id=data.document_id,
        uitkomst=data.uitkomst,
        verplichting=(
            schemas.MatchVerplichtingDto(**data.verplichting.__dict__) if data.verplichting else None
        ),
        bedrag_excl=data.bedrag_excl,
        verbruik_voor=data.verbruik_voor,
        verbruik_na=data.verbruik_na,
        percentage_na=data.percentage_na,
        overschrijding_excl=data.overschrijding_excl,
        handmatig_gekoppeld=data.handmatig_gekoppeld,
        kandidaten=[schemas.MatchKandidaatDto(**k.__dict__) for k in data.kandidaten],
        berekend_op=data.berekend_op,
        melding=data.melding,
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/verplichting-match",
    response_model=schemas.VerplichtingMatchDto,
)
def match_ophalen(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.VerplichtingMatchDto:
    try:
        return _match_dto(service.haal_match_op(administratie_id=administratie_id, document_id=document_id))
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/verplichting-match/koppel",
    response_model=schemas.VerplichtingMatchDto,
)
def match_koppelen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.KoppelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerplichtingMatchDto:
    """ "Koppel offerte…" (②) — `verplichting_document_id: null` ontkoppelt. Een niet-lopende
    verplichting is een 409 mét uitleg."""
    try:
        data = service.koppel_verplichting(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            verplichting_document_id=invoer.verplichting_document_id,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.VerplichtingFout as exc:
        raise _vertaal(exc) from exc
    return _match_dto(data)


# --- kantoorbreed (Inzicht › Verplichtingen, ⑦) ---------------------------------------------------


@router.get("/verplichtingen", response_model=schemas.VerplichtingKantoorLijstDto)
def verplichtingen_kantoorbreed(
    pagina: int = Query(1, ge=1),
    q: str = Query(""),
    administratie_id: uuid.UUID | None = Query(None),
    status_facet: str = Query("lopend", alias="status"),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.VerplichtingKantoorLijstDto:
    """Alle goedgekeurde verplichtingen over de administraties in scope, urgentste bovenaan
    (overschreden eerst); status = facet-filter (lopend | overschreden | vervallen | alle),
    administratie = facet, q = leverancier/offertenummer/project; paginering 25."""
    try:
        lijst = kantoorbreed.lijst(
            actor_id=actor.id, rol=actor.rol, pagina=pagina, q=q, administratie_id=administratie_id, status=status_facet
        )
    except service.VerplichtingFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return schemas.VerplichtingKantoorLijstDto(
        rijen=[
            schemas.KantoorRijDto(
                **{
                    **r.__dict__,
                    "facturen": [schemas.KantoorFactuurDto(**f.__dict__) for f in r.facturen],
                }
            )
            for r in lijst.rijen
        ],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        administraties_in_selectie=lijst.administraties_in_selectie,
        tellers=schemas.KantoorTellersDto(**lijst.tellers.__dict__),
        facetten=schemas.KantoorFacettenDto(
            status=lijst.facetten.status,
            administraties=[schemas.AdministratieFacetDto(**f.__dict__) for f in lijst.facetten.administraties],
        ),
    )
