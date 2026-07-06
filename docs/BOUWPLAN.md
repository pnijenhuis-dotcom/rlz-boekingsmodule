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
   - **Bootstrap-CLI voor de allereerste Beheerder.** Uitnodigen is Beheerder-only, dus er is nu
     geen manier om de eerste Beheerder aan te maken zonder rechtstreeks in de database te
     schrijven (kip-ei). Wordt een los commando (migratie-seed of eenmalig CLI-script), niet via
     de uitnodigingsflow.
   - **Refresh-tokens revocable maken** (aparte tabel i.p.v. stateless JWT — nu geen server-side
     "log alle sessies uit" mogelijk) **+ audit_event ook voor login/activatie** (nu alleen
     rol-/scope-wijzigingen, bewust beperkt gehouden bij het bouwen van de auth-basis).
   - **E-mailverzending van uitnodigingen via een Cloud Run-job** (nu retourneert de
     uitnodig-endpoint het token synchroon in de API-respons, geen SMTP-integratie).
   - **Wachtwoordbeleid** (sterkte-eisen boven de minimumlengte van 12 tekens) bewust uitgesteld
     — geen actie vóór een volgende sessie het oppakt.
3. RLZ-client: Basic auth per administratie, `{adminId}`-routing, throttling/retry, PUT+GUID-
   conventie, acties (17/19/138), `$expand`-helpers. Integratietests tegen BLOW (read-only).
4. Sync-laag per administratie: Ledgers, TaxRates, Vendors, Projects, JournalEntries (historie →
   boekingsgeheugen-seed). Cache met verversing bij gebruik.
5. Document-pipeline (statusmachine): ontvangen → gesplitst → geëxtraheerd (AI + deterministische
   checks: regeltelling vs totaal, duplicaatcheck via eigen query op Entity+Reference(30
   tekens)+bedrag — RLZ's actie 138 is bewezen zonder bruikbaar signaal, besluit 0013 — +
   deterministisch client-GUID, IBAN-wissel) → voorstel (geheugen: historie + correcties,
   recency-gewogen) → te controleren → klaar → geboekt/afgewezen/vraag open/fout. Upload via UI;
   e-mail intake = fase 3.
6. Boeken: PurchaseInvoice + PDF-bijlage + Book-actie, idempotency-key, audit, RLZ-boekstuk terug.
7. Webhook-stub "factuur geboekt" (koppelcontract §3) — payload klaar, aflevering configureerbaar.

Frontend (Vite + React, design tokens uit mockup):
8. Login + 2FA, werkvoorraad (klantenlijst → klantpagina), controlescherm (PDF-viewer + voorstel +
   correcties), vragenworkflow, afwijzen-met-reden, verzamelbak "Niet toegewezen", instellingen-lite
   (administratie koppelen, gebruikers, eigenaren), audit log, globaal zoeken (boekingen + audit).

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
