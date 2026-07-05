# KOPPELCONTRACT (definitief, v1.5) — Vastgoedbeheer-module ↔ RLZ-boekingsmodule

> Status: **vastgesteld 3 juli 2026**, sindsdien bijgewerkt (zie versiehistorie).
> Dit document is leidend voor beide projecten. Wijzigingen alleen in overleg, met versienummer.

| Versie | Datum | Wijziging | Bron |
|---|---|---|---|
| v1.0 | 2026-07-03 | Eerste vastgesteld koppelcontract (rolverdeling, sleutels, inbound/outbound) | beide |
| v1.1 | 2026-07-03 | §2b platform-fundament toegevoegd | vastgoed |
| v1.2 | 2026-07-04 | Host VPS/Docker Compose → Google Cloud europe-west4 | vastgoed |
| v1.3 | 2026-07-04 | Webhook HMAC + replay-bescherming (§3); integratietest naar aparte RLZ-test-administratie i.p.v. verwijderen (§7.3); `schema_version` in push-payload (§3) | vastgoed |
| v1.4 | 2026-07-04 | Consistentiefix: credential-store-masterkey nu correct via Secret Manager/KMS (§2b); boekingsmodule-aanvullingen uit doc 13/14-akkoord opgenomen in §2b (Cloud Storage-documentretentie, Scheduler+jobs, CLOUD Act-inbreng) | RLZ |
| v1.5 | 2026-07-04 | Eigenaarschap platform-fundament = RLZ-project; interface-wijzigingen alleen met akkoord van beide projecten | beide (besluit Peter) |

## 1. Rolverdeling (hard)

| | Vastgoedbeheer-module | RLZ-boekingsmodule |
|---|---|---|
| **Is** | Operationele subadministratie vastgoed | Verwerkingslaag boekhouding (alle klanten) |
| **Schrijft in RLZ** | Huurfacturen (`SalesInvoices`), waarborg-memoriaal (`ManualJournals`) | Inkoopboekingen, omzetboekingen, bankverwerking |
| **Leest uit RLZ** | Niets rechtstreeks (krijgt push, zie §3) | Alles wat de eigen flow nodig heeft |
| **Muteert documenten van de ander** | **Nooit** | **Nooit** |

Reeleezee blijft de boekhoudkundige bron van waarheid. Geen van beide modules verwijdert iets in RLZ.

## 2. Gedeelde sleutels & conventies

1. **Pand = RLZ-project.** Mapping: `object.reeleezee_project_id` = RLZ-project-GUID (niet de Name).
   BAG-id blijft uitsluitend in de vastgoedmodule; RLZ-projectnamen bevatten géén BAG-id.
2. **`Reference`-prefix per bron:** alle documenten die de vastgoedmodule in RLZ aanmaakt dragen
   `Reference` beginnend met `VGB-`. De boekingsmodule herkent deze en toont ze uitsluitend als
   reeds geboekt (nooit als werkvoorraad).
3. **Idempotentie:** RLZ-document-id's zijn client-gegenereerde GUID's bij PUT. De vastgoedmodule
   genereert ze deterministisch (UUIDv5 van bijv. contract+periode) zodat retries geen duplicaten
   geven. Inbound gebruikt de vastgoedmodule de RLZ-factuur-GUID als `reeleezee_factuur_id UNIQUE`.
4. **Per entiteit één RLZ-administratie** (~8), elk met eigen webservice-login; credentials
   versleuteld in de credential-store van het gezamenlijke platform (geen tweede opslag).

## 2b. Platform-fundament — antwoord op 09-v2 §6 (BESLOTEN 2026-07-03)

Beslissing "gedeeld fundament, losse modules" wordt **overgenomen en bevestigd**. Concreet:

- **Stack boekingsmodule = identiek aan vastgoedmodule: Vite + React + FastAPI + PostgreSQL.**
  Bewuste gelijkschakeling: Python past ook het best bij onze AI-extractie-pipeline, en één stack
  maakt het gedeelde fundament triviaal in plaats van een verzoeningsproject. Er hoeft niets
  verzoend te worden.
- **Host — GEWIJZIGD 2026-07-04 (over te nemen door de RLZ-boekingsmodule):** eerdere afspraak
  "kleine VPS (EU) + Docker Compose" vervalt, vervangen door **Google Cloud, regio `europe-west4`
  (Nederland)**:
  - **API:** Cloud Run (serverless containers, ingebouwde load balancer, autoscaling +
    scale-to-zero); elke module eigen Cloud Run-service, apart deploybaar. Geen monoliet.
  - **Database:** gedeelde Cloud SQL for PostgreSQL (HA + automatische back-ups + PITR), met
    AlloyDB als groeipad voor de analytische MI-module (fase 3); schema `platform` + schema per
    module (`vastgoed`, `boekhouding`, `mi`) — ongewijzigd t.o.v. het schema-per-module-model.
  - **Secrets:** Google Secret Manager (vervangt masterkey-in-`.env`/host-secret-store).
  - CLOUD Act bewust geaccepteerd 2026-07-04; herzieningsmoment vóór productie-go-live met echte
    huurderdata. Zie `01_ARCHITECTUUR.md` (platform-fundament) voor de volledige toelichting.
  - **Aanvullingen boekingsmodule (v1.4, geaccordeerd in doc 13/14):** documentopslag (facturen,
    contracten, energielabels — 7 jaar bewaarplicht) in **Cloud Storage** europe-west4 met
    retentiebeleid; achtergrondwerk beide modules via **Cloud Scheduler + Cloud Run jobs**;
    het CLOUD Act-herzieningsmoment beoordeelt de mitigaties **CMEK / client-side
    documentversleuteling** (inbreng boekingsmodule: klantboekhouddata van tientallen klanten).
- **Identiteit (gedeeld):** platform-auth-service — accounts via e-mailuitnodiging (eenmalige link,
  72 u geldig), wachtwoord + **TOTP-2FA verplicht**, rolmodel (beheerder / module-rollen /
  klant-accordeurs met administratie-scope). Sessies via JWT met korte levensduur. Elke module
  consumeert dezelfde identiteit; rolwijzigingen in het gedeelde audit log.
- **Credential-store (gedeeld, v1.4):** versleutelde tabel in PostgreSQL (envelope encryption;
  data-keys gewrapt via KMS, master-secret in **Google Secret Manager** — nooit in `.env`, git of
  code). Eén plek voor alle RLZ-webservice-logins (~8 vastgoed-entiteiten + kantoorklanten).
  Modules vragen credentials op via het platform, nooit eigen kopieën.
- **Register (gedeeld):** één PostgreSQL-cluster; schema `platform` (gebruikers, rollen,
  entiteiten/administraties incl. RLZ-adminId's, audit log) + eigen schema per module
  (`boekhouding`, `vastgoed`, straks `mi`). Gedeelde data alleen in `platform` — geen drift.
- **MI-dashboard** wordt de derde module op ditzelfde fundament (na v1 boekingsmodule): leest RLZ
  `Financials`-endpoints + de read-models van beide modules, schrijft niets.
- **Eigenaarschap (BESLOTEN 2026-07-04):** het RLZ-boekingsmoduleproject is eigenaar en beheerder
  van het gedeelde platform-fundament (auth, credential-store, entiteitenregister, IAM).
  Wijzigingen aan gedeelde interfaces (auth-contract, credential-store-API, register-schema)
  vereisen akkoord van beide projecten. Het fundament leeft achter een duidelijke modulegrens,
  zodat latere afsplitsing mogelijk blijft.

## 3. Inbound naar vastgoedmodule: push, geen polling

De boekingsmodule pusht bij elke inkoopfactuur met status **geboekt** in een vastgoed-administratie
een bericht (webhook/queue) met per factuurregel:

```
reeleezee_factuur_id  (RLZ-GUID, uniek)     datum            (factuurdatum)
reeleezee_project_id  (GUID of null)        bedrag_excl / btw_bedrag / bedrag_incl
grootboek_guid + grootboek_omschrijving     leverancier      (genormaliseerde naam + RLZ-relatie-id)
omschrijving          (regeltekst)          administratie_id (RLZ-adminId)
schema_version        (koppelvlak-versie van deze payload)
```

- **`schema_version`:** het pushformaat draagt een schemaversie zodat toekomstige
  koppelvlak-wijzigingen detecteerbaar en onderhandelbaar zijn (ontvanger kan onbekende versies
  weigeren of expliciet negeren, i.p.v. stilzwijgend verkeerd parsen).
- Regels **zonder project** worden wél meegeleverd (project null) → mens-bevestigt-pad vastgoedmodule.
- De mapping grootboek → **kostensoort** (onderhoud/GWE/…) is eigendom van de vastgoedmodule.
- Herlevering op verzoek mogelijk (replay op `reeleezee_factuur_id`), idempotent aan ontvangstzijde.
- **BESLOTEN 2026-07-04 (afspraak voor beide projecten):** het "factuur geboekt"-bericht wordt
  **HMAC-signed** (key uit Secret Manager) én krijgt **replay-bescherming**: elk bericht draagt een
  timestamp + unieke nonce; het ontvangst-endpoint weigert berichten buiten een venster van
  ~5 minuten of met een eerder geziene nonce. Zie `14_ANTWOORD_AAN_RLZ.md` §3.4.

## 4. Outbound vastgoedmodule → RLZ (rechtstreeks via API)

- **Huurfacturen als `SalesInvoices`**: regels met eigen grootboek-GUID + btw-code per regel
  (btw loopt dan correct in de aangifte mee), boeken via `POST .../Actions {Type:17}`,
  optioneel PDF via `/Uploads`. ✅ werkend bewezen.
- **Waarborgsom als `ManualJournals`** (balansboeking, saldo 0, dagboekreferentie verplicht,
  `CreditOrDebit` 1=debet/2=credit). ✅ werkend bewezen. Waarborg-grootboekrekening per
  administratie inventariseren vóór eerste boeking (standaardschema heeft alleen activa-variant).
- Grootboekmapping: `GET {adminId}/Ledgers` per administratie; mapping-tabel `grootboek_code` ↔
  Ledger-GUID als configuratie per entiteit — nooit hardcoden, schema's verschillen.
- Auth: Basic Auth per administratie; login = volledige toegang (geen scopes) — behandelen als
  boekhoudtoegang.

## 5. Projectaanmaak nieuwe panden

De boekingsmodule biedt projectaanmaak met codegeneratie en RLZ-sync; levert `reeleezee_project_id`
synchroon terug. De vastgoedmodule mag ook zelf aanmaken (PUT + client-GUID) — maar dan met
naamconventie van de betreffende administratie en melding aan de boekingsmodule (cache-refresh).

## 6. Openstaande verificaties (eigenaar: boekingsmodule, vóór koppelingsfase vastgoed)

1. Schrijfroute `Projects` (PUT via `Customers/{id}/Projects`) — PoC.
2. Rate limits exact (docs "REST API limits") — bepaalt batchgedrag outbound.
3. `CodeEventSubscriptions` (RLZ-events) — nice-to-have naast push.
4. Waarborg-grootboek per vastgoed-administratie.

## 7. Fasering

1. Boekingsmodule bouwt v1 (na collega-review mockup) — incl. `VGB-`-filter en webhook-stub.
2. Vastgoedmodule rondt verhuur-pilot af; koppeling daarna.
3. Integratietest draait tegen een **aparte RLZ-test-administratie** (niet tegen een
   productie-entiteit), testdocumenten met `VGB-TEST-` prefix. Testboekingen worden na afloop
   **gestorneerd/teruggeboekt, niet hard verwijderd** — conform de hard rule "niets verwijderen in
   andere systemen" en de audittrail-eisen van een boekhoudsysteem.
4. Bloxs blijft schaduwdraaien tot fase 3 bewezen; niets wordt verwijderd.
