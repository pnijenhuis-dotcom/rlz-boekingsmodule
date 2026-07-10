import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.beheer.router import router as beheer_router
from app.config import settings
from app.credentialstore.router import router as credentialstore_router
from app.db import session as db_session
from app.db.migratie_guard import controleer_migratie_versie
from app.documenten import service as documenten_service
from app.documenten.router import router as documenten_router
from app.sync.router import router as sync_router

logger = logging.getLogger(__name__)

# Nederlandse omschrijving per (methode, route-sjabloon) voor de melding van de globale
# exception-handler hieronder — alleen voor de gevoelige schrijfacties waarbij "er ging iets mis
# bij ..." verwarrend kaal zou zijn zonder context; alle overige routes vallen terug op de
# generieke omschrijving.
_ACTIE_PER_ROUTE: dict[tuple[str, str], str] = {
    (
        "PUT",
        "/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
    ): "het opslaan van het boekvoorstel",
    (
        "POST",
        "/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks",
    ): "het uitvoeren van de checks",
    ("POST", "/administraties/{administratie_id}/documenten/{document_id}/boeken"): "het boeken van de factuur",
    ("POST", "/administraties/{administratie_id}/documenten"): "het uploaden van het document",
}


def _actie_omschrijving(request: Request) -> str:
    route = request.scope.get("route")
    pad = getattr(route, "path", None)
    if pad is not None:
        omschrijving = _ACTIE_PER_ROUTE.get((request.method, pad))
        if omschrijving is not None:
            return omschrijving
    return "het verwerken van je aanvraag"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Migratie-guard (CLAUDE.md-taak "geen raadsel-500 door een gemiste migratie meer"): stopt
    de startup hard (fail-fast, default) of logt alleen een waarschuwing (settings.migratie_
    guard_fail_fast=False) als de database niet op de laatste migratie uit de repo staat. Draait
    vóór de eerste request wordt geaccepteerd — uvicorn start dan niet op bij een fail-fast-fout.
    Verwijst naar `db_session.engine` (module-attribuut, niet een losse import) zodat dit ook de
    testdatabase-engine ziet als tests/conftest.py::_service_layer_gebruikt_testdatabase 'm heeft
    vervangen — zelfde reden als waarom scoped_session() dat ook nooit als losse import doet.

    Daarna het async-extractie-vangnet (2026-07-10): documenten die door een proces-herstart in
    extractie_wachtrij/extractie_bezig achterbleven (de in-process wachtrij overleeft een
    herstart niet) worden opnieuw ingepland — "niets verdwijnt stil"."""
    controleer_migratie_versie(db_session.engine, fail_fast=settings.migratie_guard_fail_fast)
    documenten_service.herstel_achtergebleven_extracties()
    yield


app = FastAPI(title="RLZ Boekingsmodule", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(documenten_router)
app.include_router(sync_router)
app.include_router(credentialstore_router)
app.include_router(beheer_router)


@app.exception_handler(Exception)
async def onverwachte_fout_handler(request: Request, exc: Exception) -> JSONResponse:
    """Vangnet tegen kale "Internal Server Error"-responses (CLAUDE.md-principe "niets verdwijnt
    stil"): elke onverwachte fout die geen eigen HTTPException/handler heeft, komt hier terecht.
    Volledige traceback + correlatie-id naar de server-log, aan de client alleen een nette
    Nederlandse melding met die correlatie-id — nooit de interne foutdetails. FastAPI's eigen
    HTTPException-handler heeft voorrang op deze (Starlette matcht op de meest specifieke
    geregistreerde exception-klasse), dus de bestaande domeinfout-afhandeling in de routers
    blijft ongewijzigd werken."""
    correlatie_id = uuid.uuid4()
    logger.exception("Onverwachte fout bij %s %s (correlatie-id %s)", request.method, request.url.path, correlatie_id)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Er ging iets mis bij {_actie_omschrijving(request)} — code {correlatie_id}."},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
