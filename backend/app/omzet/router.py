from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.documenten.boeken import (
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
)
from app.documenten.checks import CheckRapport
from app.documenten.schemas import CheckRapportResponse, CheckResultaatDto
from app.documenten.service import DocumentNietGevonden
from app.omzet import boeken, mapping, schemas, voorstel
from app.omzet.boeken import HalfGeboekt
from app.rlz.credentials import GeenRlzCredentials

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["omzet"], dependencies=[Depends(vereis_kantoorrol)])


def _naar_check_rapport(rapport: CheckRapport) -> CheckRapportResponse:
    return CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding) for r in rapport.resultaten],
    )


def _verkoop_categorie_velden(administratie_id: uuid.UUID) -> dict:
    """Peter 16-09: stand + keuzelijst uit `omzet_instelling` (de check/boekmotor ververst de cache live)."""
    from app.db.session import scoped_session
    from app.omzet import categorie as categorie_service

    with scoped_session(administratie_id) as session:
        stand = categorie_service.stand_voor(session, administratie_id)
        keuzes = categorie_service.cache_keuzes(session, administratie_id)
    return {
        "verkoop_categorie": schemas.VerkoopCategorieDto(
            id=stand.id, naam=stand.naam, binder=stand.binder, bron=stand.bron, is_inkomsten=stand.is_inkomsten
        ),
        "verkoop_categorieen": [
            schemas.VerkoopCategorieKeuzeDto(id=uuid.UUID(c.id), naam=c.naam, binder=c.binder, is_inkomsten=c.is_inkomsten)
            for c in keuzes
        ],
    }


def _naar_voorstel_response(
    data: voorstel.OmzetVoorstelData, administratie_id: uuid.UUID | None = None
) -> schemas.OmzetVoorstelResponse:
    extra = _verkoop_categorie_velden(administratie_id) if administratie_id is not None else {}
    return schemas.OmzetVoorstelResponse(
        document_id=data.document_id,
        periode_start=data.periode_start,
        periode_eind=data.periode_eind,
        rapport_totaal_omzet=data.rapport_totaal_omzet,
        rapport_totaal_kostprijs=data.rapport_totaal_kostprijs,
        marge_pct=data.marge_pct,
        regels=[
            schemas.OmzetRegelDto(
                categorie=r.categorie,
                categorie_sleutel=r.categorie_sleutel,
                omzet_bedrag=r.omzet_bedrag,
                kostprijs_bedrag=r.kostprijs_bedrag,
                omzet_ledger_id=r.omzet_ledger_id,
                taxrate_id=r.taxrate_id,
                kostprijs_ledger_id=r.kostprijs_ledger_id,
                herkomst=r.herkomst,
                btw_herkomst=r.btw_herkomst,
                btw_herkomst_detail=r.btw_herkomst_detail,
            )
            for r in data.regels
        ],
        voorraad_ledger_id=data.voorraad_ledger_id,
        opgeslagen=data.opgeslagen,
        rapport_titel=data.rapport_titel,
        entiteit_naam=data.entiteit_naam,
        bron=data.bron,
        bron_detail=data.bron_detail,
        **extra,
    )


@router.put(
    "/administraties/{administratie_id}/omzet/verkoop-categorie",
    response_model=schemas.VerkoopCategorieDto,
)
def omzet_verkoop_categorie_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.VerkoopCategorieInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerkoopCategorieDto:
    """Blok B2 (Peter 16-09): de medewerker kiest in het omzet-controlescherm de RLZ-categorie (uit de gesynchroniseerde
    keuzelijst) — mens wint voor dit document én wordt de default van de administratie (bron 'mens'), audit oud→nieuw
    + tijdlijn. Kantoorrol binnen de scope (de router-poort `vereis_kantoorrol` dekt de hele omzet-router)."""
    from app.omzet import categorie as categorie_service

    try:
        stand = categorie_service.zet_verkoop_categorie_mens(
            administratie_id=administratie_id,
            actor_id=actor.id,
            categorie_id=invoer.categorie_id,
            document_id=invoer.document_id,
        )
    except categorie_service.CategorieOnbekend as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return schemas.VerkoopCategorieDto(
        id=stand.id, naam=stand.naam, binder=stand.binder, bron=stand.bron, is_inkomsten=stand.is_inkomsten
    )


@router.get(
    "/administraties/{administratie_id}/omzet/bron-instellingen",
    response_model=schemas.OmzetBronInstellingenDto,
)
def omzet_bron_instellingen_ophalen(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetBronInstellingenDto:
    """Omzetbronnen (Peter 15-09 + besluiten 16-09): stores → administratie, productnaam → categorie, tegenrekening per
    betaalwijze, btw per categorie, combi-regel, PSP — plus read-only `defaults` en de keuzelijsten."""
    from app.db.session import scoped_session

    with scoped_session(administratie_id, actor_id=actor.id) as session:
        return _bron_instellingen_dto(session, administratie_id)


def _bron_instellingen_dto(session, administratie_id: uuid.UUID) -> schemas.OmzetBronInstellingenDto:  # noqa: ANN001
    from app.omzet.bronnen import service as bronnen_service

    inst = bronnen_service.bron_instellingen_voor(session, administratie_id)
    return schemas.OmzetBronInstellingenDto(
        **inst,
        defaults=bronnen_service.defaults_voor(session, administratie_id, instellingen=inst),
        rekeningen=[
            schemas.RekeningKeuzeDto(ledger_id=r.ledger_id, code=r.code, naam=r.naam)
            for r in bronnen_service.rekeningen_voor(session, administratie_id)
        ],
        tarieven=[
            schemas.TariefKeuzeDto(
                taxrate_id=t.taxrate_id, naam=t.naam, percentage=t.percentage, is_verlegd=t.is_verlegd
            )
            for t in bronnen_service.tarieven_voor(session, administratie_id)
        ],
    )


@router.put(
    "/administraties/{administratie_id}/omzet/bron-instellingen",
    response_model=schemas.OmzetBronInstellingenDto,
)
def omzet_bron_instellingen_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.OmzetBronInstellingenInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetBronInstellingenDto:
    """Beheerder-only (Instellingen › Administraties › ‹studio› › Omzet); audit oud→nieuw."""
    from app.db.session import scoped_session
    from app.omzet.bronnen import service as bronnen_service

    try:
        bronnen_service.zet_bron_instellingen(
            administratie_id=administratie_id,
            actor_id=actor.id,
            waarden={k: v for k, v in invoer.model_dump().items() if v is not None},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        return _bron_instellingen_dto(session, administratie_id)


# ---------------------------------------------------------------------------- store → administratie (0151, 16-09)


def _store_dto(info) -> schemas.OmzetStoreDto:  # noqa: ANN001
    return schemas.OmzetStoreDto(
        id=info.id,
        store_naam=info.store_naam,
        store_norm=info.store_norm,
        administratie_id=info.administratie_id,
        administratie_naam=info.administratie_naam,
        actief=info.actief,
        bron=info.bron,
        gewijzigd_op=info.gewijzigd_op,
    )


def _vertaal_store_fout(exc: Exception) -> HTTPException:
    from app.omzet.bronnen import stores as stores_service

    if isinstance(exc, stores_service.StoreOnbekend):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/instellingen/omzet/stores", response_model=schemas.OmzetStoresDto)
def omzet_stores_lijst(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.OmzetStoresDto:
    """Platformbrede store-routering (Peter 16-09 avond, migratie 0151): welke "Store Used" uit een zonnestudio-dagstaat
    landt in welke administratie. Lezen = kantoorrol (de verzamelbak-rij linkt hierheen), schrijven = Beheerder."""
    from app.omzet.bronnen import stores as stores_service

    return schemas.OmzetStoresDto(
        stores=[_store_dto(i) for i in stores_service.lijst(actor_id=actor.id)],
        doel_pad=stores_service.DOEL_PAD_STORES,
    )


@router.post("/instellingen/omzet/stores", response_model=schemas.OmzetStoreDto)
def omzet_store_koppelen(
    invoer: schemas.OmzetStoreKoppelInput, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OmzetStoreDto:
    """Beheerder: store → administratie (upsert op de genormaliseerde naam; verhuizen = dezelfde rij; audit oud→nieuw).
    Twee administraties voor dezelfde store kan niet — de unieke index en de upsert maken dat structureel onmogelijk."""
    from app.omzet.bronnen import stores as stores_service

    try:
        info = stores_service.koppel(store=invoer.store, administratie_id=invoer.administratie_id, actor_id=actor.id)
    except stores_service.StoreFout as exc:
        raise _vertaal_store_fout(exc) from exc
    return _store_dto(info)


@router.put("/instellingen/omzet/stores/{routering_id}", response_model=schemas.OmzetStoreDto)
def omzet_store_wijzigen(
    routering_id: uuid.UUID, invoer: schemas.OmzetStoreWijzigInput, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OmzetStoreDto:
    """Beheerder: andere administratie en/of ontkoppelen (actief=false) / opnieuw activeren. Nooit verwijderen."""
    from app.omzet.bronnen import stores as stores_service

    try:
        info = None
        if invoer.administratie_id is not None:
            huidig = next((s for s in stores_service.lijst(actor_id=actor.id) if s.id == routering_id), None)
            if huidig is None:
                raise stores_service.StoreOnbekend(f"Onbekende store-routering {routering_id}")
            info = stores_service.koppel(
                store=huidig.store_naam,
                administratie_id=invoer.administratie_id,
                actor_id=actor.id,
                actief=huidig.actief if invoer.actief is None else invoer.actief,
            )
        if invoer.actief is not None:
            info = stores_service.zet_actief(routering_id=routering_id, actief=invoer.actief, actor_id=actor.id)
        if info is None:
            raise stores_service.StoreFout("Geef een administratie en/of de actief-stand op")
    except stores_service.StoreFout as exc:
        raise _vertaal_store_fout(exc) from exc
    return _store_dto(info)


@router.get(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/voorstel",
    response_model=schemas.OmzetVoorstelResponse,
)
def omzet_voorstel_ophalen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetVoorstelResponse:
    try:
        data = voorstel.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voorstel.GeenKassarapport as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_voorstel_response(data, administratie_id)


@router.put(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/voorstel",
    response_model=schemas.OmzetVoorstelResponse,
)
def omzet_voorstel_opslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.OmzetVoorstelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetVoorstelResponse:
    try:
        data = voorstel.sla_omzet_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            periode_start=invoer.periode_start,
            periode_eind=invoer.periode_eind,
            rapport_totaal_omzet=invoer.rapport_totaal_omzet,
            rapport_totaal_kostprijs=invoer.rapport_totaal_kostprijs,
            regels=[
                voorstel.OmzetRegelInput(
                    categorie=r.categorie,
                    omzet_bedrag=r.omzet_bedrag,
                    kostprijs_bedrag=r.kostprijs_bedrag,
                    omzet_ledger_id=r.omzet_ledger_id,
                    taxrate_id=r.taxrate_id,
                    kostprijs_ledger_id=r.kostprijs_ledger_id,
                )
                for r in invoer.regels
            ],
            voorraad_ledger_id=invoer.voorraad_ledger_id,
            mapping_onthouden=invoer.mapping_onthouden,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voorstel.GeenKassarapport as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except voorstel.OmzetVoorstelFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_voorstel_response(data, administratie_id)


@router.post(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/checks",
    response_model=schemas.OmzetVoorstelMetChecksResponse,
)
def omzet_checks_uitvoeren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetVoorstelMetChecksResponse:
    try:
        rapport = voorstel.voer_omzet_checks_uit(administratie_id=administratie_id, document_id=document_id)
        data = voorstel.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (voorstel.GeenKassarapport, voorstel.OmzetVoorstelFout) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.OmzetVoorstelMetChecksResponse(
        voorstel=_naar_voorstel_response(data, administratie_id), checks=_naar_check_rapport(rapport)
    )


@router.post(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/boeken",
    response_model=schemas.OmzetBoekenResponse,
)
def omzet_boeken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetBoekenResponse:
    try:
        resultaat = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "melding": "Boeken geblokkeerd door harde checks",
                "checks": _naar_check_rapport(exc.rapport).model_dump(mode="json"),
            },
        ) from exc
    except (OngeldigeBoekpoging, BoekenUitgeschakeld, VolumeremBereikt) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HalfGeboekt as exc:
        # 502: de fout ligt aan de RLZ-kant én er is een halve boeking die aandacht vraagt —
        # de melding zelf legt het herstelpad uit (omzet-reconciliatie).
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RlzBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.OmzetBoekenResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        verkoop_rlz_id=resultaat.verkoop_rlz_id,
        verkoop_referentie=resultaat.verkoop_referentie,
        verkoop_boekstuknummer=resultaat.verkoop_boekstuknummer,
        memoriaal_rlz_id=resultaat.memoriaal_rlz_id,
        memoriaal_boekstuknummer=resultaat.memoriaal_boekstuknummer,
    )


@router.get(
    "/administraties/{administratie_id}/omzet/mappingen",
    response_model=schemas.OmzetMappingLijstResponse,
)
def omzet_mappingen_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetMappingLijstResponse:
    return schemas.OmzetMappingLijstResponse(
        mappingen=[
            schemas.OmzetMappingDto(
                categorie_sleutel=m.categorie_sleutel,
                weergave_naam=m.weergave_naam,
                omzet_ledger_id=m.omzet_ledger_id,
                taxrate_id=m.taxrate_id,
                kostprijs_ledger_id=m.kostprijs_ledger_id,
            )
            for m in mapping.lijst_mappings(administratie_id=administratie_id)
        ]
    )
