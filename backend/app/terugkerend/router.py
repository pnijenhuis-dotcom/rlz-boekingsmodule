"""Terugkerende-facturen-signaal (blok B 30-08): lezen = kantoorrol + administratie-scope, snooze/afmelden
= kantoorrol + scope (menskeuze mét audit, geen boeking), drempel = Beheerder-only. Alleen signaleren."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.terugkerend import schemas, service

router = APIRouter(tags=["terugkerend"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: service.TerugkerendFout) -> HTTPException:
    if "Onbekende administratie" in str(exc) or "Geen terugkerend patroon" in str(exc):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _dto(s: service.SignaalData) -> schemas.TerugkerendSignaalDto:
    return schemas.TerugkerendSignaalDto(**s.__dict__)


@router.get("/administraties/{administratie_id}/terugkerend", response_model=schemas.TerugkerendOverzichtDto)
def terugkerend_overzicht(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TerugkerendOverzichtDto:
    """Signaal-overzicht per administratie (ontbrekend eerst, dan prijsstijgingen)."""
    try:
        drempel = service.haal_drempel_op(administratie_id=administratie_id)
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    return schemas.TerugkerendOverzichtDto(
        administratie_id=administratie_id,
        prijsstijging_drempel_pct=drempel,
        signalen=[_dto(s) for s in service.overzicht(administratie_id=administratie_id)],
    )


@router.post("/administraties/{administratie_id}/terugkerend/herbereken", response_model=schemas.HerberekenResultaatDto)
def terugkerend_herberekenen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.HerberekenResultaatDto:
    """Op verzoek herberekenen (de dagelijkse sync-alles doet dit óók) — puur code, geen RLZ-calls."""
    return schemas.HerberekenResultaatDto(**service.herbereken_administratie(administratie_id=administratie_id))


@router.post(
    "/administraties/{administratie_id}/terugkerend/{vendor_id}/snooze", status_code=status.HTTP_204_NO_CONTENT
)
def terugkerend_snooze(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.SnoozeDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        service.snooze(administratie_id=administratie_id, vendor_id=vendor_id, tot=invoer.tot, actor_id=actor.id)
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc


@router.post(
    "/administraties/{administratie_id}/terugkerend/{vendor_id}/afmelden", status_code=status.HTTP_204_NO_CONTENT
)
def terugkerend_afmelden(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.AfmeldenDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        service.zet_afgemeld(
            administratie_id=administratie_id, vendor_id=vendor_id, afgemeld=invoer.afgemeld, actor_id=actor.id
        )
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc


@router.put("/administraties/{administratie_id}/terugkerend-instelling", response_model=schemas.DrempelResultaatDto)
def terugkerend_drempel_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.DrempelDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.DrempelResultaatDto:
    """Drempel prijsstijging (%) per administratie — Beheerder-only, default 10, audit oud→nieuw."""
    try:
        waarde = service.zet_drempel(
            administratie_id=administratie_id, prijsstijging_pct=invoer.prijsstijging_pct, actor_id=actor.id
        )
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    return schemas.DrempelResultaatDto(prijsstijging_pct=waarde)


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/terugkerend-signaal",
    response_model=schemas.DocumentTerugkerendSignaalDto,
)
def document_terugkerend_signaal(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentTerugkerendSignaalDto:
    """Prijsstijging-chip voor het controlescherm (aanbetaling-signaal-patroon): alleen als dít
    document de laatste factuur van een terugkerende leverancier is én boven de drempel ligt."""
    s = service.signaal_voor_document(administratie_id=administratie_id, document_id=document_id)
    if s is None:
        return schemas.DocumentTerugkerendSignaalDto()
    return schemas.DocumentTerugkerendSignaalDto(**s.__dict__)


# --- kantoorbreed (design-ronde 03-09 blok B1; mockup inzicht-kantoorbreed ①②③⑨) -----------------
# Eén endpoint zónder administratie in het pad; scope = mijn_administraties van de actor, per
# administratie gelezen onder RLS (kantoorbreed.py). De per-administratie-routes hierboven blijven
# bestaan voor de klantpagina-deeplinks (⑨).


@router.get("/terugkerend/signalen", response_model=schemas.KantoorLijstDto)
def terugkerend_signalen_kantoorbreed(
    pagina: int = Query(1, ge=1),
    q: str = Query(""),
    administratie_id: uuid.UUID | None = Query(None),
    status_facet: str = Query("aandacht", alias="status"),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.KantoorLijstDto:
    """Alle signalen ("ontbreekt" + "prijsstijging") over de administraties in scope, urgentste
    bovenaan; status = facet-filter (aandacht | gesnoozed | afgemeld | alle), administratie = facet,
    q = leverancier; paginering 25."""
    from app.terugkerend import kantoorbreed

    try:
        lijst = kantoorbreed.lijst(
            actor_id=actor.id, rol=actor.rol, pagina=pagina, q=q, administratie_id=administratie_id, status=status_facet
        )
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    return schemas.KantoorLijstDto(
        rijen=[schemas.KantoorRijDto(**r.__dict__) for r in lijst.rijen],
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


def _run_dto(info) -> schemas.HerberekenRunDto:
    return schemas.HerberekenRunDto(**info.__dict__)


@router.post("/terugkerend/herbereken", response_model=schemas.HerberekenRunDto, status_code=status.HTTP_202_ACCEPTED)
def terugkerend_herbereken_alles(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.HerberekenRunDto:
    """"⟳ Herbereken alles" (③): één kantoorbrede achtergrondrun over álle actieve administraties —
    202 + run-id, status via GET /terugkerend/herbereken/{run_id}. Een lopende run wordt hergebruikt."""
    from app.terugkerend import herbereken_run

    try:
        return _run_dto(herbereken_run.start_run(actor_id=actor.id))
    except herbereken_run.HerberekenStartFout as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/terugkerend/herbereken/laatste", response_model=schemas.HerberekenRunDto | None)
def terugkerend_herbereken_laatste(
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.HerberekenRunDto | None:
    """Jongste run (voor "stand van …" bij binnenkomst); null als er nog nooit een run was."""
    from app.terugkerend import herbereken_run

    info = herbereken_run.laatste_run()
    return _run_dto(info) if info is not None else None


@router.get("/terugkerend/herbereken/{run_id}", response_model=schemas.HerberekenRunDto)
def terugkerend_herbereken_status(
    run_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.HerberekenRunDto:
    from app.terugkerend import herbereken_run

    try:
        return _run_dto(herbereken_run.status_van(run_id))
    except herbereken_run.HerberekenRunNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/terugkerend/{administratie_id}/{vendor_id}/conceptmail", response_model=schemas.ConceptMailDto)
def terugkerend_conceptmail(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ConceptMailDto:
    """"Navragen bij leverancier…" (②): deterministisch CONCEPT (geen AI) — genereren is lezen, er
    wordt niets verzonden of vastgelegd; de mens bewerkt en verstuurt expliciet (POST …/versturen)."""
    from app.terugkerend import kantoorbreed

    try:
        c = kantoorbreed.bouw_conceptmail(administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor.id)
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ConceptMailDto(**c.__dict__)


@router.post(
    "/terugkerend/{administratie_id}/{vendor_id}/conceptmail/versturen", response_model=schemas.ConceptMailVerzondenDto
)
def terugkerend_conceptmail_versturen(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.ConceptMailVersturenDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ConceptMailVerzondenDto:
    """Verzend de door de mens gereviewde navraag — nooit automatisch. Fail-zichtbaar: mailkanaal
    niet geconfigureerd = 503, verzendfout = 424 (factuurmatch-mail-afweging); geslaagd = audit."""
    from app.berichten.mail import MailNietGeconfigureerd, MailVerzendFout
    from app.terugkerend import kantoorbreed

    try:
        naar = kantoorbreed.verstuur_conceptmail(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            actor_id=actor.id,
            naar=invoer.naar,
            onderwerp=invoer.onderwerp,
            tekst=invoer.tekst,
        )
    except service.TerugkerendFout as exc:
        raise _vertaal(exc) from exc
    except MailNietGeconfigureerd as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except MailVerzendFout as exc:
        raise HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc)) from exc
    return schemas.ConceptMailVerzondenDto(verzonden_aan=naar)
