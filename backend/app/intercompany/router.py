"""Beheerder-routes intercompany (blok A opdracht 16-09): relaties en RC-koppelingen lezen/corrigeren, afkortingen per
administratie, "Nu afleiden". Alle routes `require_beheerder` (router-breed) — de servicelaag toetst de rol nogmaals."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder
from app.intercompany import identiteit, rc_koppelingen, relaties, schemas

router = APIRouter(prefix="/intercompany", tags=["intercompany"], dependencies=[Depends(require_beheerder)])


def _vertaal(exc: relaties.IntercompanyFout) -> HTTPException:
    if isinstance(exc, relaties.GeenBeheerder):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(
        exc, (relaties.RelatieOnbekend, rc_koppelingen.RcKoppelingOnbekend)
    ) or "Onbekende administratie" in str(exc):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/relaties", response_model=schemas.IntercompanyRelatiesDto)
def lijst_relaties(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.IntercompanyRelatiesDto:
    return schemas.IntercompanyRelatiesDto(
        relaties=[schemas.IntercompanyRelatieDto(**asdict(r)) for r in relaties.relaties_voor_administratie(None)]
    )


@router.put("/relaties/{relatie_id}", response_model=schemas.IntercompanyRelatieDto)
def wijzig_relatie(
    relatie_id: uuid.UUID, invoer: schemas.StatusWijzigingDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.IntercompanyRelatieDto:
    try:
        info = relaties.zet_status(relatie_id, status=invoer.status, reden=invoer.reden, actor_id=actor.id)
    except relaties.IntercompanyFout as exc:
        raise _vertaal(exc) from exc
    return schemas.IntercompanyRelatieDto(**asdict(info))


@router.get("/rc-koppelingen", response_model=schemas.RcKoppelingenDto)
def lijst_rc_koppelingen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.RcKoppelingenDto:
    return schemas.RcKoppelingenDto(
        koppelingen=[schemas.RcKoppelingDto(**asdict(k)) for k in rc_koppelingen.alle_rc_koppelingen()],
        identiteiten=[_identiteit_dto(i) for i in rc_koppelingen.identiteiten_overzicht()],
    )


def _identiteit_dto(i: rc_koppelingen.IdentiteitInfo) -> schemas.IdentiteitDto:
    return schemas.IdentiteitDto(
        administratie_id=i.administratie_id,
        administratie_naam=i.administratie_naam,
        naam=i.naam,
        kvk=i.kvk,
        btw=i.btw,
        bron=i.bron,
        afkortingen=i.afkortingen,
        gelezen_op=i.gelezen_op,
    )


@router.put("/rc-koppelingen/{koppeling_id}", response_model=schemas.RcKoppelingDto)
def wijzig_rc_koppeling(
    koppeling_id: uuid.UUID, invoer: schemas.StatusWijzigingDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.RcKoppelingDto:
    try:
        info = rc_koppelingen.zet_rc_status(koppeling_id, status=invoer.status, reden=invoer.reden, actor_id=actor.id)
    except relaties.IntercompanyFout as exc:
        raise _vertaal(exc) from exc
    return schemas.RcKoppelingDto(**asdict(info))


@router.put("/identiteit/{administratie_id}/afkortingen", response_model=schemas.IdentiteitDto)
def wijzig_afkortingen(
    administratie_id: uuid.UUID, invoer: schemas.AfkortingenDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.IdentiteitDto:
    try:
        info = rc_koppelingen.zet_afkortingen(administratie_id, invoer.afkortingen, actor_id=actor.id)
    except relaties.IntercompanyFout as exc:
        raise _vertaal(exc) from exc
    return _identiteit_dto(info)


@router.post("/afleiden", response_model=schemas.AfleidenResultaatDto)
def afleiden_nu(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.AfleidenResultaatDto:
    """Synchroon: identiteiten lezen (één RLZ-/Odoo-call per administratie) → relaties → RC-koppelingen. Lees-only
    naar de bronnen; fouten per administratie komen als meldingen terug, nooit als 500."""
    uitkomsten = identiteit.sync_identiteiten()
    tellers = Counter(u.stand for u in uitkomsten)
    meldingen = [f"{u.administratie_naam}: {u.stand} — {u.melding}" for u in uitkomsten if u.melding]
    rel = relaties.leid_relaties_af()
    rc = rc_koppelingen.leid_rc_koppelingen_af()
    return schemas.AfleidenResultaatDto(
        identiteiten=dict(tellers), identiteit_meldingen=meldingen, relaties=rel.as_dict(), rc_koppelingen=rc.as_dict()
    )
