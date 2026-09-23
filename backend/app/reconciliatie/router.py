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


@router.post(
    "/reconciliatie/intake/{kanaal}/nu-verwerken",
    response_model=schemas.IntakeNuVerwerkenDto,
    status_code=status.HTTP_202_ACCEPTED,
)
def intake_nu_verwerken(kanaal: str, actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.IntakeNuVerwerkenDto:
    """ "Nu verwerken" (Peter 22-09; élke kantoorrol — dezelfde handeling als wachten op de 10-minuten-scheduler, maar
    direct): start de intake-job van het kanaal opnieuw. De job leest het hele venster (INBOX + Spam, gelezen én
    ongelezen) en verwerkt wat nog niet in de verwerkt-administratie staat — idempotent op Message-ID, nooit dubbel.
    Audit `intake_postvak_nu_verwerken`; onbekend kanaal = 404; start mislukt = 502 mét reden."""
    from app.documenten.betaalstatus import POSTVAK_ADRES_PER_KANAAL
    from app.intake import nu_verwerken

    try:
        r = nu_verwerken.start(kanaal=kanaal, actor_id=actor.id)
    except nu_verwerken.OnbekendKanaal as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except nu_verwerken.StartMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.IntakeNuVerwerkenDto(
        kanaal=r.kanaal,
        postvak_adres=POSTVAK_ADRES_PER_KANAAL.get(r.kanaal),
        voertuig=r.voertuig,
        job_resource=r.job_resource,
    )


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


def _instelling_dto(gezien_dagen: int, standen: list[dict]) -> schemas.InstellingDto:
    return schemas.InstellingDto(
        gezien_dagen=gezien_dagen, soort_standen=[schemas.SoortStandDto(**s) for s in standen]
    )


@router.get("/reconciliatie/instelling", response_model=schemas.InstellingDto)
def reconciliatie_instelling(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.InstellingDto:
    return _instelling_dto(kantoorbreed.gezien_dagen(), kantoorbreed.soort_standen_overzicht())


@router.put("/reconciliatie/instelling", response_model=schemas.InstellingDto)
def reconciliatie_instelling_zetten(
    invoer: schemas.InstellingDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingDto:
    try:
        dagen = kantoorbreed.zet_gezien_dagen(dagen=invoer.gezien_dagen, actor_id=actor.id)
        return _instelling_dto(dagen, kantoorbreed.soort_standen_overzicht())
    except kantoorbreed.ReconciliatieFout as exc:
        raise _vertaal(exc) from exc


@router.put("/reconciliatie/instelling/soort-stand", response_model=schemas.InstellingDto)
def reconciliatie_soort_stand_zetten(
    invoer: schemas.SoortStandInvoerDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingDto:
    """SPOED 17-09 blok C: promotie van een bevindingssoort naar de actiemail (`actie`) of terug naar `meten` —
    Beheerder-only, mét reden en audit (`bevindingssoort_naar_actie`/`_naar_meten`)."""
    try:
        standen = kantoorbreed.zet_soort_stand(soort=invoer.soort, stand=invoer.stand, actor_id=actor.id, reden=invoer.reden)
        return _instelling_dto(kantoorbreed.gezien_dagen(), standen)
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


@router.post(
    "/reconciliatie/bevindingen/{bevinding_id}/herboeken-als-omzet",
    response_model=schemas.HerboekenAlsOmzetResultaatDto,
)
def bevinding_herboeken_als_omzet(
    bevinding_id: uuid.UUID,
    invoer: schemas.OpnieuwBoekenInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.HerboekenAlsOmzetResultaatDto:
    """ "Herboeken als omzet" (Peter 16-09, casus Van Boxtel) op een omzet-afwijking `omzet_in_inkoopstroom`: storno
    (actie 19) van de als inkoopfactuur geboekte omzet achter de btw-aangiftepoort (409 `btw_mogelijk_aangegeven`,
    Beheerder-doorzet mét reden — zelfde invoer als opnieuw boeken), document → kassarapport in de werkvoorraad; de
    mens boekt daarna als Receipt onder Inkomsten. Nooit een delete in RLZ."""
    from app.documenten import herboeken
    from app.omzet import inkoopstroom

    try:
        r = inkoopstroom.herboek_als_omzet_vanuit_bevinding(
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
    except herboeken.BtwMogelijkAangegeven as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.als_detail()) from exc
    except herboeken.HerboekenFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return schemas.HerboekenAlsOmzetResultaatDto(
        document_id=r.document_id, status=r.status.value, gestorneerd=r.gestorneerd, doel_pad=r.doel_pad
    )


@router.post(
    "/reconciliatie/bevindingen/{bevinding_id}/type-wijzigen-kassarapport",
    response_model=schemas.TypeWijzigenKassarapportResultaatDto,
)
def bevinding_type_wijzigen_kassarapport(
    bevinding_id: uuid.UUID,
    invoer: schemas.TypeWijzigenKassarapportInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.TypeWijzigenKassarapportResultaatDto:
    """"Type wijzigen → kassarapport" (blok C 16-09 avond) op een omzet-afwijking `kassarapport_in_werkvoorraad`:
    de bestaande soort-wissel (documenten/soort.py) — terug naar ONTVANGEN, extractie opnieuw via het omzetpad
    (ProfX/… deterministisch), tijdlijn + audit. 404 onbekende bevinding, 403 buiten scope, 422 verkeerde soort, 409
    als de status van het document de wissel niet toelaat (geboekt/ter accordering)."""
    from app.documenten import herboeken
    from app.omzet import inkoopstroom

    try:
        r = inkoopstroom.type_wijzigen_kassarapport_vanuit_bevinding(
            bevinding_id=bevinding_id, administratie_id=invoer.administratie_id, actor_id=actor.id, rol=actor.rol
        )
    except herboeken.BevindingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except herboeken.GeenToegang as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except herboeken.HerboekenFout as exc:
        conflict = "status" in str(exc).lower() or "geboekt" in str(exc).lower()
        code = status.HTTP_409_CONFLICT if conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return schemas.TypeWijzigenKassarapportResultaatDto(
        document_id=r.document_id, status=r.status, van_soort=r.van_soort, naar_soort=r.naar_soort, doel_pad=r.doel_pad
    )


def _vertaal_bewust_verwijderd(exc: Exception) -> HTTPException:
    from app.reconciliatie import bewust_verwijderd

    tekst = str(exc)
    if isinstance(exc, bewust_verwijderd.BevindingNietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=tekst)
    if isinstance(exc, bewust_verwijderd.GeenToegang):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=tekst)
    conflict = isinstance(exc, bewust_verwijderd.StatusFout | bewust_verwijderd.NietTerugdraaibaar)
    if conflict or "al geaccepteerd" in tekst:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=tekst)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=tekst)


@router.post(
    "/reconciliatie/bevindingen/{bevinding_id}/bewust-verwijderd", response_model=schemas.BewustVerwijderdResultaatDto
)
def bevinding_bewust_verwijderd(
    bevinding_id: uuid.UUID,
    invoer: schemas.BewustVerwijderdInvoerDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.BewustVerwijderdResultaatDto:
    """ "Bewust verwijderd in RLZ" (blok D 16-09, Beheerder) op een documenten-afwijking `ontbreekt_in_rlz`/
    `ontbreekt_in_odoo`: de mens verwijderde het stuk zélf in Reeleezee (dubbel/test). Eén klik = acceptatie mét
    de vaste reden via de bestaande schrijver + het document van geboekt naar afgevoerd_duplicaat (boekstuknummer
    blijft als historie; terugweg = heropenen op het document). 404 onbekende bevinding, 403 buiten scope/rol,
    422 verkeerde soort, 409 als het document ná de acceptatie niet van status kon wisselen (acceptatie staat)."""
    from app.reconciliatie import bewust_verwijderd

    try:
        r = bewust_verwijderd.accepteer_bewust_verwijderd(
            bevinding_id=bevinding_id,
            administratie_id=invoer.administratie_id,
            actor_id=actor.id,
            rol=actor.rol,
            toelichting=invoer.toelichting,
        )
    except bewust_verwijderd.BewustVerwijderdFout as exc:
        raise _vertaal_bewust_verwijderd(exc) from exc
    return schemas.BewustVerwijderdResultaatDto(
        acceptatie_id=r.acceptatie_id,
        document_id=r.document_id,
        document_status_nieuw=r.document_status_nieuw,
        boekstuknummer=r.boekstuknummer,
        document_status_gewijzigd=r.document_status_gewijzigd,
        reden=r.reden,
    )


@router.post(
    "/reconciliatie/documenten/{document_id}/bewust-verwijderd-herstellen",
    response_model=schemas.BewustVerwijderdHerstelResultaatDto,
)
def document_bewust_verwijderd_herstellen(
    document_id: uuid.UUID,
    invoer: schemas.BewustVerwijderdHerstelInvoerDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.BewustVerwijderdHerstelResultaatDto:
    """Terugweg van "Bewust verwijderd in RLZ" (blok D 16-09, Beheerder, verplichte reden): het document gaat van
    afgevoerd_duplicaat terug naar geboekt (alleen als de jongste afvoer het bewust-verwijderd-spoor draagt) en de
    acceptatie wordt ingetrokken — de bevinding telt bij de volgende run weer mee. 409 als het document niet via dit
    pad is afgevoerd."""
    from app.reconciliatie import bewust_verwijderd

    try:
        r = bewust_verwijderd.herstel_bewust_verwijderd(
            administratie_id=invoer.administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            rol=actor.rol,
            reden=invoer.reden,
        )
    except bewust_verwijderd.BewustVerwijderdFout as exc:
        raise _vertaal_bewust_verwijderd(exc) from exc
    return schemas.BewustVerwijderdHerstelResultaatDto(
        document_id=r.document_id,
        document_status_nieuw=r.document_status_nieuw,
        acceptatie_ingetrokken_id=r.acceptatie_ingetrokken_id,
    )


# ---- "intussen buiten de module geboekt" (Peter 22-09) — twee handelingen op het document ---------------------------


def _vertaal_extern_geboekt(exc: Exception) -> HTTPException:
    from app.documenten import intussen_extern_geboekt as ieg

    tekst = str(exc)
    if isinstance(exc, ieg.DocumentNietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=tekst)
    if isinstance(exc, ieg.GeenToegang):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=tekst)
    if isinstance(exc, ieg.StatusNietToegestaan | ieg.AlVastgelegd):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=tekst)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=tekst)


@router.post(
    "/reconciliatie/documenten/{document_id}/extern-geboekt/afwijzen",
    response_model=schemas.ExternGeboektAfwijzenResultaatDto,
)
def document_extern_geboekt_afwijzen(
    document_id: uuid.UUID,
    invoer: schemas.ExternGeboektAfwijzenInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.ExternGeboektAfwijzenResultaatDto:
    """ "Afwijzen — al geboekt als ‹RLZ-04-…›" (Peter 22-09, bevinding `intussen_extern_geboekt` én de boekfout ná het
    laatste akkoord): lopende accorderingsronde vervalt mét tijdlijnregel "niet meer nodig: al geboekt in Reeleezee",
    daarna de bestaande afwijs-route mét voorgevulde reden + kruisverwijzing. Élke kantoorrol binnen scope; 409 als het
    document op de IBAN-accordering wacht of al een andere status heeft (mét route), 404 onbekend, 403 buiten scope."""
    from app.documenten import afwijzen
    from app.documenten import intussen_extern_geboekt as ieg
    from app.documenten.statusmachine import OngeldigeStatusovergang

    try:
        r = ieg.wijs_af_al_geboekt(
            administratie_id=invoer.administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            rol=actor.rol,
            extern_boekstuk=invoer.extern_boekstuk,
            extern_id=invoer.extern_id,
            systeem=invoer.systeem,
            toelichting=invoer.toelichting,
        )
    except ieg.ExternGeboektFout as exc:
        raise _vertaal_extern_geboekt(exc) from exc
    except (afwijzen.OngeldigeStatusovergang, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.ExternGeboektAfwijzenResultaatDto(
        document_id=r.document_id,
        status=r.status,
        reden=r.reden,
        accordering_vervallen=r.accordering_vervallen,
        afwijzing_id=r.afwijzing_id,
    )


@router.post(
    "/reconciliatie/documenten/{document_id}/extern-geboekt/toch-verschillend",
    response_model=schemas.ExternGeboektTochVerschillendResultaatDto,
)
def document_extern_geboekt_toch_verschillend(
    document_id: uuid.UUID,
    invoer: schemas.ExternGeboektTochVerschillendInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.ExternGeboektTochVerschillendResultaatDto:
    """ "Toch verschillend — doorgaan" (Peter 22-09): het externe stuk is een andere factuur. Tijdlijnregel + audit, het
    stuk telt niet meer als treffer (hercontrole én harde check Duplicaatcheck), checks-cache ongeldig; een Beheerder
    accepteert in dezelfde handeling ook de open bevinding. 422 zonder inhoudelijke reden, 409 als al vastgelegd."""
    from app.documenten import intussen_extern_geboekt as ieg

    try:
        r = ieg.toch_verschillend(
            administratie_id=invoer.administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            rol=actor.rol,
            extern_id=invoer.extern_id,
            extern_boekstuk=invoer.extern_boekstuk,
            reden=invoer.reden,
            bevinding_id=invoer.bevinding_id,
        )
    except ieg.ExternGeboektFout as exc:
        raise _vertaal_extern_geboekt(exc) from exc
    return schemas.ExternGeboektTochVerschillendResultaatDto(
        document_id=r.document_id,
        extern_ids=list(r.extern_ids),
        reden=r.reden,
        bevinding_geaccepteerd=r.bevinding_geaccepteerd,
        checks_cache_ongeldig=r.checks_cache_ongeldig,
    )
