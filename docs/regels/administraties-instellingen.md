# Regels — Administraties, RLZ-/Odoo-koppelingen, sync en instellingen

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Instellingen › Administraties (archiveren, nooit verwijderen), wizard mét rechten-probe, eerste sync, RLZ-check, groepen, administratienaam volgt de bron, Odoo-koppelwizard, terugkerend-signaal, verplaatsen.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Odoo-koppelwizard nazorg 14-09 (kliktest Peter 14-09; besluit failsafe drie lagen; migratie 0140):** memoriaal-dagboek op TYPE (general minus systeemdagboeken EXCH/CABA/TAX/STJ; MISC bij Universal 1–4, MEM bij NL-template 5/7/8/9 — de module past zich aan, niet Odoo), failsafe dubbele Odoo-koppeling in drie lagen (unieke index host+company, 409 mét leesbare reden + audit op koppelen/overstap/leesbron/CLI's, wizard grijs mét reden + Reeleezee-signaal mét verplichte bevestiging), VGG company 6 = migratiedoel en nooit een nieuwe administratie, rechten-probe per company als eigen request (`POST /instellingen/odoo/probe`, budget `odoo_probe_timeout_seconds`), URL-normalisatie naar scheme + host (`app/odoo/ids.py::normaliseer_odoo_url`/`odoo_host` = de enige host-normalisatie) + foutvertaling zonder exception-namen — zie BESLISSINGEN "ODOO-KOPPELWIZARD NAZORG 14-09 — MEMORIAAL OP TYPE, FAILSAFE DUBBELE KOPPELING, PROBE PER COMPANY, URL-NORMALISATIE" + odoo-verkenning "Dagboekcodes per company — 14-09".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Rechten-probe = eerste-sync-routes + herprobe met de opgeslagen login (blok C bundel 10-09, bevinding Baard; geen migratie):** één bron `app/rlz/leesroutes.py` voor probe-set én sync-paden (fail-closed test `tests/rlz/test_leesroutes.py`), wizard/wijzigen/dearchiveren proben ná de invoer-probe óók in de OPGESLAGEN vorm (wrap → unwrap → verse client = de credential-resolutie van de sync; rood = niets opgeslagen), letterlijk RLZ-antwoord (≤ 300 tekens) + RLZ-recht per route in melding/DTO/audit, `POST /administraties/{id}/rlz-check` = herprobe met de store-login, eerste-sync-401/403 = leesbare LET-OP-stand per onderdeel — zie BESLISSINGEN "RECHTEN-PROBE = EERSTE-SYNC-ROUTES + HERPROBE MET DE OPGESLAGEN LOGIN"

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Groepskenmerk op administratie (blok 8 run 11-09 middag, opdracht Peter 11-09; migratie 0135):** `platform.groep` (naam, korte unieke code, actief — archiveren, nooit verwijderen; RLS: iedereen leest, muteren alleen Beheerder) + `administratie.groep_id` (hoogstens één groep); veld "Groep" op Instellingen › Administraties › ‹administratie› › Algemeen mét inline "Nieuwe groep…" (code-voorstel uit de naam, bewerkbaar) en optioneel in de wizard (leeg = geen groep, nooit een blokkade); chip + filter in de administratielijst, blok "Groepen" (hernoemen/archiveren); filter "Groep" op de klantenlijst (`?groep=` → `GET /werkvoorraad/overzicht?groep_id=`) en Inzicht › Reconciliatie (`?groep_id=`) — administratie is een FILTER, dit is er één meer (KP7); routes `GET/POST /groepen`, `PUT /groepen/{id}`, `PUT /administraties/{id}/groep`; audit `groep_aangemaakt`/`groep_gewijzigd`/`administratie_groep_gewijzigd` oud→nieuw; "Kempen groep" NIET in code — Peter maakt 'm via de UI; consolidatie/eliminatie = liquiditeit-mockup, niet hier — zie BESLISSINGEN "GROEPSKENMERK OP ADMINISTRATIE". **Bulk-toewijzing (Peter 16-09; geen migratie):** per groep "Administraties toevoegen…" (ScopeLijst-dialoog, verhuizen mét bevestiging, "+N −M") + bulkbalk-actie "Toewijzen aan groep…"; `PUT /groepen/{id}/administraties` = één transactie, audit per rij — zie BESLISSINGEN "GROEPSKENMERK OP ADMINISTRATIE" subkop "Bulk-toewijzing 16-09".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Groepssaldi debiteuren/crediteuren per groep (Peter 16-09; lees-only; migratie 0149 cache):** rekeningen uit de bron (RLZ RGS `BVorDeb…`/`BSchCre…` of naam, Odoo `account_type`; nooit 1300/1600), saldo Σ Debit−Credit, drie kolommen bruto = zonder-IC + IC (IC = open posten op groepsmaatschappijen uit `intercompany_relatie`), webfilter = `ongeldig` per administratie; CLI `groep-saldi --groep "Kempen groep"` (nameting-allowlist, live) + kaart "Groepssaldi" op de klantenlijst bij actief Groep-filter (nachtelijke stand uit `sync-alles`, RLS = "N van M in je scope") — zie BESLISSINGEN "GROEPSSALDI DEBITEUREN/CREDITEUREN (Peter 16-09)".

<!-- toegevoegd 21-09-2026, opdracht "BUG-groepssaldi-alle-35-administraties-fout-rlz-enumfilter-en-odoo-deprecated" -->
- **Groepssaldi — productiefout 16→21-09 (BUG 21-09; geen migratie; BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)"):** de kaart en `groep-saldi` leverden
  vanaf de deploy van 16-09 voor álle 35 leden van "Kempen groep" status `fout`: (1) RLZ weigert een int-literal op het enum-veld
  `AccountType` in `$filter` (400 "'Reeleezee.DTO.AccountTypeEnum' and 'Edm.Int32'") — de Ledgers-lezer filtert sinds 21-09 alleen
  `IsTotalAccount eq false` (+ `$expand=SystemAccountList`, gepagineerd `$top/$skip`) en toetst de balanszijde client-side in
  `vind_rekeningen_rlz`; regel: RLZ-enum-velden nooit als int in `$filter`, geen enum-literal-syntax zonder STAP-0-bewijs (guard
  `tests/unit/test_rlz_filter_enum_guard.py`, lijst `ENUM_VELDEN` alleen mét bewijs uitbreiden); (2) Odoo 19 kent op `account.account`
  geen `deprecated` (500 "Invalid field") — het domein van `OdooBron.rekeningen` is sinds 21-09 `company_ids in [company]` +
  `account_type` + `active = True`, identiek aan `odoo/sync.py::lees_grootboek`; regel: een Odoo-domein gebruikt alleen velden die
  `odoo/sync.py` live bewezen gebruikt (guard `tests/groepen/test_saldi.py::TestOdooDomein`). Een client-stub in een test speelt het
  bron-gedrag na (assert op de letterlijke `$filter`/het domein) — mocken zonder die toets is precies hoe deze bug vijf dagen
  onzichtbaar bleef. CLI `groep-saldi --groep … --stand` toont de nachtelijke cache-stand zonder lezer-scope (nameting); het signaal bij
  `fout` staat in `docs/regels/reconciliatie.md` (`groep_saldo_fout`). Werkt in productie: niet gemeten (vervolg-opdracht `niet vóór:
  2026-09-22 09:00`, dispatch-onderdeel `groep-saldi`).
  **Gemeten 22-09 (BESLISSINGEN alinea "Gemeten 22-09"; rapport `docs/rapporten/2026-09-22-nameting-groepssaldi-na-deploy.md`):** de
  Ledgers- en Odoo-fix werken (geen 400 op Ledgers meer, Bonte Hoeve/Nieuwenhoven `ok`), maar de stand van 22-09 gaf 29/35 leden `fout` op de
  VOLGENDE call: `saldi.ic_open` filterde `Status eq 2` op Sales-/PurchaseInvoices → 400 "'Reeleezee.DTO.DocumentStatus' and 'Edm.Int32'" —
  `Status` is óók een enum (STAP-0-tabel stond al in api-verkenning; de 21-09-notitie die het tegendeel beweerde is gecorrigeerd). Fix 22-09
  (geen migratie): `Status` in `$select`, client-side `STATUS_OPEN` (2); `ENUM_VELDEN = ("AccountType", "Status")`; stub speelt de 400 na.
  Regel aangescherpt: ná een enum-fout op één call álle `$filter`-strings van de motor nalopen (`docs/regels/werkloop-productie.md` 22-09).
  Werkt in productie: RLZ-Ledgers/Odoo JA, open posten NIET GEMETEN tot de deploy van 22-09 + `sync-alles` 23-09 07:00 (vervolg-opdracht
  `niet vóór: 2026-09-23 09:00`).

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Administratienaam — bewerkbaar + volgt de bron (Peter 15-09; casus Camping Nieuwenhoven → "Strandpark Zilverduynen" in Odoo; migratie 0144):** veld "Naam" op Instellingen › Administraties › ‹administratie› › Algemeen (Beheerder-only, inline, `PUT /administraties/{id}/naam`, audit `administratie_naam_gewijzigd` oud→nieuw, bezet = 409); `naam_bron` 'odoo'|'rlz'|'mens' — ≠ mens volgt de bronnaam (Odoo `res.company.name` / RLZ `Administrations.Name`, één leesbron per backend) bij élke stamgegevens-sync (audit `administratie_naam_gevolgd`), mens = nooit overschrijven maar chip "in Odoo/Reeleezee heet deze administratie nu ‹naam›" + "Naam overnemen"; data-stap CLI `administratie-naam-bron-backfill` (dry-run default) — zie BESLISSINGEN "ADMINISTRATIENAAM — BEWERKBAAR + VOLGT DE BRON (Peter 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verplaatsen naar een andere administratie — RLS-uitzondering binnen de SECURITY DEFINER-functie (blok 1 run 11-09 middag; bug Peter 11-09 Kempen Facilities → Universal Verkoop; migratie 0132):** 0080 werkte op Cloud SQL nooit (FORCE RLS geldt ook voor een eigenaar zonder superuser/BYPASSRLS) — fix = helper `platform.verplaatsing_document_id()` + per tabel één PERMISSIVE policy `<tabel>_verplaatsing` die alleen bínnen de definer-context leeft (`current_user IS DISTINCT FROM session_user`), functie zet de GUC transactie-lokaal; `verplichting_match`/`regel_gb_classificatie` verhuizen nu ook mee. RLS-weigering = systeemfout "automatisch gemeld": `app/db/rls_weigering.py` (audit `rls_weigering` uit router én centrale handler), bewakingsprobe `rls_weigering`, beheer-LET-OP in de reconciliatie; testregel: `tests/security/rls_eigenaar.py::productie_eigenaar` maakt een SECURITY DEFINER-test pas bewijskrachtig (conventies §RLS punt 6) — zie BESLISSINGEN "VERPLAATSEN — RLS-UITZONDERING BINNEN DE SECURITY DEFINER-FUNCTIE".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Eerste sync ná groene probe: 403 = herproberen (blok 3 run 11-09 middag; bevinding Peter Baard / Box Beheer / Kempen B.V.; migratie 0133):** een 403 op een route die de opgeslagen rechten-probe groen had is geen fout maar "RLZ zet rechten door" — run-status `rechten_onderweg` mét `pogingen`/`volgende_poging_op`, automatisch herproberen 5/15/60 min, daarna elk uur, max 24 u (wekker = stap `eerste_sync_wekker` in de kwartier-job `rlz-bewaking`, voertuig = bestaande job `rlz-eerste-sync`, fallback in-process), alleen niet-klare onderdelen opnieuw, audit per herpoging; 401/5xx/403-op-niet-groene-route = direct fout; ná 24 u `fout` mét letterlijk RLZ-antwoord; chip "⏳ RLZ zet rechten door — opnieuw over N min" (tooltip RLZ-antwoord), "Sync opnieuw starten" = dezelfde run direct; reconciliatie-teller `eerste_sync_herproberen` + LET-OP `rechten_na_24u` mét deeplink naar de administratie — zie BESLISSINGEN "EERSTE SYNC NÁ GROENE PROBE — 403 = HERPROBEREN".

<!-- uit CLAUDE.md § Stack & platform -->
- **Administratie toevoegen via de UI** (wizard mét verplicht groene rechten-probe, eerste sync als achtergrondrun,
  `verkoopmodule_afwezig` als ENIGE niet-blokkerende probe-uitkomst, `is_vastgoed`-Beheerder-toggle;
  `app/beheer/onboarding.py`) — zie BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08" punt 5, "VERZAMELRUN 27-08" punt 5,
  "SPOEDOPDRACHT 01-09" blok A, "AVONDRUN 26-08".

<!-- uit CLAUDE.md § Stack & platform -->
- **Terugkerende-facturen-signaal** (`app/terugkerend/`, deterministisch, alleen signaleren; migratie 0090) — zie
  BESLISSINGEN "OPDRACHT 30-08 (2)" blok B.

<!-- uit CLAUDE.md § Stack & platform -->
- **Instellingen › Administraties v2/v3** (compacte tabel + detailPAGINA per administratie mét tabs; ARCHIVEREN,
  nooit verwijderen; migratie 0089) — zie BESLISSINGEN "OPDRACHT 30-08 (2)" blok A + "INSTELLINGEN V3".

<!-- uit CLAUDE.md § Werkwijze -->
- **RLZ-check als knop (nachtrun 10/11-09 blok 1; geen migratie):** knop "RLZ-check" op Instellingen › Administraties › ‹administratie› › Algemeen (Webservice-gegevens) → `POST /administraties/{id}/rlz-check`, resultaat inline per leesroute (stand, letterlijk RLZ-antwoord ≤ 300 tekens, RLZ-recht) + "Administraties die deze login ziet: N" mét eigen-id-markering, "Sync opnieuw starten" bij groene check ná rode eerste sync, sync-fout-chip mét tooltip — zie BESLISSINGEN "RLZ-CHECK ALS KNOP".

<!-- toegevoegd 22-09-2026, opdracht "BUG-niet-btw-plichtige-administratie-btw-gesplitst-vgg-lacy-lion-te-weinig-betaald" -->
- **Kenmerk "Btw-plichtig" op de administratie (BUG Peter 22-09, casus VGG / Studio Lacy Lion; migratie 0170; BESLISSINGEN "BTW-PLICHTIG PER
  ADMINISTRATIE — NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)"):** rij "Btw-plichtig" op Instellingen › Administraties ›
  ‹administratie› › Boeken & AI (anker `btw-plichtig`, registry-entry, Beheerder-only, `GET/PUT /administraties/{id}/btw-plichtig`, audit
  `administratie_btw_plichtig_gewijzigd` oud→nieuw, bron 'mens'); default true. **Bron = RLZ waar leesbaar:** de nachtelijke identiteit-sync
  (`sync-alles` → `intercompany/identiteit.sync_identiteiten`) leest `AdministrationSettings.EnableTaxReporting` mee uit dezelfde call — true
  bevestigt btw-plichtig mét bron 'rlz' (herkomst-chip "bevestigd uit Reeleezee"), false zet het kenmerk nooit zelf om maar maakt de
  administratie kandidaat (LET-OP "bevestig btw-status" in Inzicht › Reconciliatie mét deeplink; chip "Reeleezee: btw-aangifte uit" +
  twee linkbtn's "Blijft btw-plichtig" / "Niet btw-plichtig" op de rij); een mens-keuze wordt door de sync nooit overschreven. STAP-0 22-09:
  VGG false, Kempen Facilities/Rubicon/Arvum true; de tarievenset is overal de RLZ-standaardset (22) en zegt niets. Het gedrag van het
  kenmerk (prefill bruto, verborgen keuzelijst, harde check, PUT zonder TaxRate, verkoop/omzet/doorbelasting-doel) staat in `docs/regels/btw.md`.
  Data-stap: `btw-plichtig-zetten --administratie "Vastgoedgroep" --uit` op de job-image ná deploy (besluit Peter 13-09), overige
  administraties uit `btw-plichtig-kandidaten` ná Peters besluit. Werkt in productie: niet gemeten.

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Stack & platform — Instellingen › Administraties v2 (CLAUDE.md `ed6d176` r. 52–62)

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

### Stack & platform — Terugkerende-facturen-signaal (CLAUDE.md `ed6d176` r. 63–70)

- **Terugkerende-facturen-signaal (opdracht 30-08 blok B, benchmark-besluit Peter 29-08, migratie 0090
  — BESLISSINGEN "OPDRACHT 30-08 (2)" blok B):** `app/terugkerend/` — deterministisch (géén AI) per
  (administratie, crediteur): ≥ 3 facturen met regelmatig interval maand/kwartaal ±35 % (app-documenten +
  RLZ-boekingsgeheugen); signaal 1 "verwachte factuur ontbreekt" = oranje werkvoorraad-teller
  (`terugkerend_signalen`, kolom "Verwachte facturen") + scherm Inzicht › Terugkerende facturen
  (`/terugkerend`, snooze/afmelden per leverancier mét audit); signaal 2 "prijsstijging" boven de drempel
  (`terugkerend_prijsstijging_pct`, default 10, Beheerder) = chip op het controlescherm
  (`TerugkerendSignaal`) + in het overzicht; dagelijks meeliftend in `sync-alles`. Alleen signaleren.

### Stack & platform — Administratie toevoegen via de UI (wizard, eerste sync, facturatiemodule afwezig, is_vastgoed-toggle) (CLAUDE.md `ed6d176` r. 71–92)

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

### Referenties — verkenning/odoo-verkenning.md (Odoo STAP-0 + adapter fase 1, blok E, afrondingsrun, slotstuk) (CLAUDE.md `ed6d176` r. 1559–1568)

- `verkenning/odoo-verkenning.md` — **Odoo STAP-0 (02-09-2026, universal-steigers.odoo.com, Odoo 19 JSON-2):
  verbinding/inventaris, veld-voor-veld-mapping RLZ→Odoo, semantiekverschillen, twee live bewijs-cycli,
  beslispunten + klikpunten. Kernfeiten: multi-company-db (10 bedrijven, Universal Verkoop al live),
  boekdatum-default = maandeinde (altijd `date` expliciet), storno = reversal als apart document, bijlage
  ná posten (OCR auto_send). **Adapter FASE 1 GEBOUWD 03-09 (backend, blokken 0–D — BESLISSINGEN "ODOO-ADAPTER
  FASE 1" is canoniek voor de bouwstatus): port/registry `app/backends/` (`boekhoud_backend` = alleen routeringssleutel,
  domein vertakt nooit), `app/odoo/` (koppeling + probe + sleutelrotatie, stamgegevenssync naar dezelfde caches,
  materiaalbrug product.product, inkoop-adapter boeken = create + lock-date-poort + btw-cent-override ± € 0,02 +
  post-write-company-verificatie + bijlage ná posten, tegenboeken = reversal mét kruisverwijzing, Odoo als leesbron
  voorraad); Odoo-administratie = sentinel in `rlz_admin_id` → RLZ-resolutie fail-loud. **Blok E (kantoor-UI) GEBOUWD 03/04-09 (mockup `odoo-koppeling-ui.html` = norm: backend-blok op tab Algemeen mét paarse platformchip, één wizard met twee ingangen — backend-keuze als stap 1 van "+ Administratie toevoegen" resp. "Odoo koppelen…" = overstap mét verplichte overgangsdatum (migratie 0104, adapter-poort) óf alleen-lezen leesbron — en "Geboekt in Odoo · nr · company" mét reversal-kruisverwijzing) en de keten LIVE BEWEZEN 04-09 op company 1 (odoo-verkenning §7: BILL/2026/06/0001 ↔ RBILL/2026/09/0003; vijf adapter-gebreken in de run gefixt). BESLISSINGEN "ODOO-ADAPTER BLOK E + LIVE KETEN-CYCLUS 04-09".** **Afrondingsrun 04-09 (besluiten Peter 04-09 op de blok-E-beslispunten — BESLISSINGEN "ODOO-AFRONDINGSRUN 04-09" blokken 0/A+C1/B/C2/D): (A) een overstap (ingang B) heeft een VERPLICHTE mapping-stap RLZ-grootboek → Odoo-account op rekeningcode (`zelfde_code` groen, `code_verlengd` = RLZ 4808 ↔ Odoo 480800 oranje, anders mens kiest) + RLZ-btw → Odoo-tax (verlegd → "21% R", 0 %/vrijgesteld → synthetisch "Geen btw (0%)"), mens bevestigt de hele tabel, append-only `boekhouding.odoo_rekening_mapping` (migratie 0111, correctie = nieuwe versie + audit); het boekingsgeheugen vertaalt zijn observaties VÓÓR de engine via `app/odoo/mapping.py` (één lader `geheugen/service.py::laad_engine_observaties` + `regel_gb.laad_observaties`), `app_bevestigd` blijft — autoboek-opt-ins lopen door; wizard-stap "Rekeningen koppelen" + rij "Rekening-mapping" + corrigeer-dialoog (`OdooMappingTabel.tsx`); (C1) "Overgangsdatum wijzigen…" mét 409 zodra een Odoo-boeking vóór de nieuwe datum bestaat; (B) materiaalcatalogus + product-brug beschikbaar bij uren-opt-in ÓF Odoo-backend ÓF Odoo-leesbron (`materiaal/service.py::_administratie_met_catalogus_toegang`; bestellingen/transport blijven uren-gated); (D) Universal Verkoop (company 3) draait in de CLOUD als alleen-lezen leesbron mét knip 01-09-2026 (30 Odoo-facturen/83 regels, 0 dubbel); (C2) overstap-generale = draaiboek-script `verkenning/odoo_overstap_generale.py`. **SLOTSTUK 04-09 (besluiten Peter 04-09 — BESLISSINGEN "ODOO-SLOTSTUK 04-09" is canoniek per blok; migraties 0112 + 0113): de overgangsdatum is een KANTELDATUM, géén poort — nakomers mét factuurdatum vóór de overstap boeken óók in Odoo; de duplicaat-afhandeling kijkt over de backend-grens via de eigen DB-historie (`documenten/duplicaat_historie.py`, alleen voor overgestapte administraties: harde check rood mét RLZ-boekstuk + auto-afvoer, geen RLZ-calls) en de 409 op "Overgangsdatum wijzigen" is vervallen; valt een factuurdatum in een in Odoo afgesloten periode (lock dates), dan bepaalt de adapter de boekdatum zelf = hoogste geraakte lock date + 1 dag (Odoo zou 'm STIL naar het maandeinde schuiven — live bewezen, odoo-verkenning §9.1), `invoice_date` blijft de factuurdatum, zichtbaar als `boekdatum_verschoven` (tijdlijn, "Geboekt in Odoo", chip); tegenboeking houdt de lock-date-weigering. Derde mapping-soort `project` (RLZ-project → Odoo-analytic-account: voorstel op projectnummer groen / naam oranje / leeg mag; "aanmaken in Odoo" lookup-vóór-create; het geheugen vertaalt `project_id` via de mapping). Open boekvoorstellen worden ín de overstap hervertaald (`app/odoo/hervertaling.py`, `boekvoorstel_regel.overstap_vertaling`, chips "vertaald bij overstap"/"niet vertaalbaar — kies"). GET-catalogusroutes = PUT-rechten (Beheerder/B+P). Overstap-generale LIVE BEWEZEN 04-09 op de dev-omgeving (odoo-verkenning §9.3; één adapterbug gefixt: verdwenen RLZ-verlegd-tarieven). Open: knip Universal Verkoop (01-09 heeft facturen in BEIDE systemen — §9.2, beslispunt) en de Transport-tab voor Boekhouding mét meerwerk-recht (C2). De echte Universal-Steigerbouw-overstap volgt uitsluitend op een expliciete GO van Peter.**
