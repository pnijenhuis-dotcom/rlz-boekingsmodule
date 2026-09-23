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
- Administraties/koppelingen/sync-instellingen: volledige tekst in `docs/regels/administraties-instellingen.md` (LEESPLICHT).
- DB-schema's: `platform` (gebruikers, rollen, administraties, credential-store, audit log),
  `boekhouding` (deze module). Vastgoedmodule krijgt `vastgoed`, MI-dashboard later `mi`.
- Auth, autorisatie, RLS en app-auth: volledige tekst in `docs/regels/auth-toegang.md` (LEESPLICHT) — kern: passkeys eerste lijn (0020), app-rollen toestelbinding + toegangscode (0029), geen scope = geen data, niemand muteert zijn eigen rol/scope, élk kantoor-endpoint een rolpoort.
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
- **ManualJournals** (memoriaal): PUT + `JournalEntryDiary:{id}` verplicht, regels met `DebitAmount`/`CreditAmount`
  (de bedragvelden zijn leidend; onze PUT's sturen `CreditOrDebit` 1 mét `DebitAmount` en 2 mét `CreditAmount` — RLZ
  boekt dat goed); saldo moet 0 zijn. **Op LEZEN is `CreditOrDebit` 1 = CREDIT, 2 = DEBET (34/34 regels, 6 memorialen,
  STAP-0 14-09) — de oude regel "1=debet, 2=credit" was FOUT; de code nooit als richting lezen, altijd
  `DebitAmount`/`CreditAmount`; `NetAmount` is getekend naar de normale zijde van de rekening** — zie api-verkenning
  "Memoriaalregels — teken per regel, STAP-0 14-09".
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


> **Regels per domein met LEESPLICHT (Peter 17-09, BESLISSINGEN "CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT (Peter 17-09)"):**
> de volledige, woordelijke tekst van élk domein staat in `docs/regels/<domein>.md` (chronologisch, mét datum/migratie/
> BESLISSINGEN-sectie per alinea; index + code-paden in `docs/regels/INDEX.md`). Hieronder per domein alleen wat het is, de
> bindende hoofdregels en de leesplicht. Een nieuw besluit → volledige tekst in `docs/regels/<domein>.md` + BESLISSINGEN-rij +
> hooguit één regel hier. Guards: `tests/unit/test_regels_index.py`, `tests/unit/test_rapporten_gelezen_regels.py`.

- **Werkvoorraad, documentenlijst en controlescherm** — Klantenlijst met tellers → documentenlijst → controlescherm; boekingsgeheugen, vragen, afwijzen, doorloop na boeken, kalenderdag, zoeken/archief.
  1. Administratie is een FILTER, nooit een poort; de standaardlijst is kantoorwerk (`geboekt`/afgehandeld onder één toggle, "Wachten op anderen" apart).
  2. Boekingsgeheugen: seed-only = oranje, eerste app-bevestiging = groen, recency wint (drie identieke mens-boekingen); automatische boekingen schrijven geen observatie.
  3. Controlescherm auto-first: kop-omschrijving, projectnummer en prefill deterministisch en direct persistent; mens wint altijd als tijdlijn-override.
  4. Vraag = dialoog die boeken blokkeert tot "Afgehandeld"; afwijzen = verplichte reden; niets verdwijnt stil; datums/dagtellers = NL-kalenderdag via `app/tijd.py`.
  5. Zoekveld klantenlijst + sticky dagkop planning (Peter 18-09): client-side zoeken op naam/groep mét `?zoek=`, `/` focust; planning-grids scrollen intern mét plakkende dagkop — zie BESLISSINGEN "ZOEKVELD KLANTENLIJST + STICKY DAGKOP PLANNING (Peter 18-09)".
  6. Samenvoegen-modus volgt de data, regel-btw uit de factuurkolom ("0%" = basis), pinbon-totaal alleen na sluitende som, byte-identieke directe upload = 409 "al aanwezig" (Peter 18-09) — zie BESLISSINGEN "SAMENVOEGEN-BUG, REGEL-BTW UIT DE FACTUURKOLOM EN UPLOAD 409 "AL AANWEZIG" (Peter 18-09)".
  7. Boeken sneller (Peter 18-09, migratie 0165): checks lokaal direct + extern gecachet op vingerafdruk (15 min), "Boeken in RLZ" = 202 `wordt_geboekt` + direct door naar het server-gekozen volgende document, RLZ-write in de achtergrond-schrijver (`rlz-boek-wachtrij`, claim per boeking, mislukt = rode rij) — zie BESLISSINGEN "BOEKEN SNELLER — CHECKS-CACHE + ACHTERGROND-SCHRIJVER (Peter 18-09)". **Cache-invalidatie op de bron (BUG Peter 21-09):** élke mutatie van de vertrouwde IBAN-set (vier-ogen-akkoord, bevestiging, seed/baseline, crediteur-samenvoegen) maakt de cache in dezelfde transactie ongeldig én zit als set-hash in de vingerafdruk; check-rij en paneel spreken elkaar nooit tegen (409 "al vertrouwd" → checks vers), `linkbtn` "Opnieuw controleren"; nazorg-CLI `checks-cache-legen` (uitgevoerd 22-09, 129 → 0; werkt in productie: ja voor het bevestig-pad, Meyer/akkoord-pad niet gemeten; `server_timing`-logregel kwam nooit aan → `app/logboek.py`; gemeten 23-09: logregel komt aan (126 regels, `checks.extern` p50 661 ms), audit-veld op élke set-mutatie, al-vertrouwd-route gaf 400 waar het scherm 409 verwachtte → `IbanAlVertrouwd` = 409 + scherm herkent beide, dispatch-onderdeel `checks-cache`) — zie BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09".
  8. Corrigeren vanuit de module (Peter 21-09): ⋯-menu "Corrigeren…" op een geboekt inkoop-/verkoop-/kassarapport-document = actie 19 + terug naar klaar_om_te_boeken mét gele balk, verplichte reden, één rijvergrendeling; aangifte → tegenboek-pad, afgeletterd → bank, doorbelasting beide kanten of geen, Odoo → tegenboeken; nameting 22-09 = klikpunt Peter (testadministratie gearchiveerd zonder credential) + nameting-onderdeel `corrigeren` — zie BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)".
  **LEESPLICHT: lees `docs/regels/werkvoorraad-controlescherm.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Kantoor-frontend: IA, designpass, componenten, changelog** — Tailwind v4 + tokens, designpass v2 (teal = actie, groen = status), instellingenRegistry fail-closed, Gebruikers & toegang-tabel, overflow-sweep, "Wat is nieuw".
  1. Élk nav-item/élke tab heeft een registry-entry; nieuwe module = nav-regel en/of tab, nooit een tegel; geen horizontale pagina-overflow (sweep).
  2. Contrast is een test (beide modi); tekstknop = `linkbtn`, echte knop = `btn`/`btn secondary`; nooit een kale `<button>`; comboboxen i.p.v. kale selects.
  3. "Wat is nieuw" (`WAT_IS_NIEUW.md`) VERPLICHT bijvullen bij élke feature-commit, klantleesbaar, nieuwste bovenaan.
  4. Overflow-les 18-09: tabellen in een paneel altijd in `.tabel-scroll`, omhullende grid-kolom `minWidth: 0`, actieknoppen links onder het blok; instellingen-harnas meet extra breedtes (1385/1280) — zie BESLISSINGEN "KLANT-ACCORDERING — ZOEKVELD, ACCORDEUR UITNODIGEN, LEVERANCIERSROUTE BOVENOP (Peter 18-09)".
  **LEESPLICHT: lees `docs/regels/kantoor-frontend.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Administraties, RLZ-/Odoo-koppelingen, sync en instellingen** — Instellingen › Administraties (archiveren, nooit verwijderen), wizard mét rechten-probe, eerste sync, RLZ-check, groepen, administratienaam volgt de bron, Odoo-koppelwizard, terugkerend-signaal, verplaatsen.
  1. Rechten-probe = de eerste-sync-routes (één bron `app/rlz/leesroutes.py`), altijd óók met de OPGESLAGEN login; 403 ná groene probe = herproberen (max 24 u), nooit stil.
  2. Dubbele Odoo-koppeling is een failsafe in drie lagen; VGG company 6 = migratiedoel, nooit een nieuwe administratie; URL-normalisatie via `app/odoo/ids.py`.
  3. Groep = filter (hoogstens één per administratie); naam met `naam_bron` ≠ mens volgt de bron; verplaatsen loopt via de SECURITY DEFINER-functie mét expliciete RLS-policy.
  4. Groepssaldi (BUG 21-09): RLZ-enum-velden (`AccountType`) nooit als int in `$filter` maar client-side (guard `test_rlz_filter_enum_guard.py`), Odoo-domeinen alleen velden die `odoo/sync.py` bewijst (geen `deprecated`), `fout` in de nachtelijke stand = regressie-LET-OP `groep_saldo_fout` (systeemmail), CLI `groep-saldi --stand`, nameting-onderdeel `groep-saldi`; gemeten 22-09: detector werkt, tweede enum-veld `Status` (open posten) gefixt, `ENUM_VELDEN` = AccountType + Status — zie BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)".
  **LEESPLICHT: lees `docs/regels/administraties-instellingen.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Auth, rollen, scope, RLS, app-auth en gebruikersbeheer** — Kantoor: e-mailuitnodiging + wachtwoord + TOTP, passkeys eerste lijn (0020); app-rollen: toestelbinding + toegangscode zonder passkey (0029); RLS + `vereis_kantoorrol`-poorten; Gebruikers & toegang; herstel-links; mails en push.
  1. Niemand muteert zijn eigen rol/scope; élke rol-/scope-wijziging in het audit_event; geen scope = geen data (RLS + server-side); élk kantoor-endpoint draagt een rolpoort (fail-closed sweep).
  2. Scope-lookups op `gebruiker_administratie` altijd in `scoped_session(<administratie>, actor_id=actor)`; SECURITY DEFINER omzeilt FORCE RLS niet — expliciete policy-uitzondering + niet-eigenaar-test.
  3. Maillinks zijn deep-links naar de app-flow; goedkeuren-zonder-inloggen bestaat niet; een activatie-/herstel-link laat in een browser EERST kiezen (app op deze telefoon / web) vóór er iets verzilverd wordt; versie-eis (≥ 1.1) letterlijk in de mail.
  4. Wachtwoord kwijt = Beheerder-knop "Herstel-link sturen" (nooit selfservice); legacy-app-routes 410 ná 2026-10-08.
  5. Rol wijzigen (Peter 18-09): binnen een auth-model-groep (kantoor / veld / accordeur) zonder heruitnodiging, tussen groepen 409 — zie BESLISSINGEN "ROL WIJZIGEN VELDWERKERS — ZZP'ER ↔ UITVOERDER ↔ DETACHEERDER (Peter 18-09)".
  6. Web-toestel (SPOED 18-09): server wees nooit af; ontgrendel-venster over herladen (5 min, sessionStorage), Android-terugknop = één scherm terug, opslag gewist = eerlijke melding, beginscherm-kaart — zie BESLISSINGEN "WEB-TOESTEL — 'LOGT STEEDS UIT' (SPOED 18-09)".
  7. Scope van een klant-accordeur = toegang, nooit een laag (BUG Peter 18-09): "Administraties toevoegen…" schrijft alleen `POST /auth/gebruikers/{id}/scope`; verwijderen = uit de lagen en/of toegang intrekken als twee losse vinkjes — zie BESLISSINGEN "TOEGANG IS GEEN LAAG — KLANT-ACCORDEUR TOEGANG GEVEN VERANDERT DE GOEDKEURINGSROUTE NIET (Peter 18-09)".
  **LEESPLICHT: lees `docs/regels/auth-toegang.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Btw: codes, defaults, verlegd, buitenland** — Btw-code uit de scan en het factuurtotaal, defaults uit de RLZ-grootboekrekening en de eigen historie, verlegd-herkenning (vermelding, kolomcode, onderaannemer), buitenland-signaal, verlegd-tarief deterministisch.
  1. Winnaarsvolgorde btw (`regel_prefill.py`): mens > factuur berekend > geheugen > factuur verlegd > grootboek-default (RLZ) > grootboek-historie > administratie-default > leeg; 0/onbepaalbaar/meerduidig = NOOIT invullen.
  2. Verlegd = (vermelding óf kolomcode óf verlegd-leverancier) ÉN factuur-btw 0; 0 % zonder basis blijft leeg (vrijgesteld ≠ verlegd); verlegd-tarief: voorkeur per administratie → meest gebruikt in historie → bestaand pad → default, mét herkomst-chip.
  3. Cent-fix aan de bron (`regelsom.py::corrigeer_btw_centen`) alleen in wat naar RLZ gaat; foutvertaling `vertaal_rlz_boekfout` voor buitenlandse crediteuren.
  4. Btw-bedrag volgt het tarief (Peter 18-09): 0 % op een regel mét factuur-btw = btw in de kosten (netto + btw, btw 0), harde check "Btw-bedrag past bij tarief" (marge 1 ct × samengevoegde regels, max 5) mét acties, BUA-kenmerk `btw_aftrek_uitgesloten` (migratie 0163) wint van factuur-berekend, keuzelijst NL-eerst mét "Buitenland-tarieven tonen (N)" — zie BESLISSINGEN "BTW-BEDRAG VOLGT HET TARIEF + BUA + KEUZELIJST NL-EERST (Peter 18-09)".
  5. BUA-kenmerk kantoorbreed (Peter 21-09): lees-only CLI `bua-kandidaten` (naam-match 4xxx, kenmerk-stand, module-geboekt per jaar, advies zetten/beoordelen/niet_zetten) + schrijvende `bua-kenmerk-zetten --alles --dry-run` (default 4508 + 4510, ná Peters "ja", job-image); kantine/sponsoring bewust niet; meting gemeten 22-09 via dispatch-onderdeel = replica-meting exact (297/75, 0 aan, zetten 149), zetting wacht op Peter — zie BESLISSINGEN "BUA-KENMERK — LEES-ONLY METING + BULK-VOORSTEL (Peter 21-09)".
  6. Btw-plichtig per administratie (BUG Peter 22-09, casus VGG / Studio Lacy Lion 2026-042 → RLZ-04-00000925: module splitste, RLZ boekte alleen netto, € 322,38 te weinig betaald; migratie 0170): kenmerk `administratie.btw_plichtig` (default true; RLZ `AdministrationSettings.EnableTaxReporting` true = bevestigd bron 'rlz', false = alleen DETECTOR-signaal → LET-OP "bevestig btw-status", nooit zelf op false); false = prefill élke regel bruto mét "geen btw"-code (vrijgesteld > NL 0 % > geen TaxRate), keuzelijst verborgen mét chip, harde check "Btw in niet-btw-plichtige administratie" mét actie "Btw in de kosten zetten (alle regels)" — inkoop, verkoop, kassarapport én doorbelasting-spiegel in zo'n doel; lees-only CLI `btw-in-niet-plichtige-administratie --rlz` (kolom TE WEINIG = Peters nabetaallijst), `btw-plichtig-kandidaten`, schrijvend `btw-plichtig-zetten`; gemeten 23-09: data-stap VGG gezet (false/mens), sync-signaal 74+1, nazorg TE WEINIG € 1.401,43 over 3 documenten (herstel = klikpunt) — zie BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)".
  **LEESPLICHT: lees `docs/regels/btw.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Duplicaten en crediteuren** — Harde check "Duplicaat (module)", auto-afvoer, status `afgevoerd_duplicaat`, RLZ-/Odoo-bestaanscheck, referentie-normalisatie, nabundel-motor, crediteur-dedup en dubbelen-clusters, bulk-afvoer, medewerker-wensen 04-09.
  1. Duplicaten eruit, geen lijst: cent-exact/genormaliseerde referentie over álle crediteurrecords; UBL+PDF = bundel, nooit duplicaat; byte-identieke exemplaren uit één bericht = `samengevoegd`; nooit verwijderen, altijd terugdraaibaar met reden.
  2. Al geboekt in RLZ/Odoo (zelfde referentie) = blokkerend mét boekstuk; zelfde bedrag+datum = oranje; geen credential = zichtbaar overgeslagen.
  3. Eenduidige crediteur-clusters (btw/KvK; N = 3) handelt het systeem af; verliezers zijn in de module onbruikbaar via `crediteuren/voorkeur.py`; alles telt in geen werkvoorraad-teller maar blijft terugvindbaar (Archief/Zoeken).
  **LEESPLICHT: lees `docs/regels/duplicaten-crediteuren.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **E-mail-intake, verzamelbak, splitsing en AI-extractie** — Eén intake-adres, splitsen op factuurgrenzen, toewijzen op tenaamstelling, verzamelbak "Niet toegewezen", één extractiepad achter de AVG-/API-key-/kostengrens-gates, deterministische templates, UBL deterministisch, wachtrij-trigger, union-limiet.
  1. Nooit auto-toewijzen bij twijfel; tenaamstelling leidend, afzender = hint; "hoort niet bij ons" met reden; verzamelbak leert van handmatige toewijzingen.
  2. AI alleen voor extractie/segmentatie, altijd met deterministische checks eroverheen; kostengrens € 100/maand is een harde poort, boven de grens nooit stil; schema's ≤ 16 unions, nieuwe velden sentinel-gebaseerd.
  3. UBL is deterministisch (kop, crediteur, regels, datums uit de XML); template-terugval per bekende leverancier: één rood = volledig verworpen; élke extractie loopt via de wachtrij (201 < 2 s).
  4. Bulk-upload (Peter 18-09): élke upload-plek neemt honderden bestanden/een map als één batch (wachtrij max 4, uitkomst per bestand, "al aanwezig" = duplicaat-vlag, geen fout); server ongewijzigd — zie BESLISSINGEN "BULK-UPLOAD — MEERDERE BESTANDEN TEGELIJK (Peter 18-09)".
  5. Wachtrij-trigger gebundeld (30 s per job, audit `gebundeld`, job herhaalt de pas ≤ 5), startup-vangnet laat verse bezig-runs staan, élke statusovergang compare-and-set (`StatusIntussenGewijzigd`) — BLOW-bulk 18-09: 118 executies, 429, 8× dubbel verwerkt, stil teruggezet duplicaat — zie BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)".
  6. Tweede postvak facturen@kempengroep.nl DIRECT gelezen (Peter 22-09, migratie 0171): kanaal `facturen_kempengroep` + job `rlz-intake-imap-kempengroep`; een gelezen-vlag is geen verwerkt-administratie — de fetch leest INBOX + Spam, gelezen én ongelezen, en slaat over wat in `intake_bericht_verwerkt`/`intake_bericht` staat (Message-ID); spam = chip "uit Spam" + LET-OP; herstelrun `--sinds`; lees-only `intake-postvak-audit` — zie BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)".
  **LEESPLICHT: lees `docs/regels/intake-extractie.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Automatisch boeken, autoboek-kandidaten en de AI-plausibiliteitstoets** — Opt-in per leverancier en per administratie (leren ná drie identieke mens-boekingen), harde checks blijven blokkerend, volumerem, AI-toets als extra poort mét uitval = doorlopen zichtbaar, autonomie-toekomstlijn.
  1. Automatisering-first: mens-op-de-knop is een testfase-drempel; elk deterministisch pad krijgt een autoboek-opt-in volgens het vaste patroon (default UIT, harde checks blokkerend, volumerem, 'automatisch'-markering + audit, storno als terugweg).
  2. Geen LLM in geldberekeningen; AI kiest nooit een rekening zonder deterministische toets; AI-uitval = doorlopen zonder AI, zichtbaar (chip + LET-OP); `twijfel` = niet boeken.
  3. Status per harde check is canoniek in BESLISSINGEN "Harde/blokkerende checks" — gedocumenteerd ≠ gebouwd.
  4. Volumerem alleen automatisch (SPOED Peter 18-09): 20/dag telt uitsluitend automatische boekingen; handmatig én ná klant-akkoord = 500-noodrem; één helper `app/documenten/volumerem.py`, élke melding noemt rem + teller + handeling — zie BESLISSINGEN "VOLUMEREM — ALLEEN AUTOMATISCH (Peter 18-09)".
  5. Harde checks — het externe deel (IBAN-seed, duplicaatquery's) wordt per document gecachet op vingerafdruk en bij boeken hergebruikt (≤ 15 min); retry ná boeken_mislukt en het autoboek-pad toetsen altijd vers (Peter 18-09) — zie BESLISSINGEN "BOEKEN SNELLER — CHECKS-CACHE + ACHTERGROND-SCHRIJVER (Peter 18-09)". Aangescherpt 21-09: extern gecachet = alleen RLZ-roundtrips; álle lokale toetsen (IBAN-set, duplicaat module, btw) draaien vers, ook op het boekmoment — zie BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09".
  **LEESPLICHT: lees `docs/regels/autoboeken-ai.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Reconciliatie, bewaking en meldingen** — Dagelijkse reconciliatie-blokken (documenten, bank, omzet, doorbelasting, intercompany, RC, rlz_dubbel, dubbele betaling), tellers per automatisering, actiemail + systeemmail, synthetische bewaking, bevindingssoorten in `meten`.
  1. Signalering zonder handeling is niet af: élke bevinding draagt een actie; kantoor krijgt alleen een ACTIEMAIL bij bevindingen mét handeling; systeemmail alleen bij LET-OP/systeemfout; regressies = "systeemfout — automatisch gemeld" + audit.
  2. Élke nieuwe bevindingssoort start in `meten` (facet "in meting", nooit actiemail/KPI) tot Beheerder-promotie; explosie-rem > 50/run → terug naar meten; verdwenen bevindingen — afwijkingen ÉN fouten (19-09 avond) — sluiten mét audit `reconciliatie_auto_gesloten` per soort + `samenvatting["delta"]` op de run-rij.
  3. Verdwenen extern document = `ontbreekt_in_rlz/odoo` mét "Opnieuw boeken" achter de aangiftepoort (suppletie-pad, Beheerder); bedragverschil ≤ € 0,05 = automatisch geaccepteerd mét audit.
  4. IC-verkoopkant = `SalesInvoices` ∪ `Receipts` (de collectie ziet API-facturen niet), aansluitingsblok leest de whitelist per scope, een blok dat "niets te toetsen" meldt terwijl de configuratie bestaat = systeemfout (19-09) — zie BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)".
  5. Blok `intake` (Peter 22-09): telling aan de bron (INBOX + Spam, gelezen én ongelezen) ↔ verwerkt per kanaal; verschil = `intake_postvak_verschil` direct in `actie` mét "Nu verwerken" (start de intake-job), verbinding stuk of kanaal-mét-job niet geconfigureerd = FOUT, uit Spam = LET-OP per afzender, dagteller "Intake-postvakken" — zie BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)".
  **LEESPLICHT: lees `docs/regels/reconciliatie.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Verplichtingen/offertes, projecten, projectverdeling, contract-ontleding en voorraad** — Documenttype `verplichting` + factuur↔offerte-match (nooit blokkerend), projectenmodule en projectcode-generatie, Inzicht › Projecten/Projectverdeling, pro rato, contract-ontleding auto-first, mini-voorraad en voorraad-aansluiting (mi-schema, nooit RLZ-writes).
  1. Project verplicht = hard blokkerend zonder "geen project"-optie; overhead → intern OVH-project óf pro rato over de actieve projecten per klantkeuze (Universal = omzetsleutel, géén OVH-project — Peter 21-09, zie BESLISSINGEN "UNIVERSAL — OVERHEAD VIA DE OMZETSLEUTEL, GEEN OVH-PROJECT (Peter 21-09)"); projectcode volgt de naamconventie van de klant en synct naar RLZ.
  2. Match-motor deterministisch; wachtende verplichting = `niet_toetsbaar` mét verwijzing, nooit stil `geen_verplichting`; goedkeuring matcht ook geboekte facturen achteraf (tijdlijn + audit).
  3. Contract-ontleding schrijft specs/staffels direct met herkomst `contract` (correctie → `mens`); voorraadstand = Σ append-only mutaties, mens-manipulatie onmogelijk.
  4. Projectstatus + nummer uniek (Peter 18-09, migratie 0160): afsluiten = bron eerst inactief (RLZ IsActive/Odoo archived, teruglezen, RLZ wint) → uit álle keuzelijsten via `is_actief`, toggle "Toon afgesloten (N)", nagekomen factuur = oranje; nummer = cijfer-prefix uniek per administratie over cache + RLZ (409 mét bestaand project); dubbelen/kandidaten = lees-only CLI's; het nummer wordt óók gelezen ná het voorvoegsel "Afgesloten" (19-09, rij B4) — zie BESLISSINGEN "PROJECTEN — STATUS AFGESLOTEN + PROJECTNUMMER UNIEK (Peter 18-09)".
  5. Offerte-verbruik = geboekt + onderweg (Peter 18-09 "hij moet wel doortellen", migratie 0166): facturen die nog niet geboekt en niet terminaal zijn tellen mee in de toets ("€ 70.000 van … · waarvan € 20.000 nog niet geboekt (1 factuur ter accordering)"), statuswissel van een gematchte factuur herberekent de andere open facturen mét tijdlijnregel, drie getallen geboekt/onderweg/restant overal, nazorg-CLI `verplichting-match-herberekenen` — zie BESLISSINGEN "OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)".
  6. Facturen zonder project = lees-only rapport (18-09 avond, TODO 23-08): CLI `facturen-zonder-project` (module-kant, gedekt door bevroren verdeling = geen bevinding; `--rlz` alleen GET), herstelroute als voorstel; Universal 0 bevindingen — zie BESLISSINGEN "FACTUREN ZONDER PROJECT — LEES-ONLY RAPPORT + INBOX-HYGIËNE (18-09 avond)".
  7. Projectverdeling sluit afgesloten projecten uit (19-09): omzetsleutel = `is_actief` ÉN status ≠ afgesloten, nooit op naam ("Afgesloten…" actief = LET-OP in blok `projecten`), afsluiten herrekent nog niet geboekte verdelingen mét tijdlijnregel, geboekte blijven; lees-only CLI `projectverdeling-afgesloten-rapport`; Universal RLZ-kant 2026 = 0 zonder project — zie BESLISSINGEN "PROJECTVERDELING SLUIT AFGESLOTEN PROJECTEN UIT + RLZ-KANT-METING FACTUREN ZONDER PROJECT (19-09)".
  8. Tab "Afsluiten? (N)" mét bulk-afsluiten (Peter 19-09, migratie 0167): één motor `app/projecten/afsluiten.py` (redenen stil N mnd per administratie / eindfactuur / naam zegt afgesloten / looptijd verstreken; geen activiteit ≠ stil), vinkjes + "Afsluiten (N)" = 0160-flow per project mét uitkomst per rij, "Niet afsluiten" mét verplichte reden onthouden tot nieuwe activiteit, nooit automatisch — zie BESLISSINGEN "PROJECTEN — TAB AFSLUITEN? MÉT BULK-AFSLUITEN EN NIET-AFSLUITEN (Peter 19-09)".
  **LEESPLICHT: lees `docs/regels/verplichtingen-projecten-voorraad.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Uren & meerwerk, planning, werkopdrachten, veldwerkers** — Steigerbouw-tak (opt-in per administratie): weekstaat per project, hybride keuring, factuurmatch, ZZP-dossier + KvK, planning-agenda mét urenstatus, transport, werkopdrachten, Beheer › Veldwerkers, materiaal.
  1. Nieuwe module-code roept nooit `RlzClient` aan (seam-eis; adapter-grepen in BESLISSINGEN "ODOO-ADAPTER — GREPEN"); geofence-native alleen op `feat/geofence-native`, nooit mergen/releasen.
  2. Recht 'veldwerkerbeheer' dekt overzicht, koppelingen en dossier binnen de eigen scope (server-side + RLS); rechten toekennen blijft Beheerder-only.
  3. Planning in een verstreken/lopende week = audit `achteraf` + één gebundelde melding per veldwerker × week; urenstatus in het grid uit de weekstaat.
  4. Veld-app uitvoerder 18-09: m² optioneel, doorfactureren-keuze per regel (0158), alle projecten mét gepland bovenaan, uitvoerder schrijft eigen uren (nooit zelf keuren), geen planningstab — zie BESLISSINGEN "VELD-APP UITVOERDER — FEEDBACK 18-09".
  5. Project eerst (Peter 18-09): de week = projectkaarten (gepland ∪ mét uren ∪ mét meerwerk) mét "+ Uren"/"Meerwerk melden" per kaart, "+ Ander project" = keuzelijst `?alles=true` — zie BESLISSINGEN "VELD-APP — PROJECT EERST (Peter 18-09)".
  6. Beoordelen (Peter 18-09): `/meerwerk` = tabs Urenstaten (N) · Meerwerk (M) uit dezelfde definitie als de chip; kantoor-keuring als vangnet; uitvoerder keurt álle ingediende urenstaten in scope, koppeling = alleen "gepland bovenaan" — zie BESLISSINGEN "BEOORDELEN — URENSTATEN EN MEERWERK OP ÉÉN PLEK; UITVOERDER KEURT ALLES IN SCOPE (Peter 18-09)".
  7. Veld-app UX run A (Peter 18-09): zelfde-als-gisteren (bron=kopie), tikknoppen, omschrijving-chips per administratie (0159), ≥ 48 px/≥ 14 px, indien-samenvatting, vergeten dag, terugkoppeling, doorfactureren ingeklapt, m² onder "meer" — zie BESLISSINGEN "VELD-APP — 12 UX-VERBETERINGEN (Peter 18-09)".
  8. Planning v3 DAG-EERST (Peter 18-09, migratie 0161): dagkolommen mét projectkaarten, projectbalk → reservering, vulhandvat = één bulkroute (conflict = gepland + oranje, nooit blokkerend; ongedaan = zelfde set terug), ploeg-paneel, "Per project" = lezen, afwezigheid minimaal — zie BESLISSINGEN "PLANNING V3 — DAG-EERST (Peter 18-09)".
  9. Veld-app UX run B (Peter 18-09, migratie 0162): dag-einde herinnering 16:30 per administratie (default doorlopen, opt-out per gebruiker, één claim per dag, job `rlz-uren-herinneringen`), offline-wachtrij op het slot-anker mét 409 `weekstaat_bevroren` = beide standen kiezen, indienen online-only — zie BESLISSINGEN "VELD-APP — 12 UX-VERBETERINGEN (Peter 18-09)".
  10. Conflictenpaneel (Peter 21-09, migratie 0169): balk → paneel per dag mét soort + handeling ("Houd ‹A›" via de bulkroute bron `conflict`, "Beide (halve dagen)…" = akkoord mét reden, rij weg tot de planning wijzigt), alleen huidige/toekomstige dagen, "deze week" alleen als het zo is + weekchip "verstreken week"; dubbele veldwerkers alleen op harde sleutels (KvK/IBAN/e-mail — nooit naam/planning: broers in één ploeg), lees-only CLI `veldwerkers-dubbelen` — zie BESLISSINGEN "PLANNING — CONFLICTENPANEEL MÉT HANDELING + DUBBELE VELDWERKERS (Peter 21-09)".
  **LEESPLICHT: lees `docs/regels/uren-planning-veldwerkers.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Omzetboekingen, omzetbronnen en het verkoopfactuur-boekpad** — Kassarapporten (ProfX, dagstaat/kascheck, pilates-export) als entity-loze Receipts mét binder Inkomsten + kostprijsmemoriaal, stores → administratie platformbreed, tegenzijde per betaalwijze, Vastly-verkoopfacturen (§2d), waarborg.
  1. Kasomzet = losse boeking (geen dummy-debiteur); categorie op BINDER Inkomsten, niet op naam; bron-parsers deterministisch (géén AI, geen AVG-gate); harde bron-controles als check-rijen.
  2. BLOW cannabisomzet = "NL, Geen BTW (Vrijgesteld)", bewust géén 0 %-tarief; punten = omzet 21 %; Stripe = EU-dienst verlegd; combi pro rato oranje.
  3. Onbekende store → verzamelbak `omzetbron_store_onbekend` + "Stores koppelen →"; kassarapport in de inkoopstroom zónder parser-treffer (alleen omzetrekeningen) = dagelijkse bevinding mét "Type wijzigen → kassarapport".
  4. Parser-eenduidig = het systeem doet het (Peter 19-09): inkoopfactuur mét ProfX-/dagstaat-/kascheck-/pilates-treffer wordt bij upload én in de dagelijkse run DIRECT kassarapport (tijdlijn + audit `soort_automatisch_gewijzigd`, chip "automatisch getypeerd", terugweg "Tóch inkoopfactuur…" mét reden, ná 2 correcties per afzender weer melden, dagteller `kassarapport_autotype`, nazorg-CLI `kassarapport-autotype-nazorg`) — zie BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)".
  **LEESPLICHT: lees `docs/regels/omzet.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Bank: sync, matchmotor, afletteren, splitsen, batches** — Bank-sync automatisch (07:00) zonder knoppen, voorstel-volgorde exact → gedeeltelijk → vaste regel/historie-regel → RLZ-voorstel → handmatig, afletteren via actie 15 op de PaymentTransaction, batch-stap, open bedrag als maat, zoekveld, Ponto = Jarvis.
  1. GROEN (auto-afletteren) = teken + naam/IBAN + nummer (heel token; RLZ-volgnummer óf klantreferentie) + bedrag cent-exact; ORANJE = geen teken-mismatch + twee van drie; label `bron` zegt wat matchte.
  2. Open bedrag stuurt alles (voorstellen, boeken = dekking exact, splitsen); afgeletterd toets je op `OpenAmount`, nooit op `IsComplete`; terugdraaien = storno 19 (type 16 ontkoppelt nooit).
  3. Historie-regel (IBAN + omschrijvingskern, ≥ 6 mnd, ≥ 3 boekingen) alleen automatisch bij 100 % en zonder open posten; afletteren gaat NIET door de klant-accorderingsflow.
  **LEESPLICHT: lees `docs/regels/bank.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Kempen-doorbelasting en intercompany** — Tweezijdige motor bron-verkoop + spiegel-inkoop ("Boeken + doorbelasten"), whitelist + doelentiteiten, IC-vlag, tegenboek-pad ná ingediende aangifte, aansluiting KF ↔ doelentiteiten, herkoppeling, intercompany slaat klant-accordering over.
  1. Storno-blokkade ná een ingediende aangifte (`app/rlz/aangifte.py`) → TEGENBOEK-PAD; `DoorbelastingInstelling.standaard()` is de ENIGE bron voor de niet-opgeslagen standaardstand.
  2. Herkoppeling van whitelist-rijen zonder doel alleen op exacte genormaliseerde naam; bijna-match/meerdere = LET-OP, nooit raden; doorbelastingspaar rood in de reconciliatie = systeemfout.
  3. IC-leverancier (actieve rij in `intercompany_tegenpartij` van de administratie van het document) in een administratie mét klant-accordering → géén ronde, direct de boekstap, tijdlijn + audit.
  4. Doorbelastingsverkopen staan alleen in de `Receipts`-collectie (record-GET wél); IC-toets + aansluiting lezen de unie, whitelist per administratie-scope (19-09, 174 × ic_spiegel_rood opgelost) — zie BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)".
  **LEESPLICHT: lees `docs/regels/doorbelasting-intercompany.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Klant-accordering, accordeur-/veldwerker-app, native store-apps en OTA** — Sequentiële lagen mét drempels (administratie-, afdelings- en leveranciersroute), herberekening bij configuratiewijziging, staande goedkeuring alleen bij een periodiek patroon, wachtrij set-based, PWA + iOS/Android-schil, OTA self-hosted per runtime, 426-poort, store-draaiboeken.
  1. Ná het laatste akkoord blijft het document op ter_accordering tot de boeking staat; harde checks draaien opnieuw; compleet klant-akkoord kan niet opnieuw ter accordering.
  2. Voorrang afdelingsroute > leveranciersroute > administratieroute; één route per leverancier (409); herberekenen i.p.v. vervallen.
  3. Train-regel: ná élke store-goedkeuring de marketingversie ophogen vóór de volgende push; OTA registreert per RUNTIME; `APP_MIN_RUNTIME_VERSIE` nooit vóór de winkelversie live is; native dependency = winkelrelease.
  4. App-auth zonder passkey (0029): toestelbinding + 5-cijferige toegangscode, éénmalige activatie per toestel; mislukte opslag eerlijk gemeld, nooit een tweede server-activatie.
  5. Klant-accordering-beheer (Peter 18-09, migratie 0164): kantoorbreed zoekveld/filterchips/samenvatting per regel + deeplink `?administratie=`; "Geen klant-accordeurs" = uitnodigen (voorgevuld) of bestaande accordeur koppelen (bestaande scope-route); leveranciersroute 'vervangt' | 'bovenop' (gewone lagen + extra laag vóór/ná, wijziging gewone route werkt door) — zie BESLISSINGEN "KLANT-ACCORDERING — ZOEKVELD, ACCORDEUR UITNODIGEN, LEVERANCIERSROUTE BOVENOP (Peter 18-09)".
  6. Toegang ≠ laag (BUG Peter 18-09, casus Bouwadvies/Romy): toevoegen bij een accordeur = scope-only mét keuze-stap (alleen toegang | ook als laag vóór/ná — bestaande lagen blijven | alleen leveranciersroute), verwijderen = twee vinkjes, bulk vervangt bestaande lagen alleen ná bevestiging per administratie (`vervangen_bevestigd`, server-side), "Andere klant-accordeur toegang geven…" onder élke accordeur-keuzelijst — zie BESLISSINGEN "TOEGANG IS GEEN LAAG — KLANT-ACCORDEUR TOEGANG GEVEN VERANDERT DE GOEDKEURINGSROUTE NIET (Peter 18-09)".
  7. Ter accordering — dagelijkse bestaanscheck "intussen buiten de module geboekt" (Peter 22-09, casus Bouwadvies F/2026/01235 → RLZ-04-00000518): blok `documenten` toetst élk open document (ter_accordering, wacht_op_iban, klaar_om_te_boeken > 1 dag) VERS tegen RLZ/Odoo; treffer = actie-bevinding `intussen_extern_geboekt` (direct `actie`, geen meetfase — besluit Peter) mét "Afwijzen — al geboekt als ‹boekstuk›" (ronde vervalt "niet meer nodig: al geboekt in Reeleezee" + bestaande afwijs-route) en "Toch verschillend — doorgaan"; app: banner, uit "Te accorderen", telt in "Wachten op kantoor", akkoord/herinnering 409; boekfout ná laatste akkoord = dezelfde twee knoppen; copy-check "bug"; gemeten 23-09: hercontrole/soort/actiemail/poort (32 × 409)/herinnering-onderdrukking werken in productie JA, handelingen ongebruikt → dispatch-onderdeel `extern-geboekt` + poging 2 — zie BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)".
  **LEESPLICHT: lees `docs/regels/accordering-native-app.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Vastgoedgroep Nederland → Odoo (run 1 + run 2) en het pandenregister** — Schoonlijst, pandenregister (`pand`/`pand_boeking`, pand = RLZ-project), replay RLZ → Odoo-move-vorm (lees-only), rekeningmapping, 1001-model, RJ-220-rollen op company 6, bewijscyclus `vgg-odoo-stap0`, `vgg-odoo-migratie` (concepten → toets → auto-posten), metingen via de nameting-workflow.
  1. Company-pin in de code, kill-switch alleen als executie-override, elke write terug-gelezen, audit per call; nooit unlink (annuleren = button_cancel); nooit via `nameting.sh` (weigert de schrijvende commando's hard).
  2. Memoriaalregels uitsluitend uit `DebitAmount`/`CreditAmount` (nooit `NetAmount`/`CreditOrDebit`); liquide middelen nooit in de rol-pool; één regel, één bestemming (overlap 1001-model ↔ rol = ROOD).
  3. Toets vóór het onomkeerbare moment: concepten → cent-exacte toets (Odoo-regels, per pand sluit) → pas dán posten; rood = niets posten; GO Peter op het SCHRIJF-c-rapport vóór de volledige run; RLZ-webfilter-blokkering = meting ongeldig.
  4. Vastly-klant op Odoo (verkoop/waarborg/bank-afletteren/webhooks; pilot verhuurder, nooit VGG) = ONTWERP TER AKKOORD (19-09): toets + pilotmeting gedaan, advies ARVUM onder voorwaarde Vastly-onboarding + Odoo-company, concept-addendum v1.21 in Platform/OPEN_ITEMS; geen bouw vóór akkoord — zie BESLISSINGEN "VASTLY OP ODOO — ONTWERP TER AKKOORD (Peter 19-09)" + `docs/ONTWERP_VASTLY_ODOO.md`.
  5. Toewijzing Schoffelstraat 29 UITGEVOERD 22-09 (werkt in productie: ja, idempotent), `plan` = bewijspaar vertaalbaar; SCHRIJF c gestrand op de pand-analytic-pseudo-sleutel (`action_post` 500, niets gepost) → `PandAnalyticOplosser` (lookup-vóór-create in het plan, herstel van concept 3370, guard in `maak_concept_move`), poging 2 ná deploy GESLAAGD 22-09 avond (analytic 851 aangemaakt, concept 3370 hersteld, GEPOST als F/2026/00001; werkt in productie: ja); reconcile niet uitgevoerd (klikpunt IBAN BNK1 leeg) en per-pand-sluit-eis niet gehaald (41 panden, beslispunt 2 mapping 1100/1601) → SCHRIJF d zou niets posten; GO-vraag = rapport `2026-09-22-vgg-schrijf-c-poging-2.md` — zie BESLISSINGEN "VGG — BESLISPUNT 1 BESLIST: TOEWIJZING PAND + SOORT VERKOOP RLZ-01-00000082 (Peter 21-09)".
  **LEESPLICHT: lees `docs/regels/vgg-odoo-migratie.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Activa / MVA** — AKKOORD Peter 21-09 ("activa, JA", alle defaults §8) op `docs/ONTWERP_ACTIVA_MVA.md`; fase 1 GEBOUWD 21-09 (migratie 0168): register-lezer RLZ `FixedAssets` + probe (403 = zichtbaar "recht ontbreekt"), detectie bij boeken (`grootboekrekening.is_activa` + activeringsgrens 450/RLZ `FixedAssetAlertAmount`), kaart "Activum aanmaken?" op het controlescherm, activum in RLZ ná boeken (mens bevestigt; opt-in automatisch per administratie, default UIT), reconciliatieblok `activa` in `meten`; fiscale toetsing zonder zelf rekenen — zie BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)".
  1. MVA = `IsFixedAssetAccount` ÉN AccountType 3 ÉN 0xxx (de vlag alleen is te breed); enumeraties root-only (`rlz-lezen --root`); Universal 403 = probe verplicht.
  2. Nulmeting 21-09 (78 administraties): 51 activa in 7 registers (Pilates Bloom 20 = rijkste, Zilver Beheer 13, Mantelzorgwoningen 11), 344 MVA-rekeningen, Universal + Rubicon 403; fase 2 (afschrijving triggeren/bewaken) en Odoo volgen ná de productiemeting van fase 1.
  3. Gemeten 22-09: sync (344/75, grens, probe) + blok `activa` (75 getoetst, 22 in `meten`) + kaart-route werken in productie JA; kaart/aanmaken niet gemeten (geen MVA-factuur in de module = klikpunt); een lees-only reconciliatie schrijft óók geen probe-stand (bijvangst gefixt), meetlat `db-lezen activa-stand` — zie BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)".

- **Factuuropdracht per project (steigerbouw → verkoopfactuur klaarzetten in RLZ/Odoo)** — MOCKUP TER AKKOORD (Peter 18-09, `mockup/factuuropdracht-project.html`, beslispunten ④ verzenden / ⑥ klant-accordering); geen bouw vóór akkoord — zie BESLISSINGEN "FACTUUROPDRACHT PER PROJECT — MOCKUP (Peter 18-09)".
  **LEESPLICHT: lees `docs/regels/activa.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

- **Werkloop, nametingen, deploy en productie-toegang** — Gouden set als poort, cc-inbox (launchd), nameting-workflow + `nameting.sh`, rapporten + INDEX, deploy.yml-lessen, productie alleen via gedeployde jobs, Feiten eerst (querybibliotheek, leesreplica), migratie-guards, database/RLS-lessen.
  1. Definitie van "af": gouden set groen + productiegedrag ná deploy nagemeten met een vooraf genoemd meetrecept + rapportregel "werkt in productie: ja/nee/niet gemeten"; een meting telt pas als het bot-bestand op main staat óf het run-log is gelezen.
  2. Nooit een lokaal proces tegen de productiedatabase; schrijvende nazorg = `gcloud run jobs execute` op de gedeployde image ná deploy; nametingen onder `nameting@` (lees-only allowlist); deploy-check toetst service ÉN jobs.
  3. Een `^<t>^`-scheidingsteken staat nooit in een waarde; volledige envset per service/job in één stap; élk CC-eindrapport als `docs/rapporten/<datum>-<slug>.md` + INDEX-regel + sectie "Gelezen regels".
  4. Wachten van de inbox op een handmatige CC is nooit stil (duur, aantal, melding ná 30 min, `rlz inbox vrijgeven` als bewuste keuze).
  5. CC-inbox rij (i) (18-09 avond): een lopend-kopie van een opdracht die al in gedaan/ staat mét kopregel is af — opruimen, nooit herstarten; `rlz inbox status` toont lopend/ als loopt/af/gestrand — zie BESLISSINGEN "FACTUREN ZONDER PROJECT — LEES-ONLY RAPPORT + INBOX-HYGIËNE (18-09 avond)".
  6. Stop-hook-push non-fast-forward = stille deploy-blokkade (19-09): bot-commit op origin tijdens een run → élke volgende push faalt stil; stap 0 toetst óók `main..origin/main` en merget (`--no-ff`, nooit rebase) vóór de deploy-check; procesfix gebouwd (Stop-hook = `stop-push.sh` merge + retry, status toont divergentie), beslissing 19-09 avond: geen bot-only-filter, `nameting.yml` ongewijzigd (bot blijft op main, wacht niet op deploy) — zie BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)" en "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)".
  7. CC-inbox rij (j) (19-09): claim per opdracht = atomische `mv` + `.claim` (pid/starttijd), `opdrachten/.lock` atomisch als dé ene runner-lock, ongecommit werk ná een run = WIP op `wip/<slug>` (nooit gedaan/, volgende poging start ermee), exit 0 zonder rapport/commit = herstart, vuile werkboom bij start = stop, Stop-hook via `scripts/git-hooks/stop-push.sh` = fetch + merge --no-ff + retry, blokkade luid in `rlz inbox status` — zie BESLISSINGEN "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)".
  8. CC-inbox rij (k) (19-09 avond): een opdracht mét `niet vóór: JJJJ-MM-DD[ UU:MM]` in de kop wordt pas ná dat moment geclaimd (een nameting "ná de run van 06:30" start niet de avond ervoor); `rlz inbox status` toont "wacht tot …" — zie BESLISSINGEN "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)".
  9. F3-jobs (BUG 21-09): élke `gcloud run jobs deploy` in deploy.yml draagt `--command` (Dockerfile bewust zonder ENTRYPOINT), ná de F3-lus start élke job één keer mét `--smoketest` (niet startbaar = deploy rood), f3_jobs.sh toetst/zet het commando bij "bestaat al" en eindigt luid mét GEPAUZEERD/ZONDER STARTCOMMANDO; boeking > 10 min op wordt_geboekt = regressie-LET-OP + kwartier-probe mét "Opnieuw indienen"; gemeten 22-09: command/smoketest/schedulers/probe/auto-sluiting ja, trigger-pad niet gemeten (poging 2 23-09); nieuw dispatch-onderdeel = if-tak + options + via_gh + OORDEEL_BRON-tak — zie BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)".
  **LEESPLICHT: lees `docs/regels/werkloop-productie.md` volledig vóór élke wijziging, opdracht of advies in dit domein — niet gelezen = niet beginnen.**

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

- **Werkloop, nametingen, deploy, productie-toegang en Feiten eerst: volledige tekst in `docs/regels/werkloop-productie.md` (LEESPLICHT).** Kern: gouden set + nameting + "werkt in productie: ja/nee/niet gemeten" = de definitie van af; productie alleen via gedeployde jobs of het nameting-SA; élk rapport in `docs/rapporten/` + INDEX + sectie "Gelezen regels".
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
