# Bouwplan RLZ Boekingsmodule

> Fasering vastgesteld 3 juli 2026. Elke fase heeft een definition of done en eindigt met een
> werkende, door Peter te testen oplevering. Geen fase 2 vóór fase 1 in gebruik is.

## Fase 1 — Fundament + inkoopflow (de kern)

**Doel:** één klant-administratie end-to-end: PDF/UBL erin → gecontroleerd → geboekt in RLZ.

Backend:
1. Repo-setup: FastAPI + PostgreSQL (schema's `platform` + `boekhouding`), Docker Compose voor
   lokale dev, Alembic-migraties, pytest. Deploy-doel: **Cloud Run** (europe-west4) + gedeelde
   **Cloud SQL** + **Secret Manager** + **Cloud Storage** (documenten) + **Cloud Scheduler/jobs**
   (achtergrondwerk) — conform koppelcontract v1.2. Dev→prod pariteit via container.
2. Platform-basis: gebruikers (uitnodiging + TOTP-2FA), rollen, administratie-register,
   credential-store (envelope encryption via Secret Manager/KMS), append-only audit log in het
   **uniforme `audit_event`-schema** (v1.3), **PII gescheiden van financiële data**
   (pseudonimiseerbaar), **Row-Level Security** op administratie-scope (`SET LOCAL` per transactie).
   Migratie 0002 + endpoints + tests staan (2026-07-06). **Credential-store gebouwd (2026-07-08)
   — zie punt 4 hieronder.** **Besloten (Peter, 2026-07-06) — eerste taken volgende sessie:**
   - **Bootstrap-CLI voor de allereerste Beheerder — gebouwd (2026-07-08).** Uitnodigen is
     Beheerder-only, dus zonder dit was er geen manier om de eerste Beheerder aan te maken zonder
     rechtstreeks in de database te schrijven (kip-ei). **CLI-only** (`python -m app.cli
     bootstrap-beheerder` / `make bootstrap-beheerder`) — géén seed-logica in migraties: een
     Alembic-migratie draait bij elke deploy/omgeving en is niet de juiste plek voor een
     eenmalige, omgevingsspecifieke actie met een echte e-mail/naam als invoer. Idempotent:
     weigert zodra er al een Beheerder bestaat, schrijft een eigen audit_event (migratie 0002's
     rol-trigger vuurt alleen op UPDATE, niet op deze eerste INSERT).
   - **Refresh-tokens revocable gemaakt (2026-07-08)** — migratie 0003 (`refresh_token`-tabel,
     hash-only) i.p.v. stateless JWT: rotatie bij elke `token/vernieuwen`-aanroep, hergebruik van
     een al-geroteerd token trekt alle sessies van die gebruiker in, levering als
     httpOnly+Secure+SameSite=Strict-cookie (nooit meer in de JSON-respons) **+ audit_event voor
     login (geslaagd/mislukt), TOTP-fouten en refresh-hergebruik** (nu alleen
     rol-/scope-wijzigingen, bewust beperkt gehouden bij het bouwen van de auth-basis). IP wordt
     uitsluitend als anomalie-metadata in het audit-record gezet, nooit als auth-anker (conform
     Auth-0010-b). Zie Platform/OPEN_ITEMS.md voor het volledige antwoord aan vastgoed; MFA-cadans/
     passkeys/step-up (punten 2–4 van Auth-0010-b) volgen in fase 3, zoals daar voorgesteld.
   - **E-mailverzending van uitnodigingen via een Cloud Run-job** (nu retourneert de
     uitnodig-endpoint het token synchroon in de API-respons, geen SMTP-integratie).
   - **Wachtwoordbeleid** (sterkte-eisen boven de minimumlengte van 12 tekens) bewust uitgesteld
     — geen actie vóór een volgende sessie het oppakt.
3. RLZ-client: Basic auth per administratie, `{adminId}`-routing, throttling/retry, PUT+GUID-
   conventie, acties (17/19/138), `$expand`-helpers. Integratietests tegen BLOW (read-only).
4. **Sync-laag per administratie — Ledgers/TaxRates/Vendors/Projects gebouwd (2026-07-08).**
   Migratie 0005: gedeelde `platform.grootboekrekening` (koppelcontract §2c v1.8, RLZ-sync is
   enige schrijver, vastgoed leest read-only via GRANT SELECT + RLS) + niet-gedeelde
   `boekhouding.{taxrate,vendor,project}_cache` (eigen controlescherm — crediteurkeuze, btw-code,
   projectkoppeling; `brondata`-JSONB als vangnet naast de wél-geverifieerde velden, want
   TaxRate's officiële resource-model-documentatie gaf herhaaldelijk een serverfout). Generieke
   upsert + `verdwenen_uit_bron_op`-markering (nooit hard verwijderen; terugkeer = NULL, conform
   §2c) — één implementatie voor alle vier de bronnen (`app/sync/service.py`).
   - **On-demand trigger** `POST /administraties/{id}/sync/ledgers` — nu met gebruikers-auth +
     administratie-scope (zelfde dependency als document-upload); het service-to-service
     platform-JWT voor vastgoed's eigen ververs-knop komt bij de Cloud-uitrol.
   - **Nachtelijke sync** is nu een aanroepbaar commando (`make sync-alles` /
     `python -m app.cli sync-alles`) — de **Cloud Scheduler-koppeling zelf volgt bij de
     GCP-uitrol** (fase 5-platformverbetering), dit commando is exact het werk-item dat de
     Cloud Run-job straks aanroept. Eén administratie zonder werkende credentials stopt de rest
     van de run niet.
   - **Credentials tijdelijk via .env-logins** (`app/rlz/credentials.py`, prefix per
     RLZ-adminId — Universal/TESTADMIN/Rubicon; BLOw ontbreekt bewust, het volledige adminId
     staat nergens in de repo) — vervalt zodra de credential-store er is (fase 1, punt 2 hierboven
     legde het fundament, de RLZ-credential-koppeling zelf is nog niet gedaan).
   - **Aanname, nog te bevestigen door vastgoed:** de GRANT aan hun leesrol gaat naar
     `vastgoed_app` (naar analogie van `boekhouding_app`) — zie Platform/OPEN_ITEMS.md. Lokaal is
     de GRANT voorwaardelijk (rol bestaat hier niet), dus geen migratiefout, maar wél een
     bevestiging nodig vóór de éérste keer dat vastgoed dit in de gedeelde Cloud SQL verwacht.
   - JournalEntries (historie → boekingsgeheugen-seed) blijft open voor een volgende sessie —
     hoort inhoudelijk bij het boekingsgeheugen (fase-vervolg), niet bij deze read-only
     referentiedata-sync.
   - **Credential-store + koppel-flow gebouwd (2026-07-08).** Migratie 0006:
     `platform.rlz_credential` (webservice-login per administratie, wachtwoord versleuteld at
     rest via hetzelfde envelope-patroon als `totp_secret` — geen tweede
     encryptie-implementatie) + `platform.rlz_rechten_probe` (laatste rechten-check). Geen RLS
     op beide tabellen — platformbrede beheertabellen, toegang via applicatielaag (Beheerder-only
     endpoints voor `rlz_credential`; administratie-scope voor de probe), niet via
     administratie-scoping zoals `grootboekrekening`. `app/rlz/credentials.py` is nu
     **store-first met .env-fallback**: bestaande `.env`-logins blijven werken zolang niet elke
     administratie in de store zit. Eenmalig CLI-importcommando
     (`make import-env-credentials BEHEERDER_ID=<uuid>`) zet de bekende `.env`-logins
     (RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_) de store in — slaat BLOw en Kempen Facilities
     bewust over (hun volledige RLZ-adminId staat nergens in de repo, geen aanname/gok).
     Beheer-endpoints: `PUT`/`GET /administraties/{id}/rlz-credential` (Beheerder-only,
     wachtwoord write-only — komt nooit in een response of audit_event terug, alleen de
     username en het feit van de wijziging).
   - **Rechten-probe** `POST /administraties/{id}/rlz-check` (administratie-scope, geen
     Beheerder-only — hoort bij het aansluiten van een klant, geen platformbeheer): read-only
     probes over `Administrations` (root-client, top-level endpoint), `Ledgers`, `TaxRates`,
     `Vendors`, `Customers`, `Projects`, `SalesInvoices`, `PurchaseInvoices`, `JournalEntries`,
     `PaymentAccounts` (administratie-gescoped), rapport (endpoint → `ok`/HTTP-statuscode)
     opgeslagen per administratie + audit_event. **Voor de mockup-onboarding (fase-vervolg,
     frontend nog niet gebouwd):** dit rapport is bedoeld als directe input voor het
     koppel-scherm bij het aansluiten van een nieuwe administratie — een tabel met per endpoint
     een groen vinkje (ok) of een rode kruis+statuscode, plus een herkenbare hint bij bekende
     patronen (bv. "alle documentendpoints 403 → waarschijnlijk ontbrekend
     'documenten'-rechtenprofiel op de webservice-login, zie verkenning/16_DOORBELASTING_KEMPEN.md
     §KEMPEN_*-ervaring"). Een "niets wijzigen"-vinkje/leesrechten-profiel-indicator kan uit
     `is_totaalrekening`/afwezigheid van schrijfrechten-probes worden afgeleid; dat scherm zelf
     bouwen is fase-vervolg.
   - **Overbrugging vastgoed:** Rubicons grootboekrekeningen live gesynchroniseerd (read-only,
     `RUBICON_*`-login, 403 rekeningen — zie
     `tests/integration/test_sync_ledgers_read_integration.py::test_sync_ledgers_tegen_rubicon`,
     reproduceerbaar via `make test-read-integration`) en geëxporteerd naar
     `Platform/uitwisseling/rubicon_ledgers_2026-07-08.json` (alleen rekeningschema — code/naam/
     soort/GUID's, geen andere data) zodat vastgoed tegen echte data kan bouwen vóór de gedeelde
     Cloud SQL er is. Zie `Platform/uitwisseling/README.md`.
5. **Document-pipeline (statusmachine) — fundament gebouwd (2026-07-08).** Migratie 0004:
   `boekhouding.document` (client-UUID, RLS conform besluit 0004 — `administratie_id` mag NULL
   voor de niet_toegewezen-verzamelbak, zelfde patroon als `audit_event`) + `document_gebeurtenis`
   (append-only tijdlijn, voedt de mockup-tijdlijn). Statusmachine als expliciete, geteste graaf
   (`app/documenten/statusmachine.py`, alle paren getest): ontvangen → extractie_bezig →
   te_controleren → klaar_om_te_boeken → geboekt, zijtakken vraag_open/afgewezen/boeken_mislukt/
   niet_toegewezen; elke overgang schrijft zowel document_gebeurtenis als audit_event, ongeldige
   overgangen zijn een harde fout. Upload-endpoint (PDF/XML, max-size, administratie-scope
   afgedwongen) + storage-interface (lokaal FS in dev, Cloud Storage-klaar). Sha256-duplicaatcheck
   bij binnenkomst (per administratie) zet `mogelijk_duplicaat_van_id` — een losse vlag, geen
   aparte status (mockup: chip "Mogelijk duplicaat van ... — beoordelen", het document doorloopt
   gewoon de normale flow). UBL/XML wordt al deterministisch geparst naar veldvoorstellen
   (`app/documenten/ubl.py`); PDF krijgt nog geen extractie — de AI-extractiestap zelf
   (regeltelling vs totaal, duplicaatcheck via eigen query op Entity+Reference(30 tekens)+bedrag —
   RLZ's actie 138 is bewezen zonder bruikbaar signaal, besluit 0013 — deterministisch client-GUID,
   IBAN-wissel, voorstel uit het boekingsgeheugen) is een stub-hook (`_start_extractie` in
   `app/documenten/service.py`) en landt in een fase-vervolg. **Bekend openstaand punt:** elke
   statusovergang vereist nu een menselijke actor_id (geen systeem-actor-sentinel) — voldoende
   zolang extractie synchroon binnen dezelfde request draait, maar een latere écht-asynchrone
   extractieworker (queue/Cloud Tasks) heeft hier een oplossing voor nodig vóór hij gebouwd wordt.
   Multi-factuur-PDF-splitsing en e-mail-intake blijven fase 3.
6. **Boeken — gebouwd (2026-07-09).** Migratie 0008: `boekhouding.boekvoorstel`/`boekvoorstel_regel`
   (het controlescherm-voorstel per document, RLS via het onderliggende document — zelfde
   subquery-patroon als `document_gebeurtenis`). `app/documenten/checks.py`: de drie harde checks
   (duplicaatquery Entity+Reference(30 tekens)+bedrag — eigen client-GUID telt niet als duplicaat
   bij een retry; regeltelling vs factuurtotaal; verplichte velden), altijd alle drie getoond,
   nooit stil overgeslagen. `app/documenten/boeken.py`: `boek_document()` herhaalt de checks
   server-side (nooit de client-kant vertrouwen), dan de failsafes, dan de echte RLZ-schrijfacties
   — deterministisch client-GUID (`app/documenten/rlz_ids.py`, UUIDv5 op document-id, óók voor de
   PDF-bijlage) → PUT PurchaseInvoice → **PUT** `/Uploads/{uploadId}` (geverifieerd: RLZ wil hier
   expliciet PUT, geen POST — zie verkenning/api-verkenning.md) → actie 17 → boekstuknummer terug
   (RLZ's `ReceiptNumber`, geverifieerd al gezet bij de PUT, niet pas na boeken). Status →
   `geboekt` met tijdlijn+audit; een RLZ-fout zet `boeken_mislukt` met de échte foutmelding, een
   volgende poging is idempotent (zelfde client-GUID's).
   - **Drie failsafes (CLAUDE.md-taak 2.4):** (a) `platform.administratie.boeken_ingeschakeld`
     (per-administratie opt-in, default UIT) + `platform.boeken_instelling` (globale kill switch,
     singleton) — nieuwe `app/beheer/`-module, Beheerder-only endpoints, beide moeten aan staan.
     (b) Reconciliatiejob (`app/documenten/reconciliatie.py`, `make reconciliatie` /
     `python -m app.cli reconciliatie`): vergelijkt elk lokaal `geboekt` document met de
     werkelijke RLZ-staat (bestaat, Status=2, bedrag, boekstuknummer), rapporteert afwijkingen;
     één kapotte administratie stopt de rest niet (zelfde patroon als `sync_alle_administraties`).
     (c) Volumerem: `settings.max_boekingen_per_dag_per_administratie` (default 20), telt op de
     al bestaande `document_gebeurtenis`-rijen van vandaag, geen eigen tabel nodig.
   - **Alleen de test-administratie heeft boeken aanstaan** — voor alle andere blijft de toggle op
     zijn default (uit) totdat een Beheerder 'm expliciet aanzet.
7. **Webhook-stub "factuur geboekt" — gebouwd (2026-07-09).** Migratie 0009:
   `boekhouding.webhook_uitgaand` (outbox, `afgeleverd_op` blijft NULL). `app/documenten/webhook.py`
   bouwt en ondertekent de payload (HMAC-SHA256 over timestamp+nonce+payload, koppelcontract §3) —
   RLZ-GUID, project-GUID, datum, bedragen per regel, GB-code, leverancier, referentie, adminId.
   Aflevering (HTTP-push naar vastgoed) is bewust nog niet gebouwd — dat is een fase-vervolg, zodra
   ook de "hoort dit bij een vastgoed-administratie"-filtering nodig wordt.

Frontend (Vite + React, design tokens uit mockup — die blijven leidend, ook voor onderstaande
UI-eisen):
8. Login + 2FA, werkvoorraad (klantenlijst → klantpagina), controlescherm (PDF-viewer + voorstel +
   correcties) — **kopgegevens + boekingsregels + harde checks + boekactie gebouwd (2026-07-09)**,
   zie punt 6 en `frontend/src/document/BoekvoorstelPanel.tsx` + `SearchableCombobox.tsx` (zoekbare,
   gevirtualiseerde, debounced combobox conform de UI-eisen hieronder) — vragenworkflow,
   afwijzen-met-reden, verzamelbak "Niet toegewezen", instellingen-lite
   (administratie koppelen, gebruikers, eigenaren), audit log, globaal zoeken (boekingen + audit)
   blijven open voor een volgende sessie.
   - **Openstaand (2026-07-09): het instellingen-scherm is de échte UI voor de drie toggles.**
     De mockup's administraties-tab (project verplicht / boeken-toggle / globale kill switch) is
     nog niet gebouwd — tot die tijd zijn `make boeken-aan`/`boeken-uit`/`boeken-status`
     (`app/cli.py`, hergebruikt `app.beheer.service`) en de `PUT`-endpoints zelf (curl/Postman)
     het enige beheerpad. Die CLI-commando's blijven ook daarna nuttig (server-toegang zonder
     ingelogde sessie, bv. bij een incident), maar worden geen vervanging voor het scherm.
   **UI-eisen (vastgesteld 2026-07-08), van toepassing op elk GB-/project-/entiteitveld:**
   - Zoekbare combobox met toetsenbordnavigatie (pijltjes, Enter, Esc) i.p.v. een kale `<select>`
     — deze velden hebben per administratie honderden tot duizenden opties (bv. Universal: 145
     projecten), typen-om-te-filteren is dan geen "nice to have" maar een harde eis.
   - Gevirtualiseerde lijsten voor elke lijstweergave die uit een sync-cache render (GB-schema,
     projectenlijst, entiteitenlijst) — anders schaalt het scherm niet mee met een groeiende
     administratie.
   - Debounced zoeken op de lokale sync-cache (geen request per toetsaanslag; de sync-laag zelf
     is al lokaal, dus dit is puur UI-throttling, geen netwerklatentie-mitigatie).
   - Aria-labels op elk van deze velden (en op de gevirtualiseerde lijst-items) — dit scherm is
     de kern van de dagelijkse workflow, toegankelijkheid is hier geen achteraf-toevoeging.

**Definition of done fase 1:** Peter verwerkt een echte stapel inkoopfacturen van één klant
(BLOW of Kempen) sneller dan nu in RLZ zelf, met audit trail en zonder één handmatige RLZ-handeling.

## Fase 2 — Omzetboekingen + bank

- Omzetflow: kassarapport-herkenning (profiel per administratie, periode uit rapport,
  duplicaat per periode, plausibiliteit), SalesInvoice + gekoppelde kostprijsmemoriaal als één
  transactie, systeemdebiteur per administratie. Pilot: BLOW Margerapport.
- Bankmodule: PaymentAccounts/Statements lezen, voorstel-volgorde (exacte match → gedeeltelijk →
  vaste regels → RLZ-voorstel → handmatig), auto-afletteren bij naam+factuurnr+bedrag,
  regel-leren (3×), BankMutationDirectBookings schrijven. PoC afletteren (acties 15/16) eerst.
- Bulk-boeken, archief-weergave, tijdlijn per boeking. **Let op (koppelcontract v1.7, §7.3):**
  actie 19 (Correct) zet een RLZ-document terug naar concept i.p.v. een apart creditdocument —
  archief/tijdlijn kunnen dus geen zichtbaar stornering-/credit-spoor uit RLZ's documentstatus
  lezen. Het correctiespoor ("wanneer gestorneerd, door wie, waarom") moet uit ons eigen
  `audit_event` komen. Nu nog niet uitwerken — check bij het bouwen van dit scherm.

## Fase 3 — Klantportaal + intake

- Autorisatiemodule: accordeurs, sequentiële lagen met drempels, "Ter accordering"-flow,
  goedkeuren via e-maillink, PWA (installeerbaar, push: direct + dagelijks 09:00).
- Platform-auth-uitbreiding (besluit 0010, akkoord 2026-07-05): auth-niveau per rol (TOTP
  verplicht voor kantoor/beheer/accordeur; mobiele token-flow + biometrie + Sign in with Apple
  voor huurder-accounts t.b.v. vastgoed native app) + push als platform-service met topics per
  module — moet af vóór vastgoed-fase 3.
- E-mail intake (centraal adres, IMAP/Graph), multi-factuur-PDF-splitsing, verzamelbak-leren.
- Rollenmodel volledig (module-zichtbaarheid per rol).

## Fase 4 — Projectenmodule

- Projects-write PoC, projectregister per klant (archief-toggle), projectdetail (werksoorten,
  weekanalyse, m²-voortgang, meerwerk-tab, integrale marge + dekkingscontrole), offerte-ontleding
  → budgetversies (offerte/opdracht-status), projectcode-generatie, OVH-project bij inrichting,
  dagelijkse signalering naar werkvoorraad.
- Pilot: Universal Steigerbouw (60 actieve projecten).

## Fase 5 — Integraties & schaal

- Vastgoedmodule-webhook live (HMAC + timestamp/nonce + schema_version; integratietest tegen de
  aparte RLZ-test-administratie, testboekingen storneren — koppelcontract v1.3 §7.3).
- MI-dashboard-module (read-only, Financials-endpoints + read-models).
- Peppol-intake, hardening (rate-limit-gedrag, backup/restore, monitoring), uitrol alle klanten.

## Platform-verbeteringen (vastgesteld 2026-07-04, mogelijk gemaakt door GCP-keuze)

| # | Verbetering | Waarom | Fase |
|---|-------------|--------|------|
| 1 | Boeken via **Cloud Tasks-queue** (idempotency-key = taaknaam, retry/backoff, dead-letter → foutstatus werkvoorraad) | robuustste "niets verdwijnt stil"; dubbel boeken technisch onmogelijk | **1** |
| 2 | **Staging-omgeving** (scale-to-zero, eigen kleine Cloud SQL + bucket); alles eerst tegen testadministratie | dev→prod zonder risico op klantdata | **1** |
| 3 | Audit log-export naar Cloud Storage met **bucket retention lock (WORM)** | audit log aantoonbaar onvervalsbaar (kantoor-waardig) | 2 |
| 4 | **Cloud DLP** als BSN-vangnet (NL-BSN-detectie + maskering vóór indexering) | machinale waarborg op het AVG-hard-principe | 2 |
| 5 | **Extractiekwaliteit-meting**: elke menselijke correctie = meetpunt per veld; drempels voor auto-boeken op data i.p.v. gevoel | objectieve basis voor auto-boeken per leverancier | 2 |
| 6 | **Signed URLs** (kortlevend, per gebruiker) voor factuur-PDF's in klant-app en zoekresultaten | documenten nooit publiek benaderbaar | 3 |
| 7 | **Cloud Monitoring-alerts**: RLZ-foutpercentage, sync-achterstand, signaleringsjob niet gedraaid, dead-letter niet leeg, budget | stille degradatie bestaat niet meer | 2 |
| 8 | **Secret-rotatie** RLZ-logins (halfjaarlijks, gelogd) | boekhoudtoegang verdient een rotatieproces | 5 |

Bewust afgewezen: Kubernetes (overkill), microservices binnen de module (één service + jobs
volstaat), multi-region (cross-region backup volstaat), AlloyDB (alleen MI-groeipad).

## Openstaande verificaties (inplannen in de fase waar ze nodig zijn)

| # | Wat | Fase |
|---|-----|------|
| 1 | Rate limits exact | 1 |
| 2 | Afletteren via acties 15/16 + QuickPaymentSelections | 2 |
| 3 | Projects-write (PUT via Customers-route) | 4 |
| 4 | CodeEventSubscriptions (RLZ-events) | 5 |
| 5 | Waarborg-GB per vastgoed-administratie | 5 |
