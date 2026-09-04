"""Uren & meerwerk — veld-API (fase 2): de native app-endpoints voor de rollen ZZP'er,
uitvoerder en detacheerder (mockup uren-uitvoerder.html, 1-op-1).

Toegangslagen, alle server-side:
1. get_current_gebruiker (JWT + actuele rol/status + apparaat-kill-switch per request);
2. veldrol-poort (app/auth/rollen.py) + voorwaarden-/privacyverklaring-akkoord — zelfde
   fail-closed poort als de accordeur (detail 'voorwaarden_akkoord_vereist' → de app toont
   het akkoord-scherm);
3. de service dwingt per functie opt-in + koppeling/keurrecht/namens-koppeling af (RLS
   eronder als DB-vangnet).

De detacheerder gebruikt de ZZP-endpoints mét `namens`-parameter (exact dezelfde schermen en
velden, besluit 21-08); elke mutatie legt "ingevuld door X namens Y" vast."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.auth import voorwaarden
from app.auth.deps import (
    CurrentGebruiker,
    get_current_gebruiker,
    require_beheerder,
    require_meerwerk_urenstaten_recht,
    vereis_administratie_scope,
    vereis_kantoorrol,
)
from app.auth.rollen import is_veldrol
from app.uren import dossier as dossier_service
from app.uren import overzichten, planning, schemas, service
from app.uren import werkopdracht as werkopdracht_service

router = APIRouter(prefix="/uren", tags=["uren"])

VOORWAARDEN_AKKOORD_VEREIST = "voorwaarden_akkoord_vereist"


def vereis_veldrol(current: CurrentGebruiker = Depends(get_current_gebruiker)) -> CurrentGebruiker:
    """Veldrol + voorwaarden-akkoord (dezelfde informatieplicht-poort als de accordeur —
    zelfde app, zelfde activeringsflow)."""
    if not is_veldrol(current.rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor de rollen ZZP'er/uitvoerder/detacheerder"
        )
    if not voorwaarden.heeft_akkoord(gebruiker_id=current.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=VOORWAARDEN_AKKOORD_VEREIST)
    return current


def _vertaal(exc: service.UrenFout) -> HTTPException:
    if isinstance(exc, service.GeenToegang):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, service.NietGevonden):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, service.OngeldigeInvoer | service.RedenVerplicht):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, service.WeekstaatBevroren | service.OngeldigeOvergang | service.ModuleUitgeschakeld):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, dossier_service.DossierGeblokkeerd):
        # 423 Locked: de app herkent dit als dossier-handhaving (melding + upload-ingang).
        return HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(exc))
    if isinstance(exc, dossier_service.AlHerinnerdVandaag | dossier_service.DossierCompleet):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, dossier_service.HerinneringMislukt):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _dossier_response(stand: dossier_service.DossierStand) -> schemas.DossierDto:
    return schemas.DossierDto(
        administratie_id=stand.administratie_id,
        gebruiker_id=stand.gebruiker_id,
        gebruiker_naam=stand.gebruiker_naam,
        documenten=[schemas.DossierDocumentDto(**d.__dict__) for d in stand.documenten],
        aantal_verplicht=stand.aantal_verplicht,
        aantal_aanwezig=stand.aantal_aanwezig,
        aantal_ontbrekend=stand.aantal_ontbrekend,
        aantal_verlopen=stand.aantal_verlopen,
        aantal_verloopt_binnenkort=stand.aantal_verloopt_binnenkort,
        aantal_ter_controle=stand.aantal_ter_controle,
        compleet=stand.compleet,
        compleet_incl_ter_controle=stand.compleet_incl_ter_controle,
        herinneringen_teller=stand.herinneringen_teller,
        herinneringen_max=dossier_service.MAX_HERINNERINGEN,
        laatste_herinnering_op=stand.laatste_herinnering_op,
        geblokkeerd=stand.geblokkeerd,
        geblokkeerd_op=stand.geblokkeerd_op,
        kan_herinneren_vandaag=stand.kan_herinneren_vandaag,
        kvk_nummer=stand.kvk_nummer,
        btw_nummer=stand.btw_nummer,
        kvk_naam=stand.kvk_naam,
        kvk_plaats=stand.kvk_plaats,
        kvk_rechtsvorm=stand.kvk_rechtsvorm,
        kvk_bevestigd_op=stand.kvk_bevestigd_op,
        kvk_bevestigd_door_naam=stand.kvk_bevestigd_door_naam,
        signalen=stand.signalen,
    )


async def _lees_upload(bestand: UploadFile) -> tuple[str, str, bytes]:
    inhoud = await bestand.read()
    return bestand.filename or "document", bestand.content_type or "application/octet-stream", inhoud


def _bestand_response(naam: str, content_type: str, inhoud: bytes, *, bsn_gevoelig: bool) -> Response:
    headers = {"Content-Disposition": f'inline; filename="{naam}"', "Cache-Control": "no-store"}
    if bsn_gevoelig:
        headers["X-Dossier-Bsn-Gevoelig"] = "1"
    return Response(content=inhoud, media_type=content_type, headers=headers)


def _weekstaat_response(data: service.WeekstaatData) -> schemas.WeekstaatDto:
    return schemas.WeekstaatDto(
        id=data.id,
        administratie_id=data.administratie_id,
        gebruiker_id=data.gebruiker_id,
        gebruiker_naam=data.gebruiker_naam,
        project_id=data.project_id,
        project_naam=data.project_naam,
        jaar=data.jaar,
        weeknummer=data.weeknummer,
        status=data.status,
        totaal_uren=data.totaal_uren,
        totaal_m2=data.totaal_m2,
        dagen=[
            schemas.DagDto(
                id=d.id,
                datum=d.datum,
                uren=d.uren,
                m2=d.m2,
                opmerking=d.opmerking,
                ingevuld_door_naam=d.ingevuld_door_naam,
                namens=d.namens,
                voorstel_uren=d.voorstel_uren,
                voorstel_m2=d.voorstel_m2,
                voorstel_opmerking=d.voorstel_opmerking,
                buiten_planning=d.buiten_planning,
                dag_totaal_uren=d.dag_totaal_uren,
                boven_dagmax=d.boven_dagmax,
                dagmax_uren=d.dagmax_uren,
                gestempeld_uren=d.gestempeld_uren,
                stempel_van=d.stempel_van,
                stempel_tot=d.stempel_tot,
                stempel_onvolledig=d.stempel_onvolledig,
                stempel_afwijking=d.stempel_afwijking,
            )
            for d in data.dagen
        ],
        m2_geleverd_project=data.m2_geleverd_project,
        m2_gebouwd_project=data.m2_gebouwd_project,
        meer_gebouwd_dan_geleverd=data.meer_gebouwd_dan_geleverd,
        ingediend_op=data.ingediend_op,
        ingediend_door_naam=data.ingediend_door_naam,
        ingediend_namens=data.ingediend_namens,
        goedgekeurd_op=data.goedgekeurd_op,
        goedgekeurd_door_naam=data.goedgekeurd_door_naam,
        afgekeurd_op=data.afgekeurd_op,
        afgekeurd_door_naam=data.afgekeurd_door_naam,
        afkeur_reden=data.afkeur_reden,
    )


def _meerwerk_response(data: service.MeerwerkData) -> schemas.MeerwerkDto:
    return schemas.MeerwerkDto(
        id=data.id,
        administratie_id=data.administratie_id,
        project_id=data.project_id,
        project_naam=data.project_naam,
        omschrijving=data.omschrijving,
        aantal=data.aantal,
        eenheid=data.eenheid,
        datum_uitgevoerd=data.datum_uitgevoerd,
        in_opdracht_van=data.in_opdracht_van,
        heeft_foto=data.heeft_foto,
        foto_bestandsnaam=data.foto_bestandsnaam,
        gemeld_door_naam=data.gemeld_door_naam,
        gemeld_op=data.gemeld_op,
        status=data.status,
        prijs_per_eenheid=data.prijs_per_eenheid,
        bedrag=data.bedrag,
        facturatie_notitie=data.facturatie_notitie,
        beoordeeld_op=data.beoordeeld_op,
        beoordeeld_door_naam=data.beoordeeld_door_naam,
        afwijs_reden=data.afwijs_reden,
        doorbelast_op=data.doorbelast_op,
        verkoopfactuur_referentie=data.verkoopfactuur_referentie,
        vraag_tekst=data.vraag_tekst,
        vraag_gesteld_op=data.vraag_gesteld_op,
        vraag_antwoord=data.vraag_antwoord,
        vraag_beantwoord_op=data.vraag_beantwoord_op,
    )


# --- ZZP'er (en detacheerder via `namens`) ------------------------------------------------------


@router.get("/zzp/projecten", response_model=list[schemas.ProjectKaartDto])
def zzp_projecten(
    namens: uuid.UUID | None = None, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> list[schemas.ProjectKaartDto]:
    try:
        kaarten = overzichten.mijn_projecten_zzp(zzper_id=namens or actor.id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.ProjectKaartDto(**k.__dict__) for k in kaarten]


@router.get("/zzp/weken", response_model=list[schemas.WeekKaartDto])
def zzp_weken(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    namens: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> list[schemas.WeekKaartDto]:
    try:
        kaarten = overzichten.weken_overzicht_zzp(
            administratie_id=administratie_id,
            zzper_id=namens or actor.id,
            project_id=project_id,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.WeekKaartDto(**k.__dict__) for k in kaarten]


@router.get("/zzp/weken-overzicht", response_model=list[schemas.WeekOverzichtKaartDto])
def zzp_weken_overzicht(
    namens: uuid.UUID | None = None, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> list[schemas.WeekOverzichtKaartDto]:
    """Planning-gestuurd beginscherm (A2 04-09): huidige week + weken mét planning + weken mét
    een staat die nog om een handeling vraagt."""
    try:
        kaarten = overzichten.weken_zzp(zzper_id=namens or actor.id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.WeekOverzichtKaartDto(**k.__dict__) for k in kaarten]


@router.get("/zzp/week-projecten", response_model=list[schemas.WeekProjectKaartDto])
def zzp_week_projecten(
    jaar: int,
    weeknummer: int,
    namens: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> list[schemas.WeekProjectKaartDto]:
    """Projecten in één week (A1 04-09): ingepland én/of met een bestaande staat."""
    try:
        kaarten = overzichten.week_projecten_zzp(
            zzper_id=namens or actor.id, actor_id=actor.id, jaar=jaar, weeknummer=weeknummer
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.WeekProjectKaartDto(**k.__dict__) for k in kaarten]


@router.get("/zzp/projecten-keuze", response_model=list[schemas.ProjectKeuzeDto])
def zzp_projecten_keuze(
    namens: uuid.UUID | None = None, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> list[schemas.ProjectKeuzeDto]:
    """Uitwijk "+ ander project" (A1): alle actieve projecten in de scope."""
    try:
        keuzes = overzichten.projecten_keuze_zzp(zzper_id=namens or actor.id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.ProjectKeuzeDto(**k.__dict__) for k in keuzes]


@router.get("/zzp/weekstaat", response_model=schemas.WeekstaatZoekDto)
def zzp_weekstaat_zoeken(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    namens: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.WeekstaatZoekDto:
    """Lookup van de staat voor (ZZP'er, project, week) — null zolang er nog geen dagregel is."""
    try:
        data = overzichten.weekstaat_zoeken(
            administratie_id=administratie_id,
            zzper_id=namens or actor.id,
            project_id=project_id,
            jaar=jaar,
            weeknummer=weeknummer,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.WeekstaatZoekDto(weekstaat=_weekstaat_response(data) if data is not None else None)


@router.get("/zzp/ingediend", response_model=list[schemas.IngediendeWeekDto])
def zzp_ingediend(
    namens: uuid.UUID | None = None, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> list[schemas.IngediendeWeekDto]:
    try:
        items = overzichten.ingediende_weken(zzper_id=namens or actor.id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.IngediendeWeekDto(**i.__dict__) for i in items]


@router.put("/zzp/dag", response_model=schemas.WeekstaatDto)
def zzp_dag_zetten(
    payload: schemas.DagZettenRequest, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> schemas.WeekstaatDto:
    try:
        data = service.zet_dag(
            administratie_id=payload.administratie_id,
            zzper_id=payload.namens_zzper_id or actor.id,
            project_id=payload.project_id,
            jaar=payload.jaar,
            weeknummer=payload.weeknummer,
            datum=payload.datum,
            uren=payload.uren,
            m2=payload.m2,
            opmerking=payload.opmerking,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _weekstaat_response(data)


@router.post("/zzp/indienen", response_model=schemas.WeekstaatDto)
def zzp_week_indienen(
    payload: schemas.WeekIndienenRequest, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> schemas.WeekstaatDto:
    try:
        data = service.dien_week_in(
            administratie_id=payload.administratie_id,
            zzper_id=payload.namens_zzper_id or actor.id,
            project_id=payload.project_id,
            jaar=payload.jaar,
            weeknummer=payload.weeknummer,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _weekstaat_response(data)


@router.get("/weekstaten/{administratie_id}/{weekstaat_id}", response_model=schemas.WeekstaatDto)
def weekstaat_detail(
    administratie_id: uuid.UUID,
    weekstaat_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.WeekstaatDto:
    try:
        data = overzichten.weekstaat_detail_voor(
            administratie_id=administratie_id, weekstaat_id=weekstaat_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _weekstaat_response(data)


# --- planning: veld alleen-lezen (besluit B, planning-agenda 22-08) -------------------------------


@router.post("/stempels", response_model=schemas.StempelsOntvangenDto)
def stempels_registreren(
    invoer: schemas.StempelsInvoerDto,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.StempelsOntvangenDto:
    """Intake geofence-werkstempels (blok C 28-08, append-only, fail-closed): alleen de veldwerker
    zelf (nooit namens), alleen projecten mét een zone in eigen scope; idempotent op
    (gebruiker, project, tijdstip, soort). De native OS-registratie volgt in een eigen
    release-ronde — dit endpoint is er al voor."""
    from app.uren import stempels as stempel_service

    try:
        nieuw = stempel_service.registreer_stempels(
            actor_id=actor.id,
            apparaat_id=actor.apparaat_id,
            stempels=[
                stempel_service.StempelInvoer(
                    administratie_id=s.administratie_id,
                    project_id=s.project_id,
                    tijdstip=s.tijdstip,
                    soort=s.soort,
                    bron=s.bron,
                )
                for s in invoer.stempels
            ],
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.StempelsOntvangenDto(nieuw=nieuw)


@router.get("/stempels/zones", response_model=list[schemas.StempelZoneDto])
def stempel_zones(actor: CurrentGebruiker = Depends(vereis_veldrol)) -> list[schemas.StempelZoneDto]:
    """Projectzones voor de native OS-geofence (geofence-native, branch feat/geofence-native): de
    projecten mét zone uit de planning van deze en volgende week van de veldwerker ZELF (nooit
    namens — detacheerder = 403), max 20 (OS-limiet). De app ververst ze bij opening/voorgrond."""
    from app.uren import stempels as stempel_service

    try:
        zones = stempel_service.zones_voor_veldwerker(actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.StempelZoneDto(**z.__dict__) for z in zones]


@router.get("/stempels", response_model=list[schemas.StempelDto])
def eigen_stempels(
    datum: date | None = None,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> list[schemas.StempelDto]:
    """Eigen stempels van één dag (default vandaag) — transparantie voor de veldwerker (mockup §1
    "Vandaag"); nooit namens, geen export."""
    from app.uren import stempels as stempel_service

    try:
        rijen = stempel_service.eigen_stempels(actor_id=actor.id, dag=datum or date.today())
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [
        schemas.StempelDto(
            id=r.id,
            administratie_id=r.administratie_id,
            project_id=r.project_id,
            project_naam=r.project_naam,
            tijdstip=r.tijdstip,
            soort=r.soort,
            bron=r.bron,
        )
        for r in rijen
    ]


@router.get("/zzp/planning", response_model=list[schemas.MijnPlanningDagDto])
def zzp_planning(
    jaar: int,
    weeknummer: int,
    namens: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> list[schemas.MijnPlanningDagDto]:
    """De eigen planning voor één ISO-week, ALLEEN-LEZEN ("waar moet ik heen") — de ZZP'er of
    uitvoerder zelf, of de detacheerder namens een gekoppelde ZZP'er. Plannen doet uitsluitend
    het kantoor; de veld-API heeft bewust geen mutatiepad."""
    try:
        dagen = planning.mijn_planning(
            veldwerker_id=namens or actor.id, actor_id=actor.id, jaar=jaar, weeknummer=weeknummer
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [
        schemas.MijnPlanningDagDto(
            **{
                **d.__dict__,
                "werkopdrachten": [
                    schemas.WerkopdrachtDagTekstDto(groep_id=w.groep_id, tekst=w.tekst, afwijkend=w.afwijkend)
                    for w in d.werkopdrachten
                ],
            }
        )
        for d in dagen
    ]


# --- ZZP-dossier: veldkant (A1/A2 — upload in de app, blokkade-melding) --------------------------


@router.get("/dossier", response_model=schemas.DossierDto)
def mijn_dossier(
    administratie_id: uuid.UUID,
    namens: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.DossierDto:
    """Eigen dossier (ZZP'er/uitvoerder) of dat van een gekoppelde ZZP'er (detacheerder namens)."""
    try:
        stand = dossier_service.dossier_van(
            administratie_id=administratie_id, gebruiker_id=namens or actor.id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dossier_response(stand)


@router.post("/dossier/upload", response_model=schemas.DossierDto)
async def dossier_upload(
    administratie_id: uuid.UUID = Form(...),
    type_code: str = Form(...),
    geldig_tot: date | None = Form(default=None),
    namens: uuid.UUID | None = Form(default=None),
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.DossierDto:
    """Upload door de veldwerker zelf (of detacheerder namens) → status 'ter controle'; telt
    direct voor de deblokkade, als aanwezig pas ná goedkeuring door kantoor."""
    try:
        stand = dossier_service.upload_document(
            administratie_id=administratie_id,
            gebruiker_id=namens or actor.id,
            type_code=type_code,
            geldig_tot=geldig_tot,
            bestand=await _lees_upload(bestand),
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dossier_response(stand)


@router.get("/dossier/documenten/{administratie_id}/{document_id}/bestand")
def dossier_bestand_veld(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_veldrol)
) -> Response:
    try:
        naam, ctype, inhoud, gevoelig = dossier_service.document_inhoud(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _bestand_response(naam, ctype, inhoud, bsn_gevoelig=gevoelig)


# --- detacheerder --------------------------------------------------------------------------------


@router.get("/detacheerder/zzpers", response_model=list[schemas.ZzperKaartDto])
def detacheerder_zzpers(actor: CurrentGebruiker = Depends(vereis_veldrol)) -> list[schemas.ZzperKaartDto]:
    try:
        kaarten = overzichten.mijn_zzpers(detacheerder_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.ZzperKaartDto(**k.__dict__) for k in kaarten]


# --- uitvoerder ----------------------------------------------------------------------------------


@router.get("/uitvoerder/projecten", response_model=list[schemas.UitvoerderProjectKaartDto])
def uitvoerder_projecten(
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> list[schemas.UitvoerderProjectKaartDto]:
    try:
        kaarten = overzichten.uitvoerder_projecten(uitvoerder_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.UitvoerderProjectKaartDto(**k.__dict__) for k in kaarten]


@router.get("/uitvoerder/projecten/{administratie_id}/{project_id}", response_model=schemas.ProjectDetailDto)
def uitvoerder_projectdetail(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.ProjectDetailDto:
    try:
        detail = overzichten.projectdetail_uitvoerder(
            administratie_id=administratie_id, project_id=project_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ProjectDetailDto(
        administratie_id=detail.administratie_id,
        project_id=detail.project_id,
        project_naam=detail.project_naam,
        opdrachtgever=detail.opdrachtgever,
        werknummer_opdrachtgever=detail.werknummer_opdrachtgever,
        soort_werk=detail.soort_werk,
        contract_m2=detail.contract_m2,
        gebouwd_m2=detail.gebouwd_m2,
        looptijd_van=detail.looptijd_van,
        looptijd_tot=detail.looptijd_tot,
        huurtijd_omschrijving=detail.huurtijd_omschrijving,
        doorlopende_huur_omschrijving=detail.doorlopende_huur_omschrijving,
        documenten=[schemas.ProjectDocumentKaartDto(**d.__dict__) for d in detail.documenten],
        meerwerk=[_meerwerk_response(m) for m in detail.meerwerk],
    )


@router.get("/uitvoerder/te-keuren", response_model=list[schemas.TeKeurenItemDto])
def uitvoerder_te_keuren(actor: CurrentGebruiker = Depends(vereis_veldrol)) -> list[schemas.TeKeurenItemDto]:
    try:
        items = overzichten.te_keuren(uitvoerder_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.TeKeurenItemDto(**i.__dict__) for i in items]


@router.post("/uitvoerder/weekstaten/{administratie_id}/{weekstaat_id}/akkoord", response_model=schemas.WeekstaatDto)
def week_akkoord(
    administratie_id: uuid.UUID,
    weekstaat_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.WeekstaatDto:
    try:
        data = service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=weekstaat_id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _weekstaat_response(data)


@router.post("/uitvoerder/weekstaten/{administratie_id}/{weekstaat_id}/afkeuren", response_model=schemas.WeekstaatDto)
def week_afkeuren(
    administratie_id: uuid.UUID,
    weekstaat_id: uuid.UUID,
    payload: schemas.WeekAfkeurenRequest,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.WeekstaatDto:
    try:
        data = service.keur_week_af(
            administratie_id=administratie_id,
            weekstaat_id=weekstaat_id,
            actor_id=actor.id,
            reden=payload.reden,
            correcties=[
                service.DagCorrectieInvoer(datum=c.datum, uren=c.uren, m2=c.m2, opmerking=c.opmerking)
                for c in payload.correcties
            ],
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _weekstaat_response(data)


@router.post("/uitvoerder/meerwerk", response_model=schemas.MeerwerkDto, status_code=status.HTTP_201_CREATED)
async def meerwerk_melden(
    administratie_id: uuid.UUID = Form(...),
    project_id: uuid.UUID = Form(...),
    omschrijving: str = Form(...),
    aantal: str = Form(...),
    eenheid: str = Form(...),
    datum_uitgevoerd: date = Form(...),
    in_opdracht_van: str | None = Form(default=None),
    foto: UploadFile | None = File(default=None),
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.MeerwerkDto:
    """Multipart (mockup #meerwerk: één formulier mét optionele foto). `aantal` komt als
    string binnen (multipart kent geen Decimal) en wordt hier strikt geparsed."""
    try:
        aantal_decimal = Decimal(aantal.replace(",", "."))
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Ongeldig aantal: {aantal!r}"
        ) from exc
    foto_tuple: tuple[str, str, bytes] | None = None
    if foto is not None:
        inhoud = await foto.read()
        if inhoud:
            foto_tuple = (
                foto.filename or "foto",
                foto.content_type or "application/octet-stream",
                inhoud,
            )
    try:
        data = service.meld_meerwerk(
            administratie_id=administratie_id,
            project_id=project_id,
            actor_id=actor.id,
            omschrijving=omschrijving,
            aantal=aantal_decimal,
            eenheid=eenheid,
            datum_uitgevoerd=datum_uitgevoerd,
            in_opdracht_van=in_opdracht_van,
            foto=foto_tuple,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _meerwerk_response(data)


@router.post("/meerwerk/{administratie_id}/{meerwerk_id}/vraag-antwoord", response_model=schemas.MeerwerkDto)
def meerwerk_vraag_beantwoorden(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    payload: schemas.VraagAntwoordRequest,
    actor: CurrentGebruiker = Depends(vereis_veldrol),
) -> schemas.MeerwerkDto:
    try:
        data = service.beantwoord_vraag(
            administratie_id=administratie_id, meerwerk_id=meerwerk_id, actor_id=actor.id, tekst=payload.tekst
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _meerwerk_response(data)


@router.get("/meerwerk/{administratie_id}/{meerwerk_id}/foto")
def meerwerk_foto(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> Response:
    """Foto-weergave — voor de uitvoerder (toewijzing) én het kantoor (module-recht, fase-3-
    beoordeel-paneel); de service dwingt beide paden af."""
    try:
        naam, content_type, inhoud = overzichten.meerwerk_foto_inhoud(
            administratie_id=administratie_id, meerwerk_id=meerwerk_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return Response(
        content=inhoud,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{naam}"'},
    )


# --- kantoor (fase 3): module-recht + klantscope, server-side ------------------------------------


@router.get("/kantoor/stand", response_model=schemas.UrenStandDto)
def kantoor_stand(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.UrenStandDto:
    """Tellers voor de klantpagina-standen (toon-regel: blok alleen bij teller > 0) + het
    2-weken-bewakingssignaal. 403 zonder module-recht (de UI verbergt het blok dan), 409 als
    de administratie de opt-in niet aan heeft."""
    try:
        stand = service.uren_stand(administratie_id=administratie_id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.UrenStandDto(**stand.__dict__)


@router.get("/kantoor/meerwerk", response_model=list[schemas.MeerwerkDto])
def kantoor_meerwerk_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.MeerwerkDto]:
    try:
        items = service.meerwerk_lijst(administratie_id=administratie_id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [_meerwerk_response(m) for m in items]


@router.get(
    "/kantoor/meerwerk/{administratie_id}/{meerwerk_id}/contract-toets",
    response_model=list[schemas.StaffelRegelDto],
)
def kantoor_contract_toets(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.StaffelRegelDto]:
    """VOORSTEL uit de offerte-staffel (zelfde eenheid) — de mens bevestigt de prijs, de app
    rekent nooit zelf door naar een boeking. Leeg = geen staffel bekend, handmatig prijzen."""
    try:
        regels = service.contract_toets_voor_melding(
            administratie_id=administratie_id, meerwerk_id=meerwerk_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [schemas.StaffelRegelDto(**r.__dict__) for r in regels]


@router.post("/kantoor/meerwerk/{administratie_id}/{meerwerk_id}/goedkeuren", response_model=schemas.MeerwerkDto)
def kantoor_meerwerk_goedkeuren(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    payload: schemas.MeerwerkGoedkeurenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MeerwerkDto:
    try:
        data = service.keur_meerwerk_goed(
            administratie_id=administratie_id,
            meerwerk_id=meerwerk_id,
            actor_id=actor.id,
            prijs_per_eenheid=payload.prijs_per_eenheid,
            bedrag=payload.bedrag,
            facturatie_notitie=payload.facturatie_notitie,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _meerwerk_response(data)


@router.post("/kantoor/meerwerk/{administratie_id}/{meerwerk_id}/afwijzen", response_model=schemas.MeerwerkDto)
def kantoor_meerwerk_afwijzen(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    payload: schemas.MeerwerkAfwijzenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MeerwerkDto:
    try:
        data = service.wijs_meerwerk_af(
            administratie_id=administratie_id, meerwerk_id=meerwerk_id, actor_id=actor.id, reden=payload.reden
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _meerwerk_response(data)


@router.post("/kantoor/meerwerk/{administratie_id}/{meerwerk_id}/doorbelast", response_model=schemas.MeerwerkDto)
def kantoor_meerwerk_doorbelast(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    payload: schemas.MeerwerkDoorbelastRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MeerwerkDto:
    try:
        data = service.markeer_doorbelast(
            administratie_id=administratie_id,
            meerwerk_id=meerwerk_id,
            actor_id=actor.id,
            verkoopfactuur_referentie=payload.verkoopfactuur_referentie,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _meerwerk_response(data)


@router.post("/kantoor/meerwerk/{administratie_id}/{meerwerk_id}/vraag", response_model=schemas.MeerwerkDto)
def kantoor_meerwerk_vraag(
    administratie_id: uuid.UUID,
    meerwerk_id: uuid.UUID,
    payload: schemas.VraagAntwoordRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MeerwerkDto:
    try:
        data = service.stel_vraag(
            administratie_id=administratie_id, meerwerk_id=meerwerk_id, actor_id=actor.id, tekst=payload.tekst
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _meerwerk_response(data)


# --- kantoor: planning-agenda (mockup planning-steigerbouw.html, akkoord Peter 22-08) ------------


@router.get("/kantoor/planning", response_model=schemas.PlanningWeekDto)
def kantoor_planning(
    administratie_id: uuid.UUID,
    jaar: int,
    weeknummer: int,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.PlanningWeekDto:
    """Het weekgrid (v3, besluit Peter 23-08): ÁLLE actieve projecten als rijen — mét planning
    bovenaan, de rest compact (splitsing in de UI op per_datum) — kaartjes per dag, de
    mensen-pool (geplande dagen — besluit C: > 5 kleurt) en de controle-meldingen +
    dubbele-dag-teller (uitsluitend kantoor). Eén request levert alles incl. specs-metadata;
    de aparte zoekroute is vervallen. Toegang: module-recht + klantscope; opt-in."""
    try:
        data = planning.planning_overzicht(
            administratie_id=administratie_id, jaar=jaar, weeknummer=weeknummer, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.PlanningWeekDto(
        jaar=data.jaar,
        weeknummer=data.weeknummer,
        maandag=data.maandag,
        zondag=data.zondag,
        projecten=[
            schemas.PlanningProjectRijDto(
                project_id=rij.project_id,
                project_naam=rij.project_naam,
                opdrachtgever=rij.opdrachtgever,
                soort_werk=rij.soort_werk,
                looptijd_tot=rij.looptijd_tot,
                is_actief=rij.is_actief,
                week_man=rij.week_man,
                per_datum={
                    datum: [schemas.PlanningKaartDto(**k.__dict__) for k in kaarten]
                    for datum, kaarten in rij.per_datum.items()
                },
                werkopdrachten=[
                    schemas.WerkopdrachtKortDto(groep_id=w.groep_id, van=w.van, tot_en_met=w.tot_en_met, tekst=w.tekst)
                    for w in rij.werkopdrachten
                ],
                werkopdracht_overrides={
                    datum: [
                        schemas.WerkopdrachtDagTekstDto(groep_id=t.groep_id, tekst=t.tekst, afwijkend=t.afwijkend)
                        for t in teksten
                    ]
                    for datum, teksten in rij.werkopdracht_overrides.items()
                },
            )
            for rij in data.projecten
        ],
        pool=[schemas.PlanningPoolPersoonDto(**p.__dict__) for p in data.pool],
        buiten_planning=[schemas.BuitenPlanningMeldingDto(**m.__dict__) for m in data.buiten_planning],
        dubbele_dagen=[schemas.DubbeleDagMeldingDto(**m.__dict__) for m in data.dubbele_dagen],
        dubbele_dag_tellers=[schemas.DubbeleDagTellerDto(**t.__dict__) for t in data.dubbele_dag_tellers],
        wachtrisico=[schemas.WachtrisicoKortDto(**w.__dict__) for w in data.wachtrisico],
    )


@router.post("/kantoor/planning", status_code=status.HTTP_204_NO_CONTENT)
def kantoor_planning_plannen(
    payload: schemas.PlanningToewijzingRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    """Kaartje plannen (sleep uit de pool). FAILSAFE: zelfde persoon 2× op dezelfde dag op
    hetzélfde project = 422; maakt de projectkoppeling automatisch aan (besluit A, geaudit)."""
    try:
        planning.plan_toewijzing(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            project_id=payload.project_id,
            datum=payload.datum,
            dagdeel=payload.dagdeel,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/kantoor/planning/verwijderen", status_code=status.HTTP_204_NO_CONTENT)
def kantoor_planning_verwijderen(
    payload: schemas.PlanningVerwijderRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        planning.verwijder_toewijzing(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            project_id=payload.project_id,
            datum=payload.datum,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/kantoor/planning/verplaatsen", status_code=status.HTTP_204_NO_CONTENT)
def kantoor_planning_verplaatsen(
    payload: schemas.PlanningVerplaatsRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    """Kaartje tussen cellen slepen — atomair (nooit half verplaatst)."""
    try:
        planning.verplaats_toewijzing(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            van_project_id=payload.van_project_id,
            van_datum=payload.van_datum,
            naar_project_id=payload.naar_project_id,
            naar_datum=payload.naar_datum,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/kantoor/planning/dagdeel", status_code=status.HTTP_204_NO_CONTENT)
def kantoor_planning_dagdeel(
    payload: schemas.PlanningDagdeelRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        planning.zet_dagdeel(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            project_id=payload.project_id,
            datum=payload.datum,
            dagdeel=payload.dagdeel,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


# --- werkopdrachten per project × periode (akkoord Peter 31-08, migratie 0091) ------------------


def _werkopdracht_dto(data: werkopdracht_service.WerkopdrachtData) -> schemas.WerkopdrachtDto:
    return schemas.WerkopdrachtDto(
        groep_id=data.groep_id,
        project_id=data.project_id,
        versie=data.versie,
        van=data.van,
        tot_en_met=data.tot_en_met,
        tekst=data.tekst,
        dag_overrides=[schemas.WerkopdrachtDagOverrideDto(datum=o.datum, tekst=o.tekst) for o in data.dag_overrides],
        historie=[
            schemas.WerkopdrachtHistorieRegelDto(
                tijdstip=h.tijdstip, door_naam=h.door_naam, omschrijving=h.omschrijving
            )
            for h in data.historie
        ],
    )


@router.get("/kantoor/werkopdrachten", response_model=list[schemas.WerkopdrachtDto])
def kantoor_werkopdrachten(
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> list[schemas.WerkopdrachtDto]:
    """Alle werkopdrachten van één project: actuele versie + append-only historie + dag-overrides
    (de popup op de Personeel-tab)."""
    try:
        data = werkopdracht_service.werkopdrachten_project(
            administratie_id=administratie_id, project_id=project_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return [_werkopdracht_dto(w) for w in data]


@router.post("/kantoor/werkopdrachten", response_model=schemas.WerkopdrachtDto, status_code=status.HTTP_201_CREATED)
def kantoor_werkopdracht_aanmaken(
    payload: schemas.WerkopdrachtAanmakenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WerkopdrachtDto:
    try:
        data = werkopdracht_service.maak_werkopdracht(
            administratie_id=payload.administratie_id,
            project_id=payload.project_id,
            van=payload.van,
            tot_en_met=payload.tot_en_met,
            tekst=payload.tekst,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _werkopdracht_dto(data)


@router.post("/kantoor/werkopdrachten/{groep_id}/wijzigen", response_model=schemas.WerkopdrachtDto)
def kantoor_werkopdracht_wijzigen(
    groep_id: uuid.UUID,
    payload: schemas.WerkopdrachtWijzigenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WerkopdrachtDto:
    """Wijzigen = een nieuwe append-only versie; de oude blijft als historie zichtbaar."""
    try:
        data = werkopdracht_service.wijzig_werkopdracht(
            administratie_id=payload.administratie_id,
            groep_id=groep_id,
            van=payload.van,
            tot_en_met=payload.tot_en_met,
            tekst=payload.tekst,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _werkopdracht_dto(data)


@router.post("/kantoor/werkopdrachten/{groep_id}/dag-override", response_model=schemas.WerkopdrachtDto)
def kantoor_werkopdracht_dag_override(
    groep_id: uuid.UUID,
    payload: schemas.WerkopdrachtDagOverrideRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WerkopdrachtDto:
    """Afwijkende tekst voor één dag binnen de periode (sparse — alleen die dag wint)."""
    try:
        data = werkopdracht_service.zet_dag_override(
            administratie_id=payload.administratie_id,
            groep_id=groep_id,
            datum=payload.datum,
            tekst=payload.tekst,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _werkopdracht_dto(data)


@router.get("/kantoor/weekstaten/{administratie_id}/{weekstaat_id}", response_model=schemas.WeekstaatDto)
def kantoor_weekstaat_detail(
    administratie_id: uuid.UUID,
    weekstaat_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.WeekstaatDto:
    try:
        data = overzichten.weekstaat_detail_voor(
            administratie_id=administratie_id, weekstaat_id=weekstaat_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _weekstaat_response(data)


@router.get("/kantoor/mijn-toegang", response_model=schemas.MijnToegangDto)
def kantoor_mijn_toegang(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.MijnToegangDto:
    """C1/C2 (25-08): voeding voor de slimme landing en het Planning-hoofdmenu-item — module-recht +
    opt-in-administraties binnen de eigen scope. Alleen kantoorrollen; geen mutatie."""
    from app.auth import service as auth_service
    from app.db.models import GebruikerRol

    administraties = auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    return schemas.MijnToegangDto(
        heeft_meerwerk_recht=service.heeft_meerwerk_urenstaten_recht(gebruiker_id=actor.id, rol=actor.rol),
        administraties_met_opt_in=[a.id for a in administraties if a.uren_meerwerk_ingeschakeld],
        aantal_administraties_in_scope=len(administraties),
        is_beheerder=actor.rol == GebruikerRol.BEHEERDER,
        heeft_veldwerkerbeheer_recht=service.heeft_veldwerkerbeheer_recht(gebruiker_id=actor.id, rol=actor.rol),
        is_beheerder_of_bp=actor.rol in (GebruikerRol.BEHEERDER, GebruikerRol.BOEKHOUDING_PROJECTEN),
    )


# --- ZZP-dossier: kantoorkant (module-recht + klantscope) -------------------------------------------


@router.get("/kantoor/dossier/{administratie_id}/{gebruiker_id}", response_model=schemas.DossierDto)
def kantoor_dossier(
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DossierDto:
    try:
        stand = dossier_service.dossier_van(
            administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dossier_response(stand)


@router.post("/kantoor/dossier/{administratie_id}/{gebruiker_id}/upload", response_model=schemas.DossierDto)
async def kantoor_dossier_upload(
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    type_code: str = Form(...),
    geldig_tot: date | None = Form(default=None),
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DossierDto:
    try:
        stand = dossier_service.upload_document(
            administratie_id=administratie_id,
            gebruiker_id=gebruiker_id,
            type_code=type_code,
            geldig_tot=geldig_tot,
            bestand=await _lees_upload(bestand),
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dossier_response(stand)


@router.post(
    "/kantoor/dossier/{administratie_id}/documenten/{document_id}/beoordelen", response_model=schemas.DossierDto
)
def kantoor_dossier_beoordelen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: schemas.DossierBeoordelenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DossierDto:
    try:
        stand = dossier_service.beoordeel_document(
            administratie_id=administratie_id,
            document_id=document_id,
            goedgekeurd=payload.goedgekeurd,
            reden=payload.reden,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dossier_response(stand)


@router.get("/kantoor/dossier/{administratie_id}/documenten/{document_id}/bestand")
def kantoor_dossier_bestand(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> Response:
    """Inzage; een bsn-gevoelig document (kopie ID) wordt per inzage geauditeerd en de UI toont
    het standaard gemaskeerd (BSN-regel: nooit extraheren/indexeren)."""
    try:
        naam, ctype, inhoud, gevoelig = dossier_service.document_inhoud(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _bestand_response(naam, ctype, inhoud, bsn_gevoelig=gevoelig)


@router.post(
    "/kantoor/dossier/{administratie_id}/{gebruiker_id}/herinneren",
    response_model=schemas.DossierHerinneringResultaatDto,
)
def kantoor_dossier_herinneren(
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DossierHerinneringResultaatDto:
    """Herinner-knop (A2): push, anders mail; max 1/dag; teller "N van 3"; ná de 3e blokkeert
    het indienen van weekstaten voor deze veldwerker."""
    try:
        r = dossier_service.stuur_herinnering(
            administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.DossierHerinneringResultaatDto(**r.__dict__)


@router.get("/kantoor/kvk/{kvk_nummer}", response_model=schemas.KvkLookupDto)
def kantoor_kvk_lookup(
    kvk_nummer: str, actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht)
) -> schemas.KvkLookupDto:
    """KvK Basisprofiel-lookup (A3, Vastly-patroon): ter bevestiging door een mens — schrijft niets."""
    from app.integraties import kvk

    try:
        profiel = kvk.haal_basisprofiel(kvk_nummer.strip())
    except kvk.KvkConfiguratieFout as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except kvk.KvkFout as exc:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY if "8 cijfers" in str(exc) else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    if profiel is None:
        return schemas.KvkLookupDto(kvk_nummer=kvk_nummer, gevonden=False, testomgeving=kvk.is_testomgeving())
    return schemas.KvkLookupDto(
        kvk_nummer=kvk_nummer,
        gevonden=True,
        naam=profiel.get("naam"),
        rechtsvorm=profiel.get("rechtsvorm"),
        adres=profiel.get("adres"),
        postcode=profiel.get("postcode"),
        plaats=profiel.get("plaats"),
        uitgeschreven=bool(profiel.get("uitgeschreven")),
        datum_einde=profiel.get("datum_einde"),
        testomgeving=kvk.is_testomgeving(),
    )


@router.post("/kantoor/dossier/{administratie_id}/{gebruiker_id}/bedrijfsgegevens", response_model=schemas.DossierDto)
def kantoor_dossier_bedrijfsgegevens(
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    payload: schemas.BedrijfsgegevensBevestigenRequest,
    actor: CurrentGebruiker = Depends(require_meerwerk_urenstaten_recht),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DossierDto:
    try:
        stand = dossier_service.bevestig_bedrijfsgegevens(
            administratie_id=administratie_id,
            gebruiker_id=gebruiker_id,
            kvk_nummer=payload.kvk_nummer,
            btw_nummer=payload.btw_nummer,
            naam=payload.naam,
            plaats=payload.plaats,
            rechtsvorm=payload.rechtsvorm,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return _dossier_response(stand)


# --- beheer (Beheerder-only): koppelingen + module-recht ------------------------------------------


@router.get("/beheer/veldgebruikers", response_model=list[schemas.VeldgebruikerDto])
def beheer_veldgebruikers(actor: CurrentGebruiker = Depends(require_beheerder)) -> list[schemas.VeldgebruikerDto]:
    kaarten = overzichten.veldgebruikers_overzicht(actor_id=actor.id)
    return [
        schemas.VeldgebruikerDto(
            gebruiker_id=k.gebruiker_id,
            naam=k.naam,
            e_mail=k.e_mail,
            rol=k.rol,
            status=k.status,
            projecten=[schemas.ToewijzingDto(**t.__dict__) for t in k.projecten],
            zzpers=[schemas.GekoppeldeZzperDto(**z) for z in k.zzpers],
            crediteuren=[schemas.CrediteurKoppelingDto(**c.__dict__) for c in k.crediteuren],
            uren_afwijking_aantal=k.uren_afwijking_aantal,
            uren_afwijking_som=k.uren_afwijking_som,
            dossiers=[schemas.DossierSamenvattingDto(**d.__dict__) for d in k.dossiers],
        )
        for k in kaarten
    ]


@router.get("/beheer/dossier-documenttypen/{administratie_id}", response_model=schemas.DossierDocumenttypenDto)
def beheer_dossier_documenttypen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.DossierDocumenttypenDto:
    """Documenttypen als Beheerder-instelling per administratie (A1); `is_standaard` = nog nooit
    aangepast (de default-set geldt virtueel)."""
    try:
        typen, is_standaard = dossier_service.documenttypen(administratie_id=administratie_id, actor_id=actor.id)
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.DossierDocumenttypenDto(
        typen=[schemas.DossierDocumenttypeDto(**t.__dict__) for t in typen], is_standaard=is_standaard
    )


@router.put("/beheer/dossier-documenttypen/{administratie_id}", response_model=schemas.DossierDocumenttypenDto)
def beheer_dossier_documenttypen_zetten(
    administratie_id: uuid.UUID,
    payload: schemas.DossierDocumenttypenZettenRequest,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.DossierDocumenttypenDto:
    try:
        typen = dossier_service.zet_documenttypen(
            administratie_id=administratie_id,
            typen=[
                dossier_service.TypeDef(
                    code=t.code,
                    naam=t.naam,
                    verplicht=t.verplicht,
                    geldig_tot_vereist=t.geldig_tot_vereist,
                    bsn_gevoelig=t.bsn_gevoelig,
                    volgorde=t.volgorde,
                    actief=t.actief,
                )
                for t in payload.typen
            ],
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.DossierDocumenttypenDto(
        typen=[schemas.DossierDocumenttypeDto(**t.__dict__) for t in typen], is_standaard=False
    )


# C1 (addendum Peter 04-09): de handmatige projectkoppeling via de kantoor-UI is VERVALLEN — koppelingen
# ontstaan uitsluitend automatisch (planning, bron 'planning'; uren buiten planning via "+ ander project",
# bron 'weekstaat'). De toevoeg-route bestaat daarom niet meer; bestaande koppelingen blijven staan.
# Ontkoppelen blijft als Beheerder-only noodroute zonder UI (nooit stil, altijd geauditeerd).
@router.post("/beheer/projectkoppelingen/verwijderen", status_code=status.HTTP_204_NO_CONTENT)
def beheer_projectkoppeling_verwijderen(
    payload: schemas.ProjectKoppelingRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    try:
        service.ontkoppel_project(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            project_id=payload.project_id,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/beheer/detacheerderkoppelingen", status_code=status.HTTP_204_NO_CONTENT)
def beheer_detacheerderkoppeling_toevoegen(
    payload: schemas.DetacheerderKoppelingRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    try:
        service.koppel_detacheerder(
            detacheerder_id=payload.detacheerder_id, zzper_id=payload.zzper_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/beheer/detacheerderkoppelingen/verwijderen", status_code=status.HTTP_204_NO_CONTENT)
def beheer_detacheerderkoppeling_verwijderen(
    payload: schemas.DetacheerderKoppelingRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    try:
        service.ontkoppel_detacheerder(
            detacheerder_id=payload.detacheerder_id, zzper_id=payload.zzper_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/beheer/veldwerkercrediteuren", status_code=status.HTTP_204_NO_CONTENT)
def beheer_veldwerker_crediteur_koppelen(
    payload: schemas.VeldwerkerCrediteurRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    """Crediteur-koppeling + los ZZP-uurtarief (factuurmatch fase 3, upsert, geaudit)."""
    try:
        service.koppel_veldwerker_crediteur(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            vendor_id=payload.vendor_id,
            uurtarief=payload.uurtarief,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/beheer/veldwerkercrediteuren/verwijderen", status_code=status.HTTP_204_NO_CONTENT)
def beheer_veldwerker_crediteur_verwijderen(
    payload: schemas.VeldwerkerCrediteurVerwijderRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    try:
        service.ontkoppel_veldwerker_crediteur(
            administratie_id=payload.administratie_id, gebruiker_id=payload.gebruiker_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/beheer/veldwerkercrediteuren/autoboeken", status_code=status.HTTP_204_NO_CONTENT)
def beheer_veldwerker_autoboeken(
    payload: schemas.VeldwerkerAutoboekenRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    """Autoboek-opt-in per veldwerker-koppeling (factuurmatch fase 4, besluit 4 — Beheerder-
    only, default UIT, geaudit). Het slot blijft strikt: alleen een GROENE match incl. bedrag
    + álle bestaande poorten van het inkoop-autoboekpad boekt automatisch."""
    try:
        service.zet_veldwerker_autoboeken(
            administratie_id=payload.administratie_id,
            gebruiker_id=payload.gebruiker_id,
            ingeschakeld=payload.ingeschakeld,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.post("/beheer/detacheerderkoppelingen/tarief", status_code=status.HTTP_204_NO_CONTENT)
def beheer_detacheerder_tarief(
    payload: schemas.DetacheerderTariefRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> None:
    """Bureau-tarief per detacheerder↔zzp'er-koppeling (besluit 1, hoofdmechanisme match)."""
    try:
        service.zet_detacheerder_tarief(
            detacheerder_id=payload.detacheerder_id,
            zzper_id=payload.zzper_id,
            uurtarief=payload.uurtarief,
            actor_id=actor.id,
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc


@router.get("/beheer/module-recht", response_model=schemas.ModuleRechtHoudersDto)
def beheer_module_recht_houders(
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ModuleRechtHoudersDto:
    return schemas.ModuleRechtHoudersDto(gebruiker_ids=service.module_recht_houders(actor_id=actor.id))


@router.get("/beheer/veldwerkerbeheer-recht", response_model=schemas.ModuleRechtHoudersDto)
def beheer_veldwerkerbeheer_houders(
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ModuleRechtHoudersDto:
    return schemas.ModuleRechtHoudersDto(gebruiker_ids=service.veldwerkerbeheer_houders(actor_id=actor.id))


@router.put("/beheer/veldwerkerbeheer-recht", response_model=schemas.ModuleRechtDto)
def beheer_veldwerkerbeheer_zetten(
    payload: schemas.ModuleRechtRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.ModuleRechtDto:
    """Fijnmazig recht 'veldwerkerbeheer' aan/uit per kantoormedewerker (31-08, 0019-patroon:
    Beheerder-only toekennen, audit via de DB-trigger van migratie 0034, idempotent)."""
    try:
        ingeschakeld = service.zet_veldwerkerbeheer_recht(
            gebruiker_id=payload.gebruiker_id, ingeschakeld=payload.ingeschakeld, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ModuleRechtDto(gebruiker_id=payload.gebruiker_id, ingeschakeld=ingeschakeld)


@router.put("/beheer/module-recht", response_model=schemas.ModuleRechtDto)
def beheer_module_recht_zetten(
    payload: schemas.ModuleRechtRequest, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.ModuleRechtDto:
    """Module-recht 'Meerwerk & urenstaten' aan/uit per kantoormedewerker (0019-patroon:
    Beheerder-only, audit via de DB-trigger van migratie 0034, idempotent)."""
    try:
        ingeschakeld = service.zet_meerwerk_recht(
            gebruiker_id=payload.gebruiker_id, ingeschakeld=payload.ingeschakeld, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return schemas.ModuleRechtDto(gebruiker_id=payload.gebruiker_id, ingeschakeld=ingeschakeld)


@router.get("/projectdocumenten/{administratie_id}/{document_id}")
def projectdocument_inhoud(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> Response:
    """Contract-/offerte-PDF, alleen-lezen — uitvoerder met toewijzing of kantoor met recht."""
    try:
        naam, inhoud = overzichten.project_document_inhoud(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except service.UrenFout as exc:
        raise _vertaal(exc) from exc
    return Response(
        content=inhoud,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{naam}"'},
    )
