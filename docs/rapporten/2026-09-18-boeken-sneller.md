# Rapport 18-09 — Boeken sneller: checks-cache + achtergrond-schrijver + doorloop (inbox-run 3, agent D + coördinator)

**Opdracht:** `opdrachten/gedaan/2026-09-18-boeken-sneller-checks-en-doorloop.md`. Migratie **0165**. **Werkt in productie: niet
gemeten** — deploy volgt via de Stop-hook; nulmeting vóór de fix staat hieronder, het nameting-recept onderaan.

> Procesnotitie: de bouwagent (D) werd ná het gros van het werk afgebroken op de maandelijkse tegoedlimiet (HTTP 429). De
> coördinator heeft de resterende stand geverifieerd (imports, `tsc -b`, gerichte suites, volledige suite, migratie-routine) en dit
> rapport afgerond op basis van de code en het voorlopige rapport van de agent. Regels/BESLISSINGEN/changelog zijn de teksten van de agent.

## Samenvatting (één regel voor Peter)
Klik je op "Boeken in RLZ", dan sta je binnen een seconde op de volgende factuur; de boeking in Reeleezee loopt op de achtergrond en
je ziet in de documentenlijst "Wordt geboekt…" → "Geboekt · boekstuk"; mislukt hij, dan wordt de rij rood "Boeken mislukt — reden ·
Opnieuw" (plus een melding als je nog in die administratie zit) — geen pop-up meer op de knop.

## Nulmeting (Cloud Logging, request-log `rlz-backend` 18-09 t/m 13:00Z, vóór de fix — lees-only)
| route | n | p50 | p95 | max | statussen |
|---|---|---|---|---|---|
| POST …/boekvoorstel/checks | 51 | 0,79 s | 2,14 s | 2,55 s | 200 ×51 |
| POST …/boeken | 24 | 2,65 s | 3,42 s | 3,70 s | 200 ×20 · 429 ×4 (volumerem, zie rapport volumerem-handmatig) |
De beleving "4–5 s" = checks bij openen + boeken + lijst-fetch + checks van het volgende document in serie. Ruwe rijen in de
scratchpad van de run (`nulmeting_D_raw.txt`); het filter: `resource.labels.service_name="rlz-backend" AND httpRequest.requestUrl:"/boeken"`.

## Gedaan / niet gedaan
| Stap | Stand | Kern |
|---|---|---|
| 0 Server-Timing + log | gedaan | `checks_extern.StapTiming` → `Server-Timing`-header (`checks.lokaal`, `checks.extern`, `checks.ibanseed`, `checks.duplicaat`, `boek.rlz`, `boek.db`) + gestructureerde logregel `server_timing` op checks- én boek-route; de worker logt `stappen_ms` in het audit `boek_wachtrij_afgerond`. CORS `expose_headers` Server-Timing. |
| 1.1–1.3 checks lokaal/extern + cache | gedaan | `boekvoorstel.voer_checks_uit(extern="auto"\|"vers"\|"cache", timing=)`; externe vingerafdruk = crediteur-cluster + referentie genormaliseerd + factuurdatum + totaal + factuur-IBAN + boek_cyclus; `check_extern_cache` (0165, RLS FORCE, UPDATE i.p.v. DELETE), geldig ≤ 15 min (`checks_extern_cache_minuten`); storing nooit gecachet; retry ná `boeken_mislukt` en autoboek-pad = vers. Externe calls parallel (ThreadPool max 4, één client). B's nieuwe check "Btw-bedrag past bij tarief" zit in het lokale deel. |
| 1.4 voorverwarmen | gedaan | `POST …/boekvoorstel/checks?voorverwarm=1` (Semaphore max 1, setting `CHECKS_VOORVERWARMEN` default aan, audit `checks_voorverwarmd` gedaan/uit_cache/overgeslagen_bezig/uit → teller `checks_voorverwarmen` in de reconciliatiemail). |
| 1.5 useAutoChecks | gedaan | debounce 400 ms, lokaal direct, `bijExtern` alleen bij vingerafdruk-wijziging, `lokaalBezig`/`externBezig`. |
| 2.1 synchroon deel + 202 | gedaan | `boek_wachtrij.dien_boeking_in` (poorten, statusmachine, accordering, 409's, doorbelasting-checks, lokale checks + extern uit cache of vers, toggle, volumerem) → status `wordt_geboekt` + audit + 202 `{document_id, status, volgende_document_id, volgende_document_soort}`; server-side `kies_volgend_document` = spiegel van `kiesVolgendDocument` (zelfde `VERWERKBARE_STATUSSEN`); `?direct=1` = het oude synchrone pad. |
| 2.2 achtergrond-schrijver | gedaan | `BoekWachtrij` (dev in-process thread, suite `DirecteBoekWachtrij`, cloud on-demand job `rlz-boek-wachtrij` via `boek-wachtrij-verwerken` + scheduler-vangnet */2 min); claim `boek_wachtrij_claim` (idempotency-key `boek-{document_id}-{boek_cyclus}`); worker = bestaand `boek_document` vanaf de RLZ-write incl. doorbelasting/webhook. **Keuze: job-patroon, geen Cloud Tasks** (queue/IAM/OIDC niet in deze run te bewijzen; zelfde patroon als de extractie-wachtrij sinds 26-08). |
| 2.3 vangnetten | gedaan | startup-herstel (`main.py` lifespan) + job hervatten > 10 min (`boek_wachtrij_herstel_minuten`); reconciliatie-bevinding `wordt_geboekt_verouderd` (start in `meten`) mét actie "Opnieuw proberen"; tellers `boek_wachtrij` ingediend/geboekt/mislukt/vangnet. |
| 2.4 frontend | gedaan | 202 → toast + `navigate` naar `volgende_document_id`; lijst-rij "Wordt geboekt…" (polling 5 s zolang er zulke rijen zijn) → "Geboekt · boekstuk" of rood "Boeken mislukt — reden · Opnieuw"; toast bij mislukking in dezelfde administratie. |
| 2.5 autoboek/staande goedkeuring | gedaan (interpretatie) | zelfde motor `boek_document`, geen 202-shortcut — zij draaien al in een achtergrondproces. |
| 3 doorloop | gedaan | `naVerwerking` gebruikt `volgende_document_id` (fallback `positie.volgende`, pas dan de lijst); `prefetchDetail` van het volgende document (cache 60 s) + voorverwarmen bij openen. |
| deploy | gedaan | `deploy.yml` + `f3_jobs.sh` stap 8b (`rlz-boek-wachtrij|boek-wachtrij-verwerken|900|*/2 * * * *`), guards `test_deploy_yml_image_uniform.py`/`test_deploy_yml_envset_compleet.py` (VERWACHTE_JOBS + envset). |

Niet gedaan: Cloud Tasks (bewust, zie keuze); de productiemeting op 10 boekingen (pas ná deploy).

## Tests
- Nieuw: `tests/documenten/test_boek_wachtrij.py` (claim/idempotentie 2× = één RLZ-document, gestrande claim hervatten, statusmachine
  `wordt_geboekt`, volgend document positioneel/cyclisch/alleen verwerkbaar), `tests/documenten/test_checks_extern.py` (vingerafdruk-
  velden, cache-verval, storing niet gecachet, "geen geldig rapport bij boeken → synchroon extern"), `test_router_boeken.py`
  (202-pad, `direct=1`), frontend `useAutoChecks.test.ts`, `DocumentDetailScreen.test.tsx` (202 zonder volgend document → lijst zonder fetch).
- Gerichte herdraai door de coördinator op een eigen test-DB: `TestVolgendDocument` 2 groen (de rode run van de agent was de
  migratiestub-race, niet de code). Volledige suite en vitest: zie `2026-09-18-inbox-afgewerkt-3.md`.

## Migratie-routine (coördinator)
`make migrate` dev-DB: `Running upgrade 0164 -> 0165` gezien; live-200 via een dev-uvicorn op 8011 op de nieuwe/gewijzigde GET-routes
van deze run (de voorverwarm-route heeft in de dev-DB geen document om op te toetsen — gedekt door de router-tests);
`scripts/dump_schema.sh` ná de volledige suite.

## Klikpunten Peter
- Ná de deploy: `scripts/gcp/f3_jobs.sh` opnieuw draaien (stap 8b: IAM `roles/run.invoker` op `rlz-boek-wachtrij` voor `run-backend@` +
  scheduler `*/2 * * * *`). Tot dan blijft een ingediende boeking zichtbaar op "Wordt geboekt…" tot het startup-vangnet (nooit stil).
- Na een week meten: bevindingssoort `wordt_geboekt_verouderd` van `meten` naar `actie` (Instellingen › Reconciliatie).

## Beslispunten
1. 15-min-geldigheid van het externe rapport (setting) — bij intensief boeken op één administratie kan 30 min veilig zijn.
2. Cloud Tasks alsnog (één taak per boeking, retry met backoff) zodra queue/IAM-klikpunten gedaan zijn; het contract
   `BoekWachtrij.enqueue` is erop voorbereid.

## Nameting-recept (ná deploy, lees-only, nameting-SA)
1. Deploy-check service ÉN jobs (incl. `rlz-boek-wachtrij`) op de commit van deze run; migratie-log `Running upgrade 0164 -> 0165`.
2. Peter boekt 10 facturen; Cloud Logging: `jsonPayload.server_timing` op `POST …/boeken` (route `document_boeken_ingediend`) →
   p95 van de synchrone route; audit `boek_wachtrij_afgerond` → `stappen_ms.boek.rlz`; doel: klik → volgende document ≤ 1 s (p95),
   RLZ-boeking gereed in de lijst ≤ 15 s (p95). Vóór/ná-tabel tegen de nulmeting hierboven.
3. Reconciliatiemail: tellers `boek_wachtrij` (ingediend = geboekt, 0 mislukt) en `checks_voorverwarmen` (gedaan > 0).
"werkt in productie: ja/nee" volgt in het rapport van de nameting.

## Gelezen regels
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)
- `docs/regels/autoboeken-ai.md` (122 regels)
- `docs/regels/duplicaten-crediteuren.md` (119 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- `docs/regels/kantoor-frontend.md` (123 regels)
- Overige domeinen van deze inbox-run (door de coördinator vooraf volledig gelezen): `docs/regels/btw.md` (150 regels), `docs/regels/intake-extractie.md` (270 regels), `docs/regels/accordering-native-app.md` (321 regels), `docs/regels/uren-planning-veldwerkers.md` (472 regels)
