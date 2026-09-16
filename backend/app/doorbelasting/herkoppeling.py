"""Herkoppeling doelentiteit (Peter 12-09/16-09, blok 1 — geen stille no-op, KP7 punt 6).

Casus: de whitelist-rij "Kempen Chalets B.V." is op 15-08 geseed zónder `doel_administratie_id`; de administratie is later
onboarded en nooit herkoppeld (de seed matcht alleen op het seed-moment; "+ Doelentiteit toevoegen" toont alleen
administraties die nog NIET in de whitelist staan). Zelfde klasse als Mantelzorgwoningen 01-09.

Regels:
- Loopt bij onboarding van een administratie (ná `maak_administraties_aan`) én dagelijks in `sync-alles`.
- Per actieve whitelist-rij zonder doel: kandidaten = actieve administraties; vergelijking op de genormaliseerde naam
  (`intercompany.identiteit.naam_norm`) tegen de administratienaam ÉN de bron-identiteitsnaam (RLZ `CompanyName` /
  Odoo `res.company.name`, tabel `administratie_identiteit`). KvK zou winnen, maar de whitelist-rij draagt geen KvK
  (alleen naam + Customer-GUID in de bron) — daarom is exact-op-naam de enige koppelbasis; nooit raden.
- Precies één exacte treffer → koppelen (`service.wijzig_mapping`, audit `doorbelasting_mapping_gewijzigd`) + audit
  `doelentiteit_gekoppeld`. Eén bijna-match (`service._is_bijna_match`, enkelvoud/meervoud-tolerant) of méér dan één
  exacte treffer → NIET koppelen, audit `doelentiteit_niet_gekoppeld` (reden bijna_match | meerdere) → LET-OP mét
  handeling "Koppel administratie…" (combobox op de rij in Instellingen › Doorbelasting). Geen kandidaat → `geen`
  (zichtbaar in de teller, geen LET-OP: het doel is gewoon nog niet onboarded).
- Per bron-administratie één audit `doorbelasting_herkoppeling_run` mét tellers (bron voor de automatiseringen-teller
  `doorbelasting_herkoppeling`). Geen eigenaar/actor nodig: de systeem-actor tekent (afwezig-pad).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.doorbelasting.models import DoorbelastingMapping

logger = logging.getLogger(__name__)

_MODULE = "boekhouding"
AUDIT_GEKOPPELD = "doelentiteit_gekoppeld"
AUDIT_NIET_GEKOPPELD = "doelentiteit_niet_gekoppeld"
AUDIT_RUN = "doorbelasting_herkoppeling_run"

UITKOMST_GEKOPPELD = "gekoppeld"
UITKOMST_BIJNA_MATCH = "bijna_match"
UITKOMST_MEERDERE = "meerdere"
UITKOMST_GEEN = "geen"


@dataclass(frozen=True)
class Kandidaat:
    administratie_id: uuid.UUID
    naam: str
    identiteit_naam: str | None = None


@dataclass(frozen=True)
class HerkoppelRij:
    bron_administratie_id: uuid.UUID
    mapping_id: uuid.UUID
    doelentiteit_naam: str
    uitkomst: str
    doel_administratie_id: uuid.UUID | None = None
    kandidaten: tuple[Kandidaat, ...] = ()


@dataclass
class HerkoppelUitkomst:
    rijen: list[HerkoppelRij] = field(default_factory=list)
    fouten: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    def tel(self, uitkomst: str) -> int:
        return sum(1 for r in self.rijen if r.uitkomst == uitkomst)

    @property
    def open(self) -> int:
        return len(self.rijen)

    def regels(self) -> list[str]:
        uit = [
            f"  herkoppeling doelentiteiten: open={self.open} gekoppeld={self.tel(UITKOMST_GEKOPPELD)} "
            f"bijna_match={self.tel(UITKOMST_BIJNA_MATCH)} meerdere={self.tel(UITKOMST_MEERDERE)} geen={self.tel(UITKOMST_GEEN)}"
        ]
        for r in self.rijen:
            if r.uitkomst == UITKOMST_GEKOPPELD:
                uit.append(f"    GEKOPPELD  {r.doelentiteit_naam!r} → {r.kandidaten[0].naam!r} ({r.doel_administratie_id})")
            elif r.uitkomst in (UITKOMST_BIJNA_MATCH, UITKOMST_MEERDERE):
                namen = ", ".join(repr(k.naam) for k in r.kandidaten)
                uit.append(f"    LET-OP     {r.doelentiteit_naam!r}: {r.uitkomst} — kandidaten {namen}; koppel handmatig (Instellingen › Doorbelasting)")
        for aid, m in self.fouten:
            uit.append(f"    FOUT {aid}: {m}")
        return uit


def _kandidaten(uitgezonderd: uuid.UUID) -> list[Kandidaat]:
    """Actieve administraties (mét identiteitsnaam uit `administratie_identiteit` als die er is), zonder de bron zelf."""
    from app.intercompany.identiteit import alle_identiteiten

    try:
        identiteiten = alle_identiteiten()
    except Exception:  # noqa: BLE001 — identiteit is een extra bron, geen voorwaarde
        logger.exception("herkoppeling: identiteiten niet gelezen")
        identiteiten = {}
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.execute(
            select(Administratie.id, Administratie.naam).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
        ).all()
    uit: list[Kandidaat] = []
    for aid, naam in rijen:
        if aid == uitgezonderd:
            continue
        ident = identiteiten.get(aid)
        uit.append(Kandidaat(administratie_id=aid, naam=naam, identiteit_naam=getattr(ident, "naam", None)))
    return uit


def beoordeel(doelentiteit_naam: str, kandidaten: Iterable[Kandidaat]) -> tuple[str, tuple[Kandidaat, ...]]:
    """Puur: (uitkomst, kandidaten). Exact op genormaliseerde naam (administratienaam óf identiteitsnaam) wint;
    één exacte = gekoppeld, meerdere exacte = meerdere; geen exacte maar precies één bijna-match = bijna_match;
    anders geen (méér dan één bijna-match is óók 'meerdere' — nooit raden)."""
    from app.doorbelasting.service import _is_bijna_match
    from app.intercompany.identiteit import naam_norm

    doel_norm = naam_norm(doelentiteit_naam)
    exact: list[Kandidaat] = []
    bijna: list[Kandidaat] = []
    for k in kandidaten:
        namen = [k.naam] + ([k.identiteit_naam] if k.identiteit_naam else [])
        if doel_norm and any(naam_norm(n) == doel_norm for n in namen):
            exact.append(k)
        elif any(_is_bijna_match(doelentiteit_naam, n) for n in namen):
            bijna.append(k)
    if len(exact) == 1:
        return UITKOMST_GEKOPPELD, tuple(exact)
    if len(exact) > 1:
        return UITKOMST_MEERDERE, tuple(exact)
    if len(bijna) == 1:
        return UITKOMST_BIJNA_MATCH, tuple(bijna)
    if len(bijna) > 1:
        return UITKOMST_MEERDERE, tuple(bijna)
    return UITKOMST_GEEN, ()


def _bron_administraties(administratie_ids: Iterable[uuid.UUID] | None) -> list[uuid.UUID]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie.id).where(Administratie.actief.is_(True))
        if administratie_ids is not None:
            q = q.where(Administratie.id.in_(list(administratie_ids)))
        return list(session.scalars(q.order_by(Administratie.naam)))


def herkoppel_doelen(
    *,
    administratie_ids: Iterable[uuid.UUID] | None = None,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    kandidaten: list[Kandidaat] | None = None,
) -> HerkoppelUitkomst:
    """Alle bron-administraties (of de gegeven) × hun actieve whitelist-rijen zonder doel. `kandidaten` is een
    test-seam; productie leest de actieve administraties. Nooit een stop op één administratie."""
    from app.doorbelasting import service

    uitkomst = HerkoppelUitkomst()
    for bron_id in _bron_administraties(administratie_ids):
        try:
            with scoped_session(bron_id, actor_id=actor_id) as session:
                open_rijen = list(
                    session.scalars(
                        select(DoorbelastingMapping).where(
                            DoorbelastingMapping.administratie_id == bron_id,
                            DoorbelastingMapping.actief.is_(True),
                            DoorbelastingMapping.doel_administratie_id.is_(None),
                        )
                    )
                )
                open_rijen = [(m.id, m.doelentiteit_naam) for m in open_rijen]
            if not open_rijen:
                continue
            kand = kandidaten if kandidaten is not None else _kandidaten(bron_id)
            tellers = {UITKOMST_GEKOPPELD: 0, UITKOMST_BIJNA_MATCH: 0, UITKOMST_MEERDERE: 0, UITKOMST_GEEN: 0}
            niet_gekoppeld: list[dict] = []
            for mapping_id, naam in open_rijen:
                soort, treffers = beoordeel(naam, kand)
                tellers[soort] += 1
                rij = HerkoppelRij(
                    bron_administratie_id=bron_id,
                    mapping_id=mapping_id,
                    doelentiteit_naam=naam,
                    uitkomst=soort,
                    doel_administratie_id=treffers[0].administratie_id if soort == UITKOMST_GEKOPPELD else None,
                    kandidaten=treffers,
                )
                uitkomst.rijen.append(rij)
                if soort == UITKOMST_GEKOPPELD:
                    service.wijzig_mapping(
                        administratie_id=bron_id,
                        mapping_id=mapping_id,
                        actor_id=actor_id,
                        doel_administratie_id=treffers[0].administratie_id,
                    )
                    with scoped_session(bron_id, actor_id=actor_id) as session:
                        record_audit_event(
                            session,
                            actor_id=actor_id,
                            module=_MODULE,
                            tabel="doorbelasting_mapping",
                            record_id=mapping_id,
                            actie=AUDIT_GEKOPPELD,
                            correlatie_id=mapping_id,
                            nieuwe_waarde={
                                "doelentiteit_naam": naam,
                                "doel_administratie_id": str(treffers[0].administratie_id),
                                "doel_naam": treffers[0].naam,
                                "basis": "naam_exact",
                            },
                            administratie_id=bron_id,
                        )
                elif soort in (UITKOMST_BIJNA_MATCH, UITKOMST_MEERDERE):
                    niet_gekoppeld.append(
                        {
                            "mapping_id": str(mapping_id),
                            "doelentiteit_naam": naam,
                            "reden": soort,
                            "kandidaten": [{"id": str(k.administratie_id), "naam": k.naam} for k in treffers],
                        }
                    )
            with scoped_session(bron_id, actor_id=actor_id) as session:
                for nk in niet_gekoppeld:
                    record_audit_event(
                        session,
                        actor_id=actor_id,
                        module=_MODULE,
                        tabel="doorbelasting_mapping",
                        record_id=uuid.UUID(nk["mapping_id"]),
                        actie=AUDIT_NIET_GEKOPPELD,
                        correlatie_id=uuid.UUID(nk["mapping_id"]),
                        nieuwe_waarde=nk,
                        administratie_id=bron_id,
                    )
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module=_MODULE,
                    tabel="doorbelasting_mapping",
                    record_id=bron_id,
                    actie=AUDIT_RUN,
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={"open": len(open_rijen), **tellers, "niet_gekoppeld": niet_gekoppeld},
                    administratie_id=bron_id,
                )
        except Exception as exc:  # noqa: BLE001 — zichtbaar per administratie, nooit een stop
            logger.exception("herkoppeling doelentiteit mislukt voor %s", bron_id)
            uitkomst.fouten.append((bron_id, f"{type(exc).__name__}: {str(exc)[:200]}"))
    return uitkomst


def rapporteer_herkoppeling(administratie_ids: Iterable[uuid.UUID] | None = None) -> int:
    """Sync-alles-/onboarding-stap: regels naar stdout, exit 1 alleen bij een omgevallen administratie."""
    import sys

    try:
        u = herkoppel_doelen(administratie_ids=administratie_ids)
    except Exception as exc:  # noqa: BLE001
        print(f"  FOUT herkoppeling doelentiteiten: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for regel in u.regels():
        print(regel, file=sys.stderr if regel.strip().startswith("FOUT") else sys.stdout)
    return 1 if u.fouten else 0
