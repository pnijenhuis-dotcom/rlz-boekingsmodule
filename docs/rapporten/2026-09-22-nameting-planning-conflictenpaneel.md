# Nameting 22-09 — Planning conflictenpaneel + dubbele veldwerkers (rapport 21-09)

Opdracht `opdrachten/gedaan/2026-09-22-nameting-planning-conflictenpaneel-veldwerkers-dubbelen.md` (vervolg op
`docs/rapporten/2026-09-21-planning-conflictenpaneel-dubbele-veldwerkers.md`, "werkt in productie: niet gemeten"). Lees-only: één
dispatch van het nameting-onderdeel `veldwerkers-dubbelen`, Cloud Logging op het request-log, de leesreplica via `db_lezen.sh` als
`nameting@`. Geen write, geen RLZ-call, geen forceren van het paneel. Peter keek niet mee; keuzes staan in "Keuzes".

**Werkt in productie: JA voor wat te meten was, NIET GEMETEN voor de handelingen.** De code van 21-09 staat live op service én jobs, de
planning-route mét het paneel is 17 keer zonder fout geladen, en de dubbelen-CLI geeft op de job-image "TOTAAL 0 kandidaat-cluster(s) …
0 fout(en)". De knoppen "Houd ‹A›" en "Beide (halve dagen)…" zijn nog door niemand gebruikt — en dat kán ook niet: Universal heeft op dit
moment nul conflicten op vandaag of later, dus het paneel heeft geen rij mét handeling om op te klikken.

**Één regel voor Peter:** het paneel staat live en de "17 conflicten" die je zag waren allemaal in verstreken weken (het paneel toont er nu
terecht nul); de dubbelen-toets zegt "0", maar alleen omdat er bij Universal nog geen enkel dossier mét KvK en geen enkele
crediteur-koppeling staat — die "0" bewijst het instrument, niet dat er geen dubbelen zijn.

## Stap 0 — deploy-check

| Toets | Uitkomst |
|---|---|
| `main..origin/main` bij start | 0 / 0 (schoon); ná de bot-commit `d14277b` gemerged mét `--no-ff` (`f618aa9`) |
| Feature-commit | `ab1c46d` (21-09 16:46 CEST, migratie 0169) is voorouder van `fb63be5` — deploy #… `fb63be5` groen 21-09 17:38 UTC |
| Service `rlz-backend` image | `…/backend:a3f6f94…` (HEAD van de run; deploy van `a3f6f94` liep nog op 12:53 UTC, service al bijgewerkt) |
| Jobs `rlz-reconciliatie`, `rlz-boek-wachtrij` image | beide `a3f6f94…` — service = jobs |

De planning-code van 21-09 is dus sinds 21-09 ≈ 19:40 CEST live; alle metingen hieronder onderscheiden vóór/ná dat moment.

## 1. Dubbele veldwerkers — `veldwerkers-dubbelen --alles` (bot-bestand op main)

`gh workflow run nameting -f onderdeel=veldwerkers-dubbelen` → run 35730549609 → bot-commit `d14277b` →
`verkenning/nameting-veldwerkers-dubbelen-22-09.txt`:

```
Dubbele veldwerkers — 1 administratie(s). LEES-ONLY op harde sleutels (KvK, IBAN via crediteur, e-mail) …
== Universal Steigerbouw B.V. (3ee6edf0-…) — 46 veldwerker(s) in scope · 0 mét KvK · 0 mét IBAN via crediteur · 0 kandidaat-cluster(s)
  geen kandidaten op harde sleutels (KvK, IBAN, e-mail)
  niet toetsbaar: telefoon — geen telefoonveld op platform.gebruiker
TOTAAL 0 kandidaat-cluster(s) over 46 veldwerker(s) in 1 administratie(s) · 0 fout(en).
Container called exit(0).
```

Meetlat gehaald: TOTAAL-regel mét 0 fouten, Universal 0 clusters, job-exit 0. **Maar de sleutels zijn leeg.** Cross-check op de leesreplica
(`db_lezen.sh … --administratie 3ee6edf0…`):

| Universal Steigerbouw | Aantal |
|---|---|
| Veldwerkers in scope | 46 |
| `veldwerker_dossier`-rijen | 0 (dossiers zijn virtueel tot de eerste PUT — er is nog nooit iets geüpload of een KvK gezet) |
| Dossiers mét `kvk_nummer` | 0 |
| `veldwerker_crediteur`-koppelingen | 0 |
| Koppelingen mét IBAN (`leverancier_iban`) | 0 |

Van de drie harde sleutels blijft alleen e-mail over, en `gebruiker.e_mail` is uniek — de uitkomst "0" is bij Universal dus per constructie 0.
Het instrument werkt (leest 46 personen, meldt telefoon eerlijk als niet toetsbaar, 0 fouten), maar het heeft geen data om dubbelen te
vinden. Geen bug: de opdracht van 21-09 koos bewust harde sleutels en de regel zegt dat naam/planning nooit een signaal is. Het gevolg is
wél dat een KANDIDAAT-regel pas kán verschijnen zodra kantoor dossiers (KvK) en crediteur-koppelingen invult — zie "Vervolg".

## 2. Conflictenpaneel — request-log + leesreplica (tellen, niet forceren)

Cloud Logging, `rlz-backend`, `httpRequest.requestUrl:"/uren/kantoor/planning"`, **ná de deploy** (≥ 21-09 17:40 UTC), alle van
Universal (`administratie_id=3ee6edf0…`), 22-09 05:57 → 11:47 UTC:

| Route | Aantal | Status |
|---|---|---|
| `GET /uren/kantoor/planning` (weekgrid + paneel + `conflict_akkoorden`) | 17 | 200 |
| `GET /uren/kantoor/planning` | 1 | 401 (verlopen sessie, daarna opnieuw 200) |
| `POST /uren/kantoor/planning/reservering` | 4 | 201 |
| `POST /uren/kantoor/planning/bulk` | 1 | 200 — audit `planning_bulk` bron `ploeg` (ploeg-paneel, 1 gedaan, 0 conflict) |
| `POST /uren/kantoor/planning/conflict-akkoord` | **0** | — |
| `POST …/bulk` mét bron `conflict` ("Houd ‹A›") | **0** | — (audit `planning_verwijderd` mét `bron: conflict` = 0 rijen) |
| 5xx op planning-routes ná de deploy | 0 | |

Leesreplica `boekhouding.planning_conflict_akkoord` (Universal, `--administratie`): **0 rijen**. Audit-events planning sinds 21-09 (14 rijen):
reserveringen, twee ploeg-bulks, één vulhandvat-bulk (21-09 09:13 UTC, vóór de deploy: 2 items, 1 conflict `project` — dat is precies het
oude "conflict"-gedrag dat nu een rij mét handeling zou geven), één losse `planning_verwijderd`. Niets uit het paneel.

**Waarom niemand op een knop kon drukken — de stand van de planning zelf (leesreplica):**

| Dubbel geplande persoon-dagen Universal (`planning_toewijzing`, > 1 project op één dag) | Aantal |
|---|---|
| Verstreken dagen (< 22-09), andere weken dan week 39 | 19 |
| Week 39 (21-09 t/m 27-09) | 0 |
| Vandaag of later | **0** |
| Waarvan al op dagdeel `half` | 0 |
| Afwezigheden (`veldwerker_afwezigheid`) | 0 |

Het paneel toont sinds 21-09 alleen conflicten vanaf vandaag (`conflictenVanaf`). Universal heeft er vandaag nul, dus het paneel op week 39
zegt "0 conflicten" en meldt bij een oude week alleen de historie-regel — exact het gedrag uit het bouwrapport. De "17 conflicten deze week" van
Peter (21-09) stonden in week 37 en zijn nu historie. Handeling-knoppen zonder conflict zijn er niet; ze forceren (een dubbele planning
aanmaken) zou een write in de productieplanning zijn en is bewust niet gedaan.

**Bijvangst — de 500 op `planning/bulk` van 21-09 09:13:26 UTC (vóór de deploy, oude code):** latency `0s`, in dezelfde seconde een 500 op
een statisch asset (`NieuwProjectModal-….js`, óók `0s`) en twee 401's op `POST /auth/token/vernieuwen`. Dat is een verbinding-/sessie-
niveau-afbreking tijdens een pagina-herlaad ná sessieverloop, geen applicatiefout (geen Python-traceback in het log; de app logde op
21-09 nog zonder `logboek.py`). De browser herhaalde de bulk drie seconden later → 200 mét audit `planning_bulk` bron `vulhandvat`
(2 items, gedaan 1, conflict 1). Geen actie; genoteerd zodat een latere lezer het request-log niet als paneel-fout leest.

## Oordeel per meetlat van 21-09

| Meetrecept 21-09 | Uitkomst 22-09 |
|---|---|
| 1. `/planning?administratie=<Universal>` week 39: paneel-kop "N conflicten deze week", rijen mét soort + "Houd …" | Route live (17 × 200), maar N = 0 — er zijn geen conflicten vanaf vandaag. Paneel-rendering zelf niet zichtbaar in het log (frontend); geen Playwright in de repo. **Structuur werkt (lees-kant JA), rijen mét handeling: niet zichtbaar te maken zonder conflict.** |
| 1b. `?week=2026-W37` → chip "verstreken week", geen handelingsrijen | Frontend-gedrag, niet uit het log te lezen; guard-gedekt (`PlanningScreen.test.tsx`). **Niet gemeten in productie.** |
| 2. Één "Beide (halve dagen)…" → rij weg, kaartjes ½, rij `planning_conflict_akkoord`; derde kaart → rij terug | 0 akkoord-rijen, 0 conflict-akkoord-POSTs, 0 bulks bron `conflict`. **Niet gemeten — niet gebruikt en niets om op te klikken.** |
| 3. `veldwerkers-dubbelen --alles` → TOTAAL 0 clusters, 0 fouten | **JA** — bot-bestand `verkenning/nameting-veldwerkers-dubbelen-22-09.txt` op main (`d14277b`); sleutels bij Universal leeg (zie §1). |

## Keuzes (Peter keek niet mee)

1. **Geen conflict geforceerd.** Een dubbele planning aanmaken om het paneel te testen is een write in de echte Universal-planning én stuurt
   een "planning gewijzigd"-melding naar een veldwerker. Tellen, niet forceren — zoals de opdracht zegt.
2. **"0 dubbelen" niet als groen verkocht.** De cross-check op de sleutels staat in het rapport omdat een lege toets anders vijf dagen
   "groen" zou lijken (les groepssaldi 21-09). Dit is geen bug van de CLI en ook geen reden om naam-matching terug te halen.
3. **Vervolg-opdracht mét `niet vóór:` +7 dagen (poging 2 van hoogstens 3)** voor de handelingen — pas zinvol als er in de planning een
   conflict vanaf vandaag ontstaat óf Peter er bewust één maakt; daarna `mislukt/` mét de stand, geen reeks lege rapporten (regel 22-09
   corrigeren-nameting, rij (k)).
4. **Rapportkop 21-09 alleen een verwijsregel**, geen herschrijving.

## Vervolg

- **Klikwerk kantoor (geen code):** wil de dubbelen-toets tanden krijgen, dan moeten bij Universal dossiers mét KvK worden gezet
  (`/veldwerkers` → dossier, KvK-lookup bevestigen) en ZZP'ers aan hun crediteur worden gekoppeld (veldwerkers-paneel → crediteur).
  Beide zijn bestaande flows (25-08 blok A, factuurmatch fase 3). Tot dan is "0" per constructie.
- **Poging 2 handelingen:** `opdrachten/inbox/2026-09-29-nameting-planning-conflictenpaneel-handelingen-poging-2.md` (`niet vóór: 2026-09-29
  09:00`): zelfde lees-only recept (Cloud Logging conflict-akkoord + bulk bron `conflict`, `db-lezen` akkoord-tabel, dubbel-geplande
  persoon-dagen vanaf vandaag). Bij opnieuw 0 conflicten én 0 gebruik → `mislukt/` mét deze stand als eindstand; het paneel is dan
  "werkt in productie: lees-kant ja, handelingen ongebruikt".
- Geen wijziging aan code, tests of migraties in deze run.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/uren-planning-veldwerkers.md` (520 regels — stand vóór de run)
- `docs/regels/werkloop-productie.md` (276 regels — stand vóór de run)
