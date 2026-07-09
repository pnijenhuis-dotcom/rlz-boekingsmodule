from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.beheer.router import router as beheer_router
from app.config import settings
from app.credentialstore.router import router as credentialstore_router
from app.documenten.router import router as documenten_router
from app.sync.router import router as sync_router

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
