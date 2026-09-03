"""Inzicht › Crediteuren — kantoorbrede dubbel-signalering mét actie (design-ronde 03-09). Rolpoort: élke
kantoorrol (`vereis_kantoorrol`, router-breed) — de oude per-administratie-route droeg al alleen een scope-poort;
kantoorbreed = uitsluitend de administraties in scope van de actor (Beheerder alle actieve). Geen RLZ-writes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentGebruiker, vereis_kantoorrol
from app.crediteuren import schemas, service

router = APIRouter(prefix="/crediteuren", tags=["crediteuren"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: service.CrediteurenFout) -> HTTPException:
    if isinstance(exc, service.OnbekendeAdministratie):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, service.OpenPostenBlokkeren):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "bericht": str(exc),
                "open_posten": {
                    str(v): [schemas.OpenPostDto(**p.__dict__).model_dump(mode="json") for p in posten]
                    for v, posten in exc.posten.items()
                },
            },
        )
    if isinstance(exc, service.OpenPostenToetsMislukt):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
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
        klaargezet=schemas.KlaargezetDto(**c.klaargezet.__dict__) if c.klaargezet else None,
    )


def _tellers(t: service.Tellers) -> schemas.TellersDto:
    return schemas.TellersDto(**t.__dict__)


@router.get("/dubbelen", response_model=schemas.LijstDto)
def dubbelen_lijst(
    pagina: int = Query(1, ge=1),
    q: str = Query(""),
    administratie_id: uuid.UUID | None = Query(None),
    sleutel: str | None = Query(None),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.LijstDto:
    """Kantoorbrede lijst van dubbel-clusters (zwaarste sleutel eerst), facetten Administratie/Sleutel, zoekterm,
    paginering 25 — administratie is een filter, geen poort (ontwerpnotitie ①)."""
    try:
        lijst = service.lijst(actor, q=q, pagina=pagina, administratie_id=administratie_id, sleutel=sleutel)
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
    """Werkvoorraad-teller "crediteur-dubbelen (N)" — alleen tonen bij N > 0 (ontwerpnotitie ⑧)."""
    return _tellers(service.stand(actor))


@router.get("/dubbelen/{administratie_id}/cluster-detail", response_model=schemas.ClusterDetailDto)
def cluster_detail(
    administratie_id: uuid.UUID,
    vendor_ids: list[uuid.UUID] = Query(..., min_length=2),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.ClusterDetailDto:
    """Dialooggegevens mét LIVE open-posten-toets per crediteur (RLZ-leesroute; onbereikbaar = toets mislukt)."""
    try:
        d = service.cluster_detail(actor, administratie_id=administratie_id, vendor_ids=vendor_ids)
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ClusterDetailDto(
        administratie_id=d.administratie_id,
        administratie_naam=d.administratie_naam,
        crediteuren=[_kaart(k) for k in d.crediteuren],
        voorkeur_suggestie=d.voorkeur_suggestie,
        open_posten={
            str(v): [schemas.OpenPostDto(**p.__dict__) for p in posten] for v, posten in d.open_posten.items()
        },
        toets_ok=d.toets_ok,
        toets_fout=d.toets_fout,
    )


@router.post("/dubbelen/{administratie_id}/archiveer", response_model=schemas.ArchiveerUitkomstDto)
def archiveer(
    administratie_id: uuid.UUID, invoer: schemas.ArchiveerInvoer, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.ArchiveerUitkomstDto:
    """ "Voorkeur kiezen & rest archiveren…": server hertoetst de open posten (409 bij blokkade of mislukte toets),
    schrijft de RLZ-werklijst-regel en verhuist geheugen + kenmerk naar de voorkeur — alles in één transactie."""
    try:
        u = service.archiveer(
            actor,
            administratie_id=administratie_id,
            voorkeur_vendor_id=invoer.voorkeur_vendor_id,
            overige_vendor_ids=invoer.overige_vendor_ids,
        )
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    melding = f"klaargezet — archiveer in RLZ: {', '.join(u.te_archiveren_namen)}"
    if u.al_klaargezet:
        melding = f"stond al klaar — archiveer in RLZ: {', '.join(u.te_archiveren_namen)}"
    return schemas.ArchiveerUitkomstDto(**u.__dict__, melding=melding)


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


def _werklijst_dto(regels: list[service.WerklijstRegel]) -> schemas.WerklijstDto:
    return schemas.WerklijstDto(
        regels=[schemas.WerklijstRegelDto(**r.__dict__) for r in regels],
        open=sum(1 for r in regels if r.status == "open"),
        gedaan=sum(1 for r in regels if r.status == "gedaan"),
    )


@router.get("/werklijst", response_model=schemas.WerklijstDto)
def werklijst(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.WerklijstDto:
    """Paneel "RLZ-werklijst": open + gedaan, kantoorbreed binnen scope."""
    return _werklijst_dto(service.werklijst(actor))


@router.post("/werklijst/{werklijst_id}/gedaan", response_model=schemas.WerklijstRegelDto)
def werklijst_gedaan(
    werklijst_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.WerklijstRegelDto:
    """Handmatige afvinkroute "Markeer als gedaan" (audit) — naast de dagelijkse hertoets."""
    try:
        r = service.markeer_gedaan(actor, werklijst_id=werklijst_id)
    except service.CrediteurenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.WerklijstRegelDto(**r.__dict__)
