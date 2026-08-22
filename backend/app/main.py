import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.accordering.router import router as accordering_router
from app.auth.privacy_pagina import router as privacy_pagina_router
from app.auth.router import router as auth_router
from app.auth.wellknown import router as wellknown_router
from app.bank.router import router as bank_router
from app.beheer.router import router as beheer_router
from app.berichten.router import router as berichten_router
from app.config import settings
from app.credentialstore.router import router as credentialstore_router
from app.db import session as db_session
from app.db.migratie_guard import controleer_migratie_versie
from app.documenten import service as documenten_service
from app.documenten import webhook_afleveraar
from app.documenten.router import bestand_router as documenten_bestand_router
from app.documenten.router import router as documenten_router
from app.doorbelasting.router import router as doorbelasting_router
from app.geheugen.router import router as geheugen_router
from app.intake.router import router as intake_router
from app.omzet.router import router as omzet_router
from app.projecten.kantoor_router import router as projecten_kantoor_router
from app.projecten.router import router as projecten_koppelvlak_router
from app.static_frontend import activeer_frontend_serving
from app.sync.router import router as sync_router
from app.uren.router import router as uren_router
from app.verkoop.router import router as verkoop_router
from app.waarborg.router import router as waarborg_router
from app.zoeken.router import router as zoeken_router

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
    (
        "PUT",
        "/doorbelasting/{administratie_id}/runs/{run_id}/verdeling",
    ): "het opslaan van de verdeling",
    ("POST", "/doorbelasting/{administratie_id}/runs/{run_id}/boeken"): "het doorbelasten",
}


def _actie_omschrijving(request: Request) -> str:
    route = request.scope.get("route")
    pad = getattr(route, "path", None)
    if pad is not None:
        omschrijving = _ACTIE_PER_ROUTE.get((request.method, pad))
        if omschrijving is not None:
            return omschrijving
    return "het verwerken van je aanvraag"


def _bouw_onverwachte_fout_response(request: Request) -> JSONResponse:
    """Nette Nederlandse 500 + correlatie-id; volledige traceback uitsluitend naar de server-log
    (logger.exception leest sys.exc_info(), dus aanroepen vanuit een except-blok)."""
    correlatie_id = uuid.uuid4()
    logger.exception("Onverwachte fout bij %s %s (correlatie-id %s)", request.method, request.url.path, correlatie_id)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Er ging iets mis bij {_actie_omschrijving(request)} — code {correlatie_id}."},
    )


class OnverwachteFoutVangnet:
    """Binnenste vangnet-middleware (adoptie uit Platform/registers/verbeteringen.md, vastgoed
    2026-07-11): zet elke onafgehandelde exception om in de nette JSON-500 — BINNEN de
    CORS-middleware, zodat ook dat antwoord CORS-headers draagt. Zonder dit vangnet belandt een
    onverwachte fout pas in Starlette's ServerErrorMiddleware/de globale exception-handler, en
    die zitten BUITEN de CORS-laag: de browser ziet dan een kaal "Failed to fetch" in plaats van
    de echte foutmelding. Puur ASGI (geen BaseHTTPMiddleware) — geen streaming-/achtergrondtaak-
    bijwerkingen. Is de response al gestart, dan valt er niets meer te repareren en her-raisen we."""

    def __init__(self, app) -> None:  # noqa: ANN001 — ASGI-app, Starlette geeft hier geen publiek type voor
        self._app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001 — ASGI-signatuur
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        response_gestart = False

        async def bewaakte_send(message) -> None:  # noqa: ANN001 — ASGI-message
            nonlocal response_gestart
            if message["type"] == "http.response.start":
                response_gestart = True
            await send(message)

        try:
            await self._app(scope, receive, bewaakte_send)
        except Exception:
            if response_gestart:
                raise
            response = _bouw_onverwachte_fout_response(Request(scope))
            await response(scope, receive, send)


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
    herstart niet) worden opnieuw ingepland — "niets verdwijnt stil".

    Tot slot de in-process webhook-afleveraar (2026-08-02): start alleen als er een doel-URL
    geconfigureerd is (zonder URL valt er niets af te leveren — de failsafe laat rijen dan
    openstaand); de toggle (platform.webhook_instelling, default UIT) wordt per iteratie
    gecheckt. Productie draait dezelfde verwerk-functie als Cloud Scheduler-job via de CLI."""
    controleer_migratie_versie(db_session.engine, fail_fast=settings.migratie_guard_fail_fast)
    documenten_service.herstel_achtergebleven_extracties()
    webhook_afleveraar.start_in_process_afleveraar()
    yield
    webhook_afleveraar.stop_in_process_afleveraar()


app = FastAPI(title="RLZ Boekingsmodule", lifespan=_lifespan)
# Volgorde is betekenis (Starlette: láátst toegevoegde middleware = buitenste laag): het
# fout-vangnet eerst toevoegen en CORS daarna, zodat CORS de buitenste laag is en élk antwoord
# — ook de JSON-500 uit het vangnet — CORS-headers draagt.
app.add_middleware(OnverwachteFoutVangnet)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    # Expliciete methodenlijst i.p.v. "*" (Vastly-regressie 2026-07-14, geport 2026-08-07):
    # een wildcard verbergt dat een methode ontbreekt tot een preflight in de browser faalt —
    # met een "Failed to fetch" zonder serverlog-regel als enige symptoom. De preflight-
    # regressietest (tests/unit/test_cors_foutantwoorden.py) toetst élke methode hieronder.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(wellknown_router)
app.include_router(privacy_pagina_router)
app.include_router(accordering_router)
app.include_router(berichten_router)
app.include_router(bank_router)
app.include_router(documenten_router)
app.include_router(documenten_bestand_router)
app.include_router(sync_router)
app.include_router(geheugen_router)
app.include_router(omzet_router)
app.include_router(verkoop_router)
app.include_router(waarborg_router)
app.include_router(projecten_koppelvlak_router)
app.include_router(projecten_kantoor_router)
app.include_router(doorbelasting_router)
app.include_router(zoeken_router)
app.include_router(intake_router)
app.include_router(uren_router)
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
    blijft ongewijzigd werken. In de praktijk vangt OnverwachteFoutVangnet (binnen de CORS-laag)
    de fout al eerder af — dit blijft staan als laatste redmiddel voor wat daar ooit langs zou
    glippen."""
    return _bouw_onverwachte_fout_response(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Same-origin frontend-serving (F2, beslispunt 4) — als allerlaatste, ná álle routes: de
# SPA-fallback is een catch-all en mag nooit een echte API-route voor de voeten lopen.
# Doet niets zolang frontend_dist_map leeg is (dev: Vite-dev-server + proxy).
activeer_frontend_serving(app)
