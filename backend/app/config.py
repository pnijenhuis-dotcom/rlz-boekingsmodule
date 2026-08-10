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

    # Race-tolerante hergebruik-detectie (browserreview 2026-08-07): twee parallelle
    # vernieuwen-calls uit dezelfde browser (dubbel useEffect/StrictMode, meerdere tabs) zijn
    # geen tokendiefstal. Een tweede aanbieding van hetzelfde token bínnen dit venster krijgt
    # een vers sibling-token i.p.v. revoke-all; erná geldt hergebruik onverkort als
    # replay-signaal en gaan alle sessies dicht (Auth-0010-b). Elk binnen-grace-hergebruik
    # wordt wél ge-audit — observeerbaar, nooit stil.
    refresh_hergebruik_grace_seconds: int = 10
    # Rij-lock-timeout op de rotatie-transactie (SELECT ... FOR UPDATE): een gelijktijdige
    # rotatie van hetzelfde token wacht kort op de winnaar en krijgt daarna een deterministisch
    # antwoord — nooit een eeuwig pending request (browserreview 2026-08-07: hang).
    refresh_rotatie_lock_timeout_ms: int = 5000

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

    # Webhook "factuur geboekt" (koppelcontract §3): gedeeld HMAC-secret waarmee de afleveraar
    # elke verzendpoging tekent (app/documenten/webhook_afleveraar.py). Lokaal via .env, in
    # Cloud Run via Secret Manager (besluit 0012 — secretwaarden nooit in code/logs/chat). Nooit
    # een fallback buiten dev — zelfde bewaking als jwt_secret/totp_master_key_b64.
    webhook_hmac_secret: str | None = None

    # Webhook-afleveraar: doel-URL van de vastgoed-ontvanger. Default None = onvoldoende
    # geconfigureerd — de failsafe: outbox-rijen blijven dan gewoon openstaand, GEEN fout
    # (vastgoed's ontvanger bestaat nog niet). Aflevering vereist daarnaast de expliciete
    # toggle (platform.webhook_instelling, default UIT — parallel aan de boeken-failsafe).
    webhook_doel_url: str | None = None
    webhook_timeout_seconds: float = 10.0
    # Retry/backoff per outbox-rij: exponentieel (basis * 2^(poging-1), gecapt), na
    # webhook_max_pogingen mislukte pogingen gaat de rij zichtbaar naar 'mislukt' (dead-letter)
    # — nooit een stille oneindige retry-lus.
    webhook_max_pogingen: int = 8
    webhook_backoff_basis_seconds: float = 60.0
    webhook_backoff_max_seconds: float = 3600.0
    # In-process poll-interval (dev; productie draait dezelfde verwerk-functie als Cloud
    # Scheduler/Cloud Run-job via `python -m app.cli webhook-afleveren`).
    webhook_afleveraar_interval_seconds: float = 30.0

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

    # Omzetmodule (fase 2): marge-plausibiliteitscheck — maximale afwijking (in procentpunten)
    # van de marge t.o.v. het historisch gemiddelde van de laatste geboekte omzetperiodes.
    # Blokkerend buiten de bandbreedte (harde check). Historie-venster in aantal boekingen.
    omzet_marge_bandbreedte_procentpunt: float = 30.0
    omzet_marge_historie_boekingen: int = 8

    # E-mail-intake (fase 3). intake_ai_ingeschakeld is de AVG-gate voor AI op nog-niet-
    # toegewezen documenten (tenaamstelling-lezen + multi-factuur-splitsingsdetectie): op dat
    # moment is er nog geen administratie, dus de per-administratie-gate kan niet gelden —
    # default UIT: zonder opt-in gaat er geen intake-byte naar de Claude API en valt elke
    # niet-eenduidige PDF gewoon in de verzamelbak (mens wijst toe, daarna geldt de normale
    # per-administratie-gate). IMAP-instellingen zijn de LIVE-FETCH-SEAM (app/intake/postvak.py):
    # None = niet geconfigureerd, de .eml-upload is dan het enige intake-kanaal; de echte
    # IMAP/Cloud Scheduler-koppeling wordt bij de GCP-uitrol geactiveerd.
    intake_ai_ingeschakeld: bool = False
    intake_imap_host: str | None = None
    intake_imap_gebruiker: str | None = None
    intake_imap_wachtwoord: str | None = None
    intake_postvak_adres: str | None = None

    # CreditNote-381-herkenning (koppelcontract §2d-creditnota's v1.11): config-gate.
    # AAN sinds 2026-08-10 (blok D grote opdracht): de golden-case-verificatie tegen de échte
    # Vastly-UBL's is geslaagd (intake-routing + creditboekpad + storno, zie
    # tests/intake/test_golden_cases_vastly.py en tests/integration/
    # test_golden_cases_write_integration.py) — daarmee is stap 2 van de activatievolgorde
    # (OPEN_ITEMS 2026-08-09) gezet en mag vastgoed CREDITNOTA_381_ACTIEF openen. De failsafes
    # blijven onverkort: kapotte markering/NLCIUS-invalide → verzamelbak, herleiding naar een
    # geboekt origineel is een blokkerende check. Uit-zetten kan altijd via de env-var
    # (CREDITNOTA_381_INGESCHAKELD=false) — dan valt een 381 weer zichtbaar in de verzamelbak.
    creditnota_381_ingeschakeld: bool = True

    # Migratie-guard bij startup (app/db/migratie_guard.py): default fail-fast, zodat een gemiste
    # `make migrate` nooit meer een raadsel-500 wordt maar een duidelijke weigering om te starten.
    # "waarschuwen" is een bewuste uitzondering voor latere productie-scenario's (bv. een korte
    # periode tijdens een gefaseerde rollout waarin oude en nieuwe containers naast elkaar draaien
    # tegen hetzelfde schema) — niet de default, alleen expliciet aanzetten.
    migratie_guard_fail_fast: bool = True


settings = Settings()
