from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App-configuratie. Lokaal via .env, in Cloud Run via injected env vars (Secret Manager)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Migratie-/beheerconnectie (schema-owner, draait Alembic, mag DDL en GRANT/REVOKE).
    # Poort 5433 = lokale Postgres 16 (Homebrew), bewust gescheiden van een eventuele Postgres.app-
    # instantie op 5432 — productie (Cloud SQL) draait 16, lokaal nooit een nieuwere major-versie.
    database_url: str = "postgresql+psycopg://postgres@localhost:5433/boekhouding"

    # Runtime-connectie van de applicatie zelf: least-privilege rol zonder DDL-rechten en zonder
    # UPDATE/DELETE op audit_event (append-only), onderhevig aan Row-Level Security.
    app_database_url: str = "postgresql+psycopg://boekhouding_app:devpassword@localhost:5433/boekhouding"

    # Testdatabase (pytest) — apart van de dev-database, wordt bij elke testrun gereset.
    test_database_url: str = "postgresql+psycopg://postgres@localhost:5433/boekhouding_test"
    test_app_database_url: str = (
        "postgresql+psycopg://boekhouding_app:devpassword@localhost:5433/boekhouding_test"
    )

    # Omgeving voor secret-fallback-guards (zie app/security/envelope.py, migraties/0001).
    environment: str = "dev"

    # JWT-signing (HS256). Lokaal via .env; in Cloud Run via Secret Manager. Nooit een fallback
    # buiten dev — zie app/security/tokens.py::_resolve_jwt_secret.
    jwt_secret: str | None = None
    jwt_access_ttl_seconds: int = 900  # 15 min
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 dagen
    jwt_totp_setup_ttl_seconds: int = 600  # 10 min, alleen voor de TOTP-enrollment-stap

    # Envelope-encryption masterkey (base64, 32 bytes) voor totp_secret at rest. Lokaal via .env;
    # in Cloud Run via Secret Manager/KMS (zie app/security/envelope.py voor het wrap-vervangbare
    # MasterKeyProvider-interface). Nooit een fallback buiten dev.
    totp_master_key_b64: str | None = None

    # Documentopslag (fase 1): lokaal bestandssysteem in dev, Cloud Storage-implementatie van
    # dezelfde interface in productie (zie app/documenten/storage.py) — 7 jaar bewaarplicht.
    document_opslag_basismap: str = "./.data/documenten"
    document_max_bytes: int = 20 * 1024 * 1024  # 20 MB, ruim voor PDF/XML-facturen

    # CORS: frontend (Vite-dev-server) en backend draaien lokaal op verschillende poorten, dus
    # verschillende origins. Cookies (refresh-token) vereisen expliciete origins + credentials —
    # nooit "*" i.c.m. allow_credentials (browsers weigeren dat sowieso, en het zou de
    # httpOnly-cookiebescherming ondermijnen als het wel kon).
    cors_allowed_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
