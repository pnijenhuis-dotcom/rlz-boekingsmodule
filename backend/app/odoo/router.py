"""Odoo-koppeling-endpoints (Beheerder-only, kantoor-console — vereis_kantoorrol router-breed,
rollen-gate-fix 2026-08-21). Spiegel van de RLZ-wizard-endpoints onder /instellingen/administraties."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_kantoorrol
from app.odoo import schemas, service
from app.odoo.credentials import GeenOdooKoppeling

router = APIRouter(tags=["odoo"], dependencies=[Depends(vereis_kantoorrol)])


def _koppel_fout(exc: Exception) -> HTTPException:
    if isinstance(exc, service.OdooKoppelFout):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"bericht": str(exc), "rapport": exc.rapport},
        )
    if isinstance(exc, GeenOdooKoppeling):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/instellingen/odoo/verbinding-testen", response_model=schemas.OdooVerbindingTestDto)
def odoo_verbinding_testen(
    invoer: schemas.OdooGegevensDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooVerbindingTestDto:
    """Stap a: sleutel proberen → companies (mét 'al gekoppeld'). Niets opgeslagen."""
    try:
        gevonden = service.test_verbinding(odoo_url=invoer.odoo_url, api_key=invoer.api_key)
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooVerbindingTestDto(
        companies=[
            schemas.GevondenCompanyDto(company_id=g.company_id, naam=g.naam, al_gekoppeld=g.al_gekoppeld)
            for g in gevonden
        ]
    )


@router.post(
    "/instellingen/odoo/koppelen", response_model=schemas.OdooGekoppeldDto, status_code=status.HTTP_201_CREATED
)
def odoo_koppelen(
    invoer: schemas.OdooKoppelenDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooGekoppeldDto:
    """Stap b+c+d: probe verplicht groen per company (anders 422 mét rapport, niets opgeslagen) →
    administratie + koppeling + audit → eerste stamgegevens-sync mét zichtbare run."""
    try:
        resultaten = service.koppel_administraties(
            actor_id=actor.id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            api_gebruiker=invoer.api_gebruiker,
            company_ids=invoer.company_ids,
            namen={int(k): v for k, v in invoer.namen.items() if v.strip()},
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooGekoppeldDto(
        administraties=[
            schemas.GekoppeldeAdministratieDto(
                id=r.id, naam=r.naam, company_id=r.company_id, probe=r.probe, sync_run_id=r.sync_run_id, sync=r.sync
            )
            for r in resultaten
        ]
    )


@router.get("/administraties/{administratie_id}/odoo", response_model=schemas.OdooStandDto)
def odoo_stand(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooStandDto:
    stand = service.koppelstand([administratie_id]).get(administratie_id)
    if stand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Geen Odoo-koppeling voor deze administratie")
    return schemas.OdooStandDto(**stand.__dict__)


@router.post(
    "/administraties/{administratie_id}/odoo/overstap",
    response_model=schemas.GekoppeldeAdministratieDto,
    status_code=status.HTTP_201_CREATED,
)
def odoo_overstap(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooOverstapDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.GekoppeldeAdministratieDto:
    """Blok E, ingang B (volledige backend): een bestaande RLZ-administratie stapt over op Odoo — probe verplicht
    groen (anders 422 mét rapport, niets opgeslagen) → backend 'odoo' + sentinel + koppeling mét overgangsdatum +
    audit in één transactie → eerste stamgegevens-sync mét zichtbare run."""
    try:
        r = service.koppel_overstap(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            company_id=invoer.company_id,
            overgangsdatum=invoer.overgangsdatum,
            api_gebruiker=invoer.api_gebruiker,
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.GekoppeldeAdministratieDto(
        id=r.id, naam=r.naam, company_id=r.company_id, probe=r.probe, sync_run_id=r.sync_run_id, sync=r.sync
    )


@router.put("/administraties/{administratie_id}/odoo/overgangsdatum", response_model=schemas.OdooStandDto)
def odoo_overgangsdatum(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooOvergangsdatumDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooStandDto:
    """De overgangsdatum van een schrijvende Odoo-koppeling zetten/verschuiven (audit oud→nieuw; alleen-lezen = 422)."""
    try:
        stand = service.wijzig_overgangsdatum(
            actor_id=actor.id, administratie_id=administratie_id, overgangsdatum=invoer.overgangsdatum
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooStandDto(**stand.__dict__)


@router.put("/administraties/{administratie_id}/odoo", response_model=schemas.OdooProbeDto)
def odoo_wijzigen(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooWijzigDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooProbeDto:
    """Odoo-gegevens wijzigen / sleutel roteren / herprobe — probe-gated (groen vereist vóór opslaan)."""
    try:
        p = service.wijzig_koppeling(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            api_gebruiker=invoer.api_gebruiker,
        )
    except (service.OdooKoppelFout, GeenOdooKoppeling) as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooProbeDto(
        groen=p.groen, rapport=p.rapport, company_naam=p.company_naam, versie=p.versie, lock_dates=p.lock_dates
    )


@router.post(
    "/administraties/{administratie_id}/odoo/leesbron",
    response_model=schemas.OdooProbeDto,
    status_code=status.HTTP_201_CREATED,
)
def odoo_leesbron_koppelen(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooLeesbronKoppelenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooProbeDto:
    """Blok D: Odoo als LEESBRON voor een RLZ-administratie (voorraad-uitstroom vanaf de knip) — leesprobe
    verplicht groen, koppeling is hard alleen-lezen (nooit een write op die company)."""
    try:
        p = service.koppel_leesbron(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            company_id=invoer.company_id,
            voorraad_knip_datum=invoer.voorraad_knip_datum,
            api_gebruiker=invoer.api_gebruiker,
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooProbeDto(groen=p.groen, rapport=p.rapport, company_naam=p.company_naam, versie=p.versie)


@router.put("/administraties/{administratie_id}/odoo/leesbron", response_model=schemas.OdooStandDto)
def odoo_leesbron_knip(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooLeesbronKnipDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooStandDto:
    """De voorraad-knip zetten/verschuiven/wissen (audit oud→nieuw)."""
    try:
        stand = service.wijzig_leesbron(
            actor_id=actor.id, administratie_id=administratie_id, voorraad_knip_datum=invoer.voorraad_knip_datum
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooStandDto(**stand.__dict__)


@router.post("/administraties/{administratie_id}/odoo/sync", response_model=schemas.OdooSyncResultaatDto)
def odoo_sync_nu(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooSyncResultaatDto:
    """Stamgegevens opnieuw syncen (zichtbaar als run, zelfde model als de eerste sync)."""
    try:
        run_id, onderdelen = service.eerste_sync(administratie_id=administratie_id, actor_id=actor.id)
    except GeenOdooKoppeling as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooSyncResultaatDto(run_id=run_id, onderdelen=onderdelen)


@router.post("/administraties/{administratie_id}/odoo/producten-brug", response_model=schemas.OdooProductBrugDto)
def odoo_producten_brug(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooProductBrugDto:
    """Materiaalcatalogus → product.product (blok B): lookup eerst, idempotente aanmaak, uitkomst per product."""
    from app.odoo import producten

    try:
        uitkomst = producten.leg_brug(administratie_id=administratie_id, actor_id=actor.id)
    except GeenOdooKoppeling as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooProductBrugDto(
        gevonden=uitkomst.gevonden, aangemaakt=uitkomst.aangemaakt, overgeslagen=list(uitkomst.overgeslagen)
    )
