from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.auth.deps import CurrentGebruiker, vereis_kantoorrol
from app.documenten.service import DocumentNietGevonden
from app.intake import schemas, splitsing, verwerking, verzamelbak

# De lokale vereis_kantoorrol is bij de rollen-gate-fix (2026-08-21) verhuisd naar
# app/auth/deps.py — één bron voor de kantoor-console-poort; de per-endpoint-Depends hieronder
# blijven ongewijzigd werken.
router = APIRouter(tags=["intake"])


@router.post("/intake/eml", response_model=schemas.IntakeVerwerkResponse, status_code=status.HTTP_201_CREATED)
async def eml_verwerken(
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.IntakeVerwerkResponse:
    """Verwerkt een .eml-bestand (doorgestuurde/geëxporteerde mail) — hetzelfde codepad als de
    latere live postvak-fetch (app/intake/postvak.py, seam voor de GCP-uitrol)."""
    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    try:
        resultaat = verwerking.verwerk_eml(inhoud, actor_id=actor.id)
    except verwerking.GeenGeldigIntakeBericht as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    return schemas.IntakeVerwerkResponse(
        bericht_id=resultaat.bericht_id,
        al_eerder_verwerkt=resultaat.al_eerder_verwerkt,
        bijlagen=[
            schemas.IntakeBijlageResultaatDto(
                bestandsnaam=r.bestandsnaam, uitkomst=r.uitkomst, document_id=r.document_id, detail=r.detail
            )
            for r in resultaat.bijlagen
        ],
    )


@router.post("/intake/bestand", response_model=schemas.IntakeBijlageResultaatDto, status_code=status.HTTP_201_CREATED)
async def los_bestand_verwerken(
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.IntakeBijlageResultaatDto:
    """Los bestand op de werkvoorraad-sleepzone (feedbackronde 25-08 deel 3, punt 2): PDF, UBL of
    afbeelding (JPEG/PNG/HEIC) — zelfde tenaamstelling-routing als een mailbijlage; een .eml hoort
    op /intake/eml."""
    from app.config import settings

    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    if len(inhoud) > settings.document_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Bestand te groot")
    try:
        r = verwerking.verwerk_los_bestand(
            bestandsnaam=bestand.filename or "bestand",
            inhoud=inhoud,
            content_type=bestand.content_type,
            actor_id=actor.id,
        )
    except verwerking.BestandstypeNietOndersteund as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    return schemas.IntakeBijlageResultaatDto(
        bestandsnaam=r.bestandsnaam, uitkomst=r.uitkomst, document_id=r.document_id, detail=r.detail
    )


@router.get("/verzamelbak", response_model=schemas.VerzamelbakLijstResponse)
def verzamelbak_lijst(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.VerzamelbakLijstResponse:
    items = verzamelbak.lijst_verzamelbak()
    return schemas.VerzamelbakLijstResponse(
        items=[
            schemas.VerzamelbakItemDto(
                document_id=item.document_id,
                bestandsnaam=item.bestandsnaam,
                soort=item.soort,
                bron=item.bron,
                afzender_hint=item.afzender_hint,
                tenaamstelling=item.tenaamstelling,
                suggestie_administratie_id=item.suggestie_administratie_id,
                suggestie_bron=item.suggestie_bron,
                aangemaakt_op=item.aangemaakt_op,
                splitsing_id=item.splitsing_id,
                splitsing_voorstel=[
                    schemas.SplitsSegmentDto(**segment)
                    for segment in (item.splitsing_voorstel or {}).get("facturen", [])
                ]
                if item.splitsing_voorstel
                else None,
            )
            for item in items
        ]
    )


@router.get("/verzamelbak/{document_id}/bestand")
def verzamelbak_bestand(document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> Response:
    """Bestand van een verzamelbak-document (besluit Peter 25-08, punt D1: preview-popup per rij
    zodat je ziet voor wie het document is). Fail-closed: alleen documenten die nog écht in de
    verzamelbak staan (administratie NULL + niet_toegewezen), anders 404 — een toegewezen
    document loopt via zijn administratie-gescoopte bestand-route."""
    try:
        inhoud, bestandsnaam, content_type = verzamelbak.haal_bijlage_op(document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{bestandsnaam}"'},
    )


@router.post("/verzamelbak/{document_id}/toewijzen", response_model=schemas.DocumentStatusResponse)
def verzamelbak_toewijzen(
    document_id: uuid.UUID,
    invoer: schemas.ToewijzenInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.DocumentStatusResponse:
    try:
        eind_status = verzamelbak.wijs_toe(
            document_id=document_id, administratie_id=invoer.administratie_id, actor_id=actor.id
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (verzamelbak.DocumentNietInVerzamelbak, verzamelbak.OnbekendeAdministratie) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentStatusResponse(document_id=document_id, status=eind_status.value)


@router.post("/verzamelbak/{document_id}/hoort-niet-bij-ons", response_model=schemas.DocumentStatusResponse)
def verzamelbak_hoort_niet_bij_ons(
    document_id: uuid.UUID,
    invoer: schemas.HoortNietBijOnsInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.DocumentStatusResponse:
    try:
        eind_status = verzamelbak.hoort_niet_bij_ons(document_id=document_id, actor_id=actor.id, reden=invoer.reden)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except verzamelbak.RedenVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except verzamelbak.DocumentNietInVerzamelbak as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentStatusResponse(document_id=document_id, status=eind_status.value)


@router.post("/intake/splitsingen/{splitsing_id}/bevestigen", response_model=schemas.SplitsingBevestigenResponse)
def splitsing_bevestigen(
    splitsing_id: uuid.UUID,
    invoer: schemas.SplitsingBevestigenInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.SplitsingBevestigenResponse:
    try:
        resultaten = splitsing.bevestig_splitsing(
            splitsing_id=splitsing_id,
            actor_id=actor.id,
            delen=[
                splitsing.SplitsDeelInput(
                    start_pagina=d.start_pagina, eind_pagina=d.eind_pagina, tenaamstelling=d.tenaamstelling
                )
                for d in invoer.delen
            ],
        )
    except splitsing.SplitsingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except splitsing.OngeldigeSplitsing as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except splitsing.SplitsingNietOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.SplitsingBevestigenResponse(
        delen=[
            schemas.SplitsDeelResultaatDto(
                document_id=r.document_id,
                bestandsnaam=r.bestandsnaam,
                uitkomst=r.uitkomst,
                administratie_id=r.administratie_id,
            )
            for r in resultaten
        ]
    )


@router.post("/intake/splitsingen/{splitsing_id}/afwijzen", status_code=status.HTTP_204_NO_CONTENT)
def splitsing_afwijzen(
    splitsing_id: uuid.UUID,
    invoer: schemas.SplitsingAfwijzenInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> None:
    try:
        splitsing.wijs_splitsing_af(splitsing_id=splitsing_id, actor_id=actor.id, reden=invoer.reden)
    except splitsing.SplitsingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except splitsing.SplitsingNietOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
