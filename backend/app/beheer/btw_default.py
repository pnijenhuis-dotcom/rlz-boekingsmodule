"""Btw-default per administratie — blok E medewerker-wensen 04-09 (mockup
`projectverdeling-en-regelvoorstellen.html` blok 3, ontwerpnotitie ⑧; migratie 0108
`platform.administratie.standaard_taxrate_id`).

Beheerder-instelling (default UIT = NULL; bestaande administraties ongemoeid tot Peter activeert): het
standaard-btw-voorstel dat in de boekvoorstel-prefill ALLEEN regels vult waar factuur én
leverancier-geheugen niets opleveren (`app/documenten/regel_prefill.py`, chip "standaard administratie").
Steigerbouw-casus: "verlegd hoog". De waarde moet een gesyncte btw-code van déze administratie zijn
(`taxrate_cache`, niet verdwenen) — onbekend id = 422; audit oud→nieuw mét tariefnaam. De harde checks
blijven onverkort de poort: een verkeerde default kan nooit stil doorboeken.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.schemas_basis import StrikteInvoer
from app.sync.models import TaxRateCache


class BtwDefaultFout(Exception):
    """Onbekende administratie (404 in de router)."""


class BtwDefaultOnbekendTarief(Exception):
    """Het gekozen tarief is geen gesyncte btw-code van deze administratie (422 in de router)."""


class BtwOptieDto(BaseModel):
    id: uuid.UUID
    naam: str | None = None
    percentage: Decimal | None = None


class BtwDefaultDto(BaseModel):
    """GET/PUT-antwoord: de huidige default (None = uit) + de keuzelijst uit de gesyncte tarieven."""

    taxrate_id: uuid.UUID | None = None
    taxrate_naam: str | None = None
    opties: list[BtwOptieDto] = []


class BtwDefaultInput(StrikteInvoer):
    taxrate_id: uuid.UUID | None = None


@dataclass(frozen=True)
class BtwDefaultStand:
    taxrate_id: uuid.UUID | None
    taxrate_naam: str | None
    opties: list[BtwOptieDto]


def _opties(session, administratie_id: uuid.UUID) -> list[TaxRateCache]:
    return list(
        session.scalars(
            select(TaxRateCache)
            .where(TaxRateCache.administratie_id == administratie_id, TaxRateCache.verdwenen_uit_bron_op.is_(None))
            .order_by(TaxRateCache.naam)
        )
    )


def _stand(session, administratie: Administratie) -> BtwDefaultStand:
    opties = _opties(session, administratie.id)
    per_id = {o.id: o for o in opties}
    huidig = administratie.standaard_taxrate_id
    # Een default die uit de sync verdween blijft zichtbaar als id, mét naam None — de Beheerder ziet dan
    # dat de keuze niet meer in de lijst staat (nooit stil op NULL zetten).
    return BtwDefaultStand(
        taxrate_id=huidig,
        taxrate_naam=per_id[huidig].naam if huidig in per_id else None,
        opties=[BtwOptieDto(id=o.id, naam=o.naam, percentage=o.percentage) for o in opties],
    )


def haal_btw_default_op(*, administratie_id: uuid.UUID) -> BtwDefaultStand:
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BtwDefaultFout(f"Onbekende administratie: {administratie_id}")
        return _stand(session, administratie)


def zet_btw_default(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, taxrate_id: uuid.UUID | None
) -> BtwDefaultStand:
    """Beheerder-only (router). `taxrate_id` None = uit. Audit oud→nieuw mét de tariefnamen."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BtwDefaultFout(f"Onbekende administratie: {administratie_id}")
        opties = {o.id: o for o in _opties(session, administratie_id)}
        if taxrate_id is not None and taxrate_id not in opties:
            raise BtwDefaultOnbekendTarief(
                "Onbekende btw-code voor deze administratie — kies een tarief uit de gesyncte lijst "
                "(sync de btw-codes opnieuw als het tarief nieuw is in Reeleezee)."
            )
        oud_id = administratie.standaard_taxrate_id
        oud_naam = opties[oud_id].naam if oud_id in opties else None
        administratie.standaard_taxrate_id = taxrate_id
        if oud_id != taxrate_id:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie="standaard_taxrate_gewijzigd",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"standaard_taxrate_id": str(oud_id) if oud_id else None, "naam": oud_naam},
                nieuwe_waarde={
                    "standaard_taxrate_id": str(taxrate_id) if taxrate_id else None,
                    "naam": opties[taxrate_id].naam if taxrate_id else None,
                },
                administratie_id=administratie_id,
            )
        session.flush()
        return _stand(session, administratie)


def naar_dto(stand: BtwDefaultStand) -> BtwDefaultDto:
    return BtwDefaultDto(taxrate_id=stand.taxrate_id, taxrate_naam=stand.taxrate_naam, opties=stand.opties)
