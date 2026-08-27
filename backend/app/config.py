from decimal import Decimal
from urllib.parse import quote_plus

from pydantic import model_validator
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

    # Cloud SQL-verbinding (GCP-draaiboek F2): de F1-secrets zijn losse wachtwoorden
    # (APP_DB_PASSWORD, DB_OWNER_WACHTWOORD), de app verwacht volledige URL's — deze drie
    # settings composeren die in de validator hieronder. `cloud_sql_verbinding` = de
    # instance-connection-name (project:regio:instantie); Cloud Run mount die als unix-socket
    # onder /cloudsql/. Leeg = lokale dev, de URL-defaults hierboven/hieronder blijven gelden.
    # De service krijgt alléén app_db_wachtwoord (least privilege), de migratie-job alléén
    # db_owner_wachtwoord — de andere URL blijft dan de (in de cloud onbruikbare, luid
    # falende) dev-default; dat is bewust, nooit stil de verkeerde rol gebruiken.
    cloud_sql_verbinding: str | None = None
    cloud_sql_database: str = "boekhouding"
    app_db_wachtwoord: str | None = None
    db_owner_wachtwoord: str | None = None

    # JWT-signing (HS256). Lokaal via .env; in Cloud Run via Secret Manager. Nooit een fallback
    # buiten dev — zie app/security/tokens.py::_resolve_jwt_secret.
    jwt_secret: str | None = None
    jwt_access_ttl_seconds: int = 900  # 15 min
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 dagen
    jwt_totp_setup_ttl_seconds: int = 600  # 10 min, alleen voor de TOTP-enrollment-stap

    # Accordeur-cadans (besluit Peter 2026-08-11): aparte, kortere refresh-TTL voor de rol
    # klant-accordeur. Sliding per rotatie (elke vernieuwing geeft een vers token met deze TTL),
    # dus "ná 7 dagen inactiviteit = volledige login" volgt hier direct uit — actieve gebruikers
    # blijven ingelogd, een stilliggend apparaat valt na 7 dagen terug op wachtwoord + passkey.
    jwt_refresh_ttl_accordeur_seconds: int = 60 * 60 * 24 * 7  # 7 dagen
    # Ontgrendel-frequentie (besluit Peter 2026-08-27): de passkey-ontgrendeling bij app-opening
    # is HOOGUIT 1× per dit venster per apparaat — daartussen opent de app direct op de stille
    # refresh. Server-side venster (geen client-klok): anker = `webauthn_credential.
    # laatst_gebruikt_op` van het apparaat waar de sessie aan hangt (wordt uitsluitend gezet
    # bij een echte passkey-ceremonie — registratie of assertion — nooit per request). De
    # 7-dagen-inactiviteitsregel hierboven en de kill-switch blijven onverkort.
    ontgrendel_venster_seconds: int = 60 * 60 * 24  # 24 uur
    # TTL van het tussentoken ná de wachtwoordstap van de accordeur-login/activatie — alleen
    # geldig om de passkey-registratie of -assertion af te ronden (zelfde idee als totp_setup).
    jwt_passkey_setup_ttl_seconds: int = 600
    # WebAuthn Relying Party: rp_id moet het registreerbare domein zijn waarop de app draait
    # (dev: localhost; GCP: het productiedomein via env). Origins = exact wat de browser als
    # origin meestuurt (dev: de Vite-server; de backend op 8000 voor echte-HTTP-tests).
    webauthn_rp_id: str = "localhost"
    webauthn_rp_naam: str = "Nijenhuis Boekingsmodule"
    webauthn_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]
    webauthn_challenge_ttl_seconds: int = 300
    # Dev-fallback voor de secure-context-beperking (WebAuthn werkt alleen op https/localhost —
    # een telefoontest via LAN-IP kan dus géén echte passkey doen). Default UIT en HARD
    # onwerkzaam buiten dev/local (zie app/auth/webauthn_service.py::dev_stub_actief): een
    # stub-registratie/-assertie wordt zichtbaar gemarkeerd (is_dev_stub) en in productie
    # geweigerd, ongeacht deze setting. Zie BESLISSINGEN "Accordeur-PWA".
    auth_biometrie_dev_stub: bool = False

    # Native store-app fase 2 (GO Peter 2026-08-16): passkey-domeinkoppeling voor de
    # Capacitor-apps. iOS valideert het Associated-Domains-entitlement tegen
    # /.well-known/apple-app-site-association, Android de signing-key tegen
    # /.well-known/assetlinks.json — beide op de apex (rp_id, besluit 0022), geserveerd door
    # app/auth/wellknown.py. Fail-closed: leeg = 404 (geen halve of foute koppeling
    # publiceren). Waarden komen bij de store-accounts van Peter (PDL): het Apple-team-id en
    # de sha256-vingerafdruk(ken) van de Android-signing-key. NB Android-login vergt straks
    # óók de origin `android:apk-key-hash:<b64url-sha256>` in webauthn_origins (deploy-config).
    apple_team_id: str = ""
    native_app_bundle_id: str = "nl.aknijenhuis.goedkeuren"
    android_cert_sha256_vingerafdrukken: list[str] = []

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
    # Cloud KMS-masterkeyprovider (GCP-draaiboek F1.3, beslispunt 8 — §2b-norm): volledige
    # CryptoKey-resourcenaam gezet = wrap/unwrap via KMS (masterkey verlaat KMS nooit), leeg =
    # LocalMasterKeyProvider (dev). Overstap op bestaande data vereist het herversleutel-script
    # (scripts/herversleutel_masterkey.py) — een verse key zonder die stap maakt de
    # credential-store en TOTP-secrets onbruikbaar.
    kms_masterkey_sleutel: str | None = None

    # Documentopslag (fase 1): lokaal bestandssysteem in dev, Cloud Storage-implementatie van
    # dezelfde interface in productie (zie app/documenten/storage.py) — 7 jaar bewaarplicht.
    document_opslag_basismap: str = "./.data/documenten"
    document_max_bytes: int = 20 * 1024 * 1024  # 20 MB, ruim voor PDF/XML-facturen
    # GCS-backend (GCP-draaiboek F1.5): bucketnaam gezet = documentopslag via Cloud Storage
    # (app/documenten/storage.py::GcsDocumentOpslag, ADC-authenticatie), leeg = lokaal
    # bestandssysteem. De 7-jaars-retentie zit op de bucket zelf (F1.4), niet in de app.
    document_gcs_bucket: str | None = None

    # Same-origin frontend-serving (GCP-draaiboek F2.2, beslispunt 4): pad naar de Vite-build
    # (dist). Gezet = de backend serveert de SPA zelf (app/static_frontend.py — hashed assets
    # immutable, index.html no-cache, SPA-fallback met dezelfde bypass-regels als de dev-proxy).
    # Leeg = dev (Vite-dev-server + proxy). In het productiebeeld bakt de Dockerfile de build
    # naar /app/static en zet FRONTEND_DIST_MAP daarop.
    frontend_dist_map: str | None = None

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

    # Inkomend projectaanvraag-koppelvlak (route A, koppelcontract §5 v1.15): EIGEN secret voor
    # dit inkomende kanaal — bewust niet het uitgaande webhook_hmac_secret hergebruiken (twee
    # richtingen, twee secrets; compromittering van de één raakt de ander niet). Uitwisseling
    # met vastgoed t.z.t. samen met de F4-secretuitwisseling; zonder secret buiten dev weigert
    # het endpoint zichtbaar (503), nooit een stil fallback.
    projectaanvraag_hmac_secret: str | None = None
    # Replay-venster van het inkomende kanaal (~5 min, koppelcontract-patroon HMAC + timestamp
    # + nonce): een aanvraag met een timestamp buiten dit venster wordt geweigerd.
    projectaanvraag_replay_venster_seconds: float = 300.0

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
    # Achtergrond-voertuig van de projectcijfers-sync (fix 504-crash 2026-08-23): de volledige
    # Cloud Run-job-resource ("projects/…/locations/…/jobs/rlz-projecten-cijfers"). Gezet =
    # de sync-knop triggert één on-demand job-uitvoering (metadata-server-auth, wachtrij-rij =
    # de opdracht); leeg (dev/tests) = een achtergrond-thread in het proces zelf.
    cijfers_sync_job_resource: str | None = None

    # Bank auto-verversing bij openen (feedbackronde 25-08 deel 4 punt 2): zelfde voertuig-
    # splitsing als de projectcijfers ("projects/…/jobs/rlz-bank-sync" = on-demand job; leeg =
    # thread) én de drempel tegen rate-limit-verspilling — is de laatste geslaagde bank-sync van
    # de administratie jonger dan dit aantal minuten, dan start het openen van het bankscherm
    # géén nieuwe RLZ-ronde (de handmatige verversen-knop wél, die blijft onbegrensd).
    bank_sync_job_resource: str | None = None
    # Extractie-wachtrij als on-demand Cloud Run-job (feedbackronde 26-08 punt 4:
    # "projects/…/jobs/rlz-extractie-wachtrij"). Gezet = een groot document dat naar de
    # wachtrij gaat triggert één job-uitvoering i.p.v. een in-process thread (die op Cloud Run
    # met request-based CPU buiten een request stilvalt); leeg = dev-threadpool.
    extractie_wachtrij_job_resource: str | None = None
    # Eerste-sync-run van de onboarding-wizard (feedbackronde 26-08 punt 5:
    # "projects/…/jobs/rlz-eerste-sync"). Gezet = job-trigger, leeg = dev-thread.
    eerste_sync_job_resource: str | None = None
    bank_auto_ververs_drempel_minuten: int = 5

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

    # AI-kostenmeter (besluit Peter 2026-08-14, migratie 0047): deterministische maandgrens op de
    # Anthropic-API-kosten voor intake-AI (extractie + splitsing) — "code voor cijfers": kosten
    # worden in code berekend uit deze gepinde prijstabel × gepinde USD→EUR-koers, nooit geschat
    # en nooit door AI. De limiet zelf leeft als Beheerder-instelling in de DB
    # (platform.ai_kosten_instelling); deze env-setting is uitsluitend fallback als die rij
    # ontbreekt. Koers bewust conservatief op 1,00 (EUR/USD ligt daar in de praktijk onder — de
    # meter overschat dus eerder dan dat hij onderschat). Prijzen = Anthropic-stickerprijzen
    # (USD per miljoen tokens, web-geverifieerd 2026-08-14; introductiekortingen bewust
    # genegeerd — conservatief). Cache-multipliers (schrijf 1,25×, lees 0,10× van de inputprijs,
    # 5-minuten-TTL zoals de client gebruikt) staan als constanten in app/aikosten/service.py.
    # Een model dat hier niet in staat = fail-closed: de poort blokkeert de call.
    # Tweede laag (klikwerk Peter, geen code): spend-limit ~$110 in de Anthropic-console.
    ai_kosten_maandlimiet_eur: Decimal = Decimal("100")
    ai_kosten_usd_eur_koers: Decimal = Decimal("1.00")
    ai_kosten_prijzen_usd_per_mtok: dict[str, dict[str, Decimal]] = {
        "claude-sonnet-5": {"input": Decimal("3.00"), "output": Decimal("15.00")},
        "claude-opus-5": {"input": Decimal("5.00"), "output": Decimal("25.00")},
        "claude-opus-4-8": {"input": Decimal("5.00"), "output": Decimal("25.00")},
        "claude-haiku-4-5": {"input": Decimal("1.00"), "output": Decimal("5.00")},
    }

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
    # per-administratie-gate). IMAP-instellingen = de live postvak-fetch (app/intake/postvak.py,
    # F3.4 geactiveerd 2026-08-15): het centrale adres is facturen@ak-nijenhuis.nl op Google
    # Workspace (imap.gmail.com, SSL 993, app-wachtwoord via Secret Manager
    # INTAKE_IMAP_WACHTWOORD — envs op de rlz-intake-imap-job, zie deploy.yml). None = niet
    # geconfigureerd (lokale dev), de .eml-upload is dan het intake-kanaal.
    intake_ai_ingeschakeld: bool = False
    intake_imap_host: str | None = None
    intake_imap_poort: int = 993
    intake_imap_gebruiker: str | None = None
    intake_imap_wachtwoord: str | None = None
    intake_postvak_adres: str | None = None

    # Berichten-bouwsteen (accordeur-notificaties, 2026-08-15): gedeeld uitgaand mailkanaal via
    # de bestaande Google Workspace (SMTP + app-wachtwoord — zelfde provider-lijn als de
    # IMAP-intake, DPA rond 2026-08-15). Bedient de dagelijkse accordeur-herinnering én de
    # uitnodigingsflow (accordeur- en kantooruitnodigingen per mail i.p.v. handmatig link
    # kopiëren). None = niet geconfigureerd (lokale dev): verzenden faalt dan ZICHTBAAR
    # (MailNietGeconfigureerd) — nooit stil. Wachtwoord via Secret Manager
    # (BERICHTEN_SMTP_WACHTWOORD). Afzenderadres (besluit Peter 2026-08-15): facturen@
    # ak-nijenhuis.nl — géén aparte gebruiker/licentie voor berichten@; menselijke antwoorden
    # blijven via de Reply-To buiten het intake-postvak, auto-replies die tóch op facturen@
    # binnenkomen zijn geaccepteerde zichtbare ruis (de intake herkent ze niet als factuur →
    # verzamelbak). Zie BESLISSINGEN "Accordeur-notificaties — mailbesluit".
    berichten_smtp_host: str | None = None
    berichten_smtp_poort: int = 465
    berichten_smtp_gebruiker: str | None = None
    berichten_smtp_wachtwoord: str | None = None
    berichten_afzender: str | None = None  # default: berichten_smtp_gebruiker
    berichten_afzender_naam: str = "Administratiekantoor Nijenhuis"
    # Reply-To voor álle uitgaande mail: antwoorden van mensen horen bij Peter, niet in het
    # intake-postvak (mailbesluit 2026-08-15). None = geen Reply-To-header (antwoorden gaan
    # dan naar het afzenderadres).
    berichten_reply_to: str | None = None

    # Basis-URL van de app voor links in uitgaande berichten (uitnodigingslink, PWA-deep-link).
    # Dev = de Vite-dev-server; productie = het https-domein (F2 domain mapping). HARD PRINCIPE
    # (BESLISSINGEN "Accordeur-notificaties"): een maillink is altijd een deep-link naar de app
    # — de auth-cadans (passkey bij opening) blijft de poort; goedkeuren-vanuit-de-mail (met of
    # zonder token) bestaat bewust niet.
    app_basis_url: str = "http://localhost:5173"

    # Web Push (accordeur-PWA): VAPID-sleutelpaar (scripts/genereer_vapid_sleutels.py — private
    # key via Secret Manager PUSH_VAPID_PRIVATE_KEY, public key is geen geheim). Niet gezet =
    # push niet geconfigureerd: subscriben faalt zichtbaar en de herinnering valt terug op
    # e-mail. `push_vapid_onderwerp` is de contact-claim richting de push-diensten (RFC 8292).
    push_vapid_private_key: str | None = None
    push_vapid_public_key: str | None = None
    push_vapid_onderwerp: str = "mailto:berichten@ak-nijenhuis.nl"

    # Native push voor de store-apps (fase 3, verkenning/17 (b): APNs direct voor iOS + FCM
    # voor Android, achter één adapterlaag in app/berichten/push.py). Niet gezet = die soort
    # niet geconfigureerd: verzending valt per gebruiker terug op e-mail (zelfde patroon als
    # VAPID hierboven), registreren van zo'n subscriptie weigert zichtbaar.
    # APNs: token-based auth met de .p8-sleutel uit het Apple Developer-account (PDL) —
    # private key via Secret Manager APNS_KEY_P8; topic = de bundle-id (native_app_bundle_id),
    # team-id = apple_team_id (fase 2-setting). Sandbox alleen voor TestFlight-/Xcode-builds.
    # KvK Basisprofiel-API (ZZP-dossier A3, steigerbouw-run 25-08 — Vastly-patroon): zonder
    # sleutel draait de client tegen KvK's publieke TESTOMGEVING (fictieve data); productie =
    # KVK_API_KEY + KVK_BASE_URL uit Secret Manager, nooit in code/git. Consistentiecheck in
    # app/integraties/kvk.py (sleutel en URL uit dezelfde omgeving).
    kvk_api_key: str | None = None
    kvk_base_url: str | None = None

    apns_key_p8: str | None = None
    apns_key_id: str = ""
    apns_sandbox: bool = False
    # FCM (HTTP v1): service-account-JSON van het Firebase-project (Secret Manager
    # FCM_SERVICE_ACCOUNT_JSON; project-id zit in de JSON). AVG-notitie: gegevensstroom via
    # Google — payload bevat alleen aantal + deep-link, nooit financiële details (zelfde
    # dataminimalisatie als het lockscreen-principe van Web Push).
    fcm_service_account_json: str | None = None

    # Volumerem op de herinnering-job (noodrem-patroon, zelfde grondhouding als
    # max_boekingen_per_dag_per_administratie): max. verzonden berichten per run — daarboven
    # stopt de run zichtbaar (exit 1 -> F3.2-job-failure-alert), nooit stil doorpompen.
    herinnering_max_berichten_per_run: int = 50

    # Volumerem op de nieuwe-facturen-bundelmelding (job ~elke 10 min, besluit Peter 2026-08-16;
    # zelfde noodrem-patroon als hierboven).
    nieuwe_facturen_max_berichten_per_run: int = 50

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

    @model_validator(mode="after")
    def _composeer_cloud_sql_urls(self) -> "Settings":
        """Cloud SQL-URL-compositie (F2): met een gezette `cloud_sql_verbinding` worden de
        database-URL's opgebouwd uit de losse wachtwoord-secrets — unix-socket via de
        `?host=/cloudsql/...`-vorm (psycopg). Wachtwoorden ge-URL-encodeerd (de gegenereerde
        secrets bevatten base64-tekens als + en /). Fail-closed: een verbinding zonder énig
        wachtwoord is een configuratiefout — hard weigeren, nooit stil op de dev-defaults
        doorstarten."""
        if not self.cloud_sql_verbinding:
            return self
        if not self.app_db_wachtwoord and not self.db_owner_wachtwoord:
            raise ValueError(
                "cloud_sql_verbinding is gezet maar er is geen app_db_wachtwoord of "
                "db_owner_wachtwoord — minstens één van beide secrets is vereist."
            )
        socket_query = f"?host=/cloudsql/{self.cloud_sql_verbinding}"
        if self.app_db_wachtwoord:
            self.app_database_url = (
                f"postgresql+psycopg://boekhouding_app:{quote_plus(self.app_db_wachtwoord)}"
                f"@/{self.cloud_sql_database}{socket_query}"
            )
        if self.db_owner_wachtwoord:
            self.database_url = (
                f"postgresql+psycopg://postgres:{quote_plus(self.db_owner_wachtwoord)}"
                f"@/{self.cloud_sql_database}{socket_query}"
            )
        return self


settings = Settings()
