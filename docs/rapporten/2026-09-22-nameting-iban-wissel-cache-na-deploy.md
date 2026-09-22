# Nameting checks-cache-invalidatie (IBAN-wissel ná vier-ogen-akkoord) ná de deploy van 21-09 + nazorg `checks-cache-legen` (22-09)

Opdracht `opdrachten/gedaan/2026-09-22-nameting-iban-wissel-cache-na-deploy.md` (inbox-run, `niet vóór: 2026-09-22 09:00`; gestart
22-09 ~10:20 NL). Bouwrapport: `docs/rapporten/2026-09-21-iban-wissel-cache.md`; BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON
(IBAN-akkoord) 21-09" (alinea "Gemeten 22-09" toegevoegd). Peter keek niet mee; keuzes staan in "Keuzes".

**Één regel voor Peter:** de nazorg is gedaan (129 oude cache-rapporten in 12 administraties ongeldig gemaakt, daarna 0), en de fix
werkt aantoonbaar in productie op het bevestig-pad: op 21-09 om 17:38 werd een IBAN bevestigd en 3 seconden later liep de controle
opnieuw écht tegen Reeleezee in plaats van uit de 12 seconden oude cache. Het Meyer-document zelf wacht op de derde accordeur en is
sinds de deploy door niemand geopend; de knop "Opnieuw controleren" en de vier-ogen-route zijn nog door niemand gebruikt — die drie
metingen lopen door in de vervolg-opdracht van 23-09. Bijvangst: de snelheidsmeting `server_timing` uit "Boeken sneller" (18-09) kwam
nooit in Cloud Logging aan; dat is nu gerepareerd.

## Werkt in productie — per stap

| Stap | Uitkomst | Werkt in productie |
|---|---|---|
| 0 deploy-check | service `rlz-backend` én job `rlz-reconciliatie` op `78c13c3` (`command: python`); fix `10c9fa3` is voorouder; deploy `7881cfd` klaar 21-09 10:16Z = fix live sinds 12:16 NL; `main..origin/main` = 0 | ja |
| 1 nazorg `checks-cache-legen --alles` | dry-run 1: 78 administraties, 129 geldig, 0 ongeldig gemaakt (executie `rlz-reconciliatie-t9vpj`); echte run: 129 ongeldig gemaakt (`-fhs66`); dry-run 2: 2 geldig / 0 (`-gwbfx`; Bonte Hoeve 2 = vers geschreven ná de echte run door post-fix-code) | ja |
| 2.1 Meyer 0015.21.664.V.51.0112 | status `ter_accordering` sinds 21-09 10:17:59 NL, laag 1 akkoord 10:18, laag 2 10:54, laag 3 (klant-accordeur) open; niet geboekt; 0 checks-requests op het document ná de deploy; IBAN NL04RABO0200112244 staat in de vertrouwde set (bevestigd 09:15) | niet gemeten (niet herladen door een mens) |
| 2.1b invalidatie bij bevestiging | request-log 21-09 17:38 NL, document a05c4c47 (scope 59bf1f7f): externe run 17:38:20 → `bevestig_iban` 17:38:29 → externe run 17:38:32 mét nieuwe cache-rij | **ja** |
| 2.2 `POST …/checks?extern=vers` | 0 × in 48 checks-requests sinds de deploy (24 gewoon, 24 `voorverwarm=1`) | niet gemeten (geen mens raakte de knop/409-route) |
| 2.3 audit `checks_cache_ongeldig` | 3 × `leverancier_iban_toegevoegd` sinds de deploy (baseline 12:46, bevestigd 17:38, rlz_seed 19:15 NL), 0 vier-ogen-akkoorden; het veld stond alleen op het akkoord-pad → nu op élk pad (fix in deze run) | niet gemeten (geen akkoord); veld-gat gedicht |
| 2.4 Server-Timing `checks.extern` | `jsonPayload.message="server_timing"` = 0 regels sinds 18-09: de logregel bereikte Cloud Logging nooit (bouwgat, gedicht: `app/logboek.py`); terugval request-log-latency `POST …/checks`: 21-09 n=149 p50 0,45 s / p95 1,57 s vs nulmeting 18-09 p50 0,79 / p95 2,14 — geen regressie | nee voor de logregel (gefixt, meting 23-09); ja voor "geen regressie" op route-niveau |

## Stap 0 — deploy-check

```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 → image …/backend:78c13c35e0aa…, command ['python']
gcloud run services describe rlz-backend  → image …/backend:78c13c35e0aa…
git merge-base --is-ancestor 10c9fa3 78c13c3 → ja; git rev-list --count main..origin/main → 0
```
Deploy-runs (gh): `7881cfd` 21-09 10:11→10:16Z (eerste image mét de fix), daarna `81f5de2`, `579af58`, `c43111e`, `fb63be5`, `78c13c3` (22-09 08:11→08:17Z).

## Stap 1 — nazorg (schrijvend, job-image)

Drie executies via `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="-m,app.cli,checks-cache-legen,--alles[,--dry-run]"`;
logs gelezen via `gcloud logging read … labels."run.googleapis.com/execution_name"=<executie>` (totaalregel + regels per administratie).

| Executie | Vorm | Totaalregel |
|---|---|---|
| `rlz-reconciliatie-t9vpj` | `--alles --dry-run` | `78 administratie(s), 129 geldig, 0 ongeldig gemaakt` |
| `rlz-reconciliatie-fhs66` | `--alles` | `78 administratie(s), 129 geldig, 129 ongeldig gemaakt` |
| `rlz-reconciliatie-gwbfx` | `--alles --dry-run` | `78 administratie(s), 2 geldig, 0 ongeldig gemaakt` (Bonte Hoeve B.V. 2) |

Per administratie (dry-run 1 = echte run): Universal Steigerbouw 77, Kempen Facilities 21, Bouwadvies Oost Nederland 12, Necol Energie 7,
Administratiekantoor Nijenhuis 2, Old Dutch 2, Oirschot Recreatie 2, Recreatief Vastgoed Nederland 2, Rubicon 1, Recreapi 1,
Beleggingsmaatschappij Meyer 1, Belastingbutler 1. **Kanttekening op de opdrachttekst:** "geldig" in de CLI (`checks_extern.tel_geldig`)
telt élke nog niet gemarkeerde cache-rij, ongeacht leeftijd — niet "rapporten < 15 min oud". 129 op een maandagochtend is dus de hele
voorraad rapporten sinds 18-09, geen actuele werkvoorraad. De 2 rijen van Bonte Hoeve in dry-run 2 zijn tussen de echte run (10:36 NL) en
dry-run 2 (10:38 NL) vers geschreven door post-fix-code (vingerafdruk mét set-hash) en hoeven niet weg.

## Stap 2 — metingen (lees-only)

### 2.1 Meyer-document (`db_lezen.sh` op de leesreplica, `--administratie 876d5515-…`; `document-feiten` kent geen `referentie`-parameter, daarom vrije SELECT)

Document `2f9c342c-0aeb-4881-b53d-6e65455c5c8b`, inkoopfactuur, € 34,00, vendor `5f897c38-…`, cache-rij `gecontroleerd_op` 21-09 08:17:56Z,
nu `ongeldig:…` (door de nazorg). Tijdlijn (UTC → NL +2):

| NL-tijd 21-09 | Overgang | Detail |
|---|---|---|
| 09:15:47 | wacht_op_iban_accordering → te_controleren | `iban_geaccordeerd` (het vier-ogen-akkoord uit Peters screenshot) |
| 09:30:14 | te_controleren → vraag_open | "dit wordt geblokkeerd vanwege IBANn nummer, kan je hierna kijken?" |
| 10:17:49 | vraag_open → te_controleren | vraag afgehandeld |
| 10:17:58 | te_controleren → klaar_om_te_boeken | `harde_checks: doorstaan` — verse externe run (cache-rij 10:17:56), vóór de fix-deploy: de cache van 09:15 was ná 15 min verlopen |
| 10:17:59 | klaar_om_te_boeken → ter_accordering | 3 lagen |
| 10:18:12 / 10:54:04 | ter_accordering | akkoord laag 1 / laag 2 |

Vertrouwde set: NL86INGB0002445588 (rlz_seed 14-09) + NL04RABO0200112244 (bevestigd 21-09 09:15:47). Laag 3 is open; niemand opende het
document ná de deploy (0 checks-/boekvoorstel-requests op dit id sinds 21-09 12:16 NL). **Niet gemeten.** Wat de casus wél laat zien: de
klacht van 09:15–09:30 loste destijds op door de klok (15 min), precies het gedrag dat de fix overbodig maakt.

### 2.1b Bewijs op het bevestig-pad (request-log + audit + cache-rij)

Administratie `59bf1f7f-7460-4b04-bb27-b131691ccdf6`, document `a05c4c47-c4a4-4257-a6f8-d8da61eb8c72` (te_controleren), 21-09 (UTC):

```
15:38:20.524  POST …/doc/boekvoorstel/checks   200  1,23 s   ← externe run, cache-rij geschreven
15:38:29.601  audit leverancier_iban_toegevoegd {"bron":"bevestigd","iban":"NL83ABNA0138691800"}
15:38:30.181  PUT  …/doc/boekvoorstel          200  2,31 s
15:38:32.580  POST …/doc/boekvoorstel/checks   200  0,81 s   ← cache-rij gecontroleerd_op 15:38:32.911 = NIEUWE externe run
```
Twaalf seconden ná een externe run, ver binnen de 15 min, draaide de controle opnieuw extern en schreef een nieuwe cache-rij. Zonder
`maak_ongeldig_voor_vendor` + set-hash in de vingerafdruk was 15:38:32 een cache-hit geweest (geen nieuwe `gecontroleerd_op`).
Kanttekening: de PUT om 15:38:30 kán de vingerafdruk óók veranderd hebben (crediteur/referentie/bedrag) — de keten bevestiging → verse run
binnen 3 s is er precies het patroon van de fix; ik noem het "ja" mét deze kanttekening. **Werkt in productie: ja.**

### 2.2 Request-log `?extern=vers`

Cloud Logging `httpRequest.requestUrl:"boekvoorstel/checks"` sinds 21-09 10:17Z: 48 requests (45 op 21-09, 3 op 22-09 tot 10:40 NL), 24 ×
`checks`, 24 × `checks?voorverwarm=1`, **0 × `extern=vers`**. Niemand klikte "Opnieuw controleren" en de 409-route trad niet op.
**Niet gemeten.**

### 2.3 Audit `checks_cache_ongeldig`

`platform.audit_event` heeft geen Beheerder-RLS-clausule voor rijen mét `administratie_id` (zonder scope: 65 rijen sinds 21-09, alle
`administratie_id` NULL) → sweep per administratie (`.scratch/audit-iban-sweep-22-09.sh`, 79 administraties, lees-only). Sinds de
fix-deploy: `005e2bca…` 21-09 12:46 NL baseline NL45BUNQ…; `59bf1f7f…` 17:38 NL bevestigd NL83ABNA…; `3ee6edf0…` 19:15 NL rlz_seed
NL06RABO…. Geen enkele mét `checks_cache_ongeldig`: het veld stond alleen op het akkoord-pad (`iban_accordering.accordeer`), en er was
geen akkoord. **Niet gemeten voor het akkoord-pad; gat gedicht** — `_voeg_toe` schrijft het veld nu óók (bevestig/seed/baseline), zodat het
meetrecept "veld bestaat, ≥ 0" voor élke set-mutatie geldt.

### 2.4 Server-Timing `checks.extern`

`jsonPayload.message="server_timing"` (het meetrecept van 18-09) = **0 regels sinds 18-09**, ook zonder route-filter en als vrije tekst.
Oorzaak (code gelezen): `router._zet_server_timing` logt `logger.info(...)` op `app.documenten.router`; de `app`-loggers hebben geen
handler, de Python-root staat op WARNING → de regel wordt weggegooid. Alleen uvicorn's eigen access-log (textPayload `INFO: … "POST …
HTTP/1.1" 200 OK`) komt aan. Het beslispunt "15 min omhoog ná een week `checks.extern` meten" had dus nooit data gekregen.
**Terugvalmeting** (hele route, `httpRequest.latency`, `POST …/checks` zonder voorverwarm): 20-09 (zondag) n=0; 21-09 n=149 p50 0,45 s /
p95 1,57 s (voorverwarm n=115 p50 1,49 / p95 2,71); 22-09 tot 10:40 n=2 (2,21 / 3,38 — te weinig). Nulmeting 18-09 (zelfde bron): p50
0,79 / p95 2,14 → geen regressie door de extra lokale query. **Werkt in productie: nee voor de logregel (gefixt in deze run), ja voor
"geen regressie".**

## Gebouwd in deze run (twee bouwgaten + één testgat)

1. **`app/logboek.py`** (nieuw) — `configureer_logboek()`: één JSON-`StreamHandler` op **stderr** (stdout blijft het CLI-rapport; tests
   toetsen `capsys.out`), root WARNING, `app` INFO, idempotent, `extra=`-velden als eigen sleutels; aangeroepen bij import van `app.main`
   (service) en in `app.cli.main` (jobs — óók `boek_wachtrij_afgerond.stappen_ms`). Guard `tests/unit/test_logboek.py` (6): server_timing
   als JSON mét route/document_id/stappen_ms, httpx/sqlalchemy-INFO stil, WARNING van derden komt door, exception + niet-serialiseerbare
   extra, idempotent, service+jobs roepen aan, default stderr.
2. **`leverancier_iban._voeg_toe`** — audit `leverancier_iban_toegevoegd` draagt `checks_cache_ongeldig` (aantal) op élk pad;
   gouden-set-casus af: nieuwe test `test_elk_pad_naar_de_vertrouwde_set_auditeert…` (baseline 0, akkoord ≥ 1; bron-volgorde
   `baseline`, `bevestigd`).
3. **CLI-vorm `--alles`** stond niet in de suite (regel 19-09 "élke CLI-vorm uit het meetrecept is gedraaid") →
   `TestCliChecksCacheLegen::test_cli_alles_vorm_uit_het_meetrecept_dry_run_echt_dry_run` (dry-run → echt → dry-run 0, exact de productie-volgorde).

Poort: `pytest tests/unit/test_logboek.py tests/documenten/test_checks_cache_invalidatie.py tests/unit/test_leverancier_iban_invalidatie_guard.py
tests/documenten/test_iban_accordering.py tests/documenten/test_iban_wissel.py tests/unit/test_cli_smoketest.py` = 70 passed;
`tests/keten/test_af_iban_akkoord_checks_cache.py tests/unit/test_keten_guard.py tests/unit/test_logboek.py` = 10 passed; ruff schoon op de
eigen bestanden (main.py/cli.py alleen op de eigen regels — die bestanden zijn niet format-schoon). Geen frontend-wijziging, geen migratie,
geen RLZ-write. Docs-guards: zie de slotregel van de commit.

## Keuzes (Peter keek niet mee)

- **Nazorg zonder aarzelen uitgevoerd:** de opdracht schreef de drie commando's letterlijk voor, gcloud was ingelogd, de deploy-check was
  groen → geen klikpunt.
- **"Ja" op het bevestig-pad ondanks dat de opdracht het akkoord-pad noemde:** beide paden delen `maak_ongeldig_voor_vendor` + set-hash; het
  bewijs uit het request-log is het sterkste dat er zónder een mens te storen te vinden was. Het akkoord-pad blijft "niet gemeten" tot een
  echt akkoord.
- **Logboek-fix in déze run i.p.v. een aparte opdracht:** de opdracht zei "rood = fix in dezelfde run"; een meetlat die vier dagen leeg
  was zonder signaal is rood in de zin van regel 21-09 ("niet gemeten is een schuld"). Minimaal gehouden (één handler, stderr, geen
  wijziging aan uvicorn/access-log), wél guard.
- **Geen dispatch-onderdeel in `nameting.yml`:** de drie open metingen zijn mens-afhankelijk (herladen, knop, akkoord) en de vierde is een
  eenmalige "komt de logregel aan"-toets; een vervolg-opdracht mét `niet vóór:` volstaat en houdt de workflow klein. Als 23-09 opnieuw
  "niet gemeten" oplevert, hoort het als onderdeel in de workflow (regel 21-09 (1)).
- **WAT_IS_NIEUW niet bijgevuld:** geen klantzichtbare verandering (nazorg + logregel + audit-veld).
- `.scratch/audit-iban-sweep-22-09.sh` blijft als recept in `.scratch/` (untracked), tekst in dit rapport.

## Vervolg

`opdrachten/inbox/2026-09-23-nameting-iban-wissel-cache-mens-en-server-timing.md` (`niet vóór: 2026-09-23 09:00`): Meyer-status/boekstuk,
`?extern=vers`, audit-veld op élke rij, eerste `server_timing`-regels ná deze deploy (werkt in productie ja/nee) + p50/p95 zodra ≥ 20 regels.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/werkvoorraad-controlescherm.md` (368 regels; 379 ná deze run),
`docs/regels/autoboeken-ai.md` (134 regels), `docs/regels/werkloop-productie.md` (233 regels; 244 ná deze run).
