Domeinen: reconciliatie, doorbelasting-intercompany, werkloop-productie

> **niet vóór: 2026-09-20 07:15** — meet ná de scheduler-run van 20-09 04:30 UTC (06:30 NL, ~15 min) én ná de deploy van de
> commit van poging 1 (verdwenen fouten in de delta + generiek audit). De inbox-runner claimt dit bestand pas ná dat moment (rij (k)).

# OPDRACHT 20-09 — Nameting ic_spiegel_rood ná de ÉCHTE run van 20-09 06:30 — POGING 2 (vervolg op
# docs/rapporten/2026-09-19-nameting-ic-spiegel-rood-echte-run-poging-1.md)

Poging 1 (19-09 avond) liep te vroeg (de run van 20-09 was nog niet geweest) en vond dat de 174 × `ic_spiegel_rood` (soort `fout`)
zónder spoor zouden verdwijnen: de delta kende alleen `verdwenen_afwijkingen` en het audit `reconciliatie_auto_gesloten` alleen
`dubbele_betaling_vermoed`. Gefixt in poging 1 (`run.py`: `Delta.verdwenen_fouten`, `_audit_verdwenen_bevindingen` per soort ×
administratie, herstelregel "Hersteld — N fout(en)" in de systeemmail, `samenvatting["delta"]` op de run-rij). Stap 4 (`--alleen
doorbelasting_aansluiting` op de job-image) en stap 6 (BLOW c9ba6d8d nog `te_controleren`) zijn in poging 1 al gemeten.

**Stap 0 (voorwaarde):** `git fetch origin && git rev-list --count main..origin/main` = 0 (anders `git merge --no-ff origin/main`, nooit
rebase); de commit van poging 1 (`git log --oneline --grep="verdwenen_fouten" -1`) is gedeployd op service `rlz-backend` ÉN job
`rlz-reconciliatie` (`gh run list --workflow=deploy.yml --limit 3` groen; `gcloud run jobs describe rlz-reconciliatie --region europe-west4
--format=json` → zelfde image als de service). De scheduler-run van 20-09 is AFGEROND: leesreplica `SELECT id, status, gestart_op,
afgerond_op, mail_status FROM boekhouding.reconciliatie_run ORDER BY aangevraagd_op DESC LIMIT 2` toont een `klaar`-rij mét
`gestart_op` 2026-09-20 04:30 UTC. Let op: is die run gestart VÓÓR de deploy van poging 1 (deploy-tijd `gh run view`), dan draaide hij
op de oude code → audit/`delta`-sleutel ontbreken bewust; noteer dat als "niet gemeten — run vóór deploy" en zet dit bestand terug in
inbox/ mét een nieuwe `niet vóór:`-regel voor 21-09 07:15.

## Meetrecept (lees-only; `scripts/gcp/db_lezen.sh "<SQL>" --als 2f2262cd-0423-4910-b7b5-335ba37a6ef5`, zonder --administratie = alleen
## NULL-scope-rijen — de 174 fouten HEBBEN administratie_id NULL, dus zichtbaar)
1. `reconciliatie_bevinding` van de run van 20-09: `SELECT blok, soort, count(*) … WHERE run_id = '<run>' GROUP BY 1,2` → `intercompany`/`fout`
   = 0 (was 174 in 772e6c3c). `samenvatting->'intercompany'->>'fouten'` = 0; `samenvatting->'delta'` toont `verdwenen_fouten` = 174 (of
   174 + andere verdwenen fouten — noteer de exacte waarde), `verdwenen_afwijkingen` = N.
2. `platform.audit_event` actie `reconciliatie_auto_gesloten` op 20-09: verwacht één rij mét `nieuwe_waarde->>'soort'` = `ic_spiegel_rood`,
   `bevinding_soort` = `fout`, `blok` = `intercompany`, `administratie_id` NULL, `aantal` = 174, `vingerafdrukken` ≤ 200, reden
   "niet meer geproduceerd door run <run-id> …"; plus eventueel rijen voor andere verdwenen soorten (noteer soort + aantal).
   Vóór de run: 66 rijen (alle 18-09, `dubbele_betaling_vermoed`, som 1199) — géén andere.
3. Explosie-rem `da_ontbreekt_in_doel` (102 > 50, code-default `actie`): `reconciliatie_instelling.soort_standen` bevat
   `"da_ontbreekt_in_doel": "meten"` (vóór: `{rc_sluit_niet: meten, ic_ontbreekt_bij_ontvanger: meten}`); audit `bevindingssoort_naar_meten` op
   20-09 mét reden "explosie-rem: 102 …"; bevinding blok `automatisering` soort `let_op` mét `detail->>'reden'` = `bevindingssoort_explodeert`;
   audit `automatisering_regressie` 20-09. De 9 andere `da_*` (3 × Veldhoven `da_inkoop_zonder_verkoop`, 2 × `da_bedrag_afwijkt`, 3 × Oirschot
   `da_ontbreekt_in_doel` — let op: die 3 vallen mee onder de rem omdat de soort als geheel naar meten gaat — en 1 × Molenhof Verhuur) → wat
   staat er in `samenvatting->'doorbelasting_aansluiting'` (afwijkingen 108, let_op, fouten 0)? Noteer hoeveel `da_*`-afwijkingen `detail->>'stand'`
   = `meten` dragen (per administratie-scope: loop `--administratie <KF 66e1e296-…>`).
4. Mail: `mail_status` van de run = `actie=verzonden;systeem=…` — de systeemmail is in productie `uitgeschakeld`; de herstelregel is dus alleen via
   `samenvatting->'delta'` (stap 1) en het audit (stap 2) toetsbaar — zeg dat letterlijk. Run-log (Cloud Logging, `labels."run.googleapis.com/
   execution_name"` van de scheduler-executie): "RUN … vastgelegd (N bevinding(en); mail: …)" en geen `FOUT reconciliatie-run … niet afgerond`.
5. Aandacht 340 → ≤ 166: per-blok-proxy uit `samenvatting` (som `afwijkingen` + `let_op` + `fouten` over de blokken, minus `meten`) en — als de
   tijd het toelaat — de bevindingen-loop per administratie (`--administratie`, ~81 administraties, memory "Sweep reconciliatie_bevinding per
   administratie"). De exacte UI-teller op Inzicht › Reconciliatie blijft een klikpunt Peter (login nodig).
6. Extractie-wachtrij: `gcloud run jobs executions list --job rlz-extractie-wachtrij --region europe-west4 --limit 300 --format='value(metadata.
   creationTimestamp)'` per uur = 6 zonder upload; ná een bulk-upload (als die er was) `trigger_gebundeld` > 0 in de tellers
   (`samenvatting->'automatiseringen'`). Geen bulk = "niet meetbaar", geen fout.
7. BLOW c9ba6d8d (klikpunt Peter): `SELECT id, status FROM boekhouding.document WHERE id::text LIKE 'c9ba6d8d%'` `--administratie
   5419878c-ca11-4f02-98d7-b14325ff8206` — `afgevoerd_duplicaat`? Zo niet: klikpunt herhalen, nooit een schrijvende job zonder Peter.
8. Rapport `docs/rapporten/2026-09-20-nameting-ic-spiegel-rood-echte-run-poging-2.md` mét "werkt in productie: ja/nee/niet gemeten" per
   onderdeel + INDEX; BESLISSINGEN-rij "Nameting ic_spiegel_rood échte run — POGING 1" krijgt een alinea "Poging 2 (20-09)"; regels-alinea
   reconciliatie.md "Verdwenen fouten …" van "niet gemeten" → gemeten. Geen RLZ-write, geen migratie.
