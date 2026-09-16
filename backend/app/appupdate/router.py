"""Routes OTA (Peter 16-09): publiek manifest + bundel-download (de web-laag is publieke code, geen secrets), rollback-
melding vanuit de schil, Beheerder-blok App-updates (Instellingen › Boeken)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.appupdate import service
from app.auth.deps import CurrentGebruiker, get_current_gebruiker, require_beheerder
from app.config import settings

router = APIRouter(tags=["app-updates"])


class RollbackMelding(BaseModel):
    bundel_id: str = Field(min_length=1, max_length=120)
    reden: str | None = Field(default=None, max_length=200)
    app_versie: str | None = Field(default=None, max_length=40)


class InstellingDto(BaseModel):
    percentage: int = Field(ge=0, le=100)
    uitgeschakeld: bool
    env_uitgeschakeld: bool = False
    min_runtime_versie: str = ""


class InstellingWijzigDto(BaseModel):
    percentage: int | None = Field(default=None, ge=0, le=100)
    uitgeschakeld: bool | None = None


class BundelDto(BaseModel):
    bundel_id: str
    runtime: str
    platform: str
    sha256: str
    bytes: int
    verplicht: bool
    actief: bool
    aangemaakt_op: str


class BundelActiefDto(BaseModel):
    actief: bool


@router.get("/app/update-manifest")
def update_manifest(
    request: Request,
    runtime: str = Query(min_length=1, max_length=20),
    platform: str = Query(min_length=2, max_length=10),
    huidig: str | None = Query(default=None, max_length=120),
    toestel: str | None = Query(default=None, max_length=80),
) -> dict:
    basis = str(request.base_url).rstrip("/")
    return service.manifest(runtime=runtime, platform=platform, huidig=huidig, toestel=toestel, basis_url=basis).als_dict()


@router.get("/app/bundels/{bundel_id}.zip", include_in_schema=False)
def bundel_download(bundel_id: str) -> Response:
    try:
        rij, inhoud = service.bundel_bytes(bundel_id)
    except (service.AppUpdateFout, FileNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type="application/zip",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Bundel-Sha256": rij.sha256},
    )


@router.post("/app/update-melding", status_code=status.HTTP_204_NO_CONTENT)
def update_melding(invoer: RollbackMelding, actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> Response:
    service.meld_rollback(apparaat_id=actor.apparaat_id, bundel_id=invoer.bundel_id, reden=invoer.reden, app_versie=invoer.app_versie)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _instelling_dto() -> InstellingDto:
    rij = service.haal_instelling_op()
    return InstellingDto(
        percentage=rij.percentage, uitgeschakeld=rij.uitgeschakeld, env_uitgeschakeld=settings.ota_uitgeschakeld,
        min_runtime_versie=settings.app_min_runtime_versie,
    )


@router.get("/instellingen/app-updates", response_model=InstellingDto)
def instelling_ophalen(actor: CurrentGebruiker = Depends(require_beheerder)) -> InstellingDto:
    try:
        return _instelling_dto()
    except service.AppUpdateFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/instellingen/app-updates", response_model=InstellingDto)
def instelling_zetten(invoer: InstellingWijzigDto, actor: CurrentGebruiker = Depends(require_beheerder)) -> InstellingDto:
    try:
        service.zet_instelling(actor_id=actor.id, percentage=invoer.percentage, uitgeschakeld=invoer.uitgeschakeld)
        return _instelling_dto()
    except service.AppUpdateFout as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/instellingen/app-updates/bundels", response_model=list[BundelDto])
def bundels_lijst(actor: CurrentGebruiker = Depends(require_beheerder)) -> list[BundelDto]:
    return [
        BundelDto(
            bundel_id=b.bundel_id, runtime=b.runtime, platform=b.platform, sha256=b.sha256, bytes=b.bytes,
            verplicht=b.verplicht, actief=b.actief, aangemaakt_op=b.aangemaakt_op.isoformat(),
        )
        for b in service.bundels()
    ]


@router.put("/instellingen/app-updates/bundels/{bundel_id}", response_model=BundelDto)
def bundel_actief_zetten(bundel_id: str, invoer: BundelActiefDto, actor: CurrentGebruiker = Depends(require_beheerder)) -> BundelDto:
    try:
        b = service.zet_bundel_actief(bundel_id=bundel_id, actief=invoer.actief, actor_id=actor.id)
    except service.AppUpdateFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BundelDto(
        bundel_id=b.bundel_id, runtime=b.runtime, platform=b.platform, sha256=b.sha256, bytes=b.bytes,
        verplicht=b.verplicht, actief=b.actief, aangemaakt_op=b.aangemaakt_op.isoformat(),
    )


@router.get("/instellingen/app-updates/toestellen")
def toestellen_lijst(actor: CurrentGebruiker = Depends(require_beheerder)) -> list[dict]:
    return service.laatste_toestellen(20)


__all__ = ["router", "uuid"]
