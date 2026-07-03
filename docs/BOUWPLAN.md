# Bouwplan RLZ Boekingsmodule

> Fasering vastgesteld 3 juli 2026. Elke fase heeft een definition of done en eindigt met een
> werkende, door Peter te testen oplevering. Geen fase 2 vóór fase 1 in gebruik is.

## Fase 1 — Fundament + inkoopflow (de kern)

**Doel:** één klant-administratie end-to-end: PDF/UBL erin → gecontroleerd → geboekt in RLZ.

Backend:
1. Repo-setup: FastAPI + PostgreSQL (schema's `platform` + `boekhouding`), Docker Compose,
   Alembic-migraties, pytest.
2. Platform-basis: gebruikers (uitnodiging + TOTP-2FA), rollen, administratie-register,
   credential-store (envelope encryption), append-only audit log.
3. RLZ-client: Basic auth per administratie, `{adminId}`-routing, throttling/retry, PUT+GUID-
   conventie, acties (17/19/138), `$expand`-helpers. Integratietests tegen BLOW (read-only).
4. Sync-laag per administratie: Ledgers, TaxRates, Vendors, Projects, JournalEntries (historie →
   boekingsgeheugen-seed). Cache met verversing bij gebruik.
5. Document-pipeline (statusmachine): ontvangen → gesplitst → geëxtraheerd (AI + deterministische
   checks: regeltelling vs totaal, duplicaat via actie 138 + eigen hash, IBAN-wissel) → voorstel
   (geheugen: historie + correcties, recency-gewogen) → te controleren → klaar → geboekt/afgewezen/
   vraag open/fout. Upload via UI; e-mail intake = fase 3.
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
- Bulk-boeken, archief-weergave, tijdlijn per boeking.

## Fase 3 — Klantportaal + intake

- Autorisatiemodule: accordeurs, sequentiële lagen met drempels, "Ter accordering"-flow,
  goedkeuren via e-maillink, PWA (installeerbaar, push: direct + dagelijks 09:00).
- E-mail intake (centraal adres, IMAP/Graph), multi-factuur-PDF-splitsing, verzamelbak-leren.
- Rollenmodel volledig (module-zichtbaarheid per rol).

## Fase 4 — Projectenmodule

- Projects-write PoC, projectregister per klant (archief-toggle), projectdetail (werksoorten,
  weekanalyse, m²-voortgang, meerwerk-tab, integrale marge + dekkingscontrole), offerte-ontleding
  → budgetversies (offerte/opdracht-status), projectcode-generatie, OVH-project bij inrichting,
  dagelijkse signalering naar werkvoorraad.
- Pilot: Universal Steigerbouw (60 actieve projecten).

## Fase 5 — Integraties & schaal

- Vastgoedmodule-webhook live (integratietest met VGB-TEST-documenten, koppelcontract §7).
- MI-dashboard-module (read-only, Financials-endpoints + read-models).
- Peppol-intake, hardening (rate-limit-gedrag, backup/restore, monitoring), uitrol alle klanten.

## Openstaande verificaties (inplannen in de fase waar ze nodig zijn)

| # | Wat | Fase |
|---|-----|------|
| 1 | Rate limits exact | 1 |
| 2 | Afletteren via acties 15/16 + QuickPaymentSelections | 2 |
| 3 | Projects-write (PUT via Customers-route) | 4 |
| 4 | CodeEventSubscriptions (RLZ-events) | 5 |
| 5 | Waarborg-GB per vastgoed-administratie | 5 |
