# RLZ Boekingsmodule — Administratiekantoor Nijenhuis

Multi-tenant web-app waarmee het kantoor inkoopfacturen, omzetboekingen en bankmutaties verwerkt
in Reeleezee (RLZ) voor tientallen klant-administraties. AI-extractie + mens-in-de-lus controle.

> **Omvang-regel (opdracht Peter 07-09-2026):** dit bestand blijft ruim onder Claude Code's 150k-tekens-limiet
> (daarboven wordt stil afgekapt). Uitgeschreven feature-historie, bouwstatussen, kliktest-nazorg en per-run-
> details zijn op 07-09 WOORDELIJK verhuisd naar `docs/BESLISSINGEN.md`, sectie
> "VERPLAATST UIT CLAUDE.md (07-09-2026)" — één subkop per domein, zelfde naam als de verwijsregel hier;
> laatste volledige CLAUDE.md = commit `ed6d176` (`git show ed6d176:CLAUDE.md`). Regel voortaan: een nieuw
> besluit krijgt hier hooguit één verwijsregel per domein ("X — zie BESLISSINGEN '<sectie>'"), de volledige
> tekst staat in BESLISSINGEN.
> **Guard (blok 14 vervolgrun 07-09):** `backend/tests/unit/test_claude_md_beslissingen_verwijzingen.py` — élke
> BESLISSINGEN-verwijzing hier moet als kop of registerrij bestaan; omvang < 150k tekens.

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
7. **Minimale mens, maximale autonomie (besluit Peter 02-09, capture design-ronde 03-09 —
   BESLISSINGEN "PRINCIPE MINIMALE MENS, MAXIMALE AUTONOMIE" is canoniek):** (1) administratie is
   een FILTER, nooit een poort — kantoorbrede overzichten zijn de norm, een verplichte
   administratie-picker vóór je iets ziet is fout (per-administratie-routes blijven alleen als
   deeplink-doel); (2) signalering zonder handeling is niet af — elk signaal draagt een actie op de
   rij; (3) opt-ins zijn testfase-drempels, geen einddoel; (4) alles schaalt van 2 naar 2000
   administraties (server-side paginering, urgentie-sortering, tellers "N over M administraties");
   (5) de grenzen blijven onverkort: nooit verwijderen in externe systemen, geld in code, harde
   checks blokkerend, audit op alles. Referentie-patroon: het autoboek-kandidaten-scherm.
   **(6) Geen stille no-op (besluit Peter 07-09, WERKWIJZE v1.13):** automatisering wacht NOOIT op een menselijke
   instelling — een lege optionele voorwaarde (eigenaar, toewijzing, ontvanger) = doorlopen, resultaat zonder toewijzing
   in het kantoorbrede overzicht; alleen harde voorwaarden (credential, API-key, geldpoort) blokkeren, altijd zichtbaar;
   elke opt-in heeft een test op het afwezig-pad (guard-test) en dagtellers verwacht/gedaan/overgeslagen in de
   reconciliatiemail — zie BESLISSINGEN "HERSTELRUN 07-09 — GEEN STILLE NO-OP".

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
- **Instellingen › Administraties v2/v3** (compacte tabel + detailPAGINA per administratie mét tabs; ARCHIVEREN,
  nooit verwijderen; migratie 0089) — zie BESLISSINGEN "OPDRACHT 30-08 (2)" blok A + "INSTELLINGEN V3".
- **Terugkerende-facturen-signaal** (`app/terugkerend/`, deterministisch, alleen signaleren; migratie 0090) — zie
  BESLISSINGEN "OPDRACHT 30-08 (2)" blok B.
- **Administratie toevoegen via de UI** (wizard mét verplicht groene rechten-probe, eerste sync als achtergrondrun,
  `verkoopmodule_afwezig` als ENIGE niet-blokkerende probe-uitkomst, `is_vastgoed`-Beheerder-toggle;
  `app/beheer/onboarding.py`) — zie BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08" punt 5, "VERZAMELRUN 27-08" punt 5,
  "SPOEDOPDRACHT 01-09" blok A, "AVONDRUN 26-08".
- DB-schema's: `platform` (gebruikers, rollen, administraties, credential-store, audit log),
  `boekhouding` (deze module). Vastgoedmodule krijgt `vastgoed`, MI-dashboard later `mi`.
- Auth: e-mailuitnodiging (eenmalige link 72 u) + wachtwoord + **TOTP-2FA verplicht**, JWT-sessies.
  Rollen: Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur (scope: eigen administratie).
  **App-auth zonder passkey (besluit Peter 08-09, platformbesluit 0029 = amendement op 0020; migratie 0125): native
  accordeur-/veldwerker-app + accordeur-PWA = toestelbinding (apparaat-gebonden token, rij `webauthn_credential`
  `soort='toestel'`, kill-switch per toestel, 7-dagen sliding TTL) + 5-cijferige toegangscode (lokaal anker, nooit
  server-side); activatie via universal link óf 8-tekens activatiecode uit dezelfde uitnodigingsmail; passkey/TOTP/
  wachtwoord uit de app; legacy-app-routes `Deprecation`/`Sunset`, 410 ná 2026-10-08; kantoor-web ongewijzigd (0020)
  — zie BESLISSINGEN "APP-AUTH ZONDER PASSKEY — TOESTELBINDING + TOEGANGSCODE (besluit Peter 08-09)". Historie
  accordeur-passkeys (2026-08-11, migratie 0040), 24-uurs-cadans 27-08 en pincode-activatie 31-08: archief "Auth"
  (aanvulling 08-09).**
  **Toegangscode wijzigen zonder her-verificatie + salt/wrap als één bewezen geschreven sleutel (bugfix 10-09, ZTE) — zie
  BESLISSINGEN "BUGFIX 10-09 — TOEGANGSCODE WIJZIGEN ANDROID".** Verder (volledige tekst: archief "Auth"): Wachtwoord kwijt = Beheerder-knop "Herstel-link
  sturen" (app-rollen sinds 08-09 mét activatiecode), bewust géén selfservice "wachtwoord vergeten" ("RLZ-FEEDBACKRONDE
  25-08 DEEL 2" punt 7); E-mail wijzigen zonder carrousel ("OPRUIMRUN 28-08" punt 22); activatie externe rollen
  MOBIEL-FIRST + ATOMAIR ("BOUWRUN 28-08 AVOND" blok B, géén eigen push-login; de telefoonroute mondt sinds 08-09 uit in
  de app-activatie); **Platformbesluit 0020 (2026-08-14): passkeys worden de EERSTE authenticatielijn voor álle
  rollen; wachtwoord + TOTP wordt terugval/herstel — sinds 0029 alleen nog voor de kantoor-web**; kantoor-passkeys
  GEBOUWD + GETEST 2026-08-15 ("KANTOOR-PASSKEYS").
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

> De volledige, woordelijke CLAUDE.md-tekst van élk hieronder verkort domein staat in BESLISSINGEN
> "VERPLAATST UIT CLAUDE.md (07-09-2026)" onder de subkop "Domeinbeslissingen — <domein>".

- **Werkvoorraad** = klantenlijst met tellers (alleen klanten mét openstaand werk) → klantpagina →
  controlescherm. Overal breadcrumbs, lijst→detail-patroon consistent.
- **Na boeken direct door + lijstcontext in de URL + sneltoetsen + actiebalk ónder "Doorbelasten na boeken" +
  boekingsregels-kolomminima** (besluiten Peter 25-08 t/m 01-09) — zie BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 4",
  "WERKSTROOM- + UI-RUN 27/28-08", "VERZAMELRUN 27-08" punt 4, "KANTOOR-MINI-RUN 27-08" punt 4, "GECOMBINEERDE RUN
  01-09" blok D; `werkvoorraad/volgendDocument.ts`, `werkvoorraad/lijstContext.ts`, `document/sneltoetsen.ts`.
- **Doorloop na boeken POSITIONEEL (blok 7 vervolgrun 07-09; herziet de soort-voorkeur van 25-08) + DatePicker-blurfix (blok 8) + "+ Nieuwe crediteur in RLZ" altijd bereikbaar (blok 6):** het eerstvolgende verwerkbare document ná het huidige in de getoonde lijstvolgorde, daarna cyclisch; een datum verdwijnt nooit meer stil bij Tab/blur (soepel parsen, anders rode rand + melding); crediteur aanmaken als vaste combobox-voetoptie + linkbtn — zie BESLISSINGEN "FIXRUN 07-09 — BLOK 7+8" en "FIXRUN 07-09 — BLOK 6".
- **Kantoor-frontend-modernisering** (platform-fundament Tailwind v4 + tokens; IA klant-centrisch, drie lagen, klant-klik
  landt DIRECT op de documentenlijst; Instellingen v3 twee-paneel + `instellingenRegistry.ts` fail-closed; `/gebruikers`
  mét archiveren/blokkeren) — zie BESLISSINGEN "Kantoor-frontend-modernisering", "RLZ-FEEDBACKRONDE 25-08" punt C,
  "INSTELLINGEN V3", "RLZ-FEEDBACKRONDE 26-08", "BEHEER-MINI", "Nazorg controls-review". Bindend blijft: GUARD: élk
  nav-item/élke tab heeft een registry-entry (`instellingenRegistry.test.ts`); schaalregel: nieuwe module = nav-regel
  en/of tab, nooit een tegel; regressie-vangnet `frontend/scripts/overflow_sweep.sh` (geen horizontale pagina-overflow).
- **Gebruikers & toegang — tabel-layout met kolomminima en ⋯-menu (blok 2 vervolgrun 10-09 avond; kliktest Peter 10-09; geen migratie):** één bron `gebruikers/gebruikersKolommen.ts` (px-minima per tab, `<colgroup>` + `th` nowrap + tabel-min-width = som, fixed layout; past op 1440 zonder interne scroll, op 1170 scrolt de tabel intern mét sticky acties), Rol · scope en Rechten samengevoegd, Beveiliging-/statuschips op één regel, acties = één primaire knop (Opnieuw mailen / Herstel-link) + ⋯-rijmenu (`GebruikerRijMenu` op `AnkerPopup.rijmenu`), harnas `?breed=1` in de overflow-sweep + `gebruikersKolommen.test.tsx` — zie BESLISSINGEN "GEBRUIKERS & TOEGANG — TABEL-LAYOUT MET KOLOMMINIMA EN ⋯-MENU".
- **Btw-tarief buitenland** (casus Labo Derva: crediteur-datakwaliteit, onvoorwaardelijk oranje signaal + foutvertaling
  `vertaal_rlz_boekfout`) — zie BESLISSINGEN "VERZAMELRUN 31-08 AVOND" blok A.
- **Btw-code uit de scan** (`extractie/controle.py::leid_btw_af`; 0/onbepaalbaar/meerduidig = NOOIT invullen) — zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08" punt 3.
- **Vervaldatum inkoopfactuur** (`boekvoorstel.vervaldatum`, harde check, `DueDate`; migratie 0078) — zie BESLISSINGEN
  "GECOMBINEERDE RUN 26-08" blok C.
- **RLZ-betaalstatus inkoopfactuur + intake-kanaal declaraties@ (blok 3 bundel 08-09 avond; STAP-0 08-09; migratie 0126):** het RLZ-veld "Betaling" = `QuickPaymentSelection`, kaal zetbaar vóór én ná boeken (post blijft open, uit de betaallijst); acht RLZ-waarden letterlijk, herkomst kanaal (declaraties@ → "Betaald per bank") > factuur (deterministische incasso-detectie / UBL PaymentMeansCode 59 → "Wordt automatisch geïncasseerd" + verwachte betaaldatum) > mens wint; harde check "Betaalstatus (declaraties)"; tweede IMAP-postvak `intake-postvak-verwerken --kanaal declaraties`; Odoo = parkeerpost (geen niet-afsluitend equivalent) — zie BESLISSINGEN "RLZ-BETAALSTATUS INKOOPFACTUUR + INTAKE-KANAAL DECLARATIES" + api-verkenning "Betaalstatus inkoopfactuur — STAP-0 08-09".
- **Crediteur-dedup + duplicaat over crediteuren heen** (btw-/KvK-nummer als crediteur-kenmerk, `check_duplicaat_over_
  crediteuren`: zelfde btw-nummer = BLOKKEREND, anders ORANJE SIGNAAL; migratie 0082) — zie BESLISSINGEN "OPRUIMRUN 28-08"
  punt 14.
- **Crediteuren-dubbelen schaalbaar (B13 07-09; migratie 0117):** eenduidige clusters handelt het systeem af (`app/crediteuren/afhandeling.py`, dagelijks in `sync-alles`), verliezers zijn in de MODULE onbruikbaar via één bron `crediteuren/voorkeur.py` (alle voorstel-/match-/geheugen-/Odoo-partner-paden), RLZ-werklijst = optionele CSV-export, terugdraaibaar — zie BESLISSINGEN "CREDITEUREN-DUBBELEN SCHAALBAAR".
- **Crediteuren-dubbelen nazorg (blok 5 vervolgrun 07-09; besluiten Peter op B13-beslispunten 1/2/7):** N = 3 blijft; alleen-KvK-clusters zijn EENDUIDIG (alleen-btw blijft twijfel); legacy-werklijst eenmalig omgezet in markeringen (CLI `crediteuren-werklijst-nazorg`, live 07-09: 2 regels) — zie BESLISSINGEN "VERVOLGRUN 07-09 — BLOK 5".
- **Medewerker-wensen 04-09** (A duplicaat-auto-afvoer STANDAARD AAN achter één platformbrede noodrem, B splitsing
  bijlage-bewust + "nooit splitsen" per afzender, C projectverdeling pro rato omzet, D regel-niveau GB-voorstel, E
  btw-default per administratie, F bugfix Huvanco/`regelsom.py`; migraties 0105–0109) — zie BESLISSINGEN
  "MEDEWERKER-WENSEN 04-09" (canoniek per blok), mockup `projectverdeling-en-regelvoorstellen.html`.
- **Bulk-afvoer op de Mogelijk-duplicaat-tab (B2 07-09):** checkbox + "alle N" server-side + "Afvoeren als duplicaat (n)" over de bestaande per-document-route, buiten de 20/dag-rem, uitkomst per rij — zie BESLISSINGEN "BULK-AFVOER OP DE MOGELIJK-DUPLICAAT-TAB".
- **Duplicaten hoofdmodel (blok 1 vervolgrun 07-09; besluit Peter "duplicaten eruit, geen lijst"):** harde check "Duplicaat (module)" tegen de EIGEN DB (sha256 / genormaliseerde referentie + bedrag over álle crediteur-records / crediteur+referentie bij ander bedrag), directe auto-afvoer (a)/(b) buiten de 20/dag-rem, mens-override alleen via afmelden mét reden, Archief-filter "afgevoerd" + Zoeken-chip, CLI `duplicaten-backfill` (live 07-09: Universal 110, Kempen Facilities 6); UBL+PDF = bundel, nooit duplicaat — zie BESLISSINGEN "DUPLICATEN HOOFDMODEL".
- **Herstelrun 07-09 blok A (Kempen-"duplicaten" = niet dubbel in RLZ; RLZ-duplicaatcheck cent-exact client-side; "Tegenboeken…" direct bij een geboekt module-duplicaat; RLZ negeert document-`Description` op PurchaseInvoices → kop als `Header`, afkap 200):** zie BESLISSINGEN "HERSTELRUN 07-09 — BLOK A" + api-verkenning "Description op PurchaseInvoices — STAP 0 07-09".
- **Duplicaten blok D herstelrun 07-09 (beeld-sha van een gebundeld document = categorie (a) zonder migratie, gesplitste delen nooit (b)/(c) zonder referentie/totaal, Odoo-crediteur zonder partner-koppeling = leesbare blokkerende check i.p.v. 500; live Universal 12 Floor-PDF's afgevoerd):** zie BESLISSINGEN "HERSTELRUN 07-09 — BLOK D".
- **Duplicaten-UI — eigen status `afgevoerd_duplicaat` (blok 3 bundel 08-09; migratie 0122; herziet "afgevoerd = afgewezen mét kruisverwijzing"):** telt in geen werkvoorraad-teller/-tab mee, terugvindbaar via Archief/Zoeken + toggle "Toon afgevoerde documenten", reden "automatisch (duplicaatregel)", backfill-CLI `duplicaat-status-backfill` — zie BESLISSINGEN "DUPLICATEN-UI — EIGEN STATUS `afgevoerd_duplicaat`".
- **Afgehandelde documenten — één toggle (definitieve aanvulling blok 3, Peter 08-09):** eindstatussen `samengevoegd`/`afgevoerd_duplicaat`/`verwijderd`/`afgewezen` (`AFGEHANDELDE_STATUSSEN`) standaard niet in de documentenlijst en niet in "Alle"; toggle "Toon afgehandelde documenten (N)" toont ze grijs mét reden + "→ samengevoegd in ‹document›"/"→ duplicaat van ‹document›"; tellers reizen altijd mee (`tel_afgehandeld`, chip afgewezen blijft); ⋯-menu op zo'n rij alleen Openen/Toon origineel (+ Herstellen bij verwijderd); chip "N exemplaren samengevoegd" op het echte document; boeken/aanbieden = 409 (`DocumentNietAanbiedbaar`). Plus de live-uitkomsten van de cloud-scripts (wachtrij-restoorzaak = doorbelasting-`review_data` per item, `rlz_dubbel` bij Kempen 516 paren = niet inzetbaar, backfills uitgevoerd) — zie BESLISSINGEN "NAZORGRUN 08-09 — CLOUD-UITKOMSTEN BUNDEL 08-09 + AANVULLING BLOK 3".
- **Herstelrun "Basis eerst" 08-09 (besluit Peter: nieuwe definitie van "af" = gouden set groen + productie-nameting + rapportregel "werkt in productie: ja/nee"; geen nieuwe functies, elf blokken; migraties 0123–0124):** overzicht + per-blok-secties — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — OVERZICHT".
- **Gouden set = verplichte poort (blok 0):** `backend/tests/keten/` + `frontend/scripts/keten_sweep.sh`, guard `tests/unit/test_keten_guard.py` — zie BESLISSINGEN "GOUDEN SET — KETENTEST OP ECHTE DOCUMENTEN" en § Werkwijze hieronder.
- **Gouden set — export deterministisch, referentiedatum bevroren (blok 5 vervolgrun 10-09 avond; geen migratie):** `b_floor.json` dreef op de afwijsreden "… van <ontvangstdatum> …" (`aangemaakt_op` = DB-`now()`); de `Keten`-fixture bevriest ná élke intake-stap het ontvangstmoment op `REFERENTIE_TIJDSTIP` 2026-09-08T12:00Z (ties blijven ties), guard `tests/keten/test_export_deterministisch.py` (export = gecommitte fixture, herhaling byte-gelijk, geen datum-van-vandaag in de exports) + dezelfde toets in `keten_sweep.sh`; detail-baselines 10-09 ververst — zie BESLISSINGEN "GOUDEN SET — EXPORT DETERMINISTISCH, REFERENTIEDATUM BEVROREN".
- **Wachtrij accordeur-app doorbelasting in bulk (blok 1):** `verdeling_per_doelentiteit_bulk`, statement-aantal constant per administratie — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 1".
- **Extractie-wachtrij-trigger (blok 2):** trigger werkt in productie sinds revisie 00462 (13/13 uploads → job-executie < 1 s); audit-spoor `extractie_wachtrij_trigger` + teller in de reconciliatiemail — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 2".
- **UBL is deterministisch (blok 3):** kop, crediteur (btw → KvK → IBAN → naam), regels en datums rechtstreeks uit de XML bij intake (`app/documenten/ubl_voorstel.py`), AI hooguit aanvullend; crediteur-dialoog gevuld uit UBL, PDF-in-verwerking toont "Verwerking loopt — velden volgen" — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 3".
- **RLZ-bestaanscheck op het juiste moment (blok 4):** al geboekt in RLZ/Odoo = direct `afgevoerd_duplicaat` mét boekstuknummer (UBL bij intake, PDF ná extractie), geen credential = zichtbaar overgeslagen; chip "N exemplaren samengevoegd/afgevoerd" — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 4".
- **Klant-accordeurs: scope vanuit de accordeur (blok 5):** "Administraties toevoegen…" over `POST /accordering/bulk-instellen`, verwijderen mét vervallen-rondes- en laatste-laag-waarschuwing (`aanleiding` in audit + tijdlijn), gearchiveerde administraties als naam mét status — zie BESLISSINGEN "KLANT-ACCORDEURS — SCOPE VANUIT DE ACCORDEUR".
- **Verlegd-tarief deterministisch (blok 6; migratie 0123):** `voorkeurs_verlegd_taxrate_id` per administratie (Beheerder) → meest gebruikt in RLZ-historie → bestaand pad → default, mét herkomst-chip — zie BESLISSINGEN "VERLEGD-TARIEF DETERMINISTISCH KIEZEN".
- **Reconciliatie `rlz_dubbel` alleen op referentie (blok 7):** bedrag+datum vervallen, placeholder-referenties tellen als leeg; BOOT 202632703/04 = aanvaarde grens — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 7".
- **Rapport verwijderde documenten Universal Steigerbouw 08-09 (blok 8, alleen lezen):** 222 verwijderd "dubbel", 197 zonder ander exemplaar — zie BESLISSINGEN "RAPPORT VERWIJDERDE DOCUMENTEN UNIVERSAL STEIGERBOUW 08-09".
- **Hercontrole projectverdeling (blok 10; migratie 0124):** lege omzetstand = bevinding "omzetcijfers ontbreken" mét actie cijfers-sync, geen signaal onder de drempel, hercontrole alleen ná afsluiting van de referentiemaand — zie BESLISSINGEN "HERCONTROLE PROJECTVERDELING — VALSE SIGNALEN, CADANS, BEVINDING".
- **Lijst-aanvulling — de standaardlijst is kantoorwerk (blok 11, besluit Peter 08-09):** `geboekt` onder de toggle afgehandeld (grijs, boekstuknummer, "Open in Reeleezee/Odoo"), tab "Geboekt (N)" vervalt, "Wachten op anderen (N)" = ter accordering + open vraag en telt niet in "Alle", `?groep=kantoor|wachten|afgehandeld`; klantenlijst-tellers/KPI's tellen alles — zie BESLISSINGEN "LIJST-AANVULLING — DE STANDAARDLIJST IS KANTOORWERK".
- **Verplichtingen — offerte-accordering + factuur↔offerte-match** (documenttype `verplichting`, géén RLZ-/Odoo-boeking,
  deterministische match-motor `app/verplichting/match.py`, nooit blokkade; migratie 0110) — zie BESLISSINGEN
  "VERPLICHTINGEN + FACTUUR↔OFFERTE-MATCH 04-09", mockup `offerte-matching.html`.
- **Boekingsgeheugen**: RLZ-historie + app-correcties; correcties wegen zwaarder (recency). Default
  voorstel, nooit blind boeken. Afwijkingen markeren (oranje), niet overnemen. **Seed-only = oranje
  (aangescherpt 2026-07-14): een waarde die uitsluitend op RLZ-historie steunt blijft oranje ("uit
  historie, nog niet bevestigd"), óók bij hoge stem-confidence — pas de eerste app-bevestiging van
  die waarde maakt 'm groen (`app_bevestigd` per veld in engine + voorstel-response).**
- **Boekingsgeheugen — recency wint (blok 3.1 nametingen-run 10-09 avond, besluit Peter; geen migratie):** de laatste drie MENS-boekingen identiek (gegroepeerd per boekstuk) → die waarde groen + app-bevestigd, oudere afwijkende waarden tellen niet meer mee in de tie-break maar blijven zichtbaar als "eerder ook: …" (`VeldVoorstel.recent_consensus`/`eerder_ook`); B-A-A-A groen, A-A-B/A-B-A-A oranje, seed-only oranje; automatische boekingen schrijven geen observatie meer (`leg_boeking_vast(automatisch=True)`); activatie-motor ongewijzigd, rapportteller `eerder_afwijkend` — zie BESLISSINGEN "BOEKINGSGEHEUGEN — RECENCY WINT".
- **Prefill-autosave bij openen (A10 07-09):** leverancier-geheugen server-side in de prefill; `GET …/boekvoorstel` persisteert geheugen-/template-/default-prefills direct (herkomst-chip blijft, mens wint, idempotent, tijdlijn + audit) zodat checks en doorbelasten-blok dezelfde stand zien — zie BESLISSINGEN "STALE CHECK BIJ GEHEUGEN-PREFILL".
- **Controlescherm auto-first velden (blokken 9/10 vervolgrun 07-09, besluit Peter "auto-first"):** kop-omschrijving deterministisch (één regel → regeltekst; anders AI-veld `betreft`; anders leverancier + factuurnummer; mens wint als tijdlijn-override) en mee als RLZ `Description` / Odoo `narration`; projectnummer uit de factuur op kop- én regelniveau (AI-veld `proj`, gedeelde motor `app/projecten/match.py`: exacte code > leverancier-werknummer > plaats/opdrachtgever alleen oranje; meerduidig = nooit invullen; eerste keer per leverancier oranje, ná één boeking groen) — zie BESLISSINGEN "KOP-OMSCHRIJVING AUTOMATISCH" en "PROJECTNUMMER UIT DE FACTUUR".
- **Controlescherm Spot Services (blok 4 bundel 08-09; geen migratie):** tariefstaffel-regels (aantal 0, bedrag 0) zijn bron, geen boekingsregel (`documenten/veldvoorstel_regels.py`); één regel-projectnummer = kop-default; "btw verlegd" + btw 0 → verlegd-tarief oranje; winnaarsvolgorde btw mens > factuur berekend > geheugen > factuur verlegd > default > leeg (`regel_prefill.py`); chips één regel, kolomminima 184/168/200, verplichte velden geaggregeerd — zie BESLISSINGEN "CONTROLESCHERM SPOT SERVICES 2026-608".
- **Factuurperiode op weekniveau — datalaag (blok 11 vervolgrun 07-09; migratie 0120):** AI-veld `periode` (sentinel) deterministisch genormaliseerd naar ISO-week(s) (`app/documenten/periode.py`, weeklogica uit `app/uren`), terugval = week van de factuurdatum, kolommen op `boekvoorstel`, chip "Periode (weken)" met herkomst in het controlescherm (mens wint), niet-blokkerend signaal in de factuurmatch; GEEN weekweergave van kosten per project (schermimpact → mockup) — zie BESLISSINGEN "FACTUURPERIODE WEEKNIVEAU — DATALAAG".
- **Periode-backfill (blok 7 bundel 08-09):** CLI `periode-backfill [--dry-run] [--administratie] [--alle-statussen]` vult de 0120-kolommen van geboekte documenten deterministisch (AI-veld → terugval factuurdatum, mens wint, tijdlijn + audit, idempotent; `app/documenten/periode_backfill.py`) — zie BESLISSINGEN "PERIODE-BACKFILL".
- **Automatisch boeken = opt-in per leverancier**; harde checks blijven áltijd blokkerend.
  **Status per harde/blokkerende check: canoniek in `docs/BESLISSINGEN.md` (verplichte eerste
  check, houd dáár actueel — gedocumenteerd ≠ gebouwd).** De korte opsomming van gebouwde checks, de
  per-leverancier-autoboeken-opt-in (GEBOUWD + GETEST 2026-08-09, migratie 0036 + `app/documenten/autoboeken.py`),
  de autoboek-kandidaten-motor (`app/autoboek_kandidaten/`, migratie 0095) en het principe **Automatisering-first
  (Peter, 2026-08-16, WERKWIJZE v1.10): mens-op-de-knop is een testfase-drempel en afwijkings-vangnet, geen
  einddoel — elk deterministisch pad krijgt een autoboek-opt-in volgens het vaste patroon (default UIT, harde
  checks blokkerend, volumerem, 'automatisch'-markering + audit, storno als terugweg)** staan in BESLISSINGEN
  "Harde/blokkerende checks", "AUTOBOEK-KANDIDATEN-MOTOR", "Autoboek-afweging overige deterministische paden" en het
  archief "Automatisch boeken".
- **Vragenworkflow**: vraag blokkeert boeken, toegewezen aan eigenaar per administratie, antwoord
  voedt het geheugen. Vragen zijn een status in de werkvoorraad (geen apart menu).
  **DIALOOG-model (besluit Peter 25-08, migratie 0064): een vraag is een thread; blokkeert boeken tot "Afgehandeld"
  door de oorspronkelijke vraagsteller.** Vraag aan de klant-accordeur (26-08 blok B5, migratie 0079). Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt B + "GECOMBINEERDE RUN 26-08" blok B.
- **Leeg = doorlopen — toewijzing optioneel (blok 2 herstelrun 07-09; migratie 0121):** geen eigenaar/toegewezene houdt geen automatisering meer tegen (afwijzen, vragen, duplicaat-afvoer, autovraag, verplaatsen → `toegewezen_aan = NULL`, kantoorbreed zichtbaar als "niet toegewezen"; `GeenToewijzingMogelijk` vervallen); guard `tests/unit/test_optin_afwezig_pad_guard.py` + marker `afwezig_pad` per opt-in — zie BESLISSINGEN "LEEG = DOORLOPEN — TOEWIJZING OPTIONEEL".
- **Afwijzen** = verplichte reden, blijft zichtbaar ("Afgewezen — ter controle").
- **Verzamelbak "Niet toegewezen"**: alles wat niet eenduidig aan een administratie koppelt
  (tenaamstelling leidend, afzender = hint); leert van handmatige toewijzingen; "hoort niet bij
  ons" met reden. Nooit auto-toewijzen bij twijfel.
  Bouwstatus, preview per rij (`AnkerPopup`), OPTIMISTISCH toewijzen, "Verplaats naar andere administratie…"
  (`app/documenten/verplaatsen.py`), documentenlijst-hiërarchie + sorteerbare kolommen: zie BESLISSINGEN
  "E-mail-intake + verzamelbak — GEBOUWD + GETEST", "AVONDRUN 26-08", "KANTOOR-MINI-RUN 27-08" punt 5, "WERKSTROOM-
  + UI-RUN 27/28-08", "OPRUIMRUN 28-08" punt 21. Bindend blijft: Administratie-kiezers zijn overal in de kantoor-UI
  een doorzoekbare combobox (`ui/AdministratieCombobox`, punt 13) — nooit meer een kale select; nooit meer een
  absoluut gepositioneerde popup bínnen `.tabel-scroll`/`table{overflow:hidden}`.
- **Verzamelbak-rij (C9 07-09):** soort-keuze = chip-toggle Factuur/Offerte onder de twijfelchip, kolombreedtes uit één bron (`VERZAMELBAK_KOLOMMEN`), constante rijhoogte, sweep-variant `?twijfel=1` — zie BESLISSINGEN "FIXRUN 07-09 — BLOK C9".
- **Nabundel-motor dubbel-exemplaren (blok 2 vervolgrun 07-09; herziet 03-09 "niet bouwen"):** byte-identieke PDF-/UBL-exemplaren uit hetzelfde intake-bericht worden samengevouwen (`samengevoegd` mét verwijzing, nooit verwijderd, terugdraaibaar); AFGEWEZEN telt als terminaal en ontgrendelt het paar; herdraai Universal Steigerbouw live 07-09 (26 paren) — zie BESLISSINGEN "B2 — NABUNDEL-MOTOR".
- **E-mail intake**: één centraal adres — **`facturen@ak-nijenhuis.nl`** (adreskeuze Peter
  2026-08-15, bewust kort; Google Workspace) — splitsen van multi-factuur-PDF's op
  factuurgrenzen, toewijzen op tenaamstelling.
  GEBOUWD + GETEST 2026-08-07; live IMAP-fetch GEACTIVEERD (F3.4, 2026-08-15); PDF → intake-AI achter de
  platform-brede AVG-gate `intake_ai_ingeschakeld`; **Eén extractiepad voor álle ingangen** via
  `upload_document`/`start_extractie_na_toewijzing` achter dezelfde gates (per-administratie
  `ai_extractie_ingeschakeld` + API-key + AI-kostengrens); mail-body + afbeeldingen (migraties 0069/0070). Zie
  BESLISSINGEN "E-mail-intake + verzamelbak — GEBOUWD + GETEST", "RLZ-FEEDBACKRONDE 26-08" punt 4, "RLZ-FEEDBACKRONDE
  25-08 DEEL 3", GCP_UITROL §F3.4. Bindend blijft: Dependencies staan in `pyproject.toml` (geen requirements.txt) en
  worden bewaakt door `tests/unit/test_dependencies_gedeclareerd.py`.
- **AI-kostengrens intake** (max € 100 per kalendermaand, deterministische kostenmeter `backend/app/aikosten/`, harde
  poort vóór élke call, boven de grens NOOIT stil wegvallen; migratie 0047) — zie BESLISSINGEN "AI-KOSTENGRENS INTAKE".
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
- **Deterministische extractie-terugval — template per bekende leverancier** (`app/extractie/template_terugval.py`,
  NIET achter de AI-AVG-gate, één rood = VOLLEDIG verworpen; migratie 0094) — zie BESLISSINGEN "EXTRACTIE-TERUGVAL
  TEMPLATES".
- **Best-practice-punten D1–D4** — zie BESLISSINGEN "BEST-PRACTICE-PUNTEN D1–D4". Bindend blijft (D1): "Wat is nieuw"
  = hand-gecureerd `frontend/src/changelog/WAT_IS_NIEUW.md` (klantleesbaar, nieuwste bovenaan — **VERPLICHT bijvullen
  bij élke feature-commit**, guard-test op vorm/jargon).
- **Synthetische bewaking + alerting** (job `rlz-bewaking` elk kwartier, `app/bewaking/`, post-deploy-smoketest;
  migratie 0092) — zie BESLISSINGEN "SYNTHETISCHE BEWAKING + ALERTING".
- **Reconciliatie-melding + Inzicht › Reconciliatie** (`reconciliatie-alles`, mail alleen als er iets te melden is,
  `/reconciliatie`; migratie 0114) — zie BESLISSINGEN "RECONCILIATIE-MELDING + INZICHT".
- **Reconciliatie 07-09 (A11/A12/A8):** verdwenen extern document = `ontbreekt_in_rlz`/`ontbreekt_in_odoo` (zwaarste categorie) mét actie "Opnieuw boeken" zonder tegenboeking (`app/documenten/herboeken.py`, GEBOEKT → KLAAR_OM_TE_BOEKEN, boek_cyclus +1); documenten-blok backend-agnostisch via `InkoopPort.toets_geboekt` (Odoo: posted/amount_total/onbekende reversal), bank/omzet/doorbelasting blijven RLZ-only en slaan Odoo-administraties zichtbaar over; bevindingen leesbaar (titel/wat/doe, `app/reconciliatie/teksten.py`) en acceptatie direct zichtbaar — zie BESLISSINGEN "A11 — DOCUMENTEN-RECONCILIATIE", "A12 — RECONCILIATIE BACKEND-AGNOSTISCH", "RECONCILIATIE-TEKSTEN LEESBAAR + ACCEPTATIE-BUG".
- **Reconciliatie-herzieningen vervolgrun 07-09 (blok 3 + 4, correcties Peter):** herboeken van een verdwenen document BLOKKEERT als de boekdatum in een ingediende btw-periode valt ("btw mogelijk al aangegeven — suppletie-pad", 409); alleen een Beheerder zet door met expliciete bevestiging + reden (audit + tijdlijn); Odoo-variant via lock dates; fail-closed bij onleesbare aangiftestatus — A11-rij "Volumerem / aangifte-poort — HERZIEN 07-09". RLZ-verleden van een overgestapte administratie wordt tegen RLZ getoetst via de bewaarde credential (`client_voor_rlz_verleden`), nooit meer "niet van toepassing" — zie BESLISSINGEN "RLZ-VERLEDEN VAN EEN OVERGESTAPTE ADMINISTRATIE".
- **Tellers per automatisering in de reconciliatie (blok 3 herstelrun 07-09):** per automatisering per etmaal verwacht/gedaan/overgeslagen mét reden uit bestaande audit-/run-sporen (`app/reconciliatie/automatiseringen.py`, geen migratie), LET-OP mét deeplink bij een ontbrekende harde voorwaarde en bij zeven dagen stil; uit = één regel — zie BESLISSINGEN "TELLERS PER AUTOMATISERING IN DE RECONCILIATIE".
- **Automatiserings-tellers weg van het werkscherm (blok 5 bundel 08-09; feedback Peter "wat moet ik hiermee"; geen migratie):** het blok "Automatiseringen" staat op Instellingen › Boeken platformbreed (één regel "N aan · M let-op", open bij LET-OP mét "Naar de instelling →", uit-regels niet getoond, sleutel-agnostisch), Inzicht › Reconciliatie toont alleen bevindingen mét handeling, de mail draagt het volledige blok alleen bij een LET-OP (anders "Automatiseringen: alles gelopen (N aan)"); productie 08-09: de LET-OP "duplicaat-afvoer 155× geen eigenaar" stamt van vóór 0121 (laatste weigering 07-09 16:57) en verdwijnt bij de run van 09-09 — zie BESLISSINGEN "AUTOMATISERINGS-TELLERS WEG VAN HET WERKSCHERM".
- **Reconciliatiemail = ACTIEMAIL + SYSTEEMMAIL (blok 1 bundel 09-09, feedback Peter 09-09 "veel te veel input"; geen migratie):** kantoor krijgt alleen bij bevindingen mét handeling één mail "N zaken vragen je aandacht" (één regel per zaak, één link naar /reconciliatie, max 10 + "en N andere", guard-test `tests/reconciliatie/test_actiemail_guard.py`); de volledige inhoud gaat als "[systeem] …" naar setting `reconciliatie_beheer_ontvangers`; regressie-LET-OPs (o.a. `geen_eigenaar`) = "Systeemfout — automatisch gemeld" + audit `automatisering_regressie` + bewakingsprobe — zie BESLISSINGEN "RECONCILIATIEMAIL = ACTIEMAIL + SYSTEEMMAIL".
<!-- bundel-10-09:E -->
<!-- bundel-10-09:A -->
<!-- bundel-10-09:B -->
<!-- bundel-10-09:C -->
<!-- bundel-10-09:D_backend -->
<!-- bundel-10-09:D_docs -->
<!-- bundel-10-09:F -->
- **Activatieflow: mislukte eerste opslag van de toegangscode eerlijk gemeld (bugfix 10-09 (2), blok F bundel 10-09):** `stelCodeIn` → false = fase `slot_fout` (melding + diagnoseregel + "Opnieuw proberen" op hetzelfde activatieresultaat — `POST /auth/app/activeren` is éénmalig, nooit een tweede server-activatie), geen `naGeactiveerd`/wachtrij; zelfde patroon op het legacy-pad in `AccordeurApp`; `stelCodeIn` laat bij false het anker uit het geheugen en een plain token plain — zie BESLISSINGEN "BUGFIX 10-09 (2) — ACTIVATIEFLOW: MISLUKTE OPSLAG TOEGANGSCODE EERLIJK GEMELD".
- **Vastgoedgroep Nederland → Odoo, run 1 (D3/D4, 10-09 + ADDENDUM 10-09 avond; geen code, geen migratie):** GEEN MI-dashboard in de module (besluit Peter 10-09 avond) — de module houdt alleen Register + Toewijzing (mét kolom Behandeling activeren/periodekost/balans/overhead en VERPLICHT veld verwachte verkoopprijs bij aankoop; kolommen in `pand` = run 2) en publiceert een lees-only leesroute (eigen module-rol 0019 + toestelbinding 0029, geen berekende marges); álle marge-/overhead-/break-even-berekening in een aparte Vastgoedgroep-PWA (`mockup/vastgoedgroep-app.html`, ter akkoord bij VGG); boekmodel RJ 220: pand = handelsvoorraad, geactiveerd = koopsom + direct toerekenbare kosten om verkoopklaar te maken, overige kosten W&V wanneer gemaakt, verkoop = opbrengst tegenover kostprijs verkopen (drie rekeningen, nummers run 2 — odoo-verkenning §11.6); referentie-mockups `mockup/pandenregister-cowork.html` (kantoor, alleen tabs Register + Toewijzing = bouwscope) + `vastgoedgroep-app.html`; `pandenregister.html` dashboard-tab doorgestreept als historie, notities ①–⑩ per stuk herwaardeerd + lees-only Odoo-verkenning §11 (statement lines, reconciliatiemodellen in 19 zonder `rule_type`, verkoopfactuur notaris `tax_ids=[]`, bewijscyclus op de TESTdatabase; `ODOO_TEST_URL`/`ODOO_TEST_API_KEY` als secrets) — zie BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 1: MOCKUP PANDENREGISTER + ODOO-VERKENNING".
- **Vastgoedgroep Nederland → Odoo, run 1 (bundel 10-09 blok D1/D2; migratie 0130):** lees-only CLI `migratie-schoonlijst` (concepten, dubbelen bedrag+datum+relatie, open bankregels op `OpenAmount`, dubbele IBAN, zonder-relatie-mét-bijlage; verwachtingen Peter als `--verwacht`, nooit hardgecodeerd) + datalaag `pand`/`pand_boeking` met deterministische afleiding `app/panden/afleiding.py` (aankoop = memoriaal RLZ-06 mét adres + notaris-PDF/dossier, verkoop = verkoopfactuur op notaris; meerduidig = nooit invullen) en CLI `pandenregister-afleiden` (default dry-run, `--schrijf` = voorstellen, mens wint; Overhead-project alleen gerapporteerd — aanmaken = RLZ-write, run 2) — zie BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 1: SCHOONLIJST + PANDENREGISTER-DATALAAG"
- **Vastgoedgroep Nederland → Odoo, run 2 (12-09; besluiten Peter 12-09: geen Odoo-testdatabase → direct company 6 als CONCEPT mét harde company-pin en kill-switch, RJ 220 vier rollen incl. vooruitbetaald op voorraad, pandenlijst-seam CSV, bank leidend bij dubbelen; migraties 0137–0138; geen schermen, geen posten):** RLZ knipt bank-omschrijvingen op 32 tekens met `\n` → `app/rlz/tekst.py::ontknip` is de enige normalisatie; schoonlijst mét systeemhulzen/kopieën/verschillend kenmerk/bank-bevestigd; lees-only snede 2 over alle administraties; pandenregister herbouwd (soorten aanbetaling/vaste_lasten/balans, verkopen uit notaris-ontvangsten, clustering/pandenlijst); RJ-220-rollen in de koppeling-rij (`app/odoo/rj220.py`, voorstel 325000/326000/803100/701300); Odoo-schrijfpad `app/migratie/odoo_doel.py` + `odoo_schrijf.py` (CLI's `odoo-koppeling-migratiedoel`, `vgg-odoo-stap0`, door nameting.sh geweigerd); replay dry-run `vgg-replay` met reconciliatierapport — zie BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 (12-09-2026)", "SCHOONLIJST VGG HERZIEN", "DUBBEL-SNEDE 2 OVER ALLE ADMINISTRATIES", "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 3", "RJ-220-ROLLEN OP ODOO COMPANY 6", "ODOO-SCHRIJFPAD STAP-0 OP COMPANY 6", "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 6" + api-verkenning "Regelknip op 32 tekens" + odoo-verkenning §12.
- **Rechten-probe = eerste-sync-routes + herprobe met de opgeslagen login (blok C bundel 10-09, bevinding Baard; geen migratie):** één bron `app/rlz/leesroutes.py` voor probe-set én sync-paden (fail-closed test `tests/rlz/test_leesroutes.py`), wizard/wijzigen/dearchiveren proben ná de invoer-probe óók in de OPGESLAGEN vorm (wrap → unwrap → verse client = de credential-resolutie van de sync; rood = niets opgeslagen), letterlijk RLZ-antwoord (≤ 300 tekens) + RLZ-recht per route in melding/DTO/audit, `POST /administraties/{id}/rlz-check` = herprobe met de store-login, eerste-sync-401/403 = leesbare LET-OP-stand per onderdeel — zie BESLISSINGEN "RECHTEN-PROBE = EERSTE-SYNC-ROUTES + HERPROBE MET DE OPGESLAGEN LOGIN"
- **Bank: historie-regel + AI-plausibiliteitstoets als poort (blok B bundel 10-09, besluit Peter 10-09; migratie 0129):** stap 3b `historie_regel` (IBAN + omschrijvingskern, bedrag vrij, ≥ 6 mnd dekking, ≥ 3 boekingen, 100 % = groen/automatisch kandidaat, k van n = oranje, nooit bij open posten voor de tegenpartij; cache `bank_historie_boeking`, backfill-CLI `bank-historie-backfill`) + `app/aitoets/plausibiliteit.py` als POORT vóór élke automatische bankboeking (vaste regel én historie; AVG-gate/API-key/kostengrens/AI-fout = zichtbaar overgeslagen, twijfel = open mét chip, audit per toets, sentinel-schema 0 unions) en optioneel op factuur-autoboekingen (`boeken_instelling.ai_toets_facturen_ingeschakeld`, default AAN, `GET/PUT /instellingen/boeken/ai-toets`); nameting `bank-voorstellen-lezen --met-ai-toets` — zie BESLISSINGEN "BANK — HISTORIE-REGEL + AI-PLAUSIBILITEITSTOETS ALS POORT"
- **AI-plausibiliteitstoets — uitval = doorlopen, zichtbaar (blok 4 vervolgrun 10-09 avond; besluit Peter 10-09; herziet de poort-semantiek van blok B; geen migratie):** technische uitval van de toets (AVG-gate uit, geen API-key, kostengrens, AI-fout) houdt geen automatische bank- of factuurboeking meer tegen — de deterministische poorten blijven de eis, de boeking draagt chip "zonder AI-toets" (`PlausibiliteitUitkomst.zonder_ai_toets` + `oorzaak`), audit `ai_plausibiliteitstoets` mét oorzaak + `automatisch_geboekt_zonder_ai_toets`, teller `ai_toets_overgeslagen` en een LET-OP "controleer steekproefsgewijs" mét deeplink; `twijfel` blijft NIET boeken, de AVG-gate blokkeert alleen de AI-call — zie BESLISSINGEN "AI-PLAUSIBILITEITSTOETS — UITVAL = DOORLOPEN, ZICHTBAAR".
- **Autoboeken per administratie — leren en boeken (blok A bundel 10-09, besluit Peter 10-09; herziet "kandidaten → mens klikt aan" 01-09; migratie 0128):** één Beheerder-schakelaar per administratie (default UIT, doorbelasting = 409), het systeem ACTIVEERT de per-leverancier-opt-in zelf ná ≥ 3 mens-boekingen op rij ongewijzigd (`autoboek_kandidaten/service.py::activeer_kwalificerend`, post-commit ná élke mens-boeking + dagelijks), per-leverancier-lijst = uitzonderingenlijst (uitzonderen mét reden / vrijgeven), storno/correctie van een automatische boeking = terug op "leert 0/3" (audit + tijdlijn), B3-AI-toets als extra poort, teller `autoboek_leren` + CLI `autoboek-leren-rapport` (lees-only meetrecept) — zie BESLISSINGEN "AUTOBOEKEN PER ADMINISTRATIE — LEREN EN BOEKEN"
- **AI-toets platform-opt-out zichtbaar (blok 3.2 nametingen-run 10-09 avond, besluit Peter; geen migratie):** `ai_toets_facturen_ingeschakeld` = UIT is niet meer stil — chip "AI-toets uit (platform)" + tijdlijnregel op elke automatische factuurboeking, teller `ai_toets_uit` en LET-OP "AI-toets staat platformbreed uit sinds <datum>" (actiemail, deeplink Instellingen › Boeken; óók bij 0 boekingen); mens-zette-uit ≠ toets-viel-uit (`PlausibiliteitUitkomst.ai_toets_uit` vs `zonder_ai_toets`) — zie BESLISSINGEN "AI-TOETS PLATFORM-OPT-OUT ZICHTBAAR".
- **Autoboeken — drempel telt drie identieke mens-boekingen (blok 3 vervolgrun 10-09 avond; besluit Peter 10-09; herziet de telling van blok A; geen migratie):** de reeks = langste staart van opeenvolgende mens-boekingen met onderling gelijke GB/btw/project (eerste boeking = 1/3, afwijkende boeking start een nieuwe reeks, automatisch telt niet en breekt niet, `reeks_vanaf` blijft), correcties blijven t.o.v. het voorstel gemeten en de service toetst dat het geheugen dezelfde waarden voorstelt als de reeks (`Reeks.reeks_waarden`); teksten "N identieke boekingen"; open beslispunt: één afwijkende boeking maakt de geheugen-stem blijvend "gesplitst" (oranje) — zie BESLISSINGEN "AUTOBOEKEN — DREMPEL TELT DRIE IDENTIEKE MENS-BOEKINGEN".
- **Autonomie-toekomstlijn (ontwerpnotitie blok E bundel 10-09, geen bouw; wacht op akkoord Peter):** vijf richtingen (1 boekhouden op uitzondering, 2 AI schrijft deterministische regels + backtest, 3 leren over administraties heen op RGS-niveau, 4 nachtelijke AI-onderzoeker, 5 AI-auditor-steekproef → foutkans) met volgorde-advies 2 → 5 → 3 → 4 → 1, harde grens "AI kiest nooit een rekening zonder deterministische toets; AI-uitval = doorlopen zonder AI, zichtbaar" — canoniek `docs/ONTWERP_AUTONOMIE_TOEKOMST.md`, zie BESLISSINGEN "ONTWERPNOTITIE AUTONOMIE-TOEKOMSTLIJN".
- **Reconciliatie-blok `rlz_dubbel` (blok 6 bundel 08-09; advies, schrapbaar in twee regels):** per RLZ-administratie PurchaseInvoices laatste 400 dagen, paren binnen dezelfde crediteur op genormaliseerde referentie en/of cent-exact bedrag + datum, nooit als beide van de module (UUIDv5), bevinding `dubbel_in_rlz` mét beide boekstuknummers, geen automatische actie — zie BESLISSINGEN "RECONCILIATIE — PERIODIEKE TOETS 'MOGELIJK DUBBEL GEBOEKT IN RLZ'".
- **Reconciliatie `rlz_dubbel` — clusters + referentie-classificatie (blok 1 vervolgrun 10-09 avond; herziet "RECONCILIATIE — PERIODIEKE TOETS" + blok 7; geen migratie):** één bevinding per crediteur + genormaliseerde referentie (álle boekstuknummers, vingerafdruk `cluster=<rlz_admin>|<entity>|<ref>`), referenties die een IBAN, een klant-/contractnummer (≥ 3× met ≥ 2 bedragen) of een placeholder zijn worden mét teller uitgesloten (`app/reconciliatie/referentie_classificatie.py`), rangorde "Waarschijnlijk dubbel in RLZ" (twee concepten, zelfde dag, zelfde bedrag) vs "Zelfde referentie, controleer", overgang oud → cluster zonder migratie (open paar-bevindingen vervangen onder eigen vingerafdruk, paar-acceptaties overgedragen), lees-only meetlat `reconciliatie-alles --alleen rlz_dubbel --lees-only [--administratie …]` — zie BESLISSINGEN "RECONCILIATIE RLZ_DUBBEL — CLUSTERS EN REFERENTIE-CLASSIFICATIE".
- **Mini-voorraad speciale producten** (mi-schema, stand = Σ append-only mutaties, MENS-MANIPULATIE ONMOGELIJK;
  migratie 0116) — zie BESLISSINGEN "MINI-VOORRAAD SPECIALE PRODUCTEN" (+ "— FRONTEND").
- **Kantoor-signaal "geplande week zonder weekstaat"** (`app/uren/planning_signaal.py`, geen blokkade; migratie 0115)
  — zie BESLISSINGEN "PLANNING-SIGNAAL 'GEPLANDE WEEK ZONDER WEEKSTAAT'".
- **Inzicht › Projectverdeling** (`/projectverdeling`, `document/HerverdeelDialoog.tsx`) en **Catalogus-leesroute
  smal** (`require_catalogus_lezer`) — zie BESLISSINGEN "MINI-RUN 06-09 — OVERZICHT" blokken B en C.
- **Pro-rato-periode "heel jaar" (D4 07-09; migratie 0119):** `Periode(maand|jaar)`, jaar = afgesloten kalendermaanden, bevroren jaarstand mét dekkingslabel, hercontrole tegen de actuele jaarstand — zie BESLISSINGEN "FIXRUN 07-09 — BLOK D4".
- **Accordeur-app koude start + niet-geactiveerd account** (`accordeur/standCache.ts`, `voorlader.ts`,
  `koudeStart.ts`; E1-wortel `@capacitor/app`) — zie BESLISSINGEN "KOUDE START ACCORDEUR-APP" + "NATIVE APP — EERSTE
  LOGIN OP EEN NIET-GEACTIVEERD ACCOUNT".
- **Accordeur-app vervolgrun 07-09 (blok 12+13):** diagnoseregel "Laatste koude start" in Toegang-instellingen (lokaal, nooit naar de server), geen boot-refresh-POST in native zonder leesbaar refresh-token, eerlijke Play-melding bij ontbrekende passkey-beheerder (variant B, geen 0020-impact), build 45 klaargezet (iOS via Xcode Cloud bij push, Android-AAB versionCode 3); Cloud Run min-instances staat al op 1 — zie BESLISSINGEN "ACCORDEUR-APP — DIAGNOSEREGEL".
- **Accordeur-app diagnose 08-09 (blok 2 bundel 08-09):** iOS-melding bij mislukte passkey-registratie eerlijk (`passkeyFouten.ts::isIosPasskeyMislukt`), `BackendOnbereikbaarError.oorzaak` (timeout/netwerk/server) op het slot + laatste verbindingsfout lokaal in de diagnoseregel, uitnodigingslink-in-Safari-analyse in TESTFLIGHT §0c — zie BESLISSINGEN "DIAGNOSE-RUN 08-09 — BLOK 2".
- **Wachtrij accordeur-app set-based + uploads van de event-loop + lees-timeout 30 s + élke AI-extractie op de achtergrond (blok 1 spoedrun 08-09, 1c verbreed):** `wachtrij_voor_accordeur` constant aantal queries per administratie (`WACHTRIJ_MAX_STATEMENTS_PER_ADMINISTRATIE`, gedeelde aan-de-beurt-bron `_open_rondes_met_volgende_stap`); `async def`-uploadroutes draaien blokkerend werk via `run_in_threadpool`; élke upload die AI-extractie krijgt gaat via `extractie_wachtrij` (201 < 2 s, worker = Cloud Run-job `rlz-extractie-wachtrij`; seam `ai_extractie_in_request`); app toont bij een trage/mislukte verversing nooit een kale fout zolang er een stand staat — zie BESLISSINGEN "WACHTRIJ ACCORDEUR-APP 10 S — SET-BASED HERBOUW, UPLOADS VAN DE EVENT-LOOP, LEES-TIMEOUT 30 S".
- **Omzetboekingen** (kassarapporten, bijv. BLOW Margerapport): type in de werkvoorraad; boekt als
  SalesInvoice (omzet per categorie → omzet-GB, btw-code per categorie) + gekoppelde
  kostprijsmemoriaal (per productgroep aan voorraad), als één transactie. Periode uit rapport,
  duplicaatbewaking per periode, plausibiliteitscheck (marge vs historie). BLOW: cannabisomzet =
  "NL, Geen BTW (Vrijgesteld)" — bewust géén 0%-tarief (aangifte-rubriek).
  Omzetmodule GEBOUWD + GETEST (2026-08-07); boekt sinds 2026-08-09 als entity-loze Receipts (besluit Peter
  2026-08-08 — kasomzet = losse boeking, geen dummy-debiteur); omzet-autoboeken opt-in per administratie (GO Peter
  01-09, migratie 0096). Zie BESLISSINGEN "Omzetmodule — GEBOUWD + GETEST", "OMZET-AUTOBOEKEN"; RLZ-feiten in
  api-verkenning "Omzetmodule STAP 0" + "Receipts-verkenning".
- **Verkoopfactuur-boekpad (Vastly, §2d)** — GEBOUWD + GETEST (2026-08-09), Entity = de échte huurder, CreditNote 381
  achter `creditnota_381_ingeschakeld` (AAN sinds 2026-08-10); verkoop-autoboeken opt-in per is_vastgoed-administratie
  (migratie 0051). Zie BESLISSINGEN "Vastly-verkoopfactuur-boekpad" + "VERKOOP-AUTOBOEKEN OPT-IN".
- **Bank**: klantenlijst → rekening (alle `PaymentAccounts` incl. kas). Voorstel-volgorde:
  1) exacte match naam+factuurnr+**bedrag** → auto-afletteren; 2) gedeeltelijke match → bevestigen;
  3) vaste regels (geheugen; na 3× zelfde handmatige boeking regel voorstellen); 4) RLZ's eigen
  voorstel (bron tonen — **schrijf-PoC 2026-08-02: voedingsbron bestaat wél, auto-gevuld
  `MatchedPaymentItem` bij exacte bedrag-match — de eerdere STAP-0-conclusie "geen voedingsbron"
  is herzien**); 5) handmatig. Afletteren gaat NIET door de klant-accorderingsflow.
  Bankmodule GEBOUWD + GETEST (2026-08-02); afletteren-tegen-open-post sinds 2026-08-09 ÉCHT via de API
  (`app/bank/afletteren.py`, zie "Reeleezee API" hierboven); bank-autoboeken opt-in per administratie; bank-verdieping
  25-08 deel 4 (auto-verversing, "Koppel aan relatie" = aanbetalingsdocument, splitsen; migratie 0071) en blok E 01/02-09
  (knoppen weg, voorstel-kaart). Zie BESLISSINGEN "Bankmodule — GEBOUWD + GETEST", "Afletteren-tegen-open-post:
  GEKRAAKT", "RLZ-FEEDBACKRONDE 25-08 DEEL 4", "BANKSCHERM BLOK E"; RLZ-feiten in api-verkenning "Bankmodule
  schrijf-PoC" + "Bankmutatie op een RELATIE + mutatie SPLITSEN — STAP-0 (25-08)".
- **Bank-sync automatisch, geen knoppen (blok 1 bundel 08-09, besluit Peter 08-09; geen migratie):** `sync-alles` (07:00) draait de bank-sync voor álle actieve administraties via `bank/sync_run.py::sync_alle_via_runs` (bank_sync_run-rij mét `resultaat.bron = "sync_alles"`, Odoo/geen credential = zichtbaar overgeslagen, geen fout), klantenlijst toont de laatste sync-tijd, versheid = zichtbare chip, reconciliatie-teller `bank_sync` (LET-OP "geen bank-sync-run" platformbreed + kapotte login per administratie), bank-levenscyclus volgt het afgehandeld-patroon (`?toon_oud=true`, 30 dagen) — zie BESLISSINGEN "BANK-SYNC AUTOMATISCH, GEEN KNOPPEN".
- **Nameting-instrument matchmotor (blok 0 bundel 09-09):** LEES-ONLY CLI `bank-voorstellen-lezen --administratie … [--rekening-iban] [--filter]` op de gedeployde job-image (vervangt het proxy-script; regel Peter 08-09) — zie BESLISSINGEN "BUNDEL 09-09 — BLOK 0".
- **Matchmotor bank herzien (blok 2 bundel 08-09; migratie 0127):** open-post-voorstel op score teken + naam/IBAN + factuurnummer als HEEL token + bedrag cent-exact — GROEN (auto-afletteren-kandidaat) = alle vier, ORANJE (bevestigen) = geen teken-mismatch + twee van drie, label `bron` zegt exact wat matchte; IBAN↔RLZ-entity-geheugen `bank_relatie_iban` leert bij élke bevestigde aflettering (`app/bank/iban_geheugen.py`); gouden-set-casus `l_bank_cv_08-09` — zie BESLISSINGEN "MATCHMOTOR BANK — NAAM/IBAN + NUMMER + BEDRAG + TEKEN".
- **Kempen-doorbelasting** (besluit Peter 2026-08-13; canoniek `verkenning/16_DOORBELASTING_KEMPEN.md` + BESLISSINGEN
  registerrij "KEMPEN-DOORBELASTING" + archief "Domeinbeslissingen — Kempen-doorbelasting"): tweezijdige motor bron-verkoop + spiegel-inkoop, "Boeken + doorbelasten", whitelist +
  "+ Doelentiteit toevoegen", IC-vlag, storno-blokkade ná ingediende aangifte (`app/rlz/aangifte.py`) → TEGENBOEK-PAD,
  rechtsgeldige factuur-PDF, doorbelasting × projecten. Zie ook BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt A,
  "ONBOARDING-BATCH 15-08", "Doorbelasting-kliktest-nazorg", "TEGENBOEK-PAD", "GECOMBINEERDE RUN 26-08" blok A,
  "GECOMBINEERDE RUN 01-09" blok B, "RLZ-FEEDBACKRONDE 25-08 DEEL 2" punt 2.
- **Afdelingen binnen een administratie** (`afdelingen_ingeschakeld`, harde check "Afdeling", accorderingsroute per
  afdeling; migratie 0084) — zie BESLISSINGEN "BOUWRUN 28-08 AVOND" blok A, mockup `afdelingen.html`.
- **Klant-autorisatie (à la Zenvoices), optioneel per administratie**: accordeurs per klant,
  sequentiële lagen met voorwaarden (bedragdrempels). Boekknop wordt "Ter accordering"; na laatste
  akkoord automatisch boeken (harde checks draaien opnieuw). Klant-app = PWA + store-apps (iOS TestFlight LIVE
  23-08, interne Play-testrelease LIVE 30-08; bundle-id `nl.aknijenhuis.goedkeuren`). **HARD PRINCIPE: maillinks
  zijn deep-links naar de PWA (`/accordeur?document=<id>`) — goedkeuren-zonder-inloggen/one-click-token bestaat bewust
  NIET.** Configuratiewijziging HERBEREKENT lopende rondes (blok 2 bundel 09-09, besluit Peter 08-09 — herziet 01-09 "vervallen": gegeven akkoorden blijven als de accordeur in dezelfde/eerdere laag staat en de drempel niet strenger werd, ontbrekende lagen worden aangevraagd, vervallen alleen als geen enkel akkoord meer past; `app/accordering/herberekening.py`, audit `accordering_ronde_herberekend`, gouden-set-casus p — zie BESLISSINGEN "ACCORDERINGSRONDE HERBEREKENEN I.P.V. VERVALLEN"); ná het laatste akkoord BLIJFT het document op
  ter_accordering tot de boeking staat (`boek_fout`); compleet klant-akkoord kan NIET opnieuw ter accordering. Zie
  BESLISSINGEN "Klant-accorderingsflow — GEBOUWD + GETEST", "Accordeur-PWA + auth-cadans — GEBOUWD", "GECOMBINEERDE RUN
  26-08" blok B, "VERZAMELRUN 27-08", "WERKSTROOM- + UI-RUN 27/28-08", "BUGFIX-RUN 28-08", "OPRUIMRUN 28-08",
  "GECOMBINEERDE RUN 01-09" blok A, "NATIVE-APP FASE 1–5", "NATIVE KLIKTEST RONDE 1/2", "XCODE CLOUD",
  "ANDROID-BOUWRONDE 28-08", "PLAY-NAZORG 30-08", "STORE-LINK-NAZORG", "ACCORDEUR-NOTIFICATIES",
  "NIEUWE-FACTUREN-BUNDELMELDING", "APPLE REVIEW 2.1"; `verkenning/17_NATIVE_STORE_APP_ACCORDEUR.md`.
- **Intercompany slaat klant-accordering over (blok 4 bundel 08-09 avond, besluit Peter 08-09; geen migratie):** leverancier met IC-vlag (actieve rij in `intercompany_tegenpartij` van de ADMINISTRATIE VAN HET DOCUMENT — één leesbron `app/doorbelasting/intercompany.py`, ook voor bank) in een administratie mét klant-accordering → zelfde flow, géén ronde, direct de boekstap (handmatig én autoboek), tijdlijn + audit "intercompany — klant-accordering overgeslagen (leveranciersregel)", DTO-veld `accordering_overgeslagen_reden`, knop "Boeken", historie "overgeslagen — intercompany"; lege IC-tabel = gewone flow; een lopende ronde blijft leidend — zie BESLISSINGEN "INTERCOMPANY SLAAT KLANT-ACCORDERING OVER".
- **Intercompany-leveranciers instelbaar (nachtrun 08/09-09, besluit Peter op beslispunt 1; geen migratie):** Beheerder-blok "Intercompany — accordering overslaan" op Instellingen › Administraties › ‹BV› › Klant-accordering (crediteur-combobox, herkomst-chip `handmatig`/`doorbelasting`, verwijderen = `actief=False`, audit + historie), routes `…/intercompany-leveranciers`, CLI `intercompany-leverancier-markeren`; eenmalige rij Universal Nederland → Universal Steigerbouw ná deploy via Cloud Run-job — zie BESLISSINGEN "INTERCOMPANY-LEVERANCIERS INSTELBAAR + EENMALIGE RIJ UNIVERSAL".
- **Google Play-afwijzing 07-09 (blok PLAY):** wortel ≠ Apple — reviewers logden in en strandden op de passkey-registratie (kale emulator zonder Google-account: "No create options available"); reviewer-instructies voor beide stores in `native/PLAY_DRAAIBOEK.md` §10–11 + `TESTFLIGHT_DRAAIBOEK.md` §1 — zie BESLISSINGEN "GOOGLE PLAY AFWIJZING 07-09".
- **Apple 1.0 goedgekeurd 09-09 → versie 1.1 met app-auth (mini-run 09-09; geen migratie):** train-regel = ná élke goedkeuring de marketingversie ophogen vóór de volgende push (build 98 geweigerd ITMS-90186/90062); 1.1 op pbxproj ×2 / `versionName` (vc5) / `appVersie.ts` mét guard `test_app_marketingversie_consistent.py`; `STORE_LINK_IOS` gevuld in deploy.yml (id6803862748), Android-link leeg tot Google goedkeurt; niets ingediend — zie BESLISSINGEN "APPLE 1.0 GOEDGEKEURD 09-09 — 1.1 MET APP-AUTH VOLGT" + TESTFLIGHT_DRAAIBOEK §0f.
- **Docs-nazorg store-draaiboeken 08-09 (blok 8 bundel 08-09):** eerstvolgende iOS-build = 89 (Xcode Cloud telt per push), resubmit via "Update Review" op de versiepagina, interne testers = ASC-teamleden, Play-veld "Andere informatie" ≤ 500 tekens, dode kolom `duplicaat_autoafvoer_ingeschakeld` = vervallen (geen drop) — zie BESLISSINGEN "FIXRUN 08-09 — BLOK 8: DOCS-NAZORG".
- **Projecten** (module, zichtbaar per rol + per administratie-toggle): project verplicht = hard
  blokkerend, géén "geen project"-optie; overhead → intern OVH-project (uitgesloten van bewaking).
  Budget uit offerte-ontleding (status offerte ≠ opdracht; meerwerk = aparte budgetversie).
  Werksoort = omzet-GB ↔ kosten-GB-mapping (default per administratie, override per project/regel).
  Signalen: kosten > gefactureerd per werksoort; budgetoverschrijding; weekanalyse (inkoop zonder
  omzet); m²-voortgang uit factuurregels. Integrale marge = analytische laag (AK-opslag instelbaar,
  dekkingscontrole vs OVH-project) — nooit geboekt in RLZ.
- **Projectcode-generatie** volgens naamconventie van de klant (bijv. Universal: "26xxx Plaats
  (Opdrachtgever)"), synct bij aanmaken naar RLZ.
  Kantoor-projectenmodule (mockup projecten-invoer.html, migratie 0062) + cijfers-sync als ACHTERGRONDRUN (migratie
  0063) — zie BESLISSINGEN "PROJECTENMODULE KANTOOR" + "CIJFERS-SYNC-CRASH".
- **Inzicht › Projecten kantoorbreed + projectdetail-verrijking (C5 07-09):** `GET /projecten/kantoorbreed` (lijstpatroon, chips resultaat/verplichtingen/weekstaten/m² uit caches), route `/projecten` zonder param = kantoorbreed, chip "Projecten" op de klant-documentenlijst — zie BESLISSINGEN "INZICHT › PROJECTEN KANTOORBREED".
- **Contract-ontleding AUTO-FIRST (D6 07-09, besluit Peter 06-09; migratie 0118 — HERZIET de 22-08-regel "voorstel per regel, mens bevestigt"):** kopvelden soort werk / contract-m² / doorlopende huur als sentinel-strings (schema 0 unions), ontleding schrijft specs + staffels DIRECT met herkomst `contract` (chip "uit contract", correctie → `mens`, audit oud→nieuw), meerwerk-prijsvoorstel blijft mens-besluit — zie BESLISSINGEN "CONTRACT-ONTLEDING: KOPVELDEN + AUTO-FIRST".
- **Uren & meerwerk (steigerbouw-tak, opt-in per administratie — alleen Universal initieel):** WEEKSTAAT PER PROJECT,
  rollen ZZP'er/uitvoerder/detacheerder in de bestaande native app, hybride keuring op weekniveau, factuurmatch
  (fase 1–4), ZZP-dossier + handhaving + KvK, geofence-stempels BASIS (native achtergrondlocatie alleen op branch
  `feat/geofence-native` — NIET mergen/releasen), prijsafspraken, planning-agenda (grid v3), transport v2 dag-agenda,
  werkopdrachten, fijnmazig recht "veldwerkerbeheer", detacheerder-filters. **Seam-eis steigerbouw-run: nieuwe
  module-code roept nooit RlzClient aan; adapter-grepen per blok in BESLISSINGEN "ODOO-ADAPTER — GREPEN".** Zie
  BESLISSINGEN "Ontwerpronde uren & uitvoerder + meerwerk-kantoor", "UREN & MEERWERK — BOUW", "FACTUURMATCH
  ZZP-/BUREAUFACTUREN" (fase 1–4), "STEIGERBOUW-RUN 25-08" blokken A–D, "BOUWRUN 28-08 AVOND" blok C, "OPDRACHT 29-08"
  blok C, "PLANNING-AGENDA STEIGERBOUW", "PLANNING-UITBREIDING 31-08", "DETACHEERDER-FILTERS VELD-APP"; mockups
  `uren-uitvoerder.html`, `meerwerk-kantoor.html`, `planning-steigerbouw.html`, `planning-werkopdracht-transport.html`.
- **Veldwerker-dialogen zonder picker-poort (C3 07-09):** dossier/crediteur-koppelen openen voorgeselecteerd via `gebruikers/standaardAdministratie.ts` (één in scope → recentste planning/koppeling → uren-opt-in), picker = wissel-filter — zie BESLISSINGEN "FIXRUN 07-09 — BLOK C3". **KvK-lookup productie (E7 07-09):** `KVK_BASE_URL=https://api.kvk.nl/api/v1/basisprofielen` + secret `KVK_API_KEY` (Vastly-sleutel, zelfde BV) in deploy.yml; lokaal zonder beide = testomgeving — zie BESLISSINGEN "E7 — KVK-LOOKUP PRODUCTIE".
- **Voorraad-aansluiting fase 1** (`mi`-schema, controle-laag, NOOIT RLZ-writes; opt-in `voorraad_ingeschakeld`;
  RLZ-verkoopfacturen als uitstroom-leesroute; normalisatie v2; Odoo als LEESBRON vanaf de voorraad-knip; migraties
  0086–0088/0102) — zie BESLISSINGEN "BOUWRUN 28-08 AVOND" blok D, "OPDRACHT 29-08" blok A/B, "OPDRACHT 30-08",
  "ODOO-ADAPTER FASE 1".
- **Zoeken**: globaal over boekingen (incl. archief + RLZ-boekstuk + PDF), accorderingshistorie — GEBOUWD + GETEST
  (2026-08-09), `backend/app/zoeken/` + `frontend/src/zoeken/`, scope-veilig (RLS + server-side), bewust geen nieuwe
  AI-calls; tijdlijn per boeking. Zie mockup #zoeken.
- **Archief**: geboekte documenten 7 jaar terugvindbaar met PDF (bewaarplicht).
- **Kalenderdag = Nederlandse dag (blok 2 run 11-09 middag; middernacht-flake 10/11-09; geen migratie):** geldigheids-, verval-, factuur-, boek- en periodedatums én dagtellers zijn NL-kalenderdagen via het ene anker `app/tijd.py` (`vandaag_nl()`, `kalenderdag_nl()`, monkeypatch `_klok`); tijdstempels blijven `datetime.now(UTC)` zonder `.date()`; 66 call-sites gesweept, guard `tests/unit/test_kalenderdag_guard.py` (whitelist leeg), gouden set pint `_klok` op `REFERENTIE_TIJDSTIP` — zie BESLISSINGEN "KALENDERDAG = NEDERLANDSE DAG".
- **Beginscherm kantoor-web set-based + tellers-cache (blok 6 run 11-09 middag; kliktest Peter 11-09, 71 administraties; migratie 0136):** `GET /werkvoorraad/overzicht` leest de tellers-cache `werkvoorraad_teller_cache` in ÉÉN statement over de hele scope (`app/werkvoorraad/tellers.py::lees_voor_scope`, RLS-policy met actor-scope; N=5 = N=200 = 3 statements, meetlat `tests/werkvoorraad/test_tellers_querytelling.py`), cache incrementeel via `_schrijf_overgang`/aanmaak/vragen/spiegel-hooks, nachtelijk herrekend in `sync-alles` (CLI `werkvoorraad-tellers-herrekenen`, `--dry-run` in de nameting-allowlist), fail-safe bij ontbreken, reconciliatie-LET-OP `werkvoorraad_tellers`; `spiegel_taken` server-side in de rij (de 71 losse spiegel-taken-calls zijn weg), lijst rendert vóór het bank-overzicht mét skeleton — zie BESLISSINGEN "BEGINSCHERM KANTOOR-WEB — SET-BASED + TELLERS-CACHE (blok 6 run 11-09 middag)".
- **Groepskenmerk op administratie (blok 8 run 11-09 middag, opdracht Peter 11-09; migratie 0135):** `platform.groep` (naam, korte unieke code, actief — archiveren, nooit verwijderen; RLS: iedereen leest, muteren alleen Beheerder) + `administratie.groep_id` (hoogstens één groep); veld "Groep" op Instellingen › Administraties › ‹administratie› › Algemeen mét inline "Nieuwe groep…" (code-voorstel uit de naam, bewerkbaar) en optioneel in de wizard (leeg = geen groep, nooit een blokkade); chip + filter in de administratielijst, blok "Groepen" (hernoemen/archiveren); filter "Groep" op de klantenlijst (`?groep=` → `GET /werkvoorraad/overzicht?groep_id=`) en Inzicht › Reconciliatie (`?groep_id=`) — administratie is een FILTER, dit is er één meer (KP7); routes `GET/POST /groepen`, `PUT /groepen/{id}`, `PUT /administraties/{id}/groep`; audit `groep_aangemaakt`/`groep_gewijzigd`/`administratie_groep_gewijzigd` oud→nieuw; "Kempen groep" NIET in code — Peter maakt 'm via de UI; consolidatie/eliminatie = liquiditeit-mockup, niet hier — zie BESLISSINGEN "GROEPSKENMERK OP ADMINISTRATIE".
- **Incasso-/betaalbatches uit RLZ — STAP-0 lees-only (blok 10 run 11-09 middag; geen bouw, geen migratie):** de batch leeft op de bankregel (`PaymentTransaction.PaymentBatchId` + `$expand=Batch` → `PaymentTransactionBatch {BatchId, FileName, RemainingAmount}`) en de factuur draagt DEZELFDE sleutel vooraf (`PaymentTermList.PaymentBatchInformation`, bewezen 12/12 op Universal Steigerbouw); geen batch-collectie in de API (`Remittances` = kasafsluiting, `DirectDebits`/`CreditTransfers` = kandidatenlijsten), R-transacties alleen als `ReturnReason` (count 0) + actie 115; lees-only CLI `rlz-lezen` (weigert élke niet-GET en elk Actions-pad, `--top` ≤ 50, altijd geanonimiseerd, in de nameting-allowlist); voorstel matchmotor-stap "batch" (sleutel + som = groen, N × actie 15) wacht op akkoord — zie BESLISSINGEN "INCASSO-/BETAALBATCHES UIT RLZ — STAP-0 LEES-ONLY" + api-verkenning "Incasso-/betaalbatches — STAP-0 11-09".
- **Staande goedkeuring: voorstel alleen bij een PERIODIEK patroon (blok 7 run 11-09 middag; casus Lusso 12 chalets = 12× de vraag; migratie 0134):** één gedeelde motor `terugkerend/service.py::classificeer_reeks` (periodiek = ≥ 3 gelijke facturen, tussenpozen ≥ 21 d, maand-/kwartaalpatroon; batch = twee gelijke facturen < 21 d óf ≥ 2 binnen 30 d zonder patroon → nooit een voorstel), de vraag één keer per leverancier+patroon (eerste in de wachtrij), "niet nu" = 90 dagen stil, "nooit voor deze leverancier" (accordeur zelf in de app, Beheerder administratiebreed in kantoor-web; tabel `staande_goedkeuring_voorstel_stil`, RLS, opheffen = actief=False), antwoord reist mee in de akkoord-call, DTO-veld `staande_regel_patroon`, lees-only CLI `staande-goedkeuring-voorstellen-lezen` in `nameting.sh`; bestaande staande goedkeuringen ongewijzigd — zie BESLISSINGEN "STAANDE GOEDKEURING — PERIODIEK VS BATCH (blok 7 run 11-09 middag)"
- **Verplaatsen naar een andere administratie — RLS-uitzondering binnen de SECURITY DEFINER-functie (blok 1 run 11-09 middag; bug Peter 11-09 Kempen Facilities → Universal Verkoop; migratie 0132):** 0080 werkte op Cloud SQL nooit (FORCE RLS geldt ook voor een eigenaar zonder superuser/BYPASSRLS) — fix = helper `platform.verplaatsing_document_id()` + per tabel één PERMISSIVE policy `<tabel>_verplaatsing` die alleen bínnen de definer-context leeft (`current_user IS DISTINCT FROM session_user`), functie zet de GUC transactie-lokaal; `verplichting_match`/`regel_gb_classificatie` verhuizen nu ook mee. RLS-weigering = systeemfout "automatisch gemeld": `app/db/rls_weigering.py` (audit `rls_weigering` uit router én centrale handler), bewakingsprobe `rls_weigering`, beheer-LET-OP in de reconciliatie; testregel: `tests/security/rls_eigenaar.py::productie_eigenaar` maakt een SECURITY DEFINER-test pas bewijskrachtig (conventies §RLS punt 6) — zie BESLISSINGEN "VERPLAATSEN — RLS-UITZONDERING BINNEN DE SECURITY DEFINER-FUNCTIE".
- **Eerste sync ná groene probe: 403 = herproberen (blok 3 run 11-09 middag; bevinding Peter Baard / Box Beheer / Kempen B.V.; migratie 0133):** een 403 op een route die de opgeslagen rechten-probe groen had is geen fout maar "RLZ zet rechten door" — run-status `rechten_onderweg` mét `pogingen`/`volgende_poging_op`, automatisch herproberen 5/15/60 min, daarna elk uur, max 24 u (wekker = stap `eerste_sync_wekker` in de kwartier-job `rlz-bewaking`, voertuig = bestaande job `rlz-eerste-sync`, fallback in-process), alleen niet-klare onderdelen opnieuw, audit per herpoging; 401/5xx/403-op-niet-groene-route = direct fout; ná 24 u `fout` mét letterlijk RLZ-antwoord; chip "⏳ RLZ zet rechten door — opnieuw over N min" (tooltip RLZ-antwoord), "Sync opnieuw starten" = dezelfde run direct; reconciliatie-teller `eerste_sync_herproberen` + LET-OP `rechten_na_24u` mét deeplink naar de administratie — zie BESLISSINGEN "EERSTE SYNC NÁ GROENE PROBE — 403 = HERPROBEREN".

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

## Koppelvlak vastgoedmodule (`../Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md` is leidend, v1.20)

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
- **Kostenflow-omkering + boekstand-events (v1.14, GEBOUWD + GETEST)**, **Route A projectaanmaak-naar-RLZ (§5, v1.16,
  LIVE GEVERIFIEERD; systeemanker VERVALLEN)**, **Registersync §8 (v1.18/v1.19, migratie 0081)**, **§2d-uitbreidingen
  v1.10 (AccountingCost, consument-afnemer, waarborg-memoriaal GEBOUWD)**, **v1.11-addenda (creditnota 381 AAN sinds
  2026-08-10, `factuur_afgeletterd` schema 2.0, échte huurder als debiteur)**, **Vastly-verkoopfacturen (§2d, v1.9 —
  routering op de UBL-markering `VASTLY-VERKOOP`, nooit op afzender)** en **WOZ-zij-extractie (§2e, fase 2)** — zie het
  koppelcontract (§3, §3a/§3b, §5, §8, §2d/§2e) + BESLISSINGEN "REGISTERSYNC-KOPPELVLAK 28-08", "Systeemanker route A",
  "Vastly-verkoopfactuur-boekpad"; volledige CLAUDE.md-tekst in het archief "Koppelvlak vastgoedmodule — …".

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
- `mockup/controlescherm-v2.html` + `mockup/doorbelasten-blok-v2.html` + `mockup/bank-voorstel-kaart.html`
  (iteratie 2) — bouwnorm 02-09 (akkoorden Peter 02-09, ontwerpnotities incl.; GEBOUWD 02-09) — zie BESLISSINGEN
  "UX-/INTAKE-VERBETER-RUN 02-09" + "UX-PATRONEN ALS NORM", aanvullingen "MINI-RUN 03-09 (2)" rij D en "UI-FIXES 04-09
  BLOK C". Bindend blijft: Nieuwe schermen volgen de vastgelegde UX-patronen (voorstel-kaart, restant-balk, lege stand =
  actie, één primaire knop + ⋯, werkvolgorde-regel, bundelen vóór tonen); Een tekstknop = `linkbtn`, een echte knop =
  `btn`/`btn secondary`; nooit een kale `<button>`.
- `mockup/offerte-matching.html` — definitief goedgekeurde mockup offerte-accordering + factuur↔offerte-match (Peter 04-09,
  ontwerpnotities ①–⑧ = onderdeel van het akkoord; GEBOUWD 04-09) — de bouwnorm voor het documenttype "verplichting"
- `mockup/tegenboek-mockup.html` — definitief goedgekeurde mockup tegenboek-pad (Peter
  2026-08-22, suppletie-signaal geschrapt; GEBOUWD 2026-08-22) — de bouwnorm
- `mockup/projecten-invoer.html` — definitief goedgekeurde mockup kantoor-projectenmodule
  (Peter 2026-08-22, incl. resultaat per project + cumulatief; GEBOUWD 2026-08-22) — de
  bouwnorm
- `verkenning/api-verkenning.md` — alle geverifieerde API-feiten + PoC-resultaten
- `verkenning/odoo-verkenning.md` — Odoo STAP-0 (02-09-2026, universal-steigers.odoo.com, Odoo 19 JSON-2) + live
  bewijs-cycli; adapter-bouwstatus: BESLISSINGEN "ODOO-ADAPTER FASE 1", "ODOO-ADAPTER BLOK E + LIVE KETEN-CYCLUS 04-09",
  "ODOO-AFRONDINGSRUN 04-09", "ODOO-SLOTSTUK 04-09". De echte Universal-Steigerbouw-overstap volgt uitsluitend op een
  expliciete GO van Peter.
- `../Platform/` — **gedeelde platform-map (v1.6): koppelcontract-master (`contracten/`),
  besluitenregister (`besluiten/INDEX.md` — lees bij elke sessiestart!), registers (prefixen,
  schema-versies, entiteiten, conventies)**
- `docs/BESLISSINGEN.md` — **statusregister per feature/onderwerp (status + canonieke vindplaats)**
- `docs/DIAGNOSE_INTAKE_VERZAMELBAK_02-09.md` — diagnose kliktest 02-09 (intake-splitsingsbug); fixes + nazorg:
  BESLISSINGEN "INTAKE-SPLITSINGSBUG GEFIXT 02-09", "UX-/INTAKE-VERBETER-RUN 02-09" rij B4, "VERVOLGRONDE 02-09",
  "NABUNDEL-NAZORG 03-09", "MINI-RUN 03-09 (2)".
- `docs/avg/` — AVG-pakket (jurist-akkoord 12-08); stap 1 van `05-activatie-checklist.md` beslisklaar + besluiten Peter
  02-09 (ZDR via Sales, ALLE administraties AAN): BESLISSINGEN "AVG STAP 1 — VOORBEREID" + "VERVOLGRONDE 02-09" blok E.
- `docs/BOUWPLAN.md` — fasering en definition of done per fase
- `verkenning/.env` — RLZ-credentials (BLOW + Universal Steigerbouw), NOOIT committen

## Werkwijze

- **Gouden set = verplichte poort (besluit Peter 08-09, herstelrun "Basis eerst" blok 0):** `backend/tests/keten/` is één
  ketentest op échte, geanonimiseerde productiedocumenten (Universal Nederland RLZ-2080143037, Floor 26219, Spot Services
  2026-608, Universal-Nederland-splitsing RLZ-2080143038/39, BOOT-creditnota 202633199, BDO 6088744, DCTE 202611050, Kader
  F212604921) door intake → bundeling/nabundel → extractie (deterministische stub speelt de bewaarde AI-uitkomst af, nooit
  een echte AI-call) → prefill → checks → lijst-DTO → afvoer/status, plus het frontend-harnas `harness-keten.html` +
  `frontend/scripts/keten_sweep.sh` (echte controlescherm en documentenlijst op exact de door de backend geëxporteerde
  DTO's, pixelvergelijking tegen `frontend/scripts/keten_baseline/`). **Definitie van "af" voor élk blok dat intake/
  controlescherm/lijst/accordeur-app raakt: (1) gouden set groen (doelgedrag dat nog niet staat is `xfail(strict, reason=
  "blok N — …")`, de eigenaar haalt zijn xfail weg — nooit de assert), (2) productiegedrag ná deploy nagemeten met een
  vooraf genoemd meetrecept, (3) het rapport zegt letterlijk "werkt in productie: ja/nee".** Guard:
  `tests/unit/test_keten_guard.py` — een werkboom-wijziging onder app/intake, app/extractie, app/documenten of
  frontend/src/document zonder aanraking van tests/keten is rood. Nieuwe echte casus toevoegen = fixture-map onder
  `tests/keten/fixtures/` (UBL geanonimiseerd, PDF nooit als echte bytes — kerntekst in `pdf_tekst.json`, AI-uitkomst als
  `ai_antwoord.json`, herkomst in `bron.json`); nooit BSN's — zie BESLISSINGEN "GOUDEN SET — KETENTEST OP ECHTE DOCUMENTEN
  (blok 0 herstelrun 08-09)".
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
- **Productie alleen via de bestaande Cloud Run-service of read-only scripts via Cloud Shell (regel Peter 08-09,
  nachtrun 08/09-09 — bindend):** nooit een lokale backend of ad-hoc proces (ook geen lokale CLI over de Auth Proxy)
  tegen de productiedatabase starten. Schrijvende nazorg/backfills lopen als `gcloud run jobs execute <bestaande job>
  --args="-m,app.cli,<commando>,…"` op de gedeployde job-image (dus ná de deploy van de commit die het commando
  draagt), lezen via de routes van de service of read-only in Cloud Shell. Een run die productie moet raken vóór de
  deploy is er niet: voorbereiden, meetrecept noteren, uitvoeren ná deploy. **Nametingen lopen onder het nameting-SA
  (`nameting@rlz-boekhouding`, `scripts/gcp/nameting.sh` — lees-only allowlist; sinds 10-09).** Ook een "deploy is live"-check
  toetst service ÉN jobs (`gcloud run jobs describe … image`): service en F3-jobs kunnen uit de pas lopen (les 10-09).
- **Productie-nametingen structureel — UITGEVOERD 10-09 (route A, besluit Peter):** SA `nameting@` + custom rol `nametingUitvoerder` job-scoped op `rlz-reconciliatie` + `run.viewer`/`logging.viewer`, géén cloudsql/secrets; **key geblokkeerd door org-policy `iam.managed.disableServiceAccountKeyCreation` → voorlopig impersonatie (herlogin blijft), beslispunt Peter**; rotatie-LET-OP via `settings.nameting_sa_aangemaakt_op`; `scripts/gcp/nameting_env.sh` + `nameting.sh` — zie BESLISSINGEN "NAMETINGEN-RUN 10-09 — SERVICEACCOUNT, DEPLOY-REGRESSIE, METINGEN" + GCP_UITROL §F7.3. Voorbereiding/routes: "PRODUCTIE-NAMETINGEN STRUCTUREEL — SERVICEACCOUNT OF LANGERE WORKSPACE-SESSIE".
- **Ochtendrun 11-09 — eerste échte productiemeting van bundel 09-09/10-09 + vervolgrun op deploy #180 (`58feacb`):** rlz_dubbel 954 paren → 42 clusters (6-Steps waarschijnlijk dubbel; BP Express/Food service uitgesloten), drempel 5 → 3, leren-rapport 68 administraties (5 kwalificerend), matchmotor-labels live, historie-regel/AI-poort niet meetbaar (cache leeg → `bank-historie-backfill --dry-run` gebouwd), tellers zichtbaar, RLZ-check-knop ontbrak in de UI — zie BESLISSINGEN "OCHTENDRUN 11-09 — NAMETINGEN + DEPLOY-DRIFT".
- **RLZ-check als knop (nachtrun 10/11-09 blok 1; geen migratie):** knop "RLZ-check" op Instellingen › Administraties › ‹administratie› › Algemeen (Webservice-gegevens) → `POST /administraties/{id}/rlz-check`, resultaat inline per leesroute (stand, letterlijk RLZ-antwoord ≤ 300 tekens, RLZ-recht) + "Administraties die deze login ziet: N" mét eigen-id-markering, "Sync opnieuw starten" bij groene check ná rode eerste sync, sync-fout-chip mét tooltip — zie BESLISSINGEN "RLZ-CHECK ALS KNOP".
- **Scope-dialoog: lijst in plaats van chips (nachtrun 10/11-09 blok 2; kliktest Peter 71 administraties; geen backend):** één doorzoekbare lijst mét vinkjes (`gebruikers/ScopeLijst.tsx`, ook de accordeur-variant), teller/filter/Alles-Geen (Geen mét bevestiging), gearchiveerd onderaan, alfabetisch blijft, Opslaan toont "+3 −1" — zie BESLISSINGEN "SCOPE-DIALOOG: LIJST IN PLAATS VAN CHIPS".
- **Bank — deels afgeletterde mutaties: open bedrag is de maat (nachtrun 10/11-09 blok 3; bug Peter Zilver Beheer; migratie 0131):** `open_bedrag` stuurt voorstellen, boeken (dekking ≠ open = 409 "Bedrag dekt niet het open bedrag van de mutatie …"), regels, historie en splitsen; verversronde haalt OpenAmount + `PaymentReferenceList` op (`bank_mutatie.rlz_koppelingen`); lijst toont "€ 5.023,09 · open € 2.511,05" + chip "deels afgeletterd in RLZ"; gouden-set-casus `l_bank_cv_08-09` uitgebreid; verrekening bank↔bank = STAP-0 lees-only (bestaat niet in de RLZ-API; keuze RLZ-vorm bij Peter) — zie BESLISSINGEN "BANK — DEELS AFGELETTERDE MUTATIES" + api-verkenning "Verrekening tussen twee bankmutaties — STAP-0".
- **Deploy-les 10-09 (regressie 09-09 → 10-09, 13 deploys):** een `^<t>^`-scheidingsteken in `--set/--update-env-vars` mag nooit in een waarde voorkomen (`^@^` + e-mailadres brak de workflow ná de service-stap → F3-jobs 1,5 dag op oud beeld, `INTAKE_POSTVAK_ADRES` weg van de service); guard `tests/unit/test_deploy_yml_envvar_delimiters.py` — zie BESLISSINGEN "NAMETINGEN-RUN 10-09 — SERVICEACCOUNT, DEPLOY-REGRESSIE, METINGEN". **Aanvulling 11-09: zeven rode deploys #173–#179 bleven onopgemerkt → bewakingsprobe `deploy_drift` (service-beeld ≠ job-beeld > 30 min = alert + audit + LET-OP "systeemfout — automatisch gemeld"), smoketest toetst zelfde beeld + publiek 200, `--allow-unauthenticated` weg, `if: failure()` → mail via job `rlz-bewaking deploy-mislukt`, guard `test_deploy_yml_image_uniform.py` (één `IMAGE`-variabele); IAM `roles/run.viewer` op run-jobs@ = één owner-commando (`scripts/gcp/bewaking_deploy_drift_iam.sh`).**
- **Bash-commando's: absolute paden, geen cd-kettingen met relatieve reads (afspraak Peter
  03-09, herhaalde permission-prompts).** Er staat een Read-deny op secret-bestanden; een
  samengesteld commando met `cd` + relatieve bestandsreads kan niet automatisch getoetst
  worden en triggert dan élke keer een handmatige toestemmingsvraag aan Peter. Gebruik daarom
  absolute paden (of `git -C` / `--directory`-vormen) zodat de toetsing automatisch kan.
  Secrets-paden (`.env`, `~/Sleutels`) blijven sowieso verboden terrein.
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
