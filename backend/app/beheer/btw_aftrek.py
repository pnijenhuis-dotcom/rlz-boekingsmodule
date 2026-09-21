"""Aftrek-uitgesloten grootboekrekeningen (BUA) per administratie — opdracht Peter 18-09, casus Rituals 88-186308
(representatie: "daar mag je de btw niet in aftrek nemen, ook al staat die wel op de factuur"); migratie 0163
`platform.grootboekrekening.btw_aftrek_uitgesloten`.

Beheerder-only (tab "Boeken & AI" op de administratie-detailpagina, blok "Btw niet aftrekbaar"): lijst van de
kostenrekeningen mét per rij de stand (uit/aan) en een deterministisch VOORSTEL — 4xxx-kostenrekening (AccountType 2)
waarvan de naam representatie / relatiegeschenk / personeelsvoorzien* / kantine bevat én de RLZ-default 0 %/geen btw is
of ontbreekt. Het voorstel is een vinkje dat de Beheerder BEVESTIGT; niets wordt stil aangezet. PUT = de exacte set
(oud→nieuw in het audit_event, mét codes). De prefill (`regel_prefill.py`) zet op zo'n rekening 0 %/geen btw en de
factuur-btw in de kosten; de harde check "Btw-bedrag past bij tarief" blijft de poort.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.schemas_basis import StrikteInvoer
from app.sync.models import TaxRateCache

#: Naamdelen die (mét een 0 %-/ontbrekende RLZ-default op een 4xxx-kostenrekening) een BUA-voorstel opleveren.
VOORSTEL_NAAMDELEN = ("representatie", "relatiegeschenk", "personeelsvoorzien", "kantine")
_VOORSTEL_RE = re.compile("|".join(VOORSTEL_NAAMDELEN), re.IGNORECASE)
SOORT_KOSTEN = 2


class BtwAftrekFout(Exception):
    """Onbekende administratie (404)."""


class BtwAftrekOnbekendeRekening(Exception):
    """Een ledger_id in de PUT is geen (actuele) grootboekrekening van deze administratie (422)."""


class BtwAftrekRekeningDto(BaseModel):
    ledger_id: uuid.UUID
    code: str
    naam: str
    uitgesloten: bool
    voorstel: bool
    standaard_percentage: Decimal | None = None
    standaard_naam: str | None = None
    gezet_op: datetime | None = None


class BtwAftrekDto(BaseModel):
    rekeningen: list[BtwAftrekRekeningDto]
    aantal_uitgesloten: int
    aantal_voorstel: int


class BtwAftrekInput(StrikteInvoer):
    ledger_ids: list[uuid.UUID]


def is_voorstel(*, code: str, naam: str, soort: int, standaard_percentage: Decimal | None, heeft_default: bool) -> bool:
    """Pure regel: 4xxx-kostenrekening, naam bevat een BUA-woord, en de RLZ-default is 0 %/geen btw of ontbreekt."""
    if not code.startswith("4") or soort != SOORT_KOSTEN:
        return False
    if not _VOORSTEL_RE.search(naam or ""):
        return False
    niet_nul = standaard_percentage is not None and standaard_percentage != 0
    if heeft_default and niet_nul:
        return False
    return True


def _stand(session, administratie_id: uuid.UUID) -> list[BtwAftrekRekeningDto]:
    tarieven = {
        t.id: t for t in session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id))
    }
    rijen = session.scalars(
        select(Grootboekrekening)
        .where(
            Grootboekrekening.administratie_id == administratie_id,
            Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            Grootboekrekening.is_totaalrekening.is_(False),
            Grootboekrekening.soort == SOORT_KOSTEN,
        )
        .order_by(Grootboekrekening.code)
    ).all()
    uit: list[BtwAftrekRekeningDto] = []
    for r in rijen:
        tarief = tarieven.get(r.standaard_taxrate_id) if r.standaard_taxrate_id else None
        pct = tarief.percentage if tarief is not None else None
        uit.append(
            BtwAftrekRekeningDto(
                ledger_id=r.ledger_id,
                code=r.code,
                naam=r.naam,
                uitgesloten=bool(r.btw_aftrek_uitgesloten),
                voorstel=is_voorstel(
                    code=r.code,
                    naam=r.naam,
                    soort=r.soort,
                    standaard_percentage=pct,
                    heeft_default=r.standaard_taxrate_id is not None,
                ),
                standaard_percentage=pct,
                standaard_naam=tarief.naam if tarief is not None else None,
                gezet_op=r.btw_aftrek_uitgesloten_op,
            )
        )
    return uit


def naar_dto(rekeningen: list[BtwAftrekRekeningDto]) -> BtwAftrekDto:
    return BtwAftrekDto(
        rekeningen=rekeningen,
        aantal_uitgesloten=sum(1 for r in rekeningen if r.uitgesloten),
        aantal_voorstel=sum(1 for r in rekeningen if r.voorstel and not r.uitgesloten),
    )


def haal_op(*, administratie_id: uuid.UUID) -> BtwAftrekDto:
    with scoped_session(administratie_id) as session:
        if session.get(Administratie, administratie_id) is None:
            raise BtwAftrekFout(f"Onbekende administratie {administratie_id}")
        return naar_dto(_stand(session, administratie_id))


def zet(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ledger_ids: list[uuid.UUID]) -> BtwAftrekDto:
    """De exacte set aftrek-uitgesloten rekeningen zetten (aan wat erin staat, uit wat eruit valt) — audit oud→nieuw."""
    gewenst = set(ledger_ids)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        if session.get(Administratie, administratie_id) is None:
            raise BtwAftrekFout(f"Onbekende administratie {administratie_id}")
        rijen = session.scalars(
            select(Grootboekrekening).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
        ).all()
        per_id = {r.ledger_id: r for r in rijen}
        onbekend = gewenst - set(per_id)
        if onbekend:
            raise BtwAftrekOnbekendeRekening(
                f"Onbekende grootboekrekening(en) voor deze administratie: {', '.join(sorted(map(str, onbekend)))}"
            )
        oud = sorted(r.code for r in rijen if r.btw_aftrek_uitgesloten)
        nu = datetime.now(UTC)
        gewijzigd = False
        for r in rijen:
            nieuw = r.ledger_id in gewenst
            if bool(r.btw_aftrek_uitgesloten) != nieuw:
                r.btw_aftrek_uitgesloten = nieuw
                r.btw_aftrek_uitgesloten_op = nu if nieuw else None
                gewijzigd = True
        if gewijzigd:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="beheer",
                tabel="platform.grootboekrekening",
                record_id=administratie_id,
                actie="btw_aftrek_uitgesloten_gewijzigd",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"codes": oud},
                nieuwe_waarde={"codes": sorted(per_id[i].code for i in gewenst)},
                administratie_id=administratie_id,
            )
        session.flush()
        return naar_dto(_stand(session, administratie_id))


class VoegToeResultaat(BaseModel):
    """Uitkomst van `voeg_toe`: welke codes aangingen, welke al aan stonden, en de nieuwe stand."""

    toegevoegd: list[str]
    al_aan: list[str]
    stand: BtwAftrekDto


def voeg_toe(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, ledger_ids: list[uuid.UUID], bron: str | None = None
) -> VoegToeResultaat:
    """Bestaande set ∪ `ledger_ids` (CLI `bua-kenmerk-zetten`, opdracht Peter 21-09): alleen AANzetten, nooit iets uit —
    `zet` blijft de exacte-set-variant voor het scherm. Zelfde audit-actie oud→nieuw, uitsluitend bij een wijziging;
    `bron` komt als `nieuwe_waarde["bron"]` mee (herkenbaar als bulk-stap naast de Beheerder-knop). Idempotent."""
    gewenst = set(ledger_ids)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        if session.get(Administratie, administratie_id) is None:
            raise BtwAftrekFout(f"Onbekende administratie {administratie_id}")
        rijen = session.scalars(
            select(Grootboekrekening).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
        ).all()
        per_id = {r.ledger_id: r for r in rijen}
        onbekend = gewenst - set(per_id)
        if onbekend:
            raise BtwAftrekOnbekendeRekening(
                f"Onbekende grootboekrekening(en) voor deze administratie: {', '.join(sorted(map(str, onbekend)))}"
            )
        oud = sorted(r.code for r in rijen if r.btw_aftrek_uitgesloten)
        nu = datetime.now(UTC)
        toegevoegd: list[str] = []
        al_aan: list[str] = []
        for ledger_id in gewenst:
            r = per_id[ledger_id]
            if r.btw_aftrek_uitgesloten:
                al_aan.append(r.code)
                continue
            r.btw_aftrek_uitgesloten = True
            r.btw_aftrek_uitgesloten_op = nu
            toegevoegd.append(r.code)
        if toegevoegd:
            nieuw: dict = {"codes": sorted(r.code for r in rijen if r.btw_aftrek_uitgesloten)}
            if bron:
                nieuw["bron"] = bron
            record_audit_event(
                session,
                actor_id=actor_id,
                module="beheer",
                tabel="platform.grootboekrekening",
                record_id=administratie_id,
                actie="btw_aftrek_uitgesloten_gewijzigd",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"codes": oud},
                nieuwe_waarde=nieuw,
                administratie_id=administratie_id,
            )
        session.flush()
        return VoegToeResultaat(
            toegevoegd=sorted(toegevoegd), al_aan=sorted(al_aan), stand=naar_dto(_stand(session, administratie_id))
        )
