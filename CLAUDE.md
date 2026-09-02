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
  Docker Compose = lokale dev. **Same-origin-serving (`app/static_frontend.py`): een
  browser-NAVIGATIE (Accept text/html + Sec-Fetch-Dest document) krijgt via een middleware
  VÓÓR de routing altijd de SPA — ook als het pad exact een API-route is (bugfix 25-08:
  `/instellingen/administraties` gaf "Not authenticated"); regressiesweep over álle
  router-paden in `tests/unit/test_static_frontend.py`; de frontend navigeert daarom nooit
  rechtstreeks naar een API-URL (bestanden altijd via fetch + blob).** CLOUD Act geaccepteerd; het herzieningsmoment vóór go-live is
  **uitgevoerd als platformbesluit 0021 (akkoord 2026-08-14): CMEK actief** — Cloud SQL
  `rlz-sql2` mét CMEK-key + default-CMEK-key op de documentenbucket (keys `cmek-sql`/
  `cmek-documenten` op keyring `rlz`, jaarrotatie, nooit destroy); client-side
  documentversleuteling alleen op expliciet klantverzoek.
- **Instellingen › Administraties v2 (opdracht 30-08, mockup `instellingen-administraties-v2.html` =
  norm, akkoord Peter 29-08; migratie 0089 — BESLISSINGEN "OPDRACHT 30-08 (2)" blok A is canoniek):**
  compacte tabel (naam + meta, module-/afwijkings-chips, sync-chip, ⚙ 🧪 🗑) + — sinds v3 01-09 —
  detailPAGINA per administratie met tabs (`AdministratieDetailPagina.tsx`; de v2-dialoog is
  vervallen, rij-klik/⚙ navigeren); defaults boeken + AI-extractie AAN voor
  NIEUWE administraties (bestaande behouden hun waarde, afwijking = chip); Vastly-autoboeken heeft geen
  eigen knop meer — de motor toetst op `is_vastgoed`, de kolom is een spiegel; ARCHIVEREN (🗑, nooit
  verwijderen): `actief=false` + `gearchiveerd_op/door`, webservice-login uit de credential-store,
  álle RLZ-rakende jobs/meldingen en `mijn_administraties` filteren op `actief`, registersync levert
  gearchiveerde rijen niet meer (contract v1.19, afwezigheid = verdwenen), dearchiveren = nieuwe login
  mét groene probe; `BevestigDialog` is een Radix-dialoog (geneste modals).
- **Terugkerende-facturen-signaal (opdracht 30-08 blok B, benchmark-besluit Peter 29-08, migratie 0090
  — BESLISSINGEN "OPDRACHT 30-08 (2)" blok B):** `app/terugkerend/` — deterministisch (géén AI) per
  (administratie, crediteur): ≥ 3 facturen met regelmatig interval maand/kwartaal ±35 % (app-documenten +
  RLZ-boekingsgeheugen); signaal 1 "verwachte factuur ontbreekt" = oranje werkvoorraad-teller
  (`terugkerend_signalen`, kolom "Verwachte facturen") + scherm Inzicht › Terugkerende facturen
  (`/terugkerend`, snooze/afmelden per leverancier mét audit); signaal 2 "prijsstijging" boven de drempel
  (`terugkerend_prijsstijging_pct`, default 10, Beheerder) = chip op het controlescherm
  (`TerugkerendSignaal`) + in het overzicht; dagelijks meeliftend in `sync-alles`. Alleen signaleren.
- **Administratie toevoegen via de UI (feedbackronde 26-08 punt 5, migratie 0076):** Instellingen ›
  Administraties "+ Administratie toevoegen" — wizard: webservice-login → verbinding + rechten-probe
  (10 leesroutes) verplicht groen → keuze uit `GET Administrations` (nooit een id typen) → opslaan
  met defaults (alles UIT) + credential-store (envelope) → eerste sync als achtergrondrun met status
  per onderdeel (job `rlz-eerste-sync`); "Schrijftest uitvoeren" = aparte knop (TEST-boeking +
  storno 19); "Webservice-gegevens wijzigen" per rij (probe-gated). **Eerste-sync-stand op de
  administratie-rij (wizard-nazorg 27-08): subrij mét status per onderdeel, foutreden en "Sync
  opnieuw starten" zolang de laatste run niet volledig groen is — `eerste_sync` op de
  lijst-response; BESLISSINGEN "VERZAMELRUN 27-08" punt 5. Sinds v2 (30-08): sync-chip in de tabel
  + de stand in de detail-dialoog; wizard-defaults = boeken + AI-extractie AAN.** Zie BESLISSINGEN
  "RLZ-FEEDBACKRONDE 26-08" punt 5; `app/beheer/onboarding.py`. **Facturatiemodule niet afgenomen
  (besluit 01-09, casus A.Y. Holding 2 + Abbegaa, migratie 0093): een 403 op SalesInvoices is de
  ENIGE niet-blokkerende probe-uitkomst — wizard sluit aan mét waarschuwing en zet het persistente
  kenmerk `verkoopmodule_afwezig` (chip "geen facturatiemodule"), dat de verkoop-rakende leesroutes
  uitschakelt (voorraad-RLZ-uitstroom, SalesInvoices in de projectcijfers-sync — zichtbaar
  overgeslagen, nooit stil op de 403 stuk); een herprobe mét SalesInvoices ok wist het kenmerk
  (audit beide kanten); élke andere rechten-403 meldt "geef de webservice-gebruiker in RLZ
  leesrecht op <route>". Zie BESLISSINGEN "SPOEDOPDRACHT 01-09" blok A.** **`is_vastgoed` is sinds de avondrun
  26-08 een Beheerder-toggle op dezelfde pagina (`PATCH /administraties/{id}/is-vastgoed`, kolom
  "Vastgoed-koppeling (Vastly)", bevestigingsdialoog met consequenties, audit oud→nieuw; UIT neemt
  verkoop-autoboeken zichtbaar mee uit, tier-vlag afgeletterd_event blijft; CLI-terugval `make
  is-vastgoed-aan/-uit`) — S2-draaiboek R1. Zie BESLISSINGEN "AVONDRUN 26-08".**
- DB-schema's: `platform` (gebruikers, rollen, administraties, credential-store, audit log),
  `boekhouding` (deze module). Vastgoedmodule krijgt `vastgoed`, MI-dashboard later `mi`.
- Auth: e-mailuitnodiging (eenmalige link 72 u) + wachtwoord + **TOTP-2FA verplicht**, JWT-sessies.
  Rollen: Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur (scope: eigen administratie).
  **Uitzondering klant-accordeur (besluit + gebouwd 2026-08-11, migratie 0040): passkey/WebAuthn
  i.p.v. TOTP** — publieke sleutel per gebruiker+apparaat (py_webauthn), volledige login alleen
  bij eerste gebruik / nieuw apparaat / ná 7 dagen inactiviteit (sliding 7-dagen-refresh-TTL),
  passkey-assertion bij app-opening — **sinds 27-08 HOOGUIT 1× per 24 uur per apparaat
  (besluit Peter, server-side venster op `webauthn_credential.laatst_gebruikt_op`, veld
  `ontgrendeling_nodig` op de stille refresh; geen migratie — BESLISSINGEN "VERZAMELRUN 27-08"
  punt 3)**, GEEN biometrie per actie; kantoor-kill-switch per
  apparaat (bijt per request + bij rotatie + bij assertion); dev-stub `auth_biometrie_dev_stub`
  voor LAN-kliktests (WebAuthn vereist https/localhost), hard onwerkzaam buiten dev. Zie
  BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD". **Wachtwoord kwijt (bv. ná een
  kill-switch): Beheerder-knop "Herstel-link sturen" (feedbackronde 25-08 deel 2 punt 7,
  migratie 0068 — `platform.uitnodiging.soort`): eenmalige 72-uurslink, zelfde token-mechaniek
  als de uitnodiging; nieuw wachtwoord → direct passkey-setup-token voor apparaat-registratie;
  status/passkeys/akkoorden blijven staan, sessies vervallen, alle oudere links ongeldig, audit
  beide kanten. Bewust géén selfservice "wachtwoord vergeten" — kantoor blijft poortwachter;
  alleen externe app-rollen.** **E-mail wijzigen zonder carrousel (opruimrun 28-08 punt 22, casus
  Haci): Beheerder-knop "E-mail wijzigen" op álle drie de /gebruikers-tabs (óók Kantoor) en óók bij
  geblokkeerd/gearchiveerd — een gearchiveerd account krijgt nooit een uitnodigingsmail (open links
  vervallen, alleen adres + audit oud→nieuw); uitnodigen op een adres van een bestaand (ook
  gearchiveerd) account = leesbare 409 i.p.v. UniqueViolation→500 (`EMailAlInGebruik`). Zie
  BESLISSINGEN "OPRUIMRUN 28-08" punt 22.**
  **Activatie externe rollen MOBIEL-FIRST + ATOMAIR (bouwrun 28-08 blok B, mockup
  `activatie-mobiel.html`, casus Haci, migratie 0083):** de wachtwoordstap parkeert de hash op de
  link (`uitnodiging.wachtwoord_hash_in_wacht`) en legt níéts vast; pas de geslaagde
  passkey-registratie maakt in dezelfde transactie wachtwoord + account definitief en verbruikt de
  link (mislukt = niets half, link blijft 72 u). `/activeren` op een desktop = stop-scherm mét QR
  van dezelfde link (capability-check + UA-vangnet, twijfel = stop); telefoon →
  `/accordeur/activeren?uitnodiging=` (3 stappen). Half-geactiveerde accounts (wachtwoord zonder
  passkey) zijn zichtbaar op /gebruikers; Herstel-link ruimt ze op. **Géén eigen push-login
  (besluit Peter 28-08)** — kantoor-web toont ná een cross-device-login éénmalig "Passkey
  toevoegen op dit apparaat?". Zie BESLISSINGEN "BOUWRUN 28-08 AVOND" blok B.
  **PINCODE-ACTIVATIE + APP-LOCK NATIVE APP (besluit Peter 31-08, ING-patroon, mockup
  `app-lock-pincode.html` = norm; herziet de 28-08-flow UITSLUITEND voor de native app — de
  PWA/web houdt wachtwoord → passkey én de 24-uurs-Ontgrendel):** mail-link (universal link
  opent de app; iOS applinks + Android App Links op het app-domein) → 5-cijferige code kiezen →
  bevestigen → Face ID-vraag + voorwaarden (passkey onder water) → klaar. De wachtwoordstap
  vervalt voor app-rollen (account houdt `wachtwoord_hash = NULL`; endpoint
  `/auth/uitnodigingen/activatie-zonder-wachtwoord` legt níéts vast — zelfde atomiciteit). De
  code is een puur LOKAAL anker (nooit server-side): PBKDF2-wrap ontgrendelt de sleutel die het
  refresh-token in Keychain/Keystore versleutelt (`frontend/src/api/appSlot.ts`); biometrie =
  gemakskopie via plugin `AppSlot` — HARDE EIS nageleefd: iOS `.biometryAny` (géén
  biometryCurrentSet), Android `setInvalidatedByBiometricEnrollment(false)` — biometrie-falen
  valt altijd stil terug op de code. Het slot vervangt in native de 24-uurs-assertion bij
  openen (sliding-refresh + kill-switch ongewijzigd); her-login = e-mail → passkey-assertion
  (`/auth/accordeur/passkey-login/*`, 0020-lijn) en reset het slot (nieuwe code). 5 foute
  codes = lokaal gewist + `POST /auth/app-lock/uitgesloten` (kill-switch eigen apparaat +
  audit) — herstel = verse kantoor-link; scherm "Toegang tot de app": Face ID-switch, code
  wijzigen, direct vergrendelen (anders 5 min), toestel ontkoppelen
  (`/auth/app-lock/ontkoppelen`). Zie BESLISSINGEN "PINCODE-ACTIVATIE + APP-LOCK".
  **Platformbesluit 0020 (2026-08-14, samen met vastgoed): passkeys worden de EERSTE
  authenticatielijn voor álle rollen; wachtwoord + TOTP wordt terugval/herstel.**
  **Kantoor-passkeys: GEBOUWD + GETEST (2026-08-15)** — tweede afnemer van de 0040-bouwstenen,
  geen nieuwe migratie: registratie ná login op Instellingen → beveiliging (élke kantoor-rol,
  meerdere apparaten, zonder platform-pin, géén nieuw token-paar), éénstaps-login e-mail →
  assertion mét UV (usernameless mag niet, 0022-lijn; geen passkey = generiek 409 → stil terug
  naar wachtwoord+TOTP, dat pad is ongewijzigd), standaard kantoor-JWT-semantiek maar wél
  apparaat-gebonden (kill-switch bijt per request); intrekken = eigenaar-of-Beheerder (niet-eigen
  = 404), laatste passkey intrekken sluit nooit buiten; kantoor-endpoints weigeren accordeurs
  (403 — hun eigen flow houdt de wachtwoordstap). Zie BESLISSINGEN "KANTOOR-PASSKEYS".
- **Autorisatie (hard, bevestigd 2026-07-06):** klanten-scope per medewerker via koppeltabel
  gebruiker↔administraties, afgedwongen door RLS (DB-niveau) + server-side checks — geen scope =
  geen data, ook niet via bugs in de app-laag. Rol- en scope-wijzigingen exclusief door de
  Beheerder-rol (initieel alleen Peter), server-side gecontroleerd. **Niemand kan zijn eigen rol
  of scope muteren, ook een Beheerder niet** (tweede beheerder aanwijzen kan alleen door een
  andere beheerder). Elke rol-/scope-wijziging in het append-only audit_event.
  **RLS-les scope-toetsen (bugfix 2026-08-25, BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" rij
  A-BUGFIX): een scope-lookup op `gebruiker_administratie` (zelf RLS) leest ALTIJD
  `scoped_session(<te toetsen administratie>, actor_id=actor)` — in `scoped_session(None)`
  zonder actor ziet een niet-Beheerder nul rijen en lijkt elke scope leeg (Beheerder-bypass
  verbergt dat); tests verplicht met een echte niet-Beheerder MÉT scope (groen pad), zie
  Platform `conventies.md` §RLS.**
  **Rolniveau-poorten kantoor-console (rollen-gate-fix 2026-08-21, BESLISSINGEN "ROLLEN-GATE-BUG
  WEB"):** administratie-scope is GEEN rolpoort — externe app-rollen (accordeur + veldrollen)
  hebben reguliere scope-rijen. Élk kantoor-endpoint draagt daarom `vereis_kantoorrol`
  (router-breed waar mogelijk) of `vereis_kantoor_of_accordeur` (PDF-bestand,
  accorderingsbesluiten) uit `app/auth/deps.py`; frontend-routing fail-closed via allowlists
  (`frontend/src/auth/rollen.ts`). Vangnet: `tests/security/test_rol_endpoint_gates.py` —
  rol×endpoint-matrix + fail-closed sweep over álle routes (nieuw endpoint zonder poort = rood).
  **Platformbesluit 0019 (2026-08-08): identiteit gedeeld, autorisatie per module** — elke
  module een eigen rollen-/rechtenstructuur (nooit één gedeelde enum); gebouwd als
  `platform.gebruiker_module_rol` + `platform.gebruiker_entiteit` (migratie 0034, RLS dwingt
  de mutatieregels ook op DB-niveau af); RLZ's eigen rol-enum ongewijzigd, convergentie t.z.t.
  op eigen tempo.
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
  verkenning/api-verkenning.md "Actie 138"), 15 = LinkPaymentItems (afletteren — **GEKRAAKT
  2026-08-09 via de betaal-kant**: DevTools-capture Peter + STAP-0-replay; de werkende vorm is
  `POST PaymentTransactions/{tx}/Actions {Type:15, PaymentItemList:[{id}], LinkedAmount:
  <teken van de mutatie>, IsCompletelyPaid, PaymentCorrectionMethod:1}` — actie 15 hoort op de
  PAYMENTTRANSACTION, niet het document (dáár liepen alle eerdere PoC's stuk); deelbetaling =
  deel-LinkedAmount (⚠️ restant krijgt een NIEUW PaymentItem-id), `IsCompletelyPaid:true` =
  betalingsverschil-afboeking (post dicht ondanks restant), `PaymentCorrectionMethod`
  ongedocumenteerd → gepind op 1. **Type 16 ontkoppelt in géén enkele vorm** — terugdraaien =
  storno actie 19 (⚠️ een deels-gekoppelde mutatie houdt daarna huls-koppelingen: OpenAmount
  komt niet volledig terug — reconciliatie-aandachtspunt). Motor: `RlzClient.link_payment_item`
  + `app/bank/afletteren.py`; supportvraag beantwoord door eigen capture, supportantwoord
  alleen nog ter bevestiging. Zie api-verkenning "Afletteren betaal-kant — REPLAY GESLAAGD"**).
- Documentstatus (RLZ's eigen enumeratie `GET DocumentStatuses`, geverifieerd 2026-07-13):
  **1 = Tentative/Concept, 2 = Open/Openstaand (geboekt, nog niet volledig afgeletterd),
  3 = Closed/Gesloten (volledig betaald/afgeletterd, `BaseRemainingAmount` 0)**. De eerdere
  aanname "2 = definitief inkoopfactuur, 3 = definitief memoriaal" was fout: 3 is geen
  documenttype-status maar de afgeletterd-status — een memoriaal staat direct na boeken op 3
  omdat er niets open staat (saldo 0). Let op: geboekt = Status 2 óf 3 (afhankelijk van
  betaling), nooit alleen op 2 toetsen.
- **Boekingsdatum = `BookDate`, niet `Date` (STAP 0 28-08, api-verkenning "Boekingsdatum =
  BookDate"; besluit Peter 27-08 "boekingsdatum = factuurdatum", opruimrun punt 15):** de
  journaalpost (`JournalEntry.BookDate`) volgt het PUT-veld `BookDate`; zonder dat veld zet RLZ de
  systeemdatum (dag van boeken). `BookDate` is zetbaar op PurchaseInvoices, SalesInvoices én
  ManualJournals; een datum in een ingediende btw-periode wordt niet geweigerd (TaxSource verschuift
  naar de eerstvolgende open periode). **Álle motoren geven `BookDate` = factuur-/documentdatum mee
  náást `Date`** (inkoop factuurdatum, verkoop factuurdatum, omzet periode-einde, waarborg
  berichtdatum, doorbelasting beide kanten + inhaalpad = factuurdatum BRON-document, bank-
  aanbetaling = mutatiedatum); tegenboeken blijft bewust boekdatum vandaag. `DueDate` blijft uit
  `Date` afgeleid.
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
  `Projects` (top-level GET; write = klant-loze top-level PUT, hertest 2026-08-14 —
  api-verkenning "Projects klant-loze schrijfroute"; de Customers-route bestaat óók maar is
  niet de enige vorm), `JournalEntries`/`-Lines`
  (historie → boekingsgeheugen), `PaymentAccounts` (incl. kas, Type 3; `/Statements` = alleen
  afschrift-koppen), **`PaymentTransactions` = dé ruwe bankmutaties** (tegenrekening-IBAN,
  omschrijving, afgeletterd-status `IsComplete`+`OpenAmount`; geverifieerd STAP 0 2026-08-02).
  `BankMutationDirectBookings` `IsSystemGenerated:true` bleek géén bruikbaar voorstel-signaal
  (lege concept-hulzen, systeem-plumbing per open mutatie) — zie verkenning/api-verkenning.md
  "Bankmodule STAP 0". **Bank-schrijfmechanics (schrijf-PoC 2026-08-02, "Bankmodule
  schrijf-PoC"): direct-op-grootboek = `PUT BankMutationDirectBookings/{client-guid}` met
  `PaymentTransaction`+regels (boekt direct, Status 3, storno = actie 19); leesspoor
  "waartegen afgeletterd" = `$expand=PaymentReferenceList($expand=Document)`; RLZ-matchvoorstel
  = auto-gevuld `MatchedPaymentItem` (alleen exacte bedrag-match); ⚠️ `IsComplete` blijft na
  storno stale op true — afgeletterd altijd op `OpenAmount` toetsen.** ⚠️ Versheid-probe
  `LastBankImport` antwoordt "geen aanlevering" in drie vormen (404, `400 _InvalidData` op
  kas/verrekeningen/RC/archief, `200`+HTML op een bankrekening zonder ooit een import) en
  RLZ-systeemrekeningen dragen vaste GUID's identiek over administraties — rekening-GUID
  alleen samen met administratie-id gebruiken (kliktest-fix 2026-08-08, api-verkenning
  "LastBankImport per rekeningtype").
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
- **Na boeken direct door (besluit Peter 25-08, deel 4 punt 1, GEBOUWD):** ná boeken/"Boeken +
  doorbelasten"/afwijzen/ter accordering toont het controlescherm een toast (referentie +
  boekstuknummer) en opent automatisch het volgende te-verwerken document van dezelfde klant
  (zelfde soort eerst, dan de soort-tab-volgorde; `werkvoorraad/volgendDocument.ts`); stapel
  leeg → documentenlijst van de klant. Uitzondering: ter accordering mét `boek_fout` blijft staan.
  **Lijstcontext reist mee (werkstroom-run 27/28-08, punt 1): soort-tab + status-filter + zoekterm
  van de documentenlijst staan in de URL (`soort=/status=/q=`) en reizen mee naar het inkoop-
  controlescherm — de doorloop blijft BINNEN het actieve filter (`kiesVolgendDocument(…, context)`),
  de topbar toont ‹ › mét "n van m", Esc/"← Werkvoorraad" gaan terug mét filter; élke kolom-teller in
  "Overzicht per klant" opent de lijst voorgefilterd; één filterbron `werkvoorraad/lijstContext.ts`.
  **Binnenkomst-default = "Te controleren" (wens Peter 01-09): zonder `status=`/`soort=` in de URL
  opent de lijst op het werk — expliciete status in de URL wint altijd, niets te controleren =
  terugval "Alle" (nooit leeg), tab-klik houdt de bestaande status-reset; BESLISSINGEN
  "GECOMBINEERDE RUN 01-09" blok D.**
  Sneltoetsen (punt 5): B = actieve besluitknop, A = afwijzen, ←/→, Esc, ? = overzicht, / = zoekveld —
  alleen buiten invoervelden/dialogen (`document/sneltoetsen.ts`). Onopgeslagen (debounce loopt) →
  bevestiging vóór verlaten. BESLISSINGEN "WERKSTROOM- + UI-RUN 27/28-08".**
  **Actiebalk (Afwijzen / Vraag stellen / Ter accordering / Boeken, ± doorbelasten) staat sinds
  27-08 ÓNDER het blok "Doorbelasten na boeken"** (portal-anker `actiebalkDoel`, alleen volgorde
  — BESLISSINGEN "VERZAMELRUN 27-08" punt 4). **Boekingsregels-tabel: kolomminima in px uit één bron
  (`document/boekingsregelsKolommen.ts`, tabel-min-width = de som; te smal paneel = horizontale
  scroll in `.tabel-scroll`, omschrijving wrapt op woordgrenzen — nooit meer per letter; eigen
  regressietests náást de overflow-sweep, die kolom-implosie niet ziet — BESLISSINGEN
  "KANTOOR-MINI-RUN 27-08" punt 4).**
- **Kantoor-frontend-modernisering (designronde Peter 2026-08-15, 4 iteratierondes —
  BESLISSINGEN "Kantoor-frontend-modernisering"):** de kantoor-UI migreert naar het
  platform-fundament (Vastly-generatie: Tailwind v4 + semantische tokens, shadcn-stijl-
  componenten op Radix, thema.ts-dark-mode "keuze wint, anders systeem") mét het bestaande
  RLZ-palet; `mockup/kantoor-modern.html` = de norm voor vormgeving, componenten en IA,
  `mockup/index.html` blijft de bron voor flows/inhoud. **IA-besluit klant-centrisch, drie
  lagen:** klantpagina = STANDEN (documenten per soort, bank per rekening — alleen tellers),
  deelscherm = WERKEN (één soort/rekening, segment-filters), controlescherm = één document
  — **HERZIEN 25-08 (besluit Peter, kliktest): de klant-klik landt DIRECT op de
  documentenlijst (`/?administratie=X`) mét tabs per soort (alleen teller > 0 + "Alle
  documenten") en een klikbare chip-rij met de overige standen; het standen-scherm blijft
  als `sectie=standen` bereikbaar (niets vervalt, alleen de verplichte tussenstop). Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt C;**
  Vragen-/Bank-tabbladen vervallen, kantoorbrede dwarsdoorsneden via klikbare KPI-kaarten
  bovenaan de werkvoorraad; oude URL's redirecten. Toon-regel: bakken-/soorten-regels alleen
  bij teller > 0; AI-kosten alleen op Instellingen (Beheerder). **Instellingen v3 (mockup
  `instellingen-v3.html` = norm, akkoord Peter 01-09 — HERZIET D2 25-08 "landing met
  sectiekaarten" én 30-08 "detail-dialoog"): twee-paneel op élke `/instellingen`-route — vaste
  linker settings-nav in drie groepen (Administraties / Platform / Kantoor) mét stand-chips en een
  DETERMINISTISCHE zoeker (registry naam + synoniemen + doel; "accordering arvum" = deep-link naar
  de detailpagina-tab; geen AI), `/instellingen` zonder sectie redirect naar het eerste zichtbare
  item van de rol (Beheerder → administraties, Boekhouding → beveiliging, B+P → materiaal), álle
  oude sectie-URL's redirecten; administratie-detail = PAGINA `/instellingen/administraties/{id}`
  mét tabs (Algemeen · Boeken & AI · Klant-accordering · Doorbelasting (bron/doel) · Uren &
  materiaal · Voorraad (opt-in)) die de bestaande componenten gefilterd hergebruiken — één bron,
  twee ingangen; Crediteuren-dubbelsignalering → Inzicht (`/crediteuren`). Rol×sectie-matrix
  fail-closed in `instellingenRegistry.ts` (`zichtbareNavItems`; B+P ziet als enige
  niet-Beheerder-uitzondering de Materiaalcatalogus, spiegel van backend `require_beheerder_of_bp`);
  GUARD: élk nav-item/élke tab heeft een registry-entry (`instellingenRegistry.test.ts`);
  schaalregel: nieuwe module = nav-regel en/of tab, nooit een tegel. BESLISSINGEN "INSTELLINGEN
  V3".** De globale boeken-kill-switch heet in de UI/CLI "Boeken platformbreed" — aan =
  boeken kan, uit = boeken staat plat (D4, alleen presentatie). Deel 3 (25-08): `/gebruikers`
  = tabs Kantoor/Veldwerkers/Klant-accordeurs mét tellers, zoekveld + paginering (25) per tab,
  `?groep=` in de URL, actiekolom sticky rechts (`td.acties`) en compacte administraties-chip;
  Instellingen › Administraties: IBAN-accordeurs als chips + wijzig-dialoog (één regel per
  administratie).** Sleep-upload blijft op
  werkvoorraad (tenaamstelling) én klantpagina (direct toegewezen). **GEBOUWD + GETEST in 3
  fases (2026-08-16, kliktest Peter open):** fase 1 designsysteem (Tailwind v4 zónder
  preflight, tokens + `ui/thema.ts` + componentenset `ui/basis/`, controls gemigreerd), fase
  2 IA-verbouwing (KPI-dwarsdoorsneden, klantpagina-standen, deelschermen, redirects —
  verificatiepunt accordeur-multi-administratie bewezen met backend-test: wachtrij én
  09:00-herinnering voegen administraties samen), fase 3 Gebruikers & toegang
  (`/auth/gebruikers` + uitnodiging-opnieuw-endpoint, scherm `/gebruikers`) + bulkbediening
  Instellingen. **Gebruiker ARCHIVEREN/dearchiveren (feedbackronde 26-08 punt 1, migratie 0075,
  0052-patroon): status `gearchiveerd` = uit álle default-lijsten (filter "gearchiveerd (N)" per
  tab op /gebruikers), toegang dicht, niets verwijderd; dearchiveren = status van vóór terug; open
  werk = waarschuwing mét aantallen (`GET /auth/gebruikers/{id}/open-werk`), geen blokkade — zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08".** **Gebruiker blokkeren/heractiveren: GEBOUWD + GETEST (2026-08-16, migratie
  0052)** — blokkade bijt per direct op álle paden (sessies/refresh dood, passkeys onbruikbaar
  maar geregistreerd = omkeerbaar), guards server-side (eigen account/systeem-actor/laatste
  actieve Beheerder nooit), heractiveren zet de status van vóór de blokkade terug; audit op
  beide. Zie BESLISSINGEN "BEHEER-MINI". Details per fase: BESLISSINGEN "Kantoor-frontend-modernisering".
  **Nazorg controls-review UITGEVOERD (2026-08-16, bevindingen kliktest Peter):** switch/
  checkbox-inklap (specificiteitsbotsing legacy-CSS vs `.cb`/`.switch`), switch-track-contrast
  (mockup-norm mee bijgewerkt), paneel-clipping ~1170px (tabel-scroll), thema-toggle-race,
  systeem-actor uit gebruikersbeheer (mét server-side guard), dev-stub-apparaat-deduplicatie —
  zie BESLISSINGEN "Nazorg controls-review". Regressie-vangnet: `frontend/scripts/
  overflow_sweep.sh` (alle visuele harnassen × 1440/1170/1024/768 × licht/donker — geen
  horizontale pagina-overflow; vastgoed-sweep-patroon).
- **Btw-tarief buitenland (verzamelrun 31-08 blok A, casus Labo Derva):** RLZ weigert de
  boekactie (17) van een EU-/buitenland-tarief met 400 "ongeldig belastingtarief" zolang de
  crediteurkaart in RLZ geen land/btw-nummer draagt — crediteur-datakwaliteit, geen tarief-fout;
  land/btw-nummer zijn via de API níét leesbaar (api-verkenning "EU-tarieven op
  PurchaseInvoice-Actions"). Daarom: onvoorwaardelijk oranje signaal "Btw-tarief buitenland"
  bij élk buitenland-tarief (naam-prefix ≠ NL) + foutvertaling `vertaal_rlz_boekfout` mét
  handelingsperspectief op controlescherm/boek_fout/herstel-CLI.
- **Btw-code uit de scan (feedbackronde 26-08 punt 3):** ná AI-extractie leidt CODE per regel het
  tarief af (`extractie/controle.py::leid_btw_af`: netto × tarief ≈ btw ±1 ct tegen de gesyncte
  TaxRates; gelijk percentage → RLZ-favoriet `IsFavorite` wint; verlegd/vrijgesteld/gemengd doen
  niet mee) → vooraf ingevuld mét chip "uit factuur (21%)"; 0/onbepaalbaar/meerduidig = NOOIT
  invullen (0% is ambigu: geheugen per leverancier wint, anders mens); "btw verlegd"-vermelding
  = alleen een hint-chip. Harde checks blijven de poort.
- **Vervaldatum inkoopfactuur (C1 gecombineerde run 26-08, migratie 0078):** kopveld
  `boekvoorstel.vervaldatum` uit de scan (herkomst-chip), harde check "Vervaldatum" (vóór
  factuurdatum = blokkerend; leeg mag), oranje signaal > 90 dagen (geen blokkade), naar RLZ als
  `DueDate` (live geverifieerd — zonder DueDate leidt RLZ 'm af uit Date + PaymentDueDays). De
  documentenlijst-kolom "Toegewezen" toont bij `ter_accordering` de accordeur die aan de beurt is
  (naam · laag, C2); de regelsom-badge op het veldvoorstel gebruikt exact de netto+btw=incl-logica
  van de boekingsregels-toets (C3). Zie BESLISSINGEN "GECOMBINEERDE RUN 26-08" blok C.
- **Crediteur-dedup + duplicaat over crediteuren heen (opruimrun 28-08 punt 14, besluiten Peter
  27-08, migratie 0082 `crediteur_kenmerk`):** de extractie leest het BTW-NUMMER (primair) en
  KvK-nummer (secundair) van de leverancier; code valideert (NL-vorm + elfproef óf mod-97 =
  "geverifieerd", `app/extractie/btw_nummer.py`), herkomst-chip bij de crediteur, opslag per
  crediteur zodra het boekvoorstel mét crediteur wordt opgeslagen (bron 'factuur', handmatig wint,
  audit). Crediteur-voorstel matcht éérst op btw-/KvK-nummer (RLZ-KvK uit de vendor-brondata als
  fallback), dan pas fuzzy op naam (Wola/Wola b.v.). Nieuwe check "Duplicaat bij andere
  crediteur" (`check_duplicaat_over_crediteuren`, Reference+bedrag zónder Entity-filter mét
  `$expand=Entity`): zelfde btw-nummer = BLOKKEREND, anders ORANJE SIGNAAL (`CheckResultaat.signaal`
  — ok, geen blokkade); de bestaande zelfde-crediteur-check blijft de harde poort. Instellingen ›
  Crediteuren = dubbel-signalering per administratie (btw/KvK/IBAN/genormaliseerde naam) mét
  KvK-controle (hergebruik A3-client) — samenvoegen blijft RLZ-mensenwerk, wij verwijderen niets.
  `app/documenten/crediteur_kenmerk.py`; BESLISSINGEN "OPRUIMRUN 28-08" punt 14.
- **Boekingsgeheugen**: RLZ-historie + app-correcties; correcties wegen zwaarder (recency). Default
  voorstel, nooit blind boeken. Afwijkingen markeren (oranje), niet overnemen. **Seed-only = oranje
  (aangescherpt 2026-07-14): een waarde die uitsluitend op RLZ-historie steunt blijft oranje ("uit
  historie, nog niet bevestigd"), óók bij hoge stem-confidence — pas de eerste app-bevestiging van
  die waarde maakt 'm groen (`app_bevestigd` per veld in engine + voorstel-response).**
- **Automatisch boeken = opt-in per leverancier**; harde checks blijven áltijd blokkerend.
  **Status per harde/blokkerende check: canoniek in `docs/BESLISSINGEN.md` (verplichte eerste
  check, houd dáár actueel — gedocumenteerd ≠ gebouwd).** Kort: duplicaat, regeltelling,
  verplichte velden, IBAN-wissel, duplicaat-bij-andere-crediteur (btw-nummer + referentie + bedrag,
  28-08 — Reference+bedrag zonder btw-match = oranje signaal), vraag-blokkeert-boeken,
  afwijzen-met-verplichte-reden en
  webhook-HMAC-per-verzendpoging (mét afleveraar, 2026-08-02), memoriaal-saldo-0
  (omzetmodule, 2026-08-07), het VGB-prefixfilter (e-mail-intake, 2026-08-07 — dekt het
  intake-kanaal; bij een latere leesroute uit gedeelde administraties dáár opnieuw toepassen)
  én btw-per-regel-=-factuur-btw (verkoop, blok A 2026-08-10 — categorie {S/E/Z/AE} + bedrag,
  eenhedennormalisatie fractie↔percentage in `app/sync/btw.py`, btw in het verkoopvoorstel
  auto-ingevuld + VERGRENDELD, ambiguïteit = eenmalige onthouden keuze per administratie,
  migratie 0038) én nooit-boeken-op-ankerdebiteur (route-A-nazorg 2026-08-14: verkoop-checks
  + `zorg_voor_debiteur`-slot + doorbelasting-whitelist-toets, bron `app/projecten/anker.py` —
  sinds de klant-loze schrijfroute (zelfde dag) een VANGNET: de motor maakt geen ankers meer
  aan, de checks blijven zolang er ergens een anker-debiteur bestaat)
  zijn gebouwd + getest; **per-leverancier-autoboeken-opt-in: GEBOUWD + GETEST (2026-08-09,
  migratie 0036 + `app/documenten/autoboeken.py`)** — boekt ná extractie uitsluitend bij
  opt-in aan (Beheerder-only, default UIT) + harde checks groen + voorstel volledig uit
  app-bevestigd boekingsgeheugen (seed-only/oranje weigert) + geen mogelijk-duplicaat/open
  vraag/afwijzing; volumerem en accorderingspoort onverkort; elk geval geauditeerd +
  tijdlijn-/werkvoorraadmarkering "automatisch". NB bank-autoboeken (opt-in per
  administrátie, vaste regels) staat hier los van (live sinds 2026-08-02).
  **Autoboek-kandidaten-motor (blok B 01-09, mockup `autoboek-kandidaten.html` = norm, migratie
  0095 — BESLISSINGEN "AUTOBOEK-KANDIDATEN-MOTOR" is canoniek):** `app/autoboek_kandidaten/` nomineert
  deterministisch (geen AI, geen RLZ-calls) per (administratie, leverancier) bij ≥ N opeenvolgende
  MENS-boekingen waarbij het geheugen-voorstel ongewijzigd is geboekt (N = Beheerder-instelling,
  default 5; correctie = teller opnieuw; automatisch telt niet) + volledig app-bevestigd geheugen +
  geen open vraag/afwijzing/duplicaatsignaal/veldwerker-koppeling. Dagelijks meeliftend in
  `sync-alles` (+ CLI `autoboek-kandidaten-herbereken`); scherm = het Autoboeken-nav-item
  (tabs Kandidaten/Actief/Heroverwegen, bulk "Autoboeken aanzetten (n)" mét LIVE hertoets per
  rij — niet meer kwalificerend = overgeslagen mét reden — via de BESTAANDE opt-in-schrijver;
  "Kandidaat verbergen" = snooze mét verplichte reden, filter "verborgen"; Heroverwegen =
  advies-only, uitzetten één klik mét audit). De per-leverancier-switch blijft op de
  administratie-detailpagina (tab Boeken & AI).
  **Automatisering-first (principe Peter, vastgelegd 2026-08-16, WERKWIJZE v1.10):
  mens-op-de-knop is een testfase-drempel en afwijkings-vangnet, geen einddoel — elk
  deterministisch pad krijgt een autoboek-opt-in volgens dit vaste patroon (default UIT,
  harde checks blokkerend, volumerem, 'automatisch'-markering + audit, storno als terugweg).
  Derde afnemer: verkoop-autoboeken (2026-08-16, zie "Verkoopfactuur-boekpad"); vierde:
  omzet-autoboeken (GO Peter 01-09, zie "Omzetboekingen"); doorbelasting-spiegels blijven
  gedocumenteerd-geparkeerd in BESLISSINGEN ("Autoboek-afweging overige deterministische
  paden") — bouw vergt apart akkoord.**
- **Vragenworkflow**: vraag blokkeert boeken, toegewezen aan eigenaar per administratie, antwoord
  voedt het geheugen. Vragen zijn een status in de werkvoorraad (geen apart menu).
  **DIALOOG (besluit Peter 25-08, migratie 0064 — herziet het één-antwoord-model van 14-07):**
  een vraag is een thread (append-only `vraag_bericht`, auteur + tijdstip per bijdrage, onbeperkt
  heen en weer; `aan_de_beurt` stuurt de bestaande melding `Document.toegewezen_aan`); de vraag
  blokkeert boeken tot **"Afgehandeld" door de oorspronkelijke vraagsteller** (server 403 voor
  anderen; systeem-vraag → toegewezene) — niet al bij het eerste antwoord. Controlescherm:
  tabs "Tijdlijn" (statusgebeurtenissen) en "Opmerkingen" (de threads, nieuwste onderaan). Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt B. **Vraag aan de klant-accordeur (26-08 blok B5,
  migratie 0079): toewijzen aan een accordeur = thread in de app (alleen eigen vragen zichtbaar),
  geen statusovergang op ter_accordering/geboekt, akkoord mogelijk, boeken wacht — zie
  "Accordeur-app-ronde 26-08" hieronder.**
- **Afwijzen** = verplichte reden, blijft zichtbaar ("Afgewezen — ter controle").
- **Verzamelbak "Niet toegewezen"**: alles wat niet eenduidig aan een administratie koppelt
  (tenaamstelling leidend, afzender = hint); leert van handmatige toewijzingen; "hoort niet bij
  ons" met reden. Nooit auto-toewijzen bij twijfel.
  **Bouwstatus: GEBOUWD + GETEST (2026-08-07, met de e-mail-intake)** — migratie 0028 +
  `backend/app/intake/` + `frontend/src/intake/`; details BESLISSINGEN "E-mail-intake +
  verzamelbak — GEBOUWD + GETEST". **Preview per rij (besluit Peter 25-08, D1): hover toont lazy
  de eerste PDF-pagina, klik de volledige weergave — leesroute `GET /verzamelbak/{id}/bestand`,
  fail-closed tot echte verzamelbak-documenten. Popup sinds 26-08 via `ui/basis/AnkerPopup.tsx`
  (portal + fixed, flipt aan de viewport-rand) — nooit meer een absoluut gepositioneerde popup
  bínnen `.tabel-scroll`/`table{overflow:hidden}` (feedbackronde 26-08 punt 2). **Toewijzen/hoort-niet
  OPTIMISTISCH (avondrun 26-08): rij direct weg, request async, mislukt = rij LUID terug mét rode
  reden; server idempotent (tweede klik = 200 `al_verwerkt` + rustige melding, conflicten in
  leesbare taal — geen enum-jargon); DB blijft bron van waarheid. Zie BESLISSINGEN "AVONDRUN 26-08".**
  **Foute toewijzing herstellen = "Verplaats naar andere administratie…" (⋯-menu controlescherm,
  besluit Peter 27-08, migratie 0080): alleen inkoopfacturen op te_controleren/handmatig_afmaken/
  klaar_om_te_boeken/vraag_open/afgewezen (geboekt = storno/tegenboeken, ter_accordering = eerst
  intrekken — server-side 409 mét uitleg); boek-/veldvoorstel vervallen en de extractie draait
  opnieuw achter de gates van het dóél; open vragen verhuizen mee; het toewijzings-geheugen
  corrigeert de regel die naar de oude administratie wees; RLS-doorbraak uitsluitend via de
  zelf-gepoorte SECURITY DEFINER-functie `boekhouding.verplaats_document` (bron-scope + status
  ontvangen). `app/documenten/verplaatsen.py`; BESLISSINGEN "KANTOOR-MINI-RUN 27-08" punt 5.
  Optionele checkbox "onthoud: deze tenaamstelling hoort bij <doel>" (default UIT, alleen de
  tenaamstelling, géén automatische leer-regel — werkstroom-run 27/28-08 punt 6a).**
  **Documentenlijst (werkstroom-run 27/28-08, punt 3/4): leverancier = vette hoofdregel, bestandsnaam ·
  bron · binnenkomst = metaregel; dichtheid normaal/compact per gebruiker (localStorage, geen
  migratie); status-dot "Geboekt" = `--ok`-groen (pil-chip blijft grijs); uploadzone één regel + ⓘ;
  verwijderen uitsluitend via het ⋯-rijmenu mét bevestiging en VERPLICHTE reden (server 422 zonder).
  Sorteerbare kolomkoppen (opruimrun 28-08 punt 21): Leverancier/Factuurdatum/Bedrag/Status/Toegewezen,
  klik = oplopend → aflopend → uit, pijl + aria-sort; de sortering is onderdeel van de lijstcontext
  (`sort=<kolom>:<richting>` in de URL) zodat ‹ ›, "n van m" en de na-boeken-doorloop dezelfde volgorde
  volgen. Administratie-kiezers zijn overal in de kantoor-UI een doorzoekbare combobox
  (`ui/AdministratieCombobox`, punt 13) — nooit meer een kale select.**
  Eigen naamnormalisatie: "Holding" blijft onderscheidend
  (mockup-casus); afzender-regel wijst alleen auto toe zonder tegenstrijdig
  tenaamstelling-signaal.
- **E-mail intake**: één centraal adres — **`facturen@ak-nijenhuis.nl`** (adreskeuze Peter
  2026-08-15, bewust kort; Google Workspace) — splitsen van multi-factuur-PDF's op
  factuurgrenzen, toewijzen op tenaamstelling.
  **Bouwstatus: GEBOUWD + GETEST (2026-08-07)** — .eml-upload (`POST /intake/eml` + werkvoorraad-
  uploadzone) is het werkende kanaal, idempotent op Message-ID; **de live IMAP-fetch is
  GEACTIVEERD (F3.4, 2026-08-15)**: echte imaplib-bron in `app/intake/postvak.py` (UNSEEN +
  BODY.PEEK, gelezen-vlag pas ná geslaagde verwerking = crash-veilige retry, zelfde
  idempotente codepad als de upload, systeem-actor, bron `imap`), job-config in deploy.yml
  (imap.gmail.com SSL 993, wachtwoord via secret `INTAKE_IMAP_WACHTWOORD`) — zie GCP_UITROL
  §F3.4-uitvoering; de .eml-upload blijft het lokale werkkanaal tot tranche 2. Routing per bijlage: kapotte/NLCIUS-invalide UBL → verzamelbak (§2d-
  failsafe), VGB → genegeerd-maar-zichtbaar, VASTLY-VERKOOP → soort 'verkoopfactuur' (het
  boekpad is sinds 2026-08-09 GEBOUWD — zie "Verkoopfactuur-boekpad" hieronder; een 381-
  CreditNote zit achter de config-gate `creditnota_381_ingeschakeld` — AAN sinds 2026-08-10
  na de golden-case-verificatie; uit-zetten kan via de env-var, gate dicht = zichtbaar in de
  verzamelbak), inkoop-UBL → tenaamstelling-toewijzing,
  PDF → intake-AI achter de platform-brede AVG-gate `intake_ai_ingeschakeld` (default UIT;
  sinds migratie 0029 een Beheerder-instelling `platform.intake_instelling` — knop op
  Instellingen + `make intake-ai-aan/-uit`, env-setting alleen nog fallback zolang die rij
  ontbreekt). Her-upload van een bericht dat op "bezig" bleef hangen (afgebroken run) wordt
  herverwerkt i.p.v. vroeg terug te keren, idempotent op (intake_bericht_id, sha256) —
  fix 2026-08-07. Multi-factuur-splitsing: AI-voorstel ALTIJD eerst ter controle, bevestigen =
  deterministische pypdf-splitsing, bron-document terminaal `gesplitst`.
  **Eén extractiepad voor álle ingangen (feedbackronde 26-08 punt 4):** mail/IMAP, sleepzone
  (`/intake/bestand`), klantpagina-upload, verzamelbak-toewijzen en splitsing lopen alle via
  `upload_document`/`start_extractie_na_toewijzing` achter dezelfde gates (per-administratie
  `ai_extractie_ingeschakeld` + API-key + AI-kostengrens) — regressietests per ingang in
  `tests/intake/test_extractie_per_ingang.py`. Grote documenten (> 3 MB / > 8 pag.) gaan naar de
  extractie-wachtrij: in de cloud sinds 26-08 de on-demand job `rlz-extractie-wachtrij` +
  */10-scheduler-vangnet (een in-process thread valt op Cloud Run met request-based CPU stil —
  dát was "geüploade factuur krijgt geen AI-extractie"); controlescherm toont een overgeslagen
  extractie mét reden.
  **Mail-body bij het boekingsvoorstel (feedbackronde 25-08 deel 3 punt 1, migratie 0069):**
  de intake bewaart de platte mail-body op `intake_bericht.body_tekst` (HTML → tekst, ruis
  deterministisch gestript — `app/intake/mailbody.py`), gedeeld door álle documenten uit die
  mail (FK), zichtbaar als inklapbaar blok "Uit de e-mail" op het controlescherm, en als HINT in
  toewijzing (uitsluitend een verzamelbak-suggestie `mail_body`, tenaamstelling blijft leidend)
  én AI-extractie (BSN-gefilterd, begrensd, achter de bestaande gates). Geen backfill.
  **Afbeeldingen (punt 2, migratie 0070):** JPEG/PNG/HEIC via mail én alle upload-zones →
  bij binnenkomst deterministisch + verliesvrij naar PDF (`app/documenten/afbeelding.py`,
  eigen PDF-writer; HEIC eerst naar JPEG) zodat de keten uniform PDF blijft; origineel =
  brondocument (`document.bron_*`, route `/bronbestand`); onbruikbaar → verzamelbak met reden
  (mailpad) of 422 (directe upload); inline logo's/< 600 px blijven `niet_verwerkbaar`. De
  werkvoorraad-sleepzone accepteert sindsdien ook losse PDF/UBL/foto via `POST /intake/bestand`
  (zelfde tenaamstelling-routing als een mailbijlage). Dependencies staan in `pyproject.toml`
  (geen requirements.txt) en worden bewaakt door `tests/unit/test_dependencies_gedeclareerd.py`.
  Zie BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 3".
- **AI-kostengrens intake (besluit Peter 2026-08-14, GEBOUWD + GETEST zelfde dag, migratie
  0047)**: Anthropic-API-kosten voor intake-AI max € 100 per kalendermaand (Europe/Amsterdam) —
  deterministische kostenmeter (`backend/app/aikosten/`): élke Claude-call append-only gelogd
  met wérkelijke token-usage (incl. cache), kosten in code uit gepinde prijstabel × gepinde
  USD→EUR-koers 1,00 (conservatief), harde poort vóór élke call ín de client (≥ limiet = call
  niet doen; onbekend model fail-closed). Boven de grens NOOIT stil wegvallen: zelfde pad als
  intake_ai=uit (verzamelbak-reden/chip "AI-limiet bereikt — handmatig verwerken"); 80%- en
  100%-melding éénmalig per maand (werkvoorraad-banner + audit); limiet Beheerder-only op
  Instellingen (verbruiksblok naast de AI-gate-knop). Tweede laag = klikwerk Peter: spend-limit
  ~$110 in de Anthropic-console. Zie BESLISSINGEN "AI-KOSTENGRENS INTAKE".
- **AI-schema's onder Anthropic's union-limiet (bugfix 31-08, BESLISSINGEN "BUGFIX 31-08"):**
  structured-output-schema's dragen max 16 union-/nullable-parameters (anyOf/type-array, ook in
  array-items) — het inkoopschema groeide met e/p/a naar 19 en élke extractie faalde met een 400.
  Het inkoopschema is sinds 31-08 sentinel-gebaseerd (verplichte strings, `""` = onbekend →
  deterministisch None); een NIEUW AI-veld nooit als nullable/union toevoegen maar via dit
  patroon. Testpoort: `tests/extractie/test_schema_unionlimiet.py` (alle live schema's ≤ 16 +
  fail-closed sweep op `json_schema=`-aanroepers). Nazorg-CLI `extractie-heraanbieden` biedt
  gefaalde extracties bulk opnieuw aan via de bestaande opnieuw-route. De teller/limiet leven
  sinds 31-08 runtime in `app/extractie/schema_poort.py` (de test importeert ze dáár) — de
  bewaking en de deploy-smoketest draaien dezelfde zelftest live.
- **Deterministische extractie-terugval — template per bekende leverancier (best-practice-besluit 2,
  31-08, GEBOUWD + GETEST 01-09, migratie 0094 — BESLISSINGEN "EXTRACTIE-TERUGVAL TEMPLATES" is
  canoniek):** `app/extractie/template_terugval.py` (pure logica) + `template_service.py` (DB/audit).
  Per crediteur (sleutel: btw-nummer > KvK-nummer uit `crediteur_kenmerk` — werkt dan over
  administraties heen — anders administratie+crediteur) leert het systeem uit de laatste N ≥ 3 door een
  MENS geboekte PDF-facturen ankers per kopveld uit de tekstlaag (label ervoor / label erboven /
  kolomkop, pypdf layout-modus); een template is pas geldig als hij álle N exact reproduceert
  (cent-exact, datums exact, referentie letterlijk) — anders géén template, nooit half. Runtime-volgorde
  per PDF (`documenten/service.py::_pdf_extractie_detail`): (a) geldig template + tekstlaag →
  template-parse mét interne validaties (excl + btw = incl cent-exact, vormpatroon referentie,
  geleerde btw-percentages, vervaldatum ≥ factuurdatum; één rood = VOLLEDIG verworpen + template
  ongeldig mét reden + audit) — NIET achter de AI-AVG-gate (lokale code, geen data naar buiten, werkt
  dus ook bij AI uit/limiet bereikt); (b) AI-pad ongewijzigd; (c) handmatig-pad ongewijzigd.
  Regelniveau alleen de veilige vorm (één regel = kop-totalen als álle leerdocumenten zo bevestigd
  zijn), anders kop-only + boekingsgeheugen. Crediteur-herkenning zonder AI: btw → KvK → IBAN → exacte
  naam, precies één kandidaat. Downstream ongewijzigd: zelfde veldvoorstel-contract (`bron:
  "template"`, zekerheid 1.0, `template`-blok), zelfde harde checks, autoboek-poorten tellen een
  template-extractie exact als een AI-extractie; chip "uit template" per veld, tijdlijn benoemt de bron.
  Leren/vervallen post-commit ná élke boeking (`boeken.py` → `leer_na_boeking_stil`): correctie door
  de controleur of layoutwijziging = ongeldig + direct opnieuw leren; `automatisch_geboekt` telt niet
  als leerbron; geen handmatig templatebeheer. Teller op Instellingen naast het AI-verbruiksblok ("N
  via template · M via AI · K actieve templates", `AiKostenStatusDto`). Bewaking-foutratio telt
  template-extracties niet als AI-poging. Tests: `tests/extractie/test_template_terugval.py` (pure,
  40) + `tests/documenten/test_template_terugval_pad.py` (keten, 9) + `tests/extractie/pdf_helper.py`
  (PDF-generator mét tekstlaag).
- **Best-practice-punten D1–D4 (01/02-09, BESLISSINGEN "BEST-PRACTICE-PUNTEN D1–D4"):** (D1) "Wat is
  nieuw" = hand-gecureerd `frontend/src/changelog/WAT_IS_NIEUW.md` (klantleesbaar, nieuwste bovenaan —
  **VERPLICHT bijvullen bij élke feature-commit**, guard-test op vorm/jargon), topbar-knop ✦ mét
  ongelezen-dot per gebruiker (localStorage, geen server-infra); (D2) maandagochtend-digest kantoor
  `app/berichten/digest.py` — weekmail per medewerker mét scope, alleen bij iets te melden, idempotent
  per ISO-week (`platform.kantoor_digest`, migratie 0097), opt-out `gebruiker.digest_opt_out` via
  `GET/PUT /auth/mijn/digest` + switch op Instellingen › Beveiliging, job `rlz-kantoor-digest` ma
  07:30 (CLI/make `kantoor-digest`); (D3) "Toon QR" = de bestaande uitnodigingslink als QR
  (`ui/QrLinkDialog.tsx`, /gebruikers + planning "+ ZZP'er"), geen nieuw auth-pad; (D4) badge-count
  app-icoon = open accorderingen in élke push-payload (APNs `aps.badge`, FCM `notification_count`) +
  reset/actualisatie in de app (`accordeur/appBadge.ts`, plugin `AppSlot.zetBadge`) — zichtbaar vanaf
  de volgende store-build.
- **Synthetische bewaking + alerting (best-practice-besluit 1, 31-08 — aanleiding: twee stille
  productie-incidenten 30/31-08; migratie 0092):** Cloud Run-job `rlz-bewaking` elk kwartier
  (`app/bewaking/`, statusrijen `platform.bewaking_probe_run`/`bewaking_storing`): health, DB +
  migratieversie, documentopslag-leesproef, mailkanaal-config, lichte RLZ-leesroute op de
  TEST-administratie (nooit writes); 1×/uur schema-zelftest + minimale echte AI-call
  (`claude-haiku-4-5`, onder de kostenmeter, bron `bewaking`) én het foutpiek-signaal
  (extractie-foutratio per uur ≥ 50 % bij ≥ 3 pogingen). Alerts via het eigen SMTP-kanaal naar
  p.nijenhuis@kempengroep.nl: pas bij 2 opeenvolgende fouten, idempotent per storing
  (kolom-is-None), expliciete herstelmelding. Job-exit-contract: falende probes = exit 0 (eigen
  alert); exit 1 alleen als de bewaking zelf niet draait → F3.2-vangnet. Post-deploy-smoketest
  in deploy.yml (health + gepoorte route moet 401 geven + one-off `rlz-smoketest`-job met de
  CLI `deploy-smoketest`) — een kapotte deploy is per direct luid rood. Zie BESLISSINGEN
  "SYNTHETISCHE BEWAKING + ALERTING".
- **Omzetboekingen** (kassarapporten, bijv. BLOW Margerapport): type in de werkvoorraad; boekt als
  SalesInvoice (omzet per categorie → omzet-GB, btw-code per categorie) + gekoppelde
  kostprijsmemoriaal (per productgroep aan voorraad), als één transactie. Periode uit rapport,
  duplicaatbewaking per periode, plausibiliteitscheck (marge vs historie). BLOW: cannabisomzet =
  "NL, Geen BTW (Vrijgesteld)" — bewust géén 0%-tarief (aangifte-rubriek).
  **Bouwstatus: omzetmodule GEBOUWD + GETEST (2026-08-07); boekt sinds 2026-08-09 als
  entity-loze Receipts (besluit Peter 2026-08-08 — kasomzet = losse boeking, geen
  dummy-debiteur)** — migraties 0027 + 0031, `backend/app/omzet/` + `frontend/src/omzet/`;
  details BESLISSINGEN "Omzetmodule — GEBOUWD + GETEST". Kernfeiten (api-verkenning
  "Omzetmodule STAP 0" + "Receipts-verkenning" incl. aanvulling 2026-08-09): verkoopboeking =
  PUT SalesInvoices zónder Entity, mét administratie-specifieke DocumentCategory
  "Verkoopfactuur (Omzet)" (selectie DocumentType 10 + naam, GUID gecachet in
  omzet_instelling, nooit hardcoden; ⚠️ HasSystemId is dáár geen bruikbaar selectieveld);
  `Reference` = RLZ's eigen verkoopnummering (`InvoiceNumber` wel expliciet zetbaar,
  nummer-botsing deterministisch hersteld — InvoiceNumber is op de Receipts-collectie niet
  filter-/sorteerbaar, dus herstel blijft max(SalesInvoices-collectie, lokaal)+1);
  duplicaatbewaking = lokaal per periode (DB-uniek) + eigen client-GUID +
  memoriaal-Reference-check + Receipts-prefix-check (deterministische periode-marker
  `OMZ-…-VK` als PREFIX in regel 1 + `startswith`-filter — **verkoop-STAP-0 2026-08-09: RLZ
  negeert de document-Description en leidt 'm af uit de éérste regel-Description**; de
  Receipts-collectie ziet — anders dan SalesInvoices — óók API-documenten). De
  systeemdebiteur "Kasomzet" wordt niet meer aangemaakt (instelling-kolommen gemarkeerd
  vervallen; bestaande RLZ-debiteuren blijven staan — nooit verwijderen). Kassabedragen incl.
  btw → splitsing in code; één-transactie-garantie volledig in de app (memoriaal faalt →
  storno verkoop, storno faalt óók → zichtbaar `half_geboekt` + `make omzet-reconciliatie`).
  Mapping-loze categorie = blokkerende check + automatische vraag. De SalesInvoice-motor
  blijft herbruikbaar (customer_id optioneel) — het Vastly-verkooppad hieronder draait erop.
  **Omzet-autoboeken (GO Peter 01-09, migratie 0096 — BESLISSINGEN "OMZET-AUTOBOEKEN"):** opt-in
  per administratie `omzet_autoboeken_ingeschakeld` (Beheerder-only, default UIT, overal UIT tot
  Peter activeert; toggle op de Boeken & AI-tab van de detailpagina + `make omzet-autoboeken-aan/
  -uit`). `app/omzet/autoboeken.py` boekt ná de rapport-extractie (vóór de mapping-autovraag)
  uitsluitend als álles groen is: categorie-mapping volledig MENS-bevestigd (herkomst 'mapping' op
  élke regel — 'nieuw' of een mens-opgeslagen voorstel weigert), voorraad-GB ingesteld, geen
  duplicaat/vraag/afwijzing, en daarna de bestaande motor mét álle harde checks (incl.
  memoriaal-saldo-0, duplicaat per periode, marge-plausibiliteit) + volumerem; één-transactie-
  garantie ongewijzigd; half geboekt = audit `autoboeken_half_geboekt` + bewakings-alert (nooit
  stil); `automatisch_geboekt` + bron `omzet_opt_in` op de GEBOEKT-overgang (zelfde chip/audit/
  tijdlijn).
- **Verkoopfactuur-boekpad (Vastly, §2d)** — **GEBOUWD + GETEST (2026-08-09)**: migratie 0035 +
  `backend/app/verkoop/` + `frontend/src/verkoop/`; details BESLISSINGEN
  "Vastly-verkoopfactuur-boekpad". Boekt een VASTLY-VERKOOP-document als SalesInvoice MÉT
  Entity = de échte huurder (idempotente debiteur-aanmaak uit de UBL: lookup-vóór-PUT +
  deterministisch client-GUID — géén verzameldebiteur, besluit Peter 2026-08-08); GB per
  regel deterministisch uit `cbc:AccountingCost` (onbekende code = blokkerend + automatische
  vraag; ontbrekende code = mens kiest), btw uit de UBL-regels (ondubbelzinnige
  percentage-match, anders mens); harde checks conform inkoop + creditnota-herleiding;
  duplicaatbewaking lokaal DB-uniek per (administratie, Vastly-nummer, soort) + Receipts-
  prefix-check (marker `VASTLY-VERKOOP {nr} ·` in regel 1). CreditNote 381 = negatieve
  tegenboeking op dezelfde debiteur, herkenning achter config-gate
  `creditnota_381_ingeschakeld` (AAN sinds 2026-08-10). `factuur_geboekt`-webhook vuurt óók hier
  (referentie = Vastly-factuurnummer). STAP-0-feiten: api-verkenning "Verkoopfactuur-boekpad
  STAP-0" (o.a. Entity alleen zichtbaar mét `$expand`; document-Description afgeleid van
  regel 1). Golden-case-verificatie tegen de échte Vastly-UBL's: UITGEVOERD 2026-08-10
  (blok D — intake-routing 4×380 + 2×381 én live boek-/credit-/stornocyclus op de
  TEST-administratie; zie BESLISSINGEN).
  **Verkoop-autoboeken (besluit Peter 15-08, GEBOUWD + GETEST 2026-08-16, migratie 0051 +
  `app/verkoop/autoboeken.py`)**: opt-in per is_vastgoed-administratie
  (`verkoop_autoboeken_ingeschakeld`, Beheerder-only, default UIT — aanzetten kan alléén
  bij is_vastgoed) — ná intake boekt het document automatisch uitsluitend als álles groen
  is: harde checks, per regel GB-code 'bekend' én btw vergrendeld uit de UBL (bron
  'factuur' of de eerder mens-bevestigde 'onthouden'-keuze), geen open
  vraag/afwijzing/duplicaatsignaal, geen mens-opgeslagen voorstel; creditnota's alleen via
  de groene herleiding-check. Elk ander geval → werkvoorraad, nooit stil; elke poging
  geauditeerd, GEBOEKT draagt `automatisch_geboekt` (chip "automatisch"), webhook identiek.
  Toggle op Instellingen + `make verkoop-autoboeken-aan/-uit`; staat overal UIT
  (testperiode) tot Peter per administratie activeert. Zie BESLISSINGEN
  "VERKOOP-AUTOBOEKEN OPT-IN".
- **Bank**: klantenlijst → rekening (alle `PaymentAccounts` incl. kas). Voorstel-volgorde:
  1) exacte match naam+factuurnr+**bedrag** → auto-afletteren; 2) gedeeltelijke match → bevestigen;
  3) vaste regels (geheugen; na 3× zelfde handmatige boeking regel voorstellen); 4) RLZ's eigen
  voorstel (bron tonen — **schrijf-PoC 2026-08-02: voedingsbron bestaat wél, auto-gevuld
  `MatchedPaymentItem` bij exacte bedrag-match — de eerdere STAP-0-conclusie "geen voedingsbron"
  is herzien**); 5) handmatig. Afletteren gaat NIET door de klant-accorderingsflow.
  **Bouwstatus: bankmodule GEBOUWD + GETEST (2026-08-02); afletteren-tegen-open-post sinds
  2026-08-09 ÉCHT via de API (seam-swap na de capture-replay — zie "Reeleezee API" hierboven
  en BESLISSINGEN "Afletteren-tegen-open-post: GEKRAAKT")** — `backend/app/bank/` +
  `frontend/src/bank/` + migratie 0026. De seam
  (`app/bank/afletteren.py::voer_afletter_actie_uit`) legt de koppeling via
  `RlzClient.link_payment_item` mét directe verificatie (OpenAmount-hertoets +
  PaymentReferenceList-leesspoor); het assist-pad is de expliciete FALLBACK bij een API-fout
  (opdracht blijft zichtbaar klaargezet mét foutmelding; de sync-verificatie dekt die route).
  Vóór elke link-call een vooraf-toets tegen de ACTUELE RLZ-staat (kliktest-fix 2026-08-09:
  "Nu afletteren" op een intussen al afgeletterde mutatie gaf een kale 404 — géén
  casing-probleem, client gepind op de bewezen `/Actions`-vorm): mutatie al dicht →
  "geverifieerd — al afgeletterd in RLZ" (geen fout, eigen chip), doel-post niet meer in de
  open-items-collectie → duidelijke fout vóór de call; verse OpenAmount leidend voor
  LinkedAmount.
  Stap 1 (exacte match) lettert automatisch af tijdens de bank-sync achter de opt-in
  `bank_autoboeken_ingeschakeld` + eigen volumerem, vóór de vaste regels; zonder opt-in en
  voor stap 2 (deelmatch, LinkedAmount = min(|mutatie|,|post|)) is het één-klik — nooit auto.
  Stap 3/5 = direct-op-grootboek, echt gebouwd (deterministisch client-GUID, failsafes +
  volumerem + duplicaatchecks tegen verse RLZ-staat, storno actie 19 met verplichte reden);
  autoboeken van vaste regels = opt-in per administratie (zelfde vlag, default UIT, bovenop
  de boeken-failsafes).
  Vastly-terugkoppeling: `factuur_afgeletterd`-event via de bestaande webhook-afleveraar
  (detectie op documentstatus 3; formele opname in koppelcontract §3 nog af te stemmen met
  vastgoed). Failsafe: `make bank-reconciliatie` vangt in de RLZ-UI teruggedraaide
  boekingen/afletteringen. Zie api-verkenning.md "Bankmodule schrijf-PoC" + "Bankmodule
  FALLBACK-PoC" en BESLISSINGEN "Bankmodule — GEBOUWD + GETEST".
  **Bank-verdieping feedbackronde 25-08 deel 4 (besluiten Peter, GEBOUWD + GETEST 2026-08-25,
  migratie 0071 — BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 4" is canoniek; RLZ-feiten in
  api-verkenning "Bankmutatie op een RELATIE + mutatie SPLITSEN — STAP-0 (25-08)"):**
  (2) **auto-verversing bij openen** — cache direct + "laatst ververst HH:MM", 202+status-poll
  (`app/bank/sync_run.py`, tabel `bank_sync_run`, job `rlz-bank-sync`/CLI `bank-sync-wachtrij`),
  drempel `bank_auto_ververs_drempel_minuten` = 5 (jongere sync = `overgeslagen`) — **HERZIEN 01/02-09
  (blok E, BESLISSINGEN "BANKSCHERM BLOK E"): de knoppen "Verversen uit Reeleezee"/"Nu verifiëren" zijn
  weg; versheid + klein ⟳ (noodrem, `?forceer=true` slaat alleen de drempel over) staan vast in de
  paneelkop, de verificatie van wachtende afletteropdrachten lift in élke ronde mee (`afletteren_wachtend`,
  alleen gemeld als er iets wachtte), succes = toast, fouten persistent; voorstel-kaart mét doel-post-specs
  uit `payment_item_cache` (`bank/doelpost.py`, mockup `bank-voorstel-kaart.html`), match-chip
  groen/oranje, deelmatch "restant € X blijft open" + "Afletteren (deel)", geen match = tekstregel, zelfde
  kaart in splitsen (`VoorstelKaart.tsx`)**; (3) **derde verwerkroute "Koppel aan relatie"** — RLZ kent geen relatie-boeking zonder
  document (Entity op BMDB/memoriaal = 500), de bewezen vorm is het **aanbetalingsdocument**:
  PurchaseInvoice (crediteur, één regel op systeemrekening 1403, expliciet 0%-"Nul tarief" —
  zonder tarief rekent RLZ 21%) resp. SalesInvoice (debiteur, 1806) + actie 15; verrekening =
  tegenregel −X op 1403 ín de latere factuur (actie 34 blijft dood); storno = actie 19 op het
  aanbetalingsdocument (mutatie volledig terug); de open aanbetaling per relatie leeft in
  `bank_relatie_boeking` (`app/bank/relatie.py`), zichtbaar in het paneel "Openstaande
  aanbetalingen" + **aanbetaling-open-signaal op het controlescherm** (`aanbetaling_signaal.py`,
  Entity + leverancier-IBAN, knop "Verrekenregel toevoegen", hook `markeer_verrekend_bij_boeking`
  ín de boek-transactie) — signaal, geen blokkade, geen werkvoorraad-chip; (4) **splitsen** —
  geordende compositie open posten → relaties → grootboek via de bestaande motoren
  (`app/bank/splitsen.py`; Σ delen = mutatie server-side blokkerend; half-verwerkt zichtbaar +
  hervatten; storno per deel — een afletter-deel alleen via storno van de factuur in RLZ).
  ⚠️ **Nieuw RLZ-feit: her-PUT op een gestorneerd BankMutationDirectBooking = 204 zónder effect
  (actie 17 = 409)** → de directe boeking gebruikt sinds 25-08 een **cyclus-GUID**
  (`rlz_bank_boeking_cyclus_id`) én verifieert ná élke PUT de verse OpenAmount; deel-BMDB's
  accepteren een deelbedrag. Storno van een factuur-deel op een meervoudig gekoppelde mutatie
  laat OpenAmount tijdelijk stale (huls) — reconciliatie-aandachtspunt (parkeerpost).
- **Kempen-doorbelasting (besluit Peter 2026-08-13, hoort bij de livegang; canoniek
  `verkenning/16_DOORBELASTING_KEMPEN.md` + BESLISSINGEN "KEMPEN-DOORBELASTING")**: tweezijdige
  motor op het HUIDIGE patroon (2025/2026, granulair per document; historie = archief). Actie
  "Doorbelasten…" op een GEBOEKTE inkoopfactuur (toggle per bron-administratie, default UIT —
  alleen Kempen Facilities) **én — besluit Peter 25-08, herziet 13-08 — het optionele
  controlescherm-blok "Doorbelasten na boeken" op een NOG NIET geboekt document (run-fase
  `klaargezet`, migratie 0065): boek- en doorbelasting-checks samen groen → knop "Boeken +
  doorbelasten" → orkestratie `app/doorbelasting/orkestratie.py` draait beide bestaande
  motoren in één gang (inkoop → verkopen → spiegels; fout ná de inkoopboeking = zichtbaar op de
  run, half-geboekt-patroon); bij klant-accordering gaat de verdeling mee (accordeur ziet ze
  alleen-lezen, bevroren tot het besluit) en boekt alles ná het laatste akkoord. Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt A** →
  regelverdeling in % (exact 100%, grootste-rest-centen) over de geseede mapping-whitelist
  (doelentiteit ↔ customer-GUID, server-side afgedwongen, `make doorbelasting-seed-kempen`;
  **sinds 01-09 óók via "+ Doelentiteit toevoegen" op Instellingen › Doorbelasting — mockup
  `doorbelasting-doel-toevoegen.html` = norm, Beheerder-only POST naast het wijzig-endpoint:
  debiteur-lookup op naam in de bron-RLZ mét deterministische bijna-match (Mantelzorg-les
  enkelvoud/meervoud: match altijd expliciet bevestigen, nooit stil koppelen), geen match =
  idempotente aanmaak via `zorg_voor_debiteur`, provisie-GB vooringevuld op rekeningcode,
  IC default aan — BESLISSINGEN "GECOMBINEERDE RUN 01-09" blok B**) →
  per doelentiteit: verkoopfactuur in de bron (kostenregels + losse provisieregel, provisie-%
  en vlak btw-tarief als config) + spiegel-inkoopfactuur in de doel-administratie (idempotente
  crediteur-aanmaak, Reference = verkoopnummer — bron éérst, STAP-0 2026-08-13),
  half-geboekt-patroon omzetmotor + `spiegel_open`-taak bij niet-onboarded doel (nooit stil
  half), storno beide kanten (reden verplicht), `make doorbelasting-reconciliatie` (vierde
  bron in reconciliatie-alles). **Spiegel-webhook (akkoord Peter 2026-08-14, gebouwd + getest
  zelfde dag, migratie 0046)**: een spiegel-inkoopfactuur in een `is_vastgoed`-doel vuurt óók
  `factuur_geboekt` (standaard inkoop-veldvorm, leverancier = Kempen Facilities, referentie =
  spiegel-Reference) — `webhook_uitgaand.administratie_id` draagt dan de dóél-administratie
  (document_id blijft het bron-document); afleveraar levert per coalesce onder het doel,
  nooit dubbel. Koppelcontract v1.13 §3 "Doorbelasting-spiegelkant". **Spiegelkant geverifieerd via Rubicon (§2c)**: kosten-GB's
  type 2 (géén activering), 21% aftrekbare voorbelasting, eigen provisierekening 4808;
  ⚠️ RC geldt dáár niet → **intercompany-vlag per mapping-rij** (blok 2, migratie 0045):
  IC-open-posten uit álle afletter-voorstellen + fail-closed poort
  (`IntercompanyPostUitgesloten`); `payment_item_cache.entity_guid` via geneste expand
  `Document($expand=Entity)`. Bouwstatus: blokken 0–2 gebouwd 2026-08-13 (migraties
  0044/0045), UI + motor-tests in afronding — zie BESLISSINGEN.
  **GEACTIVEERD (onboarding-batch 2026-08-15, BESLISSINGEN "ONBOARDING-BATCH 15-08"):**
  Facilities + 5 doelen (Molenhof B/V, Oirschot Recreatie, OVB, Veldhoven) onboarded
  (smoketest-protocol: rechten-probe, syncs, TEST-boeking+storno geverifieerd), whitelist
  geseed + live geverifieerd, per rij provisie-GB (4173/4808) + IC-vlag (álle 5 doelen hebben
  RC Kempen Facilities — anders dan Rubicon, dus IC=true; alleen Rubicon-rij false; §2c-vervolg
  in verkenning/16), toggle AAN alleen Facilities. ⚠️ Drie doelen activeren deels op
  AccountType-3-rekeningen (spiegelverdeler kiest dan een activarekening). NIJENHUIS
  (kantoor-administratie) na credential-herstel zelfde dag alsnog onboarded — 11/11.
  **Kliktest Peter UITGEVOERD (2026-08-16, volledige cyclus geslaagd; nazorg in twee rondes
  — BESLISSINGEN "Doorbelasting-kliktest-nazorg" (ronde 1: opslag-bug + client-validatie) en
  "ronde 2")**: "verkopen op concept" = correct gedrag ná Peters eigen storno;
  RLZ-UI-vindbaarheids-hypothese (ontbrekende DocumentCategory) WEERLEGD — beide kanten
  krijgen automatisch de categorie/boekstuk-reeks van Peters historische praktijk
  (api-verkenning "DocumentCategory & boekstuk-reeksen": reeks-prefix volgt de categorie;
  Verkopen→Facturen-lijst toont API-facturen sowieso niet, dat is RLZ-collectie-gedrag);
  storno beide kanten geverifieerd (5 spiegels Status 1; bron-concepten daarna handmatig in
  de RLZ-UI verwijderd — bevestiging Peter open). **Randgeval storno-ná-btw-aangifte
  (vraag Peter 15-08) ONDERZOCHT: RLZ weigert actie 19 NIET** — het verschuift de
  terugdraai-btw zelf als negatieve TaxSource naar de eerstvolgende open aangifte-periode
  (api-verkenning "Actie 19 in een periode met ingediende btw-aangifte"); foutvertaling +
  alles-of-niets-zorg vervallen. **Vervolg-besluit Peter 15-08, GEBOUWD + GETEST 2026-08-16:
  harde STORNO-BLOKKADE ná ingediende aangifte** — poort `app/rlz/aangifte.py` (TaxDeclarations
  Status 2/3 dekt de boekdatum = storno geblokkeerd, fail-closed bij onleesbaarheid, 404/
  concept vrij) vóór álle bestaande storno-paden: bank-direct én doorbelasting (alles-of-niets
  over bron + doel, per kant zichtbaar waarom; UI-knop disabled mét melding via de
  storno-toets-leesroute; interne rollback-storno's ín een boek-transactie bewust niet gepoort
  — btw-netto-nul). **Het tegenboek-pad is GEBOUWD + GETEST
  (2026-08-22, migratie 0061 — mockup tegenboek-mockup.html; het suppletie-signaal is
  definitief GESCHRAPT, besluit Peter 22-08): is storno door de aangifte-poort geblokkeerd,
  dan biedt het controlescherm (en het ⋯-menu in het archief) "Tegenboeken…" — een NIEUWE
  PurchaseInvoice met gespiegelde negatieve regels op dezelfde Entity, boekdatum vandaag
  (btw = negatieve voorbelasting in de open periode, STAP-0 api-verkenning "Tegenboek-pad
  STAP 0"); volledig (chip TEGENGEBOEKT + kruisverwijzing) óf tegenboeken-én-opnieuw-boeken
  (GEBOEKT→te_controleren, boek_cyclus+1 — herboeking op een eigen RLZ-GUID, uitgezonderd
  van het duplicaatsignaal); harde checks onverkort, verplichte reden, betaalstatus-
  waarschuwing (open creditpost); vastgoed krijgt het als factuur_geboekt-event met
  negatieve regels (creditnota-norm §3a) mét — sinds 2026-08-23, akkoord Vastly, schema
  1.1→1.2/contract v1.17 — het optionele veld `corrigeert_document_id` (= rlz_document_id
  van het origineel, UITSLUITEND op tegenboeking-events; de herboeking draagt het níét),
  bewust géén factuur_gestorneerd. Zie BESLISSINGEN "TEGENBOEK-PAD".** Kliktest-herstart geverifieerd (BESLISSINGEN
  "KLIKTEST-HERSTART"): her-PUT op een bestaand concept vervángt de DocumentLineList (live
  bewezen, api-verkenning "Her-PUT op een bestaand concept"). **Kliktest 2 strandde alsnog
  op de bijlage-upload (nazorg ronde 3, gefikst + getest 2026-08-16): RLZ's /Uploads kent
  géén her-PUT** (bestaand GUID = 400, verbruikt GUID van een verwijderd document = 404;
  api-verkenning "Uploads bij een herstart-boekcyclus") — bijlage-idempotentie loopt sindsdien
  in álle motoren via `app/rlz/bijlage.py::zorg_voor_bijlage` (aanwezigheids-check via de
  Uploads-leesroute + deterministische cyclus-GUID's). **RECHTSGELDIGE FACTUUR-PDF (blok A
  gecombineerde run 26-08, besluit Peter, migratie 0077 — BESLISSINGEN "GECOMBINEERDE RUN
  26-08" blok A is canoniek):** ná de verkoopboeking rendert de motor RLZ's eigen factuur
  (`GET SalesInvoices/{id}/Download` mét `Accept: application/pdf` — route A; stamgegevens/
  btw-nummer zijn via de API níét leesbaar, dus geen eigen generator), toetst deterministisch
  op de gerenderde tekst (nummer = spiegel-Reference, KvK, btw-nummer, geboekte bedragen
  cent-exact) en zet 'm als bijlage op BEIDE kanten (spiegel: eerste bijlage, bon tweede;
  `zorg_voor_bijlage(op_bestandsnaam=True)` = meerdere bijlagen per document); ontbreekt =
  `factuur_pdf_status ontbreekt` mét reden, nooit blokkerend; download op de run; nazorg
  `make doorbelasting-facturen-herstel` (`DRY_RUN=1` eerst). `app/doorbelasting/factuur.py`.
  **Opruimlijst achtergebleven
  RLZ-concepten (2026-08-16): de doorbelasting-reconciliatie signaleert Status-1-concepten
  van gestorneerde/vervallen runs (beide kanten, informatief — nooit exit 1) + scanknop op
  Instellingen → Doorbelasting; de app verwijdert NOOIT in RLZ (kernprincipe 3, expliciet
  herbevestigd door Peter) — opruimen is klikwerk in de RLZ-UI, indien gewenst.**
  **Doorbelasting × projecten (besluit Peter 25-08 "optie 2", GEBOUWD + GETEST 2026-08-25,
  migratie 0067 — BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 2" punt 2 is canoniek):** per
  verdeelregel een project uit de DOEL-administratie (verplicht + blokkerende check zodra dat
  doel `project_verplicht` aan heeft; spiegel-regels dragen `Project:{id}`, webhook `project_id`
  per regel), multi-project binnen een doelentiteit (alle actieve projecten; basis naar rato
  contract-m² — ontbrekende m² = geweigerd, nooit gokken — óf gelijk per object; centen
  server-side via de herbruikbare pure motor `app/doorbelasting/verdeelhulp.py`; één
  spiegel-regel per project), verdeelsleutels per bron-administratie (naam + versie,
  append-only, één klik toepassen, herleidbaar op de run + audit). Verdeelhulp-UI voor gewone
  regel-splitsing zonder doorbelasting = parkeerpost.
- **Afdelingen binnen een administratie (bouwrun 28-08 blok A, mockup `afdelingen.html`,
  migratie 0084, casus Kempen Facilities):** toggle `afdelingen_ingeschakeld` op het
  project_verplicht-patroon — AAN = afdeling verplicht op élk inkoopdocument (harde check
  "Afdeling", óók als poort bij ter accordering vanaf klaar_om_te_boeken) + accorderingsroute per
  afdeling (`accordering_laag.afdeling_id`, vervángt de administratie-route; terugval "Algemeen"
  ontstaat automatisch en volgt de administratie-route; afdeling zonder route = expliciete fout);
  afdelingen archiveren, nooit verwijderen; keuze handmatig per document mét prefill uit het
  leverancier-geheugen (`leverancier_afdeling`, chip "vorige keuze bij …", nooit auto-toewijzing);
  staande goedkeuringen tellen alleen binnen de afdeling waar afgegeven; afdeling wijzigen ná
  aanbieden = ronde vervalt mét reden; accordeur-app = één kaart per (administratie, afdeling).
  Geen backfill. `app/afdelingen/`; BESLISSINGEN "BOUWRUN 28-08 AVOND" blok A.
- **Klant-autorisatie (à la Zenvoices), optioneel per administratie**: accordeurs per klant,
  sequentiële lagen met voorwaarden (bedragdrempels). Boekknop wordt "Ter accordering"; na laatste
  akkoord automatisch boeken (harde checks draaien opnieuw). **Configuratiewijziging (lagen/toggle)
  laat lopende rondes expliciet VERVALLEN (werkstroom-run 27/28-08 punt 2a, casus 34 facturen):
  status `vervallen`, document terug naar klaar_om_te_boeken, tijdlijn mét reden
  "accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist" + batch-id, eenmalige banner op de
  documentenlijst (`GET …/accordering/vervallen-meldingen`); herstelroute = bulk "Ter accordering
  aanbieden" op de tab Klaar om te boeken (`POST …/accordering/documenten/bulk-aanbieden`, zelfde
  poorten per document, overgeslagen mét reden — punt 2b).** **Bulk instellen (01-09, mockup
  `bulk-accordering.html` = norm): de bulk-selectie van administraties-v2 draagt
  "Klant-accordering instellen…" — één dialoog past de lagen toe op álle geselecteerde BV's
  (Beheerder-only endpoints; orkestratie over de bestaande configuratieroute, geen tweede
  schrijver): ontbrekende accordeur-scope aangemaakt mét expliciete vink (trigger-audit; zonder
  vink = BV overgeslagen mét reden), bestaande config VERVANGEN mét vooraf de telling vervallen
  rondes (bestaand vervallen-patroon), toggle aan waar uit; preview = resultaat-weergave,
  deelfout per BV zichtbaar. Zie BESLISSINGEN "GECOMBINEERDE RUN 01-09" blok A.** **Ná het laatste akkoord BLIJFT het
  document op ter_accordering tot de boeking staat (bugfix-run 28-08 — vóór de fix ging het éérst
  naar klaar_om_te_boeken en bleef het dáár stil hangen zodra de boekpoging faalde; casus Kempen
  Facilities 27-08, ±42 documenten): elke mislukking = persistente `boek_fout` op de ronde +
  tijdlijnreden + audit, controlescherm-sectie mét "Opnieuw boeken (klant-akkoord compleet)", lijst-chip
  "boeken ná akkoord mislukt"; poort telt alleen de LAATSTE ronde én het bedrag mag niet gewijzigd zijn;
  élke ⚙-systeemovergang draagt een `reden` (vangnet in `_schrijf_overgang`); herstel bestaande gevallen
  = `make accordering-herstel-boeken DRY_RUN=1` eerst, uitvoeren alleen op Peters go — BESLISSINGEN
  "BUGFIX-RUN 28-08".** **Opruimrun 28-08 (punten 24 + 23): een compleet, nog niet verzilverd
  klant-akkoord (laatste ronde afgerond, bedrag ongewijzigd, sinds die afronding niet geboekt) kan
  NIET opnieuw ter accordering — losse route 409 `KlantAkkoordAlCompleet` "boek het direct", bulk =
  overgeslagen mét reden, lijst-checkbox uit mét uitleg (`klant_akkoord_compleet`); boeken kan wél.
  Volumerem: de teller telt alleen échte overgangen niet-geboekt→geboekt; boekingen ná een compleet
  klant-akkoord (accorderingspad, herstel-CLI, meelopende doorbelasting in dezelfde gang) vallen
  onder een eigen NOODREM `max_boekingen_na_klant_akkoord_per_dag_per_administratie` = 200 i.p.v. de
  20/dag-automatiseringsrem — de mens heeft al per document op de knop gedrukt; autoboek-paden
  (opt-ins, bank, verkoop) blijven onverkort onder de 20-rem. BESLISSINGEN "OPRUIMRUN 28-08".**
  Klant-app = PWA + store-apps
  (besluit Peter 2026-08-14: de accordeur-app wordt óók uitgebracht als native App Store- én
  Google Play-app; de gebouwde PWA/webcode is de basis via een native schil, bv. Capacitor —
  PWA blijft interim + terugval; aandachtspunten native passkey-integratie (WebAuthn in een
  webview is beperkt) en store-accounts onder de juiste entiteit; planning ná GCP —
  **voorverkenning UITGEVOERD 2026-08-16: Capacitor-schil staat in `native/` (webcode niet
  geraakt), beslispuntenrapport `verkenning/17_NATIVE_STORE_APP_ACCORDEUR.md` = basis voor
  het go/no-go-bouwbesluit; GO Peter 2026-08-16 (aanbevolen route: native-passkey-plugin +
  APNs/FCM + gebundelde assets + bearer-refresh Keychain/Keystore, bundle-id
  `nl.aknijenhuis.goedkeuren`) — bouwstatus per fase: verkenning/17 "Bouwstatus" +
  BESLISSINGEN "NATIVE-APP FASE 1–5" (alle vijf 2026-08-17): fase 1 snelheidslaag PWA
  GEBOUWD+GETEST (optimistisch akkoord/afwijzen via achtergrond-verzendrij met begrensde
  retry, definitief mislukt = zichtbaar terug in de rij; prefetch/prerender eerstvolgende
  factuur; backend-idempotente besluit-herhaling `_herhaald_besluit`; dubbeltik-vangnet);
  fase 2 native passkey-plugin (eigen dunne Swift/Java-plugin, webcode-seam getest,
  well-known-routes fail-closed); fase 3 native push (migratie 0055 subscriptie-soort
  apns/fcm, adapters, kill-switch dekt web én native); fase 4 (VITE_API_BASE,
  bearer-refresh via X-Refresh-Token + Keychain/Keystore-plugins, web-contract ongewijzigd
  + bewaakt); fase 5 VOORBEREID (`native/STORE_GEREEDHEID.md`, assets uit één SVG-bron).**
  **Kliktests echt iPhone-toestel rondes 1+2 (2026-08-17) VOLLEDIG GROEN — fases 1–4
  BEWEZEN OP TOESTEL** (passkey-Face-ID, koude-herstart-Keychain-refresh, safe-area,
  meldingen-flow + APNs-push + deep-link, PWA-passkey in native, kill-switch — BESLISSINGEN
  "NATIVE KLIKTEST RONDE 1/2"); **TestFlight LIVE via Xcode Cloud (23-08, workflow main →
  TestFlight intern) mét `APNS_SANDBOX=false` afgerond — native push op productie-APNs,
  web-push/VAPID ongewijzigd (BESLISSINGEN "XCODE CLOUD")**; **Android-bouwronde 28-08
  VOORBEREID (BESLISSINGEN "ANDROID-BOUWRONDE 28-08", draaiboek `native/PLAY_DRAAIBOEK.md`):
  Firebase in HETZELFDE GCP-project (Analytics UIT), `google-services.json` gecommit,
  google-services-plugin hard, `POST_NOTIFICATIONS` + monochroom statusbalk-icoon; FCM-verzendkant
  LIVE via Application Default Credentials van run-backend@/run-jobs@ (IAM
  `roles/firebasecloudmessaging.admin`, alleen `FCM_PROJECT_ID` — géén server-key-secret;
  `scripts/gcp/fcm_afronden.sh`); Gradle-signing leest `keystore.properties` (gitignored,
  keystore buiten de repo — `native/scripts/android_keystore.sh`), release-AAB via
  `bouw_android_release.sh`. **UITGEVOERD 29-08 (besluit Peter "installs toegestaan"): JDK 21 +
  SDK via CLI (openjdk@21 keg-only → JAVA_HOME/ANDROID_HOME per shell, draaiboek §1), `assembleDebug`
  groen (Java-plugins compileren zonder fix), upload-keystore in `~/Sleutels/` (wachtwoord alleen
  dáár), release-AAB vc1/1.0 gevalideerd, drie Play-screenshots uit de emulator. Android-fixes uit
  die run: pdf.js LEGACY-build in beide viewers (hoofdbuild vereist `Uint8Array.toHex`, Chromium ≥
  140 — WebView 133 brak het factuurbeeld) + ⏻-glyph → `UitlogIcoon` (SVG). Debug-only
  cleartext-overlay `app/src/debug/` + env-vlag `NATIVE_LOKALE_BACKEND` voor lokale
  emulator-builds; release-script bewaakt dat beide NIET in de AAB zitten.** **Interne
  Play-testrelease LIVE (30-08); assetlinks + WebAuthn-origins (BESLISSINGEN "PLAY-NAZORG 30-08"):
  `ANDROID_CERT_SHA256_VINGERAFDRUKKEN` in deploy.yml draagt BEIDE certificaten (Google
  app-signing-key + upload-key) en is de ENIGE bron — `app/auth/android_signing.py` leidt daaruit
  de assetlinks-statement (route + gegenereerd statisch apex-bestand
  `native/apex-well-known/assetlinks.json`) én de `android:apk-key-hash:`-origins af
  (`toegestane_webauthn_origins`; nooit met de hand in `WEBAUTHN_ORIGINS`), settings-validator
  fail-loud, drift-test deploy↔apex-bestand; R8 in identiteitsmodus + mapping/debug-symbols als
  upload-artefact naast de AAB. Klikwerk Peter: assetlinks.json naar de WordPress-apex (30-08 nog
  404) → Google's checker → kliktest §8.** Eerder klikwerk: wachtwoordmanager → AAB naar Internal
  testing → App signing: BEIDE certificaten → screenshots.**).
  **Store-link-nazorg voorbereid (blok F 01/02-09, BESLISSINGEN "STORE-LINK-NAZORG"): settings
  `STORE_LINK_IOS`/`STORE_LINK_ANDROID` (default leeg = niets tonen); gevuld → blok "Download eerst de
  app" in de uitnodigingsmail voor app-rollen, op het desktop-stop-scherm van /activeren en op het
  web-fallback van de universal link (`auth/StoreLinks.tsx`); nazorg ná Apple/Google = alleen de
  env-vars zetten.** Factuurbeeld
  centraal, akkoord → volgende, dagelijkse push 09:00 alleen bij >0 open.
  **Bouwstatus: backend + kantoor-UI GEBOUWD + GETEST (2026-08-09)** — migratie 0033 +
  `backend/app/accordering/` + kantoor-UI (Instellingen-sectie, "Ter accordering"-knop,
  accorderingssectie controlescherm, "Bij klant"-teller); incl. staande goedkeuring (besluit
  2026-08-08: per accordeur+leverancier+exact bedrag, automatisch akkoord mét audit+tijdlijn,
  intrekbaar — harde checks blijven onverkort) en direct-boeken-blokkade zodra de toggle aan
  staat. Details BESLISSINGEN "Klant-accorderingsflow — GEBOUWD + GETEST".
  **De accordeur-PWA zelf: GEBOUWD + GETEST (2026-08-11, kliktest Peter open)** —
  `frontend/src/accordeur/` op /accordeur (eigen lazy chunk, geen kantoor-bundels; mockup
  `mockup/accordeur.html` 1-op-1; ≥16px-velden + visualViewport-sheets + dark default;
  PDF lazy via pdfjs-dist; installeerbaar zónder service worker), activeringsflow
  wachtwoord → passkey → voorwaarden/privacyverklaring-akkoord (server-side afgedwongen,
  `platform.accordeur_akkoord` + audit), apparatenbeheer/kill-switch op Instellingen.
  Zie BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD".
  **Accordeur-app-ronde 26-08 (blok B gecombineerde run, mockup `accordeur-vragen.html` = norm,
  migratie 0079 — BESLISSINGEN "GECOMBINEERDE RUN 26-08" blok B is canoniek):** compacte header
  zónder administratienamen; PDF-weergave mét laadstate/retry/tijdslimiet (oorzaak wit vlak:
  verborgen prerender op breedte 0 → `PdfWeergave.actief`); 🔔-hoekje + popup + wachtrij-kaart
  VERVALLEN (meldingskeuze alleen éénmalig in de activeringsflow, daarna telefooninstellingen);
  native `.then is not a function` gefikst (bridge-shim geeft een plain listener-handle,
  `nativePush.alsHandle`); doorbelast-blok = één regel + uitklap; **vragen-dialoog naar de
  accordeur**: vraag aan een klant-accordeur laat de documentstatus staan (ter_accordering/
  geboekt), akkoord blijft mogelijk, boeken wacht ná het laatste akkoord zichtbaar op de open
  vraag (`vraag_open` + boek_fout); accordeur ziet uitsluitend eigen threads (`GET
  /accordering/vragen`, `WachtrijItem.vraag`, antwoord-POST), afgehandeld alleen vraagsteller;
  push-anders-mail per beurt mét stille uren (`app/berichten/vraag_meldingen.py`).
  **Accordeur-app-ronde 2 (VERZAMELRUN 27-08, besluiten Peter 27-08, mockup scherm 0 "Uw
  administraties" = norm — BESLISSINGEN "VERZAMELRUN 27-08" is canoniek):** de app opent met
  één kaart per administratie MÉT werk (teller, chip "💬 vragen aan u", oudste-wacht-regel; geen
  ✓-bij-rijen; alles bij = "✓ Alles is bij" mét verversknop), klik = wachtrij per BV, één BV met
  werk = direct die wachtrij, ná akkoord de volgende van dezelfde BV, deep-links landen in de
  juiste BV (`accordeur/administraties.ts`, geen nieuw endpoint); pull-to-refresh + automatisch
  stil verversen bij terugkeer naar de voorgrond (`PullToRefresh.tsx`, `verversen.ts`);
  ontgrendeling hooguit 1× per 24 u per apparaat (zie Auth). Open beslispunt: teal Akkoord-knop.
  **Notificaties: GEBOUWD + GETEST (2026-08-15, BESLISSINGEN "ACCORDEUR-NOTIFICATIES")** —
  gedeeld SMTP-mailkanaal (`app/berichten/`, Google Workspace, fail-zichtbaar; bedient óók de
  uitnodigingsmail), dagelijkse 09:00-herinnering (job `rlz-accordeur-herinneringen`, alleen
  bij >0 open, idempotent per dag per accordeur, migratie 0050), Web Push via
  `public/accordeur-sw.js` (scope /accordeur, UITSLUITEND push — geen fetch-handler/caching,
  installatie-/updatepad ongewijzigd; subscriptie per apparaat, kill-switch trekt push mee in;
  permissie alleen vanuit expliciete klik). **Meldingen-kaart eenmalig (UX-besluit Peter
  2026-08-17, HERZIEN 26-08 blok B3): voorstel éénmalig in de activeringsflow (ná
  voorwaarden-akkoord), keuze per apparaat onthouden (óók "nee"; mislukt = eerlijke fout + één
  herkansing) — het 🔔-hoekje en de meldingen-popup zijn sinds 26-08 weg; om-/uitzetten =
  telefooninstellingen; kill-switch ongewijzigd.** **HARD PRINCIPE: maillinks zijn deep-links naar de
  PWA (`/accordeur?document=<id>`) — goedkeuren-zonder-inloggen/one-click-token bestaat bewust
  NIET** (zou de passkey-laag omzeilen). **Afzenderadres beslist (Peter 2026-08-15):
  facturen@ak-nijenhuis.nl (géén aparte gebruiker/licentie) mét Reply-To
  p.nijenhuis@kempengroep.nl — menselijke antwoorden blijven zo buiten de intake; auto-replies
  op facturen@ zijn geaccepteerde zichtbare ruis.** Live-verificatie loopt via het gebundelde
  interactieve `scripts/gcp/notificaties_afronden.sh` (slots + VAPID-generatie +
  wachtwoord-invoer + deploy + job-run + verificatie-gegate scheduler-resume in één gang;
  open TEST-accordering voor het passkeytest-account is geseed in de cloud-DB,
  `backend/scripts/cloud_seed_accordering.py`). Open: die live-verificatie (scheduler
  gepauzeerd tot dan).
  **Handmatige herinner-knop: GEBOUWD + GETEST (2026-08-16, migratie 0053)** — kantoor
  stuurt per direct een extra herinnering aan de accordeur die aan de beurt is
  (klantpagina-paneel + accorderingssectie, "laatst herinnerd" zichtbaar; max 1 per
  document per dag, audit + tijdlijn). **Nieuwe-facturen-bundelmelding: GEBOUWD + GETEST
  (2026-08-16, besluit Peter 16-08 — expliciet géén melding per factuur; migratie 0054)**:
  job `rlz-nieuwe-facturen` (~elke 10 min) bundelt nieuw klaargezet werk per accordeur tot
  één bericht ("Er staan N facturen voor u klaar", N = totaal openstaand); idempotent per
  (accordeur, document) — nooit dubbel; stille uren 20:00–08:00 Europe/Amsterdam; de
  09:00-herinnering blijft ongewijzigd en telt integraal; scheduler start gepauzeerd tot de
  notificatie-live-verificatie. Zie BESLISSINGEN "NIEUWE-FACTUREN-BUNDELMELDING" +
  GCP_UITROL §F3.6.
- **Projecten** (module, zichtbaar per rol + per administratie-toggle): project verplicht = hard
  blokkerend, géén "geen project"-optie; overhead → intern OVH-project (uitgesloten van bewaking).
  Budget uit offerte-ontleding (status offerte ≠ opdracht; meerwerk = aparte budgetversie).
  Werksoort = omzet-GB ↔ kosten-GB-mapping (default per administratie, override per project/regel).
  Signalen: kosten > gefactureerd per werksoort; budgetoverschrijding; weekanalyse (inkoop zonder
  omzet); m²-voortgang uit factuurregels. Integrale marge = analytische laag (AK-opslag instelbaar,
  dekkingscontrole vs OVH-project) — nooit geboekt in RLZ.
- **Projectcode-generatie** volgens naamconventie van de klant (bijv. Universal: "26xxx Plaats
  (Opdrachtgever)"), synct bij aanmaken naar RLZ.
  **Kantoor-projectenmodule (mockup projecten-invoer.html, akkoord + GEBOUWD + GETEST
  2026-08-22, migratie 0062 — BESLISSINGEN "PROJECTENMODULE KANTOOR" is canoniek):**
  projectenlijst + detail met specs/contract-&-offerte-upload/verrekenstaffels/leverancier-
  werknummers (schrijven = Beheerder + Boekhouding+Projecten, lezen = kantoorrol + scope),
  contract-ontleding als AI-VOORSTEL per regel (per-administratie AVG-gate
  ai_extractie_ingeschakeld + AI-kostengrens; bevestigen = deterministisch opslaan), nieuw
  project via de bestaande RLZ-projectmotor-bouwstenen ("26127 Tilburg (Heijmans)"), en het
  resultaat per project + cumulatief overzicht (analytische laag — project_regel_cache uit
  RLZ-Lines mét projectref, `make projecten-cijfers-sync`; onderweg = getekende onverrekende
  uren × tarief (ontbrekend tarief = onbepaalbaar, nooit gokken) + goedgekeurd meerwerk;
  werkweek-herleiding via verrekende weekstaten; zelfde rekenfunctie voor detail én
  overzicht; nooit geboekt in RLZ, excl. AK-opslag; géén suppletie-signaal — besluit 22-08).
  **Cijfers-sync = ACHTERGRONDRUN (fix 504-crash, 2026-08-23, migratie 0063 — BESLISSINGEN
  "CIJFERS-SYNC-CRASH" is canoniek):** de ⟳-knop antwoordt 202 + statusrij
  (`project_cijfers_sync_run`, UI pollt bezig/klaar/fout mét zichtbare foutreden en
  leesfouten-teller), motor gepagineerd per documenttype/RLZ-pagina (nooit volledige
  collecties in één request — dat gaf de 504); voertuig cloud = on-demand job
  `rlz-projecten-cijfers` (metadata-server-trigger, IAM f3_jobs.sh stap 6), dev = thread;
  dagelijkse verversing draait mee in de rlz-sync-job van 07:00. Een onleesbaar document
  (RLZ-403) telt als leesfout en wordt nooit vals als "verdwenen" gemarkeerd.
- **Uren & meerwerk (steigerbouw-tak — ontwerpronde + BOUW GO Peter 2026-08-21):**
  het fase-4-item "urenportaal ZZP'ers" is naar voren getrokken; twee mockups definitief
  goedgekeurd: `mockup/uren-uitvoerder.html` (veldkant, zelfde native app als de accordeur,
  drie rollen) + `mockup/meerwerk-kantoor.html` (kantoorkant, stijl kantoor-modern) — UX
  ligt vast, 1-op-1 voortbouwen. Scope: steigerbouw-specifiek, **opt-in per administratie**
  (alleen Universal initieel); onderdeel van de projectadministratie maar **niet leidend**
  ervoor — de generieke projectenmodule blijft eigen ontwerp en wordt alleen gevoed
  (m²-voortgang, meerwerklijst, getekende urenstaten). **Datamodel-besluit (21-08):
  WEEKSTAAT PER PROJECT** — één staat per persoon per project per week; zelfde dag op twee
  projecten = twee staten. Rollen in de bestaande native app: **ZZP'er** (weekstaat per
  project — uren + optionele m² per dag, indienen per week, deadline ma 09:00),
  **uitvoerder** (specs/contract alleen-lezen mét prijzen, meerwerk melden zonder prijzen,
  **HYBRIDE keuring op WEEKNIVEAU (aanvulling Peter 22-08, migratie 0059)** — week akkoord
  óf week afkeuren met verplichte reden, hele week terug naar "corrigeren", ZZP'er dient de
  wéék opnieuw in; bij afkeuren kan de keurder per dag een CORRECTIEVOORSTEL meegeven
  (uren/m²/opmerking) dat de ZZP'er letterlijk in zijn corrigeer-scherm ziet — de keurder
  wijzigt nooit zelf andermans uren; geen dag-keuring, dagen alleen ter controle. Elke
  afkeuring mét voorstel wordt geregistreerd (`weekstaat_correctie`: ingediend vs.
  voorgesteld/goedgekeurd, optelbaar per veldwerker, alléén zichtbaar voor kantoor —
  het goedgekeurde totaal blijft de toetsbron voor de factuurmatch) en **detacheerder** (besluit 21-08, vervángt de 17-08-rollen
  teamleider/manager: vult weekstaten in namens door kantoor gekoppelde ZZP'ers, exact
  dezelfde schermen/velden, geen projectinhoud — per project alleen nummer + plaats; elk
  namens-scherm draagt "· namens <ZZP'er>", elke invoer vastgelegd als "ingevuld door X
  namens Y", audit + zichtbaar bij de keuring). Kantoor beheert keurders per
  uitvoerder↔project én detacheerder↔zzp'er (Beheerder-only, audit). Goedgekeurde staat =
  getekende urenstaat, onmuteerbaar (wijzigen alleen via nieuwe afkeuring) = basis
  factuurmatch. **Factuurmatch: verkenning + fasering AKKOORD (Peter 2026-08-21, vier
  richtingbesluiten — BESLISSINGEN "FACTUURMATCH ZZP-/BUREAUFACTUREN" is canoniek):**
  (1) bureau-tarief per detacheerder↔zzp'er-koppeling = hoofdmechanisme (bureaufactuur =
  som van uren × tarief per ZZP'er; ontbrekend tarief = match alleen op uren, oranje "geen
  tarief bekend", geen blokkade; los ZZP-tarief op de veldwerker↔crediteur-koppeling);
  (2) boeken bij afwijking mág mét expliciete bevestiging ("geboekt ondanks
  match-afwijking", tijdlijn + audit), autoboek-slot strikt groen incl. bedrag;
  (3) afwijking = vlag + eigen teller/chip (duplicaat-patroon), geen enum-status;
  (4) autoboek-opt-in per veldwerker-koppeling (default UIT). **Fase 1 GEBOUWD + GETEST
  (2026-08-21, migratie 0057)**: veldwerker_crediteur + bureau-tarieven + factuurmatch(-staat)
  + weekstaat-verrekening (dubbeltelling-preventie) + deterministische motor
  `app/uren/factuurmatch.py`. **Fase 2 pipeline-integratie GEBOUWD + GETEST (2026-08-21,
  migratie 0058 — BESLISSINGEN "Fase 2" is canoniek)**: match-run ná
  extractie/voorstel-opslag/staat-goedkeuring + herbereken-endpoint met staten-selectie
  (altijd systeem-actor — RLS bureau-tarieven), boeken-mét-expliciete-bevestiging ("geboekt
  ondanks match-afwijking" in tijdlijn + audit; bevestiging persistent op de match-rij,
  herberekening wist 'm; zelfde poort bij ter-accordering-aanbieden), staten-verrekening ín
  de boek-transactie + afkeur-blokkade op verrekende weken, werkvoorraad-teller/chip/banner
  (duplicaat-patroon), concept-mail aan de veldwerker (mens bewerkt + verstuurt expliciet,
  nooit auto) én weigering van de oude leverancier-autoboek-opt-in voor gekoppelde
  crediteuren (runtime-vangnet + 409 bij aanzetten). **Fase 3 kantoor-UI GEBOUWD + GETEST
  (2026-08-22 — BESLISSINGEN "Fase 3" is canoniek)**: veldwerkers-paneel met
  crediteur-koppeling + ZZP-uurtarief + bureau-tarief per detacheerder↔zzp'er
  (Beheerder-only endpoints, geaudit) én de match-sectie op het controlescherm
  (uitkomst-chip, verschil-per-week-uitsplitsing, periode-keuze/herberekenen met
  weekstaat-selectie via de kandidaat-staten-leesroute, concept-mail-paneel);
  mockup meerwerk-kantoor.html mee bijgewerkt. **Fase 4 autoboek-slot GEBOUWD + GETEST
  (2026-08-22, geen migratie — kolom 0057): opt-in per veldwerker-koppeling (Beheerder-only
  endpoint + switch in de crediteur/tarief-modal, ⚡-badge), slot uitsluitend groen bij
  match-uitkomst `match` (bedrag getoetst — tarief verplicht) mét ≥ 1 getekende staat,
  bovenop álle bestaande inkoop-autoboekpoorten (app-bevestigd geheugen, harde checks,
  duplicaat/vraag, volumerem, accorderingspoort); bron `veldwerker_opt_in` in tijdlijn +
  audit; twee triggers (ná extractie én ná weekstaat-goedkeuring die de match groen maakt);
  staat overal UIT — activeren per koppeling is klikwerk Peter.**
  **ZZP-dossier + handhaving + KvK (steigerbouw-run 25-08 blok A, besluiten Peter 23/24-08,
  GEBOUWD + GETEST 2026-08-25, migratie 0072 — BESLISSINGEN "STEIGERBOUW-RUN 25-08 — BLOK A"
  is canoniek):** per veldwerker (ZZP'er/uitvoerder) × administratie een dossier met
  Beheerder-instelbare documenttypen (default kopie ID/steigerpas/VCA vol/AVB/KvK-uittreksel;
  virtueel tot de eerste PUT), statusmodel ontbreekt → ter controle (upload kantoor óf app, ook
  detacheerder namens) → goedgekeurd/afgewezen-met-reden, verlopen + 30-dagen-vooraankondiging;
  kopie ID volgt de BSN-regel (nooit extraheren/indexeren, gemaskeerde weergave, élke inzage
  geauditeerd). Handhaving: herinner-knop (push-anders-mail, max 1/dag, "N van 3"); ná de 3e
  herinnering blokkeert weekstaat-INDIENEN (HTTP 423, óók namens) — dagen zetten blijft mogelijk,
  deblokkade zodra alles geüpload is (ter controle telt), afwijzing heractiveert, teller-reset
  pas bij volledig goedgekeurd. KvK-lookup = eigen kopie Vastly-patroon (`app/integraties/
  kvk.py`, testomgeving default, `KVK_API_KEY`/`KVK_BASE_URL` productie), mens bevestigt.
  Daarnaast: veldwerker aanmaken zónder mail (`uitnodiging_later`), Beheerder-only e-mail
  wijzigen (`PATCH /auth/gebruikers/{id}/e-mail`, verse uitnodiging bij niet-geactiveerd) en het
  signaal > N uur per dag (`administratie.uren_dagmax_uren`, default 12 — som over álle
  weekstaten per kalenderdag, oranje vlag, geen blokkade). **Seam-eis steigerbouw-run: nieuwe
  module-code roept nooit RlzClient aan; adapter-grepen per blok in BESLISSINGEN "ODOO-ADAPTER
  — GREPEN"; de Odoo-feiten voor de adapter staan in `verkenning/odoo-verkenning.md` (STAP-0 02-09).**
  **Geofence-stempels BASIS (bouwrun 28-08 blok C, mockup `geofence-stempels.html`, migratie 0085;
  jurist akkoord 28-08 — regeling in de voorwaarden/privacyverklaring alinea 4, tekstversie
  `2026-08-28-v2`, géén apart instemmingsscherm):** projectzone op de projectspecs (adres + lat/lon +
  straal; geen zone = geen stempels), `boekhouding.werkstempel` APPEND-ONLY met fail-closed intake
  `POST /uren/stempels` (alleen de veldwerker zelf, nooit namens; alleen projecten mét zone in
  scope), eigen stempels in de veld-app, keuringskolom "gestempeld aanwezig" (Σ in/uit-paren,
  onvolledig paar sluit op middernacht mét markering, > 1,0 u afwijking = oranje vlag — nooit
  korting; geen stempels = toets zwijgt). **Native achtergrondlocatie: GEBOUWD OP
  BRANCH `feat/geofence-native` (29-08) — NIET gemerged, NIET releasen:** iOS CLLocationManager-
  regiobewaking + Android GeofencingClient, zones uit de weekplanning (`GET /uren/stempels/zones`,
  max 20), éénmalige OS-permissiestap, buffer + nazenden via `POST /uren/stempels` bij app-opening;
  kabeltest-draaiboek `native/GEOFENCE_KABELTEST.md` (branch). Xcode Cloud bouwt vanaf main; de
  `ACCESS_BACKGROUND_LOCATION`-guard in `bouw_android_release.sh` blijft op main; store-motivering +
  release = versie 1.1 ná de eerste store-goedkeuring. BESLISSINGEN "BOUWRUN 28-08 AVOND" blok C +
  "OPDRACHT 29-08" blok C.
  **Prijsafspraken per project × veldwerker (steigerbouw-run 25-08 blok B1, GEBOUWD + GETEST
  2026-08-25, migratie 0073 — BESLISSINGEN "STEIGERBOUW-RUN 25-08 — BLOK B" is canoniek):**
  tarief mét eenheid uur óf m² + ISO-week-venster, append-only (intrekken met reden), overlap
  geweigerd; factuurmatch-tariefresolutie per weekstaat: projectafspraak wint → koppeling-tarief →
  onbepaalbaar (nooit gokken), m² rekent met goedgekeurde weekstaat-m², geldt óók voor
  bureaufacturen; de match-sectie toont altijd de tariefbron. Weeknummers in alle steigerbouw-
  datumweergaves (B2, `datumMetWeek`).
  **Slimme landing + Planning-menu (steigerbouw-run 25-08 blok C, GEBOUWD 2026-08-25 —
  BESLISSINGEN "BLOK C"):** `GET /uren/kantoor/mijn-toegang` voedt `useMijnToegang`; een
  mono-klant-medewerker (één administratie in scope, geen Beheerder) landt op zijn klantpagina,
  mét module-recht + opt-in op `/meerwerk?administratie=X`; fail-closed = werkvoorraad. Planning
  als zijbalk-item bij module-recht + opt-in. **Koude start rlz-backend ≈ 15 s (gemeten 25-08) → WARME START aangezet (besluit Peter 25-08,
  uitgevoerd 26-08): `--min-instances 1` request-based verankerd in deploy.yml, ≈ € 7/mnd — rapport
  + verificatie in `docs/COLD_START_ONDERZOEK_25-08.md`; alleen de service, jobs ongemoeid.**
  **Transportplanning + bestellingen + materiaalstand (steigerbouw-run 25-08 blok D, besluiten
  Peter 24-08, GEBOUWD + GETEST 2026-08-25, migratie 0074 — BESLISSINGEN "BLOK D" is canoniek;
  mockup planning-steigerbouw Transport-tab + popup = norm):** `app/materiaal/` — catalogus per
  leverancier (seed uit de bestellijst-xlsx, m² = Σ(aantal × lengte)/4,6), bestellingen mét
  append-only revisies (PDF-bon per mail via het bestaande SMTP-kanaal, update-mail = alleen
  gewijzigde regels oud→nieuw, mailfout = geen revisie), transport levering/retour per project ×
  dag (**seam `zet_transport_status(bron=)`** voor het
  latere verhuursysteem/veld-aftekening), materiaalstand + huurperiode per item, wachtrisico-
  kruissignaal op beide planning-tabs, materiaalmatch (D6: verhuur-crediteur vs aantal ×
  huurperiode; zelfde vlag-patroon + boekpoort als de urenmatch; m²-toetsbron in de keuring).
  Nieuwe module-code roept nergens RlzClient aan (seam-eis).
  **Transport v2 = DAG-AGENDA + statusflow-her-enum (opdracht 31-08, mockup
  `planning-werkopdracht-transport.html` = norm, migratie 0091 — BESLISSINGEN
  "PLANNING-UITBREIDING 31-08" is canoniek):** de Transport-tab is een dag-agenda zónder
  projectrijen (kaart = projectnr + klant + adres uit de specs + ▲/▼ + materiaal + voertuig +
  planner + status; sleepbaar tussen dagen mét klik-alternatief; werkbakje: zoek → chip → sleep
  of klik-klik; signaalkaart "nog te plannen" bij een verstuurde bestelling zonder
  transportregel). **Status: gereserveerd (rood, uit het werkbakje) → bevestigd (oranje,
  VERPLICHTE voertuigtoezegging combi/voorwagen + mail aan het TRANSPORT-CONTACT) → definitief
  (groen, materiaallijst + transportplanner + volledige lijst aan het MATERIAAL-CONTACT) →
  geleverd (grijs); wijzigen ná definitief = delta-mail (alleen oud→nieuw); dag verschuiven =
  terug naar gereserveerd (voertuig vervalt, lijst blijft); álle mails mail-first (mailfout =
  502, geen stille wijziging); legacy 'gepland' gedraagt zich als gereserveerd
  (`effectieve_status` — migratie puur DDL).** Leverancier draagt twee contactpersonen
  (transport-/materiaal-contact, leverancierbeheer); leverancier-/catalogusbeheer sinds 31-08
  voor Beheerder ÓF B+P (`require_beheerder_of_bp`).
  **Werkopdrachten per project × periode (31-08, zelfde mockup/migratie):** `app/uren/
  werkopdracht.py` — APPEND-ONLY (groep_id + versies, DB-grant zonder UPDATE/DELETE; historie
  in de popup), meerdere/overlappende per project, dag-override sparse (alleen die dag wint);
  paarse chip + ⊕ per projectrij op de Personeel-tab, override via de dagcel; de veld-app toont
  de geldende tekst alleen-lezen per geplande dag — bewust GEEN push bij tekstwijziging.
  **Fijnmazig recht "veldwerkerbeheer" (31-08, 0019-patroon, eigen module-sleutel
  `boekhouding.veldwerkerbeheer` — PK-les: één gebruiker draagt meerwerk- én dit recht):**
  B+P mét het recht mag UITSLUITEND veldwerkers aanmaken (incl. uitnodiging_later) en
  archiveren binnen de eigen scope (zelf-gepoorte SECURITY DEFINER-scope-toets
  `platform.veldwerker_scope_binnen_actor`, fail-closed) — nooit kantoorrollen of rol-/
  scope-mutaties; toekennen Beheerder-only (/gebruikers-switch); ingang "+ ZZP'er"/🗑 in de
  planning-zijbalk; "+ Project aanmaken" terug op /planning (B+P, bestaande projectmotor).
  NB de module-recht-houderslijst leest sinds 31-08 mét actor (RLS-leesbug /gebruikers:
  actor-loze sessie zag stil nul rijen — kolom toonde overal "uit").
  **Planning-agenda steigerbouw (ontwerpronde v2 + BOUW akkoord Peter 22-08, mockup
  `planning-steigerbouw.html` = norm; GEBOUWD + GETEST 2026-08-22, migratie 0060 —
  BESLISSINGEN "PLANNING-AGENDA STEIGERBOUW" is canoniek):** kantoor plant ZZP'ers/
  uitvoerders per dag op ACTIEVE projecten (weekgrid `/planning`, sleepbare kaartjes,
  dagdeel heel/half; ingang op de klantpagina). Harde failsafe = samengestelde PK
  persoon×project×dag; besluit A: plannen maakt de projectkoppeling automatisch aan
  (geaudit, bron 'planning'); besluit B: veldwerker ziet de eigen planning ALLEEN-LEZEN in
  de app (tab "📅 Planning", ook detacheerder-namens; geen veld-mutatiepad); besluit C:
  > 5 geplande dagen p.p./week = zacht signaal. Planning = TOETSBRON weekstaten: uren
  buiten planning = oranje `buiten_planning`-vlag bij de keuring (geen blokkade); dubbele
  dag zonder dekking = interne melding + 30-dagen-teller per ZZP'er, uitsluitend kantoor.
  Toegang onder module-recht "Meerwerk & urenstaten" + uren-&-meerwerk-opt-in.
  **Jaaragenda + bruikbaarheids-fixes (besluiten Peter 22-08, GEBOUWD + GETEST zelfde dag —
  geen migratie):** vrij vooruit plannen onbegrensd (géén week-kopieerknop — het hele jaar
  wordt vooruit gevuld; project-einddatum = zacht oranje signaal, geen blokkade), week in de
  URL (`?week=2026-W41`) mét weekkiezer, drag & drop gerepareerd + volwaardig klik-alternatief
  (cel aanklikken → persoon kiezen), opmaak conform de bijgewerkte mockup.
  **Grid v3 (besluit Peter 23-08, GEBOUWD + GETEST zelfde dag — vervángt het 22-08-grid-filter
  "alleen projecten mét planning + zoekrij", dat gaf een leeg grid waarin je niet kon
  beginnen):** het weekgrid toont ÁLLE actieve projecten in twee blokken — mét planning
  bovenaan (volle rijen), de rest compact onder een scheidingskop, direct beplanbaar via klik
  én drag & drop — mét live filterveld + telling "N actieve projecten · M mét planning"; de
  "+ project toevoegen"-rij en het endpoint `/uren/kantoor/planning/projecten` zijn VERVALLEN,
  de planning-GET levert alles (incl. specs-metadata, gebatcht) in één request — vlot bij 68
  actieve projecten (Universal). Veld-app-planningtab ongewijzigd. BESLISSINGEN
  "PLANNING-AGENDA" (rij GRID V3) is canoniek.
  Meerwerk-kantoorkant: gemeld → goedgekeurd-nog-doorbelasten → doorbelast/afgewezen(eigen
  rekening, verplichte reden); contract-toets stelt prijs voor uit de offerte-staffel, mens
  bevestigt (nooit auto-boeken); goedgekeurd + 2 weken niet op een verkoopfactuur =
  werkvoorraad-signaal (sluit aan op de item-niveau-doorbelastingscontrole); omschrijvingen
  altijd voluit. Toegang: één module-recht "Meerwerk & urenstaten" per kantoormedewerker
  (0019-patroon, Beheerder-only, audit, server-side incl. menu/standen/zoeken/API;
  klantscope blijft eronder gelden). Bouwstatus: zie BESLISSINGEN "Ontwerpronde uren &
  uitvoerder + meerwerk-kantoor" + "UREN & MEERWERK — BOUW".
- **Voorraad-aansluiting fase 1 (bouwrun 28-08 blok D, mockup `voorraad-aansluiting.html`,
  migratie 0086 — eerste bewoner van het `mi`-schema):** controle-laag, géén tweede
  voorraadadministratie en NOOIT RLZ-writes. Opt-in `voorraad_ingeschakeld` (Beheerder-only, default
  UIT; sinds 29-08 AAN voor Universal Verkoop, Universal Nederland, Universal Steigerbouw, Bradwolff
  Constructie en BWC Steigers — in de cloud gekoppeld; eerste vulling 29-08 avond, zie BESLISSINGEN
  "OPDRACHT 29-08" blok A "Eerste voorraad-vulling"). Instroom = regel-niveau feiten uit het inkoop-veldvoorstel
  (AI-regelschema levert nu óók eenheid `e` + stuksprijs `p`), uitstroom = verkoopfactuurregels van de
  in de app geboekte verkoopdocumenten (UBL-hoeveelheden) **én — blok A 29-08, STAP-0 groen, migratie
  0087 — de EIGEN RLZ-verkoopfacturen van de administratie via de dagelijkse leesroute
  `app/voorraad/rlz_uitstroom.py` (meelopend in `sync-alles`, incrementeel vanaf max(datum) − 14 dagen,
  alleen Status 2/3, aantal = `Quantity` mét teken — creditregels zijn al negatief, nooit dubbel
  flippen; `voorraad-rlz-sync --volledig` voor de eerste run; strikt GET-only). Odoo = parkeerpost.**
  Normalisatie VOLAUTOMATISCH: dienst-regel zonder AI, bestaande regel deterministisch,
  eerste match = AI-voorstel (`ClaudeExtractieClient.vraag_json`, zelfde kostenpoort) direct
  toegepast, onzeker telt mee mét vlag, geen AI = "niet genormaliseerd" (prominente teller);
  correctie optioneel en herrekent historie. Aansluitscherm (menu Inzicht › Voorraad): per
  artikelgroep begin + inkoop − verkoop = theoretisch vs telling, tolerantie 1% default, bron per
  kolom (incl. herkomst per regel: app-document vs "RLZ-verkoopfactuur nr"), drill-down + dagstanden;
  invoer (nieuwe groep, tolerantie) via designpass-v2-dialogen (blok B 29-08). **Normalisatie v2
  (besluiten Peter 29-08 avond, GEBOUWD 30-08, migratie 0088 — BESLISSINGEN "OPDRACHT 30-08" is
  canoniek): "uitgesloten" is een SOORT-label (artikel/dienst/transport) — dienst-/transportregels
  blijven bewaard en queryable (`regels?soort=`, omzet-informatie voor MI) en tellen alleen niet;
  `normalisatie_status` = puur zekerheid ('uitgesloten' = legacy pre-0088, omgezet door de
  hernormalisatie; migratie puur DDL want Alembic op Cloud SQL heeft geen BYPASSRLS). Dienst-regex
  uitgebreid op de 29-08-bevindingen (kilometers/reistijd/inspectie/keuring/kalibratie/huurperiode)
  MÉT dienst-inzage per tekst + correctie (eis Peter: nooit blind vertrouwen). Artikelcode als
  deterministische sleutel per RICHTING (verkoop: "(560140.4)" uit de Description; inkoop: nieuw
  AI-regelveld `a`) in `mi.artikelcode_koppeling` — inkoop- en verkoopcodes nooit gelijkgesteld;
  prioriteit handmatig > tekstregel > code > regex > AI (batches van 40); codes-inzage + correctie
  per code; steigerdelen 3 m ≠ 5 m (prompt). Hernormalisatie zonder RLZ-calls: `make
  voorraad-hernormaliseer` (rapport per BV + AI-maandmeter); tegen de cloud via
  `backend/scripts/cloud_cli.py` — cloud-run 30-08 = klikpunt (deploy 0088 + `gcloud auth login`).**
  `app/voorraad/`; BESLISSINGEN "BOUWRUN 28-08 AVOND" blok D + "OPDRACHT 29-08" blok A/B +
  "OPDRACHT 30-08".
- **Zoeken**: globaal over boekingen (incl. archief + RLZ-boekstuk + PDF), accorderingshistorie
  — **GEBOUWD + GETEST (2026-08-09)**: `backend/app/zoeken/` + `frontend/src/zoeken/`,
  scope-veilig per administratie (RLS + server-side), doorzoekt kopgegevens + lokaal
  aanwezige extractietekst (veldvoorstel — bewust geen nieuwe AI-calls), vragen en
  accorderingshistorie inline, audit-sectie conform mockup #zoeken. Zie hieronder;
  archiefweergave per administratie idem gebouwd.
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

## Koppelvlak vastgoedmodule (`../Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md` is leidend, v1.18)

- **Schrijfverdeling (gecorrigeerd v1.10, drift-audit 2026-08-07): vastgoed schrijft NIET in
  RLZ — wij doen álle RLZ-writes** (inkoop, omzet/verkoop incl. Vastly-huurfacturen uit de
  §2d-mailflow, waarborg-memoriaal ná de §2d-waarborgroute, bank, projecten). Vastgoed levert
  documenten aan via de boekhoudmail. Niemand muteert documenten van de ander.
- Het `VGB-`-prefix is gereserveerd maar niet in gebruik (er is geen vastgoed-schrijfroute);
  ons intake-filter blijft als failsafe staan: `VGB-`-document → nooit werkvoorraad, wél
  zichtbaar geregistreerd.
- Wij pushen bij "geboekt" een webhook per inkoopfactuur van vastgoed-administraties (payload:
  rlz_document_id, referentie, adminId, datum, leverancier, regels met ledger+GB-code+bedragen —
  de wérkelijke payload is sinds v1.10 de contractnorm); **sinds 2026-08-09 óók bij het boeken
  van een VASTLY-VERKOOP-document** (referentie = Vastly-factuurnummer; velden `soort` +
  `debiteur` i.p.v. `leverancier` — sinds v1.12 (2026-08-10) formeel als norm in §3
  opgenomen); **en sinds 2026-08-14 óók voor doorbelasting-spiegel-inkoopfacturen in
  vastgoed-doeladministraties** (v1.13 §3, standaard inkoop-veldvorm — zie
  "Kempen-doorbelasting" hierboven).
- **Kostenflow-omkering + boekstand-events (v1.14, 2026-08-14 — GEBOUWD + GETEST):** Vastly's
  eigen kostenintake vervalt voor RLZ-administraties, kostenregels komen uitsluitend via
  `factuur_geboekt` binnen (§3a; pand = `project_id` per regel via §2.1 + de bestaande
  `project_verplicht`-vlag, activatie samen met vastgoed-S2). Drie §3-uitbreidingen (de
  kostenflow-randvragen a/b/c): (a) **creditnota-norm inkoop** — negatieve PurchaseInvoice →
  event in de standaard veldvorm met negatieve regelbedragen, geen vlag, eigen
  rlz_document_id; (b) **`volgnummer` per boekstand** in `factuur_geboekt` (schema 1.0→**1.1**):
  één monotone reeks per rlz_document_id over geboekt- én gestorneerd-events
  (`app/documenten/boekstand.py`, stand leeft in de outbox-rijen — geen extra tabel),
  ontvanger idempotent per (rlz_document_id, volgnummer), hoogste wint, 1.0-events = stand 0 —
  herboeking-op-zelfde-GUID is reëel (doorbelasting-spiegel na storno + nieuwe run);
  (c) **nieuw event `factuur_gestorneerd`** (eigen schema 1.0, zelfde kanaal/outbox/HMAC —
  harde eis vastgoed-S2): `module_storno` = direct event in de storno-transactie
  (doorbelasting-spiegel), `rlz_ui_detectie` = `app/documenten/storno_detectie.py` in het
  reconciliatie-CLI-commando — **latentie = reconciliatie-cadans (nu dagelijks ≤ 24 u),
  expliciet in §3b**; geen event zonder eerder geboekt-event.
- **Route A — projectaanmaak-naar-RLZ on-demand (§5, v1.16 — GEBOUWD + GETEST + LIVE
  GEVERIFIEERD 2026-08-14):** `POST /koppelvlak/vastgoed/projectaanvragen` (`app/projecten/`,
  migratie 0048) — HMAC+timestamp+nonce met EIGEN inkomend secret
  (`PROJECTAANVRAAG_HMAC_SECRET`, uitwisseling bij F4), `bericht_id`-idempotentie, harde
  is_vastgoed-scope, synchroon `rlz_project_id`+definitieve projectnaam. Motor: UUIDv5 op
  administratie+pand_referentie, lookup-vóór-PUT (RLZ-naam wint — PUT is create-or-update!),
  naamconventie-poorten (BAG-id §2.1 = weigeren; naamlimiet 50 tekens = RLZ's harde
  PRJNAM-grens, hertest 14-08), **KLANT-LOZE top-level `PUT {adminId}/Projects/{id}`**
  (screencheck-correctie Peter 2026-08-14: de STAP-0-conclusie "Customers-route is de enige
  schrijfvorm" was fout — Basic-Auth-hertest bevestigde de route; ⚠️ IsActive default false →
  motor zet expliciet true; ⚠️ de Help-lijst is géén volledig route-inventaris — feiten:
  api-verkenning "Projects klant-loze schrijfroute"), directe project_cache-upsert.
  **Systeemanker VERVALLEN uit het aanmaakpad (heropend + afgesloten 2026-08-14,
  BESLISSINGEN "Systeemanker route A")**: de motor maakt geen anker-debiteuren
  "Pandprojecten (systeem)" meer aan; bestaande ankers blijven staan (Customer archiveren
  kan niet via de API — hertest; nooit verwijderen) en reeds anker-gebonden projecten
  blijven bruikbaar (PoC: eigenaarschap is geen scope, óók door boeken/storno heen —
  api-verkenning "Projectgebruik op vreemde documentregels"). De blokkerende check
  `check_geen_ankerdebiteur` (verkoop-rapport + fail-closed slot `zorg_voor_debiteur` op
  naam én GUID + doorbelasting-whitelist-toets; ene bron `app/projecten/anker.py`) blijft
  als VANGNET zolang er ergens een anker bestaat. Open: aanroepkant vastgoed (OPEN_ITEMS);
  `project_verplicht`-activatie = S2-moment (gereedheid geverifieerd: default UIT,
  Beheerder-only, check leest live).
- **Registersync §8 (v1.18, GEBOUWD + GETEST 2026-08-28, migratie 0081 — BESLISSINGEN
  "REGISTERSYNC-KOPPELVLAK 28-08" + Platform-besluit 0023):** `GET /koppelvlak/vastgoed/register`
  levert Vastly in één response het VOLLEDIGE administratie- + grootboekregister als snapshot
  (geen delta's/paginering/filtering; administraties ongefilterd, grootboek alleen actuele rijen
  `verdwenen_uit_bron_op IS NULL` van álle administraties; afwezig = verdwenen, client verwijdert
  nooit hard; telling per registerdeel, leeg = expliciet 0; sleutel grootboek
  `(administratie_id, ledger_id)` — ledger-GUID's zijn NIET globaal uniek). Read-only in één
  `REPEATABLE READ READ ONLY`-transactie mét per-administratie RLS-scope (`app/registersync/`).
  Auth = route-A-patroon via headers `X-Registersync-Timestamp/-Nonce/-Signature` over de vaste
  data `{"event":"registersync"}` mét EIGEN secret `REGISTERSYNC_HMAC_SECRET` (compartimentering
  per koppelvlak — nooit het webhook-/projectaanvraag-secret; zonder secret buiten dev 503).
  Klikpunt Peter: `scripts/gcp/registersync_secret.sh` + deploy.yml-regel + overdracht aan
  Vastly. Vervangt de handmatige S2-nalevering van 27-08; vervalt per contractversie zodra het
  §2c-leespatroon fysiek beschikbaar is. **Sinds 31-08 (v1.19-notitie (2), verzoek Vastly):
  optioneel additief veld `inbox_adres` per administratie-rij — afwezig = geen uitspraak,
  null/leeg = expliciet geen intake-adres; wij leveren het centrale `facturen@ak-nijenhuis.nl`
  op élke actieve rij (config `INTAKE_POSTVAK_ADRES`, sinds 31-08 óók op de Cloud Run-sérvice —
  eigen deploy-stap, de waarde past niet in de `^@^`-gescheiden `--set-env-vars`).**
- **§2d-uitbreidingen v1.10:** per UBL-regel komt de RLZ-grootboekcode mee als
  `cbc:AccountingCost` (BT-133) — wij lezen deterministisch, onbekende code = blokkerende check
  + vraag, ontbrekende code = mens kiest (geen fout); consument-facturen (alleen-BR-NL-10-
  schending mét geldige markering) → omzet-werkvoorraad mét vlag "consument-afnemer" (landt bij
  de volledige-schematron-stap); waarborg via `VASTLY-WAARBORG`-bericht (velddefinitie
  **DEFINITIEF v1.11**, incl. `bericht_id`-idempotentiesleutel) — wij boeken het memoriaal:
  **intake + boekpad GEBOUWD + GETEST (2026-08-10/11, blok E; migratie 0039,
  `app/documenten/waarborg_xml.py` + `backend/app/waarborg/` + `frontend/src/waarborg/`)** —
  herkenning op root `VastlyWaarborg` (schema-versie 1.0, elementvorm bij de parser),
  idempotent op bericht_id, saldo-0-memoriaal op de balans_gb_code (ontvangst = credit =
  verplichting), tegenrekening = mens kiest; STAP-0 tegen de test-administratie uitgevoerd
  incl. storno; vastgoed bouwt de verzendkant (OPEN_ITEMS 2026-08-10);
  §6.4 is **uitgevoerd (2026-08-09)**: Rubicon-waarborg-GB = 0204 "Waarborgsommen"
  (RLZ-template-rekening; inventarisatie herhalen per nieuwe vastgoed-administratie —
  0204 live bevestigd in de test-administratie, STAP-0 2026-08-10).
- **v1.11-addenda (2026-08-09, besluiten Peter 2026-08-08):** §2d-creditnota's (apart UBL
  CreditNote-document 381 mét VASTLY-VERKOOP-markering + BillingReference-herleiding →
  creditboeking omzetkant) — **herkenning + creditboekpad GEBOUWD (2026-08-09)** achter onze
  config-gate `creditnota_381_ingeschakeld` (AAN sinds 2026-08-10 — golden-cases geverifieerd,
  activatievolgorde stap 2 gezet; vastgoed mag CREDITNOTA_381_ACTIEF openen); de
  §3-`factuur_afgeletterd`-velddefinitie DEFINITIEF — **payload GEBOUWD (2026-08-09,
  schema_version 2.0)**: cumulatief betaald_bedrag + open_bedrag uit BaseRemainingAmount,
  volgnummer, ont_afgeletterd expliciet, tier-vlag `afgeletterd_event_ingeschakeld` per
  administratie (migratie 0037) — event blijft UIT tot vastgoeds verwerker.
  Vastly-verkoopfacturen boeken op de **échte huurder als RLZ-debiteur** (idempotente
  debiteur-aanmaak uit de UBL, besluit Peter 2026-08-08 — geen verzameldebiteur; GEBOUWD, zie
  BESLISSINGEN).
- **Vastly-verkoopfacturen (§2d, v1.9)**: e-mail-intake routeert op de vaste UBL-markering
  `cac:AdditionalDocumentReference/cbc:ID = "VASTLY-VERKOOP"` (nooit op afzender) → omzetkant
  (SalesInvoice). Geen/kapotte markering of NLCIUS-invalide UBL → verzamelbak "Niet toegewezen",
  nooit stil naar inkoop. Intake gebouwd 2026-08-07; boekpad gebouwd 2026-08-09 (zie
  "Verkoopfactuur-boekpad" hierboven).
- **WOZ-zij-extractie (§2e, v1.9)**: uit de OZB-aanslag (die wij gewoon als kostenfactuur boeken)
  extraheren wij jaargebonden WOZ-regels — mens bevestigt, waardepeildatum extraheren-en-bevestigen
  (nooit afleiden) + deterministische plausibiliteitscheck tegen 1 jan (belastingjaar − 1) —
  geleverd via `platform.woz_beschikking` (append-only, patroon §2c). Bouw in fase 2.

## Referenties in deze repo

- `mockup/index.html` — goedgekeurde UI (alle schermen, klikbaar) — bron voor flows/inhoud
- `mockup/kantoor-modern.html` — **designpass-norm kantoor-UI (akkoord Peter 2026-08-15):
  vormgeving, componenten en IA; semantische design tokens = de bron voor de frontend-tokens**
- `mockup/kantoor-designpass-v2.html` — **DESIGNPASS V2 (akkoord Peter 2026-08-26, GEBOUWD zelfde
  dag): neutrale fundering (ontgroend, inkt + echte grijzen), rijker teal, inkt-zijbalk, grafiet-dark
  zonder groenzweem, hover-lift/pressed/rij-hover/dot+label/avatars/skeleton-shimmer, lichtbaan
  alleen dark+landing. BINDENDE SEMANTIEK-REGEL: teal (`--primary`) = exclusief ACTIE, groen
  (`--ok`) = exclusief STATUS. Contrast is een test (`frontend/src/styles/contrast.test.ts`,
  parseert tokens.css + accordeur.css, beide modi — faalt een paar: token bijstellen, nooit de
  eis). Zie BESLISSINGEN "DESIGNPASS V2"; kantoor-modern.html/accordeur.html qua tokens mee.**
- `mockup/accordeur.html` — klikbare mobile-first accordeur-app-mockup (blok 5, 2026-08-09;
  ter beoordeling Peter op het mobiele breakpoint — bouw start pas na akkoord)
- `mockup/uren-uitvoerder.html` + `mockup/meerwerk-kantoor.html` — definitief goedgekeurde
  mockups uren & meerwerk (Peter 2026-08-21, BOUW GO): veldkant (ZZP'er/uitvoerder/
  detacheerder in de native app) + kantoorkant (stijl kantoor-modern) — de bouwnorm
  (zie "Uren & meerwerk" hierboven)
- `mockup/planning-steigerbouw.html` — definitief goedgekeurde mockup planning-agenda
  (v2, Peter 2026-08-22; GEBOUWD 2026-08-22) — de bouwnorm voor `/planning` + de
  veld-app-planningweergave
- `mockup/planning-werkopdracht-transport.html` — definitief goedgekeurde mockup
  planning-uitbreiding 31-08 (werkopdrachten per project × periode + transport-dag-agenda
  mét werkbakje/statusflow; ontwerpnotities onderin = onderdeel van het akkoord; GEBOUWD
  2026-08-31) — de bouwnorm voor de Personeel-tab-werkopdrachten en de Transport-tab v2
- `mockup/tegenboek-mockup.html` — definitief goedgekeurde mockup tegenboek-pad (Peter
  2026-08-22, suppletie-signaal geschrapt; GEBOUWD 2026-08-22) — de bouwnorm
- `mockup/projecten-invoer.html` — definitief goedgekeurde mockup kantoor-projectenmodule
  (Peter 2026-08-22, incl. resultaat per project + cumulatief; GEBOUWD 2026-08-22) — de
  bouwnorm
- `verkenning/api-verkenning.md` — alle geverifieerde API-feiten + PoC-resultaten
- `verkenning/odoo-verkenning.md` — **Odoo STAP-0 (02-09-2026, universal-steigers.odoo.com, Odoo 19 JSON-2):
  verbinding/inventaris, veld-voor-veld-mapping RLZ→Odoo, semantiekverschillen, twee live bewijs-cycli,
  beslispunten + klikpunten. Kernfeiten: multi-company-db (10 bedrijven, Universal Verkoop al live),
  boekdatum-default = maandeinde (altijd `date` expliciet), storno = reversal als apart document, bijlage
  ná posten (OCR auto_send). GEEN adapter gebouwd — bouw vergt bouwplan + akkoord (BESLISSINGEN "ODOO STAP-0").**
- `../Platform/` — **gedeelde platform-map (v1.6): koppelcontract-master (`contracten/`),
  besluitenregister (`besluiten/INDEX.md` — lees bij elke sessiestart!), registers (prefixen,
  schema-versies, entiteiten, conventies)**
- `docs/BESLISSINGEN.md` — **statusregister per feature/onderwerp (status + canonieke vindplaats)**
- `docs/BOUWPLAN.md` — fasering en definition of done per fase
- `verkenning/.env` — RLZ-credentials (BLOW + Universal Steigerbouw), NOOIT committen

## Werkwijze

- **`docs/BESLISSINGEN.md` is de verplichte eerste check vóór elk feature-voorstel of bouwstart**
  (pre-feature-ritueel, `Platform/WERKWIJZE.md` v1.9 — incl. de bindende
  bron-vs-realiteit-verificatie, de periodieke drift-audit én de **UX-review vóór elke
  bouwopdracht met scherm-/UX-impact** (besluit Peter 2026-08-15: past het in de bestaande
  IA? mockup-aanpassing nodig? — zichtbaar blok vóór de bouw)): raadpleeg het register + de canonieke
  vindplaats en benoem expliciet waar de feature al staat; goedgekeurde mockup/besluit = 1-op-1
  voortbouwen, niet opnieuw uitvragen. **Capture-at-acceptance:** elk akkoord van Peter meteen in
  dit register (+ canonieke plek) vastleggen, nooit alleen in de chat.
- **Cross-projectdocumenten hebben precies één canonieke locatie**: het koppelcontract leeft
  sinds v1.6 (besluit 0007) als enig exemplaar in `../Platform/contracten/
  KOPPELCONTRACT_RLZ_VASTGOED.md` — het oude kopie+sync-ritueel is afgeschaft, project-repo's
  bevatten alleen verwijzingen; `01_ARCHITECTUUR.md` en `14_ANTWOORD_AAN_RLZ.md` leven
  uitsluitend in de vastgoed-repo. Geen derde kopieën maken.
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
- **Git-werkwijze (2026-08-02, zelfde opzet als de vastgoedmodule):** pushen gaat automatisch
  via de Stop-hook in `.claude/settings.local.json` — na elke afgeronde Claude Code-run wordt
  `git push origin main` gedraaid zodra er lokale commits zijn die origin nog niet heeft (anders
  stil overgeslagen; bij een push-fout een melding, geen retry). De hook pusht **beide repo's**:
  deze RLZ-repo én de Platform-repo (`../Platform`, via `git -C` — twee onafhankelijke
  hook-entries, een fout in de één blokkeert de ander niet; zelfde waarborgen, nooit force).
  `git push` blijft voor de agent in de deny-lijst (incl. force/-f/--delete) — alleen de hook
  pusht, nooit een ad-hoc push tijdens een run. **Committen aan het einde van elke opdracht is
  de standaard-werkwijze (2026-08-02):** Claude Code sluit elke opdracht af door het werk te
  committen onder P. Nijenhuis, in logische, goed-gemessagede commits (feature/docs/config
  gescheiden waar zinvol — geen blinde "commit alles"), zonder op een aparte commit-instructie
  te wachten; de Stop-hook pusht daarna beide repo's. **Uitzondering:** zegt een opdracht
  expliciet "niet committen, eerst review", dan wordt er niet gecommit en stopt de run voor
  review. Force-push blijft verboden.
- **Pre-commit-vangnet frontend (procesnotitie Peter 2026-08-15, les verbeteringen.md 12-08
  vastgoed; aanleiding: deploys #23/#24 rood op een TS-fout die bij het committen gevangen had
  moeten worden):** vóór élke frontend-rakende commit draait `tsc -b` over de VOLLEDIGE actuele
  werkboom — nooit een eerder groen resultaat citeren als er daarna nog geschreven is.
  Afgedwongen door het git-pre-commit-hook `scripts/git-hooks/pre-commit` (per kloon eenmalig
  installeren: `ln -sf ../../scripts/git-hooks/pre-commit .git/hooks/pre-commit` — op deze Mac
  gedaan 2026-08-15); `--no-verify` alleen met expliciete reden.
- Tests verplicht op geldlogica (mapping, totalen, idempotentie, statusmachine) vóór UI-polish.
  **Vaste testconfig (hygiëne-run 2026-08-16, "de webauthn-les"):** de suite draait op de
  code-defaults voor álle settings behalve de vier database-URL's (borging in
  tests/conftest.py + vangnet `tests/unit/test_vaste_testconfig.py`) — een test die een
  afwijkende waarde nodig heeft, pint die zelf via monkeypatch; fixtures muteren `settings`
  nooit direct. **`alembic check` is sinds 2026-08-16 weer een bruikbaar signaal**
  (representatie-drift gelijkgetrokken via type_annotation_map + index-declaraties).
- Elke schrijfactie naar RLZ eerst tegen een testadministratie of met TEST-referentie + akkoord.

## Migraties (afsluit-routine, verplicht — vastgoed-patroon geadopteerd 2026-08-07)

Een taak die een Alembic-migratie bevat is pas "af" als **alle drie** aantoonbaar gedaan zijn:
1. `make migrate` (alembic upgrade head) is gedraaid tegen de **dev-database** (`boekhouding`),
   niet alleen `boekhouding_test` — toon de upgrade-output (Running upgrade X -> Y) in de sessie.
2. Het geraakte endpoint geeft **live een 200** op de draaiende backend (curl tegen poort 8000),
   gecontroleerd ná de upgrade. NB de migratie-guard in de lifespan stopt een draaiende
   `--reload`-uvicorn zodra het migratiebestand vóór de upgrade in de repo staat — dat is
   bedoeld gedrag; na `make migrate` de reload opnieuw triggeren of `make run` herstarten.
3. De referentie-dump is ververst en meegecommit: `scripts/dump_schema.sh` — **vanuit de
   REPO-ROOT draaien, niet vanuit `backend/`** (het script staat in `<repo>/scripts/`; vanuit
   backend/ geeft het "no such file or directory" — 2026-08-12). Dumpt `boekhouding_test` @ head
   naar `backend/migrations/schema_referentie.sql`. Alembic blijft
   de bron van waarheid; de dump is een leesbaarheids-/reviewreferentie, nooit met de hand
   bewerken.
Hangt de upgrade langer dan ~15 seconden: **expliciet melden** (waarschijnlijk houdt een
draaiend proces een lock vast, Peter stopt dat dan even) — nooit stil blijven wachten.
Migraties blijven schema-only (pure DDL); data-backfills zijn losse, expliciete stappen.
Bewaking: `migrations/env.py` importeert álle model-modules (Base.metadata compleet — anders is
`alembic check`/autogenerate onbetrouwbaar); `tests/unit/test_migratie_metadata_guard.py` faalt
als daar een module ontbreekt of als model en gemigreerde database uit de pas lopen.
