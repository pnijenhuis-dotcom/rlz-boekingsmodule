"""Voorraad-aansluiting (blok D 28-08): lezen = kantoorrol + administratie-scope, muteren
(telling, groep, correctie, herrekenen) = kantoorrol + scope (geen Beheerder-only: dit is
controle-werk zonder boeking; de opt-in zelf is Beheerder-only in beheer/router.py). Nooit RLZ-writes."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import service as auth_service
from app.auth.deps import CurrentGebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.voorraad import schemas, service

router = APIRouter(tags=["voorraad"], dependencies=[Depends(vereis_kantoorrol)])

PER_PAGINA_DEFAULT = 25
PER_PAGINA_MAX = 200


def _pagineer(items: list, pagina: int, per_pagina: int) -> tuple[list, int]:
    start = (pagina - 1) * per_pagina
    return items[start : start + per_pagina], len(items)


def _voorraad_administraties(actor: CurrentGebruiker) -> list[tuple[uuid.UUID, str]]:
    """Scope-waarheid voor de kantoorbrede routes: de administraties van de actor (Beheerder = alle
    actieve) mét de opt-in "Voorraad bijhouden" — per administratie leest de service daarna in een
    gescoopte sessie (RLS blijft de poort, dit is alleen de iteratielijst)."""
    return [
        (a.id, a.naam)
        for a in auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
        if a.voorraad_ingeschakeld
    ]


def _verschil_dto(r: service.VerschilRij) -> schemas.VerschilRijDto:
    return schemas.VerschilRijDto(**r.__dict__)


@router.get("/voorraad/verschillen", response_model=schemas.VerschillenLijstDto)
def verschillen_kantoorbreed(
    administratie_id: uuid.UUID | None = None,
    q: str = Query(""),
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(PER_PAGINA_DEFAULT, ge=1, le=PER_PAGINA_MAX),
    tot: date | None = None,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.VerschillenLijstDto:
    """Landing Inzicht › Voorraad (design-ronde 03-09, mockup inzicht-kantoorbreed ⑤): artikelgroepen
    buiten tolerantie over álle voorraad-administraties in scope, zwaarste afwijking eerst;
    administratie = facet (leeg = alle), `q` zoekt op artikelgroep; paginering 25. Alleen lezen."""
    lijst = service.verschillen_kantoorbreed(
        administraties=_voorraad_administraties(actor),
        actor_id=actor.id,
        administratie_id=administratie_id,
        q=q,
        pagina=pagina,
        per_pagina=per_pagina,
        tot=tot,
    )
    return schemas.VerschillenLijstDto(
        rijen=[_verschil_dto(r) for r in lijst.rijen],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        tellers=schemas.VerschilTellersDto(**lijst.tellers.__dict__),
        facetten=[schemas.VerschilFacetAdministratieDto(**f.__dict__) for f in lijst.facetten],
        van=lijst.van,
        tot=lijst.tot,
    )


@router.get("/voorraad/verschillen/stand", response_model=schemas.VerschilTellersDto)
def verschillen_stand(
    tot: date | None = None, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.VerschilTellersDto:
    """Alleen de tellers (nav-/KPI-chip): N groepen buiten tolerantie over M administraties."""
    tellers = service.verschillen_tellers(administraties=_voorraad_administraties(actor), actor_id=actor.id, tot=tot)
    return schemas.VerschilTellersDto(**tellers.__dict__)


def _vertaal(exc: service.VoorraadFout) -> HTTPException:
    if isinstance(exc, service.VoorraadUitgeschakeld):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _groep_dto(g: service.GroepAansluiting) -> schemas.GroepAansluitingDto:
    return schemas.GroepAansluitingDto(**g.__dict__)


def _regel_dto(r: service.RegelData) -> schemas.RegelDto:
    return schemas.RegelDto(**r.__dict__)


@router.get("/administraties/{administratie_id}/voorraad/aansluiting", response_model=schemas.AansluitingDto)
def aansluiting(
    administratie_id: uuid.UUID,
    van: date,
    tot: date,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AansluitingDto:
    try:
        a = service.aansluiting(administratie_id=administratie_id, van=van, tot=tot)
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.AansluitingDto(
        administratie_id=a.administratie_id,
        van=a.van,
        tot=a.tot,
        groepen=[_groep_dto(g) for g in a.groepen],
        niet_genormaliseerd_in=a.niet_genormaliseerd_in,
        niet_genormaliseerd_uit=a.niet_genormaliseerd_uit,
        onzeker_totaal=a.onzeker_totaal,
        regels_totaal=a.regels_totaal,
        dienst_regels=a.dienst_regels,
        transport_regels=a.transport_regels,
        bronnen=a.bronnen,
    )


@router.get(
    "/administraties/{administratie_id}/voorraad/groepen/{artikelgroep_id}/dagstanden",
    response_model=list[schemas.DagStandDto],
)
def dagstanden(
    administratie_id: uuid.UUID,
    artikelgroep_id: uuid.UUID,
    van: date,
    tot: date,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.DagStandDto]:
    try:
        rijen = service.dagstanden(administratie_id=administratie_id, artikelgroep_id=artikelgroep_id, van=van, tot=tot)
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.DagStandDto(**d.__dict__) for d in rijen]


@router.get("/administraties/{administratie_id}/voorraad/regels", response_model=schemas.RegelsPaginaDto)
def regels(
    administratie_id: uuid.UUID,
    van: date,
    tot: date,
    artikelgroep_id: uuid.UUID | None = None,
    normalisatie_status: str | None = None,
    soort: str | None = None,
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(PER_PAGINA_DEFAULT, ge=1, le=PER_PAGINA_MAX),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RegelsPaginaDto:
    """Drill-down per artikelgroep (alle factuurregels achter het getal), het normalisatie-scherm
    (`normalisatie_status=niet_genormaliseerd,onzeker` — meerdere waarden komma-gescheiden) óf de
    dienst-/omzetregels (`soort=dienst|transport` — v2, MI-query). Server-side gepagineerd (B3.3, 03-09):
    `{rijen, totaal, pagina, per_pagina}`, default 25, max 200."""
    try:
        p = service.regels_pagina(
            administratie_id=administratie_id,
            van=van,
            tot=tot,
            artikelgroep_id=artikelgroep_id,
            status=normalisatie_status,
            soort=soort,
            pagina=pagina,
            per_pagina=per_pagina,
        )
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.RegelsPaginaDto(
        rijen=[_regel_dto(r) for r in p.rijen], totaal=p.totaal, pagina=p.pagina, per_pagina=p.per_pagina
    )


@router.get("/administraties/{administratie_id}/voorraad/diensten", response_model=schemas.DienstenPaginaDto)
def diensten(
    administratie_id: uuid.UUID,
    van: date,
    tot: date,
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(PER_PAGINA_DEFAULT, ge=1, le=PER_PAGINA_MAX),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DienstenPaginaDto:
    """Inzage "als dienst geclassificeerd" (v2 blok B, eis Peter: controleerbaar): per unieke tekst
    mét aantallen, soort en bron van de classificatie; correctie via `normalisatie/corrigeer` op de
    voorbeeldregel (geldt voor álle regels met dezelfde tekst/code). Gepagineerd (B3.3), meest
    voorkomend eerst."""
    try:
        rijen = service.dienst_teksten(administratie_id=administratie_id, van=van, tot=tot)
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    deel, totaal = _pagineer(rijen, pagina, per_pagina)
    return schemas.DienstenPaginaDto(
        rijen=[schemas.DienstTekstDto(**d.__dict__) for d in deel], totaal=totaal, pagina=pagina, per_pagina=per_pagina
    )


@router.get("/administraties/{administratie_id}/voorraad/artikelcodes", response_model=schemas.ArtikelcodesPaginaDto)
def artikelcodes(
    administratie_id: uuid.UUID,
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(PER_PAGINA_DEFAULT, ge=1, le=PER_PAGINA_MAX),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ArtikelcodesPaginaDto:
    """Codes-inzage (v2 blok C): élke code → groep/soort per richting + leverancier, mét bron
    (AI-voorstel vs handmatig), zekerheid en het aantal regels dat erop steunt. Gepagineerd (B3.3)."""
    try:
        rijen = service.artikelcodes(administratie_id=administratie_id)
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    deel, totaal = _pagineer(rijen, pagina, per_pagina)
    return schemas.ArtikelcodesPaginaDto(
        rijen=[schemas.ArtikelcodeDto(**a.__dict__) for a in deel], totaal=totaal, pagina=pagina, per_pagina=per_pagina
    )


@router.post(
    "/administraties/{administratie_id}/voorraad/artikelcodes/{koppeling_id}/corrigeer",
    response_model=schemas.CorrectieResultaatDto,
)
def artikelcode_corrigeren(
    administratie_id: uuid.UUID,
    koppeling_id: uuid.UUID,
    invoer: schemas.ArtikelcodeCorrectieDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.CorrectieResultaatDto:
    """Correctie van een code-koppeling: wordt 'handmatig' (wint van de AI) en herleidt álle regels met
    dezelfde (richting, leverancier, code) deterministisch."""
    try:
        n = service.corrigeer_artikelcode(
            administratie_id=administratie_id,
            koppeling_id=koppeling_id,
            soort=invoer.soort,
            artikelgroep_id=invoer.artikelgroep_id,
            actor_id=actor.id,
        )
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.CorrectieResultaatDto(herrekend=n)


@router.get("/administraties/{administratie_id}/voorraad/groepen", response_model=list[schemas.GroepDto])
def groepen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> list[schemas.GroepDto]:
    return [schemas.GroepDto(**g.__dict__) for g in service.groepen(administratie_id=administratie_id)]


@router.post(
    "/administraties/{administratie_id}/voorraad/groepen",
    response_model=schemas.GroepDto,
    status_code=status.HTTP_201_CREATED,
)
def groep_aanmaken(
    administratie_id: uuid.UUID,
    invoer: schemas.GroepAanmakenDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.GroepDto:
    try:
        g = service.maak_groep(
            administratie_id=administratie_id,
            naam=invoer.naam,
            eenheid=invoer.eenheid,
            tolerantie_pct=invoer.tolerantie_pct,
            actor_id=actor.id,
        )
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.GroepDto(**g.__dict__)


@router.put(
    "/administraties/{administratie_id}/voorraad/groepen/{artikelgroep_id}/tolerantie",
    status_code=status.HTTP_204_NO_CONTENT,
)
def tolerantie_zetten(
    administratie_id: uuid.UUID,
    artikelgroep_id: uuid.UUID,
    invoer: schemas.TolerantieDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        service.zet_tolerantie(
            administratie_id=administratie_id,
            artikelgroep_id=artikelgroep_id,
            tolerantie_pct=invoer.tolerantie_pct,
            actor_id=actor.id,
        )
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc


@router.post("/administraties/{administratie_id}/voorraad/tellingen", status_code=status.HTTP_204_NO_CONTENT)
def telling_invoeren(
    administratie_id: uuid.UUID,
    invoer: schemas.TellingInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    """Systeemstand fase 1 = handmatige telling per artikelgroep per datum (upsert op datum)."""
    try:
        service.voer_telling_in(
            administratie_id=administratie_id,
            artikelgroep_id=invoer.artikelgroep_id,
            datum=invoer.datum,
            aantal=invoer.aantal,
            opmerking=invoer.opmerking,
            actor_id=actor.id,
        )
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc


@router.post(
    "/administraties/{administratie_id}/voorraad/normalisatie/corrigeer",
    response_model=schemas.CorrectieResultaatDto,
)
def normalisatie_corrigeren(
    administratie_id: uuid.UUID,
    invoer: schemas.CorrectieDto,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.CorrectieResultaatDto:
    """Optionele correctie — soort artikel (mét groep) óf dienst/transport; geldt vanaf dan voor álle
    regels met dezelfde leverancier + tekst én dezelfde artikelcode (historie herrekend). Nooit een
    voorwaarde voor de aansluiting."""
    try:
        n = service.corrigeer_normalisatie(
            administratie_id=administratie_id,
            regel_id=invoer.regel_id,
            soort=invoer.soort,
            artikelgroep_id=invoer.artikelgroep_id,
            actor_id=actor.id,
        )
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.CorrectieResultaatDto(herrekend=n)


@router.post("/administraties/{administratie_id}/voorraad/herreken", response_model=schemas.HerrekenResultaatDto)
def herrekenen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.HerrekenResultaatDto:
    """ "⟳ Verversen": alle inkoop-veldvoorstellen en geboekte verkoopdocumenten opnieuw door de
    feitenlaag (bekende teksten deterministisch, nieuwe teksten via de AI-gates)."""
    try:
        telling = service.herreken_administratie(administratie_id=administratie_id, actor_id=actor.id)
    except service.VoorraadFout as exc:
        raise _vertaal(exc) from exc
    return schemas.HerrekenResultaatDto(**telling)
