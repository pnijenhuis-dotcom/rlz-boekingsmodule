"""Transport + bestellingen + materiaal-API (blok D): prefix /materiaal/{administratie_id}/…
Toegang: kantoorrol (router-breed) + module-recht 'Meerwerk & urenstaten' + klantscope per
endpoint; leverancier-/catalogusbeheer = Beheerder óf Boekhouding+Projecten (besluit Peter
31-08, was Beheerder-only). Fout-vertaling identiek aan de uren-router."""

from __future__ import annotations

import contextlib
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.deps import (
    CurrentGebruiker,
    require_beheerder_of_bp,
    require_meerwerk_urenstaten_recht,
    vereis_administratie_scope,
    vereis_kantoorrol,
)
from app.materiaal import match as match_service
from app.materiaal import schemas
from app.materiaal import service as materiaal
from app.uren import service as uren_service

router = APIRouter(prefix="/materiaal", tags=["materiaal"], dependencies=[Depends(vereis_kantoorrol)])


def _vertaal(exc: uren_service.UrenFout) -> HTTPException:
    if isinstance(exc, uren_service.GeenToegang):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, uren_service.NietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, uren_service.OngeldigeInvoer):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, materiaal.VerzendenMislukt):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, uren_service.OngeldigeOvergang | uren_service.ModuleUitgeschakeld):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _dto(cls, obj):
    return cls(**obj.__dict__)


def _bestelling_dto(b: materiaal.BestellingData) -> schemas.BestellingDto:
    return schemas.BestellingDto(
        **{k: v for k, v in b.__dict__.items() if k not in ("regels", "revisies")},
        regels=[
            schemas.BestelRegelDto(
                product=_dto(schemas.ProductDto, r.product), aantal=r.aantal, was=r.was, geleverd=r.geleverd
            )
            for r in b.regels
        ],
        revisies=[_dto(schemas.RevisieDto, r) for r in b.revisies],
    )


def _transport_dto(t: materiaal.TransportData) -> schemas.TransportDto:
    return _dto(schemas.TransportDto, t)


# --- catalogus ---------------------------------------------------------------------------------------


@router.get("/{administratie_id}/leveranciers", response_model=list[schemas.LeverancierDto])
def leveranciers(
    administratie_id: uuid.UUID,
    zoek: str = "",
    alleen_actief: bool = True,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.LeverancierDto]:
    try:
        rijen = materiaal.leveranciers_overzicht(
            administratie_id=administratie_id, actor_id=actor.id, zoek=zoek, alleen_actief=alleen_actief
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [_dto(schemas.LeverancierDto, r) for r in rijen]


@router.put("/{administratie_id}/leveranciers", status_code=status.HTTP_200_OK)
def leverancier_zetten(
    administratie_id: uuid.UUID,
    payload: schemas.LeverancierZettenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder_of_bp),
) -> dict:
    try:
        lid = materiaal.zet_leverancier(
            administratie_id=administratie_id,
            actor_id=actor.id,
            leverancier_id=payload.id,
            naam=payload.naam,
            bestel_email=payload.bestel_email,
            telefoon=payload.telefoon,
            adres=payload.adres,
            vendor_id=payload.vendor_id,
            actief=payload.actief,
            transport_contact_naam=payload.transport_contact_naam,
            transport_contact_email=payload.transport_contact_email,
            materiaal_contact_naam=payload.materiaal_contact_naam,
            materiaal_contact_email=payload.materiaal_contact_email,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(lid)}


@router.get("/{administratie_id}/leveranciers/{leverancier_id}/catalogus", response_model=list[schemas.CategorieDto])
def catalogus(
    administratie_id: uuid.UUID,
    leverancier_id: uuid.UUID,
    alleen_actief: bool = True,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.CategorieDto]:
    try:
        cats = materiaal.catalogus(
            administratie_id=administratie_id,
            leverancier_id=leverancier_id,
            actor_id=actor.id,
            alleen_actief=alleen_actief,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [
        schemas.CategorieDto(
            id=c.id,
            naam=c.naam,
            bundel=c.bundel,
            volgorde=c.volgorde,
            actief=c.actief,
            producten=[_dto(schemas.ProductDto, p) for p in c.producten],
        )
        for c in cats
    ]


@router.get("/{administratie_id}/producten", response_model=schemas.ProductenPaginaDto)
def producten(
    administratie_id: uuid.UUID,
    leverancier_id: uuid.UUID | None = None,
    zoek: str = "",
    pagina: int = 1,
    per_pagina: int = 25,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProductenPaginaDto:
    try:
        items, totaal = materiaal.producten_overzicht(
            administratie_id=administratie_id,
            actor_id=actor.id,
            leverancier_id=leverancier_id,
            zoek=zoek,
            pagina=pagina,
            per_pagina=per_pagina,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ProductenPaginaDto(
        items=[_dto(schemas.ProductDto, p) for p in items],
        totaal=totaal,
        pagina=pagina,
        per_pagina=min(max(per_pagina, 1), materiaal.MAX_PER_PAGINA),
    )


@router.put("/{administratie_id}/categorieen")
def categorie_zetten(
    administratie_id: uuid.UUID,
    payload: schemas.CategorieZettenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder_of_bp),
) -> dict:
    try:
        cid = materiaal.zet_categorie(
            administratie_id=administratie_id,
            actor_id=actor.id,
            leverancier_id=payload.leverancier_id,
            categorie_id=payload.id,
            naam=payload.naam,
            bundel=payload.bundel,
            volgorde=payload.volgorde,
            actief=payload.actief,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(cid)}


@router.put("/{administratie_id}/producten")
def product_zetten(
    administratie_id: uuid.UUID,
    payload: schemas.ProductZettenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder_of_bp),
) -> dict:
    try:
        pid = materiaal.zet_product(
            administratie_id=administratie_id,
            actor_id=actor.id,
            leverancier_id=payload.leverancier_id,
            product_id=payload.id,
            categorie_id=payload.categorie_id,
            naam=payload.naam,
            verpakking=payload.verpakking,
            eenheid=payload.eenheid,
            m2_lengte=payload.m2_lengte,
            volgorde=payload.volgorde,
            actief=payload.actief,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(pid)}


@router.post("/{administratie_id}/seed-universal", response_model=schemas.SeedResultaatDto)
def seed_universal(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder_of_bp)
) -> schemas.SeedResultaatDto:
    """Standaardcatalogus uit de bestellijst laden (idempotent, nooit verwijderen)."""
    try:
        r = materiaal.seed_universal(administratie_id=administratie_id, actor_id=actor.id)
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dto(schemas.SeedResultaatDto, r)


# --- bestellingen -----------------------------------------------------------------------------------------


@router.get("/{administratie_id}/bestellingen", response_model=schemas.BestellingenPaginaDto)
def bestellingen(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    zoek: str = "",
    bestel_status: str | None = None,
    pagina: int = 1,
    per_pagina: int = 25,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BestellingenPaginaDto:
    try:
        items, totaal = materiaal.bestellingen_overzicht(
            administratie_id=administratie_id,
            actor_id=actor.id,
            project_id=project_id,
            zoek=zoek,
            status=bestel_status,
            pagina=pagina,
            per_pagina=per_pagina,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.BestellingenPaginaDto(
        items=[_bestelling_dto(b) for b in items],
        totaal=totaal,
        pagina=pagina,
        per_pagina=min(max(per_pagina, 1), materiaal.MAX_PER_PAGINA),
    )


@router.post("/{administratie_id}/bestellingen", status_code=status.HTTP_201_CREATED)
def bestelling_aanmaken(
    administratie_id: uuid.UUID,
    payload: schemas.BestellingAanmakenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> dict:
    try:
        bid = materiaal.maak_bestelling(
            administratie_id=administratie_id,
            actor_id=actor.id,
            project_id=payload.project_id,
            leverancier_id=payload.leverancier_id,
            gewenste_leverdatum=payload.gewenste_leverdatum,
            gewenste_levertijd=payload.gewenste_levertijd,
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(bid)}


@router.get("/{administratie_id}/bestellingen/{bestelling_id}", response_model=schemas.BestellingDto)
def bestelling_detail(
    administratie_id: uuid.UUID,
    bestelling_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BestellingDto:
    try:
        return _bestelling_dto(
            materiaal.bestelling_detail(
                administratie_id=administratie_id, bestelling_id=bestelling_id, actor_id=actor.id
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.put("/{administratie_id}/bestellingen/{bestelling_id}/concept", response_model=schemas.BestellingDto)
def bestelling_concept(
    administratie_id: uuid.UUID,
    bestelling_id: uuid.UUID,
    payload: schemas.BestellingConceptRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BestellingDto:
    try:
        return _bestelling_dto(
            materiaal.werk_concept_bij(
                administratie_id=administratie_id,
                actor_id=actor.id,
                bestelling_id=bestelling_id,
                regels=payload.regels,
                gewenste_leverdatum=payload.gewenste_leverdatum,
                gewenste_levertijd=payload.gewenste_levertijd,
                leveradres=payload.leveradres,
                contactpersoon=payload.contactpersoon,
                opmerking=payload.opmerking,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/bestellingen/{bestelling_id}/versturen", response_model=schemas.BestellingDto)
def bestelling_versturen(
    administratie_id: uuid.UUID,
    bestelling_id: uuid.UUID,
    payload: schemas.VersturenRequest | None = None,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BestellingDto:
    """Mens verstuurt expliciet: revisie r{n+1} + PDF-bon per mail (update-mail = alleen de
    gewijzigde regels oud → nieuw); mailfout = 502, niets vastgelegd, opnieuw mag."""
    try:
        return _bestelling_dto(
            materiaal.verstuur_bestelling(
                administratie_id=administratie_id,
                actor_id=actor.id,
                bestelling_id=bestelling_id,
                koppel_levering=payload.koppel_levering if payload else True,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/bestellingen/{bestelling_id}/annuleren", response_model=schemas.BestellingDto)
def bestelling_annuleren(
    administratie_id: uuid.UUID,
    bestelling_id: uuid.UUID,
    payload: schemas.RedenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BestellingDto:
    try:
        return _bestelling_dto(
            materiaal.annuleer_bestelling(
                administratie_id=administratie_id, actor_id=actor.id, bestelling_id=bestelling_id, reden=payload.reden
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.get("/{administratie_id}/bestellingen/{bestelling_id}/revisies/{revisie}/pdf")
def bestelling_pdf(
    administratie_id: uuid.UUID,
    bestelling_id: uuid.UUID,
    revisie: int,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> Response:
    try:
        naam, inhoud = materiaal.revisie_pdf(
            administratie_id=administratie_id, actor_id=actor.id, bestelling_id=bestelling_id, revisie=revisie
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return Response(
        content=inhoud, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{naam}"'}
    )


# --- transport ---------------------------------------------------------------------------------------------


@router.get("/{administratie_id}/transport", response_model=schemas.TransportWeekDto)
def transport_week(
    administratie_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportWeekDto:
    if not (1 <= weeknummer <= 53) or not (2000 <= jaar <= 2100):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ongeldige week")
    try:
        w = materiaal.transport_week(
            administratie_id=administratie_id, actor_id=actor.id, jaar=jaar, weeknummer=weeknummer
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.TransportWeekDto(
        jaar=w.jaar,
        weeknummer=w.weeknummer,
        maandag=w.maandag,
        zondag=w.zondag,
        projecten=[
            schemas.TransportProjectRijDto(
                project_id=r.project_id,
                project_naam=r.project_naam,
                opdrachtgever=r.opdrachtgever,
                is_actief=r.is_actief,
                per_datum={d: [_transport_dto(t) for t in items] for d, items in r.per_datum.items()},
                week_transporten=r.week_transporten,
                ploeg_label=r.ploeg_label,
            )
            for r in w.projecten
        ],
        wachtrisico=[_dto(schemas.WachtrisicoDto, m) for m in w.wachtrisico],
        aantal_transporten=w.aantal_transporten,
        bestellingen_concept=w.bestellingen_concept,
        bestellingen_met_wijzigingen=w.bestellingen_met_wijzigingen,
        materiaalmatch_open=w.materiaalmatch_open,
        te_plannen=[_dto(schemas.TePlannenDto, s) for s in w.te_plannen],
    )


@router.post("/{administratie_id}/transport", response_model=schemas.TransportDto, status_code=status.HTTP_201_CREATED)
def transport_plannen(
    administratie_id: uuid.UUID,
    payload: schemas.TransportPlannenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    try:
        return _transport_dto(
            materiaal.plan_transport(
                administratie_id=administratie_id,
                actor_id=actor.id,
                project_id=payload.project_id,
                leverancier_id=payload.leverancier_id,
                soort=payload.soort,
                datum=payload.datum,
                tijdstip=payload.tijdstip,
                regels=payload.regels,
                omschrijving=payload.omschrijving,
                bestelling_id=payload.bestelling_id,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.put("/{administratie_id}/transport/{transport_id}", response_model=schemas.TransportDto)
def transport_wijzigen(
    administratie_id: uuid.UUID,
    transport_id: uuid.UUID,
    payload: schemas.TransportWijzigenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    try:
        return _transport_dto(
            materiaal.wijzig_transport(
                administratie_id=administratie_id,
                actor_id=actor.id,
                transport_id=transport_id,
                datum=payload.datum,
                tijdstip=payload.tijdstip,
                regels=payload.regels,
                omschrijving=payload.omschrijving,
                project_id=payload.project_id,
                soort=payload.soort,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/transport/{transport_id}/status", response_model=schemas.TransportDto)
def transport_status(
    administratie_id: uuid.UUID,
    transport_id: uuid.UUID,
    payload: schemas.TransportStatusRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    """Statusovergangen zónder mail (31-08): definitief → geleverd, terug naar gereserveerd,
    annuleren mét reden. Bevestigen en definitief maken lopen via de eigen endpoints (mail-first).
    'geleverd' ververst de materiaalmatch van open facturen van de leverancier."""
    try:
        data = materiaal.zet_transport_status(
            administratie_id=administratie_id,
            actor_id=actor.id,
            transport_id=transport_id,
            nieuwe_status=payload.status,
            reden=payload.reden,
            bron="kantoor",
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    if payload.status == "geleverd":
        # Signalering, nooit een blokkade van de statuswijziging.
        with contextlib.suppress(Exception):
            match_service.herbereken_voor_leverancier(
                administratie_id=administratie_id, leverancier_id=data.leverancier_id
            )
    return _transport_dto(data)


@router.post("/{administratie_id}/transport/{transport_id}/bevestigen", response_model=schemas.TransportDto)
def transport_bevestigen(
    administratie_id: uuid.UUID,
    transport_id: uuid.UUID,
    payload: schemas.TransportBevestigRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    """Rood → oranje (31-08): verplichte voertuigtoezegging + bevestig-mail aan het
    transport-contact van de leverancier. Mailfout = 502, géén statuswijziging."""
    try:
        return _transport_dto(
            materiaal.bevestig_transport(
                administratie_id=administratie_id,
                actor_id=actor.id,
                transport_id=transport_id,
                voertuig=payload.voertuig,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/transport/{transport_id}/definitief", response_model=schemas.TransportDto)
def transport_definitief(
    administratie_id: uuid.UUID,
    transport_id: uuid.UUID,
    payload: schemas.TransportDefinitiefRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    """Oranje → groen (31-08): materiaallijst + transportplanner ingevuld — de volledige lijst
    gaat per mail naar het materiaal-contact. Mailfout = 502, niets gewijzigd."""
    try:
        return _transport_dto(
            materiaal.maak_definitief(
                administratie_id=administratie_id,
                actor_id=actor.id,
                transport_id=transport_id,
                regels=payload.regels,
                transportplanner=payload.transportplanner,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/transport/{transport_id}/materiaallijst", response_model=schemas.TransportDto)
def transport_materiaallijst(
    administratie_id: uuid.UUID,
    transport_id: uuid.UUID,
    payload: schemas.TransportMateriaallijstRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    """Materiaallijst wijzigen ná definitief (31-08): delta-mail (alleen gewijzigde regels
    oud → nieuw) aan het materiaal-contact — bestel-update-mailpatroon. Mailfout = 502,
    géén stille wijziging."""
    try:
        return _transport_dto(
            materiaal.wijzig_materiaallijst(
                administratie_id=administratie_id,
                actor_id=actor.id,
                transport_id=transport_id,
                regels=payload.regels,
                transportplanner=payload.transportplanner,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/transport/{transport_id}/verschuiven", response_model=schemas.TransportDto)
def transport_verschuiven(
    administratie_id: uuid.UUID,
    transport_id: uuid.UUID,
    payload: schemas.TransportVerschuifRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TransportDto:
    """Dag verschuiven (slepen, 31-08): terug naar gereserveerd — opnieuw bevestigen mét
    nieuwe voertuigtoezegging; materiaallijst + transportplanner blijven bewaard."""
    try:
        return _transport_dto(
            materiaal.verschuif_transport(
                administratie_id=administratie_id,
                actor_id=actor.id,
                transport_id=transport_id,
                nieuwe_datum=payload.datum,
            )
        )
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc


# --- materiaalstand + match ---------------------------------------------------------------------------------


@router.get("/{administratie_id}/stand/{project_id}", response_model=schemas.MateriaalStandDto)
def materiaalstand(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MateriaalStandDto:
    try:
        s = materiaal.materiaalstand(administratie_id=administratie_id, project_id=project_id, actor_id=actor.id)
    except uren_service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.MateriaalStandDto(
        **{k: v for k, v in s.__dict__.items() if k != "regels"},
        regels=[_dto(schemas.StandRegelDto, r) for r in s.regels],
    )


@router.get("/{administratie_id}/match/{document_id}", response_model=schemas.MateriaalmatchDto | None)
def materiaalmatch(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MateriaalmatchDto | None:
    m = match_service.lees_materiaalmatch(administratie_id=administratie_id, document_id=document_id)
    return _dto(schemas.MateriaalmatchDto, m) if m else None


@router.post("/{administratie_id}/match/{document_id}/herbereken", response_model=schemas.MateriaalmatchDto | None)
def materiaalmatch_herbereken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MateriaalmatchDto | None:
    m = match_service.draai_materiaalmatch(administratie_id=administratie_id, document_id=document_id)
    return _dto(schemas.MateriaalmatchDto, m) if m else None


_ = date  # (type-import gebruikt in de query-params hierboven)
