import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.beheer.router import router as beheer_router
from app.config import settings
from app.credentialstore.router import router as credentialstore_router
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


app = FastAPI(title="RLZ Boekingsmodule")
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
