# Bundelrun 24-09 — zeven open punten in één opdracht (Peter 24-09 "alles in 1 opdracht") — GEBOUWD

**Opdracht:** `opdrachten/gedaan/2026-09-24-bundelrun-vastly-pdf-tweelingen-odoo-taal-dearchiveren-odoo-doorbelasting-pdf-toets-bua-jaarrapport-activa-conventie.md`
(+ integraal: `2026-09-24-BUG-dearchiveren-odoo-administratie-vraagt-reeleezee-login.md`, `2026-09-23-BUG-vraag-thread-opent-kassarapport-in-inkoopscherm.md`,
`2026-09-23-BUG-samenvoegen-vinkje-weg-als-scan-geen-regelbedragen-heeft.md`). Handmatige CC-sessie (Peter), coördinator + zeven parallelle bouwagenten (fork,
eigen test-DB per agent, hot files door de coördinator). Geen migratie in enig blok. Niets in productie gedearchiveerd of gewijzigd; élke nazorg-CLI dry-run-default.
**Bronnen gelezen:** LEESPLICHT (sectie "Gelezen regels"), `docs/gesprekken/2026-09-23.md` + `2026-09-24.md`, `Platform/WERKWIJZE.md` v1.18.

## Uitkomst in één alinea
Alle zeven blokken zijn gebouwd en groen op de gouden set; per blok één commit (zie "Commits"). **Blok 1 (URGENT):** de oorzaak is ónze
bundeling, niet Vastly en niet deploy 0171 — Vastly-UBL's dragen geen ingesloten PDF (hash-regel kan nooit matchen) en heten `…-ubl.xml`
(stam-regel matcht niet); het job-log bewijst hetzelfde patroon al op 31-08. Fix: stam-normalisatie + factuurnummer-regel bij intake,
nazorg-CLI voor de 23 PDF's (dry-run default, geboekt UBL → PDF als RLZ-bijlage), bevinding `ubl_pdf_ongebundeld` mét knop "Bundelen".
**Blok 2:** `lang: nl_NL` op élke Odoo-call; namen volgen bij de eerstvolgende sync. **Blok 3:** dearchiveren is backend-bewust via de port —
Odoo zonder loginvelden. **Blok 4 (lees-only):** RLZ legt op de Lusso-verkoop én de Molenhof-spiegel 6.024,14 vast, de motor boekte 6.024,15
→ uitkomst B (onze regelsom wijkt af); fix pas ná Peters akkoord, lees-only telinstrument gebouwd. **Blok 5:** BUA-jaarrapport (CLI + blok +
bevinding vanaf 1-12) i.p.v. kenmerk. **Blok 6:** afschrijvingsrekening = kostenrekening mét dezelfde omschrijving. **Blok 7:** documentlink
volgt de soort (17 plekken, één functie, redirect) en het samenvoegen-vinkje komt uit de opgeslagen regels. **Werkt in productie: voor élk
blok NIET GEMETEN** (deploy volgt op de push; zes dispatch-onderdelen + één vervolg-opdracht `niet vóór: 2026-09-25 07:15`).

## Productie-lees-toegang in deze run (feit)
De leesreplica was vanaf dit netwerk onbereikbaar (`cloud-sql-proxy`: TCP 3307 naar 34.6.111.253 geweigerd — zelfde blokkade als 08-09) en
`db-lezen --sql --als` op de job-image weigerde `p.nijenhuis@kempengroep.nl` én `peter@ak-nijenhuis.nl` ("is geen actieve Beheerder"). Gebruikt:
Cloud Logging (intake-job-log per bericht/bijlage), `rlz-lezen` (Receipts KF + Molenhof Verhuur) en de Vastly-golden-UBL's in `Platform/uitwisseling`.
Drie nieuwe bibliotheek-queries dienen als meetlat zonder `--als`: `documenten-open`, `administratie-stand`, `grootboek-taal` (`tests/lezen/test_lezen.py`).

## Blok 1 — Vastly-PDF-tweelingen: bundeling faalt sinds 23-09 (URGENT, 23 documenten) — CODE (b)(c)(d)

**Oorzaak (a):** zie de sectie (a) hieronder — onze bundeling (stam-regel kent het `-ubl`-suffix niet; Vastly-UBL's dragen geen ingesloten PDF), niet Vastly en niet deploy 0171  · **OPEN_ITEM (e):** n.v.t. — geen Vastly-afwijking (koppelcontract §2d eist geen ingesloten PDF); suggestie in de aangrenzende gaten

### (a) Oorzaak aan het échte bericht (lees-only: Cloud Logging job-log `rlz-intake-imap`, 23-09 20:10–20:30 UTC + 31-08 14:10 UTC; Vastly-golden-UBL's in `Platform/uitwisseling/`)

**Kanaal/job:** de Vastly-batch van 23-09 kwam binnen via het postvak `facturen` (job `rlz-intake-imap`, ak-nijenhuis), niet via
`facturen_kempengroep`. Per bericht twee bijlagen: `factuur-XXX-2026-NNNN.pdf` + `factuur-XXX-2026-NNNN-ubl.xml`. Het job-log toont per
bericht letterlijk `…pdf=verzamelbak, …-ubl.xml=toegewezen` — de PDF is NIET gebundeld en ging als losse bijlage de AI-route in
(verzamelbak op 20:1x omdat de AI-maandlimiet toen dicht stond; daarna als inkoopfactuur toegewezen — de 23 tweelingen):
ARV-2026-0025/26/27 (3), MEY-2026-0025/26/27 (3), JGM-2026-0036/0041 (2) + JGM-0038/0039 (PDF én UBL beide "toegewezen" = dubbel document),
RUB-2026-0025…0034 (10), STI-2026-0010/11/12 (3), INP-2026-0025 (PDF om 20:20:40 alléén + om 20:20:43 opnieuw mét UBL → dubbel).

**Waarom de bundeling faalde — twee bewezen feiten:**
1. **Geen ingesloten PDF in de Vastly-UBL** → de hash-regel (stap 1) kan nooit matchen. Alle Vastly-golden-UBL's (`factuur-380-golden-*.xml`,
   `creditnote-381-golden-*.xml`) dragen 0 × `EmbeddedDocumentBinaryObject`; `cac:AdditionalDocumentReference` bevat alleen de markering
   `VASTLY-VERKOOP` (+ `cbc:ID` factuurnummer). Koppelcontract §2d schrijft "PDF + NLCIUS-UBL als twee bijlagen" voor en eist géén
   ingesloten PDF → **geen Vastly-afwijking, geen contractbreuk** → (e) OPEN_ITEM niet van toepassing (wél een suggestie, zie aangrenzende gaten).
2. **Naamstam ongelijk** → de stam-regel (stap 2) faalt op het `-ubl`-suffix (`factuur-RUB-2026-0031` ≠ `factuur-RUB-2026-0031-ubl`).

**Niet 0171, niet Vastly-gewijzigd:** de Elissen-batch van 31-08 (`factuur-JGM-2026-0032/33/34`) toont in het job-log exact hetzelfde
patroon (`pdf=verzamelbak, -ubl.xml=toegewezen`); "Elissen 31-08 wél gebundeld" was het resultaat van de nabundel-nazorg/handmatig
"Samenvoegen" ná intake, niet van de bundeling zélf. De bundeling heeft voor Vastly-mails dus nooit bij intake gewerkt sinds Vastly de
`-ubl`-naamgeving gebruikt. De fix (b) — stam-normalisatie + factuurnummer-regel — dekt beide feiten; (c) herstelt de 23 (+ de dubbele
paren JGM-0038/0039/INP-0025 als zij als tweeling kwalificeren); (d) meldt nieuwe gevallen dagelijks.

### Gebouwd
- **(b) `app/intake/bundeling.py`** — stap 2 "naamstam" vergelijkt sinds 24-09 de GENORMALISEERDE stam: een suffix `-ubl`/`_ubl`/
  `-xml`/`_xml` (hoofdletterongevoelig, alleen als staart van de stam) wordt aan beide kanten gestript (`genormaliseerde_stam`:
  `factuur-RUB-2026-0031-ubl.xml` ≡ `factuur-RUB-2026-0031.pdf`); ondubbelzinnigheid blijft de eis (twee PDF's met dezelfde stam =
  geen paar). Nieuwe stap 3 `REDEN_FACTUURNUMMER`: het UBL-`cbc:ID` (≥ 4 tekens, `ubl_factuurnummer` via `parseer_ubl_factuur`) staat
  tekstueel in de PDF-bestandsnaam óf in de PDF-tekstlaag (pypdf, `normaliseer_tekst` = witruimte weg + casefold, één lees per PDF
  gecachet) én er is precies één zo'n PDF (meerdere = log + geen paar). Volgorde hash → stam → factuurnummer → ingesloten-alleen.
  Module-docstring bijgewerkt. Publieke helpers: `genormaliseerde_stam`, `normaliseer_tekst`, `ubl_factuurnummer`,
  `pdf_tekstlaag_genormaliseerd`, `pdf_draagt_factuurnummer`.
- **(c) `app/intake/tweelingen_herstel.py`** (nieuw) + CLI `vastly-pdf-tweelingen-herstel [--dry-run] [--uitvoeren]
  [--administratie <uuid|naamdeel>]` (register/dispatch in `app/cli.py`; **dry-run is de default**, `--uitvoeren` schrijft, beide =
  exit 2). Eén kandidaten-motor `kandidaten_voor_administratie` (per administratie in eigen `scoped_session(aid)`): losse INKOOPFACTUUR-
  PDF (te_controleren/handmatig_afmaken/klaar_om_te_boeken, bron e-mail, geen beeld, geen samenvoeg-verwijzing) × VERKOOPFACTUUR-UBL
  (.xml, niet terminaal) uit hetzelfde intake-bericht (zonder bericht: zelfde kalenderdag én beide zonder bericht), match op
  genormaliseerde stam óf factuurnummer (bestandsnaam/tekstlaag); precies één UBL per PDF én één PDF per UBL, anders `twijfel` mét
  reden (zichtbaar overgeslagen). Herstel `herstel_een`: het UBL-document blijft HET document — PDF wordt zijn beeld
  (`bron_opslag_pad`/`bron_bestandsnaam`/`bron_content_type`, `beeld.bepaal_beeld` toont 'm met herkomst bron), PDF-document →
  `samengevoegd` mét `samengevoegd_in_id` via `_schrijf_overgang` (statusmachine + tijdlijn + audit), tijdlijnregel op de UBL-kant,
  audit `gebundeld_achteraf` op BEIDE rijen (één correlatie-id); is het UBL-document GEBOEKT (`verkoop_boeking` status geboekt) dan
  ná de commit de PDF als extra RLZ-bijlage via `zorg_voor_bijlage(client, "SalesInvoices", verkoop_rlz_id, upload_id=uuid5,
  op_bestandsnaam=True)` — bijlage-fout = uitkomst `gebundeld_bijlage_mislukt` mét reden (lokaal blijft gebundeld, niets half),
  Odoo-administratie = bijlage overgeslagen mét reden. Poorten worden in de transactie opnieuw getoetst (status, beeld, verwijzing).
  Idempotent: tweede run 0 kandidaten. Uitvoer: regel per paar, telling per administratie, `TOTAAL: N kandidaten, G gebundeld,
  O overgeslagen, M mislukt — DRY-RUN/UITGEVOERD`; exit 1 alleen bij `mislukt`.
- **(d) reconciliatie** — soort `ubl_pdf_ongebundeld` (blok `documenten`, `sinds` 24-09, `default=METEN`) in `soort_stand.py`;
  leesbare tekst in `teksten.py` (titel "Losse PDF hoort bij een verkoopfactuur · ‹pdf›", wat noemt UBL + basis + "al geboekt",
  doe = "Klik 'Bundelen'"); productie in `app/documenten/reconciliatie.py::_ongebundelde_tweelingen` (beide takken van
  `reconcilieer_administratie`, lees-only, lokaal — géén RLZ-call; dezelfde kandidaten-motor; alleen eenduidige paren); detail draagt
  `document_id`, `ubl_document_id`, `bestandsnaam`, `ubl_bestandsnaam`, `match_basis`, `factuurnummer`, `ubl_geboekt`,
  `document_status`; deeplink = bestaand `_doel_pad` (controlescherm van de PDF). Actie **"Bundelen"**: route
  `POST /reconciliatie/documenten/{document_id}/bundelen` (`vereis_kantoorrol`, body `{administratie_id}`; scope-toets;
  200 `{document_id, ubl_document_id, status, match_basis, rlz_bijlage, doel_pad=/verkoop/<adm>/<ubl>}`, 404 geen paar, 409
  twijfel/intussen verwerkt, 403 buiten scope, 422 mislukt) = `bundel_vanuit_bevinding` → exact `herstel_een` mét MENS-actor;
  frontend `frontend/src/reconciliatie/BundelenActie.tsx` (`isUblPdfOngebundeld`, knop `Button` teal, fout als `role=alert`,
  ná succes link "Naar de verkoopfactuur →") geregistreerd in `ReconciliatieScreen.tsx` vóór de kassarapport-actie.
- Endpoint-gate-guard: `tests/security/test_rol_endpoint_gates.py` kent de nieuwe route (kantoorrol).

### Tests (uitkomsten letterlijk)
- `tests/intake/test_bundeling_stam_factuurnummer.py` (12) + `tests/intake/test_bundeling_en_samenvoegen.py` (13): `25 passed in 15.26s`
  (suffix-stam, hele batch van 3 nummers, twee kandidaten = twijfel, cbc:ID via bestandsnaam én via tekstlaag (`maak_tekst_pdf`),
  te kort nummer paart nooit, oud gedrag hash/stam ongewijzigd).
- `tests/intake/test_tweelingen_herstel.py` (17): `17 passed in 12.69s` — kandidaten (stam, factuurnummer, twijfel bij twee PDF's,
  ander bericht/upload-bron = geen kandidaat), dry-run schrijft niets, échte run (beeld + samengevoegd + tijdlijn beide kanten + audit
  beide rijen + `bepaal_beeld` = bron + idempotent), geboekt UBL → `FakeBoekClient.uploads` op de verkoop_rlz_id mét
  `upload_id_voor(pdf)`, bijlage-fout zichtbaar mét bundeling intact, intussen verwerkt = overgeslagen, soort in meten + tekst,
  documenten-blok → bevinding → `GET /reconciliatie/bevindingen?soort=meten` → `POST …/bundelen` 200 (mens-actor in audit) →
  tweede POST 404 → volgende toets leeg, 409 twijfel + 403 buiten scope, CLI-vormen letterlijk (`vastly-pdf-tweelingen-herstel`,
  `--dry-run`, `--dry-run --administratie <naam>`, `--uitvoeren --administratie <uuid>`, `--uitvoeren`, beide = 2).
- Gouden set + guards: `tests/keten/test_b_g_floor_ubl_plus_pdf.py` (nieuwe klasse `TestVastlySuffixStam`: Floor-UBL als
  `…-ubl.xml` zónder ingesloten PDF + losse PDF → `gebundeld (naamstam)`, 0 AI-calls, één werkstuk), `tests/unit/test_keten_guard.py`,
  `tests/reconciliatie/test_soort_stand.py`, `test_teksten.py`, `tests/security/test_rol_endpoint_gates.py`: `581 passed in 243.58s`.
- Buren: `test_nabundelen`, `test_verwerking`, `test_golden_cases_vastly`, `test_intussen_extern_geboekt`, `test_run`,
  `test_kantoorbreed`, `test_cli_smoketest`, `tests/documenten/test_reconciliatie.py`: `164 passed in 108.85s`.
- Vitest `BundelenActie.test.tsx` (3) + `ReconciliatieScreen.test.tsx`: `2 files, 17 passed`; `tsc -b` zonder fouten in mijn bestanden.
- Volledige suite/keten-sweep: coördinator. Eigen test-DB `boekhouding_test_a2`.

### Meetrecept ná deploy (dispatch-onderdeel `vastly-tweelingen`) — werkt in productie: **niet gemeten**
1. `scripts/gcp/nameting.sh vastly-pdf-tweelingen-herstel --dry-run` (job-image, lees-only; allowlist-woord toevoegen, alleen mét
   `--dry-run`) → verwacht `TOTAAL: 23 kandidaten, 0 gebundeld, 0 overgeslagen` mét per administratie Rubicon 10 / Elissen 4 / ARVUM 3 /
   Meyer 3 / Shuto 3, één regel `(…, naamstam, geboekt)` voor RUB-2026-0031. Afwijking van 23 = eerst verklaren, dan pas de echte run.
2. Échte run ná Peters "ja": `gcloud run jobs execute rlz-reconciliatie --args="^|^-m|app.cli|vastly-pdf-tweelingen-herstel|--uitvoeren"`
   (owner-sessie) → `TOTAAL: 23 kandidaten, 23 gebundeld`, RUB-0031 mét `[RLZ-bijlage: geüpload op SalesInvoices/…]`; daarna dry-run =
   0 kandidaten (idempotent). Controle RLZ: `nameting.sh rlz-lezen --administratie Rubicon --pad SalesInvoices --record-via-filter
   "Reference eq 'RUB-2026-0031'" --expand UploadList` (2 bijlagen).
3. `db-lezen --sql` (Beheerder): documenten `status='samengevoegd'` mét audit `gebundeld_achteraf` = 23 × 2 rijen; werkvoorraad-tellers
   van de vijf administraties −23.
4. Reconciliatie: run van 25-09 06:30 → 0 × `ubl_pdf_ongebundeld` (ná de herstelrun) óf N × in facet "in meting" (vóór de run); de
   `Bundelen`-route in het request-log (`httpRequest.requestUrl:"/bundelen"`) 200/404/409/5xx.
5. Eerste Vastly-batch ná deploy (november-facturen): `intake_bericht.detail.bijlagen` toont per PDF `gebundeld … (naamstam)`.

### Klikpunten Peter
- "ja" voor de échte herstelrun (23 PDF's, waarvan 1 bij een al geboekt UBL: RUB-2026-0031, Rubicon, verkoop 23-09 — bron-id/bedrag
  uit de dry-run-uitvoer van stap 1).

### Aangrenzende gaten
1. Lifecycle: ongedaan maken van `gebundeld_achteraf` bestaat niet (de nabundel-ongedaan-route kent alleen zijn eigen sleutel) — een
   verkeerde bundeling terugdraaien = Beheerder via de bestaande "samenvoegen-ongedaan"-route NIET mogelijk; voorstel: aparte
   ongedaan-route pas als het zich voordoet (nooit verwijderen; de PDF-rij + bestand blijven bestaan).
2. Consistentie: de intake-bundeling (b) en de nazorg (c) gebruiken dezelfde stam-normalisatie en factuurnummer-toets; de
   nabundel-motor (`nabundelen.py`, verzamelbak-UBL ↔ toegewezen PDF) gebruikt nog de exacte stam — bewust ongewijzigd (andere casus,
   inkoop), kandidaat voor dezelfde normalisatie.
3. UX: de bevinding start in `meten` (facet "in meting", geen actiemail) — promotie naar `actie` ná de eerste productiemeting.
4. Compliance: geen RLZ-write behalve de bijlage-upload op een al geboekt verkoopdocument (idempotent op bestandsnaam); niets verwijderd.

### Gewijzigde/nieuwe bestanden
`backend/app/intake/bundeling.py` (M), `backend/app/intake/tweelingen_herstel.py` (nieuw), `backend/app/cli.py` (M: register/dispatch),
`backend/app/reconciliatie/soort_stand.py` (M), `backend/app/reconciliatie/teksten.py` (M), `backend/app/reconciliatie/schemas.py` (M),
`backend/app/reconciliatie/router.py` (M), `backend/app/documenten/reconciliatie.py` (M), `backend/tests/intake/test_bundeling_stam_factuurnummer.py`
(nieuw), `backend/tests/intake/test_tweelingen_herstel.py` (nieuw), `backend/tests/keten/test_b_g_floor_ubl_plus_pdf.py` (M),
`backend/tests/security/test_rol_endpoint_gates.py` (M), `frontend/src/reconciliatie/BundelenActie.tsx` (nieuw),
`frontend/src/reconciliatie/BundelenActie.test.tsx` (nieuw), `frontend/src/reconciliatie/ReconciliatieScreen.tsx` (M).

## Blok 2 — Odoo: grootboeknamen Engels in de module (Bonte Hoeve) → taal-poort `lang: nl_NL`

**Oorzaak (bevestigd in code):** `app/odoo/client.py::OdooClient.call` gaf uitsluitend `context.allowed_company_ids` mee; Odoo levert vertaalbare velden (`account.account.name`, dagboek-, product- en btw-namen) dan in de standaardtaal van de API-gebruiker (en_US). Onze caches (`platform.grootboekrekening`, `taxrate_cache`, …) toonden daardoor Engelse namen terwijl de Odoo-UI van de klant NL toont. Geen data-wijziging in Odoo nodig.

**Gebouwd (geen migratie):**
- `backend/app/odoo/client.py` — constante `ODOO_TAAL = "nl_NL"`; `call()` zet `context.lang = ODOO_TAAL` op ÉLKE lees- én schrijfcall naast `allowed_company_ids`; een expliciet meegegeven `context.lang` wint; `versie()` (auth-loos `/web/webclient/version_info`) blijft zonder context. Docstring: ontwerpregel TAAL-POORT.
- `backend/tests/odoo/test_client.py` — `TestTaalPoort` (3 tests): search_read/read/search_count/create/write/fields_get/call dragen alle `lang == nl_NL` én company; expliciete `en_US` wint; `versie()` zonder context. Bestaande test "eigen context wordt samengevoegd" ongewijzigd groen.
- Hersync: GEEN nieuwe motor. De nachtelijke `sync-alles` (job `rlz-sync`, `app/sync/service.py::sync_alle_administraties` → `_odoo_sync` → `app/odoo/sync.py::sync_alles_voor_odoo_administratie`) overschrijft `naam` via `_upsert_en_markeer_verdwenen` (bewezen in test). Voor een hersync op verzoek zonder op de nacht te wachten: **nieuwe CLI-alias** `odoo-stamgegevens-sync (--administratie <uuid|naamdeel> | --alles) [--dry-run]` (`backend/app/odoo/sync_cli.py`, geregistreerd in `app/cli.py`) die uitsluitend de bestaande eerste-sync-route `app/odoo/service.py::eerste_sync` aanroept (sync-run-rij zichtbaar op de detailpagina, zelfde als "Sync opnieuw starten"). Schrijvend → NIET in de nameting-allowlist; `--dry-run` doet geen Odoo-call.
- `backend/tests/odoo/test_taal_hersync.py` (5 tests): Engelse cache-naam "Account Receivable" → hersync mét NL-respons → "Debiteuren" (bijgewerkt=1, aangemaakt=0, verdwenen=0); CLI-parser kent élke argumentvorm uit het meetrecept; dry-run zonder sync; echte run via `eerste_sync` → run-rij `klaar`; onbekende/niet-eenduidige administratie = exit 2.

**Tests (eigen DB a3):** `tests/odoo/test_client.py tests/odoo/test_taal_hersync.py tests/migratie/test_odoo_doel.py tests/beheer/test_administratienaam.py tests/unit/test_cli_smoketest.py` → groen (99 passed in de gecombineerde run). Rood maar NIET van dit blok: `tests/odoo/test_router.py::TestFailsafeDubbeleKoppeling::test_laag3_verbinding_testen_draagt_reden_en_rlz_signaal` — assert op het exacte `GevondenCompanyDto`-dict, blok 3 voegde een veld toe aan `app/odoo/schemas.py` (coördinator: test-dict aanvullen in blok 3). Tijdens de run was `app/documenten/vragen.py` even niet importeerbaar (blok 7a mid-edit).

**Wat archiveren/naam-volgen NIET raakt:** archiveren van een Odoo-administratie trekt geen credential in (alleen RLZ) en raakt de caches niet; `naam_bron`/administratienaam volgt `res.company.name` (0144) en is onafhankelijk van de rekeningnamen; `odoo_rekening_mapping` (RLZ-code ↔ Odoo-account) blijft op code/id en verandert niet door een andere weergavenaam. Het boekingsgeheugen en de mapping lezen id's, niet namen.

**Werkt in productie: niet gemeten.** Meetrecept (dispatch-onderdeel `odoo-taal`, zie `$S/nameting_blok2.txt`):
1. Vóór/ná: `scripts/gcp/nameting.sh db-lezen --sql "<Q>" --als peter@ak-nijenhuis.nl --administratie "Bonte Hoeve"` mét
   `Q = select g.code, g.naam, g.laatst_gesynchroniseerd from platform.grootboekrekening g join platform.administratie a on a.id = g.administratie_id where a.naam ilike '%Bonte Hoeve%' and g.verdwenen_uit_bron_op is null order by g.code`
   en de telling `select count(*) filter (where g.naam ~* '(Receivable|Payable|Expenses|Revenue|Bank|Cash|Equity|Tax)') as engels, count(*) as totaal from platform.grootboekrekening g join platform.administratie a on a.id = g.administratie_id where a.naam ilike '%Bonte Hoeve%' and g.verdwenen_uit_bron_op is null` (géén `|`-teken in de query zelf buiten de regex — let op: de regex-alternatie gebruikt `|`; nameting.sh splitst `--args` op `^|^` → gebruik daarom in de workflow de variant met `similar to` of losse `ilike`-termen, zie nameting_blok2.txt).
2. Ná deploy: hersync Bonte Hoeve op de job-image (schrijvend, Peters "ja"): `gcloud run jobs execute rlz-sync --region europe-west4 --args="^|^-m|app.cli|odoo-stamgegevens-sync|--administratie|Bonte Hoeve"` (eerst `…|--dry-run`), óf wachten op `sync-alles` van 07:00; daarna stap 1 opnieuw → verwacht: `engels = 0`, `laatst_gesynchroniseerd` ≥ deploy-moment, en Cloud Logging job `rlz-sync` regel `OK <id>: ledgers=…bijgewerkt=N…` voor de drie Odoo-administraties.
3. Oordeel: "werkt in productie: ja" als de telling `engels` van > 0 naar 0 gaat bij gelijk `totaal`.

**Klikpunten:** geen (de hersync-executie is een owner-commando ná deploy; vervolg-opdracht `niet vóór:` deploy + 1 u door de coördinator).

**Aangrenzende gaten:** (1) lifecycle — btw-namen (`taxrate_cache.naam`) en crediteur-/projectnamen volgen dezelfde sync en worden mee-vertaald; de `odoo_id_koppeling.naam`-kolom (label "code naam") wordt in `_schrijf_id_koppelingen` óók herschreven bij de sync → geen achterblijver; (2) consistentie — `CompanyGepindeClient` (VGG-migratie) erft `call()` en krijgt de taal-poort mee, de pin-toets kijkt alleen naar `allowed_company_ids` (tests groen); (3) UX — geen schermwijziging; de chip "in Odoo heet deze rekening nu …" bestaat niet (namen zijn cache, geen mens-invoer); (4) compliance — geen.

## Blok 3 — Dearchiveren Odoo-administratie vraagt Reeleezee-login (BUG Peter 24-09, Recreatief Vastgoed Nederland)

**Opdracht** `opdrachten/inbox/2026-09-24-BUG-dearchiveren-odoo-administratie-vraagt-reeleezee-login.md` integraal uitgevoerd (punten 1–6).
Casus: companies 13 "Recreatief Vastgoed Nederland B.V." (actief) en 11 "… BV." (gearchiveerd) op universal-steigers.odoo.com; module-administraties
`8ea9d28b-e743-4566-96d7-bb7d81531368` (company 13) en `59bf1f7f-7460-4b04-bb27-b131691ccdf6` (company 11), beide 24-09 gearchiveerd; herkoppelen op 13
terecht 409 (claim), maar dearchiveren eiste een Reeleezee-webservice-login die een Odoo-administratie niet heeft — de enige aangewezen weg was dood.

**Oorzaak.** Archiveren/dearchiveren (v2 30-08) dateert van vóór de Odoo-backend (blok E 03-09): `dearchiveer_administratie` riep rechtstreeks
`onboarding.probe_nieuwe_login(rlz_admin_id=…)` aan (sentinel `odoo:<host>:<company>` kent geen webservice-login) en de dialoog toonde voor élke rij de
Reeleezee-tekst + loginvelden. Besluit 0016 geschonden in de andere richting: het domein kende maar één backend.

**Gebouwd (geen migratie).**
1. Port + registry: `app/backends/port.py` `HeractiveerPort` (Protocol) + `HeractiverenGeweigerd(bericht, rapport)`; `app/backends/registry.py::heractiveer_port_voor(administratie_id)` op `boekhoud_backend` (archiveren wijzigt die sleutel niet).
   - `app/backends/rlz_heractiveer.py` `RlzHeractiveerPort` = exact het oude gedrag (login verplicht → 422 "vereist een nieuwe webservice-login", admin-pin + rechten-probe + herprobe via `probe_nieuwe_login`, credential in de store, probe op de credential). Bestaande tests `test_archivering.py` ongewijzigd groen.
   - `app/odoo/heractiveer.py` `OdooHeractiveerPort`: meegegeven login = 422 "Een webservice-login is niet van toepassing voor een Odoo-administratie …"; bestaande `OdooKoppeling` + versleutelde sleutel via `odoo_client_voor` (company-poort) opnieuw geprobed (`voer_probe_uit`), `res.company` van de gebonden company terug-gelezen == `koppeling.company_id`; groen → `probe_rapport`/`probe_op`/`company_naam` bijgewerkt; rood → 422 mét rapport, mismatch → 422 "Odoo geeft company N terug waar de koppeling company M verwacht — niets gewijzigd".
   - `app/beheer/service.dearchiveer_administratie(*, actor_id, administratie_id, webservice_username=None, wachtwoord=None, client=None)`: poorten (bestaat / gearchiveerd) → `port.heractiveer_probe(…)` → generiek `actief=True`, `gearchiveerd_op/door=None`, audit `administratie_gedearchiveerd` mét `nieuwe_waarde.backend` (rlz|odoo) + `probe_rapport`.
2. Router `POST /instellingen/administraties/{id}/dearchiveren`: body optioneel (`DearchiverenDto`, beide velden optioneel); `HeractiverenGeweigerd` → 422 `{bericht, rapporten: {<administratie_id>: rapport}, meldingen}` (zelfde vorm als OnboardingFout); 409 niet gearchiveerd, 404 onbekend, Beheerder-only ongewijzigd.
3. Frontend `AdministratiesV2.tsx`: op `boekhoud_backend === 'odoo'` geen loginvelden, tekst "De Odoo-koppeling wordt opnieuw geprobed; company ‹odoo_company_id› moet ongewijzigd terugkomen. De opgeslagen API-sleutel wordt hergebruikt — er is geen webservice-login nodig.", knop "Dearchiveren", melding "… teruggezet — de Odoo-koppeling is opnieuw geprobed (groen), de opgeslagen API-sleutel is hergebruikt."; `instellingenApi.dearchiveerAdministratie(id, login?)` stuurt bij Odoo `{}`.
4. Archiveren Odoo (besluit): `trek_credential_in` raakt alleen de RLZ-credential; de `OdooKoppeling` mét versleutelde API-sleutel BLIJFT staan (nodig voor 1; gearchiveerd ≠ verwijderd; de sleutel is nooit uitleesbaar). Zichtbaar: `ArchiveringResultaat(Dto).odoo_sleutel_behouden` (default False) + melding in `ArchiveerDialog` "Odoo-API-sleutel blijft versleuteld bewaard voor dearchiveren".
5. Wizard-guard: `CompanyClaim.wizard_label()` geeft voor een gearchiveerde claim "gearchiveerd — dearchiveer ‹naam›"; `GevondenCompany(Dto).gearchiveerd: bool`; wizard-rij grijs/uitgeschakeld mét title "… dearchiveer die via Instellingen › Administraties › gearchiveerd; nooit een tweede koppeling".

**Tests.**
- `backend/tests/beheer/test_dearchiveren_odoo.py` (10): archiveren Odoo laat sleutel staan + `odoo_sleutel_behouden`; RLZ False; dearchiveren Odoo groen zonder login (actief terug, probe_op vers, 0 RLZ-credentials, client gesloten, audit backend odoo + rapport); company-mismatch = niets gewijzigd; rode probe = niets gewijzigd + rapport; login meegegeven = "niet van toepassing" zonder probe; RLZ zonder login = "vereist een nieuwe webservice-login"; route Odoo body→422 / leeg→200 / nog eens→409; route RLZ leeg→422 + boekhouding 403; `wizard_label` gearchiveerd; `test_verbinding` geeft `gearchiveerd` mee.
- Aangepast: `tests/odoo/test_router.py` (DTO-veld `gearchiveerd: False` in de exacte vergelijking).
- Uitkomst (`pytest_blok.sh a4`): `test_dearchiveren_odoo.py test_archivering.py test_router.py::TestFailsafeDubbeleKoppeling test_probe.py test_optin_afwezig_pad_guard.py` → **71 passed**; `tests/security/test_rol_endpoint_gates.py tests/beheer/test_router.py test_onboarding.py test_service.py` → **587 passed** (4:01).
- Vitest: `InstellingenScreen.test.tsx` (+1: Odoo-dialoog zonder loginvelden, tekst company 13, knop "Dearchiveren", body zonder login, melding), `OdooKoppelWizard.test.tsx` (+1: company 13 grijs "gearchiveerd — dearchiveer …", title), `AdministratiesV2.test.tsx` → **72 passed (3 files)**; `tsc -b` schoon (op het moment van meten).
- Ruff: nieuwe/geraakte bestanden schoon (pre-existing E501 in `rlz_inkoop.py`/`router.py:911`/`schemas.py:221` niet aangeraakt).

**Werkt in productie: niet gemeten** (niets in productie gedearchiveerd — regel opdracht). **Meetrecept ná deploy (Peter/Cowork):**
1. Instellingen › Administraties › filter "gearchiveerd" → rij "Recreatief Vastgoed Nederland B.V." (`8ea9d28b…`) → "Dearchiveren…" → dialoog zonder loginvelden ("company 13 moet ongewijzigd terugkomen") → "Dearchiveren" → melding groen. `59bf1f7f…` (company 11, in Odoo gearchiveerd) NIET dearchiveren.
2. Nameting (dispatch-onderdeel `dearchiveren-odoo`, zie `nameting_blok3.txt`): request-log `POST …/instellingen/administraties/*/dearchiveren` sinds de deploy (200 = teruggezet, 422 = geweigerd mét reden, 5xx = rood) + `db-lezen` op `platform.administratie` × `odoo_koppeling` voor beide Recreatief-administraties (`actief`, `gearchiveerd_op`, `probe_op`, `company_id`) + audit `administratie_gedearchiveerd` mét `backend=odoo`. Verwacht: 8ea9d28b actief/probe_op ≥ deploy/company 13; 59bf1f7f gearchiveerd; `company_claims` toont 13 → 8ea9d28b (actief) en 11 → 59bf1f7f (gearchiveerd — label "gearchiveerd — dearchiveer …" in de wizard).
3. Daarna sync-alles groen voor 8ea9d28b (Odoo-stamgegevenssync draait weer omdat `actief` true).

**Klikpunten Peter:** dearchiveren `8ea9d28b-e743-4566-96d7-bb7d81531368` (company 13, "Recreatief Vastgoed Nederland B.V.", gearchiveerd 24-09, 0 account.move) via de nieuwe dialoog ná deploy; `59bf1f7f-7460-4b04-bb27-b131691ccdf6` (company 11, 0 account.move) blijft gearchiveerd (in Odoo óók gearchiveerd).

**Aangrenzende gaten.**
- lifecycle: verwijderen bestaat niet (archiveren, nooit verwijderen — ongewijzigd); een Odoo-koppeling waarvan de API-sleutel in Odoo is ingetrokken → probe rood → 422 mét rapport, herstel = "API-sleutel wijzigen" op de detailpagina (bestaand `wijzig_koppeling`) — dat pad eist `backend odoo` en werkt ook op een gearchiveerde administratie (koppeling_voor filtert niet op actief) — niet apart getest; dearchiveren van een RLZ-administratie mét alleen-lezen Odoo-leesbron volgt het RLZ-pad (backend rlz) — correct, de leesbron-koppeling blijft staan.
- consistentie: `company_claims`/`CompanyClaim.reden` (409-tekst) noemde "dearchiveer die administratie" al — nu klopt de weg; `wizard_label` sluit aan; DTO additief (`gearchiveerd`, `odoo_sleutel_behouden`) — `proxy-prefixes` ongewijzigd (bestaande route).
- UX/branding: dialoogtekst noemt het company-id uit de lijst-DTO (`odoo_company_id`); zonder company-id (halve stand zonder koppeling-rij) staat er "‹onbekend›" en geeft de server 422 "geen (volledige) Odoo-koppeling … koppel opnieuw via 'Odoo koppelen…'".
- compliance: audit `administratie_gedearchiveerd` draagt nu `backend` + probe-rapport (geen sleutel, geen wachtwoord); Odoo-sleutel reist nooit terug; 422-detail draagt alleen het rapport.

**Gewijzigde/nieuwe bestanden (blok 3):** `backend/app/backends/port.py`, `backend/app/backends/registry.py`, `backend/app/backends/rlz_heractiveer.py` (nieuw), `backend/app/odoo/heractiveer.py` (nieuw), `backend/app/beheer/service.py` (dearchiveer + ArchiveringResultaat.odoo_sleutel_behouden), `backend/app/beheer/router.py` (dearchiveren-route + archiveren-DTO-veld), `backend/app/beheer/schemas.py` (`DearchiverenDto`, `ArchiveringResultaatDto.odoo_sleutel_behouden`), `backend/app/odoo/service.py` (wizard_label gearchiveerd, GevondenCompany.gearchiveerd), `backend/app/odoo/schemas.py`, `backend/app/odoo/router.py`, `backend/tests/beheer/test_dearchiveren_odoo.py` (nieuw), `backend/tests/odoo/test_router.py` (1 regel), `frontend/src/api/types.ts` (ArchiveringResultaatDto), `frontend/src/instellingen/instellingenApi.ts`, `frontend/src/instellingen/AdministratiesV2.tsx`, `frontend/src/instellingen/ArchiveerDialog.tsx`, `frontend/src/instellingen/OdooKoppelWizard.tsx`, `frontend/src/instellingen/InstellingenScreen.test.tsx`, `frontend/src/instellingen/OdooKoppelWizard.test.tsx`.
Let op voor de coördinator: `backend/app/beheer/router.py`, `schemas.py`, `service.py`, `frontend/src/api/types.ts` en `instellingenApi.ts` zijn óók door andere blokken geraakt (bua_cli/odoo client) — hunks splitsen bij het committen.

## Blok 4 — Doorbelasting: factuur-PDF "onvolledig" door een cent-verschil (LEES-ONLY EERST; geen wijziging in geldlogica)

**Casus (Peter 24-09, screenshot):** KF → Molenhof Verhuur B.V., Lusso-Design 261004, € 4.741,55 + provisie € 237,08, chip "factuur
ontbreekt — factuur-PDF onvolledig: btw-som € 1.045,52, totaal incl € 6.024,15". De motor boekt de btw PER REGEL afgerond
(`geld.btw_over`: 4.741,55 × 21 % = 995,73 + 237,08 × 21 % = 49,79 = **1.045,52**, totaal 6.024,15); op factuur-niveau is 21 % × 4.978,63
= 1.045,5123 → **1.045,51**, totaal 6.024,14.

### (a) Lees-only meting op productie-RLZ (24-09, `nameting.sh rlz-lezen`, alleen GET — uitvoer in `.scratch`/rapport)
| Kant | RLZ-document | Datum | `TotalPayableAmount` / `BaseInvoiceAmount` | Status |
|---|---|---|---|---|
| Bron-inkoop Lusso (KF) | `RLZ-04-00004431`, Reference 261004 | 21-08-2026 | 5.737,28 (= 4.741,55 + 995,73) | 3 (betaald) |
| **Doorbelasting-verkoop KF → Molenhof Verhuur** | `RLZ-01-00002726`, Reference 24713312, Description "Lusso-Design Interior Projects B.V. 261004 — Factuur 261004 — Pakket Beige KC096 deelfactuur 910" | 21-08-2026 | **6.024,14** | 2 (open) |
| **Spiegel-inkoop bij Molenhof Verhuur** | `RLZ-04-00000614`, Reference 24713312 | 21-08-2026 | **6.024,14** (open 6.024,14) | 2 (open) |

**Uitkomst: B.** RLZ heeft op BEIDE documenten 6.024,14 vastgelegd = btw 1.045,51 (factuur-niveau), terwijl de module-boeking
(`doorbelasting_boeking.btw_bedrag`) 1.045,52 / 6.024,15 draagt. De PDF toont dus precies wat RLZ boekte; niet de render is
afwijkend, maar ónze regelsom. Nog niet gelezen: de regelbedragen van het RLZ-record (`SalesInvoices/{id}` — de collectie-`$expand`
`DocumentLineList` wordt door RLZ stil genegeerd, api-verkenning 2312/2405; het record-pad vraagt het volledige GUID dat de
anonimisering knipt) — dát leest het nieuwe instrument hieronder ná deploy. `TotalTaxAmount`/`TotalNetAmount` zijn op deze
Receipts-rijen `null` (geen btw-veld om op te vertrouwen — zelfde les als ManualJournals).

**Gevolgen (feiten, geen fix):** (1) de module-kolommen `netto_totaal/provisie_bedrag/btw_bedrag` en de `factuur_geboekt`-webhook
naar Vastly (regels mét per-regel `TaxAmount`) dragen 1 cent meer dan RLZ; (2) de bank-aflettering van de spiegel bij Molenhof
Verhuur zal 6.024,14 zoeken (RLZ = waarheid) — een betaling van 6.024,15 laat 1 cent open; (3) de cent-exacte PDF-toets faalt
structureel op élke doorbelasting mét ≥ 2 regels waarvan de per-regel-afronding afwijkt van de factuur-niveau-afronding → "factuur
ontbreekt" op de spiegel terwijl de boeking goed staat. **De melding is nu niet gewijzigd** (opdracht: (b)-B = fix pas ná akkoord).

### (b) Voorstel ná Peters akkoord (NIET gebouwd — geen geldlogica gewijzigd)
Uitkomst B → de doorbelastingsmotor moet boeken zoals RLZ vastlegt: btw per tarief over het subtotaal (één afronding, ROUND_HALF_UP),
verdeeld over de regels via grootste-rest-centen (`geld.verdeel_grootste_rest`), zodat Σ regel-btw = factuur-niveau-btw en de PDF-toets,
de webhook en de bankmatch cent-exact op RLZ aansluiten. Alleen in `app/doorbelasting/boeken.py`/`geld.py` (niet in de inkoop-`regelsom.py`
— daar is de per-regel-afronding bewust, factuur leidend). Bestaande boekingen: de kolommen op `doorbelasting_boeking` corrigeren is een
data-stap (dry-run-CLI) — alleen ná Peters "ja"; RLZ zelf hoeft niet aangeraakt (RLZ staat al goed). Vastly ontving 1 cent te veel in de
payload van elke geraakte doorbelasting: melden via Platform/OPEN_ITEMS zodra (c) de omvang geeft.

### (c) Kantoorbrede telling — instrument gebouwd, meting ná deploy
`doorbelasting-factuur-pdf-toets [--administratie <uuid|naamdeel>] [--referentie <tekst>] [--pdf] [--max N] [--json-uit]`
(`app/doorbelasting/factuur_pdf_toets.py`, LEES-ONLY, nameting-allowlist, dispatch-onderdeel `doorbelasting-pdf`): per administratie
in eigen RLS-scope élke `doorbelasting_boeking` mét `factuur_pdf_status = 'ontbreekt'` (of NULL, GEBOEKT/spiegel_open), geclassificeerd
op de reden: `onvolledig_cent` (alleen btw-som/totaal ontbreken én geboekt − factuur-niveau = ± 1 cent), `onvolledig_anders`
(KvK/btw-nummer/referentie of groter verschil), `render_mislukt`, `geen_pdf`, `onleesbaar`, `overig`; `--pdf` leest per boeking het
RLZ-record (regelsom `TaxAmount`) én de render (`Download`, Accept pdf) en zet geboekt / factuur-niveau / gevonden-in-PDF naast elkaar mét
de uitkomst A/B/compleet/onbekend. Alleen GET; niets geschreven (tests bewijzen 0 PUT's, status ongewijzigd).
De vrije-SQL-route (`db-lezen --sql --als`) was in deze run niet bruikbaar: de leesreplica is vanaf dit netwerk niet bereikbaar
(TCP 3307 geweigerd, zelfde blokkade als 08-09) en de job-route weigerde beide bekende Beheerder-adressen ("geen actieve Beheerder") →
klikpunt hieronder.

### (d) `make doorbelasting-facturen-herstel` NIET gedraaid (opdracht) — en zou ook niets herstellen: dezelfde toets faalt opnieuw.

**Tests:** `tests/doorbelasting/test_factuur_pdf_toets.py` — 17 passed (classificatie Lusso = cent-verschil, KvK/groot verschil = anders,
render/geen-pdf/onleesbaar/overig; PDF-tekst-toets A/B/compleet/onbekend; DB-meting op een échte 'ontbreekt'-boeking mét Lusso-bedragen:
zonder `--pdf` geen RLZ-call, mét `--pdf` uitkomst A op de fake-render, 0 PUT's, status ongewijzigd; referentie-filter; onbekende
administratie = exit 2; élke CLI-argumentvorm uit het meetrecept letterlijk; `cli.main` kent het commando).

**Werkt in productie: niet gemeten** (het instrument bestaat pas ná deploy). Meetrecept = dispatch-onderdeel `doorbelasting-pdf`:
`scripts/gcp/nameting.sh doorbelasting-factuur-pdf-toets --administratie "Kempen Facilities" --referentie 261004 --pdf --max 1` →
verwacht "klasse onvolledig_cent (verschil +1 ct)" en PDF/record-regel "regelsom-btw record 1045.52 · PDF bevat factuur-niveau=True →
A/B" (leest B als het record óók 1.045,51 draagt) + de kantoorbrede telling zonder `--pdf` → TOTAAL-regel per klasse (Peters vraag (c):
zijn het allemaal 1-cent-gevallen?). Vervolg-opdracht `niet vóór:` deploy + 30 min.

**Klikpunten Peter:** (1) akkoord op (b) — de doorbelastingsmotor op factuur-niveau-btw zetten (RLZ-vorm) + data-stap voor bestaande
boekingen; tot dan blijft de chip "factuur ontbreekt" staan op deze gevallen; (2) een actieve Beheerder-e-mail voor `db-lezen --sql --als`
op de job (de twee bekende adressen zijn in productie geen actieve Beheerder) — óf `POST /lezen/sql` als Beheerder vanuit de kantoor-web;
(3) Molenhof Verhuur RLZ-04-00000614 (21-08-2026, € 6.024,14 open) — bij betaling het RLZ-bedrag aanhouden, niet het module-/webhook-bedrag.

**Aangrenzende gaten:** lifecycle — een doorbelasting die ná (b) opnieuw wordt gestorneerd/herboekt volgt automatisch de nieuwe
afronding (geen aparte migratie); consistentie — de inkoop-`regelsom.py` (factuur leidend, per regel) blijft bewust anders dan de
doorbelasting (RLZ-verkoop = RLZ-render leidend); UX — de chip-tekst "lay-out/stamgegevens in de RLZ-UI aanvullen" is voor deze klasse
misleidend, herformuleren hoort bij (b) ("RLZ-factuur toont € 1.045,51, module boekte € 1.045,52 — cent-verschil per-regel-afronding");
compliance — de webhook-payload aan Vastly draagt voor deze klasse 1 cent te veel (OPEN_ITEM ná de telling).

## Blok 5 — BUA: jaareinde-rapport i.p.v. kenmerk (besluit Peter 24-09 "nee standaard 21 % btw aanhouden")

**Werkt in productie: niet gemeten** (lees-only instrument; meetrecept hieronder, dispatch-onderdeel `bua-jaarrapport`; de bevinding
`bua_correctie_open` is per definitie pas ná 1-12-2026 meetbaar). Geen migratie, geen datawijziging, geen kenmerk gezet.

### Gebouwd
1. **Lees-only CLI `bua-jaarrapport --jaar 2026 [--administratie <uuid|naamdeel>] [--rlz] [--json-uit]`** (`backend/app/beheer/bua_cli.py`,
   zelfde module en registratiepatroon als `bua-kandidaten`): per administratie in eigen RLS-scope de `bua-kandidaten`-set met per rekening
   categorie (`categorie_voor`: **BUA** = representatie/relatiegeschenken/personeel/horeca; **kantine** en **sponsoring — reclame** apart),
   kenmerk-stand, documenten, netto, afgetrokken btw. Bron (a) module = boekvoorstel-regels van GEBOEKTE inkoopfacturen op factuurdatum +
   bank-direct-geboekt (exact `kandidaten_voor`); (b) `--rlz` = per rekening `JournalEntryLines` uitsluitend GET, `$filter` alleen
   `Account/id eq <guid>` (geen int op een enum-veld — de FakeRlz-stub pint die vorm), `$expand=JournalEntry`, boekjaar client-side op
   `BookDate`, Σ Debit−Credit + Σ `VatAmount`, ≤ 10 × 200 regels; geen credential / Odoo / RLZ-fout = zichtbare regel "RLZ-kant: niet
   gemeten (…)", nooit een fout. Kolom "correctie laatste aangifte (voorstel)" = Σ btw van de BUA-rekeningen (kantine/sponsoring getoond,
   NIET in de som). LET-OP letterlijk in élke uitvoer: "de € 227-drempel per begunstigde per jaar is niet uit de boekhouding te halen —
   voorstel = volledige btw-som; de accountant toetst de drempel, de module past niets toe". TOTAAL-regel (oordeelregel):
   `TOTAAL N administratie(s) mét BUA-btw van M · BUA-btw € x · voorstel correctie € y · kantine € k · sponsoring € s · fouten 0`.
2. **Bevinding `bua_correctie_open`** — `soort_stand.REGISTRY` (blok `documenten`, `sinds` 24-09, `default=METEN`), tekst in
   `teksten._documenten` ("BUA-correctie {jaar} nog te beoordelen — … € x btw afgetrokken … correctie in de laatste btw-aangifte …",
   zonder GUID's), handeling "Rapport openen" = `kantoorbreed._doel_pad` → `/instellingen/administraties/{aid}?tab=boeken-ai#bua-jaarrapport`.
   Stap `bua_cli.reconciliatie_stap(verzamelaar, vandaag=…)` aan het einde van het documenten-blok (`cli._reconciliatie`): vóór 1 december
   niets ("nog niet aan de orde"), daarna per administratie mét BUA-btw > 0 in het boekjaar één afwijking (vingerafdruk
   `documenten:<aid>:bua_correctie_open:<jaar>`, detail jaar/btw_som/kantine_btw/sponsoring_btw/rekeningen mét btw ≠ 0); lees-only in beide
   modi (geen writes, geen RLZ-call); een fout in de stap = FOUT-bevinding, nooit een crash van het blok.
3. **Route `GET /administraties/{id}/bua-jaarrapport?jaar=`** (`app/beheer/router.py`): kantoorrol (router-brede poort) + administratie-scope,
   lees-only, nooit een RLZ-call vanuit een request (RLZ-kant alleen via de CLI); 404 onbekende administratie, 403 buiten scope.
   Toegevoegd aan de gate-sweep `tests/security/test_rol_endpoint_gates.py`.
4. **Frontend**: `frontend/src/instellingen/BuaJaarrapportBlok.tsx` op Instellingen › ‹administratie› › Boeken & AI onder "Btw niet
   aftrekbaar" (anker `bua-jaarrapport`; registry-entry `bua-jaarrapport` in `instellingenRegistry.ts`, `beheerder: false` — lezen mag élke
   kantoorrol); jaar-keuze (huidig/−1/−2), tabel in `.tabel-scroll` met alleen rekeningen mét btw ≠ 0, categorie-chip, chip "correctie laatste
   aangifte (voorstel)", sommen (BUA/kantine apart/sponsoring apart/Reeleezee-kant), LET-OP als `role="note"`, lege stand mét zin, fout =
   `role="alert"`. Geen `<button>`; geen schrijfactie.
5. Het kenmerk 0163 blijft per rekening beschikbaar; `bua-kenmerk-zetten` blijft bestaan en is NIET gedraaid.

### Tests (letterlijk)
- `pytest_blok.sh a5 tests/beheer/test_bua_jaarrapport.py tests/beheer/test_bua_cli.py tests/reconciliatie/test_soort_stand.py tests/unit/test_cli_smoketest.py`
  → `73 passed`; eerder in één run mét `tests/security/test_rol_endpoint_gates.py tests/activa/test_reconciliatie.py` → `593 passed`.
  Nieuw `tests/beheer/test_bua_jaarrapport.py` (19): categorie puur (7 parametrisch), LET-OP letterlijk, motor module+bank per administratie
  zonder lek, kantine/sponsoring buiten het voorstel, RLZ-kant via fake GET-client mét boekjaar client-side (regel van 2025 valt af, credit
  negatief), geen credential = zichtbaar niet gemeten, élke CLI-vorm letterlijk (`--jaar 2026`; `--administratie Tweede`; `--json-uit` op uuid;
  `--rlz` mét fake; `--rlz` zonder credential; onbekend = exit 2), kapotte administratie stopt de rest niet, soort in meten, stap vóór 1-12
  niets / ná 1-12 twee rijen mét detail + leesbare tekst + deeplink / lees-only variant, hook in `_reconciliatie` (aanroep + foutpad),
  route 200 Beheerder / 200 Boekhouding mét scope / 404 / 403.
- Les uit de bouw: de eerste fake-stub weigerde `" eq 1"` in het filter en struikelde dus over élke ledger-GUID die met "1" begint (2 van 590
  rood, intermittent) — nu `re.fullmatch(r"Account/id eq [0-9a-f-]{36}")`; twee opeenvolgende runs groen.
- Frontend: `npx vitest run src/instellingen/BuaJaarrapportBlok.test.tsx src/instellingen/instellingenRegistry.test.ts
  src/instellingen/AdministratieDetailPagina.minivoorraad.test.tsx` → `22 passed`; `npx tsc -b` schoon (op het moment van meten).
- ruff: mijn regels schoon; resterende E501/I001 in `router.py:911` (import-blok van een ander blok), `soort_stand.py` en `teksten.py` zijn
  pre-existente of andermans regels — niet aangeraakt.

### Meetrecept ná deploy (werkt in productie: ja/nee)
1. `gh workflow run nameting -f onderdeel=bua-jaarrapport` (vier plekken in `$S/nameting_blok5.txt`: if-tak + `options` + `via_gh_onderdeel`
   + `OORDEEL_BRON`; allowlist-woord `bua-jaarrapport` in `nameting.sh`) → bot-bestand `verkenning/nameting-bua-jaarrapport-<dd-mm>.txt`.
   Verwacht: 78 administraties, TOTAAL-regel mét `fouten 0`, per RLZ-administratie "RLZ-kant: gemeten (JournalEntryLines, alleen GET)"
   (Odoo = "niet gemeten (Odoo…)"; Universal Steigerbouw/Rubicon mogelijk "niet gemeten (RLZ-fout: 403…)" = uitkomst, geen fout).
   Werkt in productie: ja = TOTAAL-regel aanwezig mét `fouten 0` én ≥ 1 administratie mét "RLZ-kant: gemeten".
2. Kantoor-web: Instellingen › BLOW B.V. › Boeken & AI › blok "BUA-jaarrapport" toont 2026 (verwacht o.a. 4510 met de 2 T&J/BLOW-regels
   uit de meting van 22-09: module btw 0,00 → mogelijk "geen btw afgetrokken"); request-log `GET …/bua-jaarrapport` 200, 0 × 5xx.
3. De bevinding: `db-lezen reconciliatie-bevindingen --param afwijking_soort=bua_correctie_open` — pas ná de run van 1-12-2026; tot dan
   staat in élke run-uitvoer de regel "BUA-jaarcorrectie: nog niet aan de orde (pas vanaf 1 december 2026)" (job-log rlz-reconciliatie).
4. Vervolg-opdracht `opdrachten/inbox/2026-09-25-nameting-bua-jaarrapport-na-deploy.md` (`niet vóór:` deploy + 15 min).

### Klikpunten Peter
- Geen. (De zetting `bua-kenmerk-zetten` van 21-09 vervalt door dit besluit; niets te klikken.)

### Aangrenzende gaten
1. **Lifecycle:** de bevinding sluit automatisch zodra de som 0 wordt of het jaar voorbij is (vingerafdruk per jaar; `reconciliatie_auto_gesloten`);
   een beoordeelde correctie = "Gezien" met reden — er is bewust géén "correctie ingediend"-knop (de module past niets toe; aangifte is
   accountantswerk). Verwijderen: n.v.t. (lees-only, geen data).
2. **Consistentie:** de categorie-indeling volgt exact `advies_voor` (kantine = beoordelen, sponsoring = niet_zetten) — één afwijking
   in `BUA_NAAMDELEN`-uitbreiding raakt beide; `bua-kandidaten --jaar` en `bua-jaarrapport` lezen dezelfde tel-logica (`kandidaten_voor`),
   dus geen tweede waarheid. De RLZ-kant kan overlappen met de module-kant (zelfde boeking in beide bronnen) — bewust náást elkaar
   getoond, niet opgeteld.
3. **UX:** het blok toont alleen rekeningen mét btw ≠ 0 (lege stand = zin); een export (CSV) voor de accountant is niet gebouwd — kandidaat
   als Peter erom vraagt. De promotie van `bua_correctie_open` naar `actie` (actiemail in december) = Beheerder-besluit ná de eerste
   meting (regel 17-09).
4. **Compliance:** de € 227-drempel per begunstigde is niet uit de boekhouding te halen → LET-OP-tekst op élke uitvoer; het rapport is een
   voorstel, de correctie zelf blijft mens (accountant) — conform "geld = code, knop = mens".

### Gewijzigde/nieuwe bestanden (blok 5)
- `backend/app/beheer/bua_cli.py` (jaarrapport-motor, CLI, reconciliatie-stap), `backend/app/beheer/router.py` (route), `backend/app/cli.py`
  (hook aan het einde van `_reconciliatie`), `backend/app/reconciliatie/soort_stand.py` (soort), `backend/app/reconciliatie/teksten.py`
  (tekst), `backend/app/reconciliatie/kantoorbreed.py` (deeplink), `backend/tests/security/test_rol_endpoint_gates.py` (route in de sweep),
  nieuw `backend/tests/beheer/test_bua_jaarrapport.py`.
- `frontend/src/instellingen/BuaJaarrapportBlok.tsx` (nieuw), `BuaJaarrapportBlok.test.tsx` (nieuw), `instellingenRegistry.ts` (entry),
  `AdministratieDetailPagina.tsx` (import + plaatsing).
- Coördinator-bestanden: `$S/beslissingen_blok5.md`, `$S/regels_blok5.md` (doel `docs/regels/btw.md`), `$S/watisnieuw_blok5.md`,
  `$S/nameting_blok5.txt` (+ guard-suggestie voor `test_nameting_workflow.py`).

### Gelezen regels (voor de rapportsectie)
`docs/regels/btw.md` (271 regels), `docs/regels/reconciliatie.md` (306 regels), `docs/regels/kantoor-frontend.md` (144 regels),
`docs/regels/werkloop-productie.md` (332 regels).

## Blok 6 — Activa: afschrijvingsrekening = KOSTENrekening mét dezelfde omschrijving (besluit Peter 24-09 07:5x)

**Gebouwd (geen migratie):** de conventie "code + 1 op 0xxx" (BUG-run 23-09 avond) is vervangen door "de 4xxx-KOSTENrekening
(soort 2, niet-verdwenen, niet-totaal, zelfde administratie) waarvan de genormaliseerde omschrijving ná het voorvoegsel
Afschrijving/Afschrijvingen/Afschrijvingskosten (+ optioneel op/van) gelijk is aan die van de activarekening; ook de omgekeerde vorm
'‹naam› afschrijving'". Normalisatie = lowercase, diakrieten weg, niet-alfanumeriek → spatie. Precies één treffer = voorgevuld
mét herkomst `conventie`; nul of meerdere = leeg → combobox verplicht + 422 (ongewijzigd). Balanskant blijft `BalanceAccount`.
Volgorde koppeling > instelling > conventie ongewijzigd; chip op de kaart = "voorgevuld: conventie (kostenrekening zelfde omschrijving)".
De combobox-opties (`afschrijving_ledger_opties`) zijn nu de 4xxx-kostenrekeningen (soort 2), "afschrijving" in de naam eerst, dan op code
(was: 0xxx soort 3). `_valideer_invoer` eiste al geen soort → geen wijziging. Het vangnet in `maak_aan_in_rlz` volgt automatisch.
`volgende_code` is verwijderd (geen andere aanroeper). Pilates Bloom 4706 mét de kale naam "Afschrijvingskosten" matcht bewust NIET
(geen kern) → daar kiest de mens uit de combobox, of de instelling per categorie.

**Bestanden:** `backend/app/activa/afschrijving.py` (herschreven: `normaliseer`, `kern_van_afschrijvingsnaam`, `conventie_rekening`,
`SOORT_KOSTEN`), `backend/app/activa/instelling.py` (opties 4xxx soort 2, `SOORT_KOSTEN`), `backend/app/activa/voorstel.py` +
`service.py` (docstrings/commentaar), `frontend/src/activa/activaApi.ts` (chiptekst + doc), `frontend/src/document/ActivaVoorstelKaart.tsx`
(commentaar), tests: `backend/tests/activa/test_afschrijving.py` (herschreven, RGS-schema 0xxx + 4700-reeks, naam-varianten, dubbel/
verdwenen/totaal/soort-3/8xxx/andere administratie/fuzzy = None, diakrieten), `tests/activa/conftest.py` (GB_0108 = 4708 soort 2),
`test_voorstel.py`, `test_router.py`, `test_service.py`, `test_reconciliatie.py` (opties `["4708", "4400"]`, code 4708), gouden-set-casus
**ag** `tests/keten/test_ag_activum_mva_rekening.py` (fixture 4708 soort 2, `DepreciationAccount` = 4708), `frontend/src/document/
ActivaVoorstelKaart.test.tsx` (chiptekst).

**Tests:** `pytest_blok.sh a6 tests/activa tests/keten/test_ag_activum_mva_rekening.py tests/unit/test_keten_guard.py` → `127 passed`;
`vitest src/document/ActivaVoorstelKaart.test.tsx` → `15 passed`; `tsc -b` geen fouten in activa-bestanden.

**Werkt in productie: niet gemeten.** Meetrecept (dispatch-onderdeel `activa-conventie` — zie `$S/nameting_blok6.txt`): (1) ná deploy de
eerstvolgende kaart-klik: `db-lezen activa-stand --administratie <naamdeel>` rij `koppeling` → `afschrijving_ledger_code` begint met 4;
(2) request-log `POST …/activa-voorstel/*/aanmaken` 200/422/5xx sinds de deploy (zelfde filter als `activa-kaart`); (3) job-log
`activum_aanmaken_mislukt(_mens)`; (4) `rlz-lezen FixedAssets --expand DepreciationAccount` op de administratie van de klik →
`DepreciationAccount` = 4xxx.

**Klikpunten Peter (niet in deze run uitgevoerd — recept):**
1. STAP-0 deel 2 (schrijvend) op de RLZ-testadministratie `faae29c5` ("Administratiekantoor Nijenhuis (test)", gearchiveerd sinds 30-08,
   0 credentials): (a) dearchiveren mét de TESTADMIN-login (ná blok 3 blijft dat voor een RLZ-administratie het login-dialoog); (b)
   TEST-inkoopfactuur € 1.000 op een 0xxx-MVA-rekening boeken via de module; (c) kaart → conventie levert de 4xxx-afschrijvingskosten-
   rekening (chip "kostenrekening zelfde omschrijving") → "Aanmaken ná boeken"; (d) varianten als de PUT weer 404 `NotFound_FixedAsset`
   geeft: V0 `PUT FixedAssets/{client-guid}` mét `DepreciationAccount` 4xxx (huidige code), V1 zonder `DepreciationMethod`, V2 mét
   `FixedAssetMutationList` Type 6 Manual ter grootte van de aanschaf (het échte Pilates-Bloom-patroon), V3 `POST FixedAssets` zonder id
   — élk mét TEST-referentie; (e) controle `rlz-lezen --administratie "Nijenhuis (test)" --pad FixedAssets --expand
   "DepreciationAccount,BalanceAccount,DepreciationMethod"` → `DepreciationAccount.Code` 4xxx, `BalanceAccount.Code` 0xxx; (f) storno/
   verwijderen van het TEST-activum doet Peter in de RLZ-UI (de module verwijdert niets).
2. Herstel BLOw B.V. ná deploy én ná STAP-0 deel 2 via "Opnieuw aanmaken" (Inzicht › Reconciliatie, blok Activa) of de kaart:
   23619 € 935,00 (23-09, 0107) · 06052 € 680,00 (23-09, 0107) · MK Illumination MK22507863 € 1.078,10 (23-09, 0107); vooraf toetsen of
   BLOw een 4xxx-rekening "Afschrijving kantoorinventaris" (of gelijknamig aan de 0107-omschrijving) heeft — anders kiest Peter in de
   combobox of zet de instelling per categorie.

**Aangrenzende gaten:** (1) lifecycle — een instelling-per-categorie die nog naar een 0xxx-rekening wijst (vóór dit besluit gezet) wint
nog steeds van de conventie en zou RLZ een balansrekening als `DepreciationAccount` geven; productie 22-09: `afschrijving_ledgers` nergens
gevuld (instelling-rijen alleen grens/probe), dus geen data-stap nodig — wél een guard-vraag voor de Beheerder-UI (opties zijn nu 4xxx,
een oude 0xxx-waarde verschijnt niet meer in de lijst; voorstel: LET-OP in blok `activa` "afschrijvingsrekening is geen kostenrekening",
niet gebouwd). (2) consistentie — Pilates Bloom-patroon "kale naam Afschrijvingskosten" levert geen conventie-treffer; als dat vaak
voorkomt is "precies één kostenrekening mét 'afschrijving' in de administratie" een kandidaat-terugvalregel (niet gebouwd, geen gok).
(3) UX — de combobox toont nu álle 4xxx-kostenrekeningen (ook 4400 Inhuur); filteren op "afschrijving" zou de lijst korter maken maar
sluit een bewuste andere keuze uit — bewust niet. (4) compliance — geen.

## Blok 7a — Documentlink volgt de soort (BUG 23-09: vraag-thread opende kassarapport in het inkoopscherm)

**Feit:** Peter opende op 23-09 vanuit een vraag (Van Boxtel Horeca Exploitatie, `Journaal 19-9.pdf`
e7d89765-c4f5-42f3-82d9-71f8a11f5f7f, soort `kassarapport`, `vraag_open`) het document en kreeg het INKOOP-controlescherm:
`VraagThread.tsx:242` linkte hard naar `/documenten/<adm>/<doc>`; `documentRoute`/`reviewPad` kenden de soort-route maar de
thread (en 17 andere plekken) gebruikten ze niet.

### Gebouwd (geen migratie)
1. **Eén bron voor "open dit document"** — `frontend/src/werkvoorraad/format.ts::documentPad(administratieId, {id, soort?, status?}, context?)`:
   kassarapport → `/omzet/…`, verkoopfactuur → `/verkoop/…`, waarborg → `/waarborg/…`, verplichting → `/verplichting/…`, `vraag_open`
   (niet verwijderd) → de vraag op de klantpagina, al het andere/onbekende soort → inkoop-controlescherm (lijstcontext reist alleen dáár mee).
   `documentRoute` is er een dunne laag op; `zoeken/reviewPad.ts` en `materiaal/miniVoorraadApi.ts::documentPad` delegeren; `heeftEigenReviewscherm(soort)`.
2. **Server-spiegel** `backend/app/documenten/deeplink.py::document_pad(administratie_id, document_id, soort=None, status=None)` +
   `heeft_eigen_reviewscherm`; `documenten/corrigeren.py::review_pad` en `db/rls_weigering.py::doel_pad_voor_route` lopen erlangs.
   (Mails/push: geen enkele mail bouwde een `/documenten/…`-link — de kantoor-/accordeur-mails deeplinken naar `/accordeur…`; niets te migreren, wel geguard.)
3. **DTO's dragen de soort:** `VraagData.document_soort` + `VraagResponse.document_soort` (default `inkoopfactuur`), `OpenVraagRij(Dto).document_soort`;
   frontend `VraagDto.document_soort?`, `OpenVraagRijDto.document_soort?` (optioneel: oudere responses vallen terug op inkoop).
4. **Redirect in `DocumentDetailScreen`:** detail geladen mét een soort die een eigen reviewscherm heeft → `<Navigate replace>` naar `documentPad(…)`
   — nooit meer een leeg inkoopformulier voor een kassarapport/verkoopfactuur/waarborg/verplichting (ook voor oude links, mails, handmatige URL's).
5. **Copy vraag-thread:** "Factuur bekijken" → **"Document bekijken"** (volgt de soort); bij soort kassarapport óf een vraag-tekst mét "omzetreview"
   staat er een extra `btn secondary` **"Naar omzetreview →"** naar `/omzet/<adm>/<doc>`.
6. **Guards:** vitest `werkvoorraad/documentPad.guard.test.ts` (leest álle `src/**/*.ts(x)` behalve tests/`dev/`: geen letterlijke
   `` `/documenten/${ ``-link buiten `format.ts`; API-paden `/administraties/${…}/documenten/${…}` tellen niet) + gedragstoets; pytest
   `tests/unit/test_documentlink_deeplink_guard.py` (geen `"/documenten/{`-f-string buiten `deeplink.py` in `backend/app` + spiegel-gedrag).
   Keten-guard: `tests/keten/test_lijst_standaard_en_wachten.py::TestDocumentlinkVolgtDeSoort` (Floor-vraag draagt `document_soort`, spiegel kiest het pad).

### Cross-cutting-inventaris (élke plek die een documentlink bouwde)
| plek | stand |
|---|---|
| `vragen/VraagThread.tsx` (de casus) | gefixt — `documentPad` mét `vraag.document_soort` + knop "Naar omzetreview →" |
| `vragen/OpenVragenKantoorbreed.tsx::vraagDeeplink` | n.v.t. — deeplink naar de vráág (`?sectie=vragen&document=`), soort op de rij toegevoegd (`document_soort`) |
| `document/DocumentDetailScreen.tsx` (mogelijk_duplicaat_van; navigate ná verplaatsen) | gefixt (verplaatsen neemt `detail.soort` mee) + redirect-grendel |
| `document/DuplicaatAfvoer.tsx` (3×), `document/TegenboekSectie.tsx` | gefixt — soort ontbreekt in de DTO → inkoop (duplicaat-/tegenboek-context = inkoopfacturen); het detailscherm stuurt anders door |
| `werkvoorraad/DocumentenDeelscherm.tsx` (afwijzing.duplicaat_van, samengevoegd_in, duplicaat_werkvoorraad_van, mogelijk_duplicaat_van, "Toon origineel") | gefixt (fallback inkoop; redirect vangt de rest) |
| `werkvoorraad/useUploadWachtrij.tsx` "→ bestaand document" | gefixt |
| `zoeken/ZoekenScreen.tsx`, `zoeken/ArchiefScreen.tsx` (open origineel; `reviewPad`-aanroepen) | gefixt / via `reviewPad` → `documentPad` |
| `verplichting/VerplichtingReviewScreen.tsx`, `verplichting/VerplichtingenScreen.tsx` (gematchte facturen) | gefixt (facturen = inkoop) |
| `instellingen/AutoboekKandidaten.tsx` (laatste document) | gefixt |
| `doorbelasting/DoorbelastingReviewScreen.tsx` "← Document" | gefixt |
| `voorraad/VoorraadScreen.tsx`, `materiaal/miniVoorraadApi.ts::documentPad` (VoorraadLog) | gefixt |
| `projectverdeling/HercontroleScreen.tsx::documentPad(rij)` | n.v.t. — bouwt al de klantpagina-deeplink `/?administratie=…&document=` |
| `werkvoorraad/KlantStanden.tsx`, `FilterWeergave.tsx`, `DocumentenDeelscherm` rij-klik | al via `documentRoute` (nu laag op `documentPad`) |
| `dev/visueelHarnas*.tsx`, alle `*.test.tsx` | bewust uitgesloten (mock-URL's/verwachtingen) |
| backend `documenten/corrigeren.py::review_pad`, `db/rls_weigering.py::doel_pad_voor_route` | gefixt via `deeplink.document_pad` |
| backend mails (`app/berichten/*`) | n.v.t. — geen `/documenten/…`-link; deeplinks `/accordeur…`; geguard |
| `reconciliatie/kantoorbreed.py::_doel_pad` | n.v.t. — klantpagina-deeplink `/?administratie=…&document=` (de klantpagina routeert per soort) |

### Tests (letterlijk)
- vitest `src/vragen src/werkvoorraad src/document src/zoeken src/verplichting src/instellingen/AutoboekKandidaten src/doorbelasting src/voorraad src/materiaal`: **Test Files 96 passed (96) · Tests 714 passed (714)**; `npx tsc -b` schoon.
- pytest (eigen DB `guards`): `tests/unit/test_documentlink_deeplink_guard.py tests/documenten/test_corrigeren.py` **23 passed**;
  `tests/bewaking/test_rls_weigering.py tests/vragen tests/documenten/test_vragen.py tests/keten/test_lijst_standaard_en_wachten.py tests/unit/test_keten_guard.py` **66 passed**.
- Nieuw: `VraagThread.test.tsx` (3: kassarapport → `/omzet`, geen soort → inkoop, tekst "omzetreview" → knop), `DocumentDetailScreen.test.tsx`
  (redirect kassarapport → `/omzet/…`; inkoopfactuur blijft), `documentPad.guard.test.ts` (3), `test_documentlink_deeplink_guard.py` (2), keten-klasse (1).
  Aangepast: `VragenScreen.test.tsx` (knoplabel "Document bekijken").

### Meetrecept ná deploy (werkt in productie: NIET GEMETEN)
1. Request-log: `resource.labels.service_name="rlz-backend" httpRequest.requestUrl:"/omzet/"` — ná de deploy een GET op
   `/omzet/<Van Boxtel-adm>/e7d89765-c4f5-42f3-82d9-71f8a11f5f7f` (Peter klikt "Document bekijken"/"Naar omzetreview →" in de vraag van 21-09 06:10)
   en géén GET `/administraties/<adm>/documenten/e7d89765…/boekvoorstel` meer vanuit die vraag (het inkoopscherm laadde dat).
2. Cloud Logging op `/vragen/open` (kantoorbrede lijst) → response draagt `document_soort` (steekproef via kantoor-web Netwerk-tab, Peter).
3. Klikpunt Peter: open de Van Boxtel-vraag → landt op het omzetreview-scherm; type handmatig `/documenten/<adm>/e7d89765…` → redirect naar `/omzet/…`.

zie sectie 'Punt 3 — Van Boxtel' hieronder

### Aangrenzende gaten
- **Lifecycle:** een `verwijderd` document mét soort kassarapport redirect nu óók naar `/omzet/…` — dat scherm toont de verwijderd-stand (bestaand gedrag van OmzetReviewScreen? niet getoetst in deze run). Geen link naar een verwijderd document wordt aangemaakt behalve "Toon origineel".
- **Consistentie:** `DuplicaatReferentieDto`/`samengevoegd_in`/`duplicaat_werkvoorraad_van` dragen geen soort — de redirect-grendel op het detailscherm dekt het (één omweg); wil men de omweg weg, dan is `soort` op die referentie-DTO's een kleine additieve uitbreiding (niet gedaan: geen casus).
- **UX:** de knop "Naar omzetreview →" verschijnt op tekst-match ("omzetreview") — de automatische mapping-vraag noemt dat scherm letterlijk; een toekomstige herformulering van die vraagtekst laat de knop op soort `kassarapport` gewoon staan.
- **Compliance:** geen.

### Bestanden
backend: `app/documenten/deeplink.py` (nieuw), `app/documenten/vragen.py`, `app/documenten/schemas.py`, `app/documenten/router.py`, `app/documenten/corrigeren.py`, `app/db/rls_weigering.py`, `app/vragen/service.py`, `app/vragen/schemas.py`, `tests/unit/test_documentlink_deeplink_guard.py` (nieuw), `tests/keten/test_lijst_standaard_en_wachten.py`.
frontend: `src/werkvoorraad/format.ts`, `src/werkvoorraad/documentPad.guard.test.ts` (nieuw), `src/werkvoorraad/DocumentenDeelscherm.tsx`, `src/werkvoorraad/useUploadWachtrij.tsx`, `src/zoeken/reviewPad.ts`, `src/zoeken/ZoekenScreen.tsx`, `src/zoeken/ArchiefScreen.tsx`, `src/vragen/VraagThread.tsx`, `src/vragen/VraagThread.test.tsx`, `src/vragen/VragenScreen.test.tsx`, `src/document/DocumentDetailScreen.tsx`, `src/document/DocumentDetailScreen.test.tsx`, `src/document/DuplicaatAfvoer.tsx`, `src/document/TegenboekSectie.tsx`, `src/doorbelasting/DoorbelastingReviewScreen.tsx`, `src/instellingen/AutoboekKandidaten.tsx`, `src/verplichting/VerplichtingReviewScreen.tsx`, `src/verplichting/VerplichtingenScreen.tsx`, `src/voorraad/VoorraadScreen.tsx`, `src/materiaal/miniVoorraadApi.ts`, `src/api/types.ts` (VraagDto + OpenVraagRijDto `document_soort?`).
Let op: `src/api/types.ts`, `src/document/DocumentDetailScreen.tsx`, `src/document/DocumentDetailScreen.test.tsx` worden ook door andere blokken geraakt (7b/6) — hunks per blok stagen.

### Punt 3 — Van Boxtel: InboekDienst2 (7×), MargeRapport5 week 38, weekstaten week 38 (coördinator)
Peter besliste dit al op 24-09 08:xx (gespreksverslag, letterlijk): **"boxtel aparte boekstukken, gewoon zoals de rest ook is"** →
losse kassarapport-boekstukken per document, geen bijlagen bij het Journaal. Geen parser-uitbreiding: de ProfX-parser kent alleen
Journaal/Margerapport op de tekstlaag; InboekDienst2/MargeRapport5/weekstaten zijn andere rapportvormen zonder deterministische
herkenning → géén autotype (nooit raden), wél de bestaande handeling. Handeling kantoor: documentenlijst Van Boxtel Horeca Exploitatie →
vinkjes → ⋯ "Type wijzigen… → kassarapport" (bulk-actie 16-09) — de omzetstroom neemt ze dan op als losse boekstukken. Lees-only meting
in productie was in deze run niet mogelijk (vrije SQL geblokkeerd, zie blok 4) → meetlat = bibliotheek-query
`db-lezen documenten-open --administratie "Van Boxtel" --param soort=inkoopfactuur` ná deploy (verwacht: 9 rijen InboekDienst2/
MargeRapport5/weekstaten zolang het kantoor het type niet wijzigt). Klikpunt = de bulk-typewissel door het kantoor (geen bedrag, geen
boekstuk — pure typering van open documenten).

## Blok 7b — Samenvoegen-vinkje: bron = opgeslagen regels, nooit stil weg (BUG 23-09, BLOW Van Rumpt 2025135 € 1.277,50, document 3405157f-5a1c-46e8-ba16-980e03d79ee4)

**Gebouwd (geen migratie):**
- `backend/app/documenten/boekvoorstel.py`: nieuwe pure functie `_samengevoegde_regel_uit_opgeslagen(regels, percentages, factuurnummer) → (regel | None, reden | None)`: ≥ 2 opgeslagen regels → Σ netto, Σ btw (regel-btw leeg → `regelsom.btw_uit_tarief(netto, percentage)` cent-exact uit `taxrate_cache`; geen percentage → reden "btw-bedrag van regel n onbekend"; netto leeg → "nettobedrag van regel n onbekend"), één btw-code (anders reden `REDEN_SAMENVOEGEN_BTW_CODES` = "verschillende btw-codes"), grootboek alleen als alle regels hetzelfde dragen, omschrijving "Factuur ‹nr› — samengevoegd (N regels)". In `_lees_opgeslagen_voorstel` vervangt die uitkomst bij ≥ 2 opgeslagen regels de scan-variant; de scan (`_samengevoegde_regel(veldvoorstel)`) blijft de bron zonder/bij 1 opgeslagen regel. `_samenvoeg_velden` draagt de nieuwe sleutel `samenvoegen_niet_mogelijk_reden` (scan met ≥ 2 gelezen regels maar geen totaal → `REDEN_SAMENVOEGEN_SCAN_ONVOLLEDIG`). Helper `_taxrate_percentages_in_sessie`. Dataclass-veld `BoekvoorstelData.samenvoegen_niet_mogelijk_reden`.
- `backend/app/documenten/schemas.py` + `router.py`: DTO-veld `samenvoegen_niet_mogelijk_reden: str | None` op de boekvoorstel-response.
- `frontend/src/api/types.ts`: idem. `frontend/src/document/BoekvoorstelPanel.tsx`: state `samenvoegenNietMogelijkReden`; kan er bij > 1 regel niet worden samengevoegd (toegestaan, geen variant), dan chip `samenvoegen-niet-mogelijk-chip` "samenvoegen niet mogelijk: ‹reden›" (server-reden, anders "geen samengevoegde regel te berekenen") naast/in plaats van de chip "weergave hersteld"; het vinkje verschijnt weer zodra de server een variant meegeeft.
- Tests: `backend/tests/documenten/test_boekvoorstel_samenvoegen_23_09.py` (11: puur 6 — 7 regels Σ 1.055,81 / btw 221,69, opgeslagen btw wint, verschillende codes → reden, geen percentage → reden, verschillende GB → regel zonder GB, 1 regel → (None, None); DB 4 — opgeslagen regels zonder btw geven variant, gemengde codes → reden, 1 regel → geen reden, scan-pad ongewijzigd bij 1 UBL-regel; 1 constante), `frontend/src/document/BoekvoorstelPanel.samenvoegen23.test.tsx` (4). Keten-aanraking: `backend/tests/keten/test_ae_zilver_horeca_regelkolom.py` (projectplicht → veld reist mee, None, geen chip).

**Poort (eigen DB `boekhouding_test_guards2`):** `$S/pytest_blok.sh guards2 tests/documenten/test_boekvoorstel_samenvoegen_23_09.py tests/documenten/test_boekvoorstel.py tests/documenten/test_router.py tests/documenten/test_spot_services_blok4.py tests/keten/test_ae_zilver_horeca_regelkolom.py tests/keten/test_ae_rituals_btw_volgt_tarief.py tests/documenten/test_regel_prefill_factuur_regel_18_09.py -q -p no:randomly` → **85 passed, 1 warning in 43.94s**; vitest `BoekvoorstelPanel.samenvoegen23` + `modus18` → **8 passed**; `tsc -b` geen fouten in eigen bestanden. (Tussentijds strandde één herdraai op een import-fout van blok 7a — `app/documenten/vragen.py` `VraagData.document_soort` default-veld vóór het non-default `totaalbedrag`; intussen door dat blok gefixt, herdraai groen.)

**Keten-sweep (pixelbaseline):** de nieuwe chip verschijnt alleen bij ≥ 2 regels zónder berekenbare variant; de gouden-set-detailcasussen (Universal Nederland UBL, Floor, Spot Services, BDO, DCTE, Kader) dragen een UBL-totaal of projectplicht → geen chip verwacht, baseline ongewijzigd. Wordt een detail-casus tóch rood, dan alleen díe herdraaien (`KETEN_ALLEEN=<casus>`), nooit de baseline verversen zonder te kijken.

**Meetrecept ná deploy (werkt in productie: niet gemeten):**
1. Request-log `GET …/administraties/5419878c…/documenten/3405157f-5a1c-46e8-ba16-980e03d79ee4/boekvoorstel` ná de deploy → 200; Peter opent het document: vinkje "Splitsen per regel" zichtbaar, geen chip (7 regels, zelfde btw-code 1e44993a-…).
2. Nazorg-meting omvang (punt 3 van de opdracht, leesreplica/job `db-lezen --sql`, per administratie in RLS-scope, zonder `|` en `;`):
`select d.administratie_id, count(*) as documenten from boekhouding.document d join boekhouding.boekvoorstel b on b.document_id = d.id where d.status in ('te_controleren','handmatig_afmaken','klaar_om_te_boeken','vraag_open') and d.soort = 'inkoopfactuur' and (select count(*) from boekhouding.boekvoorstel_regel r where r.document_id = d.id) >= 2 group by d.administratie_id order by 2 desc`
(kolommen `boekhouding.boekvoorstel_regel.document_id`, `boekhouding.boekvoorstel.document_id`; de scan-stand — veldvoorstel zonder `totaal_excl`/regel-`netto_bedrag` — staat in de tijdlijn-JSON en is per document via `db-lezen document-feiten` te lezen; kantoorbreed telt deze query het bovengrens-aantal documenten dat het vinkje ná deploy kán terugkrijgen).
3. Vitest-/pytest-poort zoals hierboven; geen dispatch-onderdeel nodig (scherm-gedrag; de meting is het request-log + Peters klik).

**Klikpunt Peter:** document 3405157f… (BLOW, Van Rumpt 2025135, € 1.277,50, 7 regels, status te_controleren 23-09) ná de deploy openen → vinkje terug; de 6 weggekruiste regels hoeven niet hersteld te worden als het document intussen geboekt is.

**Aangrenzende gaten:** lifecycle — een regel die de mens ná het samenvoegen weer splitst valt terug op de opgeslagen (nu ene) regel + de AI-prefill (bestaand gedrag, ongewijzigd); consistentie — de samengevoegde omschrijving volgt de bestaande factuurnummer-vorm van `_samengevoegde_regel`; de regelsom-check blijft de poort (Σ ≠ factuurtotaal = rood, ook op de samengevoegde regel); UX — chip `stil`, tekst benoemt de reden en de handeling (bedragen/btw-codes aanvullen of los boeken); compliance — geen geldlogica gewijzigd buiten de weergave-/boekvorm (Σ van de opgeslagen regels is per definitie de som die de mens al zag).

**Bestanden:** backend/app/documenten/boekvoorstel.py, backend/app/documenten/schemas.py, backend/app/documenten/router.py, backend/tests/documenten/test_boekvoorstel_samenvoegen_23_09.py (nieuw), backend/tests/keten/test_ae_zilver_horeca_regelkolom.py, frontend/src/api/types.ts, frontend/src/document/BoekvoorstelPanel.tsx, frontend/src/document/BoekvoorstelPanel.samenvoegen23.test.tsx (nieuw).

## Poort (gouden set)
- pytest volledige suite (alleen, `boekhouding_test`): **7428 passed, 21 deselected in 53:55** (een eerste run strandde op een DB-reset door een gelijktijdige guard-test van de coördinator — eigen fout, herstart).
- vitest volledig: **263 bestanden, 1975 tests passed**; `npx tsc -b` schoon (werkboom ná alle agenten).
- Gouden set: `frontend/scripts/keten_sweep.sh` **11 metingen groen, 0 nieuwe baselines** (export `b_floor.json` draagt het nieuwe DTO-veld `samenvoegen_niet_mogelijk_reden: null` — pixel-identiek).
- Docs-guards (CLAUDE.md↔BESLISSINGEN, regels-index, rapporten-INDEX/Gelezen regels/klikpunten, nameting-workflow) groen; changelog-guard groen ná het samenvoegen van omgeslagen bullets.
- Niet gedraaid: `overflow_sweep.sh` (het nieuwe BUA-blok staat op een bestaande tab in `.tabel-scroll`; de instellingen-harnas mockt de nieuwe route niet — kandidaat voor de nameting-nazorg).

## Commits
- `9ca61ab` feat(activa blok 6 bundelrun 24-09 — afschrijvingsrekening = KOSTENrekening mét dezelfde omschrijving (besluit Peter 24-09 07:5x, herziet BUG 24-09 regel 1 'code + 1 op 0xxx'; geen migrati…
- `0233f57` feat(odoo blok 2 bundelrun 24-09 — taal-poort lang=nl_NL op élke lees- én schrijfcall (Peter 24-09, Bonte Hoeve: grootboeknamen Engels in de module; geen migratie): OdooClient.call zet con…
- `d51f2ac` fix(blok 7 bundelrun 24-09 — twee bugs van 23-09; geen migratie): (7a) documentlink volgt de soort — één routefunctie werkvoorraad/format.ts::documentPad (kassarapport → /omzet, verkoopfac…
- `5fe2c54` fix(administraties blok 3 bundelrun 24-09 — dearchiveren Odoo-administratie zonder Reeleezee-login (BUG Peter 24-09, Recreatief Vastgoed Nederland companies 13/11; geen migratie): Heractiv…
- `7534944` fix(intake blok 1 bundelrun 24-09 URGENT — Vastly-PDF-tweelingen: bundeling faalde stil (23 losse PDF's als inkoopfactuur, batch 23-09 én al 31-08); oorzaak = onze bundeling: Vastly-UBL's …
- `658596a` feat(doorbelasting blok 4 bundelrun 24-09 LEES-ONLY — factuur-PDF 'onvolledig' = cent-verschil per-regel-afronding (casus KF → Molenhof Verhuur, Lusso 261004: motor 995,73 + 49,79 = 1.045,…
- `baf577d` feat(btw blok 5 bundelrun 24-09 — BUA-jaareinde-rapport i.p.v. kenmerk (besluit Peter 24-09 'nee standaard 21 % btw aanhouden … liever een correctie indienen'; herziet het bulk-voorstel 21…
- docs-commit: deze commit (rapport, BESLISSINGEN, regels, CLAUDE.md, WAT_IS_NIEUW, gespreksverslag, nameting-workflow, opdrachten).

## Nametingen (recept vooraf) — werkt in productie: niet gemeten
Zes dispatch-onderdelen in `.github/workflows/nameting.yml` (vier plekken elk; guard `test_nameting_workflow.py::test_bundelrun_24_09_*`):
`vastly-tweelingen` (dry-run herstel-CLI + `documenten-open` + bevindingen), `odoo-taal` (`grootboek-taal` per Odoo-administratie),
`dearchiveren-odoo` (request-log + `administratie-stand`), `doorbelasting-pdf` (klasse-telling + Lusso `--pdf`), `bua-jaarrapport`
(`--jaar 2026 --rlz`), `activa-conventie` (kaart-recept + `activa-stand` 4xxx + FixedAssets). Vervolg-opdracht
`opdrachten/inbox/2026-09-25-nameting-bundelrun-zeven-punten-na-deploy.md` (`niet vóór: 2026-09-25 07:15`, ná de deploy én de run van 06:30).
Blok 7a/7b: request-log + Peters klik (geen onderdeel — schermgedrag).

## Klikpunten Peter (samengevat; detail per blok hierboven)
1. Blok 1 — "ja" voor de échte herstelrun ná deploy: `gcloud run jobs execute rlz-reconciliatie --args="^|^-m|app.cli|vastly-pdf-tweelingen-herstel|--uitvoeren"` (eerst de dry-run: verwacht 23 kandidaten — Rubicon 10 / Elissen 4 / ARVUM 3 / Meyer 3 / Shuto 3 uit de batch van 23-09; RUB-2026-0031 mét RLZ-bijlage). Afwijking van 23 = eerst verklaren (JGM-0038/0039 en INP-0025 kwamen als dubbelpaar binnen).
2. Blok 2 — hersync Bonte Hoeve niet afwachten tot 07:00? Dan `gcloud run jobs execute rlz-sync --args="^|^-m|app.cli|odoo-stamgegevens-sync|--administratie|Bonte Hoeve"` (eerst `…|--dry-run`).
3. Blok 3 — dearchiveer `8ea9d28b-e743-4566-96d7-bb7d81531368` (Recreatief Vastgoed Nederland B.V., company 13, gearchiveerd 24-09) via de nieuwe dialoog; `59bf1f7f…` (company 11) blijft gearchiveerd.
4. Blok 4 — akkoord op voorstel (b): doorbelastingsmotor boekt de btw per tarief over het subtotaal (RLZ-vorm) + data-stap bestaande boekingen; en een actieve Beheerder-e-mail voor `db-lezen --sql --als` op de job.
5. Blok 6 — STAP-0 deel 2 op de testadministratie (dearchiveren mét TESTADMIN-login) en herstel BLOw 23619 € 935,00 / 06052 € 680,00 / MK22507863 € 1.078,10 (alle 23-09, 0107) via "Opnieuw aanmaken".
6. Blok 7a punt 3 — Van Boxtel: 9 open documenten (InboekDienst2 7×, MargeRapport5 week 38, weekstaten week 38) bulk "Type wijzigen → kassarapport" (uw besluit 24-09 "aparte boekstukken").
7. Blok 7b — document 3405157f… (BLOW, Van Rumpt 2025135, € 1.277,50, 23-09) ná deploy openen: vinkje terug.

## Gelezen regels
- `docs/regels/intake-extractie.md` (380 regels)
- `docs/regels/duplicaten-crediteuren.md` (152 regels)
- `docs/regels/administraties-instellingen.md` (169 regels)
- `docs/regels/kantoor-frontend.md` (144 regels)
- `docs/regels/doorbelasting-intercompany.md` (185 regels)
- `docs/regels/btw.md` (271 regels)
- `docs/regels/activa.md` (109 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (428 regels)
- `docs/regels/omzet.md` (276 regels)
(regelaantallen = stand bij het lezen aan het begin van de run, vóór de aanvullingen van deze run)
