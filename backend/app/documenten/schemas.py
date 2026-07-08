from __future__ import annotations

import uuid

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    mogelijk_duplicaat_van: uuid.UUID | None = None
