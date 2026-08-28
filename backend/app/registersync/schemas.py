"""Wire-vorm van de registersnapshot (koppelcontract §8 v1.18). Veldreferentie per rij = exact
de kolommen van de S2-registerlevering van 27-08 (Platform/uitwisseling/01_administratie.sql +
02_grootboekrekening.sql) — geen interne toggles/instellingen (is_vastgoed, boeken_ingeschakeld,
…) en geen sync-metadata per rij. Elke uitbreiding = schema_version-bump + contractronde."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

REGISTERSYNC_SCHEMA_VERSION = "1.0"
REGISTERSYNC_EVENT = "registersync"
# Headers waarin Vastly timestamp, nonce en handtekening meestuurt (een GET heeft geen body).
TIMESTAMP_HEADER = "X-Registersync-Timestamp"
NONCE_HEADER = "X-Registersync-Nonce"
SIGNATURE_HEADER = "X-Registersync-Signature"


class AdministratieRij(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    rlz_admin_id: str
    naam: str
    actief: bool


class GrootboekrekeningRij(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_id: uuid.UUID
    administratie_id: uuid.UUID
    code: str
    naam: str
    soort: int
    is_totaalrekening: bool


class Registerdeel[T](BaseModel):
    """Eén registerdeel mét eigen telling: `aantal` == len(rijen), altijd aanwezig — een leeg
    register is een expliciete levering `{"aantal": 0, "rijen": []}`, nooit een kale lijst
    zonder duiding. Vastly toetst de telling en weigert een lege/gedeeltelijke levering zelf."""

    model_config = ConfigDict(extra="forbid")

    aantal: int
    rijen: list[T]


class RegisterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REGISTERSYNC_SCHEMA_VERSION
    generated_at: datetime
    # Informatief, snapshot-breed: het jongste `laatst_gesynchroniseerd` over de geleverde
    # grootboekrijen — zegt hoe vers RLZ's eigen kopie van Reeleezee is (generated_at zegt alleen
    # wanneer déze snapshot is opgebouwd). NULL bij een leeg grootboekregister.
    bron_laatst_gesynchroniseerd_op: datetime | None
    administraties: Registerdeel[AdministratieRij]
    grootboekrekeningen: Registerdeel[GrootboekrekeningRij]
