"""Crediteur-kenmerken (btw-/KvK-nummer per crediteur) — opruimrun 28-08 punt 14, besluiten Peter 27-08.

Drie afnemers, één bron (`boekhouding.crediteur_kenmerk`, migratie 0082 + RLZ-KvK uit de vendor-cache):
1. `kandidaten_met_kenmerken` — de crediteur-voorstel-match leest nummer vóór naam;
2. `btw_per_vendor` — de duplicaatcheck over ÁLLE crediteuren (checks.check_duplicaat_over_crediteuren);
3. `dubbele_crediteuren` — de signaleringslijst op Instellingen (naam/IBAN/nummer), samenvoegen blijft
   RLZ-mensenwerk — wij verwijderen niets.
Schrijven gebeurt uitsluitend via `neem_over_uit_veldvoorstel` (bij het opslaan van een boekvoorstel
mét crediteur: de mens heeft de crediteur bevestigd, het nummer komt letterlijk van de factuur).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.models import CrediteurKenmerk, LeverancierIban
from app.extractie.btw_nummer import normaliseer_kvk_nummer
from app.extractie.controle import VendorKandidaat, _genormaliseerd
from app.sync.models import VendorCache


@dataclass(frozen=True)
class Kenmerk:
    vendor_id: uuid.UUID
    btw_nummer: str | None
    btw_nummer_geverifieerd: bool | None
    kvk_nummer: str | None
    kvk_nummer_bron: str | None


def _rlz_kvk(rij: VendorCache) -> str | None:
    """KvK-nummer zoals RLZ 'm kent (`ChamberOfCommerceNumber` in de vendor-brondata) — lees-fallback."""
    return normaliseer_kvk_nummer(str((rij.brondata or {}).get("ChamberOfCommerceNumber") or ""))


def kenmerken_per_vendor(session: Session, *, administratie_id: uuid.UUID) -> dict[uuid.UUID, Kenmerk]:
    """Alle bekende kenmerken per crediteur: tabel eerst, RLZ-KvK als fallback (bron 'rlz'). Sessie
    van de aanroeper (al gescoopt op de administratie)."""
    uit_tabel = {
        k.vendor_id: k
        for k in session.scalars(select(CrediteurKenmerk).where(CrediteurKenmerk.administratie_id == administratie_id))
    }
    resultaat: dict[uuid.UUID, Kenmerk] = {}
    for rij in session.scalars(
        select(VendorCache).where(
            VendorCache.administratie_id == administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None)
        )
    ):
        k = uit_tabel.get(rij.id)
        kvk = (k.kvk_nummer if k else None) or _rlz_kvk(rij)
        resultaat[rij.id] = Kenmerk(
            vendor_id=rij.id,
            btw_nummer=k.btw_nummer if k else None,
            btw_nummer_geverifieerd=k.btw_nummer_geverifieerd if k else None,
            kvk_nummer=kvk,
            kvk_nummer_bron=(k.kvk_nummer_bron if k and k.kvk_nummer else ("rlz" if kvk else None)),
        )
    for vendor_id, k in uit_tabel.items():
        resultaat.setdefault(
            vendor_id,
            Kenmerk(vendor_id, k.btw_nummer, k.btw_nummer_geverifieerd, k.kvk_nummer, k.kvk_nummer_bron),
        )
    return resultaat


def kandidaten_met_kenmerken(session: Session, *, administratie_id: uuid.UUID) -> list[VendorKandidaat]:
    """Vendor-kandidaten voor de extractie-controlelaag (naam + nummers), actueel en niet-gearchiveerd."""
    kenmerken = kenmerken_per_vendor(session, administratie_id=administratie_id)
    return [
        VendorKandidaat(
            id=rij.id,
            naam=rij.naam or "",
            btw_nummer=(kenmerken.get(rij.id).btw_nummer if rij.id in kenmerken else None),
            kvk_nummer=(kenmerken.get(rij.id).kvk_nummer if rij.id in kenmerken else None),
        )
        for rij in session.scalars(
            select(VendorCache).where(
                VendorCache.administratie_id == administratie_id,
                VendorCache.verdwenen_uit_bron_op.is_(None),
                VendorCache.is_gearchiveerd.isnot(True),
            )
        )
    ]


def btw_per_vendor(session: Session, *, administratie_id: uuid.UUID) -> dict[str, str]:
    """vendor-id (str) → btw-nummer, voor de duplicaatcheck over crediteuren heen."""
    return {
        str(k.vendor_id): k.btw_nummer
        for k in kenmerken_per_vendor(session, administratie_id=administratie_id).values()
        if k.btw_nummer
    }


def neem_over_uit_veldvoorstel(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    veldvoorstel: dict | None,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> bool:
    """Upsert (bron 'factuur') zodra het opgeslagen boekvoorstel een crediteur heeft én het laatste
    veldvoorstel een gevalideerd btw-/KvK-nummer draagt. Een handmatig ingevoerd nummer ('handmatig')
    wordt nooit overschreven door de factuur. Audit oud→nieuw bij elke wijziging. True = iets gewijzigd."""
    if not veldvoorstel:
        return False
    btw = veldvoorstel.get("btw_nummer") or None
    kvk = veldvoorstel.get("kvk_nummer") or None
    if not btw and not kvk:
        return False
    rij = session.get(CrediteurKenmerk, (administratie_id, vendor_id))
    oud = (
        {"btw_nummer": rij.btw_nummer, "kvk_nummer": rij.kvk_nummer}
        if rij is not None
        else {"btw_nummer": None, "kvk_nummer": None}
    )
    if rij is None:
        rij = CrediteurKenmerk(administratie_id=administratie_id, vendor_id=vendor_id)
        session.add(rij)
    gewijzigd = False
    if btw and rij.btw_nummer_bron != "handmatig" and rij.btw_nummer != btw:
        rij.btw_nummer = btw
        rij.btw_nummer_geverifieerd = bool(veldvoorstel.get("btw_nummer_geverifieerd"))
        rij.btw_nummer_bron = "factuur"
        gewijzigd = True
    if kvk and rij.kvk_nummer_bron != "handmatig" and rij.kvk_nummer != kvk:
        rij.kvk_nummer = kvk
        rij.kvk_nummer_bron = "factuur"
        gewijzigd = True
    if not gewijzigd:
        return False
    rij.laatst_uit_document_id = document_id
    rij.bijgewerkt_door = actor_id
    rij.bijgewerkt_op = datetime.now(UTC)
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="crediteur_kenmerk",
        record_id=vendor_id,
        actie="crediteur_kenmerk_uit_factuur",
        correlatie_id=document_id,
        oude_waarde=oud,
        nieuwe_waarde={"btw_nummer": rij.btw_nummer, "kvk_nummer": rij.kvk_nummer, "document_id": str(document_id)},
        administratie_id=administratie_id,
    )
    return True


@dataclass(frozen=True)
class DubbeleCrediteur:
    vendor_id: uuid.UUID
    naam: str | None
    btw_nummer: str | None
    kvk_nummer: str | None
    ibans: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DubbelGroep:
    """Eén groep waarschijnlijk-dezelfde crediteuren; `sleutel` = waarop ze gelijk zijn."""

    soort: str  # 'btw_nummer' | 'kvk_nummer' | 'iban' | 'naam'
    sleutel: str
    crediteuren: list[DubbeleCrediteur]


def dubbele_crediteuren(*, administratie_id: uuid.UUID) -> list[DubbelGroep]:
    """Signalering (nooit samenvoegen, nooit verwijderen): groepen actieve crediteuren die hetzelfde
    btw-nummer, KvK-nummer of IBAN delen, of dezelfde genormaliseerde naam (zonder rechtsvorm/leestekens,
    hoofdletterongevoelig — 'Wola' vs 'Wola b.v.'). Volgorde: nummer-groepen eerst (zekerst), dan IBAN,
    dan naam; binnen een groep op naam."""
    with scoped_session(administratie_id) as session:
        vendors = list(
            session.scalars(
                select(VendorCache).where(
                    VendorCache.administratie_id == administratie_id,
                    VendorCache.verdwenen_uit_bron_op.is_(None),
                    VendorCache.is_gearchiveerd.isnot(True),
                )
            )
        )
        kenmerken = kenmerken_per_vendor(session, administratie_id=administratie_id)
        ibans: dict[uuid.UUID, list[str]] = defaultdict(list)
        for rij in session.scalars(select(LeverancierIban).where(LeverancierIban.administratie_id == administratie_id)):
            ibans[rij.vendor_id].append(rij.iban)

    per_vendor = {
        v.id: DubbeleCrediteur(
            vendor_id=v.id,
            naam=v.naam,
            btw_nummer=kenmerken[v.id].btw_nummer if v.id in kenmerken else None,
            kvk_nummer=kenmerken[v.id].kvk_nummer if v.id in kenmerken else None,
            ibans=sorted(ibans.get(v.id, [])),
        )
        for v in vendors
    }
    groepen: list[DubbelGroep] = []
    for soort, sleutels in (
        ("btw_nummer", lambda c: [c.btw_nummer] if c.btw_nummer else []),
        ("kvk_nummer", lambda c: [c.kvk_nummer] if c.kvk_nummer else []),
        ("iban", lambda c: c.ibans),
        ("naam", lambda c: [_genormaliseerd(c.naam)] if c.naam and _genormaliseerd(c.naam) else []),
    ):
        per_sleutel: dict[str, list[DubbeleCrediteur]] = defaultdict(list)
        for c in per_vendor.values():
            for s in sleutels(c):
                per_sleutel[s].append(c)
        for sleutel in sorted(per_sleutel):
            leden = per_sleutel[sleutel]
            if len(leden) > 1:
                leden_gesorteerd = sorted(leden, key=lambda c: (c.naam or "").lower())
                groepen.append(DubbelGroep(soort=soort, sleutel=sleutel, crediteuren=leden_gesorteerd))
    return groepen


