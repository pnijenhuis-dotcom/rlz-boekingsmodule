# Regels — Omzetboekingen, omzetbronnen en het verkoopfactuur-boekpad

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Kassarapporten (ProfX, dagstaat/kascheck, pilates-export) als entity-loze Receipts mét binder Inkomsten + kostprijsmemoriaal, stores → administratie platformbreed, tegenzijde per betaalwijze, Vastly-verkoopfacturen (§2d), waarborg.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Omzetboekingen** (kassarapporten, bijv. BLOW Margerapport): type in de werkvoorraad; boekt als
  SalesInvoice (omzet per categorie → omzet-GB, btw-code per categorie) + gekoppelde
  kostprijsmemoriaal (per productgroep aan voorraad), als één transactie. Periode uit rapport,
  duplicaatbewaking per periode, plausibiliteitscheck (marge vs historie). BLOW: cannabisomzet =
  "NL, Geen BTW (Vrijgesteld)" — bewust géén 0%-tarief (aangifte-rubriek).
  Omzetmodule GEBOUWD + GETEST (2026-08-07); boekt sinds 2026-08-09 als entity-loze Receipts (besluit Peter
  2026-08-08 — kasomzet = losse boeking, geen dummy-debiteur); omzet-autoboeken opt-in per administratie (GO Peter
  01-09, migratie 0096). Zie BESLISSINGEN "Omzetmodule — GEBOUWD + GETEST", "OMZET-AUTOBOEKEN"; RLZ-feiten in
  api-verkenning "Omzetmodule STAP 0" + "Receipts-verkenning".
  **Receipts-categorie op BINDER Inkomsten, niet op naam (Peter 16-09, Van Boxtel; geen migratie):** STAP-0 bewees dat de
  RLZ-UI-mappen Inkomsten/Uitgaven de `DocumentBinder` van de categorie volgen en dat de Van Boxtel-"omzetrapporten"
  PurchaseInvoices waren (kassarapporten via de inkoopstroom); `app/omzet/categorie.py` kiest DocumentType 10 + binder
  Inkomsten (harde check "Omzetcategorie (Inkomsten)", mens kiest in het omzetscherm = default van de administratie),
  reconciliatie-soorten `verkoop_categorie_afwijkt`/`omzet_in_inkoopstroom` mét actie "Herboeken als omzet" (storno 19
  achter de aangiftepoort + herclassificatie), lees-only CLI `omzet-binder-rapport` — zie BESLISSINGEN "OMZET-RECEIPTS —
  BINDER INKOMSTEN, NIET NAAM (Peter 16-09, Van Boxtel)" + api-verkenning "Receipts — binder Inkomsten/Uitgaven (STAP-0 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Omzetbronnen spreadsheet — zonnestudio dagstaat + kascheck en pilates betalingsexport (Peter 15-09; migratie 0146):** deterministische parsers (`app/omzet/bronnen/`, xlrd/openpyxl → `Grid`, géén AI, geen AVG-gate) op het bestaande kassarapport-type mét veld `bron`; harde bron-controles als check-rijen, dagstaat + kascheck gebundeld per dag (wederhelft `samengevoegd`), pilates-export gesplitst per uitbetaling mét dedupe-sleutel `Factuurnummer|methode|bedrag|betaaldatum`, intake-routering op "Store Used" via Beheerder-instelling `bron_instellingen.stores` (route `GET/PUT …/omzet/bron-instellingen`, UI open), blok "Bron" in het omzet-controlescherm — zie BESLISSINGEN "OMZETBRON ZONNESTUDIO DAGSTAAT (Peter 15-09)" en "OMZETBRON PILATES BETALINGSEXPORT (Peter 15-09)". **Besluiten Peter 16-09 (geen migratie):** punten = omzet zonnebank 21 % bij verkoop (check "Puntenwaarde bekend" vervalt), tegenzijde per betaalwijze (PIN/kas/Stripe/kasverschil/storting) mét defaults op naam uit het rekeningschema en RLZ-vorm AFLETTERING (Receipt blijft open post; PIN/Stripe via actie 15, storting direct op kas), bank-matchmotor stap "omzetbatch-post" (Stripe +1…+7 d nooit vóór de omzetdatum), reconciliatie `tussenrekening_open` > 14 d, pilates btw laag/hoog per categorie + combi pro rato (batch → 30 d → 50/50 oranje), Stripe = EU-dienst verlegd, Beheerder-blok "Omzetbronnen" op de tab Boeken & AI — zie BESLISSINGEN "OMZETBRONNEN — BESLUITEN PETER 16-09 (tegenzijde, stores, btw, combi, Stripe)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Omzetbron coffeeshop ProfX Journaal + bruto/netto-schakelaar (Peter 16-09, screenshot De Bazar Apeldoorn; migratie 0150):** herkenning op INHOUD vóór de AI-classificatie (`omzet/bronnen/herkenning.py`, PDF-tekstlaag "ProfX Journaal"/"ProfX Margerapport" → kassarapport, géén AI), deterministische parser per ARTIKELGROEP (niet de artikellijst; periode 05:00→05:00 = kassadag = boekdatum; sluitcontroles als check-rijen), btw-klasse-defaults Wiet/Hash/Joints/Edible vrijgesteld (Edible mét bevestig-chip) · Dranken/Snacks laag · Headshop hoog, margerapport uit dezelfde mail = kostprijs per groep (zelfde dag gebundeld, weekrapport = eigen document mét periode-dekking; dagscherm toont live "kostprijs: weekrapport N verwacht/gekoppeld/geboekt"), omzetscherm herbouwd naar `mockup/omzet-kassarapport-v2.html` (één tabel omzet · btw · inkoopwaarde · marge, twee kaarten, "Boeken (2 documenten)"), kopje NETTO/BRUTO klikbaar in inkoop- én omzetscherm (`document/bedragModus.ts`, cent-exact, voorkeur per gebruiker, geen tegenwaarde onder de cel), profiel "Winkel / kassa" afgeleid + Beheerder-override (`kassa_profiel`, chip/filter, Omzetbronnen-blok), lees-only CLI `kassarapporten-in-inkoopstroom` — zie BESLISSINGEN "OMZETBRON COFFEESHOP PROFX JOURNAAL + BRUTO/NETTO-SCHAKELAAR (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Omzet — store → administratie platformbreed + Van Boxtel-herkenning + dagelijkse bevinding kassarapport-in-werkvoorraad (Peter 16-09 avond; Sunshine Island = eigen BV; migratie 0151):** één tabel `omzet_store_routering` (genormaliseerde "Store Used" → administratie, unieke storenaam, actief/ontkoppeld, audit) als enige bron (`app/omzet/bronnen/stores.py`), Beheerder-blok "Stores" op Instellingen › Boeken (`StoresBlok.tsx`, registry-anker `stores`), per-administratie-lijst alleen nog afgeleid ("stores die hier landen", PUT weigert `stores`); intake: dagstaat volgt de store ongeacht mailbox (onbekende store → verzamelbak `omzetbron_store_onbekend: X` + "Stores koppelen →"), kascheck volgt de dagstaat uit dezelfde mail of de enige open dagstaat van die dag; data-stap `omzet-stores-migreren [--schrijf]`; Van Boxtel = ProfX-journalen (lees-only gemeten 14/14 `profx_journaal`, geen nieuwe vingerafdruk); reconciliatie-soort `kassarapport_in_werkvoorraad` mét actie "Type wijzigen → kassarapport" (`POST /reconciliatie/bevindingen/{id}/type-wijzigen-kassarapport`), lokale toets ook voor Odoo-administraties; tellers `omzetbron_herkenning` (LET-OP `store_onbekend` → `/instellingen/boeken#stores`) en `kassarapport_inkoopstroom` — zie BESLISSINGEN "OMZET — STORE → ADMINISTRATIE PLATFORMBREED + VAN BOXTEL-HERKENNING (Peter 16-09 avond)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verkoopfactuur-boekpad (Vastly, §2d)** — GEBOUWD + GETEST (2026-08-09), Entity = de échte huurder, CreditNote 381
  achter `creditnota_381_ingeschakeld` (AAN sinds 2026-08-10); verkoop-autoboeken opt-in per is_vastgoed-administratie
  (migratie 0051). Zie BESLISSINGEN "Vastly-verkoopfactuur-boekpad" + "VERKOOP-AUTOBOEKEN OPT-IN".

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Omzetboekingen (omzetmodule, Receipts, omzet-autoboeken) (CLAUDE.md `ed6d176` r. 700–737)

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

### Domeinbeslissingen — Verkoopfactuur-boekpad (Vastly, §2d) + verkoop-autoboeken (CLAUDE.md `ed6d176` r. 738–766)

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

### Koppelvlak vastgoedmodule — Kostenflow-omkering + boekstand-events (v1.14) (CLAUDE.md `ed6d176` r. 1412–1427)

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

### Koppelvlak vastgoedmodule — Route A projectaanmaak-naar-RLZ (§5, v1.16) (CLAUDE.md `ed6d176` r. 1428–1450)

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

### Koppelvlak vastgoedmodule — Registersync §8 (v1.18/v1.19) (CLAUDE.md `ed6d176` r. 1451–1468)

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

### Koppelvlak vastgoedmodule — §2d-uitbreidingen v1.10 (AccountingCost, consument, waarborg) (CLAUDE.md `ed6d176` r. 1469–1483)

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

### Koppelvlak vastgoedmodule — v1.11-addenda (creditnota 381, factuur_afgeletterd, échte huurder) (CLAUDE.md `ed6d176` r. 1484–1495)

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

### Koppelvlak vastgoedmodule — Vastly-verkoopfacturen (§2d, v1.9) (CLAUDE.md `ed6d176` r. 1496–1500)

- **Vastly-verkoopfacturen (§2d, v1.9)**: e-mail-intake routeert op de vaste UBL-markering
  `cac:AdditionalDocumentReference/cbc:ID = "VASTLY-VERKOOP"` (nooit op afzender) → omzetkant
  (SalesInvoice). Geen/kapotte markering of NLCIUS-invalide UBL → verzamelbak "Niet toegewezen",
  nooit stil naar inkoop. Intake gebouwd 2026-08-07; boekpad gebouwd 2026-08-09 (zie
  "Verkoopfactuur-boekpad" hierboven).

### Koppelvlak vastgoedmodule — WOZ-zij-extractie (§2e, v1.9) (CLAUDE.md `ed6d176` r. 1501–1504)

- **WOZ-zij-extractie (§2e, v1.9)**: uit de OZB-aanslag (die wij gewoon als kostenfactuur boeken)
  extraheren wij jaargebonden WOZ-regels — mens bevestigt, waardepeildatum extraheren-en-bevestigen
  (nooit afleiden) + deterministische plausibiliteitscheck tegen 1 jan (belastingjaar − 1) —
  geleverd via `platform.woz_beschikking` (append-only, patroon §2c). Bouw in fase 2.
