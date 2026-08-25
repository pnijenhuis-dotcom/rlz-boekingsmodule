"""HTTP-laag kantoor-projectenmodule (mockup projecten-invoer.html, akkoord Peter 22-08).

Toegang: router-breed `vereis_kantoorrol` (rollen-gate-patroon 2026-08-21) + per endpoint
`vereis_administratie_scope`; wijzigen is dáárbovenop server-side beperkt tot Beheerder en
Boekhouding+Projecten (app/projecten/kantoor.py::_vereis_schrijfrol — mockup-keuze 4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.db.session import scoped_session
from app.projecten import cijfers, cijfers_run, kantoor, ontleding
from app.projecten import schemas_kantoor as schemas
from app.projecten.motor import ProjectAanmakenMislukt, ProjectNaamConflict
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials

router = APIRouter(prefix="/projecten", tags=["projecten"], dependencies=[Depends(vereis_kantoorrol)])

_MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


def _vertaal(exc: kantoor.ProjectenFout) -> HTTPException:
    if isinstance(exc, kantoor.GeenSchrijfrecht):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, kantoor.ProjectNietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _specificatie_dto(spec) -> schemas.SpecificatieDto | None:
    if spec is None:
        return None
    return schemas.SpecificatieDto(
        opdrachtgever=spec.opdrachtgever,
        werknummer_opdrachtgever=spec.werknummer_opdrachtgever,
        soort_werk=spec.soort_werk,
        contract_m2=spec.contract_m2,
        looptijd_van=spec.looptijd_van,
        looptijd_tot=spec.looptijd_tot,
        huurtijd_omschrijving=spec.huurtijd_omschrijving,
        doorlopende_huur_omschrijving=spec.doorlopende_huur_omschrijving,
    )


@router.get("/{administratie_id}", response_model=schemas.ProjectenLijstResponse)
def projecten_lijst(
    administratie_id: uuid.UUID,
    zoek: str = "",
    alleen_actief: bool = True,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProjectenLijstResponse:
    rijen = kantoor.projecten_lijst(administratie_id=administratie_id, zoek=zoek, alleen_actief=alleen_actief)
    return schemas.ProjectenLijstResponse(
        projecten=[schemas.ProjectLijstRijDto(**rij.__dict__) for rij in rijen],
        # Mockup-keuze 5: "zonder specs" telt alleen projecten mét uren-/meerwerk-activiteit.
        zonder_specs=sum(1 for rij in rijen if rij.heeft_activiteit and rij.specs_status != "compleet"),
    )


@router.get("/{administratie_id}/volgend-nummer", response_model=schemas.VolgendNummerResponse)
def volgend_nummer(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VolgendNummerResponse:
    return schemas.VolgendNummerResponse(
        projectnummer=kantoor.volgende_projectnummer(administratie_id=administratie_id)
    )


@router.post("/{administratie_id}", response_model=schemas.NieuwProjectResponse, status_code=status.HTTP_201_CREATED)
def nieuw_project(
    administratie_id: uuid.UUID,
    invoer: schemas.NieuwProjectInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.NieuwProjectResponse:
    """Nieuw project conform de klant-naamconventie, via de bestaande RLZ-projectmotor-
    bouwstenen (idempotent — géén tweede motor); RLZ blijft de bron, de cache volgt direct."""
    try:
        resultaat = kantoor.maak_project_aan(
            administratie_id=administratie_id,
            actor_id=actor.id,
            projectnummer=invoer.projectnummer,
            plaats=invoer.plaats,
            opdrachtgever=invoer.opdrachtgever,
            startdatum=invoer.startdatum,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    except ProjectNaamConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (ProjectAanmakenMislukt, RlzApiError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.NieuwProjectResponse(
        rlz_project_id=resultaat.rlz_project_id, projectnaam=resultaat.projectnaam, bestond_al=resultaat.bestond_al
    )


@router.get("/{administratie_id}/resultaat-overzicht", response_model=schemas.ProjectenOverzichtResponse)
def resultaat_overzicht(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProjectenOverzichtResponse:
    """Cumulatief resultaat over álle actieve projecten mét activiteit — zelfde rekenlaag als
    het projectdetail (cijfers sluiten per definitie); gesorteerd op laagste marge eerst."""
    overzicht = cijfers.overzicht_alle_projecten(administratie_id=administratie_id)
    return schemas.ProjectenOverzichtResponse(
        baten_totaal=overzicht.baten_totaal,
        kosten_totaal_incl_onderweg=overzicht.kosten_totaal_incl_onderweg,
        uren_onderweg_totaal=overzicht.uren_onderweg_totaal,
        onbepaalbaar_uren_totaal=overzicht.onbepaalbaar_uren_totaal,
        meerwerk_onderweg_totaal=overzicht.meerwerk_onderweg_totaal,
        marge_totaal=overzicht.marge_totaal,
        marge_pct=overzicht.marge_pct,
        aandacht=overzicht.aandacht,
        rijen=[
            schemas.OverzichtRijDto(
                project_id=rij.cijfers.project_id,
                project_naam=rij.cijfers.project_naam,
                opdrachtgever=rij.cijfers.opdrachtgever,
                baten=rij.cijfers.baten_geboekt + rij.cijfers.meerwerk_onderweg_bedrag,
                kosten_incl_onderweg=rij.cijfers.kosten_geboekt + rij.cijfers.uren_onderweg_bedrag,
                marge=rij.cijfers.verwachte_marge,
                marge_pct=rij.cijfers.marge_pct,
                trend=rij.trend,
                kosten_zonder_omzet_weken=rij.kosten_zonder_omzet_weken,
                meerwerk_te_lang_niet_doorbelast=rij.meerwerk_te_lang_niet_doorbelast,
                doorlopende_huur=rij.doorlopende_huur,
                onbepaalbaar_uren=rij.cijfers.onbepaalbaar_uren,
            )
            for rij in overzicht.rijen
        ],
    )


@router.post(
    "/{administratie_id}/cijfers-sync",
    response_model=schemas.CijfersSyncStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def cijfers_sync(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.CijfersSyncStartResponse:
    """Start de verversing van de project_regel_cache als ACHTERGRONDRUN (fix 504-crash
    23-08: de volledige RLZ-ronde hoort niet in één request-response) — 202 + run_id; de UI
    pollt de status-leesroute hieronder. Een al lopende run wordt hergebruikt."""
    try:
        run = cijfers_run.start_achtergrondrun(administratie_id=administratie_id, actor_id=actor.id)
    except cijfers_run.CijfersSyncStartFout as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.CijfersSyncStartResponse(run_id=run.run_id, status=run.status)


@router.get("/{administratie_id}/cijfers-sync/status", response_model=schemas.CijfersSyncStatusResponse)
def cijfers_sync_status(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.CijfersSyncStatusResponse:
    """Status van de recentste syncrun (knop óf dagelijkse job): wachtrij/bezig/klaar/fout
    mét zichtbare foutreden en leesfouten-teller — nooit stil."""
    run = cijfers_run.laatste_run(administratie_id)
    if run is None:
        return schemas.CijfersSyncStatusResponse(status="geen")
    return schemas.CijfersSyncStatusResponse(
        status=run.status,
        run_id=run.run_id,
        aangevraagd_op=run.aangevraagd_op,
        gestart_op=run.gestart_op,
        beeindigd_op=run.beeindigd_op,
        documenten=run.documenten,
        regels=run.regels,
        verdwenen=run.verdwenen,
        leesfouten=run.leesfouten,
        fout_reden=run.fout_reden,
    )


@router.get("/{administratie_id}/{project_id}", response_model=schemas.ProjectDetailResponse)
def project_detail(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProjectDetailResponse:
    try:
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=project_id)
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ProjectDetailResponse(
        project_id=detail.project_id,
        naam=detail.naam,
        is_actief=detail.is_actief,
        specificatie=_specificatie_dto(detail.specificatie),
        documenten=[schemas.ProjectDocumentDto(**d.__dict__) for d in detail.documenten],
        staffels=[schemas.StaffelDto(**s.__dict__) for s in detail.staffels],
        werknummers=[schemas.WerknummerDto(**w.__dict__) for w in detail.werknummers],
        ontleding=[schemas.OntledingRegelDto(**r.__dict__) for r in detail.ontleding],
        gebouwd_m2=detail.gebouwd_m2,
        prijsafspraken=[schemas.PrijsafspraakDto(**a.__dict__) for a in detail.prijsafspraken],
        veldwerkers=[schemas.VeldwerkerKeuzeDto(**v.__dict__) for v in detail.veldwerkers],
    )


@router.post("/{administratie_id}/{project_id}/prijsafspraken", status_code=status.HTTP_201_CREATED)
def prijsafspraak_toevoegen(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    invoer: schemas.PrijsafspraakInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> dict:
    """Projectspecifieke prijsafspraak per veldwerker (steigerbouw-run B1): uur óf m², venster in
    ISO-weken; wint in de factuurmatch van het koppeling-tarief. Schrijven = Beheerder +
    Boekhouding+Projecten (service), geaudit."""
    if (invoer.geldig_vanaf_jaar is None) != (invoer.geldig_vanaf_week is None) or (invoer.geldig_tm_jaar is None) != (
        invoer.geldig_tm_week is None
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Jaar en week horen samen")
    try:
        afspraak_id = kantoor.voeg_prijsafspraak_toe(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=actor.id,
            gebruiker_id=invoer.gebruiker_id,
            eenheid=invoer.eenheid,
            tarief=invoer.tarief,
            geldig_vanaf=(invoer.geldig_vanaf_jaar, invoer.geldig_vanaf_week)
            if invoer.geldig_vanaf_jaar is not None
            else None,
            geldig_tm=(invoer.geldig_tm_jaar, invoer.geldig_tm_week) if invoer.geldig_tm_jaar is not None else None,
            toelichting=invoer.toelichting,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(afspraak_id)}


@router.post("/{administratie_id}/prijsafspraken/{afspraak_id}/intrekken", status_code=status.HTTP_204_NO_CONTENT)
def prijsafspraak_intrekken(
    administratie_id: uuid.UUID,
    afspraak_id: uuid.UUID,
    invoer: schemas.PrijsafspraakIntrekkenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        kantoor.trek_prijsafspraak_in(
            administratie_id=administratie_id, afspraak_id=afspraak_id, actor_id=actor.id, reden=invoer.reden
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc


@router.put("/{administratie_id}/{project_id}/specificatie", status_code=status.HTTP_204_NO_CONTENT)
def zet_specificatie(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    invoer: schemas.SpecificatieInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        kantoor.zet_specificatie(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=actor.id,
            opdrachtgever=invoer.opdrachtgever,
            werknummer_opdrachtgever=invoer.werknummer_opdrachtgever,
            soort_werk=invoer.soort_werk,
            contract_m2=invoer.contract_m2,
            looptijd_van=invoer.looptijd_van,
            looptijd_tot=invoer.looptijd_tot,
            huurtijd_omschrijving=invoer.huurtijd_omschrijving,
            doorlopende_huur_omschrijving=invoer.doorlopende_huur_omschrijving,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/{project_id}/staffels", status_code=status.HTTP_201_CREATED)
def staffel_toevoegen(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    invoer: schemas.StaffelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> dict:
    try:
        staffel_id = kantoor.voeg_staffel_toe(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=actor.id,
            omschrijving=invoer.omschrijving,
            eenheid=invoer.eenheid,
            prijs_per_eenheid=invoer.prijs_per_eenheid,
            verrekenbaar=invoer.verrekenbaar,
            bron=invoer.bron,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(staffel_id)}


@router.put("/{administratie_id}/staffels/{staffel_id}", status_code=status.HTTP_204_NO_CONTENT)
def staffel_wijzigen(
    administratie_id: uuid.UUID,
    staffel_id: uuid.UUID,
    invoer: schemas.StaffelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        kantoor.wijzig_staffel(
            administratie_id=administratie_id,
            staffel_id=staffel_id,
            actor_id=actor.id,
            omschrijving=invoer.omschrijving,
            eenheid=invoer.eenheid,
            prijs_per_eenheid=invoer.prijs_per_eenheid,
            verrekenbaar=invoer.verrekenbaar,
            bron=invoer.bron,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/{project_id}/documenten", status_code=status.HTTP_201_CREATED)
async def document_uploaden(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    bestand: UploadFile = File(...),
    soort: str = Form(...),
    titel: str = Form(""),
    versie_omschrijving: str = Form(""),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> dict:
    """Contract-/offerte-PDF per project (alleen-lezen zichtbaar voor de uitvoerder via de
    bestaande route /uren/projectdocumenten/…)."""
    naam = bestand.filename or "document.pdf"
    if not naam.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Alleen PDF")
    inhoud = await bestand.read()
    if len(inhoud) > _MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Bestand te groot (max 25 MB)")
    try:
        document_id = kantoor.upload_project_document(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=actor.id,
            soort=soort,
            titel=titel,
            bestandsnaam=naam,
            inhoud=inhoud,
            versie_omschrijving=versie_omschrijving or None,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(document_id)}


@router.post(
    "/{administratie_id}/{project_id}/documenten/{project_document_id}/ontleden",
    response_model=schemas.OntleedResponse,
)
def document_ontleden(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    project_document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OntleedResponse:
    """AI-ontleding als VOORSTEL (mens bevestigt per regel) — achter de per-administratie
    AVG-gate én de AI-kostengrens (poort in de client); uit/limiet = zichtbare fout,
    handmatig invullen blijft werken."""
    from app.aikosten.service import AiKostenLimietBereikt
    from app.extractie.client import AiExtractieFout, AiExtractieNietGeconfigureerd

    try:
        resultaat = ontleding.ontleed_document(
            administratie_id=administratie_id,
            project_id=project_id,
            project_document_id=project_document_id,
            actor_id=actor.id,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    except ontleding.OntledingUitgeschakeld as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AiKostenLimietBereikt as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except (AiExtractieFout, AiExtractieNietGeconfigureerd) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.OntleedResponse(
        project_document_id=resultaat.project_document_id, aantal_regels=resultaat.aantal_regels
    )


@router.post("/{administratie_id}/ontleding/{regel_id}/beslis", status_code=status.HTTP_204_NO_CONTENT)
def ontleding_beslissen(
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    invoer: schemas.OntledingBeslisInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        ontleding.beslis_regel(
            administratie_id=administratie_id,
            regel_id=regel_id,
            actor_id=actor.id,
            bevestigen=invoer.bevestigen,
            eenheid=invoer.eenheid,
            verrekenbaar=invoer.verrekenbaar,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/{administratie_id}/{project_id}/werknummers", status_code=status.HTTP_201_CREATED)
def werknummer_toevoegen(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    invoer: schemas.WerknummerInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> dict:
    try:
        werknummer_id = kantoor.voeg_werknummer_toe(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=actor.id,
            vendor_id=invoer.vendor_id,
            werknummer=invoer.werknummer,
        )
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc
    return {"id": str(werknummer_id)}


@router.post("/{administratie_id}/werknummers/{werknummer_id}/bevestig", status_code=status.HTTP_204_NO_CONTENT)
def werknummer_bevestigen(
    administratie_id: uuid.UUID,
    werknummer_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        kantoor.bevestig_werknummer(administratie_id=administratie_id, werknummer_id=werknummer_id, actor_id=actor.id)
    except kantoor.ProjectenFout as exc:
        raise _vertaal(exc) from exc


@router.get("/{administratie_id}/{project_id}/resultaat", response_model=schemas.ProjectResultaatResponse)
def project_resultaat(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ProjectResultaatResponse:
    """Resultaat per project (mockup view 3): tegels + weektabel met cumulatief — analytische
    laag, wordt nooit in RLZ geboekt, excl. AK-opslag."""
    with scoped_session(administratie_id) as session:
        data = cijfers.bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project_id)
    return schemas.ProjectResultaatResponse(
        project_id=data.project_id,
        project_naam=data.project_naam,
        opdrachtgever=data.opdrachtgever,
        baten_geboekt=data.baten_geboekt,
        kosten_geboekt=data.kosten_geboekt,
        uren_onderweg_bedrag=data.uren_onderweg_bedrag,
        uren_onderweg_uren=data.uren_onderweg_uren,
        onbepaalbaar_uren=data.onbepaalbaar_uren,
        meerwerk_onderweg_bedrag=data.meerwerk_onderweg_bedrag,
        onderweg_saldo=data.onderweg_saldo,
        verwachte_marge=data.verwachte_marge,
        marge_pct=data.marge_pct,
        weken=[schemas.ProjectWeekDto(**week.__dict__) for week in data.weken],
    )
