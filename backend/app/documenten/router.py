from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

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
