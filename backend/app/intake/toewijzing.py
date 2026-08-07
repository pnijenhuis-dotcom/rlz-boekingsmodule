"""Administratie-toewijzing op tenaamstelling (leidend) met afzender als hint (CLAUDE.md-
verzamelbakbesluit). Deterministisch — de AI leest hooguit de tenaamstelling vóór, de matching
zelf is code:

1. Tenaamstelling matcht exact (genormaliseerd) een administratienaam of een geleerde
   tenaamstelling-regel → automatische toewijzing.
2. Geen tenaamstelling-match, wél een geleerde afzender-regel → automatische toewijzing
   (mockup: "dezelfde afzender wordt de volgende keer automatisch gekoppeld"), MAAR alleen als
   er geen tegenstrijdig tenaamstelling-signaal is: is er wél een tenaamstelling gelezen die
   nergens op matcht, dan is dat twijfel → verzamelbak, met de afzender-administratie als
   suggestie ("nooit auto-toewijzen bij twijfel").
3. Anders → verzamelbak, met de beste hint als suggestie (nooit een stille keuze).

Leren: elke handmatige toewijzing in de verzamelbak wordt een regel (tenaamstelling én — als
bekend — afzender). Zelfde sleutel later anders toegewezen = oude regel deactiveren + nieuwe
rij (historie blijft)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.intake.models import ToewijzingRegel, ToewijzingRegelSoort

# Eigen normalisatie — bewust NIET de vendor-matchnormalisatie van app/extractie/controle.py:
# die strijkt ook "holding" weg, terwijl dat woord bij tenaamstelling-toewijzing juist het
# onderscheid maakt (mockup: tenaamstelling "BLOW Holding" matcht "BLOW B.V." níét exact — dat
# hoort verzamelbak te zijn, geen auto-match). Alleen rechtsvorm-afkortingen zijn opmaak.
_RECHTSVORM_SUFFIX = re.compile(r"\b(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?)\b", re.IGNORECASE)
_GEEN_LETTER_OF_CIJFER = re.compile(r"[^0-9a-zà-ÿ]+")


def normaliseer_partijnaam(naam: str) -> str:
    zonder_rechtsvorm = _RECHTSVORM_SUFFIX.sub(" ", naam.lower())
    tokens = [t for t in _GEEN_LETTER_OF_CIJFER.split(zonder_rechtsvorm) if t]
    return " ".join(tokens)


@dataclass(frozen=True)
class ToewijzingBesluit:
    """None-administratie = verzamelbak. `suggestie_*` is de beste hint voor de mens."""

    administratie_id: uuid.UUID | None
    bron: str | None
    suggestie_administratie_id: uuid.UUID | None = None
    suggestie_bron: str | None = None


def normaliseer_afzender(afzender: str | None) -> str | None:
    if not afzender:
        return None
    schoon = afzender.strip().lower()
    return schoon or None


def _actieve_regel(session: Session, *, soort: ToewijzingRegelSoort, sleutel: str) -> ToewijzingRegel | None:
    return session.scalars(
        select(ToewijzingRegel).where(
            ToewijzingRegel.soort == soort.value,
            ToewijzingRegel.sleutel == sleutel,
            ToewijzingRegel.actief.is_(True),
        )
    ).first()


def _administratie_op_naam(session: Session, genormaliseerde_naam: str) -> uuid.UUID | None:
    """Exacte (genormaliseerde) naammatch tegen het administratieregister — alleen bij precies
    één match, anders geen giswerk."""
    kandidaten = [
        rij.id
        for rij in session.scalars(select(Administratie).where(Administratie.actief.is_(True)))
        if normaliseer_partijnaam(rij.naam) == genormaliseerde_naam
    ]
    return kandidaten[0] if len(kandidaten) == 1 else None


def bepaal_toewijzing(
    session: Session, *, tenaamstelling: str | None, afzender: str | None
) -> ToewijzingBesluit:
    tenaamstelling_sleutel = normaliseer_partijnaam(tenaamstelling) if tenaamstelling else ""
    afzender_sleutel = normaliseer_afzender(afzender)

    if tenaamstelling_sleutel:
        regel = _actieve_regel(
            session, soort=ToewijzingRegelSoort.TENAAMSTELLING, sleutel=tenaamstelling_sleutel
        )
        if regel is not None:
            return ToewijzingBesluit(administratie_id=regel.administratie_id, bron="tenaamstelling_regel")
        register_match = _administratie_op_naam(session, tenaamstelling_sleutel)
        if register_match is not None:
            return ToewijzingBesluit(administratie_id=register_match, bron="tenaamstelling_register")

    afzender_regel = (
        _actieve_regel(session, soort=ToewijzingRegelSoort.AFZENDER, sleutel=afzender_sleutel)
        if afzender_sleutel
        else None
    )
    if afzender_regel is not None:
        if tenaamstelling_sleutel:
            # Tegenstrijdig signaal: er ís een tenaamstelling maar die matcht niets — twijfel,
            # dus verzamelbak mét de afzender-administratie als suggestie.
            return ToewijzingBesluit(
                administratie_id=None,
                bron=None,
                suggestie_administratie_id=afzender_regel.administratie_id,
                suggestie_bron="afzender_regel_maar_onbekende_tenaamstelling",
            )
        return ToewijzingBesluit(administratie_id=afzender_regel.administratie_id, bron="afzender_regel")

    return ToewijzingBesluit(administratie_id=None, bron=None)


def leer_toewijzing(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    tenaamstelling: str | None,
    afzender: str | None,
) -> None:
    """Legt de handmatige toewijzing vast als regel(s) — tenaamstelling én afzender voor zover
    bekend. Ongewijzigd = no-op; ander doel voor dezelfde sleutel = oude regel deactiveren +
    nieuwe rij, mét audit_event."""
    paren: list[tuple[ToewijzingRegelSoort, str]] = []
    tenaamstelling_sleutel = normaliseer_partijnaam(tenaamstelling) if tenaamstelling else ""
    if tenaamstelling_sleutel:
        paren.append((ToewijzingRegelSoort.TENAAMSTELLING, tenaamstelling_sleutel))
    afzender_sleutel = normaliseer_afzender(afzender)
    if afzender_sleutel:
        paren.append((ToewijzingRegelSoort.AFZENDER, afzender_sleutel))

    for soort, sleutel in paren:
        bestaand = _actieve_regel(session, soort=soort, sleutel=sleutel)
        if bestaand is not None and bestaand.administratie_id == administratie_id:
            continue
        oude_waarde = None
        if bestaand is not None:
            oude_waarde = {"administratie_id": str(bestaand.administratie_id)}
            bestaand.actief = False
            bestaand.gedeactiveerd_door = actor_id
            bestaand.gedeactiveerd_op = datetime.now(UTC)
        regel = ToewijzingRegel(
            soort=soort.value,
            sleutel=sleutel,
            administratie_id=administratie_id,
            aangemaakt_door=actor_id,
        )
        session.add(regel)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="toewijzing_regel",
            record_id=regel.id,
            actie="toewijzing_regel_geleerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oude_waarde,
            nieuwe_waarde={"soort": soort.value, "sleutel": sleutel, "administratie_id": str(administratie_id)},
            # Platform-breed audit-feit (administratie_id=None): de regel zelf is intake-breed —
            # het doel staat in nieuwe_waarde. Zo werkt het leren ook vanuit een sessie zonder
            # (of met een andere) administratie-scope; audit_event-RLS eist anders scope=doel.
            administratie_id=None,
        )
