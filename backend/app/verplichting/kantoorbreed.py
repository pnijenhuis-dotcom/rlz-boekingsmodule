"""Inzicht › Verplichtingen — KANTOORBREED lijstpatroon (mockup `offerte-matching.html` blok 3 + ⑦).

Zelfde patroon als `app/terugkerend/kantoorbreed.py`: één endpoint zónder administratie in het pad,
scope = `mijn_administraties(actor)` (Beheerder = alle actieve), per administratie gelezen in
`scoped_session(aid, actor_id=…)` — RLS blijft de scope-waarheid. Aggregeren/sorteren/pagineren in
Python. Alleen lezen; geen RLZ-calls, geen AI.

Eén RIJ = één goedgekeurde verplichting mét haar verbruiksstand en de gekoppelde facturen (uitklap).
Urgentste bovenaan: overschreden eerst (grootste bedrag erover), dan lopend op hoogste verbruik-%.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.auth import service as auth_service
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentStatus
from app.sync.models import ProjectCache, VendorCache
from app.verplichting import match as match_motor
from app.verplichting.models import Verplichting, VerplichtingMatch
from app.verplichting.service import VerplichtingFout

PER_PAGINA = 25
STATUSSEN = ("lopend", "overschreden", "vervallen", "alle")


@dataclass(frozen=True)
class FactuurRij:
    document_id: uuid.UUID
    referentie: str | None
    factuurdatum: date | None
    bedrag_excl: Decimal | None
    status: str
    verrekend: bool


@dataclass(frozen=True)
class KantoorRij:
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    offertenummer: str | None
    soort_label: str | None
    leverancier_naam: str | None
    project_naam: str | None
    totaal_excl: Decimal | None
    verbruikt_excl: Decimal
    percentage: int | None
    over_excl: Decimal | None
    goedgekeurd_op: datetime | None
    goedgekeurd_door_naam: str | None
    geldig_tot: date | None
    status: str
    facturen: list[FactuurRij]


@dataclass(frozen=True)
class Tellers:
    lopend: int
    overschreden: int
    vervallen: int


@dataclass(frozen=True)
class AdministratieFacet:
    administratie_id: uuid.UUID
    naam: str
    aantal: int


@dataclass(frozen=True)
class Facetten:
    status: dict[str, int]
    administraties: list[AdministratieFacet]


@dataclass(frozen=True)
class KantoorLijst:
    rijen: list[KantoorRij]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: Tellers
    facetten: Facetten


def _rij_status(verplichting: Verplichting) -> str:
    if verplichting.vervallen_op is not None:
        return "vervallen"
    totaal = verplichting.goedgekeurd_bedrag_excl
    verbruikt = Decimal(verplichting.verbruikt_bedrag_excl or 0)
    if totaal is not None and verbruikt > totaal:
        return "overschreden"
    return "lopend"


def _alle_rijen(*, actor_id: uuid.UUID, rol: GebruikerRol) -> list[KantoorRij]:
    administraties = auth_service.mijn_administraties(actor_id=actor_id, rol=rol)
    rijen: list[KantoorRij] = []
    for administratie in administraties:
        aid, naam = administratie.id, administratie.naam
        with scoped_session(aid, actor_id=actor_id) as session:
            # Beheerder-bypass leest via mijn_administraties alles; RLS blijft per administratie de poort.
            if session.get(Administratie, aid) is None:
                continue
            verplichtingen = list(
                session.execute(
                    select(Verplichting)
                    .join(Document, Document.id == Verplichting.document_id)
                    .where(
                        Verplichting.administratie_id == aid,
                        Document.status == DocumentStatus.GEACCORDEERD,
                    )
                ).scalars()
            )
            if not verplichtingen:
                continue
            vendor_namen = dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(VendorCache.administratie_id == aid)
                ).all()
            )
            project_namen = dict(
                session.execute(
                    select(ProjectCache.id, ProjectCache.naam).where(ProjectCache.administratie_id == aid)
                ).all()
            )
            gebruiker_namen = _gebruikersnamen(
                session, {v.goedgekeurd_door for v in verplichtingen if v.goedgekeurd_door}
            )
            facturen_per_verplichting = _facturen_per_verplichting(
                session, administratie_id=aid, verplichting_ids=[v.document_id for v in verplichtingen]
            )
            for v in verplichtingen:
                totaal = v.goedgekeurd_bedrag_excl
                verbruikt = Decimal(v.verbruikt_bedrag_excl or 0)
                over = (verbruikt - totaal).quantize(Decimal("0.01")) if totaal is not None else None
                rijen.append(
                    KantoorRij(
                        document_id=v.document_id,
                        administratie_id=aid,
                        administratie_naam=naam,
                        offertenummer=v.offertenummer,
                        soort_label=v.soort_label,
                        leverancier_naam=vendor_namen.get(v.vendor_id) if v.vendor_id else None,
                        project_naam=project_namen.get(v.project_id) if v.project_id else None,
                        totaal_excl=totaal,
                        verbruikt_excl=verbruikt,
                        percentage=match_motor.percentage(verbruikt, totaal),
                        over_excl=over if over is not None and over > 0 else None,
                        goedgekeurd_op=v.goedgekeurd_op,
                        goedgekeurd_door_naam=gebruiker_namen.get(v.goedgekeurd_door),
                        geldig_tot=v.geldig_tot,
                        status=_rij_status(v),
                        facturen=facturen_per_verplichting.get(v.document_id, []),
                    )
                )
    return rijen


def _gebruikersnamen(session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:  # noqa: ANN001
    if not ids:
        return {}
    from app.db.models import Gebruiker

    return dict(session.execute(select(Gebruiker.id, Gebruiker.naam).where(Gebruiker.id.in_(ids))).all())


def _facturen_per_verplichting(
    session, *, administratie_id: uuid.UUID, verplichting_ids: list[uuid.UUID]  # noqa: ANN001
) -> dict[uuid.UUID, list[FactuurRij]]:
    """Bulk (geen N+1): de gematchte facturen per verplichting — de uitklap in het scherm."""
    if not verplichting_ids:
        return {}
    rijen = session.execute(
        select(VerplichtingMatch, Document, Boekvoorstel)
        .join(Document, Document.id == VerplichtingMatch.document_id)
        .join(Boekvoorstel, Boekvoorstel.document_id == VerplichtingMatch.document_id, isouter=True)
        .where(
            VerplichtingMatch.administratie_id == administratie_id,
            VerplichtingMatch.verplichting_document_id.in_(verplichting_ids),
            VerplichtingMatch.uitkomst.in_([match_motor.BINNEN, match_motor.BUITEN]),
        )
        .order_by(Document.aangemaakt_op)
    ).all()
    per: dict[uuid.UUID, list[FactuurRij]] = {}
    for match, document, voorstel in rijen:
        per.setdefault(match.verplichting_document_id, []).append(
            FactuurRij(
                document_id=match.document_id,
                referentie=voorstel.referentie if voorstel is not None else None,
                factuurdatum=voorstel.factuurdatum if voorstel is not None else None,
                bedrag_excl=match.bedrag_excl,
                status=document.status.value,
                verrekend=match.verrekend_op is not None,
            )
        )
    return per


def _urgentie(r: KantoorRij) -> tuple:
    """Overschreden eerst (grootste bedrag erover), dan lopend op hoogste verbruik-%, dan
    alfabetisch leverancier — deterministisch en stabiel."""
    rang = {"overschreden": 0, "lopend": 1, "vervallen": 2}.get(r.status, 3)
    return (
        rang,
        -(r.over_excl or Decimal(0)),
        -(r.percentage or 0),
        (r.leverancier_naam or "").lower(),
        r.administratie_naam.lower(),
        str(r.document_id),
    )


def lijst(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    pagina: int = 1,
    q: str = "",
    administratie_id: uuid.UUID | None = None,
    status: str = "lopend",
    per_pagina: int = PER_PAGINA,
) -> KantoorLijst:
    if status not in STATUSSEN:
        raise VerplichtingFout(f"Onbekende status: {status}")
    alles = _alle_rijen(actor_id=actor_id, rol=rol)
    tellers = Tellers(
        lopend=sum(1 for r in alles if r.status == "lopend"),
        overschreden=sum(1 for r in alles if r.status == "overschreden"),
        vervallen=sum(1 for r in alles if r.status == "vervallen"),
    )
    zoek = q.strip().lower()

    def matcht_zoek(r: KantoorRij) -> bool:
        if not zoek:
            return True
        velden = (r.leverancier_naam, r.offertenummer, r.project_naam, r.administratie_naam)
        return any(zoek in (veld or "").lower() for veld in velden)

    na_q = [r for r in alles if matcht_zoek(r)]
    na_admin = [r for r in na_q if administratie_id is None or r.administratie_id == administratie_id]
    status_facet = {s: len([r for r in na_admin if s == "alle" or r.status == s]) for s in STATUSSEN}
    na_status = [r for r in na_q if status == "alle" or r.status == status]
    per_admin: dict[uuid.UUID, AdministratieFacet] = {}
    for r in na_status:
        bestaand = per_admin.get(r.administratie_id)
        per_admin[r.administratie_id] = AdministratieFacet(
            administratie_id=r.administratie_id,
            naam=r.administratie_naam,
            aantal=(bestaand.aantal if bestaand else 0) + 1,
        )
    selectie = [r for r in na_admin if status == "alle" or r.status == status]
    selectie.sort(key=_urgentie)
    start = max(pagina - 1, 0) * per_pagina
    return KantoorLijst(
        rijen=selectie[start : start + per_pagina],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=per_pagina,
        administraties_in_selectie=len({r.administratie_id for r in selectie}),
        tellers=tellers,
        facetten=Facetten(
            status=status_facet, administraties=sorted(per_admin.values(), key=lambda f: f.naam.lower())
        ),
    )
