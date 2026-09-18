# Nazorg + nameting ná deploy: offerte-verbruik = geboekt + onderweg (casus Bouwadvies 32949)

**Opdracht:** `opdrachten/gedaan/2026-09-18-offerte-verbruik-onderweg-nameting.md` (tweede run; de eerste run legde de opdracht
terug omdat de fix nog niet gecommit was — `docs/rapporten/2026-09-18-offerte-verbruik-onderweg-nameting-uitgesteld.md`).
**Werkt in productie: JA** — nazorg-CLI op de gedeployde job-image uitgevoerd, leesreplica toont de verwachte drie getallen
(32949: verbruik ná 150.000,00 · onderweg 100.000,00 · 2 facturen ter accordering). Alleen de kaarttekst in de app zelf (stap 4)
is een klikpunt voor Peter; de tekst is deterministisch afgeleid uit de servergetallen mét de pure helpers.
**BESLISSINGEN:** "OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)" — status bijgewerkt naar "werkt in productie: ja".
**Bugrapport:** `docs/rapporten/2026-09-18-bug-offerte-verbruik-telt-onderweg-facturen.md`.

## Stap 0 — deploy-check: LIVE (service én jobs op `b6ae7fc`)
- `gh run list --workflow deploy.yml`: run `35384309424` op `b6ae7fc` (bevat `de8eaf2` = fix + migratie 0166) LIEP nog bij de
  start (19:09 UTC) → `gh run watch` volgens de aangescherpte stap 0; afgerond groen 19:15 UTC (job "deploy": success).
- Migratie-job `rlz-migratie-lv69k` (Cloud Logging): `Running upgrade 0165 -> 0166, Offerte-verbruik telt onderweg-facturen mee …`.
  De regel staat NIET in het GitHub-log (de migratie-job logt naar Cloud Logging) — voor een volgende deploy-check: het
  executie-log lezen, niet het workflow-log grep'en.
- Post-deploy-smoketest `rlz-smoketest-64htf`: successfully completed.
- Beeld: service `rlz-backend` = `…/backend:b6ae7fc6acb1…`, jobs `rlz-sync` én `rlz-migratie` = hetzelfde beeld. (De service heet
  `rlz-backend`, niet `rlz-boekhouding` zoals de opdracht schreef — `gcloud run services list` toonde één service.)

## Stap 1 — nazorg dry-run (job-image, lees-only): EXACT de verwachting
`gcloud run jobs execute rlz-sync … --args="-m,app.cli,verplichting-match-herberekenen,--administratie,a265c010-…,--dry-run"`
→ executie `rlz-sync-t6kz9`, letterlijk:
```
Bouwadvies Oost Nederland B.V. (a265c010-91ee-4b72-a5d6-48ddb67652f4): 3 open gematchte factu(u)r(en)
  269eef9d-ef49-462c-aab9-540734fbf1fe  binnen   verbruik_na 20000.00  (dry-run)
  d9b44b34-72c8-4db9-91ed-ea835ec8e0ef  binnen   verbruik_na 50000.00  (dry-run)
  8430932e-6799-45b3-9829-8dd245b7f971  binnen   verbruik_na 80000.00  (dry-run)
Totaal: 3 kandidaten, 0 herberekend, 0 gewijzigd (dry-run: niets geschreven)
```
Drie kandidaten (32948 € 20.000, 32949 € 50.000, 33122 € 80.000), alle `binnen`, verbruik_na = eigen bedrag — geen nieuwe factuur,
niets geboekt of afgewezen sinds de nulmeting van 20:50. Door naar stap 2 zonder verklaring nodig.

## Stap 2 — nazorg uitgevoerd (SCHRIJVEND, alleen matchrijen)
Bouwadvies, executie `rlz-sync-24ckx`, letterlijk:
```
Bouwadvies Oost Nederland B.V. (a265c010-91ee-4b72-a5d6-48ddb67652f4): 3 open gematchte factu(u)r(en)
  269eef9d-ef49-462c-aab9-540734fbf1fe  binnen  → binnen   verbruik_na 20000.00 → 150000.00  (onderweg 130000.00, 2 facturen)
  d9b44b34-72c8-4db9-91ed-ea835ec8e0ef  binnen  → binnen   verbruik_na 50000.00 → 150000.00  (onderweg 100000.00, 2 facturen)
  8430932e-6799-45b3-9829-8dd245b7f971  binnen  → binnen   verbruik_na 80000.00 → 150000.00  (onderweg 70000.00, 2 facturen)
Totaal: 3 kandidaten, 3 herberekend, 3 gewijzigd
```
Kantoorbreed (zonder `--administratie`): dry-run `rlz-sync-gv5lx` → "Totaal: 3 kandidaten, 0 herberekend, 0 gewijzigd" — buiten
Bouwadvies heeft geen enkele administratie open gematchte inkoopfacturen (binnen/buiten, niet verrekend, niet terminaal/geboekt).
Kantoorbrede uitvoering `rlz-sync-7qrrq` → "3 kandidaten, 3 herberekend, 0 gewijzigd", alle drie `(ongewijzigd)`: idempotent.
Geen RLZ-calls, geen documentstatus geraakt; alleen `verplichting_match`-rijen (uitkomst/verbruik/details/berekend_op).

## Stap 3 — nameting leesreplica (`scripts/gcp/db_lezen.sh`, READ ONLY als `nameting@…iam`, rol `rlz_lezer`)
Letterlijk (`db-lezen`, 19:21 UTC, RLS-scope Bouwadvies):
```
             document_id              | referentie |     status      | uitkomst | verbruik_voor | verbruik_na | geboekt | onderweg  | n | ter_acc |          berekend_op
--------------------------------------+------------+-----------------+----------+---------------+-------------+---------+-----------+---+---------+-------------------------------
 269eef9d-ef49-462c-aab9-540734fbf1fe | 32948      | ter_accordering | binnen   |     130000.00 |   150000.00 | 0.00    | 130000.00 | 2 | 2       | 2026-09-18 19:21:21.490546+00
 d9b44b34-72c8-4db9-91ed-ea835ec8e0ef | 32949      | ter_accordering | binnen   |     100000.00 |   150000.00 | 0.00    | 100000.00 | 2 | 2       | 2026-09-18 19:21:21.724925+00
 8430932e-6799-45b3-9829-8dd245b7f971 | 33122      | ter_accordering | binnen   |      70000.00 |   150000.00 | 0.00    | 70000.00  | 2 | 2       | 2026-09-18 19:21:21.960808+00
```
Verplichting `34aaf45b` (zonder offertenummer): `totaalbedrag_excl` 1.192.922,50 = `goedgekeurd_bedrag_excl`, `verbruikt_bedrag_excl`
(boekstand) 0,00, niet vervallen, document `geaccordeerd`. Statussen ongewijzigd t.o.v. de nulmeting → de verwachting uit de opdracht
geldt onverkort en is gehaald: **32949 verbruik_na 150000.00, onderweg 100000.00, n 2**, alle onderweg-facturen ter accordering
(`ter_acc` 2 = `n` 2 → tekst "ter accordering", niet "in behandeling"). `verbruik_voor` = geboekt + onderweg van de ándere twee,
consistent per rij (130k/100k/70k).

## Stap 4 — kaarttekst: klikpunt Peter (accordeur-app / kantoor-controlescherm 32949, Inzicht › Verplichtingen)
Niet zelf geklikt (geen app-sessie in deze run); de tekst is deterministisch afgeleid uit de gemeten servergetallen (bron: `db-lezen`
hierboven, 18-09) mét de pure helpers die de DTO's voeden:
- `match.onderweg_tekst(Decimal('100000'), 2, 2)` → letterlijk `waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)`.
- Kaart 32949 verwacht: "✓ Binnen de goedgekeurde offerte zonder nummer · Deze factuur van € 50.000,00 (2e termijn) past. ·
  € 150.000,00 van € 1.192.922,50 · waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)"; balk: onderweg gearceerd,
  deze factuur gemarkeerd. Termijnnummer = positie op berekend_op/datum onder geboekt + onderweg — bij drie gelijktijdige facturen
  kan dat 1e/2e/3e zijn afhankelijk van de volgorde; de opdracht schreef bewust "(Ne termijn)".
- Inzicht › Verplichtingen, rij Bouwadvies zonder nummer (`bereken_verbruik_stand(totaal=1192922.50, geboekt=0, onderweg=150000/3/3)`):
  "geboekt € 0,00 · onderweg € 150.000,00 · restant € 1.042.922,50" (restant = 1.192.922,50 − 0 − 150.000,00), percentage 12,6 %
  (geboekt + onderweg), status niet overschreden.
Klikt Peter dit na en klopt de tekst niet, dan is het een frontend-presentatiebug (server-DTO's dragen de getallen aantoonbaar).

## Keuzes in deze run (Peter kijkt niet mee)
1. Lopende deploy = wachten (`gh run watch`, 6 min) in plaats van "niet live → stoppen" — de aangescherpte stap 0 uit de vorige run.
2. De kantoorbrede schrijfrun is uitgevoerd ondanks de dry-run "0 gewijzigd" buiten Bouwadvies: de opdracht schreef "aantal noteren →
   uitvoeren", de CLI is idempotent (bewijs: 3 × ongewijzigd) en zo staat vast dat geen enkele andere administratie een stale matchrij
   draagt.
3. Stap 4 als klikpunt Peter mét deterministische afleiding i.p.v. een eigen login op productie (geen app-credential in een run; de
   nameting-SA heeft bewust geen app-toegang).

## Lessen
- De migratie-regel `Running upgrade …` staat niet in het GitHub-Actions-log maar in het Cloud-Logging-log van de `rlz-migratie`-
  executie — de deploy-check in volgende opdrachten moet dáár lezen.
- De Cloud Run-service heet `rlz-backend`; opdrachten die `rlz-boekhouding` als servicenaam noemen bedoelen het project.
- Job-uitvoer verschijnt ~20 s ná `--wait` in Cloud Logging (`--order=asc` + `--freshness`); de `gcloud run jobs execute`-uitvoer zelf
  bevat alleen de executienaam.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (266 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
