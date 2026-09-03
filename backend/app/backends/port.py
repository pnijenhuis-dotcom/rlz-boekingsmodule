"""Port-interface van de boekhoud-backend voor het INKOOP-boekpad (fase 1; verkoop/omzet/bank volgen
per flow — besluit 0016 §5.1 van de Odoo-verkenning).

Twee kanten:
1. `leesclient()` — het duck-typed leesobject dat de bestaande harde checks al gebruiken
   (`find_purchase_invoices_by_reference`, `get("Vendors/{id}/BankRelations")`). De RLZ-adapter geeft
   hier gewoon de RlzClient; de Odoo-adapter een facade die dezelfde vorm (RLZ-veldnamen) teruggeeft.
   Zo blijven checks.py/leverancier_iban.py ongewijzigd — pakketkennis leeft in de adapter.
2. Schrijfoperaties mét één uitkomstvorm: `boek_inkoopfactuur` en `boek_tegenboeking`; fouten komen
   ALTIJD als `BackendBoekFout` mét een leesbare reden (de motor zet 'm als boeken_mislukt / 502).

Capability-contract: een operatie die een adapter niet kent raise-t `NietOndersteund` — zichtbaar, nooit
een stille no-op."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.documenten.boekvoorstel import BoekvoorstelData
    from app.rlz.aangifte import KantToets


class Backend(enum.StrEnum):
    RLZ = "rlz"
    ODOO = "odoo"


class NietOndersteund(Exception):
    """De adapter ondersteunt deze operatie niet (capability-contract 0016 §4)."""


class BackendBoekFout(Exception):
    """De backend weigerde/faalde tijdens een schrijfactie — `str(exc)` is de leesbare reden mét
    handelingsperspectief (vertaald in de adapter)."""


@dataclass(frozen=True)
class BoekUitkomst:
    #: lokale UUID van het externe document (RLZ: het client-GUID; Odoo: odoo_uuid van de account.move)
    extern_document_id: uuid.UUID
    boekstuknummer: str | None
    #: backend-specifiek detail voor tijdlijn/audit (bv. odoo_move_id, odoo_naam, btw_override)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TegenboekUitkomst:
    extern_document_id: uuid.UUID
    boekstuknummer: str | None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrigineelStand:
    """Stand van het origineel vóór een tegenboeking: de storno-toets (aangifte-/lock-poort), de
    betaalstatus en of het origineel nog geboekt staat."""

    kant: KantToets
    nog_geboekt: bool
    betaald_bedrag: Decimal | None
    open_bedrag: Decimal | None
    volledig_afgeletterd: bool


class InkoopPort(Protocol):
    backend: Backend

    def __enter__(self) -> InkoopPort: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def leesclient(self) -> Any: ...

    def boek_inkoopfactuur(
        self, *, document_id: uuid.UUID, voorstel: BoekvoorstelData, bestand: bytes, bestandsnaam: str
    ) -> BoekUitkomst: ...

    def origineel_stand(self, *, document_id: uuid.UUID, boek_cyclus: int) -> OrigineelStand: ...

    def boek_tegenboeking(
        self,
        *,
        document_id: uuid.UUID,
        voorstel: BoekvoorstelData,
        referentie: str,
        omschrijving: str,
        reden: str,
        bestand: bytes,
        bestandsnaam: str,
    ) -> TegenboekUitkomst: ...
