"""Rekeningtype → projectplicht (punt 6 "Boeken prettig 1", Peter 02-10: "soms hebben we gewoon spullen die als voorraad
worden gekocht, die moeten helemaal geen project krijgen" / "voorraad boeken vraagt nog steeds om project").

Regel: projecteis én projectverdeling gelden UITSLUITEND voor KOSTENrekeningen — `grootboekrekening.soort == 2` (RLZ
`AccountType` onvertaald: 1 opbrengsten, 2 kosten, 3 activa, 4 passiva; Odoo `account_type` expense* → 2, zie
`app/odoo/sync.py::soort_voor_account_type`). Voorraad (3xxx, balans), activa (0xxx), tussenrekeningen: géén projectveld,
geen verdeling, geen check. Deterministisch op het rekeningtype uit de sync — geen instelling, geen keuzelijst. Een rekening
die NIET in de cache staat (nog niet gesynct, leeg veld) telt als kosten: fail-closed richting de projectplicht."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Grootboekrekening

#: RLZ AccountType 2 = kosten (W&V); alleen dáár hoort een project op de regel (of in de verdeling).
SOORT_KOSTEN = 2


def balans_ledger_ids(session: Session, *, administratie_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """Alle grootboekrekeningen van de administratie die GEEN kostenrekening zijn (soort ≠ 2) — één query, RLS-scope."""
    return frozenset(
        session.scalars(
            select(Grootboekrekening.ledger_id).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.soort != SOORT_KOSTEN,
            )
        )
    )


def project_van_toepassing(ledger_id: uuid.UUID | None, balans: frozenset[uuid.UUID]) -> bool:
    """True = de regel draagt een project (kosten of onbekende rekening); False = balansrekening (voorraad/activa/
    tussenrekening): geen projectveld, geen verdeling, geen check."""
    return ledger_id is None or ledger_id not in balans
