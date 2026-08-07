"""Categorie→GB+btw-mapping per administratie (omzetmodule): eerste keer instellen, daarna
onthouden — zelfde principe als het boekingsgeheugen, maar deterministisch: één actieve mapping
per genormaliseerde categorie-sleutel, geen weging. BLOW-besluit blijft een mapping-keuze:
cannabisomzet → "NL, Geen BTW (Vrijgesteld)", bewust géén 0%-tarief (aangifte-rubriek) — de
mapping legt vast wélke taxrate, deze module dwingt geen inhoudelijke keuze af."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.omzet.models import OmzetCategorieMapping

# "1. Weed" / "2) Hash" / "10 - Edibles" → nummering is opmaak, geen betekenis: dezelfde
# categorie moet op dezelfde sleutel landen ook als de rapport-nummering verschuift.
_VOORLOOP_NUMMERING = re.compile(r"^\s*\d+\s*[.\-):]*\s*")
_GEEN_LETTER_OF_CIJFER = re.compile(r"[^0-9a-zà-ÿ]+")


def normaliseer_categorie_sleutel(categorie: str | None) -> str | None:
    """Lowercase → voorloopnummering strippen → leestekens naar spaties → whitespace inklappen.
    Bewust GEEN token-set-sortering (anders dan het boekingsgeheugen): "Weed Prepacked" en
    "Prepacked Weed" zijn hier verschillende rapportcategorieën als de klant ze zo voert —
    de sleutel normaliseert opmaak, geen volgorde."""
    if not categorie:
        return None
    zonder_nummer = _VOORLOOP_NUMMERING.sub("", categorie.lower())
    tokens = [t for t in _GEEN_LETTER_OF_CIJFER.split(zonder_nummer) if t]
    if not tokens:
        return None
    return " ".join(tokens)


@dataclass(frozen=True)
class MappingData:
    id: uuid.UUID
    categorie_sleutel: str
    weergave_naam: str
    omzet_ledger_id: uuid.UUID
    taxrate_id: uuid.UUID
    kostprijs_ledger_id: uuid.UUID | None
    aangemaakt_op: datetime


def _naar_data(m: OmzetCategorieMapping) -> MappingData:
    return MappingData(
        id=m.id,
        categorie_sleutel=m.categorie_sleutel,
        weergave_naam=m.weergave_naam,
        omzet_ledger_id=m.omzet_ledger_id,
        taxrate_id=m.taxrate_id,
        kostprijs_ledger_id=m.kostprijs_ledger_id,
        aangemaakt_op=m.aangemaakt_op,
    )


def actieve_mappings(session: Session, *, administratie_id: uuid.UUID) -> dict[str, MappingData]:
    """Alle actieve mappings van één administratie, gesleuteld op categorie_sleutel."""
    rijen = session.scalars(
        select(OmzetCategorieMapping).where(
            OmzetCategorieMapping.administratie_id == administratie_id,
            OmzetCategorieMapping.actief.is_(True),
        )
    )
    return {rij.categorie_sleutel: _naar_data(rij) for rij in rijen}


def lijst_mappings(*, administratie_id: uuid.UUID) -> list[MappingData]:
    with scoped_session(administratie_id) as session:
        return sorted(
            actieve_mappings(session, administratie_id=administratie_id).values(),
            key=lambda m: m.categorie_sleutel,
        )


def onthoud_mapping(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    categorie: str,
    omzet_ledger_id: uuid.UUID,
    taxrate_id: uuid.UUID,
    kostprijs_ledger_id: uuid.UUID | None,
) -> MappingData | None:
    """Legt de mapping voor deze categorie vast (of werkt 'm bij) — aangeroepen bij het opslaan
    van het omzetvoorstel: wat de controleur dáár kiest, is voortaan de default. Ongewijzigd =
    geen nieuwe rij en geen audit_event (elke opslaan-actie herhaalt de actuele stand). Wijziging
    = oude rij deactiveren + nieuwe rij (append-only historie, zelfde patroon als
    leverancier_iban), mét audit_event."""
    sleutel = normaliseer_categorie_sleutel(categorie)
    if sleutel is None:
        return None

    bestaand = session.scalars(
        select(OmzetCategorieMapping).where(
            OmzetCategorieMapping.administratie_id == administratie_id,
            OmzetCategorieMapping.categorie_sleutel == sleutel,
            OmzetCategorieMapping.actief.is_(True),
        )
    ).first()
    if (
        bestaand is not None
        and bestaand.omzet_ledger_id == omzet_ledger_id
        and bestaand.taxrate_id == taxrate_id
        and bestaand.kostprijs_ledger_id == kostprijs_ledger_id
    ):
        return _naar_data(bestaand)

    oude_waarde = None
    if bestaand is not None:
        oude_waarde = {
            "omzet_ledger_id": str(bestaand.omzet_ledger_id),
            "taxrate_id": str(bestaand.taxrate_id),
            "kostprijs_ledger_id": str(bestaand.kostprijs_ledger_id) if bestaand.kostprijs_ledger_id else None,
        }
        bestaand.actief = False
        bestaand.gedeactiveerd_door = actor_id
        bestaand.gedeactiveerd_op = datetime.now(UTC)

    nieuw = OmzetCategorieMapping(
        administratie_id=administratie_id,
        categorie_sleutel=sleutel,
        weergave_naam=categorie.strip(),
        omzet_ledger_id=omzet_ledger_id,
        taxrate_id=taxrate_id,
        kostprijs_ledger_id=kostprijs_ledger_id,
        aangemaakt_door=actor_id,
    )
    session.add(nieuw)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="omzet_categorie_mapping",
        record_id=nieuw.id,
        actie="omzet_mapping_vastgelegd",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oude_waarde,
        nieuwe_waarde={
            "categorie_sleutel": sleutel,
            "omzet_ledger_id": str(omzet_ledger_id),
            "taxrate_id": str(taxrate_id),
            "kostprijs_ledger_id": str(kostprijs_ledger_id) if kostprijs_ledger_id else None,
        },
        administratie_id=administratie_id,
    )
    return _naar_data(nieuw)
