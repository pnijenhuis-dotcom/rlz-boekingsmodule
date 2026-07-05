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


settings = Settings()
