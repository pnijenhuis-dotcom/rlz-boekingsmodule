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
  **Uitzondering klant-accordeur (besluit + gebouwd 2026-08-11, migratie 0040): passkey/WebAuthn
  i.p.v. TOTP** — publieke sleutel per gebruiker+apparaat (py_webauthn), volledige login alleen
  bij eerste gebruik / nieuw apparaat / ná 7 dagen inactiviteit (sliding 7-dagen-refresh-TTL),
  passkey-assertion éénmaal per app-opening, GEEN biometrie per actie; kantoor-kill-switch per
  apparaat (bijt per request + bij rotatie + bij assertion); dev-stub `auth_biometrie_dev_stub`
  voor LAN-kliktests (WebAuthn vereist https/localhost), hard onwerkzaam buiten dev. Zie
  BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD".
  **Platformbesluit 0020 (2026-08-15, samen met vastgoed): passkeys worden de EERSTE
  authenticatielijn voor álle rollen; wachtwoord + TOTP wordt terugval/herstel.**
  Kantoor-passkeys bouwen bij de GCP-fase (WebAuthn vergt https); accordeurs hebben het al.
- **Autorisatie (hard, bevestigd 2026-07-06):** klanten-scope per medewerker via koppeltabel
  gebruiker↔administraties, afgedwongen door RLS (DB-niveau) + server-side checks — geen scope =
  geen data, ook niet via bugs in de app-laag. Rol- en scope-wijzigingen exclusief door de
  Beheerder-rol (initieel alleen Peter), server-side gecontroleerd. **Niemand kan zijn eigen rol
  of scope muteren, ook een Beheerder niet** (tweede beheerder aanwijzen kan alleen door een
  andere beheerder). Elke rol-/scope-wijziging in het append-only audit_event.
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
- **Boekingsgeheugen**: RLZ-historie + app-correcties; correcties wegen zwaarder (recency). Default
  voorstel, nooit blind boeken. Afwijkingen markeren (oranje), niet overnemen. **Seed-only = oranje
  (aangescherpt 2026-07-14): een waarde die uitsluitend op RLZ-historie steunt blijft oranje ("uit
  historie, nog niet bevestigd"), óók bij hoge stem-confidence — pas de eerste app-bevestiging van
  die waarde maakt 'm groen (`app_bevestigd` per veld in engine + voorstel-response).**
- **Automatisch boeken = opt-in per leverancier**; harde checks blijven áltijd blokkerend.
  **Status per harde/blokkerende check: canoniek in `docs/BESLISSINGEN.md` (verplichte eerste
  check, houd dáár actueel — gedocumenteerd ≠ gebouwd).** Kort: duplicaat, regeltelling,
  verplichte velden, IBAN-wissel, vraag-blokkeert-boeken, afwijzen-met-verplichte-reden en
  webhook-HMAC-per-verzendpoging (mét afleveraar, 2026-08-02), memoriaal-saldo-0
  (omzetmodule, 2026-08-07), het VGB-prefixfilter (e-mail-intake, 2026-08-07 — dekt het
  intake-kanaal; bij een latere leesroute uit gedeelde administraties dáár opnieuw toepassen)
  én btw-per-regel-=-factuur-btw (verkoop, blok A 2026-08-10 — categorie {S/E/Z/AE} + bedrag,
  eenhedennormalisatie fractie↔percentage in `app/sync/btw.py`, btw in het verkoopvoorstel
  auto-ingevuld + VERGRENDELD, ambiguïteit = eenmalige onthouden keuze per administratie,
  migratie 0038) zijn gebouwd + getest; **per-leverancier-autoboeken-opt-in: GEBOUWD + GETEST (2026-08-09,
  migratie 0036 + `app/documenten/autoboeken.py`)** — boekt ná extractie uitsluitend bij
  opt-in aan (Beheerder-only, default UIT) + harde checks groen + voorstel volledig uit
  app-bevestigd boekingsgeheugen (seed-only/oranje weigert) + geen mogelijk-duplicaat/open
  vraag/afwijzing; volumerem en accorderingspoort onverkort; elk geval geauditeerd +
  tijdlijn-/werkvoorraadmarkering "automatisch". NB bank-autoboeken (opt-in per
  administrátie, vaste regels) staat hier los van (live sinds 2026-08-02).
- **Vragenworkflow**: vraag blokkeert boeken, toegewezen aan eigenaar per administratie, antwoord
  voedt het geheugen. Vragen zijn een status in de werkvoorraad (geen apart menu).
- **Afwijzen** = verplichte reden, blijft zichtbaar ("Afgewezen — ter controle").
- **Verzamelbak "Niet toegewezen"**: alles wat niet eenduidig aan een administratie koppelt
  (tenaamstelling leidend, afzender = hint); leert van handmatige toewijzingen; "hoort niet bij
  ons" met reden. Nooit auto-toewijzen bij twijfel.
  **Bouwstatus: GEBOUWD + GETEST (2026-08-07, met de e-mail-intake)** — migratie 0028 +
  `backend/app/intake/` + `frontend/src/intake/`; details BESLISSINGEN "E-mail-intake +
  verzamelbak — GEBOUWD + GETEST". Eigen naamnormalisatie: "Holding" blijft onderscheidend
  (mockup-casus); afzender-regel wijst alleen auto toe zonder tegenstrijdig
  tenaamstelling-signaal.
- **E-mail intake**: één centraal adres, splitsen van multi-factuur-PDF's op factuurgrenzen,
  toewijzen op tenaamstelling.
  **Bouwstatus: GEBOUWD + GETEST (2026-08-07)** — .eml-upload (`POST /intake/eml` + werkvoorraad-
  uploadzone) is het werkende kanaal, idempotent op Message-ID; de live IMAP-fetch is een
  gemarkeerde seam (`app/intake/postvak.py` + intake_imap_*-settings) die bij de GCP-uitrol
  geactiveerd wordt. Routing per bijlage: kapotte/NLCIUS-invalide UBL → verzamelbak (§2d-
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
- **Kempen-doorbelasting (besluit Peter 2026-08-13, hoort bij de livegang; canoniek
  `verkenning/16_DOORBELASTING_KEMPEN.md` + BESLISSINGEN "KEMPEN-DOORBELASTING")**: tweezijdige
  motor op het HUIDIGE patroon (2025/2026, granulair per document; historie = archief). Actie
  "Doorbelasten…" op een GEBOEKTE inkoopfactuur (toggle per bron-administratie, default UIT —
  alleen Kempen Facilities; NB bewuste afwijking van de mockup-boekflow-trigger) →
  regelverdeling in % (exact 100%, grootste-rest-centen) over de geseede mapping-whitelist
  (doelentiteit ↔ customer-GUID, server-side afgedwongen, `make doorbelasting-seed-kempen`) →
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
  0044/0045), UI + motor-tests in afronding — zie BESLISSINGEN. Afhankelijkheid Peter:
  webservice-logins doelentiteiten (elke bestaande login is single-administratie).
- **Klant-autorisatie (à la Zenvoices), optioneel per administratie**: accordeurs per klant,
  sequentiële lagen met voorwaarden (bedragdrempels). Boekknop wordt "Ter accordering"; na laatste
  akkoord automatisch boeken (harde checks draaien opnieuw). Klant-app = PWA + store-apps
  (besluit Peter 2026-08-15: de accordeur-app wordt óók uitgebracht als native App Store- én
  Google Play-app; de gebouwde PWA/webcode is de basis via een native schil, bv. Capacitor —
  PWA blijft interim + terugval; aandachtspunten native passkey-integratie (WebAuthn in een
  webview is beperkt) en store-accounts onder de juiste entiteit; planning ná GCP). Factuurbeeld
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
  Zie BESLISSINGEN "Accordeur-PWA + auth-cadans — GEBOUWD". E-maillink-goedkeuren en push
  (incl. service worker) zijn het open GCP-vervolg.
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

## Koppelvlak vastgoedmodule (`../Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md` is leidend, v1.15)

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
- **Route A — projectaanmaak-naar-RLZ on-demand (§5, v1.15 — GEBOUWD + GETEST + LIVE
  GEVERIFIEERD 2026-08-14):** `POST /koppelvlak/vastgoed/projectaanvragen` (`app/projecten/`,
  migratie 0048) — HMAC+timestamp+nonce met EIGEN inkomend secret
  (`PROJECTAANVRAAG_HMAC_SECRET`, uitwisseling bij F4), `bericht_id`-idempotentie, harde
  is_vastgoed-scope, synchroon `rlz_project_id`+definitieve projectnaam. Motor: UUIDv5 op
  administratie+pand_referentie, lookup-vóór-PUT (RLZ-naam wint — PUT is create-or-update!),
  naamconventie-poorten (BAG-id §2.1 = weigeren), systeemanker-debiteur "Pandprojecten
  (systeem)" per administratie (de RLZ-route `PUT Customers/{baseId}/Projects/{id}` dwingt
  een customer af; ⚠️ IsActive default false → motor zet expliciet true — STAP-0-feiten:
  api-verkenning "Projects-schrijfroute STAP-0"), directe project_cache-upsert. Open:
  aanroepkant vastgoed (OPEN_ITEMS); `project_verplicht`-activatie = S2-moment (gereedheid
  geverifieerd: default UIT, Beheerder-only, check leest live).
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

- `mockup/index.html` — goedgekeurde UI (alle schermen, klikbaar; design tokens = CSS-variabelen)
- `mockup/accordeur.html` — klikbare mobile-first accordeur-app-mockup (blok 5, 2026-08-09;
  ter beoordeling Peter op het mobiele breakpoint — bouw start pas na akkoord)
- `verkenning/api-verkenning.md` — alle geverifieerde API-feiten + PoC-resultaten
- `../Platform/` — **gedeelde platform-map (v1.6): koppelcontract-master (`contracten/`),
  besluitenregister (`besluiten/INDEX.md` — lees bij elke sessiestart!), registers (prefixen,
  schema-versies, entiteiten, conventies)**
- `docs/BESLISSINGEN.md` — **statusregister per feature/onderwerp (status + canonieke vindplaats)**
- `docs/BOUWPLAN.md` — fasering en definition of done per fase
- `verkenning/.env` — RLZ-credentials (BLOW + Universal Steigerbouw), NOOIT committen

## Werkwijze

- **`docs/BESLISSINGEN.md` is de verplichte eerste check vóór elk feature-voorstel of bouwstart**
  (pre-feature-ritueel, `Platform/WERKWIJZE.md` v1.7 — incl. de bindende
  bron-vs-realiteit-verificatie en de periodieke drift-audit): raadpleeg het register + de canonieke
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
- Tests verplicht op geldlogica (mapping, totalen, idempotentie, statusmachine) vóór UI-polish.
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
