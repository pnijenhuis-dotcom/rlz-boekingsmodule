from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.documenten.boeken import BoekenUitgeschakeld, VolumeremBereikt
from app.documenten.checks import CheckRapport
from app.documenten.schemas import CheckRapportResponse, CheckResultaatDto
from app.doorbelasting import boeken, schemas, service
from app.doorbelasting.models import DoorbelastingMapping, DoorbelastingRegel
from app.rlz.aangifte import STORNO_BLOKKADE_MELDING, StornoGeblokkeerdDoorAangifte
from app.rlz.credentials import GeenRlzCredentials

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["doorbelasting"], dependencies=[Depends(vereis_kantoorrol)])


def _naar_check_rapport(rapport: CheckRapport) -> CheckRapportResponse:
    return CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding) for r in rapport.resultaten],
    )


def _naar_mapping(m: DoorbelastingMapping) -> schemas.MappingResponse:
    return schemas.MappingResponse(
        id=m.id,
        doelentiteit_naam=m.doelentiteit_naam,
        doel_customer_guid=m.doel_customer_guid,
        doel_administratie_id=m.doel_administratie_id,
        intercompany=m.intercompany,
        provisie_kosten_ledger_id=m.provisie_kosten_ledger_id,
        laatste_kosten_ledger_id=m.laatste_kosten_ledger_id,
        actief=m.actief,
    )


def _naar_regel(r: DoorbelastingRegel) -> schemas.VerdeelRegelResponse:
    return schemas.VerdeelRegelResponse(
        id=r.id,
        bron_regel_id=r.bron_regel_id,
        mapping_id=r.mapping_id,
        percentage=r.percentage,
        netto_deel=r.netto_deel,
        doel_kosten_ledger_id=r.doel_kosten_ledger_id,
    )


def _naar_run_response(data: service.RunReviewData) -> schemas.RunResponse:
    return schemas.RunResponse(
        id=data.run.id,
        document_id=data.run.document_id,
        status=data.run.status,
        laatste_fout=data.run.laatste_fout,
        regels=[_naar_regel(r) for r in data.regels],
        previews=[
            schemas.DoelentiteitPreviewResponse(
                mapping_id=p.mapping_id,
                doelentiteit_naam=p.doelentiteit_naam,
                onboarded=p.onboarded,
                netto_totaal=p.netto_totaal,
                provisie_bedrag=p.provisie_bedrag,
                btw_bedrag=p.btw_bedrag,
                boeking_status=p.boeking_status,
                boeking_id=p.boeking_id,
            )
            for p in data.previews
        ],
        checks=_naar_check_rapport(data.rapport),
    )


# --- instellingen + mapping (Beheerder-only, patroon beheer/router) -----------------------


@router.get("/doorbelasting/{administratie_id}/instelling", response_model=schemas.InstellingResponse)
def instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.InstellingResponse:
    instelling = service.haal_instelling_op(administratie_id=administratie_id)
    return schemas.InstellingResponse(
        administratie_id=administratie_id,
        provisie_percentage=instelling.provisie_percentage,
        btw_taxrate_id=instelling.btw_taxrate_id,
        omzet_ledger_id=instelling.omzet_ledger_id,
        provisie_omzet_ledger_id=instelling.provisie_omzet_ledger_id,
    )


@router.put("/doorbelasting/{administratie_id}/instelling", response_model=schemas.InstellingResponse)
def instelling_zetten(
    administratie_id: uuid.UUID,
    body: schemas.InstellingRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.InstellingResponse:
    instelling = service.zet_instelling(
        administratie_id=administratie_id,
        actor_id=actor.id,
        provisie_percentage=body.provisie_percentage,
        btw_taxrate_id=body.btw_taxrate_id,
        omzet_ledger_id=body.omzet_ledger_id,
        provisie_omzet_ledger_id=body.provisie_omzet_ledger_id,
    )
    return schemas.InstellingResponse(
        administratie_id=administratie_id,
        provisie_percentage=instelling.provisie_percentage,
        btw_taxrate_id=instelling.btw_taxrate_id,
        omzet_ledger_id=instelling.omzet_ledger_id,
        provisie_omzet_ledger_id=instelling.provisie_omzet_ledger_id,
    )


@router.get("/doorbelasting/{administratie_id}/mappings", response_model=list[schemas.MappingResponse])
def mappings_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> list[schemas.MappingResponse]:
    return [_naar_mapping(m) for m in service.lijst_mappings(administratie_id=administratie_id)]


@router.put(
    "/doorbelasting/{administratie_id}/mappings/{mapping_id}", response_model=schemas.MappingResponse
)
def mapping_wijzigen(
    administratie_id: uuid.UUID,
    mapping_id: uuid.UUID,
    body: schemas.MappingWijzigRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.MappingResponse:
    velden = body.model_dump(exclude_unset=True)
    try:
        mapping = service.wijzig_mapping(
            administratie_id=administratie_id,
            mapping_id=mapping_id,
            actor_id=actor.id,
            doel_administratie_id=velden.get("doel_administratie_id", ...),
            intercompany=velden.get("intercompany", ...),
            provisie_kosten_ledger_id=velden.get("provisie_kosten_ledger_id", ...),
            actief=velden.get("actief", ...),
        )
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _naar_mapping(mapping)


# --- run + verdeling + boeken (scope-gebonden) ---------------------------------------------


@router.get(
    "/doorbelasting/{administratie_id}/documenten/{document_id}/run", response_model=schemas.RunResponse
)
def run_voor_document(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    """Read-only leesroute voor het documentdetail-scherm: 404 als er (nog) geen run is —
    louter openen van een geboekt document maakt niets aan (de POST is de gebruikersactie)."""
    run = service.vind_run(administratie_id=administratie_id, document_id=document_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Geen doorbelasting-run voor dit document")
    data = service.review_data(administratie_id=administratie_id, run_id=run.id)
    return _naar_run_response(data)


@router.post(
    "/doorbelasting/{administratie_id}/documenten/{document_id}/run", response_model=schemas.RunResponse
)
def run_starten(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    try:
        run = service.start_of_haal_run(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
        data = service.review_data(administratie_id=administratie_id, run_id=run.id)
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_run_response(data)


@router.get("/doorbelasting/{administratie_id}/runs/{run_id}", response_model=schemas.RunResponse)
def run_ophalen(
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    try:
        data = service.review_data(administratie_id=administratie_id, run_id=run_id)
    except service.RunNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _naar_run_response(data)


@router.put("/doorbelasting/{administratie_id}/runs/{run_id}/verdeling", response_model=schemas.RunResponse)
def verdeling_opslaan(
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    body: schemas.VerdelingRequest,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    try:
        service.sla_verdeling_op(
            administratie_id=administratie_id,
            run_id=run_id,
            regels=[
                service.VerdeelRegelInvoerData(
                    bron_regel_id=r.bron_regel_id,
                    mapping_id=r.mapping_id,
                    percentage=r.percentage,
                    doel_kosten_ledger_id=r.doel_kosten_ledger_id,
                )
                for r in body.regels
            ],
            actor_id=actor.id,
        )
        data = service.review_data(administratie_id=administratie_id, run_id=run_id)
    except service.RunNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_run_response(data)


@router.post("/doorbelasting/{administratie_id}/runs/{run_id}/boeken", response_model=schemas.BoekResultaatResponse)
def run_boeken(
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekResultaatResponse:
    try:
        resultaat = boeken.boek_doorbelasting_run(
            administratie_id=administratie_id, run_id=run_id, actor_id=actor.id
        )
    except boeken.BoekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"melding": str(exc), "checks": _naar_check_rapport(exc.rapport).model_dump()},
        ) from exc
    except (BoekenUitgeschakeld, VolumeremBereikt, GeenRlzCredentials) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except boeken.AdministratieNietBereikbaar as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except service.RunNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.BoekResultaatResponse(per_doelentiteit=resultaat)


# --- open spiegel-taken + storno -----------------------------------------------------------


@router.get("/doorbelasting/{administratie_id}/opruimlijst", response_model=schemas.OpruimlijstResponse)
def opruimlijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OpruimlijstResponse:
    """Achtergebleven RLZ-concepten van gestorneerde/vervallen doorbelasting-runs — live scan
    tegen RLZ (klein volume). Informatief lijstje "handmatig opruimen indien gewenst"; de app
    verwijdert nooit iets in RLZ. Beheerder-only (leeft op Instellingen → Doorbelasting)."""
    from app.doorbelasting import reconciliatie

    resultaat = reconciliatie.verzamel_opruimlijst(administratie_id)
    return schemas.OpruimlijstResponse(
        kandidaten=[
            schemas.OpruimKandidaatResponse(
                concept_administratie_id=k.concept_administratie_id,
                kant=k.kant,
                rlz_id=k.rlz_id,
                document_id=k.document_id,
                referentie=k.referentie,
                reden=k.reden,
                detail=k.detail,
            )
            for k in resultaat.kandidaten
        ],
        fouten=resultaat.fouten,
    )


@router.get("/doorbelasting/{administratie_id}/spiegel-taken", response_model=list[schemas.SpiegelTaakResponse])
def spiegel_taken(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.SpiegelTaakResponse]:
    taken = service.open_spiegel_taken(administratie_id=administratie_id)
    mappings = {m.id: m for m in service.lijst_mappings(administratie_id=administratie_id)}
    return [
        schemas.SpiegelTaakResponse(
            boeking_id=t.id,
            document_id=t.document_id,
            mapping_id=t.mapping_id,
            doelentiteit_naam=mappings[t.mapping_id].doelentiteit_naam if t.mapping_id in mappings else "?",
            netto_totaal=t.netto_totaal,
            provisie_bedrag=t.provisie_bedrag,
            verkoop_referentie=t.verkoop_referentie,
            aangemaakt_op=t.aangemaakt_op,
        )
        for t in taken
    ]


@router.put(
    "/doorbelasting/{administratie_id}/boekingen/{boeking_id}/doel-gbs",
    status_code=status.HTTP_204_NO_CONTENT,
)
def spiegel_doel_gbs_zetten(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    body: schemas.SpiegelDoelGbsRequest,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    """GB-toewijzing voor een open spiegel-taak (de verdeling is bevroren; alleen GB's)."""
    try:
        service.zet_spiegel_doel_gbs(
            administratie_id=administratie_id,
            boeking_id=boeking_id,
            actor_id=actor.id,
            regel_gbs=body.regel_gbs,
            provisie_kosten_ledger_id=body.provisie_kosten_ledger_id,
        )
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/doorbelasting/{administratie_id}/boekingen/{boeking_id}/spiegel-boeken",
    response_model=schemas.BoekResultaatResponse,
)
def spiegel_alsnog_boeken(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekResultaatResponse:
    try:
        boeking = boeken.boek_spiegel_alsnog(
            administratie_id=administratie_id, boeking_id=boeking_id, actor_id=actor.id
        )
    except (BoekenUitgeschakeld, GeenRlzCredentials) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except boeken.AdministratieNietBereikbaar as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.BoekResultaatResponse(per_doelentiteit={str(boeking.mapping_id): boeking.status})


@router.post(
    "/doorbelasting/{administratie_id}/boekingen/{boeking_id}/storno",
    response_model=schemas.BoekResultaatResponse,
)
def boeking_storneren(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    body: schemas.StornoRequest,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekResultaatResponse:
    try:
        boeking = boeken.storno_doorbelasting_boeking(
            administratie_id=administratie_id,
            boeking_id=boeking_id,
            actor_id=actor.id,
            reden=body.reden,
        )
    except StornoGeblokkeerdDoorAangifte as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail_tekst()) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.BoekResultaatResponse(per_doelentiteit={str(boeking.mapping_id): boeking.status})


@router.get(
    "/doorbelasting/{administratie_id}/documenten/{document_id}/storno-toets",
    response_model=schemas.StornoToetsResponse,
)
def storno_toets(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.StornoToetsResponse:
    """Aangifte-poort als leesroute (opdracht 2026-08-16): de UI schakelt de storno-knop uit
    mét melding zodra één kant in een ingediende btw-aangifte valt — de POST hierboven blijft
    de echte poort. Fail-closed: geen credentials voor de bron = alles geblokkeerd (409 komt
    hier niet voor terug; de UI behandelt élke fout als geblokkeerd)."""
    try:
        per_boeking = boeken.storno_toets_voor_document(
            administratie_id=administratie_id, document_id=document_id
        )
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.StornoToetsResponse(
        per_boeking={
            boeking_id: schemas.BoekingStornoToetsDto(
                toegestaan=all(t.toegestaan for t in toetsen),
                melding=None if all(t.toegestaan for t in toetsen) else STORNO_BLOKKADE_MELDING,
                kanten=[
                    schemas.KantToetsDto(kant=t.kant, toegestaan=t.toegestaan, reden=t.reden)
                    for t in toetsen
                ],
            )
            for boeking_id, toetsen in per_boeking.items()
        }
    )
