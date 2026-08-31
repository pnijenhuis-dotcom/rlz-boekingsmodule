"""Wire-vorm van de registersnapshot (koppelcontract §8 v1.18). Veldreferentie per rij = exact
de kolommen van de S2-registerlevering van 27-08 (Platform/uitwisseling/01_administratie.sql +
02_grootboekrekening.sql) — geen interne toggles/instellingen (is_vastgoed, boeken_ingeschakeld,
…) en geen sync-metadata per rij. Elke niet-additieve wijziging = schema_version-bump +
contractronde; een OPTIONEEL additief veld mag per contract-notitie mét akkoord van beide kanten
(precedent: `inbox_adres`, verzoek Vastly 31-08)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_serializer

REGISTERSYNC_SCHEMA_VERSION = "1.0"
REGISTERSYNC_EVENT = "registersync"
# Headers waarin Vastly timestamp, nonce en handtekening meestuurt (een GET heeft geen body).
TIMESTAMP_HEADER = "X-Registersync-Timestamp"
NONCE_HEADER = "X-Registersync-Nonce"
SIGNATURE_HEADER = "X-Registersync-Signature"


# Sentinel voor "geen uitspraak" over inbox_adres: het veld wordt dan wéggelaten uit de wire
# (§8-semantiek verzoek Vastly 31-08: afwezig = geen uitspraak, Vastly raakt de cache niet aan;
# aanwezig maar null/leeg = expliciet geen intake-adres, Vastly maakt de cache leeg).
GEEN_UITSPRAAK = "\x00geen-uitspraak"


class AdministratieRij(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    rlz_admin_id: str
    naam: str
    actief: bool
    # v1.19-notitie (2), verzoek Vastly 31-08: optioneel additief veld — het e-mailadres waarop
    # de administratie inkomende verkoopfacturen ontvangt. Default = weglaten (geen uitspraak).
    inbox_adres: str | None = GEEN_UITSPRAAK

    @model_serializer(mode="wrap")
    def _serialiseer(self, handler) -> dict[str, Any]:
        data = handler(self)
        if self.inbox_adres == GEEN_UITSPRAAK:
            data.pop("inbox_adres", None)
        return data


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
