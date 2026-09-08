"""Intercompany-leveranciersregel — één leesbron (blok 4 bundel 08-09 avond, besluit Peter 08-09).

"Leverancier met IC-vlag" = een actieve rij in `boekhouding.intercompany_tegenpartij` (migratie 0045, Kempen-
doorbelasting blok 2) in de ADMINISTRATIE VAN HET DOCUMENT met de vendor-entity-GUID van het boekvoorstel. De tabel
wordt onderhouden door `doorbelasting/service.py::upsert_intercompany_tegenpartij` (bron-kant = doel_customer_guid
bij mapping-aanmaak/-wijziging, doel-kant = crediteur-GUID zodra de spiegel-inkoop voor het eerst boekt) en volgt
`mapping.intercompany`/`actief` — `actief=False` i.p.v. delete.

Afnemers: bank-afletteren (`app/bank/voorstellen.py`, IC-open-posten nooit als afletter-doel) en de klant-
accordering (`app/accordering/service.py`: een IC-document doorloopt exact dezelfde flow maar de stap "ter
accordering" wordt overgeslagen). Puur lezen, nooit AI, geen schrijfpad. Lege/inactieve tabel = gewone flow
(kernprincipe 7: geen stille no-op — er gebeurt dan niets bijzonders)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.doorbelasting.models import IntercompanyTegenpartij

# Waarde van `accordering_overgeslagen_reden` in de DTO's / het tijdlijn-detail — de enige reden die bestaat.
OVERGESLAGEN_REDEN_INTERCOMPANY = "intercompany"


def intercompany_entity_guids(session: Session, *, administratie_id: uuid.UUID) -> set[uuid.UUID]:
    """De entity-GUID's die in deze administratie als intercompany gelden (alleen actieve rijen)."""
    return {
        rij.entity_guid
        for rij in session.scalars(
            select(IntercompanyTegenpartij).where(
                IntercompanyTegenpartij.administratie_id == administratie_id,
                IntercompanyTegenpartij.actief.is_(True),
            )
        )
    }


def intercompany_tegenpartij(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None
) -> IntercompanyTegenpartij | None:
    """De actieve IC-rij voor deze crediteur in deze administratie, of None. `vendor_id` None = None (geen
    leverancier herkend → nooit intercompany)."""
    if vendor_id is None:
        return None
    return session.scalars(
        select(IntercompanyTegenpartij).where(
            IntercompanyTegenpartij.administratie_id == administratie_id,
            IntercompanyTegenpartij.entity_guid == vendor_id,
            IntercompanyTegenpartij.actief.is_(True),
        )
    ).first()


def is_intercompany_leverancier(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> bool:
    """True als deze crediteur in déze administratie een actieve IC-rij heeft — dé definitie van
    "leverancier met IC-vlag" voor alle afnemers."""
    return intercompany_tegenpartij(session, administratie_id=administratie_id, vendor_id=vendor_id) is not None
