Domeinen: reconciliatie, doorbelasting-intercompany, werkloop-productie

# OPDRACHT 20-09 — Nameting ná de ÉCHTE run van 20-09 06:30: 174 × ic_spiegel_rood auto-gesloten, aandacht ≤ 166, `--alleen
# doorbelasting_aansluiting` werkt op de job-image — vervolg op docs/rapporten/2026-09-19-nameting-ic-spiegel-rood-na-deploy.md

Op 19-09 (rapport hierboven) is de fix `27c0950` lees-only nagemeten op image `a731dd4`: 0 × `ic_spiegel_rood`, spiegelparen
174/174 groen, aansluitingsblok leeft. Wat NIET meetbaar was op 19-09: de laatste ÉCHTE run (scheduler 04:30 UTC) draaide vóór de
deploy, dus de 174 open bevindingen stonden nog open en het audit `reconciliatie_auto_gesloten` was er nog niet. Deze opdracht
meet dat ná de run van 20-09 06:30 (NL).

**Voorwaarde (stap 0):** `git rev-list --count main..origin/main` = 0 (anders `git merge --no-ff origin/main`, nooit rebase); de
commit van deze nameting-run (keuzelijst `--alleen` = `run.BLOKKEN`) is gedeployd op service ÉN jobs (`gh run view` groen;
`gcloud run jobs describe rlz-reconciliatie --format=json` → image = service-image). Niet gedeployd = wachten.

## Meetrecept (lees-only)
1. Leesreplica (`scripts/gcp/db_lezen.sh … --als 2f2262cd-0423-4910-b7b5-335ba37a6ef5`, NULL-scope): laatste run mét
   `status='klaar'` is die van 20-09 04:30 UTC; `reconciliatie_bevinding` blok `intercompany` soort `fout` = 0 (was 174 in run
   772e6c3c van 19-09); `platform.audit_event` actie `reconciliatie_auto_gesloten` op 20-09 = aantal + reden (verwacht 174 verdwenen,
   één audit-rij per run of per bevinding — noteer wat het is). Blok `doorbelasting_aansluiting`: bevindingen per soort (verwacht 0;
   Kempen Chalets/Rubicon zonder boekingen = geen bevinding). VERWACHT (rapport 19-09): 108 afwijkingen, waarvan 99 ×
   `da_ontbreekt_in_doel` Molenhof Beheer + 3 Oirschot → 102 > 50 = explosie-rem: soort automatisch naar `meten` mét systeemfout-LET-OP
   `bevindingssoort_explodeert` + audit; `reconciliatie_instelling.soort_standen` krijgt `da_ontbreekt_in_doel: meten`. Toets dat dat
   gebeurd is; de 9 andere (3 × Veldhoven da_inkoop_zonder_verkoop, 2 × da_bedrag_afwijkt, 1 × Molenhof Verhuur) horen in de actiemail.
2. Inzicht › Reconciliatie: aandacht 340 → ≤ 166 (uit `reconciliatie_run.samenvatting` van de run van 20-09; noteer per blok).
3. Reconciliatiemail 20-09 (systeemmail uitgeschakeld — lees de run-rij `mail_status` en het run-log in Cloud Logging): herstelregel
   voor de 174 verdwenen fouten, geen nieuwe systeemfout, "Automatiseringen: alles gelopen" of de LET-OP's genoemd.
4. `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen doorbelasting_aansluiting --lees-only` → geen argparse-fout
   meer (19-09 gaf "invalid choice"), "1 bron-administratie(s) mét whitelist", KF: 8 doelen gelezen.
5. Tellers extractie-wachtrij: `gcloud run jobs executions list --job rlz-extractie-wachtrij` per uur ≈ 6 + 1 per batch; bij de
   eerstvolgende bulk-upload `trigger_gebundeld` > 0 en `vangnet_scheduler` 0 in de reconciliatiemail-regel "Extractie-wachtrij".
6. BLOW-nazorg c9ba6d8d (klikpunt Peter 19-09, dry-run bevestigde exact 1 af te voeren): staat het document intussen op
   `afgevoerd_duplicaat`? Zo niet → blijft klikpunt, herhaal het in het rapport (geen schrijvende job zonder Peter).
7. Rapportregel "werkt in productie: ja/nee" + INDEX; BESLISSINGEN-rij "Systeemfout ic_spiegel_rood 174×" alinea "Nameting 20-09".
