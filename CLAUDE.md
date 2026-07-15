# RLZ Boekingsmodule — Administratiekantoor Nijenhuis

Multi-tenant web-app waarmee het kantoor inkoopfacturen, omzetboekingen en bankmutaties verwerkt
in Reeleezee (RLZ) voor tientallen klant-administraties. AI-extractie + mens-in-de-lus controle.

## Kernprincipes (hard, niet onderhandelbaar)

1. **RLZ is de boekhoudkundige bron van waarheid.** Deze app is een verwerkingslaag, nooit een
   tweede waarheid. Lokale caches zijn caches.
2. **Code voor cijfers, AI voor taal, mens voor de knop op geld.** Geen LLM in geldberekeningen;
   AI alleen voor extractie/segmentatie, altijd met deterministische checks eroverheen.
3. **Nooit data verwijderen in RLZ of andere externe systemen.** Correcties via RLZ-acties (19
   Correct); verwijderen doet alleen een mens in RLZ zelf.
4. **Niets verdwijnt stil.** Afwijzen = verplichte reden + status in werkvoorraad. API-fout =
   zichtbare foutstatus + retry. Append-only audit log op elke handeling (wie/wat/wanneer/oud→nieuw).
5. **Idempotentie overal**: client-GUID's (UUIDv5 waar deterministisch mogelijk) + eigen
   duplicaatquery op Entity+Reference+bedrag vóór elke PUT, idempotency-keys op boekacties.
   **RLZ's eigen actie 138 (duplicaatcheck) is bewezen zonder bruikbaar signaal** (drie
   experimenten, verkenning/api-verkenning.md "Actie 138") — RLZ blokkeert duplicaten ook niet
   zelf bij boeken (17). Niet gebruiken; idempotentie is volledig onze verantwoordelijkheid.
6. **Secrets** in `.env`/secret-store, nooit in code of git. RLZ-credentials server-side versleuteld
   (envelope encryption, master key buiten de DB).

## Stack & platform (besloten, koppelcontract v1.1 §2b)

- **Vite + React** (frontend) · **FastAPI** (backend) · **PostgreSQL** — identiek aan de
  vastgoedmodule (apart project, zelfde platform-fundament).
- **Host (v1.2, 2026-07-04): Google Cloud `europe-west4`.** Deze module = eigen **Cloud
  Run**-service; database = gedeelde **Cloud SQL for PostgreSQL** (HA + PITR), schema
  `boekhouding`; secrets via **Google Secret Manager** (credential-store: envelope encryption met
  KMS-gewrapte data-keys); documenten (7 jaar bewaarplicht) in **Cloud Storage** met retentie;
  achtergrondwerk (signalering, sync, e-mail-intake) via **Cloud Scheduler + Cloud Run jobs**.
  Docker Compose = lokale dev. CLOUD Act geaccepteerd; herzieningsmoment vóór go-live (inbreng:
  CMEK/client-side documentversleuteling voor klantboekhouddata).
- DB-schema's: `platform` (gebruikers, rollen, administraties, credential-store, audit log),
  `boekhouding` (deze module). Vastgoedmodule krijgt `vastgoed`, MI-dashboard later `mi`.
- Auth: e-mailuitnodiging (eenmalige link 72 u) + wachtwoord + **TOTP-2FA verplicht**, JWT-sessies.
  Rollen: Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur (scope: eigen administratie).
- **Autorisatie (hard, bevestigd 2026-07-06):** klanten-scope per medewerker via koppeltabel
  gebruiker↔administraties, afgedwongen door RLS (DB-niveau) + server-side checks — geen scope =
  geen data, ook niet via bugs in de app-laag. Rol- en scope-wijzigingen exclusief door de
  Beheerder-rol (initieel alleen Peter), server-side gecontroleerd. **Niemand kan zijn eigen rol
  of scope muteren, ook een Beheerder niet** (tweede beheerder aanwijzen kan alleen door een
  andere beheerder). Elke rol-/scope-wijziging in het append-only audit_event.
- **Platformbrede afspraken (koppelcontract v1.3 + 14_ANTWOORD_AAN_RLZ, bindend):**
  uniform `audit_event`-schema (timestamptz, actor=platform-user-id, module, tabel+record-id,
  actie, oude+nieuwe waarde JSON, correlatie-id) als bron voor de WORM-export; **PII gescheiden
  van financiële data** (AVG-verwijderverzoek = pseudonimiseren ná relatie-einde + 7 jaar, nooit
  hard verwijderen); **Row-Level Security** op entiteit/administratie als DB-niveau
  scopingpatroon (scope-context via `SET LOCAL` per transactie — nooit sessie-breed i.v.m.
  connection pooling); webhook-push met HMAC + timestamp + nonce (replay-venster ~5 min) en
  `schema_version` in de payload.

## Reeleezee API (live geverifieerd — zie verkenning/api-verkenning.md)

- Base: `https://apps.reeleezee.nl/api/v1` · Basic Auth (webservice-login per administratie) ·
  OData v4 · JSON via `Accept: application/json`. Endpointlijst: `GET /Help` (2.133 routes).
- **Multi-administratie**: elke route ook als `{adminId}/...`. `GET Administrations` → id's.
- **Aanmaken = PUT met client-GUID** (geen POST). Acties: `POST .../{id}/Actions {Type: n}`
  (per document, ook 138 — een collectie-vorm bestaat niet). Actie 17 = Book (definitief), 19 =
  Correct (zet terug naar concept, géén apart creditdocument), 34 = verrekenen, 138 =
  duplicaatcheck (**bewezen zonder bruikbaar signaal, niet gebruiken** — zie
  verkenning/api-verkenning.md "Actie 138"), 15/16 = LinkPaymentItems/UnlinkPayment (afletteren).
- Documentstatus (RLZ's eigen enumeratie `GET DocumentStatuses`, geverifieerd 2026-07-13):
  **1 = Tentative/Concept, 2 = Open/Openstaand (geboekt, nog niet volledig afgeletterd),
  3 = Closed/Gesloten (volledig betaald/afgeletterd, `BaseRemainingAmount` 0)**. De eerdere
  aanname "2 = definitief inkoopfactuur, 3 = definitief memoriaal" was fout: 3 is geen
  documenttype-status maar de afgeletterd-status — een memoriaal staat direct na boeken op 3
  omdat er niets open staat (saldo 0). Let op: geboekt = Status 2 óf 3 (afhankelijk van
  betaling), nooit alleen op 2 toetsen.
- **PurchaseInvoices**: PUT met `Entity:{id:vendorGuid}` + `DocumentLineList` (per regel
  `Account:{id}`, `TaxRate:{id}`, `NetAmount`, `TaxAmount`, `Project:{id}`). `/Uploads` = PDF-bijlage
  (base64 `Content`). RLZ berekent totalen zelf.
- **SalesInvoices**: idem; btw per regel komt correct in de aangifte. Gebruikt voor omzetboekingen
  (kassarapporten) met systeemdebiteur "Kasomzet" per administratie.
- **ManualJournals** (memoriaal): PUT + `JournalEntryDiary:{id}` verplicht, regels met
  `CreditOrDebit` (1=debet, 2=credit), `DebitAmount`/`CreditAmount`; saldo moet 0 zijn.
  Gebruikt voor kostprijsboekingen (gekoppeld aan omzetboeking, zelfde PDF-bijlage).
- **Lines lezen mét refs**: `.../Lines?$expand=Account,Project`.
- **Sync per administratie** (nooit hardcoden): `Ledgers` (+`?search=`), `TaxRates`, `Vendors`,
  `Projects` (top-level GET; write via Customers-route — PoC nodig), `JournalEntries`/`-Lines`
  (historie → boekingsgeheugen), `PaymentAccounts` (+`/Statements`), `BankMutationDirectBookings`
  (RLZ's eigen bankvoorstellen, `IsSystemGenerated:true`).
- Rate limits: docs "REST API limits" — exact verifiëren; client bouwt met throttling + retry/backoff.
- Testdata (v1.3-afspraak): integratietests tegen een **aparte RLZ-test-administratie**;
  testboekingen worden **gestorneerd** (actie 19 Correct), nooit hard verwijderd — consistent met
  "niets verwijderen in externe systemen". **Geverifieerd gedrag (6 juli 2026, zie
  verkenning/api-verkenning.md "Actie 19 Correct"): actie 19 zet hetzelfde document terug naar
  concept (Status 1), er komt géén apart creditdocument bij** — de eerdere aanname
  "actie 19 + creditboeking" was ongetest en klopt niet. Open vervolgpunt: nagaan of dit
  domeinbeslissingen raakt die een zichtbaar stornering/credit-spoor veronderstellen (bv.
  archief/tijdlijn-weergave), en koppelcontract §7.3 hierop bijwerken. Schrijftests op echte
  klantadministraties alleen bij uitzondering, met TEST-referentie en akkoord van Peter.

## Domeinbeslissingen (uit 10 ontwerprondes met Peter — details in mockup/index.html)

- **Werkvoorraad** = klantenlijst met tellers (alleen klanten mét openstaand werk) → klantpagina →
  controlescherm. Overal breadcrumbs, lijst→detail-patroon consistent.
- **Boekingsgeheugen**: RLZ-historie + app-correcties; correcties wegen zwaarder (recency). Default
  voorstel, nooit blind boeken. Afwijkingen markeren (oranje), niet overnemen. **Seed-only = oranje
  (aangescherpt 2026-07-14): een waarde die uitsluitend op RLZ-historie steunt blijft oranje ("uit
  historie, nog niet bevestigd"), óók bij hoge stem-confidence — pas de eerste app-bevestiging van
  die waarde maakt 'm groen (`app_bevestigd` per veld in engine + voorstel-response).**
- **Automatisch boeken = opt-in per leverancier**; harde checks blijven áltijd blokkerend.
  **Status per harde/blokkerende check: canoniek in `docs/BESLISSINGEN.md` (verplichte eerste
  check, houd dáár actueel — gedocumenteerd ≠ gebouwd).** Kort: duplicaat, regeltelling,
  verplichte velden, IBAN-wissel, vraag-blokkeert-boeken en afwijzen-met-verplichte-reden zijn
  gebouwd + getest; **nog niet gebouwd:** memoriaal-saldo-0 (fase 2), VGB-prefixfilter
  (vóór gedeelde administraties), per-leverancier-autoboeken-opt-in (vóór eerste autoboek),
  webhook-HMAC-per-verzendpoging (mét de afleveraar).
- **Vragenworkflow**: vraag blokkeert boeken, toegewezen aan eigenaar per administratie, antwoord
  voedt het geheugen. Vragen zijn een status in de werkvoorraad (geen apart menu).
- **Afwijzen** = verplichte reden, blijft zichtbaar ("Afgewezen — ter controle").
- **Verzamelbak "Niet toegewezen"**: alles wat niet eenduidig aan een administratie koppelt
  (tenaamstelling leidend, afzender = hint); leert van handmatige toewijzingen; "hoort niet bij
  ons" met reden. Nooit auto-toewijzen bij twijfel.
- **E-mail intake**: één centraal adres, splitsen van multi-factuur-PDF's op factuurgrenzen,
  toewijzen op tenaamstelling.
- **Omzetboekingen** (kassarapporten, bijv. BLOW Margerapport): type in de werkvoorraad; boekt als
  SalesInvoice (omzet per categorie → omzet-GB, btw-code per categorie) + gekoppelde
  kostprijsmemoriaal (per productgroep aan voorraad), als één transactie. Periode uit rapport,
  duplicaatbewaking per periode, plausibiliteitscheck (marge vs historie). BLOW: cannabisomzet =
  "NL, Geen BTW (Vrijgesteld)" — bewust géén 0%-tarief (aangifte-rubriek).
- **Bank**: klantenlijst → rekening (alle `PaymentAccounts` incl. kas). Voorstel-volgorde:
  1) exacte match naam+factuurnr+**bedrag** → auto-afletteren; 2) gedeeltelijke match → bevestigen;
  3) vaste regels (geheugen; na 3× zelfde handmatige boeking regel voorstellen); 4) RLZ's eigen
  voorstel (bron tonen); 5) handmatig. Afletteren gaat NIET door de klant-accorderingsflow.
- **Klant-autorisatie (à la Zenvoices), optioneel per administratie**: accordeurs per klant,
  sequentiële lagen met voorwaarden (bedragdrempels). Boekknop wordt "Ter accordering"; na laatste
  akkoord automatisch boeken (harde checks draaien opnieuw). Klant-app = PWA (factuurbeeld centraal,
  akkoord → volgende, dagelijkse push 09:00 alleen bij >0 open).
- **Projecten** (module, zichtbaar per rol + per administratie-toggle): project verplicht = hard
  blokkerend, géén "geen project"-optie; overhead → intern OVH-project (uitgesloten van bewaking).
  Budget uit offerte-ontleding (status offerte ≠ opdracht; meerwerk = aparte budgetversie).
  Werksoort = omzet-GB ↔ kosten-GB-mapping (default per administratie, override per project/regel).
  Signalen: kosten > gefactureerd per werksoort; budgetoverschrijding; weekanalyse (inkoop zonder
  omzet); m²-voortgang uit factuurregels. Integrale marge = analytische laag (AK-opslag instelbaar,
  dekkingscontrole vs OVH-project) — nooit geboekt in RLZ.
- **Projectcode-generatie** volgens naamconventie van de klant (bijv. Universal: "26xxx Plaats
  (Opdrachtgever)"), synct bij aanmaken naar RLZ.
- **Zoeken**: globaal over boekingen (incl. archief + RLZ-boekstuk + PDF), accorderingshistorie
  inline, vragen, audit. **Tijdlijn** per boeking (binnenkomst → extractie → vraag → accordering →
  boeking, met datum+tijd).
- **Archief**: geboekte documenten 7 jaar terugvindbaar met PDF (bewaarplicht).

## Praktijklessen uit echte documenten (verkenning/12_DOCUMENTANALYSE_UNIVERSAL.md)

- **Btw verlegd is de norm in de bouwketen** (onderaanneming): factuur zonder btw van een
  arbeids-leverancier → verlegd voorstellen, nooit 0%/vrijgesteld. Geheugen leert per leverancier.
- **Leveranciers hanteren eigen werknummers**: mapping leverancier-werknummer ↔ RLZ-project +
  fuzzy match op plaats/opdrachtgever; eerste keer bevestigen, daarna automatisch.
- **Urenstaat = documenttype**: gekoppeld aan project+week; inkoopfactuur onderaannemer wordt
  gecheckt tegen de getekende staat; "geparkeerde uren" = wacht-op-akkoord-status.
- **Intercompany-huurbijlagen parsen**: m²-standen per datum = bron voor voortgang en
  doorlopende-huur-detectie. Intercompany-leveranciers krijgen een vlag.
- **Contract-ontleding**: eenheden m²/m¹/stuks/manuren, verrekenbaarheidsregels, boeteclausules,
  termijnregeling — contractkenmerken sturen de projectsignalen.
- **G-rekening (WKA)**: één factuur → gesplitste betaling (regulier + G-rekening) is de
  standaard-case in bankmatching, geen uitzondering.
- **Doorbelastingscontrole op item-niveau (dagelijks)**: ingehuurde items/huurperiodes (liften,
  trappentorens, gaas — uit inkoopfactuurregels) vergelijken met ontlede offerte/opdracht én
  verkoopfactuurregels per project. Niet gedekt én niet doorbelast → signaal + vraag; de
  verrekenbaarheidsregels uit het contract bepalen het advies (doorbelasten vs eigen rekening).
  Bedragcontrole per werksoort vangt dit niet (aantallen kunnen wegvallen in totalen).
- **Creditnota's**: negatieve regels accepteren, nulregels (tariefstaffels) wegfilteren.
- **AVG hard principe: BSN's nooit extraheren, indexeren of in AI-output** — brondocument blijft
  bewaard (WKA), preview maskeert.

## Koppelvlak vastgoedmodule (verkenning/11_KOPPELCONTRACT_DEFINITIEF.md is leidend)

- Documenten van de vastgoedmodule dragen `Reference`-prefix **`VGB-`** → herkennen, nooit als
  werkvoorraad tonen.
- Wij pushen bij "geboekt" een webhook per inkoopfactuur van vastgoed-administraties (payload:
  RLZ-GUID, project-GUID, datum, bedragen per regel, GB, leverancier, omschrijving, adminId).
- Schrijfverdeling: zij huurfacturen + waarborg-memoriaal; wij inkoop/omzet/bank. Niemand muteert
  documenten van de ander.

## Referenties in deze repo

- `mockup/index.html` — goedgekeurde UI (alle schermen, klikbaar; design tokens = CSS-variabelen)
- `verkenning/api-verkenning.md` — alle geverifieerde API-feiten + PoC-resultaten
- `../Platform/` — **gedeelde platform-map (v1.6): koppelcontract-master (`contracten/`),
  besluitenregister (`besluiten/INDEX.md` — lees bij elke sessiestart!), registers (prefixen,
  schema-versies, entiteiten, conventies)**
- `docs/BESLISSINGEN.md` — **statusregister per feature/onderwerp (status + canonieke vindplaats)**
- `docs/BOUWPLAN.md` — fasering en definition of done per fase
- `verkenning/.env` — RLZ-credentials (BLOW + Universal Steigerbouw), NOOIT committen

## Werkwijze

- **`docs/BESLISSINGEN.md` is de verplichte eerste check vóór elk feature-voorstel of bouwstart**
  (pre-feature-ritueel, `Platform/WERKWIJZE.md` v1.4): raadpleeg het register + de canonieke
  vindplaats en benoem expliciet waar de feature al staat; goedgekeurde mockup/besluit = 1-op-1
  voortbouwen, niet opnieuw uitvragen. **Capture-at-acceptance:** elk akkoord van Peter meteen in
  dit register (+ canonieke plek) vastleggen, nooit alleen in de chat.
- **Cross-projectdocumenten hebben precies één canonieke locatie**: het koppelcontract leeft als
  master in `verkenning/` van deze repo (kopie in de vastgoed-repo wordt bij elke versiebump
  gesynchroniseerd en per diff geverifieerd); `01_ARCHITECTUUR.md` en `14_ANTWOORD_AAN_RLZ.md`
  leven uitsluitend in de vastgoed-repo. Geen derde kopieën maken.
- **Dit project is eigenaar van het gedeelde platform-fundament** (auth, credential-store,
  entiteitenregister, IAM, audit_event/WORM) — interface-wijzigingen alleen met akkoord van
  beide projecten en een versienummer (contract v1.5).
- **Continue evaluatie**: bij elk nieuw inzicht actief checken of eerdere beslissingen, dit
  bestand, het bouwplan of het koppelcontract bijgewerkt moeten worden — inconsistenties tussen
  afspraken zelf ook signaleren.

- **Werkwijze/rol/samenwerking met Peter: zie `../Platform/WERKWIJZE.md` (canoniek, bindend, lees
  bij sessiestart — besluit 0014).** Kort: denk als de beste developer/front-end-specialist/
  architect/analist/accountant ineen; proactief en kritisch (geen lege complimenten, onderbouw,
  zeg het als Peter iets mist); bronnen eerst; vind gaten vóór hij ze vindt. Volledige, actuele
  versie staat uitsluitend in WERKWIJZE.md.
- Nederlands in UI en documentatie; code/comments Engels.
- Tests verplicht op geldlogica (mapping, totalen, idempotentie, statusmachine) vóór UI-polish.
- Elke schrijfactie naar RLZ eerst tegen een testadministratie of met TEST-referentie + akkoord.
