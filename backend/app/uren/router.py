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
from app.auth.deps import CurrentGebruiker, get_current_gebruiker
from app.auth.rollen import is_veldrol
from app.uren import overzichten, schemas, service

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
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


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
            )
            for d in data.dagen
        ],
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
        data = service.keur_week_goed(
            administratie_id=administratie_id, weekstaat_id=weekstaat_id, actor_id=actor.id
        )
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
            administratie_id=administratie_id, weekstaat_id=weekstaat_id, actor_id=actor.id, reden=payload.reden
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
