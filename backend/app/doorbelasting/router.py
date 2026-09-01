from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status

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


def _naar_regel(r: DoorbelastingRegel, project_namen: dict[uuid.UUID, str] | None = None) -> schemas.VerdeelRegelResponse:
    return schemas.VerdeelRegelResponse(
        id=r.id,
        bron_regel_id=r.bron_regel_id,
        mapping_id=r.mapping_id,
        percentage=r.percentage,
        netto_deel=r.netto_deel,
        doel_kosten_ledger_id=r.doel_kosten_ledger_id,
        project_id=r.project_id,
        project_naam=(project_namen or {}).get(r.project_id) if r.project_id else None,
        project_aandeel=r.project_aandeel,
        verdeelbasis=r.verdeelbasis,
        m2=r.m2,
    )


def _naar_run_response(data: service.RunReviewData) -> schemas.RunResponse:
    return schemas.RunResponse(
        id=data.run.id,
        document_id=data.run.document_id,
        status=data.run.status,
        laatste_fout=data.run.laatste_fout,
        regels=[_naar_regel(r, data.project_namen) for r in data.regels],
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
                factuur_pdf_status=p.factuur_pdf_status,
                factuur_pdf_reden=p.factuur_pdf_reden,
                factuur_pdf_bestandsnaam=p.factuur_pdf_bestandsnaam,
                projecten=[
                    schemas.ProjectPreviewResponse(project_id=pp.project_id, naam=pp.naam, netto_totaal=pp.netto_totaal)
                    for pp in p.projecten
                ],
            )
            for p in data.previews
        ],
        checks=_naar_check_rapport(data.rapport),
        verdeelsleutel=(
            schemas.VerdeelsleutelKortResponse(
                id=data.verdeelsleutel.id,
                naam=data.verdeelsleutel.naam,
                versie=data.verdeelsleutel.versie,
                toegepast_op=data.verdeelsleutel.toegepast_op,  # type: ignore[arg-type]
            )
            if data.verdeelsleutel
            else None
        ),
    )


def _naar_verdeelsleutel(v) -> schemas.VerdeelsleutelResponse:
    return schemas.VerdeelsleutelResponse(
        id=v.id, naam=v.naam, versie=v.versie, actief=v.actief, definitie=v.definitie, aangemaakt_op=v.aangemaakt_op
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


@router.get(
    "/doorbelasting/{administratie_id}/mappings/kandidaat-doelen",
    response_model=schemas.KandidaatDoelenResponse,
)
def mapping_kandidaat_doelen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.KandidaatDoelenResponse:
    """"+ Doelentiteit toevoegen" (mockup doorbelasting-doel-toevoegen.html, akkoord 01-09):
    onboarded administraties die nog niet in de whitelist van deze bron staan, plus het
    provisie-GB-voorstel uit de bestaande rijen. Beheerder-only, net als het mapping-beheer."""
    kandidaten, voorstel = service.kandidaat_doelen(administratie_id=administratie_id)
    return schemas.KandidaatDoelenResponse(
        kandidaten=[schemas.KandidaatDoelDto(id=k.id, naam=k.naam) for k in kandidaten],
        provisie_voorstel=(
            schemas.ProvisieVoorstelDto(code=voorstel.code, naam=voorstel.naam) if voorstel else None
        ),
    )


@router.post(
    "/doorbelasting/{administratie_id}/mappings/debiteur-lookup",
    response_model=schemas.DebiteurLookupResponse,
)
def mapping_debiteur_lookup(
    administratie_id: uuid.UUID,
    body: schemas.DebiteurLookupRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.DebiteurLookupResponse:
    """Lookup op naam in de bron-RLZ: exacte én bijna-matches (enkelvoud/meervoud-tolerant,
    deterministisch — les Mantelzorgwoningen 01-09), mét kaartgegevens; de dialoog laat de
    mens expliciet bevestigen dat een treffer dezelfde entiteit is — nooit stil koppelen."""
    from app.rlz.client import RlzApiError

    try:
        matches = service.zoek_debiteur_in_bron(administratie_id=administratie_id, zoeknaam=body.zoeknaam)
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RlzApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reeleezee-lookup mislukt: {exc}",
        ) from exc
    return schemas.DebiteurLookupResponse(
        matches=[
            schemas.DebiteurMatchDto(customer_guid=m.customer_guid, naam=m.naam, exact=m.exact, kaart=m.kaart)
            for m in matches
        ]
    )


@router.post(
    "/doorbelasting/{administratie_id}/mappings",
    response_model=schemas.MappingResponse,
    status_code=status.HTTP_201_CREATED,
)
def mapping_aanmaken(
    administratie_id: uuid.UUID,
    body: schemas.MappingAanmaakRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.MappingResponse:
    """Nieuw POST-endpoint naast het bestaande wijzig-endpoint (de seed-CLI blijft voor
    bulk/herstel). Debiteur: bevestigde match = koppelen; geen match = idempotente aanmaak
    (zorg_voor_debiteur). De whitelist blijft server-side afgedwongen in de motor."""
    from app.rlz.client import RlzApiError
    from app.verkoop.debiteur import DebiteurAanmakenMislukt

    try:
        mapping = service.maak_mapping(
            administratie_id=administratie_id,
            actor_id=actor.id,
            doel_administratie_id=body.doel_administratie_id,
            doelentiteit_naam=body.doelentiteit_naam,
            doel_customer_guid=body.doel_customer_guid,
            provisie_kosten_ledger_id=body.provisie_kosten_ledger_id,
            intercompany=body.intercompany,
        )
    except (GeenRlzCredentials, DebiteurAanmakenMislukt, service.DoorbelastingFout) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RlzApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reeleezee niet bereikbaar bij de debiteur-koppeling: {exc}",
        ) from exc
    return _naar_mapping(mapping)


@router.put("/doorbelasting/{administratie_id}/mappings/{mapping_id}", response_model=schemas.MappingResponse)
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


@router.get("/doorbelasting/{administratie_id}/documenten/{document_id}/run", response_model=schemas.RunResponse)
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


@router.post("/doorbelasting/{administratie_id}/documenten/{document_id}/run", response_model=schemas.RunResponse)
def run_starten(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    try:
        run = service.start_of_haal_run(administratie_id=administratie_id, document_id=document_id, actor_id=actor.id)
        data = service.review_data(administratie_id=administratie_id, run_id=run.id)
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_run_response(data)


@router.post(
    "/doorbelasting/{administratie_id}/documenten/{document_id}/run/default",
    response_model=schemas.RunResponse | None,
    responses={204: {"description": "Geen run aangemaakt — eerdere keuze of niet klaarzetbaar"}},
)
def run_default_aan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    response: Response,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse | None:
    """Default-AAN (besluit Peter 25-08, deel 2 punt 5): het controlescherm zet het vinkje
    standaard aan — maakt alleen een klaargezette run als er nog nooit één was; 204 = niets
    aangemaakt (mens had 'm al uitgezet, of het document is niet klaarzetbaar)."""
    run = service.zet_run_default_klaar(administratie_id=administratie_id, document_id=document_id, actor_id=actor.id)
    if run is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    data = service.review_data(administratie_id=administratie_id, run_id=run.id)
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
                    project_ids=tuple(r.project_ids),
                    verdeelbasis=r.verdeelbasis,
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


# --- doorbelasting × projecten + verdeelsleutels (besluit Peter 25-08, deel 2 punt 2) ----------


@router.get(
    "/doorbelasting/{administratie_id}/mappings/{mapping_id}/projecten",
    response_model=schemas.DoelProjectenResponse,
)
def projecten_van_doelentiteit(
    administratie_id: uuid.UUID,
    mapping_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DoelProjectenResponse:
    """Projecten van de DOEL-administratie achter een whitelist-rij (voor de projectkeuze in de
    verdeel-UI): naam, actief, contract-m² — plus of het doel project_verplicht heeft. Alleen
    met scope op het doel (403), niet-onboarded doel = leeg."""
    try:
        projecten = service.projecten_voor_mapping(administratie_id=administratie_id, mapping_id=mapping_id, actor_id=actor.id)
    except service.GeenScopeOpDoel as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    mapping = next((m for m in service.lijst_mappings(administratie_id=administratie_id) if m.id == mapping_id), None)
    doel_id = mapping.doel_administratie_id if mapping else None
    verplicht = False
    if doel_id is not None:
        verplicht = service._project_verplicht_per_administratie({doel_id}).get(doel_id, (False, ""))[0]
    return schemas.DoelProjectenResponse(
        doel_administratie_id=doel_id,
        project_verplicht=verplicht,
        projecten=[
            schemas.DoelProjectResponse(id=p.id, naam=p.naam, is_actief=p.is_actief, contract_m2=p.contract_m2)
            for p in projecten
        ],
    )


@router.get("/doorbelasting/{administratie_id}/verdeelsleutels", response_model=list[schemas.VerdeelsleutelResponse])
def verdeelsleutels_lijst(
    administratie_id: uuid.UUID,
    alleen_actief: bool = True,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.VerdeelsleutelResponse]:
    return [
        _naar_verdeelsleutel(v)
        for v in service.lijst_verdeelsleutels(administratie_id=administratie_id, alleen_actief=alleen_actief)
    ]


@router.post(
    "/doorbelasting/{administratie_id}/verdeelsleutels",
    response_model=schemas.VerdeelsleutelResponse,
    status_code=status.HTTP_201_CREATED,
)
def verdeelsleutel_opslaan(
    administratie_id: uuid.UUID,
    body: schemas.VerdeelsleutelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VerdeelsleutelResponse:
    """Nieuwe sleutel of nieuwe versie onder een bestaande naam (append-only, geauditeerd)."""
    definitie = {
        "doelen": [
            {
                "mapping_id": str(d.mapping_id),
                "percentage": str(d.percentage),
                "doel_kosten_ledger_id": str(d.doel_kosten_ledger_id) if d.doel_kosten_ledger_id else None,
                "projecten": d.projecten if d.projecten == "alle_actief" else [str(p) for p in d.projecten],
                "verdeelbasis": d.verdeelbasis,
            }
            for d in body.doelen
        ]
    }
    try:
        sleutel = service.sla_verdeelsleutel_op(
            administratie_id=administratie_id, naam=body.naam, definitie=definitie, actor_id=actor.id
        )
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_verdeelsleutel(sleutel)


@router.post(
    "/doorbelasting/{administratie_id}/runs/{run_id}/verdeelsleutels/{sleutel_id}/toepassen",
    response_model=schemas.RunResponse,
)
def verdeelsleutel_toepassen(
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    sleutel_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    """Eén klik: de sleutel op alle bron-regels van de run toepassen (server rekent bindend);
    daarna nog aanpasbaar vóór opslaan. Run onthoudt sleutel(versie) + moment (QoE)."""
    try:
        service.pas_verdeelsleutel_toe(
            administratie_id=administratie_id, run_id=run_id, sleutel_id=sleutel_id, actor_id=actor.id
        )
        data = service.review_data(administratie_id=administratie_id, run_id=run_id)
    except service.RunNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_run_response(data)


@router.post("/doorbelasting/{administratie_id}/runs/{run_id}/vervallen", response_model=schemas.RunResponse)
def run_vervallen(
    administratie_id: uuid.UUID,
    run_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RunResponse:
    """Vinkje "Doorbelasten na boeken" weer uit (besluit 25-08): de klaargezette run wordt
    VERVALLEN — nooit een delete, spoor + audit blijven. 409 als de run niet meer klaargezet is
    (geboekt/bij de klant)."""
    try:
        service.laat_run_vervallen(administratie_id=administratie_id, run_id=run_id, actor_id=actor.id)
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
        resultaat = boeken.boek_doorbelasting_run(administratie_id=administratie_id, run_id=run_id, actor_id=actor.id)
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


@router.get("/doorbelasting/{administratie_id}/boekingen/{boeking_id}/factuur")
def factuur_pdf_downloaden(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> Response:
    """De rechtsgeldige factuur-PDF van een doorbelastings-boeking (blok A 26-08): onze
    bewaarkopie van RLZ's eigen render — dezelfde bytes als de bijlage op beide kanten. De
    frontend haalt 'm via fetch + blob (Authorization-header), nooit als kale navigatie."""
    try:
        naam, inhoud = service.factuur_pdf_van_boeking(administratie_id=administratie_id, boeking_id=boeking_id)
    except service.DoorbelastingFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{naam}"'},
    )


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
        per_boeking = boeken.storno_toets_voor_document(administratie_id=administratie_id, document_id=document_id)
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.StornoToetsResponse(
        per_boeking={
            boeking_id: schemas.BoekingStornoToetsDto(
                toegestaan=all(t.toegestaan for t in toetsen),
                melding=None if all(t.toegestaan for t in toetsen) else STORNO_BLOKKADE_MELDING,
                kanten=[schemas.KantToetsDto(kant=t.kant, toegestaan=t.toegestaan, reden=t.reden) for t in toetsen],
            )
            for boeking_id, toetsen in per_boeking.items()
        }
    )
