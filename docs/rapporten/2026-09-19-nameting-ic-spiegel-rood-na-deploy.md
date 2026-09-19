# Nameting ná deploy: 174 × `ic_spiegel_rood` → 0, aansluitingsblok leeft, wachtrij-trigger — meting 19-09 (image `a731dd4`)

**Opdracht:** `opdrachten/gedaan/2026-09-19-nameting-ic-spiegel-rood-en-wachtrij-na-deploy.md` (vervolg op
`docs/rapporten/2026-09-19-ic-spiegel-rood-174-wachtrij-trigger-en-tellers.md`, fix-commit `27c0950`).
**Werkt in productie: JA** voor de twee gefixte blokken (IC-verkoopkant + aansluitingsblok), lees-only gemeten op de gedeployde
job-image; **niet gemeten** (kan pas ná de échte run van 20-09 06:30): de automatische sluiting van de 174 open bevindingen, de
aandacht-teller 340 → ≤ 166 en de wachtrij-teller `trigger_gebundeld` (sinds de deploy nog geen bulk-upload). Vervolg-opdracht
`opdrachten/inbox/2026-09-20-nameting-ic-spiegel-rood-echte-run-en-aansluiting-alleen.md`. Geen migratie, geen RLZ-write.

## Stap 0 — deploy-check (groen)

- `main..origin/main` = 0 (fetch 17:26). Fix-commit `27c0950` ∈ `a731dd4` (HEAD).
- deploy.yml run 35451558371 (`a731dd4`) success 15:21 UTC; service `rlz-backend` én jobs `rlz-reconciliatie` + `rlz-extractie-wachtrij`
  op `europe-west4-docker.pkg.dev/rlz-boekhouding/rlz/backend:a731dd4afb02…` (gelezen met `gcloud run jobs describe --format=json`;
  de `value(template.template…)`-vorm geeft leeg — via JSON lezen).

## 1. IC-blok — `reconciliatie-alles --alleen intercompany --lees-only` (executie `rlz-reconciliatie-whzvz`, 15:28 UTC)

| Relatie Kempen Facilities → | vóór (run 772e6c3c, 04:30 UTC, image vóór fix) | ná (whzvz, image `a731dd4`) |
|---|---|---|
| Veldhoven Recreatie | 731 verkoop / 829 inkoop, 730 gematcht, spiegelparen 0/94 ROOD | 826 / 829, 825 gematcht (824 nummer + 1 bedrag), **94/94 groen** |
| Oirschot Recreatie | 343 / 374, 340 gematcht, 0/34 ROOD | 377 / 374, 374 gematcht, **34/34 groen** |
| Molenhof Verhuur | 270 / 299, 270 gematcht, 0/28 ROOD | 298 / 299, 298 gematcht, **28/28 groen** |
| Molenhof Beheer | 99 / 11, 2 gematcht (alleen bedrag), 0/11 ROOD | 110 / 11, 11 gematcht op nummer, **11/11 groen** |
| Mantelzorgwoningen Midden Nederland | 44 / 51, 44 gematcht, 0/7 ROOD | **51 / 51, 51 gematcht, 7/7 groen** (exact de verwachting) |
| Kempen Chalets · Oirschot Vastgoed Beheer | 53/53 · 30/30, spiegelparen 0/0 | ongewijzigd |

- **`ic_spiegel_rood`: 174 → 0** (grep over de volledige uitvoer; ook 0 in de volledige run `txspn`). 27 IC-paren → 20 handelsrelaties.
- **In meting:** `ic_ontbreekt_bij_verkoper` 6 → 5 (verdwenen: KF → Veldhoven 24711601 € 29,91 26-08-2025 — nu via Receipts gematcht).
  De opdracht-aanname "daalt met de 174 spiegels" klopte niet: de spiegels telden vóór de fix als `ic_spiegel_rood` (fout), niet
  óók als `ic_ontbreekt_bij_verkoper`. `ic_ontbreekt_bij_ontvanger` 205 → 207 (+2, beide KF → Molenhof Beheer 24712908 € 6.352,50 en
  24712909 € 13.135,55, 01-06-2026: verkopen die vóór de fix onzichtbaar waren en géén inkoop bij Molenhof Beheer hebben — geen
  doorbelastingsboekingen in de module: `doorbelasting_boeking` in KF-scope kent voor Molenhof Beheer alleen twee gestorneerde
  runs 24713189/24713224). `ic_bedrag_verschilt` 2 → 2. Universal Nederland → Universal Steigerbouw 509/404 ongewijzigd (de
  `factuur=None bedrag=0.00`-rijen stonden er vóór de fix ook — geen bijvangst van de Receipts-unie).
- Job-exit 1 = "afwijkingen aanwezig" (verwacht bij lees-only; 8 LET-OP's "IC-tegenrelatie onbekend" ongewijzigd).

## 2. Aansluitingsblok — leeft (valse nul weg)

- Meetrecept-stap 2 noemde `--alleen doorbelasting_aansluiting`; **die keuze bestond niet in de CLI** (executie `2w5wh`: argparse
  "invalid choice", exit 2) — het blok stond wél in `run.BLOKKEN` en in de blokkenlijst, niet in de hard gecodeerde `choices=`.
  Gemeten via de **volledige** `reconciliatie-alles --lees-only` (executie `rlz-reconciliatie-txspn`, 15:30–15:45 UTC, log via
  Cloud Logging — zie "Procesles"). Fix in deze run: `choices=_reconciliatie_run_blokken()` = `run.BLOKKEN` (één bron), guard
  `tests/unit/test_reconciliatie_alleen_keuzelijst.py` (11 passed); meetbaar ná de volgende deploy (vervolg-opdracht stap 4).
- Uitkomst: **"1 bron-administratie(s) mét whitelist"** (was 0 sinds 16-09), **Kempen Facilities: 8 doelentiteiten, 1758 verkoop /
  1660 inkoop gelezen, 1652 sluiten; 108 afwijkingen, 0 fouten.** De verwachting "0 afwijkingen" uit de opdracht klopte niet — het
  blok had nog nooit iets getoetst, dus er was geen basis voor die nul. Kempen Chalets/Rubicon: geen regels (geen bevinding).

| Soort (blok `doorbelasting_aansluiting`) | Doel | N | Duiding |
|---|---|---|---|
| `da_ontbreekt_in_doel` | Molenhof Beheer | 99 | KF-verkoopfacturen aan Molenhof Beheer (15-08-2025 … 2026, € 53 – € 76.021) zonder inkoop bij Molenhof Beheer op enig KF-crediteurrecord — dezelfde 99 die het IC-blok als `ic_ontbreekt_bij_ontvanger` (in meting) telt: één feit, twee blokken |
| `da_ontbreekt_in_doel` | Oirschot Recreatie | 3 | 24712615 € 245,21 (02-04), 24712648 € 275,28 (20-04), 24712802 € 102,73 (11-05) |
| `da_inkoop_zonder_verkoop` | Veldhoven Recreatie | 3 | **dezelfde drie nummers**: verkocht aan Oirschot Recreatie, als inkoop geboekt bij Veldhoven Recreatie — entiteit-verwisseling aan één van beide kanten |
| `da_bedrag_afwijkt` | Veldhoven Recreatie | 2 | 24712869 verkoop € 69,82 / inkoop € 0,00 en 24712873 verkoop € 0,00 / inkoop € 69,82 — nummer-verwisseling bij het inboeken |
| `da_inkoop_zonder_verkoop` | Molenhof Verhuur | 1 | 24713191 € 25,41 16-08-2026 — dag van de kliktest-storno's van Peter (spiegel bleef staan ná storno van de bron) |

- **Let op voor de run van 20-09 06:30:** de `da_*`-soorten staan op code-default `actie` (geen DB-override; `reconciliatie_instelling
  .soort_standen` = `{rc_sluit_niet: meten, ic_ontbreekt_bij_ontvanger: meten}`). `da_ontbreekt_in_doel` produceert 102 > 50 → de
  explosie-rem zet de soort automatisch terug naar `meten` mét systeemfout-LET-OP `bevindingssoort_explodeert` (regel 17-09). Dat is
  ontworpen gedrag, geen fout; de 9 andere afwijkingen (Oirschot/Veldhoven/Molenhof Verhuur) komen wél in de actiemail. Geen
  handmatige stand-wijziging gedaan (Beheerder-besluit).

## 3. Leesreplica — stand vóór de échte run (kan pas 20-09 veranderen)

- `reconciliatie_run`: laatste `klaar` = 772e6c3c (scheduler 19-09 04:30 UTC, **vóór de deploy van 15:21 UTC**); geen "Nu draaien"-run.
  `reconciliatie_bevinding` van die run: 174 × intercompany/fout/`ic_spiegel_rood` + 2 × automatisering/let_op. 18-09: 162.
- Audit `reconciliatie_auto_gesloten`, aandacht 340 → ≤ 166: **niet meetbaar op 19-09** — lees-only runs leggen niets vast (bewust);
  een échte run forceren = actiemail naar kantoor buiten het dagritme, niet gedaan. Meting = vervolg-opdracht 20-09 stap 1–3.

## 4. Extractie-wachtrij-tellers

- `gcloud run jobs executions list --job rlz-extractie-wachtrij` per uur: 18-09 11:00 UTC **118** (de bulk), daarna élk uur exact 6
  (scheduler-vangnet) t/m 19-09 14:00, 15:00 UTC 3 (deel-uur). Sinds de deploy (15:21 UTC) geen bulk-upload → `trigger_gebundeld`
  en "geen 429" niet meetbaar; regel voor de vervolg-opdracht.

## 5. Nazorg BLOW c9ba6d8d — klikpunt (schrijvende job geweigerd)

- Replica (BLOW-scope 5419878c): document `c9ba6d8d-ad7f-…` "2023-12-13_div. crediteuren_20230872.pdf" status `te_controleren`,
  `laatst_gewijzigd_op` 18-09 11:05:14.6 (de late flush), tijdlijn eindigt 11:05:20 `te_controleren → afgevoerd_duplicaat`
  (afwijzing f8517c2b, automatisch, duplicaat van `0bbb1a1d-…`, zelfde sha256 `f0b910f5…`); de afwijzing staat nog `open` — precies
  de stale overschrijving uit het vorige rapport.
- `duplicaten-backfill --dry-run --administratie 5419878c` op de job-image (executie `rlz-reconciliatie-k57ql`): **BLOw B.V: 173
  toetsbaar, 2 kandidaten, 1 af te voeren** = exact dit document ("[te_controleren, bestand] → duplicaat van 20230872"), het origineel
  0bbb1a1d overgeslagen als "zelf het origineel". Aantal = verwachting (1).
- De schrijvende variant (`gcloud run jobs execute … duplicaten-backfill --administratie 5419878c`, gedeployde image) is door de
  auto-mode-classifier geweigerd → **klikpunt Peter**: in de werkvoorraad BLOW het document 2023-12-13_div. crediteuren_20230872.pdf
  (ontvangen 18-09-2026, id c9ba6d8d) via "Afvoeren als duplicaat" afvoeren, óf `gcloud run jobs execute rlz-reconciliatie
  --args="^|^-m|app.cli|duplicaten-backfill|--administratie|5419878c-ca11-4f02-98d7-b14325ff8206"` (dry-run bewees 1). NB: beide
  routes maken een tweede `Afwijzing`-rij naast de open f8517c2b (`_open_afwijzing` leest `.first()` — geen fout, wel dubbel spoor);
  netter zou zijn: `duplicaat-status-backfill` óók laten kijken naar `te_controleren` + open duplicaat-afwijzing (CAS-race-signatuur)
  zodat de bestaande rij hergebruikt wordt — niet gebouwd, voorstel.

## 6. Procesles (herhaald incident)

`scripts/gcp/nameting.sh` is tijdens de lopende volledige run bewerkt (één commentaarregel toegevoegd) → bash las het script
incrementeel verder en strandde ná de job-executie op "regel 124: syntaxfout" (exit 2); de job zelf was klaar (exit 1 = afwijkingen)
en de uitvoer is uit Cloud Logging gelezen (executienaam `txspn`, 2447 regels). Zelfde les als 17-09 (memory
"script-niet-bewerken-tijdens-achtergrondrun") — nu als regel in `docs/regels/werkloop-productie.md`.

## 7. Wat er gewijzigd is (code)

- `backend/app/cli.py`: `--alleen`-keuzelijst van `reconciliatie-alles` = `run.BLOKKEN` via `_reconciliatie_run_blokken()`.
- `backend/tests/unit/test_reconciliatie_alleen_keuzelijst.py` (nieuw, 11 tests): élk blok geldige keuze (eigen FOUT-regel, geen
  argparse-SystemExit), keuzelijst == BLOKKEN, onbekend blok blijft argparse-fout.
- `scripts/gcp/nameting.sh`: voorbeeldregel `--alleen doorbelasting_aansluiting`.
- Docs: BESLISSINGEN-rij "Systeemfout ic_spiegel_rood 174×" niet gemeten → gemeten 19-09; regels-alinea's reconciliatie /
  doorbelasting-intercompany / werkloop-productie; vervolg-opdracht 20-09 in de inbox.

## Klikpunten

1. BLOW: document 2023-12-13_div. crediteuren_20230872.pdf (id c9ba6d8d, ontvangen 18-09-2026) opnieuw afvoeren als duplicaat van
   0bbb1a1d — dry-run op de job-image bevestigde exact 1 af te voeren (sectie 5).
2. Kempen Facilities → Molenhof Beheer: 99 verkoopfacturen zonder inkoop bij Molenhof Beheer (15-08-2025 t/m 2026, € 53 – € 76.021,
   bron run-log `rlz-reconciliatie-txspn` blok doorbelasting_aansluiting) — worden die bij Molenhof Beheer buiten KF-crediteurrecords
   geboekt (RC-memoriaal?) of ontbreken ze? Bepaalt of de soort `da_ontbreekt_in_doel` ná de explosie-rem terug naar `actie` mag.
3. Oirschot Recreatie ↔ Veldhoven Recreatie: 24712615 € 245,21 (02-04-2026), 24712648 € 275,28 (20-04-2026), 24712802 € 102,73
   (11-05-2026) verkocht aan Oirschot, ingeboekt bij Veldhoven (bron: run-log txspn) — welke kant is fout?
4. Veldhoven Recreatie 24712869/24712873 € 69,82 (run-log txspn): nummer-verwisseling bij het inboeken — corrigeren in RLZ (mens).
5. Molenhof Verhuur 24713191 € 25,41 (16-08-2026, run-log txspn): achtergebleven spiegel van een kliktest — storno of accepteren mét reden.

## Suite
`tests/unit` + `tests/reconciliatie/test_rlz_dubbel.py`: 382 passed, 1 skipped (2:45). Docs-guards (CLAUDE.md↔BESLISSINGEN, regels-INDEX, rapporten-INDEX, gelezen regels, klikpunten, nameting-workflow): 32 passed. Nieuwe guard 11 passed. Gouden set niet geraakt (geen wijziging onder app/intake, app/extractie, app/documenten of frontend).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/reconciliatie.md` (131 regels — stand vóór de run)
- `docs/regels/doorbelasting-intercompany.md` (157 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (142 regels — stand vóór de run)
