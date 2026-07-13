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

    # Webhook-stub "factuur geboekt" (koppelcontract §3, app/documenten/webhook.py): HMAC-secret
    # voor het ondertekenen van uitgaande payloads. Aflevering zelf staat nog uit (fase-vervolg),
    # maar de payload wordt al getekend zodat het schema/de handtekeningvorm nu al klopt. Nooit
    # een fallback buiten dev — zelfde bewaking als jwt_secret/totp_master_key_b64.
    webhook_hmac_secret: str | None = None

    # Boeken-failsafe (c), volumerem (CLAUDE.md: "config, default laag"): max. aantal boekingen
    # per administratie per kalenderdag. Bewust laag — dit is een noodrem tegen een runaway-bug
    # of verkeerd geconfigureerde automatische boeking, geen normale-bedrijfsvoering-limiet.
    max_boekingen_per_dag_per_administratie: int = 20

    # AI-extractie (fase AI-extractie sessie 1): Claude leest de PDF, code rekent, mens drukt.
    # Key uitsluitend via .env/Secret Manager (besluit 0012 — nooit in code/logs/chat); géén
    # fallback: zonder key wordt AI-extractie zichtbaar overgeslagen, nooit stil geraden.
    # Model config-gedreven (registers/koppelingen.md, kern-AI-koppeling) — wijzigen = alleen
    # deze setting, geen code. Default Sonnet: gestructureerde factuurextractie heeft geen
    # Opus-diepte nodig en Opus liep in de praktijk tegen de request-timeout aan bij een normale
    # factuur (zie docs/BOUWPLAN.md 5b, timeout-fix 2026-07-10) — Sonnet is sneller én goedkoper
    # bij gelijke kwaliteit op dit taaktype.
    anthropic_api_key: str | None = None
    ai_extractie_model: str = "claude-sonnet-5"

    # Boekingsgeheugen (app/geheugen/): seed-recency-cap in maanden (alleen facturen jonger dan
    # dit venster tellen mee in de RLZ-seed) en de weegparameters van de voorstel-engine —
    # app-observaties (door een mens bevestigde boekingen) wegen zwaarder dan de RLZ-seed
    # (CLAUDE.md: "correcties wegen zwaarder"), en oudere observaties tellen exponentieel
    # minder mee (halfwaardetijd in dagen).
    boekingsgeheugen_seed_maanden: int = 36
    boekingsgeheugen_halfwaardetijd_dagen: int = 365
    boekingsgeheugen_gewicht_app: float = 3.0
    boekingsgeheugen_gewicht_rlz_seed: float = 1.0
    # Ruim genoeg voor facturen met veel regels; de SDK-timeout dekt de synchrone upload-flow
    # (bewust synchroon deze fase — zie docs/BOUWPLAN.md, async-worker uitgesteld).
    ai_extractie_max_tokens: int = 16000
    ai_extractie_timeout_seconds: float = 120.0
    # Minimale tussenruimte tussen twee Claude-aanroepen (throttling-conventie voor elke
    # koppeling-client, registers/conventies.md) — retry/backoff zelf zit in de SDK (429/5xx).
    ai_extractie_min_interval_seconds: float = 0.5
    # Zekerheidsscores onder deze drempel markeert het controlescherm oranje ("bij twijfel nooit
    # gokken" — de waarde blijft een voorstel dat Peter controleert, nooit een automatische keuze).
    ai_extractie_zekerheid_drempel: float = 0.8

    # Klein-vs-groot-routing (async extractie, 2026-07-10): een PDF die op de AI-route gaat en
    # boven één van deze drempels zit, gaat niet synchroon in de upload-request maar direct de
    # achtergrondwachtrij in (status extractie_wachtrij) — een monsterfactuur mag het scherm
    # nooit meer blokkeren. Onder beide drempels blijft de bestaande snelle synchrone route.
    ai_extractie_sync_max_paginas: int = 8
    ai_extractie_sync_max_bytes: int = 3 * 1024 * 1024  # 3 MB
    # Overbelastingsbescherming: maximaal zoveel zware extracties tegelijk (dev: in-process
    # threads). Bewust 1 — één grote factuur mag de machine niet plattrekken, en de wachtrij
    # maakt wachten zichtbaar i.p.v. traag.
    ai_extractie_worker_concurrency: int = 1

    # Migratie-guard bij startup (app/db/migratie_guard.py): default fail-fast, zodat een gemiste
    # `make migrate` nooit meer een raadsel-500 wordt maar een duidelijke weigering om te starten.
    # "waarschuwen" is een bewuste uitzondering voor latere productie-scenario's (bv. een korte
    # periode tijdens een gefaseerde rollout waarin oude en nieuwe containers naast elkaar draaien
    # tegen hetzelfde schema) — niet de default, alleen expliciet aanzetten.
    migratie_guard_fail_fast: bool = True


settings = Settings()
