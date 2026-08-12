# GCP-uitroldraaiboek — RLZ Boekingsmodule

> **Status: alle 10 beslispunten BESLIST (Peter 2026-08-12) — F0 klaar om te draaien.**
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
   - `jobs@` — runtime van de Cloud Run-jobs (zelfde grondhouding, plus wat de sync/afleveraar
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
- Secret- en bucket-bindings voor `run-backend@`/`jobs@` zijn bewust **niet** in F0 opgenomen:
  die zijn per-resource en horen bij F1 (de secrets en de bucket bestaan dan pas).
- Na afloop print het script de **projectnummer- en WIF-provider-resourcenamen**; daarmee
  bouwt Code de GitHub Actions-testworkflow voor de dummy-push (de laatste F0-verificatie).

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
     masterkey-continuïteit uit punt 3. Draaiboekje + verificatiequery's (rijtellingen,
     documenttellingen per administratie) als los script. *(Code)*

**Verificatie F1:** `alembic upgrade head` schoon tegen de nieuwe instantie; de
metadata-guard-test groen tegen dat schema; een testdocument geüpload + teruggelezen via de
GCS-implementatie; retentiebeleid zichtbaar op de bucket.

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

## F3 — Jobs (Scheduler → Cloud Run jobs)

**Afhankelijk van:** F2. De bestaande CLI-commando's zíjn de job-entrypoints — geen nieuwe code,
alleen verpakking.

| Job | Commando | Cadans (voorstel) |
|---|---|---|
| Nachtelijke sync | `python -m app.cli sync-alles` | dagelijks 03:00 |
| Reconciliaties (documenten + bank + omzet) | `python -m app.cli reconciliatie-alles` | dagelijks 06:30 |
| Webhook-afleveraar | `python -m app.cli webhook-afleveren` | elke 5 min |
| E-mail-intake (IMAP-fetch) | intake-CLI op de seam `app/intake/postvak.py` | elke 10 min |

1. **Cloud Scheduler → Cloud Run jobs** onder `jobs@`; per job een eigen definitie zodat een
   hangende sync nooit de afleveraar blokkeert. *(Code)*
2. **Alerting is onderdeel van deze fase, geen nazorg:** de reconciliatie is een vangrail —
   lokaal zág je exit 1, in de cloud is een falende job stil. Cloud Monitoring-alert op
   job-failure/exit≠0 → e-mail naar kantoor. Zonder dit vinkje is F3 niet af. *(Code)*
3. **IMAP-intake activeren** (de gemarkeerde seam + `intake_imap_*`-settings):
   **besloten (beslispunt 5): de bestaande kantoor-mailprovider.** Voorwaarde vóór
   activering: **AVG-checklist D (DPA provider) afronden** — tot die check rond is blijft de
   .eml-upload gewoon het werkende kanaal, er valt niets om. *(Code activeert ná de
   DPA-check)*
4. **De lokale dagelijkse run vervalt** zodra de scheduler-jobs draaien en de alerting staat —
   niet eerder (geen gat tussen oud en nieuw vangnet).

**Verificatie F3:** elke job één keer handmatig getriggerd met zichtbaar resultaat in de logs;
een geforceerde failure (verkeerde env) levert daadwerkelijk een alertmail op.

## F4 — Koppelvlak vastgoed (webhooks, tier-vlaggen)

**Afhankelijk van:** vastgoeds backend live op `api.vastly.software` (hun week 2/3) — **níét van
onze F0–F3**: webhooks versturen vereist alleen uitgaande https, dus dit kan desnoods al vanaf
de lokale backend. Zie het OPEN_ITEMS-webhook-item voor de afspraken.

1. Vastgoed levert de publieke endpoint-URL (`POST /webhooks/rlz`) + het gedeelde
   HMAC-secret via het Secret Manager-patroon (besluit 0012). **Ontvangstvoorkeur:** secret
   als Secret Manager-verwijzing in `vastly-504108`, met `secretAccessor` voor onze
   `run-backend@`/`jobs@`-SA's (zelfde org, dus één bron, rotatie op één plek); zolang ons
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
eerder). De poort = **AVG-activatie-checklist stap 2, integraal**:

- [ ] Google Cloud **CDPA** geaccepteerd, versie + datum gearchiveerd;
- [ ] **regio-borging** aantoonbaar (alles `europe-west4` + Org Policy — staat sinds F0);
- [ ] **herzieningsmoment CLOUD Act** (besluit 0003) uitgevoerd: **CMEK en/of client-side
      documentversleuteling beoordeeld, uitkomst als platformbesluit vastgelegd**
      *(besloten — beslispunt 6: het memo wordt bij F5 voorbereid, met als lean-lijn
      **CMEK aan bij go-live** en client-side documentversleuteling alleen op klantverzoek;
      het memo formaliseert dit als platformbesluit)*;
- [ ] retentie/PITR-instellingen gedocumenteerd (staat technisch sinds F1);
- [ ] verwerkersovereenkomst **Exact Reeleezee** bevestigd + gearchiveerd;
- [ ] IMAP-provider-DPA rond (checklist D, hoort bij F3);
- [ ] verwerkingsregister §8/§9 bijgewerkt op de wérkelijke cloudconfiguratie;
- [ ] identiteit-eerst-check afgerond genoteerd (uit F0).

Daarna, als sluitstuk: de **datamigratie-tranche 2** uit F1.6 (DB-dump/restore mét
masterkey-continuïteit, documenten-rsync, verificatiequery's) en de omschakeling van het
kantoor naar het productiedomein.

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
| 5 | IMAP-provider boekhoudmail (+ DPA, checklist D) | F3 | **bestaande kantoor-mailprovider**; DPA-check (checklist D) vóór activering |
| 6 | CMEK / client-side documentversleuteling (besluit 0003-herziening) | F5 | **memo bij F5; lean-lijn: CMEK aan bij go-live, client-side versleuteling alleen op klantverzoek** — uitkomst als platformbesluit |
| 7 | Bucket-retentie locked/unlocked | F1 | **unlocked** starten; heroverwegen bij het WORM-export-besluit |
| 8 | Masterkey: Cloud KMS meteen (contractnorm §2b) of Secret Manager eerst | F1 | **Cloud KMS meteen**; masterkey-continuïteit expliciet in het migratiescript |
| 9 | Optie-2-administraties voor `afgeletterd_event_ingeschakeld` | F4 | **alleen Rubicon**; uitbreiding per onboarding-moment |
| 10 | Deploy-pipeline | F0 | **GitHub Actions + WIF naar vastgoed-patroon**, repo-conditie op `pnijenhuis-dotcom/rlz-boekingsmodule` |
