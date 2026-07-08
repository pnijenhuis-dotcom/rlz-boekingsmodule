from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope
from app.config import settings
from app.documenten import schemas, service

router = APIRouter(tags=["documenten"])

_TOEGESTANE_SUFFIXEN = {".pdf", ".xml"}


@router.post(
    "/administraties/{administratie_id}/documenten",
    response_model=schemas.DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def document_uploaden(
    administratie_id: uuid.UUID,
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentUploadResponse:
    if not bestand.filename or Path(bestand.filename).suffix.lower() not in _TOEGESTANE_SUFFIXEN:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Alleen PDF- of XML-bestanden"
        )

    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    if len(inhoud) > settings.document_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Bestand te groot")

    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestand.filename,
        inhoud=inhoud,
        actor_id=actor.id,
    )
    return schemas.DocumentUploadResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        mogelijk_duplicaat_van=resultaat.mogelijk_duplicaat_van_id,
    )


@router.get(
    "/administraties/{administratie_id}/documenten",
    response_model=schemas.DocumentListResponse,
)
def documenten_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentListResponse:
    documenten = service.lijst_documenten(administratie_id=administratie_id)
    return schemas.DocumentListResponse(
        documenten=[
            schemas.DocumentListItemResponse(
                id=d.id,
                bestandsnaam=d.bestandsnaam,
                status=d.status.value,
                bron=d.bron.value,
                mogelijk_duplicaat_van=d.mogelijk_duplicaat_van_id,
                toegewezen_aan=d.toegewezen_aan,
                aangemaakt_op=d.aangemaakt_op,
                laatst_gewijzigd_op=d.laatst_gewijzigd_op,
            )
            for d in documenten
        ]
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}",
    response_model=schemas.DocumentDetailResponse,
)
def document_detail(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentDetailResponse:
    try:
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    d = detail.document
    return schemas.DocumentDetailResponse(
        id=d.id,
        administratie_id=d.administratie_id,
        bestandsnaam=d.bestandsnaam,
        status=d.status.value,
        bron=d.bron.value,
        mogelijk_duplicaat_van=d.mogelijk_duplicaat_van_id,
        toegewezen_aan=d.toegewezen_aan,
        aangemaakt_op=d.aangemaakt_op,
        laatst_gewijzigd_op=d.laatst_gewijzigd_op,
        veldvoorstel=detail.veldvoorstel,
        tijdlijn=[
            schemas.DocumentGebeurtenisResponse(
                van_status=g.van_status.value if g.van_status else None,
                naar_status=g.naar_status.value,
                actor_id=g.actor_id,
                detail=g.detail,
                tijdstip=g.tijdstip,
            )
            for g in detail.gebeurtenissen
        ],
    )


@router.get("/administraties/{administratie_id}/documenten/{document_id}/bestand")
def document_bestand(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> Response:
    try:
        inhoud, bestandsnaam, content_type = service.haal_bijlage_op(
            administratie_id=administratie_id, document_id=document_id
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{bestandsnaam}"'},
    )
