"""Instellingen › Autoboeken (kandidaten-motor, mockup autoboek-kandidaten.html) — Beheerder-only, net
als de per-leverancier-opt-in die eronder ligt. Aanzetten/uitzetten lopen via de bestaande
opt-in-schrijver; verbergen = snooze mét verplichte reden; heroverwegen = advies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, require_beheerder
from app.autoboek_kandidaten import schemas, service

router = APIRouter(prefix="/instellingen/autoboeken", tags=["autoboek-kandidaten"], dependencies=[Depends(require_beheerder)])


def _vertaal(exc: service.AutoboekKandidaatFout) -> HTTPException:
    if "Onbekende" in str(exc):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _tellers(t: service.Tellers) -> schemas.TellersDto:
    return schemas.TellersDto(**t.__dict__)


@router.get("/kandidaten", response_model=schemas.LijstDto)
def kandidaten_lijst(
    tab: str = Query("kandidaten"),
    q: str = Query(""),
    pagina: int = Query(1, ge=1),
    verborgen: bool = Query(False),
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.LijstDto:
    try:
        lijst = service.lijst(tab=tab, q=q, pagina=pagina, verborgen=verborgen)
    except service.AutoboekKandidaatFout as exc:
        raise _vertaal(exc) from exc
    return schemas.LijstDto(
        rijen=[schemas.KandidaatRijDto(**r.__dict__) for r in lijst.rijen],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        tellers=_tellers(lijst.tellers),
    )


@router.get("/stand", response_model=schemas.TellersDto)
def kandidaten_stand(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.TellersDto:
    """Nav-stand-chip + tab-tellers (stand van de laatste run mét tijdstip)."""
    return _tellers(service.tellers())


@router.post("/herbereken", response_model=schemas.HerberekenResultaatDto)
def kandidaten_herberekenen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.HerberekenResultaatDto:
    """Op verzoek de motor draaien (de dagelijkse sync-alles doet dit óók) — puur code, geen RLZ-calls."""
    resultaten = service.herbereken_alle()
    return schemas.HerberekenResultaatDto(
        administraties=len(resultaten),
        fouten=sum(1 for r in resultaten.values() if isinstance(r, str)),
        tellers=_tellers(service.tellers()),
    )


def _selectie(invoer: schemas.BulkSelectieDto) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Bulk-selectie: expliciete items, óf `alle: true` = exact de rijen die de lijst mét dezelfde filters
    toont, zonder paginering (B5.2 — "Selecteer alle N resultaten")."""
    if invoer.alle:
        try:
            rijen = service.rijen_binnen_filter(tab=invoer.tab, q=invoer.q, verborgen=invoer.verborgen)
        except service.AutoboekKandidaatFout as exc:
            raise _vertaal(exc) from exc
        return [(r.administratie_id, r.vendor_id) for r in rijen]
    return [(i.administratie_id, i.vendor_id) for i in invoer.items or []]


@router.post("/kandidaten/aanzetten", response_model=schemas.BulkAanzettenResultaatDto)
def kandidaten_aanzetten(
    invoer: schemas.BulkAanzettenDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.BulkAanzettenResultaatDto:
    """"Autoboeken aanzetten (n)": per rij live hertoetst; niet-kwalificerend = overgeslagen mét reden."""
    uitkomsten = service.bulk_aanzetten(items=_selectie(invoer), actor_id=actor.id)
    return schemas.BulkAanzettenResultaatDto(
        uitkomsten=[schemas.AanzetUitkomstDto(**u.__dict__) for u in uitkomsten],
        aangezet=sum(1 for u in uitkomsten if u.status == "aangezet"),
        overgeslagen=sum(1 for u in uitkomsten if u.status != "aangezet"),
    )


@router.post("/kandidaten/verbergen", response_model=schemas.BulkVerbergenResultaatDto)
def kandidaten_verbergen(
    invoer: schemas.BulkVerbergenDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.BulkVerbergenResultaatDto:
    """"Kandidaat verbergen" in bulk, één call (B5.1, 03-09): reden verplicht (422 zonder), uitkomst per rij
    verborgen | overgeslagen mét reden | fout; één fout stopt de rest niet."""
    try:
        uitkomsten = service.bulk_verbergen(items=_selectie(invoer), actor_id=actor.id, reden=invoer.reden)
    except service.AutoboekKandidaatFout as exc:
        raise _vertaal(exc) from exc
    return schemas.BulkVerbergenResultaatDto(
        uitkomsten=[schemas.AanzetUitkomstDto(**u.__dict__) for u in uitkomsten],
        verborgen=sum(1 for u in uitkomsten if u.status == "verborgen"),
        overgeslagen=sum(1 for u in uitkomsten if u.status != "verborgen"),
    )


@router.post("/kandidaten/{administratie_id}/{vendor_id}/uitzetten", status_code=status.HTTP_204_NO_CONTENT)
def kandidaat_uitzetten(
    administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    """Heroverwegen → uitzetten (één klik, audit via de bestaande opt-in-schrijver)."""
    try:
        service.uitzetten(administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor.id)
    except service.AutoboekKandidaatFout as exc:
        raise _vertaal(exc) from exc


@router.post("/kandidaten/{administratie_id}/{vendor_id}/verbergen", status_code=status.HTTP_204_NO_CONTENT)
def kandidaat_verbergen(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.VerbergenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> None:
    try:
        service.verbergen(administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor.id, reden=invoer.reden)
    except service.AutoboekKandidaatFout as exc:
        raise _vertaal(exc) from exc


@router.post("/kandidaten/{administratie_id}/{vendor_id}/weer-tonen", status_code=status.HTTP_204_NO_CONTENT)
def kandidaat_weer_tonen(
    administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    try:
        service.toon_weer(administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor.id)
    except service.AutoboekKandidaatFout as exc:
        raise _vertaal(exc) from exc


@router.get("/instelling", response_model=schemas.InstellingDto)
def instelling_ophalen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.InstellingDto:
    drempel, laatste_run = service.haal_instelling_op()
    return schemas.InstellingDto(drempel_op_rij=drempel, laatste_run_op=laatste_run)


@router.put("/instelling", response_model=schemas.InstellingDto)
def instelling_zetten(
    invoer: schemas.DrempelDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingDto:
    """Drempel "N op rij ongewijzigd" — Beheerder-only, default 5, audit oud→nieuw."""
    try:
        drempel = service.zet_drempel(actor_id=actor.id, drempel=invoer.drempel_op_rij)
    except service.AutoboekKandidaatFout as exc:
        raise _vertaal(exc) from exc
    _, laatste_run = service.haal_instelling_op()
    return schemas.InstellingDto(drempel_op_rij=drempel, laatste_run_op=laatste_run)
