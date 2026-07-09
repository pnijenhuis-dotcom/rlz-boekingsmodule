from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials
from app.sync import schemas, service

router = APIRouter(tags=["sync"])


@router.post(
    "/administraties/{administratie_id}/sync/ledgers",
    response_model=schemas.SyncTellingResponse,
)
def sync_ledgers_trigger(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SyncTellingResponse:
    """On-demand trigger (koppelcontract §2c) voor de ververs-knop. Nu met gebruikers-auth +
    administratie-scope (dezelfde dependency als document-upload); het service-to-service
    platform-JWT voor de vastgoed-kant komt bij de Cloud-uitrol — lezen blijft altijd via de
    gedeelde tabel, nooit via dit endpoint (§2c: "lezen nooit via endpoint")."""
    try:
        telling = service.sync_ledgers(administratie_id=administratie_id)
    except service.SyncFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RlzApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.SyncTellingResponse(
        aangemaakt=telling.aangemaakt, bijgewerkt=telling.bijgewerkt, verdwenen=telling.verdwenen
    )


@router.get("/administraties/{administratie_id}/grootboek", response_model=schemas.GrootboekLijstResponse)
def grootboek_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.GrootboekLijstResponse:
    """Voedt de GB-combobox in het controlescherm (CLAUDE.md-taak 2.1) — uit de gedeelde
    `platform.grootboekrekening`-sync, nooit rechtstreeks van RLZ (lezen gaat altijd via de
    sync-cache, koppelcontract §2c)."""
    rekeningen = service.lijst_grootboek(administratie_id=administratie_id)
    return schemas.GrootboekLijstResponse(
        rekeningen=[
            schemas.GrootboekOptieResponse(ledger_id=r.ledger_id, code=r.code, naam=r.naam, soort=r.soort)
            for r in rekeningen
        ]
    )


@router.get("/administraties/{administratie_id}/btw-codes", response_model=schemas.TaxrateLijstResponse)
def taxrate_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.TaxrateLijstResponse:
    codes = service.lijst_taxrates(administratie_id=administratie_id)
    return schemas.TaxrateLijstResponse(
        btw_codes=[schemas.TaxrateOptieResponse(id=t.id, naam=t.naam) for t in codes]
    )


@router.get("/administraties/{administratie_id}/crediteuren", response_model=schemas.VendorLijstResponse)
def vendor_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.VendorLijstResponse:
    vendors = service.lijst_vendors(administratie_id=administratie_id)
    return schemas.VendorLijstResponse(
        crediteuren=[schemas.VendorOptieResponse(id=v.id, naam=v.naam) for v in vendors]
    )


@router.get("/administraties/{administratie_id}/projecten", response_model=schemas.ProjectLijstResponse)
def project_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ProjectLijstResponse:
    projecten = service.lijst_projects(administratie_id=administratie_id)
    return schemas.ProjectLijstResponse(
        projecten=[schemas.ProjectOptieResponse(id=p.id, naam=p.naam) for p in projecten]
    )
