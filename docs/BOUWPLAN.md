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
   Migratie 0002 + endpoints + tests staan (2026-07-06). **Besloten (Peter, 2026-07-06) — eerste
   taken volgende sessie:**
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
4. Sync-laag per administratie: Ledgers, TaxRates, Vendors, Projects, JournalEntries (historie →
   boekingsgeheugen-seed). Cache met verversing bij gebruik.
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
6. Boeken: PurchaseInvoice + PDF-bijlage + Book-actie, idempotency-key, audit, RLZ-boekstuk terug.
7. Webhook-stub "factuur geboekt" (koppelcontract §3) — payload klaar, aflevering configureerbaar.

Frontend (Vite + React, design tokens uit mockup — die blijven leidend, ook voor onderstaande
UI-eisen):
8. Login + 2FA, werkvoorraad (klantenlijst → klantpagina), controlescherm (PDF-viewer + voorstel +
   correcties), vragenworkflow, afwijzen-met-reden, verzamelbak "Niet toegewezen", instellingen-lite
   (administratie koppelen, gebruikers, eigenaren), audit log, globaal zoeken (boekingen + audit).
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
