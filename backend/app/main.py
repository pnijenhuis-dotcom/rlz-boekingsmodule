from fastapi import FastAPI

app = FastAPI(title="RLZ Boekingsmodule")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
