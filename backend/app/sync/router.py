from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope
from app.rlz.client import RlzApiError
from app.rlz.credentials import GeenRlzCredentials
from app.sync import schemas, service

router = APIRouter(tags=["sync"])


def _sync_trigger(
    sync_fn: Callable[..., service.SyncTelling], *, administratie_id: uuid.UUID
) -> schemas.SyncTellingResponse:
    """Gedeelde foutafhandeling voor alle vier de on-demand sync-triggers (koppelcontract §2c) —
    lezen blijft altijd via de gedeelde tabel, nooit via dit endpoint (§2c: "lezen nooit via
    endpoint"), dit is uitsluitend de ververs-knop."""
    try:
        telling = sync_fn(administratie_id=administratie_id)
    except service.SyncFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RlzApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.SyncTellingResponse(
        aangemaakt=telling.aangemaakt, bijgewerkt=telling.bijgewerkt, verdwenen=telling.verdwenen
    )


@router.post(
    "/administraties/{administratie_id}/sync/ledgers",
    response_model=schemas.SyncTellingResponse,
)
def sync_ledgers_trigger(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SyncTellingResponse:
    """On-demand trigger voor de ververs-knop. Gebruikers-auth + administratie-scope (dezelfde
    dependency als document-upload); het service-to-service platform-JWT voor de vastgoed-kant
    komt bij de Cloud-uitrol."""
    return _sync_trigger(service.sync_ledgers, administratie_id=administratie_id)


@router.post(
    "/administraties/{administratie_id}/sync/taxrates",
    response_model=schemas.SyncTellingResponse,
)
def sync_taxrates_trigger(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SyncTellingResponse:
    """Zelfde on-demand trigger als Ledgers (zie sync_ledgers_trigger hierboven), voor de
    btw-codes-combobox in het controlescherm (design-pass taak 3)."""
    return _sync_trigger(service.sync_taxrates, administratie_id=administratie_id)


@router.post(
    "/administraties/{administratie_id}/sync/vendors",
    response_model=schemas.SyncTellingResponse,
)
def sync_vendors_trigger(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SyncTellingResponse:
    """Zelfde on-demand trigger als Ledgers, voor de crediteuren-combobox."""
    return _sync_trigger(service.sync_vendors, administratie_id=administratie_id)


@router.post(
    "/administraties/{administratie_id}/sync/projects",
    response_model=schemas.SyncTellingResponse,
)
def sync_projects_trigger(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SyncTellingResponse:
    """Zelfde on-demand trigger als Ledgers, voor de project-combobox."""
    return _sync_trigger(service.sync_projects, administratie_id=administratie_id)


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
        btw_codes=[schemas.TaxrateOptieResponse(id=t.id, naam=t.naam, percentage=t.percentage) for t in codes]
    )


@router.post(
    "/administraties/{administratie_id}/crediteuren",
    response_model=schemas.VendorOptieResponse,
    status_code=status.HTTP_201_CREATED,
)
def crediteur_aanmaken(
    administratie_id: uuid.UUID,
    invoer: schemas.NieuweCrediteurInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VendorOptieResponse:
    """Nieuwe crediteur aanmaken in RLZ vanaf het controlescherm (fix 2, 2026-07-10) — de
    AI-gelezen leverancier die niet in de cache staat, met de geëxtraheerde naam voorgevuld.
    Schrijfactie in de klantboekhouding: idempotent client-GUID + duplicaatcheck + dezelfde
    failsafe-poort als boeken (zie service.maak_crediteur_aan)."""
    try:
        crediteur = service.maak_crediteur_aan(administratie_id=administratie_id, actor_id=actor.id, naam=invoer.naam)
    except service.CrediteurBestaatAl as exc:
        # De bestaande vendor_id reist mee zodat de frontend de bestaande crediteur direct kan
        # selecteren — een kale foutmelding zou de controleur alsnog laten zoeken in de combobox.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "vendor_id": str(exc.vendor_id)},
        ) from exc
    except service.CrediteurAanmakenUitgeschakeld as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except service.SyncFout as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RlzApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.VendorOptieResponse(id=crediteur.id, naam=crediteur.naam)


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
