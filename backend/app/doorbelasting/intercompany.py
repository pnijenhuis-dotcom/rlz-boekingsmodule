"""Intercompany-leveranciersregel — één leesbron (blok 4 bundel 08-09 avond, besluit Peter 08-09).

"Leverancier met IC-vlag" = een actieve rij in `boekhouding.intercompany_tegenpartij` (migratie 0045, Kempen-
doorbelasting blok 2) in de ADMINISTRATIE VAN HET DOCUMENT met de vendor-entity-GUID van het boekvoorstel. De tabel
wordt onderhouden door `doorbelasting/service.py::upsert_intercompany_tegenpartij` (bron-kant = doel_customer_guid
bij mapping-aanmaak/-wijziging, doel-kant = crediteur-GUID zodra de spiegel-inkoop voor het eerst boekt) en volgt
`mapping.intercompany`/`actief` — `actief=False` i.p.v. delete.

Afnemers: bank-afletteren (`app/bank/voorstellen.py`, IC-open-posten nooit als afletter-doel) en de klant-
accordering (`app/accordering/service.py`: een IC-document doorloopt exact dezelfde flow maar de stap "ter
accordering" wordt overgeslagen). Puur lezen, nooit AI, geen schrijfpad. Lege/inactieve tabel = gewone flow
(kernprincipe 7: geen stille no-op — er gebeurt dan niets bijzonders).

Sinds 16-09 (opdracht intercompany-factuurmatch, blok A) leven de drie functies in `app/intercompany/relaties.py` — de
ENE intercompany-leesbron (afgeleide relaties + doorbelasting-IC-vlag). Dit module her-exporteert ze met identieke
semantiek zodat alle afnemers en tests ongewijzigd blijven."""

from __future__ import annotations

from app.intercompany.relaties import (
    OVERGESLAGEN_REDEN_INTERCOMPANY,
    intercompany_entity_guids,
    intercompany_tegenpartij,
    is_intercompany_leverancier,
)

__all__ = [
    "OVERGESLAGEN_REDEN_INTERCOMPANY",
    "intercompany_entity_guids",
    "intercompany_tegenpartij",
    "is_intercompany_leverancier",
]
