"""Bundel-opslag: dezelfde `DocumentOpslag`-interface als de documenten (GCS in productie, lokale map in dev) — geen
derde partij op de code-levering (AVG-lijn), geen secrets in de bundel."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.documenten.storage import DocumentOpslag, GcsDocumentOpslag, LokaleBestandsopslag


def bundel_opslag() -> DocumentOpslag:
    if settings.app_bundel_gcs_bucket:
        return GcsDocumentOpslag(settings.app_bundel_gcs_bucket)
    return LokaleBestandsopslag(Path(settings.app_bundel_opslag_basismap))
