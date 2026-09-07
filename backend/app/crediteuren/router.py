"""Inzicht › Crediteuren — kantoorbrede dubbel-signalering mét actie (design-ronde 03-09; schaalbaar blok B13 07-09).
Rolpoort: élke kantoorrol (`vereis_kantoorrol`, router-breed); kantoorbreed = uitsluitend de administraties in scope
van de actor (Beheerder alle actieve). Geen RLZ-calls, geen RLZ-writes: verliezers worden in de MODULE onbruikbaar."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.auth.deps import CurrentGebruiker, vereis_kantoorrol
from app.crediteuren import afhandeling, schemas, service

router = APIRouter(prefix="/crediteuren", tags=["crediteuren"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: service.CrediteurenFout) -> HTTPException:
    if isinstance(exc, service.OnbekendeAdministratie):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _kaart(k: service.Kaart) -> schemas.KaartDto:
    return schemas.KaartDto(
        vendor_id=k.vendor_id,
        naam=k.naam,
        btw_nummer=k.btw_nummer,
        kvk_nummer=k.kvk_nummer,
        ibans=k.ibans,
        aantal_boekingen=k.aantal_boekingen,
        laatst_geboekt=k.laatst_geboekt,
    )


def _cluster(c: service.Cluster) -> schemas.ClusterDto:
    return schemas.ClusterDto(
        cluster_id=c.cluster_id,
        administratie_id=c.administratie_id,
        administratie_naam=c.administratie_naam,
        soort=c.soort,
        sleutel=c.sleutel,
        sleutels=[schemas.SleutelDto(soort=s, sleutel=w) for s, w in c.sleutels],
        chips=c.chips,
        crediteuren=[_kaart(k) for k in c.crediteuren],
        aantal_boekingen=c.aantal_boekingen,
        laatst_geboekt=c.laatst_geboekt,
        kvk_verschilt=c.kvk_verschilt,
        afmelden_primair=c.afmelden_primair,
        voorkeur_suggestie=c.voorkeur_suggestie,
        eenduidig=c.eenduidig,
        classificatie_reden=c.classificatie_reden,
    )


def _tellers(t: service.Tellers) -> schemas.TellersDto:
    return schemas.TellersDto(**t.__dict__)


@router.get("/dubbelen", response_model=schemas.LijstDto)
def dubbelen_lijst(
    pagina: int = Query(1, ge=1),
    q: str = Query(""),
    administratie_id: uuid.UUID | None = Query(None),
    sleutel: str | None = Query(None),
    classificatie: str | None = Query(None),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.LijstDto:
    """Kantoorbrede lijst van dubbel-clusters (zwaarste sleutel eerst), facetten Administratie/Sleutel/Classificatie,
    zoekterm, paginering 25 — administratie is een filter, geen poort (ontwerpnotitie ①)."""
    try:
        lijst = service.lijst(
            actor, q=q, pagina=pagina, administratie_id=administratie_id, sleutel=sleutel, classificatie=classificatie
        )
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.LijstDto(
        rijen=[_cluster(c) for c in lijst.rijen],
        totaal=lijst.totaal,
        pagina=lijst.pagina,
        per_pagina=lijst.per_pagina,
        tellers=_tellers(lijst.tellers),
        facetten=schemas.FacettenDto(
            administraties=[schemas.FacetAdministratieDto(**f.__dict__) for f in lijst.facetten.administraties],
            sleutels=lijst.facetten.sleutels,
        ),
    )


@router.get("/dubbelen/stand", response_model=schemas.TellersDto)
def dubbelen_stand(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.TellersDto:
    """Werkvoorraad-teller "crediteur-dubbelen (N)" = alleen TWIJFEL-clusters (mens nodig) — tonen bij N > 0."""
    return _tellers(service.stand(actor))


def _run_dto(u: afhandeling.RunUitkomst) -> schemas.AutoRunDto:
    return schemas.AutoRunDto(
        run_id=u.run_id,
        dry_run=u.dry_run,
        eenduidig=u.eenduidig,
        twijfel=u.twijfel,
        afgehandeld=u.afgehandeld,
        fouten=u.fouten,
        administraties=[
            schemas.AdministratieUitkomstDto(
                administratie_id=a.administratie_id,
                administratie_naam=a.administratie_naam,
                eenduidig=a.eenduidig,
                twijfel=a.twijfel,
                afgehandeld=a.afgehandeld,
                fouten=a.fouten,
                voorbeelden=[schemas.VoorbeeldDto(**v.__dict__) for v in a.voorbeelden],
            )
            for a in u.administraties
        ],
    )


@router.post("/dubbelen/auto-afhandelen", response_model=schemas.AutoRunDto)
def auto_afhandelen(
    invoer: schemas.AutoAfhandelenInvoer, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.AutoRunDto:
    """ "Eenduidige clusters automatisch afhandelen (N)": `dry_run=true` = preview (aantallen + voorbeelden per
    administratie, niets gewijzigd); `dry_run=false` = afhandelen — één transactie per cluster, audit, terugdraaibaar.
    Alleen administraties in scope van de actor."""
    try:
        u = afhandeling.auto_afhandelen(
            service.Actor(id=actor.id, rol=actor.rol), dry_run=invoer.dry_run, administratie_id=invoer.administratie_id
        )
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return _run_dto(u)


@router.get("/dubbelen/{administratie_id}/cluster-detail", response_model=schemas.ClusterDetailDto)
def cluster_detail(
    administratie_id: uuid.UUID,
    vendor_ids: list[uuid.UUID] = Query(..., min_length=2),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.ClusterDetailDto:
    """Dialooggegevens "Voorkeur kiezen…": kaarten, vooringevulde voorkeur, classificatie mét reden. Geen RLZ-call."""
    try:
        d = service.cluster_detail(actor, administratie_id=administratie_id, vendor_ids=vendor_ids)
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ClusterDetailDto(
        administratie_id=d.administratie_id,
        administratie_naam=d.administratie_naam,
        crediteuren=[_kaart(k) for k in d.crediteuren],
        voorkeur_suggestie=d.voorkeur_suggestie,
        eenduidig=d.eenduidig,
        classificatie_reden=d.classificatie_reden,
    )


@router.post("/dubbelen/{administratie_id}/afhandelen", response_model=schemas.AfhandelUitkomstDto)
def afhandelen(
    administratie_id: uuid.UUID, invoer: schemas.AfhandelenInvoer, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.AfhandelUitkomstDto:
    """ "Voorkeur kiezen…" (mens): verliezers worden in de module onbruikbaar; geheugen, kenmerk, IBAN's en open
    boekvoorstellen gaan naar de voorkeur — één transactie, audit, terugdraaibaar. Geen RLZ-write."""
    try:
        u = service.afhandelen(
            actor,
            administratie_id=administratie_id,
            voorkeur_vendor_id=invoer.voorkeur_vendor_id,
            verliezer_vendor_ids=invoer.verliezer_vendor_ids,
        )
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    melding = f"afgehandeld — {', '.join(u.verliezer_namen)} {'is' if len(u.verliezer_namen) == 1 else 'zijn'} in de module onbruikbaar; voorkeur {u.voorkeur_naam or ''}".strip()
    return schemas.AfhandelUitkomstDto(**u.__dict__, melding=melding)


@router.post("/dubbelen/{administratie_id}/afmelden", response_model=schemas.AfmeldenUitkomstDto)
def afmelden(
    administratie_id: uuid.UUID, invoer: schemas.AfmeldenInvoer, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.AfmeldenUitkomstDto:
    """ "Geen dubbel — afmelden": reden verplicht (422 zonder), cluster verdwijnt en komt voor dezelfde combinatie
    niet terug (ontwerpnotitie ⑤)."""
    try:
        afmelding_id = service.afmelden(
            actor, administratie_id=administratie_id, vendor_ids=invoer.vendor_ids, reden=invoer.reden
        )
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.AfmeldenUitkomstDto(afmelding_id=afmelding_id)


def _afhandelingen_dto(regels: list[afhandeling.AfhandelingRegel]) -> schemas.AfhandelingenDto:
    return schemas.AfhandelingenDto(
        regels=[schemas.AfhandelingRegelDto(**r.__dict__) for r in regels],
        actief=sum(1 for r in regels if r.teruggedraaid_op is None),
        teruggedraaid=sum(1 for r in regels if r.teruggedraaid_op is not None),
    )


@router.get("/afhandelingen", response_model=schemas.AfhandelingenDto)
def afhandelingen(
    administratie_id: uuid.UUID | None = Query(None), actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.AfhandelingenDto:
    """Log van afgehandelde clusters (auto + mens), nieuwste eerst, kantoorbreed binnen scope — de terugdraai-ingang."""
    return _afhandelingen_dto(
        afhandeling.lijst_afhandelingen(service.Actor(id=actor.id, rol=actor.rol), administratie_id=administratie_id)
    )


@router.post("/afhandelingen/{afhandeling_id}/terugdraaien", response_model=schemas.AfhandelingRegelDto)
def terugdraaien(
    afhandeling_id: uuid.UUID, invoer: schemas.TerugdraaiInvoer, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.AfhandelingRegelDto:
    """Terugdraaien mét verplichte reden: markering en kenmerk/boekvoorstellen hersteld, audit."""
    try:
        r = afhandeling.draai_terug(
            service.Actor(id=actor.id, rol=actor.rol), afhandeling_id=afhandeling_id, reden=invoer.reden
        )
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.AfhandelingRegelDto(**r.__dict__)


@router.get("/opruimlijst.csv")
def opruimlijst(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> Response:
    """Optionele export "wie wil opruimen in RLZ": alle verliezers in scope + legacy werklijst-regels. Geen teller."""
    csv_tekst = afhandeling.export_opruimlijst(service.Actor(id=actor.id, rol=actor.rol))
    return Response(
        content=csv_tekst.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rlz-opruimlijst-crediteuren.csv"'},
    )
