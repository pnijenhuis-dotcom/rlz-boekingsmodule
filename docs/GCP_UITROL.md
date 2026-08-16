# GCP-uitroldraaiboek — RLZ Boekingsmodule

> **Status: F0 FORMEEL AF (2026-08-14, projectnummer 652591056217 — slotverificatie
> deploy-test-run #1 GROEN, zie §F0-uitvoering); F1 UITGEVOERD (2026-08-14 —
> migratie 0001→0047 + GCS/KMS-verificatie geslaagd, zie §F1 — UITGEVOERD);
> F2 FORMEEL AF (2026-08-14); F3 UITGEVOERD (2026-08-14, zie §F3-uitvoering —
> alerting + 4 jobs + scheduler staan, per job een handmatige run geverifieerd;
> IMAP bewust inactief tot DPA-check; open: alertmail-ontvangst bevestigen (Peter));
> F3.3 rapportage-teller GEFIXT (2026-08-14 — cutover-voorwaarde dicht);
> F5-VOORBEREIDING UITGEVOERD (2026-08-14): CMEK-memo = voorstel-besluit 0021,
> verwerkingsregister §8/§9 bijgewerkt, poortdossier `docs/avg/08-f5-poortdossier.md`;
> CMEK-BESLUIT 0021 BESLOTEN (akkoord Peter 2026-08-14) + UITGEVOERD
> (2026-08-14, zie §F5-CMEK-uitvoering): Cloud SQL herbouwd als `rlz-sql2` mét CMEK,
> bucket-default-key gezet, volledige F1-herverificatie groen, oude `rlz-sql` opgeruimd —
> poortdossier-stand 7/8 ✅ (2026-08-15: CDPA versie 8 juni 2026 gearchiveerd — punt 1 ✅;
> Exact-VWO-bevestiging gearchiveerd — punt 5 ✅);
> **F5-POORT DICHT: 8/8 ✅ (2026-08-15 — punt 6 IMAP-provider-DPA rond: Google Workspace,
> geldende DPA = de CDPA; zie poortdossier punt 6). Tranche 2 (§F1.6) is daarmee
> vrijgegeven — uitvoering zodra Peter het go-live-moment kiest.**
> **F3.4 IMAP-ACTIVATIE UITGEVOERD (2026-08-15, zie §F3.4-uitvoering): live IMAP-fetch
> gebouwd (echte imaplib-bron i.p.v. de seam-stub) + job-config in deploy.yml
> (facturen@ak-nijenhuis.nl, imap.gmail.com SSL 993); resterende klikken: app-wachtwoord
> in het secret (Peter), scheduler-resume + handmatige groene run + livetest.**
> NB datumcorrectie 2026-08-14: eerdere "2026-08-15"-stempels in dit document waren een
> dag te ver (commits én GCP-timestamps bewijzen 2026-08-14). Dat gold óók voor de
> akkoorddatum van besluit 0021: correctie Peter 2026-08-14 — de "15-08" zat in de
> aangeleverde opdrachttekst, werkelijke akkoorddatum = 2026-08-14.
> Besluiten Peter 2026-08-12: **eigen RLZ-project binnen
> de PDL Powerhouse-organisatie** (zelfde org als vastgoeds `vastly-504108`, nadrukkelijk NIET
> hetzelfde project); **tempo = zo snel mogelijk live**; de **AVG-poort geldt alleen voor echte
> klantdata** — infra-opbouw en draaien met de TEST-administratie/eigen kantoordata mag eerder
> (parallel spoor). De besluiten op de 10 beslispunten staan in de tabel onderaan en zijn in de
> fase-teksten verwerkt; het **F0-uitvoeringspakket** staat in `scripts/gcp/f0_fundament.sh`
> (zie §F0-uitvoering). Kaders: koppelcontract §2b (Cloud Run / Cloud SQL / Secret Manager /
> Storage / Scheduler, `europe-west4`), CLAUDE.md-hostbesluit v1.2, docs/avg/05-activatie-
> checklist stap 2 (= de cloud-gate), Platform OPEN_ITEMS (GCP-uitrol-item + identiteit-eerst),
> en vastgoeds week-1-patronen (WIF + SA's + Artifact Registry, project `vastly-504108`).
>
> Legenda per fase: **Afhankelijk van** · **Wie** (Peter = accounts/besluiten/DNS/jurist,
> Code = code/config/scripts/verificatie) · **Verificatie** (pas afvinken als aantoonbaar).

## F0 — Fundament (project, IAM, registry)

**Afhankelijk van:** niets (startpunt). **Doorlooptijd:** ~1 dagdeel mét Peter erbij.

1. **Identiteit-eerst-check (OPEN_ITEMS-item, no-regret):** project, billing, domein en secrets
   hangen onder de juiste **juridische entiteit** (de PDL Powerhouse-org, niet een
   privé-account). **Besloten (beslispunt 2): owner = het org-beheeraccount van de PDL
   Powerhouse-org, hetzelfde account als bij `vastly-504108`.** *(Peter)*
2. **Project aanmaken** in de PDL Powerhouse-org. **Besloten (beslispunt 1): `rlz-boekhouding`**
   (project-ID krijgt zo nodig een cijfersuffix, zelfde patroon als `vastly-504108`).
   Billing-account van de org koppelen. *(Peter)*
3. **Regio-pin `europe-west4`** voor álles + **Organization Policy op EU-locaties**
   (`constraints/gcp.resourceLocations`) — dit is meteen een vinkje van AVG-stap 2; op
   org-niveau bestaat die policy mogelijk al door vastgoed — controleren, anders op
   projectniveau zetten. *(Peter zet, Code verifieert)*
4. **IAM-basis, least privilege — drie aparte service-accounts** (vastgoed-patroon):
   - `run-backend@` — runtime van de Cloud Run-service (Cloud SQL Client,
     Secret Manager accessor op alléén de eigen secrets, Storage objectAdmin op alléén de
     documentenbucket);
   - `run-jobs@` — runtime van de Cloud Run-jobs (zelfde grondhouding, plus wat de sync/afleveraar
     nodig heeft);
   - `deploy@` — deployen via **Workload Identity Federation** naar het vastgoed-patroon
     (GitHub Actions zonder langlevende keys; Artifact Registry writer + Cloud Run deployer;
     **besloten — beslispunt 10: WIF/GitHub Actions, repo-conditie op
     `pnijenhuis-dotcom/rlz-boekingsmodule`**).
   *(Code bereidt gcloud-commando's voor, Peter voert uit als owner)*
5. **Artifact Registry**: één Docker-repository in `europe-west4`. *(Code)*

**Verificatie F0:** project zichtbaar onder de org met billing; `gcloud`-lijst van de drie SA's
met hun rollen; een dummy-image gepusht naar de registry via WIF (bewijst de deploy-keten).

### F0-uitvoering (klaar om te draaien)

Het volledige commandopakket staat in **`scripts/gcp/f0_fundament.sh`** — genummerd, elk
commando met één regel uitleg én de bijbehorende verificatiestap. **Peter draait het als
org-owner** (Cloud Shell of lokale `gcloud` met het org-beheeraccount); Code voert niets uit.

- **In te vullen door Peter (bovenin het script, het script weigert te draaien zolang de
  placeholders staan):** `ORG_ID` (`gcloud organizations list`) en `BILLING_ACCOUNT_ID`
  (`gcloud billing accounts list`). De GitHub-repo staat er al in
  (`pnijenhuis-dotcom/rlz-boekingsmodule` — even checken dat dit de repo is waar de
  deploy-workflow gaat leven).
- Het script **controleert eerst of de EU-locatie-org-policy al op org-niveau bestaat**
  (mogelijk gezet door vastgoed) en zet 'm anders op projectniveau.
- Secret- en bucket-bindings voor `run-backend@`/`run-jobs@` zijn bewust **niet** in F0 opgenomen:
  die zijn per-resource en horen bij F1 (de secrets en de bucket bestaan dan pas).
- Na afloop print het script de **projectnummer- en WIF-provider-resourcenamen**; daarmee
  bouwt Code de GitHub Actions-testworkflow voor de dummy-push (de laatste F0-verificatie).
- **Deploy-workflow-SKELET staat klaar (2026-08-13):** `.github/workflows/deploy.yml` —
  workflow_dispatch-only + expliciete VUL-IN-guard (weigert zolang PROJECT_NUMBER uit F0
  niet is ingevuld), WIF-auth zonder SA-keys, en de bindende volgorde build → push →
  migratie-job (`rlz-migratie`, zelfde beeld, `alembic upgrade head`) → revisie live.
  Activeren = F0-waarden invullen + push-trigger openzetten (staat er als commentaar in).

#### F0 — UITGEVOERD (2026-08-14)

- **Gedraaid door Peter (org-owner).** De eerste run liep vast op niet-idempotente
  `create`-commando's (met `set -e` stopt het script op een al bestaande resource — halve
  uitrol, drie hervatpogingen). **LES, bindend voor alle volgende fundament-scripts:
  idempotent vanaf het begin — describe-vóór-create op élke resource.** De idempotente
  afronding staat in `scripts/gcp/f0_hervat3.sh` (herdraaibaar); `f0_fundament.sh` blijft
  het volledige genummerde naslagpakket. `f1_data.sh` volgt het patroon vanaf regel één.
- **Hernoeming:** de jobs-SA heet **`run-jobs@`** (Google eist 6–30 tekens voor
  SA-namen; `jobs` was te kort) — overal doorgevoerd, incl. F3 hieronder.
- **Uitkomst-waarden (resourcenamen, geen secrets):** `PROJECT_ID=rlz-boekhouding`,
  `PROJECT_NUMBER=652591056217`, `WIF_PROVIDER=projects/652591056217/locations/global/
  workloadIdentityPools/github/providers/github-oidc`,
  `DEPLOY_SA=deploy@rlz-boekhouding.iam.gserviceaccount.com`,
  `REGISTRY=europe-west4-docker.pkg.dev/rlz-boekhouding/rlz`.
- **Read-only geverifieerd (Code, gcloud 2026-08-14):** drie SA's mét draaiboek-rollen
  (cloudsql.client ×2; artifactregistry.writer + run.developer op deploy@;
  serviceAccountUser van deploy@ op beide runtime-SA's), WIF-provider ACTIVE met de
  repo-conditie, registry `rlz` (Docker, europe-west4), billing aan, effectieve
  EU-locatie-org-policy dekt het project.
- **Slotverificatie UITGEVOERD (2026-08-14): deploy-test-run #1 GROEN** (Success, 48 s;
  door Peter getriggerd via GitHub → Actions → deploy-test) — het dummy-image staat via
  WIF in de registry, daarmee is de hele deploy-keten (GitHub Actions → WIF → Artifact
  Registry) bewezen. **F0 is hiermee formeel AF.** `deploy.yml` heeft de F0-waarden
  ingevuld (blijft dispatch-only tot F2).

## F1 — Data (Cloud SQL, secrets, documenten)

**Afhankelijk van:** F0.

1. **Eigen Cloud SQL for PostgreSQL 16-instantie** (HA + PITR aan, `europe-west4`,
   automatische backups; lokaal draait bewust ook PG16 — nooit een nieuwere major lokaal).
   Database `boekhouding`, schema's `platform` + `boekhouding` via de bestaande
   **Alembic-keten (0001 → head)** — geen handwerk, de migratie-guard bewaakt de rest.
   Twee DB-rollen zoals lokaal: owner (migraties, DDL) en **`boekhouding_app`**
   (least privilege + RLS). NB de voorwaardelijke `vastgoed_app`-GRANTs in migraties 0005/0034
   blijven op onze eigen instantie een bedoelde no-op (de rol bestaat hier niet); ze activeren
   pas bij een latere gedeelde instance. *(Code; Peter drukt op de knop voor de instantie)*
2. **Secrets naar Secret Manager** (besluit 0012: waarden nooit in code/logs/chat):
   `JWT_SECRET` (**vers genereren voor productie**, nooit de dev-waarde hergebruiken),
   `TOTP_MASTER_KEY` (⚠️ zie datamigratie-kanttekening hieronder), `WEBHOOK_HMAC_SECRET`
   (gedeeld met vastgoed — zie F4), `ANTHROPIC_API_KEY`, t.z.t. het IMAP-wachtwoord (F3).
   Cloud Run injecteert ze als env-vars — `app/config.py` is daar al op gebouwd, code-wijziging
   nul. De RLZ-webservice-logins leven al versleuteld in de credential-store
   (`platform.rlz_credential`); de `.env`-fallback vervalt in productie.
3. **Masterkey-architectuur (koppelcontract §2b: envelope encryption met KMS-gewrapte
   data-keys):** het `MasterKeyProvider`-interface in `app/security/envelope.py` is bewust
   wrap-vervangbaar. Twee smaken:
   - (a) masterkey als Secret Manager-secret (zelfde model als nu, snelste route);
   - (b) **Cloud KMS**-provider implementeren (masterkey verlaat KMS nooit) — dit is de
     §2b-contractnorm. **Besloten (beslispunt 8): (b) meteen** — **GEBOUWD + GETEST
     (2026-08-13):** `KmsMasterKeyProvider` in `app/security/envelope.py`, config-gedreven
     via `KMS_MASTERKEY_SLEUTEL` (volledige CryptoKey-resourcenaam; leeg = lokale provider,
     dev-default), CRC32C-integriteitschecks conform de KMS-docs, unit-tests met
     fake-KMS-client (`tests/unit/test_envelope_kms.py`). *(Rest: keyring/key aanmaken +
     SA-binding encrypt/decrypt — F1-uitvoering)*
   - ⚠️ **Masterkey-continuïteit bij datamigratie — GEBORGD (script gebouwd + getest
     2026-08-13):** `scripts/herversleutel_masterkey.py` (logica
     `app/security/herversleutel.py`) doet unwrap-met-oud → wrap-met-nieuw over
     `platform.rlz_credential` + `platform.totp_secret` (webauthn n.v.t. — publieke
     sleutels). Default DRY-RUN met tellingen; `--uitvoeren` schrijft alleen als álle
     rijen slagen (één transactie); classificatie is bewijs-gedreven (kandidaat-key moet
     de ciphertext echt ontsleutelen) en daarmee hervatbaar/idempotent; een guard-test
     alarmeert zodra een nieuwe tabel met `wrapped_data_key` buiten het script valt.
     Hoofdroute: `--van lokaal --naar kms` (KMS_MASTERKEY_SLEUTEL). Dry-run tegen de
     dev-database uitgevoerd: 3 credentials + 2 TOTP-secrets herkend, 0 mislukt.
4. **Cloud Storage-bucket documenten** (`europe-west4`): **retentiebeleid 7 jaar**
   (bewaarplicht) op de bucket. **Besloten (beslispunt 7): retentie *unlocked*** (verwijderen
   kan dan alleen nog door een admin; *locked* = 7 jaar onherroepelijk, ook bij een
   foutupload) — heroverwegen bij het WORM-export-besluit. Versioning aan.
5. **Cloud Storage-implementatie van het opslag-interface** — **GEBOUWD + GETEST
   (2026-08-13):** `GcsDocumentOpslag` in `app/documenten/storage.py`, config-gedreven via
   `DOCUMENT_GCS_BUCKET` (leeg = lokaal bestandssysteem, dev-default; factory
   `storage.standaard_opslag()`), NotFound→FileNotFoundError-pariteit + zelfde
   pad-vangrail; contracttests draaien élke test tegen beide implementaties
   (`tests/documenten/test_storage.py`, fake-GCS-client). *(Rest van F1.5: bucket zelf
   aanmaken + ADC/SA-binding — Peter/F1-uitvoering)*
6. **Migratiepad bestaande data — twee tranches, expliciet gescheiden door de F5-poort:**
   - *vóór F5:* alleen schema + TEST-administratie/eigen kantoordata (verse sync — RLZ is de
     bron van waarheid, caches zijn caches);
   - *ná F5:* de échte overzet: `pg_dump`/restore van de lokale dev-DB (audit log,
     boekingsgeheugen-bevestigingen, werkvoorraad, acceptaties en accordeur-akkoorden zijn
     géén cache en moeten mee), documenten via `gsutil rsync` uit `./.data/documenten`,
     masterkey-continuïteit uit punt 3. **Verificatiescript GEBOUWD (2026-08-13):**
     `scripts/gcp/datamigratie_check.py` (rijtellingen per tabel over platform+boekhouding
     én per-administratie-tellingen voor élke tabel met `administratie_id` — generiek via
     information_schema, een nieuwe tabel valt nooit stil buiten de check; alembic-versie
     moet identiek zijn; exit 1 bij elk verschil). Stappenplan: zie **"F1.6-stappenplan
     datamigratie tranche 2"** hieronder.

**Verificatie F1:** `alembic upgrade head` schoon tegen de nieuwe instantie; de
metadata-guard-test groen tegen dat schema; een testdocument geüpload + teruggelezen via de
GCS-implementatie; retentiebeleid zichtbaar op de bucket.

### F1-uitvoering (pakket gebouwd 2026-08-14; uitgevoerd 2026-08-14 — zie hieronder)

Verdeling strikt: **Peter draait `scripts/gcp/f1_data.sh`** (alles wat gcloud is;
idempotent conform de F0-les — describe-vóór-create, herdraaibaar na elke deelfout);
**Code draait daarna de migratie + verificaties.** Volgorde:

1. **`scripts/gcp/f1_data.sh`** *(Peter, org-owner; Cloud SQL-aanmaak duurt 10–20 min —
   normaal, niet afbreken)*. Gedocumenteerde keuzes die het draaiboek open liet:
   - Cloud SQL-instantie **`rlz-sql`**, tier `db-custom-1-3840` (kleinste HA-waardige
     Enterprise-tier; verticaal schalen kan later zonder herbouw), PG16 gepind, REGIONAL
     (HA) + PITR (7 dagen transactielogs) + backups 02:00; **publiek IP zónder authorized
     networks** — verbinden kan alleen via de Cloud SQL Auth Proxy/connector (privé-IP zou
     een VPC-connector vergen: extra bewegende delen, zelfde afweging als beslispunt 4).
   - Secrets (user-managed replicatie `europe-west4` — 'automatic' botst met de
     EU-org-policy): `JWT_SECRET` (**vers gegenereerd**, nooit de dev-waarde),
     `TOTP_MASTER_KEY` (vers; met KMS actief alleen het fallback-slot van envelope.py),
     `DB_OWNER_WACHTWOORD` + `APP_DB_PASSWORD` (gegenereerd, URL-safe),
     `WEBHOOK_HMAC_SECRET` + `ANTHROPIC_API_KEY` (interactief; Enter = container zonder
     versie, waarde volgt later — HMAC komt van vastgoed, F4). Waarden nooit in
     code/logs/chat (besluit 0012). `secretAccessor` per secret voor `run-backend@` +
     `run-jobs@`; `DB_OWNER_WACHTWOORD` alléén voor `run-jobs@` (migratie-job).
   - KMS: keyring **`rlz`**, key **`masterkey`** (`europe-west4`, rotatie 1×/jaar — oude
     versies blijven ontsleutelbaar, geen herversleuteling nodig bij KMS-interne rotatie);
     encrypt/decrypt-binding voor beide runtime-SA's + het uitvoerende account (t.b.v. de
     verificatie). **`KMS_MASTERKEY_SLEUTEL` = `projects/rlz-boekhouding/locations/
     europe-west4/keyRings/rlz/cryptoKeys/masterkey`** (resourcenaam, geen secret).
   - Bucket **`rlz-boekhouding-documenten`**: retentie 7 jaar (220.903.200 s)
     **unlocked** (beslispunt 7 — nooit `retention lock` draaien), versioning aan, uniform
     bucket-level access + public-access-prevention, `objectAdmin` bucket-scoped voor
     alléén de twee runtime-SA's. `DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten`.
2. **`scripts/gcp/f1_migratie.sh`** *(Code/Peter, lokaal)* — **verbindingsroute: Cloud SQL
   Auth Proxy** (`brew install cloud-sql-proxy`, poort 5434; 5433 = lokale PG16). Draait
   `alembic upgrade head` als `postgres` (owner) — migratie 0001 maakt `boekhouding_app`
   aan met `APP_DB_PASSWORD` uit Secret Manager (precies de twee rollen zoals lokaal) —
   en daarna **de tabelniveau-metadata-guard tegen dat schema** (zelfde vergelijking als
   `tests/unit/test_migratie_metadata_guard.py`, inline in het script). ⚠️ De
   pytest-metadata-guard mag NIET met `TEST_DATABASE_URL` op de cloud-database gericht
   worden: `tests/conftest.py` TRUNCATE't de testdatabase. ⚠️ En `alembic check` is hier
   — anders dan eerder gedacht — GEEN gelijkwaardige toets: zie de les onder
   "F1 — UITGEVOERD".
3. **`backend/.venv/bin/python scripts/gcp/f1_verificatie.py`** *(Code)* — GCS-upload +
   teruglezen via `GcsDocumentOpslag` tegen de echte bucket (testobject blijft staan:
   retentie verbiedt verwijderen — bedoeld) én KMS-wrap/unwrap-rondje + volledig
   envelope-pad via `KmsMasterKeyProvider` tegen de echte key. ADC vooraf:
   `gcloud auth application-default login`.
4. **Géén klantdata** (tranche 1): alleen schema + straks de TEST-administratie — de
   F5-poort verbiedt de rest; datamigratie tranche 2 komt ná F5 (stappenplan hieronder).

#### F1 — UITGEVOERD (2026-08-14)

- **F1.1/F1.2 (migratie + rollen):** `f1_migratie.sh` gedraaid via de Cloud SQL Auth Proxy —
  Alembic 0001→head schoon; slotcontrole in de cloud-database: **`alembic_version = 0047`**
  (= head), **rol `boekhouding_app` aanwezig**, metadata-guard groen
  (**68 modeltabellen == 68 cloud-tabellen**, platform+boekhouding).
- **LES metadata-guard: `alembic check` is NIET de gelijkwaardige toets** die het
  script-commentaar beloofde. Het vergelijkt óók type-representaties en index-declaraties
  en faalt op pre-existente model↔DDL-drift (modellen: `DateTime()`/`String`; migraties:
  `timestamptz`/`TEXT`; `ix_`-indexes alleen in migraties gedeclareerd). Bewijs dat dit
  géén cloud-signaal is: `alembic check` faalt tegen de lokale dev-database met een —
  na normalisatie van geheugenadressen — **byte-identieke** diff (129.639 tekens).
  `f1_migratie.sh` draait daarom nu de échte guard-test-vergelijking (tabelniveau) inline.
  Open punt (laag, nice-to-have): de model-type-drift ooit gelijktrekken zodat
  `alembic check`/autogenerate weer signaalwaarde krijgt — tot die tijd autogenerate-output
  altijd handmatig schiften (dat was al de werkwijze).
- **LES ADC-quota-project:** de eerste KMS-call faalde met 403 `SERVICE_DISABLED` tegen
  project `vastly-504108` — ADC droeg nog dat quota-project (attributie van de call, niet
  de resource). Fix: `gcloud auth application-default set-quota-project rlz-boekhouding`.
  GCS had er geen last van; KMS wel. Bij een toekomstige ADC-herlogin dit meteen meenemen.
- **F1.3/F1.4/F1.5 (verificatie GCS + KMS):** `f1_verificatie.py` GESLAAGD — testobject
  geüpload + byte-identiek teruggelezen via `GcsDocumentOpslag` tegen
  `gs://rlz-boekhouding-documenten` (object blijft staan — retentie verbiedt verwijderen,
  bedoeld); KMS-wrap/unwrap-rondje + volledig envelope-pad (`wrap_secret`/`unwrap_secret`)
  via `KmsMasterKeyProvider` tegen de echte `masterkey`. Bucketstaat read-only
  geverifieerd: **retentiebeleid 220.903.200 s (7 jaar) zichtbaar en effectief
  (2026-08-14), unlocked; versioning aan; public-access-prevention enforced; uniform
  bucket-level access aan.**
- **Bewust open (geen F1-blocker):** `WEBHOOK_HMAC_SECRET` en `ANTHROPIC_API_KEY` zijn
  containers zonder versie (HMAC volgt bij de F4-uitwisseling met vastgoed; de API-key bij
  het AI-gate-klikwerk). Tranche 1 = alleen schema — géén klantdata (F5-poort).

**F1-verificatie-eisen uit het draaiboek — alle vier aantoonbaar gedaan:** upgrade schoon ✓,
metadata-guard groen tegen dat schema ✓, testdocument geüpload + teruggelezen ✓,
retentiebeleid zichtbaar op de bucket ✓.

### F1.6-stappenplan datamigratie tranche 2 (ná F5 — de échte overzet)

Volgorde is bindend; elke stap heeft een expliciete verificatie vóór de volgende begint.

1. **Freeze bron:** lokale backend + dagelijkse run stoppen; geen boekingen/sync tijdens de
   overzet (RLZ zelf draait gewoon door — dat is de bron van waarheid, geen probleem).
2. **Dump + restore:** `pg_dump --format=custom` van de lokale `boekhouding` →
   `pg_restore` in de Cloud SQL-database (schema's staan er al via de Alembic-keten uit
   F1.1 — restore met `--data-only --disable-triggers`, of een verse database en
   full-restore; kies één smaak en verifieer de alembic_version).
3. **Documenten:** `gsutil -m rsync -r ./.data/documenten gs://<bucket>` — eerst met `-n`
   (droogloop) en de aantallen vergelijken met `boekhouding.document`.
4. **Masterkey-continuïteit (F1.3):** `scripts/herversleutel_masterkey.py --van lokaal
   --naar kms` — eerst dry-run (verwacht: 0 mislukt), dan `--uitvoeren`. De OUDE
   TOTP_MASTER_KEY pas weggooien nadat stap 6 groen is.
5. **Verificatie:** `scripts/gcp/datamigratie_check.py` met BRON=lokaal, DOEL=Cloud SQL —
   exit 0 vereist (rijtellingen + per-administratie-tellingen + alembic-versie).
6. **Functionele proef op doel:** kantoor-login (TOTP werkt = herversleuteling bewezen),
   RLZ-sync van één administratie (credential-store bewezen), één documentweergave uit de
   bucket (GCS-pad bewezen).
7. **Cutover:** Cloud Scheduler-jobs aan (F3), lokale cron uit — pas nadat de
   job-failure-alerting staat (F3.2, "geen gat tussen oud en nieuw vangnet").

## F2 — Services (backend, frontend, domein/https)

**Afhankelijk van:** F1 (DB + secrets moeten bestaan).

1. **Containerisatie: `backend/Dockerfile` GEBOUWD + lokaal geverifieerd (2026-08-13)** —
   Python 3.12-slim (pariteit met `make check-versions`), dependencies uit pyproject
   (aparte cache-laag via stdlib-tomllib), uvicorn zonder `--reload` op `$PORT`
   (Cloud Run-contract, exec/PID 1), non-root `appuser`; `.env`/tests/dev-data buiten het
   beeld (`backend/.dockerignore` — besluit 0012). Verificatie: docker build + container
   tegen de lokale Postgres → `/health` 200 mét migratie-guard-passage.
   - migratiestap in de deploy: **eerst `alembic upgrade head` als aparte job/stap, dán de
     nieuwe revisie live** — hetzelfde beeld, ander commando
     (`docker run <image> alembic upgrade head`, lokaal geverifieerd); de migratie-guard
     (fail-fast) blijft de vangrail die een vergeten upgrade tegenhoudt;
   - de in-process dev-lussen (extractie-wachtrij, webhook-afleveraar-poller) zijn in Cloud
     Run met scale-to-zero onbetrouwbaar → productie draait die functies als jobs (F3), de
     dev-lus blijft dev. NB de docker-compose-kop zegt "Docker niet geïnstalleerd op deze
     machine" — sinds 2026-08-13 is Docker er wél (29.x); compose blijft alleen-Postgres.
2. **Frontend-hosting — aanbeveling: same-origin, uit de backend-container.** De backend
   serveert de statische Vite-build (FastAPI StaticFiles + SPA-fallback; hashed assets
   immutable-cache, `index.html` no-cache). Onderbouwing: dev draait al same-origin via de
   Vite-proxy (`app/proxy_prefixes.py` is daar de bron van waarheid), dus productie wordt
   1-op-1 hetzelfde padmodel; CORS verdwijnt (`cors_allowed_origins` leeg), het
   refresh-cookie en de WebAuthn-origins worden één domein, en de PWA en de API delen één
   host. Alternatieven (aparte static-service, GCS+CDN) geven bij dit gebruikersaantal alleen
   extra bewegende delen. *(Besloten — beslispunt 4: same-origin; Code bouwt)*
3. **Domein + https (KRITIEK PAD) — besloten (beslispunt 3):** het domein
   **`administratiekantoornijenhuis.nl` is al in bezit** — geen registratie nodig. De app
   draait op het subdomein **`app.administratiekantoornijenhuis.nl`** (Cloud Run domain
   mapping + managed certificaat; DNS bij Peter); **de apex blijft vrij voor de
   kantoorwebsite**. **F2-bouwvereiste WebAuthn-config:** `webauthn_rp_id` = het
   **APEX-domein** `administratiekantoornijenhuis.nl` (níét het subdomein), zodat de
   passkeys op álle subdomeinen geldig blijven (RP ID mag een registrable suffix van de
   origin zijn — een later tweede subdomein breekt dan geen bestaande passkeys);
   `webauthn_origins` = `https://app.administratiekantoornijenhuis.nl`.
   **https ontgrendelt de échte passkeys** voor de accordeur-PWA (secure context);
   dev-stub blijft hard onwerkzaam (`ENVIRONMENT=production`). Ook de PWA-installatie bij
   klanten kan pas dan.
4. **Productie-config:** `ENVIRONMENT=production` (alle dev-fallback-guards bijten dan),
   cookies `Secure`, geen dev-stub, `webhook_afleveraar_interval`-lus uit (jobs doen het).
   Verifiëren dat het refresh-cookie het `Secure`-attribuut daadwerkelijk krijgt. *(Code)*

**Verificatie F2:** health-endpoint 200 via `https://<domein>`; kantoor-login incl. TOTP;
**een échte passkey-registratie + ontgrendeling op een telefoon** (geen stub, hét bewijs dat
de https-keten klopt); PDF-weergave uit de GCS-bucket; accordeur-PWA installeerbaar.

### F2-uitvoering (Code-kant GEBOUWD 2026-08-14)

Gebouwd + lokaal geverifieerd (18 nieuwe unit-tests, suite 1338 groen):

- **Same-origin-serving (F2.2):** `backend/app/static_frontend.py` — catch-all die als
  allerlaatste route registreert en de dev-proxy-regels 1-op-1 spiegelt
  (`frontend/proxyRegels.ts`): bestaand build-bestand serveren (hashed `/assets/*` een jaar
  immutable, al het niet-gehashte incl. `index.html`/PWA-manifest no-cache) → document-
  navigatie (Accept text/html + Sec-Fetch-Dest document) altijd de SPA → fetch naar een
  onbekend pad ónder een API-segment = JSON-404 (de "Unexpected token '<'"-bugklasse) →
  rest = SPA-fallback. API-segmenten komen uit `app/proxy_prefixes.py` (zelfde bron als de
  dev-proxy, berekend bij activatie — geen handmatig lijstje); traversal-guard
  (resolve + is_relative_to); activatie via `FRONTEND_DIST_MAP`, leeg = dev; gezette map
  zonder build = harde startup-weigering.
- **Cloud SQL-URL-compositie:** de F1-secrets zijn losse wachtwoorden, de app verwacht
  URL's — `app/config.py` composeert ze uit `CLOUD_SQL_VERBINDING` +
  `APP_DB_WACHTWOORD`/`DB_OWNER_WACHTWOORD` (unix-socket `?host=/cloudsql/...`, wachtwoord
  ge-URL-encodeerd, fail-closed bij verbinding-zonder-wachtwoord). Service krijgt alléén het
  app-wachtwoord, de migratie-job alléén het owner-wachtwoord (least privilege, F1-bindings).
- **Productie-gates (F2.4):** in-process webhook-afleveraar start niet bij
  `ENVIRONMENT=production` (Cloud Run-jobs leveren af, F3); Secure/httpOnly/SameSite op het
  refresh-cookie zat er al — nu ook per test geborgd.
- **Dockerfile multi-stage:** node:26-stage bouwt de Vite-build → `/app/static` in het
  Python 3.12-beeld; **build-context = repo-root** (`docker build -f backend/Dockerfile .`),
  `.dockerignore` verhuisd naar de root (allowlist; `verkenning/.env` valt buiten de context).
  Containerverificatie: /health 200 mét migratie-guard, index no-cache, asset immutable,
  `/bank/`-navigatie → SPA, `/bank/onzin`-fetch → JSON-404, geen `.env`/tests in het beeld.
- **`deploy.yml` ACTIEF (push naar main):** create-or-update (`gcloud run jobs deploy` +
  `gcloud run deploy`) — de éérste run maakt `rlz-migratie` en `rlz-backend` zelf aan, mét
  volledige runtime-config als code: SA's, Cloud SQL, secret-verwijzingen
  (APP_DB_PASSWORD/JWT_SECRET/TOTP_MASTER_KEY; WEBHOOK_HMAC_SECRET + ANTHROPIC_API_KEY
  bewust NIET gemount — geen versie, mounten zou de revisie-start breken),
  `WEBAUTHN_RP_ID`=apex + origin=app-subdomein (F2.3-bouwvereiste), CORS leeg,
  GCS-bucket + KMS-sleutel; concurrency-groep (nooit twee deploys door elkaar);
  volgorde migratie-job → revisie onverkort.
- **`scripts/gcp/f2_services.sh` (Peter):** idempotent — domein-verificatie-check
  (`gcloud domains verify` zo nodig), **allUsers-invoker op de service (stap 3, zie de
  run-#2-les hieronder)**, domain mapping `app.administratiekantoornijenhuis.nl`
  → `rlz-backend`, print de te zetten DNS-records (managed certificaat daarna automatisch).

**Deploy-run #1 GEFAALD + GEFIXT (2026-08-14).** Beeld bouwen/pushen slaagde; de
migratie-job stierf bij het LADEN van de revisiebestanden: 0001 deed de
APP_DB_PASSWORD-resolutie op module-niveau, en Alembic importeert álle revisies bij élke
upgrade — óók op head. **LES, bindend voor alle migratiebestanden: env-var-resolutie nooit
op module-niveau, altijd lazy bínnen upgrade()** — het bestand moet importeerbaar zijn in
elke omgeving, ook zonder de secrets van die specifieke migratie. Fix (commit a778636):
resolutie naar bínnen `upgrade()` (geen DDL-/gedragswijziging, alleen het import-moment —
enige revisie met dit patroon) + APP_DB_PASSWORD alsnog gemount in de migratie-job
(run-jobs@ had de accessor al, F1 1.4).

**Deploy-run #2: migratie-job + revisie-uitrol GROEN — service bestaat, maar antwoordt
403 (2026-08-14).** `--allow-unauthenticated` kon de allUsers-invoker niet zetten:
deploy@ heeft bewust alleen `run.developer` (F0 4.5) en die mist
`run.services.setIamPolicy`. **LES: gcloud waarschuwt hier slechts en de run blijft
GROEN — een geslaagde deploy-run bewijst dus níét dat de service publiek bereikbaar is;
/health-curl is de echte toets.** Structurele keuze: deploy@ NIET verbreden naar
run.admin (least privilege intact); de binding is service-niveau, éénmalig door het
owner-account (f2_services.sh stap 3, idempotent) en overleeft elke volgende revisie.

**F2 FORMEEL AF (2026-08-14).** De open punten zijn uitgevoerd: `f2_services.sh` gedraaid
(invoker + domain mapping), DNS gezet — live geverifieerd bij de F3-run (2026-08-14):
`/health` → **200** op de run.app-URL én op `https://app.administratiekantoornijenhuis.nl`
(managed certificaat actief).

### Bootstrap eerste Beheerder — élke verse omgeving kent dit moment

Een verse omgeving (lege database) heeft nog geen enkele gebruiker, dus de normale
Beheerder-only uitnodigingsflow kan nergens beginnen — dit bootstrap-moment hoort daarom
structureel bij elke nieuwe omgeving (cloud nu, een eventuele latere staging idem; lokaal
was het destijds `python -m app.cli bootstrap-beheerder`). Het cloud-recept
(**`backend/scripts/cloud_bootstrap_beheerder.py`**, hergebruikt de bestaande
uitnodigingsflow — patroon kliktest_accordeur_seed):

```bash
cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 &   # poort 5434, F1-conventie (rlz-sql2 sinds besluit 0021)
cd backend
APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
  .venv/bin/python scripts/cloud_bootstrap_beheerder.py --app-url https://<run.app-URL of app-domein>
```

- Maakt (idempotent) de eerste Beheerder aan — Peter, `Peter@ak-nijenhuis.nl` — en print de
  **activeerlink** (eenmalig token, 72 u). Peter stelt via die link **wachtwoord + TOTP
  opnieuw in**: de cloud is een verse omgeving, dat hoort zo (bewust geen hergebruik van
  lokale secrets). Er staat nooit een wachtwoord in de output.
- Herdraaien kan: link verlopen zonder activatie → verse link; Beheerder al actief → script
  doet niets. Failsafes: weigert zonder expliciete `APP_DATABASE_URL` én weigert poort 5433
  (lokale PG16) — het raakt dus nooit stil de dev-database.
- NB de datamigratie tranche 2 (F1.6) overschrijft deze verse cloud-gebruikerstabel met de
  lokale dump — dit bootstrap-account dient de F2/F3-verificatiefase; ná de overzet geldt
  gewoon het lokale accountbestand weer.

## F3 — Jobs (Scheduler → Cloud Run jobs)

**Afhankelijk van:** F2. De bestaande CLI-commando's zíjn de job-entrypoints — geen nieuwe code,
alleen verpakking.

| Job | Commando | Cadans (voorstel) |
|---|---|---|
| Nachtelijke sync | `python -m app.cli sync-alles` | dagelijks 03:00 |
| Reconciliaties (documenten + bank + omzet) | `python -m app.cli reconciliatie-alles` | dagelijks 06:30 |
| Webhook-afleveraar | `python -m app.cli webhook-afleveren` | elke 5 min |
| E-mail-intake (IMAP-fetch) | intake-CLI op de seam `app/intake/postvak.py` | elke 10 min |
| Accordeur-herinneringen (push/mail, toegevoegd 2026-08-15 — zie §F3.5) | `python -m app.cli accordeur-herinneringen` | dagelijks 09:00 |
| Nieuwe-facturen-bundelmelding (toegevoegd 2026-08-16 — zie §F3.6) | `python -m app.cli nieuwe-facturen-melden` | elke 10 min, 08:00–20:00 |

1. **Cloud Scheduler → Cloud Run jobs** onder `run-jobs@`; per job een eigen definitie zodat een
   hangende sync nooit de afleveraar blokkeert. *(Code)*
2. **Alerting is onderdeel van deze fase, geen nazorg:** de reconciliatie is een vangrail —
   lokaal zág je exit 1, in de cloud is een falende job stil. Cloud Monitoring-alert op
   job-failure/exit≠0 → e-mail naar kantoor. Zonder dit vinkje is F3 niet af. *(Code)*
3. **Rapportage-teller repareren vóór de alerting-cutover** (bevinding dagelijkse run 2026-08-14,
   BESLISSINGEN "Rapportage-bug reconciliatie"): acceptaties op een **uitgesloten** administratie
   tellen niet mee in de slotregel (`0 geaccepteerd` terwijl er GEACCEPTEERD-regels boven staan;
   per-administratieregel meldt `0 bevinding(en)` met bevindingen eronder). Lokaal las Peter het
   rapport zelf en zag hij de tegenspraak; in de cloud is de slotregel — samen met de exit-code —
   het enige dat een mens onder ogen krijgt, en een vangrail die zichzelf verkeerd samenvat is
   precies wat je in een stille omgeving niet wilt. Fix zit in `app/cli.py` (uitgesloten-tak van
   de documenten- en bank-variant), is klein en migratieloos. **Voorwaarde vóór punt 4** — het
   raakt de exit-code niet, dus het blokkeert F3 niet, maar de cutover naar het cloud-vangnet
   vindt niet plaats op een rapport dat "0 geaccepteerd" liegt. *(Code)*
4. **IMAP-intake activeren** (de gemarkeerde seam + `intake_imap_*`-settings):
   **besloten (beslispunt 5): de bestaande kantoor-mailprovider.** Voorwaarde vóór
   activering: **AVG-checklist D (DPA provider) afronden** — tot die check rond is blijft de
   .eml-upload gewoon het werkende kanaal, er valt niets om. *(Code activeert ná de
   DPA-check)*
5. **De lokale dagelijkse run vervalt** zodra de scheduler-jobs draaien en de alerting staat —
   niet eerder (geen gat tussen oud en nieuw vangnet).

**Verificatie F3:** elke job één keer handmatig getriggerd met zichtbaar resultaat in de logs;
een geforceerde failure (verkeerde env) levert daadwerkelijk een alertmail op.

### F3-uitvoering — UITGEVOERD (2026-08-14)

Verdeling conform F2-patroon: **job-definities = config-as-code in `deploy.yml`** (stap
"F3-jobs bijwerken": create-or-update op elke push, zelfde beeld als de service, per job een
eigen definitie — run-jobs@, alléén het app-DB-wachtwoord + KMS-masterkey-pad, CLI-commando
als `--command python --args=-m,app.cli,<commando>`); **`scripts/gcp/f3_jobs.sh`** (owner,
idempotent, describe-vóór-create) doet wat deploy@ niet mag/kan: alerting, IAM, scheduler,
secret-slot — plus een eenmalige job-bootstrap zodat F3 niet op de eerstvolgende push hoefde
te wachten (`F3_IMAGE_OVERRIDE`; de volgende deploy-run trekt de beelden weer gelijk).

- **F3.2 alerting stond EERST (opdracht 2026-08-14, geen gat tussen oud en nieuw vangnet):**
  notificatiekanaal `RLZ kantoor-e-mail (job-alerts)` → `Peter@ak-nijenhuis.nl`
  (channels/4756600988219015933) + policy `RLZ Cloud Run job-failure (F3.2)`
  (alertPolicies/18237971923707230913): metric
  `run.googleapis.com/job/completed_task_attempt_count` met `result=failed`, groepering per
  jobnaam, één failure is genoeg (duration 0s — vangrail, geen ruisfilter); dekt
  scheduler-runs én handmatige runs.
- **Jobs + cadans (draaiboektabel):** `rlz-sync` (03:00), `rlz-reconciliatie` (06:30),
  `rlz-webhook-afleveraar` (elke 5 min), `rlz-intake-imap` (elke 10 min, scheduler meteen
  GEPAUZEERD) — alle Europe/Amsterdam, Scheduler → `jobs/<naam>:run` met OAuth als run-jobs@
  (job-scoped `roles/run.invoker`). Secret-slot `INTAKE_IMAP_WACHTWOORD` staat klaar zónder
  versie + accessor voor run-jobs@; activatie (F3.4) = versie toevoegen, `INTAKE_IMAP_*`-envs
  aan de job hangen (deploy.yml), scheduler resumen — pas ná mailbox + app-wachtwoord +
  DPA-check (checklist D).
- **No-op-borging seed-testdata:** de cloud-DB draagt de credential-loze seed-administratie
  (SEED-PASSKEYTEST); `sync-alles` telde die als FOUT (exit 1) — de nachtelijke job zou
  permanent rood staan en de verse alerting elke nacht laten afgaan. Fix (wél een kleine
  gedragswijziging, bewust): `GeenRlzCredentials` = niet-onboarded → zichtbare
  OVERGESLAGEN-regel + aparte teller, exit 0 (zelfde patroon als webhook-afleveren); élke
  andere fout blijft exit 1. De reconciliaties/afleveraar hadden hun no-op-pad al
  (kortsluiten zonder geboekte documenten resp. "OVERGESLAGEN: toggle uit").
- **Verificatie per job (handmatige runs, 2026-08-14):** `rlz-sync` GROEN
  ("0/1 administraties gesynchroniseerd. (1 overgeslagen: geen credential geregistreerd)");
  `rlz-reconciliatie` GROEN (alle vier blokken OK, samenvatting zichtbaar);
  `rlz-webhook-afleveraar` GROEN ("OVERGESLAGEN: aflevering staat uit", exit 0);
  `rlz-intake-imap` FAALT BEWUST met de expliciete SEAM-melding (exit 1) — dat is meteen de
  geforceerde-failure-test voor de alerting (failed-metric geverifieerd). **Open vinkje:
  Peter bevestigt de alertmail-ontvangst** — pas dan is F3.2 aantoonbaar rond.
- **Lessen:** (1) lokaal gebouwde beelden zijn arm64 (Apple Silicon) en docker's
  containerd-store pusht een OCI-index mét attestation-manifest — Cloud Run weigert beide;
  lokale override-builds altijd `--platform linux/amd64 --provenance=false --sbom=false`
  (deploy.yml op de ubuntu-runner heeft dit niet nodig). (2) `gcloud --args -m,...` leest de
  `-m` als eigen flag — altijd de `--args=`-vorm. (3) de Monitoring-API heeft een eigen
  filtersyntax; idempotentie-checks op displayName lokaal matchen, niet via `--filter`.
- **Blijft open binnen F3:** ~~punt 3 (rapportage-teller)~~ — **GEFIXT + GETEST bij de
  F5-voorbereiding (2026-08-14):** de uitgesloten-tak van de documenten- én bank-variant
  telt geaccepteerde afwijkingen nu mee in een aparte teller ("X open, Y geaccepteerd —
  telt niet mee") en de slotregel benoemt de uitgesloten geaccepteerd-telling apart; de
  exit-code is ongewijzigd (besluit 0043). Tests:
  `tests/reconciliatie/test_rapportage_teller_cli.py` (4, incl. de voorheen ongedekte
  uitgesloten-tak). **De cutover-voorwaarde uit punt 3 is daarmee dicht.**
  ~~Punt 4 (IMAP-activatie ná DPA)~~ — **UITGEVOERD 2026-08-15, zie §F3.4-uitvoering.**
  Nog open: punt 5 (lokale dagelijkse run blijft het echte vangnet tot cutover F1.6
  stap 7, ná F5 — jobs draaien tot tranche 2 als infrastructuurbewijs/no-op).

### F3.4-uitvoering — live IMAP-intake geactiveerd (2026-08-15)

Voorwaarde was checklist D (mailprovider-DPA) — **rond 2026-08-15** (poortdossier punt 6:
Google Workspace; de geldende Workspace-DPA is de CDPA, zelfde gearchiveerde document als
poortpunt 1). Mailbox: **`facturen@ak-nijenhuis.nl`** (adreskeuze Peter 2026-08-15 —
bewust kort, niet het app-domein).

- **Code (dezelfde dag):** `ImapPostvakBron` is geen seam-stub meer maar de echte
  imaplib-koppeling (`app/intake/postvak.py`): SELECT INBOX → UID SEARCH **UNSEEN** →
  per bericht `BODY.PEEK[]` (ophalen zet géén gelezen-vlag) → verwerken → pas ná
  geslaagde verwerking `+FLAGS \Seen`. Crash tijdens verwerking = bericht blijft
  ongelezen = volgende run is de retry; dubbel ophalen kan nooit dubbel verwerken
  (`verwerk_eml` is idempotent op Message-ID — zelfde codepad als de .eml-upload).
  CLI `intake-postvak-verwerken` verwerkt als **systeem-actor** (bron `imap`), meldt
  per bericht VERWERKT/AL-VERWERKT, en een onparsebaar bericht wordt zichtbaar
  overgeslagen (gemarkeerd gelezen tegen een eeuwige retry-lus) mét exit 1 zodat de
  F3.2-alert bijt. Tests: `tests/intake/test_postvak_imap.py` (9).
- **Config-as-code (deploy.yml):** de `rlz-intake-imap`-job krijgt ná de job-lus
  `INTAKE_IMAP_HOST=imap.gmail.com`, `INTAKE_IMAP_POORT=993`,
  `INTAKE_IMAP_GEBRUIKER=facturen@ak-nijenhuis.nl`, `INTAKE_POSTVAK_ADRES=idem` +
  secret `INTAKE_IMAP_WACHTWOORD:latest` (aparte update-stap: de `--set-env-vars` in
  de lus vervangt de envset per push, de update zet ze er direct weer op).
- **Resterende klikken (volgorde bindend):** (1) Peter zet het app-wachtwoord van de
  mailbox in het slot: `gcloud secrets versions add INTAKE_IMAP_WACHTWOORD
  --data-file=-` (waarde via stdin, nooit als argument/in chat) — kan meteen, maar de
  job kan 'm pas gebruiken ná de eerstvolgende groene deploy; (2) scheduler-resume
  `rlz-intake-imap` + één handmatige groene run; (3) livetest: één echte factuur-PDF
  naar `facturen@ak-nijenhuis.nl`, verifiëren dat het bericht idempotent binnenkomt
  (AI-gate staat uit → verzamelbak/handmatige route is het verwachte pad).
  NB tot tranche 2 landt intake-mail in de **cloud-DB** (het kantoor werkt nog lokaal)
  — bewust: dit is het infrastructuurbewijs, de lokale .eml-upload blijft het
  werkkanaal tot de cutover.

### F3.5 — accordeur-herinneringen (toegevoegd 2026-08-15, berichten-bouwsteen)

Job `rlz-accordeur-herinneringen` (dagelijks 09:00 Europe/Amsterdam, mockup-besluit "dagelijkse
push 09:00 alleen bij >0 open") — canoniek: BESLISSINGEN "ACCORDEUR-NOTIFICATIES". Opzet volgt
F3 1-op-1: definitie in deploy.yml (job-lus + eigen update-stap voor de BERICHTEN_*/PUSH_*-envs
en -secrets, guarded zolang de slots ontbreken), IAM + scheduler in `scripts/gcp/f3_jobs.sh`
(scheduler start GEPAUZEERD), secret-slots + accessors + activatiestappen in
**`scripts/gcp/notificaties_infra.sh`** (owner, idempotent). Secrets:
`BERICHTEN_SMTP_WACHTWOORD` (Workspace-app-wachtwoord verzendadres — voorstel
berichten@ak-nijenhuis.nl, adreskeuze bij Peter), `PUSH_VAPID_PRIVATE_KEY` (alléén run-jobs@),
`PUSH_VAPID_PUBLIC_KEY` (ook run-backend@ — het subscribe-endpoint); waarden via stdin, nooit
als argument. De service krijgt in een eigen guarded stap dezelfde SMTP-config (uitnodigings-
mail) + de publieke sleutel. Idempotent per dag per accordeur (migratie 0050); 0 open werk =
exit 0 (F3-les). **Activatievolgorde:** notificaties_infra.sh → secret-versies → deploy → één
handmatige run + live-verificatie (één échte push op Peters iPhone-PWA + één échte mail) →
scheduler resume.

### F3.6 — nieuwe-facturen-bundelmelding (toegevoegd 2026-08-16, besluit Peter 16-08)

Job `rlz-nieuwe-facturen` (CLI `nieuwe-facturen-melden`, cadans `*/10 8-19 * * *`
Europe/Amsterdam) — canoniek: BESLISSINGEN "NIEUWE-FACTUREN-BUNDELMELDING". Bundelt per
accordeur het NIEUW klaargezette werk sinds de vorige melding tot één bericht ("Er staan N
facturen voor u klaar", N = totaal openstaand); idempotent per (accordeur, document) via
`platform.accordeur_nieuw_gemeld` (migratie 0054, nooit dubbel voor hetzelfde document);
stille uren 20:00–08:00 dubbel afgedwongen (cron dekt alleen de meldingsuren én de code
weigert zelf); volumerem; 0 nieuw = exit 0 (F3-les). Zelfde notificatie-config als F3.5
(eigen guarded update-stap in deploy.yml, zelfde secrets); scheduler start GEPAUZEERD —
resume samen met/na de F3.5-live-verificatie. De 09:00-herinnering blijft ongewijzigd en
telt integraal.

## F4 — Koppelvlak vastgoed (webhooks, tier-vlaggen)

> **Uitvoering: `docs/F4_ACTIVATIE_RUNBOOK.md` is het cutover-draaiboek (F4-voorbereiding
> 2026-08-14 — alles t/m de laatste knop staat klaar: secret-slots + bindings via
> `scripts/gcp/f4_koppelvlak.sh`, kanaaltest `scripts/f4_kanaaltest.py`, fail-closed
> geverifieerd; wat vastgoed aanlevert staat in Platform/OPEN_ITEMS "F4-cutover-pakket").**

**Afhankelijk van:** vastgoeds backend live op `api.vastly.software` (hun week 2/3) — **níét van
onze F0–F3**: webhooks versturen vereist alleen uitgaande https, dus dit kan desnoods al vanaf
de lokale backend. Zie het OPEN_ITEMS-webhook-item voor de afspraken. NB het ínkomende kanaal
(route A) draait wél op de cloud-service; end-to-end-livegang daarvan hangt aan de werk-DB
(zie de kanttekening "route A vóór tranche 2" in het runbook).

1. Vastgoed levert de publieke endpoint-URL (`POST /webhooks/rlz`) + het gedeelde
   HMAC-secret via het Secret Manager-patroon (besluit 0012). **Ontvangstvoorkeur:** secret
   als Secret Manager-verwijzing in `vastly-504108`, met `secretAccessor` voor onze
   `run-backend@`/`run-jobs@`-SA's (zelfde org, dus één bron, rotatie op één plek); zolang ons
   project er nog niet is: eenmalige veilige overdracht door Peter (heeft beide kanten) naar
   onze lokale `.env` — waarde nooit in chat/git.
2. Onze kant, **doorlooptijd ≤ 1 werkdag na ontvangst URL + secret**: `webhook_doel_url` +
   secret zetten → toggle aan (`make webhook-aflevering-aan`) → openstaande outbox-rijen
   worden alsnog geldig afgeleverd (tekenen-per-verzendpoging) → aflevering + dead-letter-pad
   controleren (`make webhook-redrive` bestaat voor herstel).
3. **Tier-vlaggen `afgeletterd_event_ingeschakeld`** per optie-2-administratie aanzetten
   (`make afgeletterd-event-aan`, schema_version 2.0) — **besloten (beslispunt 9): alleen
   Rubicon**; uitbreiding gebeurt per onboarding-moment van een nieuwe
   vastgoed-administratie, geen bulk-activatie.
4. De boekhoudmail-verhuizing aan vastgoed-kant raakt ons niet: routing loopt op de
   UBL-markering, nooit op afzender (geverifieerd, zie OPEN_ITEMS-antwoord 2026-08-12).

**Verificatie F4:** een echte `factuur_geboekt`-aflevering met 200 + verwerkt-bevestiging aan
vastgoed-kant; een `factuur_afgeletterd` 2.0-event op een tier-administratie idem.

## F5 — Go-live-gate (HARDE POORT vóór echte klantdata)

**Afhankelijk van:** F1–F3 af; de jurist-toets kan al die tijd parallel lopen.

Er gaat **geen enkele echte klantadministratie** de cloud in vóór deze poort dicht is
(besluit Peter 2026-08-12: de AVG-poort zit exact hier — testdata/eigen administratie mocht
eerder). De poort = **AVG-activatie-checklist stap 2, integraal**. **Het afvinkbare
bewijsdossier (per punt: bewijs/vindplaats + wie + status) is
`docs/avg/08-f5-poortdossier.md` — status dáár bijhouden**; de lijst hieronder blijft de
normtekst (stand 2026-08-14, F5-voorbereiding):

- [x] Google Cloud **CDPA** geaccepteerd, versie + datum gearchiveerd — **versie
      8 juni 2026**, gearchiveerd 2026-08-15
      (`docs/avg/nl-cloud-data-processing-addendum-customers.pdf`, dossier punt 1);
- [x] **regio-borging** aantoonbaar (alles `europe-west4` + Org Policy — describe-bewijs
      in het poortdossier, 2026-08-14);
- [x] **herzieningsmoment CLOUD Act** (besluit 0003) uitgevoerd: **platformbesluit 0021
      BESLOTEN (akkoord Peter 2026-08-14) + UITGEVOERD (2026-08-14)** —
      CMEK aan bij go-live (Cloud SQL herbouwd als `rlz-sql2` mét key `cmek-sql`,
      bucket-default-key `cmek-documenten`), client-side documentversleuteling alleen op
      klantverzoek; describe-bewijs in het poortdossier punt 3, uitvoeringsdetail in
      §F5-CMEK-uitvoering hieronder;
- [x] retentie/PITR-instellingen gedocumenteerd (technisch sinds F1; als poortbewijs
      vastgelegd in het dossier, describe 2026-08-14);
- [x] verwerkersovereenkomst **Exact Reeleezee** bevestigd + gearchiveerd — bevestiging
      Exact 2026-08-14, gearchiveerd 2026-08-15 (`docs/avg/Bevestiging versie RLZ.pdf`,
      dossier punt 5; restpunten EU-hosting + API-voorwaarden in checklist C);
- [x] IMAP-provider-DPA rond (checklist D, hoort bij F3) — **rond 2026-08-15**: Google
      Workspace, mailbox `facturen@ak-nijenhuis.nl`; de geldende Workspace-DPA is de
      **CDPA** (zelfde gearchiveerde document als het CDPA-punt hierboven — dekt
      Workspace expliciet; dossier punt 6);
- [x] verwerkingsregister §8/§9 bijgewerkt op de wérkelijke cloudconfiguratie
      (2026-08-14, incl. subverwerkers-checklist-consistentie + PDL in §0);
- [x] identiteit-eerst-check afgerond genoteerd (uit F0 — dossier punt 8).

Daarna, als sluitstuk: de **datamigratie-tranche 2** uit F1.6 (DB-dump/restore mét
masterkey-continuïteit, documenten-rsync, verificatiequery's) en de omschakeling van het
kantoor naar het productiedomein. De volgorde-koppeling (CMEK-herbouw vóór tranche 2 —
CMEK kan alleen bij instantie-aanmaak) is **uitgevoerd**: zie §F5-CMEK-uitvoering.

### F5-CMEK-uitvoering — UITGEVOERD (2026-08-14; besluit 0021, akkoord 2026-08-14)

Uitvoeringsplan §6 van het besluit, volgorde bindend, alles gedraaid met het
org-owner-account (idempotente scripts, F0-les):

1. **`scripts/gcp/f5_cmek.sh`**: keys `cmek-sql` + `cmek-documenten` op keyring `rlz`
   (jaarrotatie, **nooit destroy** — key weg = data + backups definitief weg);
   service-agent-bindings (⚠️ twee lessen: de Cloud SQL-service-agent bestaat pas na
   `gcloud beta services identity create` — fout nooit wegslikken, binding kort retryen
   op IAM-propagatie; de GCS-agent provisioneer je mét binding in één stap via
   `gcloud storage service-agent --authorize-cmek`); **`rlz-sql2`** aangemaakt met het
   f1_data.sh-recept + `--disk-encryption-key` (PG16, REGIONAL, PITR 7 d, backups 02:00);
   postgres-wachtwoord uit het bestaande secret (secrets zijn instantie-onafhankelijk —
   niets geroteerd); bucket-default-key gezet (nieuwe objecten CMEK; alleen het oude
   F1-testobject blijft Google-default — geen klantdata, gedocumenteerd).
2. **Configflips** (de 4 plekken uit besluit 0021 §3.3): `deploy.yml` `CLOUD_SQL`,
   `f1_migratie.sh`, `f3_jobs.sh`, docstrings `backend/scripts/cloud_*.py`
   (+ `test_config_cloud_sql.py` cosmetisch).
3. **Volledige F1-herverificatie GROEN (2026-08-14):** Alembic 0001→head = **0049**
   via de Auth Proxy, metadata-guard **69 == 69** tabellen, rol `boekhouding_app`
   aanwezig; `f1_verificatie.py` geslaagd (GCS byte-identiek + KMS-envelope-pad);
   nieuw testobject draagt `kms_key` = `cmek-documenten/cryptoKeyVersions/1`.
4. **Service + 5 jobs omgehangen** naar `rlz-sql2` (eenmalige `gcloud run … update`,
   zelfde waarden als de deploy.yml-flip — de volgende push-deploy convergeert);
   `/health` **200** op run.app én `https://app.administratiekantoornijenhuis.nl`;
   handmatige `rlz-sync`-run exit 0 ("0/0 administraties" — verse database, bedoeld).
5. **Bootstrap-Beheerder opnieuw** (verse database): activeerlink uitgegeven aan Peter
   (72 u; wachtwoord + TOTP opnieuw — verse omgeving, bedoeld). ⚠️ De eerdere
   iPhone-passkey van de accordeur-seed is een **wees** geworden (de publieke sleutel
   stond in de oude database): accordeur-seed + passkey-herregistratie opnieuw ná Peters
   activeerklik (het seed-script eist een actieve Beheerder als actor — bewuste failsafe).
   **Seed opnieuw gedraaid 2026-08-15** (Beheerder was actief; proxy op `--gcloud-auth`,
   ADC verlopen): test-administratie + accordeur-account staan in `rlz-sql2`, verse
   activeerlink (72 u) aan Peter — open: passkey-herregistratie op de iPhone.
6. **Oude `rlz-sql` verwijderd** ná groene verificatie (`scripts/gcp/f5_cmek_opruimen.sh`,
   guards: rlz-sql2 RUNNABLE + CMEK + service aantoonbaar omgehangen). Motivatie
   (uitzondering op "niets verwijderen" expliciet gemaakt): eigen lege infra-testinstantie
   — uitsluitend schema + bootstrap/seed, géén klantdata, geen extern systeem; alles
   herproduceerbaar met bestaande scripts; laten staan = ~€2/dag + een verwarrende
   niet-CMEK-instantie. Instantienaam ~1 week gereserveerd bij Google.

## F6 — default compute service account afknijpen (hygiëne-run 2026-08-16, klikwerk Peter)

Google's automatisch aangemaakte default compute SA
(`652591056217-compute@developer.gserviceaccount.com`) heeft standaard projectbreed
**Editor** en wordt door onze uitrol nergens gebruikt (alles draait op run-backend@/
run-jobs@/deploy@ — F0-least-privilege). Draaiboek: **`scripts/gcp/f6_default_compute_sa.sh`**
(owner, idempotent — describe-vóór-mutatie): (1) verifieert fail-closed dat geen Cloud
Run-service/-job op het default-SA draait, (2) haalt roles/editor eraf, (3) schakelt het SA
uit (omkeerbaar met `enable`; verwijderen bewust niet). Mocht ooit iets stilletjes op het
default-SA leunen (bv. een legacy Cloud Build-pad), dan faalt dat vanaf dan zichtbaar —
terugweg is één enable-commando + een eigen SA voor die dienst.

## Kritieke pad & parallelsporen

```
F0 ──► F1 ──► F2 ──┬──► F3 (jobs + alerting) ──┐
                   └──► (verificaties)          ├──► F5-poort ──► klantdata-migratie ──► GO-LIVE
AVG-jurist-toets (stap 0 + 2) ── parallel ──────┘
F4 (webhooks vastgoed) ── onafhankelijk spoor, kan zelfs vóór F0 (lokale backend volstaat)
```

- **Kritiek pad:** F0 → F1 → F2 → F5. Binnen F2 is **domein + https** de langste pol
  (DNS/certificaat) — vroeg starten.
- **Parallel kan:** de jurist-toets van het AVG-pakket (loopt al, ter toetsing sinds
  2026-08-11) naast álle infra-fases; F3 naast de F2-verificaties; F4 volledig los (vastgoeds
  week-3-moment hangt niet op onze uitrol).
- **Bewust NIET parallel:** klantdata-migratie vóór de F5-poort — dat is precies wat de poort
  verbiedt.

## Beslispunten — ALLE 10 BESLIST (Peter, 2026-08-12)

| # | Beslispunt | Fase | Besluit |
|---|---|---|---|
| 1 | Projectnaam/-ID | F0 | **`rlz-boekhouding`** (ID-cijfersuffix alleen bij botsing) |
| 2 | Owner-account (identiteit-eerst: juridische entiteit) | F0 | **het org-beheeraccount van de PDL Powerhouse-org** — zelfde account als `vastly-504108` |
| 3 | Productiedomein | F2 | **`app.administratiekantoornijenhuis.nl`** — domein al in bezit (geen registratie); apex vrij voor de website; **WebAuthn RP ID = het apex-domein** (F2-bouwvereiste, zie F2.3) |
| 4 | Frontend-hosting | F2 | **same-origin uit de backend-container** (onderbouwing in F2.2) |
| 5 | IMAP-provider boekhoudmail (+ DPA, checklist D) | F3 | **bestaande kantoor-mailprovider = Google Workspace**; DPA-check rond 2026-08-15 (= CDPA), mailbox `facturen@ak-nijenhuis.nl`, geactiveerd — §F3.4-uitvoering |
| 6 | CMEK / client-side documentversleuteling (besluit 0003-herziening) | F5 | **memo bij F5; lean-lijn: CMEK aan bij go-live, client-side versleuteling alleen op klantverzoek** — uitkomst als platformbesluit |
| 7 | Bucket-retentie locked/unlocked | F1 | **unlocked** starten; heroverwegen bij het WORM-export-besluit |
| 8 | Masterkey: Cloud KMS meteen (contractnorm §2b) of Secret Manager eerst | F1 | **Cloud KMS meteen**; masterkey-continuïteit expliciet in het migratiescript |
| 9 | Optie-2-administraties voor `afgeletterd_event_ingeschakeld` | F4 | **alleen Rubicon**; uitbreiding per onboarding-moment |
| 10 | Deploy-pipeline | F0 | **GitHub Actions + WIF naar vastgoed-patroon**, repo-conditie op `pnijenhuis-dotcom/rlz-boekingsmodule` |
