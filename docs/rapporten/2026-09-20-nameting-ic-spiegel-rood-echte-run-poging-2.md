# Nameting ic_spiegel_rood ná de ÉCHTE run van 20-09 — POGING 2: de 174 fouten zijn automatisch gesloten mét audit en delta; explosie-rem op `da_ontbreekt_in_doel` gewerkt; aandacht 341 → 176 (bovengrens)

**Opdracht:** `opdrachten/gedaan/2026-09-20-nameting-ic-spiegel-rood-echte-run-poging-2.md` (vervolg op
`docs/rapporten/2026-09-19-nameting-ic-spiegel-rood-echte-run-poging-1.md`). Gestart 20-09 ~07:20 CEST ná de `niet vóór: 07:15`-poort (rij (k)) —
de poort werkte: de opdracht is niet op 19-09 avond opgepakt.

**Werkt in productie: JA** voor stap 1 (0 × `intercompany`/`fout`, `delta.verdwenen_fouten` 174), stap 2 (precies één audit-rij
`reconciliatie_auto_gesloten` `ic_spiegel_rood`/`fout`/`intercompany`/NULL/174), stap 3 (explosie-rem: `da_ontbreekt_in_doel` → `meten` mét audit,
LET-OP en regressie-audit) en stap 4 (run afgerond, mail-status zoals verwacht). **Bovengrens gemeten** stap 5 (aandacht-proxy 176; de UI-teller
blijft een klikpunt). **Niet meetbaar** stap 6 (`trigger_gebundeld`: geen bulk-upload). **Klikpunt blijft** stap 7 (BLOW c9ba6d8d nog
`te_controleren`). Alles lees-only: geen RLZ-write, geen migratie, geen codewijziging.

## Stap 0 — voorwaarde (groen)

- `git fetch origin && git rev-list --count main..origin/main` = 0; HEAD = origin/main = `0453020`.
- De commit van poging 1 (`8d03c45`, `verdwenen_fouten`) zit in `0453020`; deploy-run 35457743184 (`0453020`) success, gestart 19-09 17:19 UTC,
  klaar ~17:25 UTC. Service `rlz-backend` én job `rlz-reconciliatie` staan beide op `europe-west4-docker.pkg.dev/rlz-boekhouding/rlz/backend:045302084c…`.
- Scheduler-run: `reconciliatie_run` `55facc7c-342d-4f22-a862-d4eeb82962ce`, `klaar`, `gestart_op` 2026-09-20 04:30:20 UTC, `afgerond_op` 04:44:52 UTC,
  `exit_code` 1 (= afwijkingen, verwacht), `mail_status` `actie=verzonden;systeem=uitgeschakeld`. Cloud Run-executie `rlz-reconciliatie-kv8v6`
  (04:30:01 → 04:44:59 UTC). De run startte ruim ná de deploy → nieuwe code; "niet gemeten — run vóór deploy" is niet aan de orde.

## Meetrecept en uitkomsten (leesreplica via `scripts/gcp/db_lezen.sh --als 2f2262cd-…`, Cloud Logging op de executienaam)

### Stap 1 — bevindingen en delta van run `55facc7c`

| Meting | Vorige run `772e6c3c` (19-09) | Run `55facc7c` (20-09) |
|---|---|---|
| NULL-scope `intercompany`/`fout` | 174 | **0** |
| NULL-scope `automatisering`/`let_op` | 2 | 1 |
| `samenvatting.intercompany` | fouten 174 | fouten **0**, afwijkingen 210, let_op 7, status `actie` |
| run-log IC-blok | 174 rood | "spiegelparen 174 groen / 0 rood, 0 fout(en)" |

`samenvatting.delta` (nieuw sinds `8d03c45`):

```
verdwenen_fouten 174 · verdwenen_afwijkingen 10 · nieuwe_afwijkingen 111 · nieuwe_let_op 10 · nieuwe_fouten 0 · nieuwe_geaccepteerd 0 · blokken_fout []
```

De `verdwenen_afwijkingen` 10 = `ic_ontbreekt_bij_ontvanger` 4, `ic_ontbreekt_bij_verkoper` 1, `kassarapport_in_werkvoorraad` 4 (de autotype-motor
van 19-09 deed zijn werk: dagteller `kassarapport_autotype` 4/4), `dubbele_betaling_vermoed` 1.

### Stap 2 — audit `reconciliatie_auto_gesloten` (platform.audit_event)

Vóór de run 66 rijen (alle 18-09, `dubbele_betaling_vermoed`). Ná de run **72**; de zes nieuwe rijen dragen alle `tijdstip` 2026-09-20 04:44:54 UTC,
`record_id` = de run-id, `tabel` `reconciliatie_bevinding`:

| `soort` | `bevinding_soort` | `blok` | `administratie_id` (waarde) | `aantal` | vingerafdrukken | reden |
|---|---|---|---|---|---|---|
| `ic_spiegel_rood` | `fout` | `intercompany` | NULL | **174** | 174 | niet meer geproduceerd door run 55facc7c… — fout uit de vorige run verdwenen (blok intercompany) |
| `ic_ontbreekt_bij_ontvanger` | `afwijking` | `intercompany` | f13f30c2 (Molenhof Beheer) | 3 | 3 | … afwijking uit de vorige run verdwenen (blok intercompany) |
| `ic_ontbreekt_bij_ontvanger` | `afwijking` | `intercompany` | 3ee6edf0 | 1 | 1 | idem |
| `ic_ontbreekt_bij_verkoper` | `afwijking` | `intercompany` | 66e1e296 (Kempen Facilities) | 1 | 1 | idem |
| `kassarapport_in_werkvoorraad` | `afwijking` | `omzet` | cd973c86 | 4 | 4 | … (blok omzet) |
| `dubbele_betaling_vermoed` | `afwijking` | `bank` | 3ee6edf0 | 1 | 1 | herdefinitie 17-09 — valse positieven (periodiek / betaling mét factuur) |

Exact de verwachting uit poging 1. Eén nuance: de **kolom** `audit_event.administratie_id` is bij álle zes rijen NULL — de run schrijft het
audit in `scoped_session(None)` (RLS-eis, memory "audit_event mét administratie_id vereist scope"); de administratie van de verdwenen bevinding
staat in `nieuwe_waarde.administratie_id`. Voor `ic_spiegel_rood` zijn kolom én waarde NULL (de fouten waren zelf NULL-scope). Geen fout, wel
een leesinstructie voor wie het audit filtert.

### Stap 3 — explosie-rem `da_ontbreekt_in_doel`

- `reconciliatie_instelling.soort_standen` = `{"rc_sluit_niet": "meten", "da_ontbreekt_in_doel": "meten", "ic_ontbreekt_bij_ontvanger": "meten"}` (vóór: zonder `da_…`).
- Audit `bevindingssoort_naar_meten` 04:44:52 UTC: `{"soort": "da_ontbreekt_in_doel", "stand": "meten", "reden": "explosie-rem: 99 bevindingen in één run (> 50); run 55facc7c…"}`.
- Bevinding `automatisering`/`let_op`: `reden` `bevindingssoort_explodeert`, `bevindingssoort` `da_ontbreekt_in_doel`, `aantal` 99, `doel_pad` `/reconciliatie?soort=meten`.
- Audit `automatisering_regressie` 04:44:55 UTC: categorie `bevindingssoort_explodeert`, aantal 99, vingerafdruk `6aa53838…`.
- **De rem greep op 99, niet op 102.** Het aansluitingsblok meldt 105 afwijkingen (poging 1 lees-only: 108): KF-scope `da_ontbreekt_in_doel` 99 in
  `meten` (96 Molenhof Beheer + 3 Oirschot Recreatie — de Oirschot-rijen vallen mee onder de stand, de soort als geheel), `da_inkoop_zonder_verkoop` 4
  en `da_bedrag_afwijkt` 2 in `actie`. 108 → 105 is géén regressie: het 400-dagen-venster schoof van 2025-08-15 naar 2025-08-16 en precies de drie
  Molenhof-Beheer-verkopen van 15-08-2025 (lees-only 19-09: 3 × `datum=2025-08-15`) vielen eruit; tellers 1758/1660/1652 → 1744/1649/1641.
- Run-log kv8v6: 2.679 regels, de `LET-OP     bevindingssoort … explodeert`-regel staat er níét in (wel de `=== automatiseringen ===`-kop en de
  RUN-slotregel) — Cloud Run-job-logs laten regels vallen (memory); het audit en de bevinding zijn het bewijs, niet het log.

### Stap 4 — mail en run-log

`mail_status` = `actie=verzonden;systeem=uitgeschakeld`; log: "RUN 55facc7c… vastgelegd (778 bevinding(en); mail: actie=verzonden;systeem=uitgeschakeld
— systeem: RECONCILIATIE_BEHEER_ONTVANGERS leeg — systeemmail uit)". Geen regel "FOUT reconciliatie-run … niet afgerond". **De systeemmail staat in
productie uit, dus de herstelregel "Hersteld — 174 fout(en) …" is nergens verzonden; hij is uitsluitend via `samenvatting.delta` (stap 1) en het
audit (stap 2) getoetst — precies waarvoor `samenvatting["delta"]` in poging 1 gebouwd is.**

### Stap 5 — aandacht 340 → ≤ 166? Gemeten: 341 → 176 (bovengrens), verschil volledig verklaard

Scope-loop over de 80 administraties (`--administratie` per rij, RLS zonder Beheerder-clausule) + NULL-scope, voor beide runs:

| | run 19-09 `772e6c3c` | run 20-09 `55facc7c` |
|---|---|---|
| bevindingen totaal (= run-log) | 843 | 778 |
| afwijking / let_op / fout / geaccepteerd | 566 / 93 / 174 / 10 | 667 / 101 / 0 / 10 |
| waarvan `meten` | 492 | 592 |
| **aandacht-proxy** (afwijking + let_op + fout − meten) | **341** | **176** |
| administraties mét ≥ 1 aandacht-rij | 48 | 48 |

341 sluit aan op de "340" uit de opdracht. De verwachting "≤ 166" rekende alleen met −174; het verschil (+10) is compleet herleidbaar: −174 fouten,
−4 `kassarapport_in_werkvoorraad`, −1 `ic_ontbreekt_bij_verkoper`, **+6 `da_*` in `actie`** (het aansluitingsblok gaf tot 19-09 een valse nul),
**+8 LET-OP `project_naam_afgesloten_status_actief`** (nieuwe soort uit de deploy van 19-09), +1 IC-LET-OP → 341 − 179 + 15 = 177 ≈ 176. `meten` groeide
van 492 naar 592 door `da_ontbreekt_in_doel` 99 + `project_nummer_dubbel` 2 → 4 + `wordt_geboekt_verouderd` 1 (−2 `ic_ontbreekt_bij_ontvanger`). De proxy
trekt gesnoozede LET-OP's (`reconciliatie_gezien`) en live-acceptaties niet af, dus de UI-teller op Inzicht › Reconciliatie is ≤ 176 — het exacte
getal blijft een klikpunt (login nodig).

### Stap 6 — extractie-wachtrij

`gcloud run jobs executions list --job rlz-extractie-wachtrij`: exact 6 executies per uur van 19-09 00:00 t/m 20-09 04:00 UTC (05:00 UTC: 3, lopend
uur). Dagteller `extractie_wachtrij` in `samenvatting.automatiseringen.tellers`: verwacht 1 / gedaan 0 / overgeslagen `lokaal_thread` 1; geen
`trigger_gebundeld`. Geen bulk-upload sinds de deploy → niet meetbaar, geen fout.

### Stap 7 — BLOW c9ba6d8d (klikpunt)

Leesreplica (scope BLOW `5419878c`): `c9ba6d8d-ad7f-4c3c-a37b-111257b8643b` status `te_controleren`, `laatst_gewijzigd_op` 2026-09-18 11:05:14 UTC;
origineel `0bbb1a1d-9650-…` idem (10:39:56 UTC). Onveranderd sinds 19-09; geen schrijvende job zonder Peter.

## Keuzes zonder Peter (vastgelegd)

- **Vergelijkingsloop óók voor de vorige run** (extra ~4 min lees-only) — zonder die basislijn was "341 → 176" niet te scheiden van de nieuwe
  soorten uit de deploy van 19-09; de opdracht noemde de loop als optioneel, de verklaring van +10 boven de verwachting rechtvaardigt 'm.
- **108 → 105 als venster-effect gerapporteerd, niet als regressie**, op basis van de datums in de lees-only uitvoer van 19-09 en de tellers
  (1758 → 1744 verkopen) — geen extra RLZ-lezing nodig.
- **Geen codewijziging:** de NULL-kolom `administratie_id` op het audit is bestaand gedrag (RLS), de waarde staat in `nieuwe_waarde`; een fix zou
  de run in per-administratie-scope moeten laten schrijven en is een aparte afweging (regels reconciliatie.md noteert de leesinstructie).
- **Geen "Wat is nieuw"-regel:** nameting-only, geen feature-commit.

## Klikpunten

1. BLOW: document "2023-12-13_div. crediteuren_20230872.pdf" (id c9ba6d8d, ontvangen 18-09-2026, status `te_controleren` op de leesreplica
   20-09 07:40) alsnog afvoeren als duplicaat van 0bbb1a1d — dry-run op de job-image (19-09, executie `k57ql`) bewees exact 1.
2. Kempen Facilities → Molenhof Beheer: 96 verkoopfacturen zonder inkoop bij Molenhof Beheer (run `55facc7c`, 29-08-2025 … 2026, € 53 – € 76.021,
   bevindingen KF-scope `da_ontbreekt_in_doel`) — worden die daar buiten de KF-crediteurrecords geboekt? Bepaalt of `da_ontbreekt_in_doel` terug
   naar `actie` mag (`PUT …/instelling/soort-stand` / CLI `bevindingssoort-stand`).
3. UI-teller "aandacht" op Inzicht › Reconciliatie ná de run van 20-09: verwacht ≤ 176 (proxy), ter bevestiging.
   Klikpunten Oirschot ↔ Veldhoven (24712615/24712648/24712802), Veldhoven € 69,82 (24712869/24712873) en Molenhof Verhuur 24713191 uit het rapport
   van 19-09 middag staan ongewijzigd.

## Suite
Geen code geraakt. Docs-guards: `test_rapporten_index.py`, `test_rapporten_gelezen_regels.py`, `test_rapporten_klikpunten.py`,
`test_claude_md_beslissingen_verwijzingen.py`, `test_regels_index.py` — uitkomst in de commit-boodschap.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/reconciliatie.md` (158 regels — stand vóór de run)
- `docs/regels/doorbelasting-intercompany.md` (166 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (184 regels — stand vóór de run)
