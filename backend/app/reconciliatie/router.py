"""Inzicht › Reconciliatie (opdracht 06-09 blok C): kantoorbrede lijst + KPI-stand voor élke kantoorrol
binnen scope (RLS), handelingen per rij (accepteren/intrekken = Beheerder via de bestaande schrijver;
gezien = kantoorrol binnen scope), "Nu draaien" (Beheerder, 202 + status-poll) en de Beheerder-instelling
`gezien_dagen`. Router-breed `vereis_kantoorrol` (rollen-gate-fix 21-08)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_kantoorrol
from app.reconciliatie import kantoorbreed, schemas
from app.reconciliatie import run as run_service

router = APIRouter(tags=["reconciliatie"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: kantoorbreed.ReconciliatieFout) -> HTTPException:
    tekst = str(exc)
    if "niet gevonden" in tekst or "Geen actieve" in tekst:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=tekst)
    if "Geen toegang" in tekst or "Alleen een Beheerder" in tekst:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=tekst)
    if "al geaccepteerd" in tekst:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=tekst)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=tekst)


def _run_dto(info: run_service.RunInfo | None) -> schemas.ReconciliatieRunDto | None:
    return schemas.ReconciliatieRunDto(**run_service.als_dict(info)) if info is not None else None


def _rij_dto(r: kantoorbreed.Rij) -> schemas.BevindingDto:
    return schemas.BevindingDto(
        id=r.id,
        run_id=r.run_id,
        blok=r.blok,
        soort=r.soort,
        administratie_id=r.administratie_id,
        administratie_naam=r.administratie_naam,
        vingerafdruk=r.vingerafdruk,
        tekst=r.tekst,
        titel=r.titel,
        wat=r.wat,
        doe=r.doe,
        details=[schemas.DetailRegelDto(label=label, waarde=waarde) for label, waarde in r.details],
        sinds=r.sinds,
        nieuw=r.nieuw,
        acceptatie=schemas.AcceptatieWeergaveDto(**r.acceptatie.__dict__) if r.acceptatie else None,
        gezien=schemas.GezienWeergaveDto(**r.gezien.__dict__) if r.gezien else None,
        detail=r.detail,
        doel_pad=r.doel_pad,
    )


@router.get("/reconciliatie/stand", response_model=schemas.StandDto)
def reconciliatie_stand(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.StandDto:
    """KPI-kaart "Reconciliatie" op de werkvoorraad (alleen getoond bij teller > 0)."""
    s = kantoorbreed.stand(actor_id=actor.id, rol=actor.rol)
    return schemas.StandDto(
        teller=s.teller,
        afwijkingen=s.afwijkingen,
        let_op=s.let_op,
        fouten=s.fouten,
        laatste_run=_run_dto(s.laatste_run),
    )


@router.get("/reconciliatie/bevindingen", response_model=schemas.BevindingenLijstDto)
def reconciliatie_bevindingen(
    pagina: int = Query(1, ge=1),
    q: str = Query(""),
    administratie_id: uuid.UUID | None = Query(None),
    soort: str = Query("aandacht"),
    groep_id: uuid.UUID | None = Query(None),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.BevindingenLijstDto:
    """Bevindingen van de laatste afgeronde run over de administraties in scope, urgentste bovenaan;
    soort = facet (aandacht | afwijking | let_op | fout | geaccepteerd | uitgesloten | gezien | alle),
    administratie = facet, groep = facet (blok 8 run 11-09), q = tekst/administratie; paginering 25."""
    try:
        lijst = kantoorbreed.lijst(
            actor_id=actor.id,
            rol=actor.rol,
            pagina=pagina,
            q=q,
            administratie_id=administratie_id,
            soort=soort,
            groep_id=groep_id,
        )
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc
    return schemas.BevindingenLijstDto(
        rijen=[_rij_dto(r) for r in lijst.rijen],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        administraties_in_selectie=lijst.administraties_in_selectie,
        tellers=schemas.TellersDto(**lijst.tellers.__dict__),
        facetten=schemas.FacettenDto(
            soort=lijst.facetten_soort,
            administraties=[schemas.AdministratieFacetDto(**f.__dict__) for f in lijst.facetten_administraties],
        ),
        laatste_run=_run_dto(lijst.laatste_run),
    )


@router.post("/reconciliatie/bevindingen/{bevinding_id}/accepteren", response_model=schemas.ActieResultaatDto)
def bevinding_accepteren(
    bevinding_id: uuid.UUID, invoer: schemas.RedenInvoerDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.ActieResultaatDto:
    """ "Accepteren…" = de bestaande `reconciliatie-accepteer`-schrijver (Beheerder, verplichte reden, audit)."""
    try:
        acceptatie_id = kantoorbreed.accepteer(
            bevinding_id=bevinding_id,
            administratie_id=invoer.administratie_id,
            reden=invoer.reden,
            actor_id=actor.id,
            rol=actor.rol,
        )
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ActieResultaatDto(id=acceptatie_id)


@router.post("/reconciliatie/bevindingen/{bevinding_id}/intrekken", response_model=schemas.ActieResultaatDto)
def bevinding_acceptatie_intrekken(
    bevinding_id: uuid.UUID, invoer: schemas.RedenInvoerDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.ActieResultaatDto:
    try:
        acceptatie_id = kantoorbreed.trek_acceptatie_in(
            bevinding_id=bevinding_id,
            administratie_id=invoer.administratie_id,
            reden=invoer.reden,
            actor_id=actor.id,
            rol=actor.rol,
        )
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ActieResultaatDto(id=acceptatie_id)


@router.post("/reconciliatie/bevindingen/{bevinding_id}/gezien", response_model=schemas.ActieResultaatDto)
def bevinding_gezien(
    bevinding_id: uuid.UUID, invoer: schemas.RedenInvoerDto, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.ActieResultaatDto:
    """ "Gezien" op een LET-OP (opruim-kandidaat): snooze mét reden, kantoorrol binnen scope; vervalt ná
    de Beheerder-instelling `gezien_dagen` of zodra de kandidaat een andere reden krijgt."""
    try:
        gezien_id = kantoorbreed.markeer_gezien(
            bevinding_id=bevinding_id,
            administratie_id=invoer.administratie_id,
            reden=invoer.reden,
            actor_id=actor.id,
            rol=actor.rol,
        )
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ActieResultaatDto(id=gezien_id)


@router.post("/reconciliatie/bevindingen/{bevinding_id}/gezien-intrekken", response_model=schemas.ActieResultaatDto)
def bevinding_gezien_intrekken(
    bevinding_id: uuid.UUID, invoer: schemas.RedenInvoerDto, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.ActieResultaatDto:
    try:
        gezien_id = kantoorbreed.gezien_intrekken(
            bevinding_id=bevinding_id,
            administratie_id=invoer.administratie_id,
            reden=invoer.reden,
            actor_id=actor.id,
            rol=actor.rol,
        )
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ActieResultaatDto(id=gezien_id)


@router.post("/reconciliatie/run", response_model=schemas.ReconciliatieRunDto, status_code=status.HTTP_202_ACCEPTED)
def reconciliatie_nu_draaien(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.ReconciliatieRunDto:
    """ "Nu draaien" (Beheerder): wachtrij-rij bron 'handmatig' + voertuig (dev thread / cloud on-demand
    job rlz-reconciliatie) — 202 + run-id, status via GET /reconciliatie/run/{run_id}. Een lopende run
    wordt hergebruikt."""
    try:
        return _run_dto(run_service.start_handmatig(actor_id=actor.id))  # type: ignore[return-value]
    except run_service.RunStartFout as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/reconciliatie/run/laatste", response_model=schemas.ReconciliatieRunDto | None)
def reconciliatie_laatste_run(
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.ReconciliatieRunDto | None:
    return _run_dto(run_service.laatste_run())


@router.get("/reconciliatie/run/{run_id}", response_model=schemas.ReconciliatieRunDto)
def reconciliatie_run_status(
    run_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.ReconciliatieRunDto:
    try:
        return _run_dto(run_service.status_van(run_id))  # type: ignore[return-value]
    except run_service.RunNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/reconciliatie/instelling", response_model=schemas.InstellingDto)
def reconciliatie_instelling(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.InstellingDto:
    return schemas.InstellingDto(gezien_dagen=kantoorbreed.gezien_dagen())


@router.put("/reconciliatie/instelling", response_model=schemas.InstellingDto)
def reconciliatie_instelling_zetten(
    invoer: schemas.InstellingDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingDto:
    try:
        return schemas.InstellingDto(
            gezien_dagen=kantoorbreed.zet_gezien_dagen(dagen=invoer.gezien_dagen, actor_id=actor.id)
        )
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc


@router.post(
    "/reconciliatie/bevindingen/{bevinding_id}/opnieuw-boeken", response_model=schemas.OpnieuwBoekenResultaatDto
)
def bevinding_opnieuw_boeken(
    bevinding_id: uuid.UUID,
    invoer: schemas.OpnieuwBoekenInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.OpnieuwBoekenResultaatDto:
    """ "Opnieuw boeken (extern document verdwenen)" (A11, 07-09) op een documenten-afwijking
    `ontbreekt_in_rlz`/`ontbreekt_in_odoo`: de service toetst LIVE dat de backend het stuk echt niet meer kent,
    zet het document terug op klaar_om_te_boeken mét boek_cyclus +1 (vers GUID, géén tegenboeking) en legt
    reden/tijdlijn/audit vast; de mens boekt daarna via het controlescherm (harde checks opnieuw).

    Aangifte-poort (correctie Peter 07-09): valt de boekdatum van de verdwenen boeking in een ingediende
    btw-aangifte (of is die status niet leesbaar), dan 409 mét `detail.code == "btw_mogelijk_aangegeven"`; alleen
    een Beheerder zet door met `btw_niet_in_aangifte_bevestigd` + `bevestiging_reden` (andere rol = 403, reden
    ontbreekt = 422). De rol komt uit het token/DB (`CurrentGebruiker.rol`), nooit uit de body."""
    from app.documenten import herboeken

    try:
        r = herboeken.opnieuw_boeken_vanuit_bevinding(
            bevinding_id=bevinding_id,
            administratie_id=invoer.administratie_id,
            reden=invoer.reden,
            actor_id=actor.id,
            rol=actor.rol,
            btw_niet_in_aangifte_bevestigd=invoer.btw_niet_in_aangifte_bevestigd,
            bevestiging_reden=invoer.bevestiging_reden,
        )
    except herboeken.BevindingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except herboeken.GeenToegang as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except herboeken.NogAanwezigInBackend as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except herboeken.BtwMogelijkAangegeven as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.als_detail()) from exc
    except herboeken.HerboekenFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return schemas.OpnieuwBoekenResultaatDto(
        document_id=r.document_id, status=r.status.value, boek_cyclus=r.boek_cyclus, doel_pad=r.doel_pad
    )
