"""Kantoorbreed bladeren door het geboekte archief — B4 design-ronde 03-09 (mockup
`inzicht-kantoorbreed.html` ⑥ + ⑨ = bouwnorm; principe "minimale mens, maximale autonomie",
besluit Peter 02-09: het kantoor zoekt niet meer per administratie, de administratie is een
FACET-filter en nooit een poort).

`GET /archief?pagina=&per_pagina=&administratie_id=&van=&tot=&q=&sort=` (vereis_kantoorrol,
router-breed). Scope = de administraties van de actor (`mijn_administraties`; Beheerder = alle
actieve), per administratie gelezen in `scoped_session(aid, actor_id=actor)` — RLS blijft de
scope-waarheid, nooit `scoped_session(None)` voor administratie-gebonden rijen (conventies §RLS).

Paginering over meerdere administraties (gekozen aanpak): per administratie een aparte
count-query (voedt óók de facetwaarden) en — alleen voor de administraties in de selectie mét
rijen — de server-side gesorteerde TOP-K met K = pagina × per_pagina (meer heeft één
administratie nooit nodig om de gevraagde pagina te vullen); de rijen worden in Python
samengevoegd, opnieuw gesorteerd met exact dezelfde sleutel (tekst lowercase bytegewijs =
SQL `lower() COLLATE "C"`, ontbrekende waarden achteraan, secundair boekmoment nieuwste eerst,
tertiair document-id) en gesneden. Is precies één administratie gekozen (facet gezet of scope
van één), dan gaat LIMIT/OFFSET rechtstreeks in SQL. SCHAALGRENS: bij meerdere administraties is
pagina × per_pagina begrensd op `MAX_DIEPTE` (5000 rijen per administratie in het geheugen) —
daarboven vraagt de route om verfijnen op administratie of datumvenster (422, leesbaar); het
default-venster van 12 maanden houdt dit in de praktijk ver buiten bereik.

De per-administratie-route (`router.py`) blijft bestaan voor de klantpagina-deeplink."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth import service as auth_service
from app.auth.deps import CurrentGebruiker, vereis_kantoorrol
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.zoeken import service
from app.zoeken.router import ArchiefDocumentDto
from app.zoeken.service import ArchiefDocument, ArchiefFout, ArchiefSortering

MAX_DIEPTE = 5000


@dataclass(frozen=True)
class KantoorbreedRij:
    administratie_id: uuid.UUID
    administratie_naam: str
    document: ArchiefDocument


@dataclass(frozen=True)
class FacetWaarde:
    administratie_id: uuid.UUID
    naam: str
    aantal: int


@dataclass(frozen=True)
class KantoorbreedPagina:
    documenten: list[KantoorbreedRij]
    totaal: int
    pagina: int
    per_pagina: int
    van: date
    tot: date
    # "N documenten over M administraties" — M telt alleen administraties mét rijen in de selectie.
    administraties_met_documenten: int
    # Facetwaarden over de hele scope (binnen venster + zoekterm), ongeacht het gezette facet —
    # zo blijft de kiezer bruikbaar om van administratie te wisselen.
    facet: list[FacetWaarde]


def _waarde(rij: KantoorbreedRij, kolom: str) -> object | None:
    """Primaire sorteersleutel per kolom — spiegel van `service._archief_order_by`."""
    d = rij.document
    if kolom == "leverancier":
        return d.leverancier.lower() if d.leverancier is not None else None
    if kolom == "boekstuk":
        return d.rlz_boekstuknummer.lower() if d.rlz_boekstuknummer is not None else None
    if kolom == "factuurdatum":
        return d.factuurdatum
    if kolom == "bedrag":
        return d.totaalbedrag
    if kolom == "geboekt_op":
        return d.geboekt_op
    if kolom == "administratie":
        return rij.administratie_naam.lower()
    raise ArchiefFout(f"Onbekende sorteerkolom: {kolom!r}.")


def _secundair(rij: KantoorbreedRij) -> tuple:
    g = rij.document.geboekt_op
    return (g is None, -g.timestamp() if g is not None else 0.0, str(rij.document.document_id))


def sorteer(rijen: list[KantoorbreedRij], sortering: ArchiefSortering) -> list[KantoorbreedRij]:
    """Dezelfde totale orde als de SQL-sortering per administratie: primair de kolom (ontbrekend
    achteraan, ongeacht richting), secundair boekmoment nieuwste eerst, tertiair document-id.
    Python's sort is stabiel (óók met reverse=True), dus secundair-eerst + primair-daarna volstaat."""
    basis = sorted(rijen, key=_secundair)
    met = [r for r in basis if _waarde(r, sortering.kolom) is not None]
    zonder = [r for r in basis if _waarde(r, sortering.kolom) is None]
    met.sort(key=lambda r: _waarde(r, sortering.kolom), reverse=sortering.richting == "desc")  # type: ignore[arg-type, return-value]
    return met + zonder


def blader(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    pagina: int = 1,
    per_pagina: int = service.ARCHIEF_PER_PAGINA_DEFAULT,
    administratie_id: uuid.UUID | None = None,
    van: date | None = None,
    tot: date | None = None,
    q: str = "",
    sortering: ArchiefSortering | None = None,
) -> KantoorbreedPagina:
    if pagina < 1:
        raise ArchiefFout("Pagina begint bij 1.")
    if not 1 <= per_pagina <= service.ARCHIEF_PER_PAGINA_MAX:
        raise ArchiefFout(f"per_pagina moet tussen 1 en {service.ARCHIEF_PER_PAGINA_MAX} liggen.")
    filt = service.maak_archief_filter(van=van, tot=tot, q=q)
    sortering = sortering or service.STANDAARD_ARCHIEF_SORTERING

    administraties = auth_service.mijn_administraties(actor_id=actor_id, rol=rol)
    # Facet = filter, nooit poort: een administratie buiten de scope levert simpelweg niets.
    gekozen = [a for a in administraties if administratie_id is None or a.id == administratie_id]

    tellingen: dict[uuid.UUID, int] = {}
    facet: list[FacetWaarde] = []
    for a in administraties:
        with scoped_session(a.id, actor_id=actor_id) as session:
            n = service.archief_tel(session, administratie_id=a.id, filt=filt)
        tellingen[a.id] = n
        if n:
            facet.append(FacetWaarde(administratie_id=a.id, naam=a.naam, aantal=n))
    facet.sort(key=lambda f: f.naam.lower())

    totaal = sum(tellingen[a.id] for a in gekozen)
    offset = (pagina - 1) * per_pagina
    rijen: list[KantoorbreedRij]
    if len(gekozen) == 1:
        a = gekozen[0]
        with scoped_session(a.id, actor_id=actor_id) as session:
            docs = service.archief_rijen(
                session, administratie_id=a.id, filt=filt, sortering=sortering, limit=per_pagina, offset=offset
            )
        rijen = [KantoorbreedRij(administratie_id=a.id, administratie_naam=a.naam, document=d) for d in docs]
    else:
        diepte = pagina * per_pagina
        if diepte > MAX_DIEPTE:
            raise ArchiefFout(
                f"Zo diep bladeren over meerdere administraties kan niet (max {MAX_DIEPTE} rijen) — "
                "kies een administratie of verklein het datumvenster."
            )
        alles: list[KantoorbreedRij] = []
        for a in gekozen:
            if not tellingen[a.id]:
                continue
            with scoped_session(a.id, actor_id=actor_id) as session:
                docs = service.archief_rijen(
                    session, administratie_id=a.id, filt=filt, sortering=sortering, limit=diepte, offset=0
                )
            alles.extend(KantoorbreedRij(administratie_id=a.id, administratie_naam=a.naam, document=d) for d in docs)
        rijen = sorteer(alles, sortering)[offset:diepte]

    return KantoorbreedPagina(
        documenten=rijen,
        totaal=totaal,
        pagina=pagina,
        per_pagina=per_pagina,
        van=filt.van,
        tot=filt.tot,
        administraties_met_documenten=sum(1 for a in gekozen if tellingen[a.id]),
        facet=facet,
    )


# ----------------------------------------------------------------------------- router

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): kantoor-console, externe app-rollen 403.
router = APIRouter(tags=["archief"], dependencies=[Depends(vereis_kantoorrol)])


class ArchiefKantoorbreedDocumentDto(ArchiefDocumentDto):
    administratie_id: uuid.UUID
    administratie_naam: str


class ArchiefFacetDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class ArchiefKantoorbreedResponse(BaseModel):
    documenten: list[ArchiefKantoorbreedDocumentDto]
    totaal: int
    pagina: int
    per_pagina: int
    van: date
    tot: date
    administraties_met_documenten: int
    facet: list[ArchiefFacetDto]


def _dto(rij: KantoorbreedRij) -> ArchiefKantoorbreedDocumentDto:
    d = rij.document
    return ArchiefKantoorbreedDocumentDto(
        administratie_id=rij.administratie_id,
        administratie_naam=rij.administratie_naam,
        document_id=d.document_id,
        soort=d.soort,
        bestandsnaam=d.bestandsnaam,
        leverancier=d.leverancier,
        referentie=d.referentie,
        rlz_boekstuknummer=d.rlz_boekstuknummer,
        totaalbedrag=d.totaalbedrag,
        factuurdatum=d.factuurdatum,
        geboekt_op=d.geboekt_op,
        automatisch_geboekt=d.automatisch_geboekt,
        tegengeboekt=d.tegengeboekt,
    )


@router.get("/archief", response_model=ArchiefKantoorbreedResponse)
def archief_kantoorbreed(
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(service.ARCHIEF_PER_PAGINA_DEFAULT, ge=1, le=service.ARCHIEF_PER_PAGINA_MAX),
    administratie_id: uuid.UUID | None = Query(None, description="Facet-filter (leeg = alle administraties in scope)"),
    van: date | None = Query(None),
    tot: date | None = Query(None),
    q: str = Query(""),
    sort: str | None = Query(None, description="<kolom>:<asc|desc>; leeg = boekmoment nieuwste eerst"),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> ArchiefKantoorbreedResponse:
    """Kantoorbreed geboekt archief over álle administraties in de scope van de actor — gepagineerd,
    datumvenster (default 12 maanden op boekmoment), zoekterm, sorteerbare kolommen
    leverancier/factuurdatum/bedrag/boekstuk/administratie/geboekt_op; administratie = facet."""
    try:
        resultaat = blader(
            actor_id=actor.id,
            rol=actor.rol,
            pagina=pagina,
            per_pagina=per_pagina,
            administratie_id=administratie_id,
            van=van,
            tot=tot,
            q=q,
            sortering=service.parse_archief_sortering(sort),
        )
    except ArchiefFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return ArchiefKantoorbreedResponse(
        documenten=[_dto(r) for r in resultaat.documenten],
        totaal=resultaat.totaal,
        pagina=resultaat.pagina,
        per_pagina=resultaat.per_pagina,
        van=resultaat.van,
        tot=resultaat.tot,
        administraties_met_documenten=resultaat.administraties_met_documenten,
        facet=[ArchiefFacetDto(**vars(f)) for f in resultaat.facet],
    )
