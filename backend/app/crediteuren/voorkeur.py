"""Eén bron voor "verliezer → voorkeur" (blok B13 07-09, migratie 0117).

Een crediteur mét `vendor_cache.voorkeur_vendor_id` is een VERLIEZER van een afgehandeld dubbel-cluster: in de module
onbruikbaar. Élk pad dat crediteuren voorstelt, matcht of per crediteur aggregeert leest via deze module:
- `BRUIKBAAR` — SQL-filter voor kandidaat-/keuzelijsten (alleen niet-verliezers);
- `verliezers(session, administratie_id)` — {verliezer → voorkeur}, ketens platgeslagen (A→B, B→C ⇒ A→C);
- `voorkeur_van(session, administratie_id, vendor_id)` — de bruikbare crediteur voor een gegeven id (identiteit
  als het geen verliezer is; None blijft None).
Bewust géén imports uit andere domeinmodules (wordt vanuit extractie, geheugen, terugkerend, verplichting, Odoo en
sync aangeroepen — geen cyclus)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.sync.models import VendorCache

#: Filter voor keuzelijsten en kandidaat-sets: een verliezer wordt nooit meer voorgesteld of gekozen.
BRUIKBAAR = VendorCache.voorkeur_vendor_id.is_(None)

_MAX_KETEN = 8


def verliezers(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    """{verliezer_vendor_id → voorkeur_vendor_id} voor deze administratie, ketens platgeslagen."""
    ruw = dict(
        session.execute(
            select(VendorCache.id, VendorCache.voorkeur_vendor_id).where(
                VendorCache.administratie_id == administratie_id, VendorCache.voorkeur_vendor_id.is_not(None)
            )
        ).all()
    )
    return {v: _eind(v, ruw) for v in ruw}


def _eind(vendor_id: uuid.UUID, ruw: dict[uuid.UUID, uuid.UUID]) -> uuid.UUID:
    doel = ruw[vendor_id]
    gezien = {vendor_id}
    for _ in range(_MAX_KETEN):
        if doel not in ruw or doel in gezien:
            break
        gezien.add(doel)
        doel = ruw[doel]
    return doel


def vertaal(vendor_id: uuid.UUID | None, kaart: dict[uuid.UUID, uuid.UUID]) -> uuid.UUID | None:
    """Vertaal één id met een eerder opgehaalde `verliezers`-kaart (voor lussen zonder N+1)."""
    if vendor_id is None:
        return None
    return kaart.get(vendor_id, vendor_id)


def voorkeur_van(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> uuid.UUID | None:
    """De bruikbare crediteur voor `vendor_id`: de (eind)voorkeur als het een verliezer is, anders het id zelf."""
    if vendor_id is None:
        return None
    huidig = vendor_id
    for _ in range(_MAX_KETEN):
        rij = session.get(VendorCache, (huidig, administratie_id))
        if rij is None or rij.voorkeur_vendor_id is None or rij.voorkeur_vendor_id == huidig:
            return huidig
        huidig = rij.voorkeur_vendor_id
    return huidig


def is_verliezer(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> bool:
    rij = session.get(VendorCache, (vendor_id, administratie_id))
    return rij is not None and rij.voorkeur_vendor_id is not None
