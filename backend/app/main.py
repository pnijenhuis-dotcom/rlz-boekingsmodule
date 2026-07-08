from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.documenten.router import router as documenten_router

app = FastAPI(title="RLZ Boekingsmodule")
app.include_router(auth_router)
app.include_router(documenten_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
