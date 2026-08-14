from __future__ import annotations

import uuid

from pydantic import BaseModel

# Eigen schemaversie van het inkomende projectaanvraag-kanaal (route A, koppelcontract §5
# v1.15; registers/schema-versions.md) — los van de uitgaande event-versies.
PROJECTAANVRAAG_SCHEMA_VERSION = "1.0"
PROJECTAANVRAAG_EVENT = "projectaanvraag"


class ProjectAanvraagData(BaseModel):
    bericht_id: uuid.UUID
    administratie_id: uuid.UUID
    pand_referentie: str
    naam_invoer: str


class ProjectAanvraagEnvelope(BaseModel):
    """Zelfde envelope-vorm als het uitgaande §3-kanaal (schema_version + event + timestamp +
    nonce + data + handtekening) — één wire-conventie voor beide richtingen."""

    schema_version: str
    event: str
    timestamp: str
    nonce: str
    data: ProjectAanvraagData
    handtekening: str


class ProjectAanvraagResponse(BaseModel):
    schema_version: str
    bericht_id: uuid.UUID
    status: str  # aangemaakt | bestond_al
    rlz_project_id: uuid.UUID
    projectnaam: str
