# Rapport 18-09 — Veld-app UX run B: dag-einde herinnering (punt 4) + offline werken (punt 5) — backend + frontend

Opdracht: `opdrachten/gedaan/2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md` (akkoord Peter 18-09 "alle punten"). Domeinen:
uren-planning-veldwerkers, accordering-native-app. Migratie **0162** (`administratie.uren_herinnering_tijd`, `gebruiker.uren_herinnering_uit`,
claim-tabel `boekhouding.uren_herinnering`). Beslispunten vooraf genoteerd: herinneringstijd default 16:30; opt-out PER GEBRUIKER (niet per
toestel); mockup v3 uitgebreid met schermen ⑤ + ⑥ vóór de bouw. Twee bouwagenten (5B backend, 5F frontend) op `CONTRACT_5.md`; de
verduidelijkingen (409-body onder FastAPI-`detail`, venster 06:00–18:59, 409 zonder uren-opt-in) zijn door 5F verwerkt.

**Werkt in productie: NIET GEMETEN** — deploy volgt via de Stop-hook. **Klikpunt Peter (éénmalig):** Cloud Scheduler-job
`rlz-uren-herinneringen` aanmaken (commando in deel A) — zonder scheduler draait de job nooit; dat is zichtbaar in de reconciliatiemail
(teller `uren_herinnering` blijft op 0 verwacht).

## Coördinator — migratie-routine en live-200 (dev)

| Stap | Uitkomst |
|---|---|
| `make migrate` (dev) | `Running upgrade 0161 -> 0162`; `alembic check` schoon |
| Live 200 (uvicorn 8011, Beheerder-token) | `GET /uren/beheer/herinnering-tijd/{aid}` → 200 `{"tijd":"16:30","standaard":true}` (geen instelling = default doorlopen) |

---

# DEEL A — Rapport blok 5B — Veld-app UX run B, punt 4 dag-einde herinnering (backend) + 409-contract offline (punt 5, server)

Opdracht: `opdrachten/lopend/2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md`. Contract: `CONTRACT_5.md` (geen inhoudelijke
afwijkingen; verduidelijkingen in `contract_afwijkingen_5.md`). Migratie **0162**. Domeinen: uren-planning-veldwerkers,
accordering-native-app.

**Werkt in productie: NIET GEMETEN** — meetrecept ná deploy: (1) `gcloud run jobs describe rlz-uren-herinneringen` = nieuwe
image; (2) scheduler bestaat (klikpunt) → job-log 16:45 toont `uren-herinneringen 2026-09-xx: … kandidaten=N verwacht=N gedaan=…`;
(3) testaccount zonder uren krijgt om ±16:45 de push "Nog geen uren voor vandaag", tikken opent Mijn uren (vandaag); (4) replica:
`boekhouding.uren_herinnering` één rij per testaccount per dag; (5) reconciliatiemail volgende ochtend draagt de regel
"Uren-herinnering einde werkdag (veld-app)  altijd  verwacht N, gedaan M, overgeslagen …".

## Klikpunt Peter — scheduler aanmaken (éénmalig)
`scripts/gcp/f3_jobs.sh` (stap 6 slaat bestaande jobs over en maakt de nieuwe aan) óf los:
```
gcloud scheduler jobs create http rlz-uren-herinneringen --location=europe-west4 \
  --schedule="0,15,30,45 15-18 * * 1-5" --time-zone="Europe/Amsterdam" \
  --uri="https://europe-west4-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/rlz-boekhouding/jobs/rlz-uren-herinneringen:run" \
  --http-method=POST --oauth-service-account-email="run-jobs@rlz-boekhouding.iam.gserviceaccount.com" --attempt-deadline=180s
```
(pas ná de deploy die de job aanmaakt; `PROJECT_ID`/`REGION` zoals in f3_jobs.sh.)

## Gebouwd
- **0162**: `platform.administratie.uren_herinnering_tijd` TIME NULL; `platform.gebruiker.uren_herinnering_uit` bool default false;
  `boekhouding.uren_herinnering` (id, gebruiker_id, administratie_id NULL, datum, verzonden_op, kanaal, detail; UNIQUE gebruiker+datum;
  FORCE RLS: systeem-actor + Beheerder + eigen rijen lezen; GRANT zonder DELETE). Modellen additief in `db/models.py` + `uren/models.py`.
- **Motor `app/uren/herinnering.py`**: `verstuur_dag_einde_herinneringen(nu=)` → `HerinneringRapport` (datum, werkdag, stille_uren,
  administraties_met_opt_in/tijd_bereikt, kandidaten, verwacht, gedaan, verzonden_push/mail, overgeslagen_al_uren/opt_out/
  al_verzonden/stille_uren/geen_kanaal/niet_actief, geen_tijd_bereikt, mislukt, fouten). Per administratie in haar eigen
  RLS-scope (les: `gebruiker_administratie`/`weekstaat` geven in `scoped_session(None)` als systeem-actor stil 0 rijen).
  Claim vóór verzenden; geen kanaal = claim `geen_kanaal`; verzendfout = geen claim. Audit `uren_herinnering_verzonden` per
  verzending + `uren_herinnering_run` per run (administratie-loos). `rapport_regel()` voor de job-uitvoer.
- **Service**: `herinnering_stand`, `zet_herinnering_uit` (audit `uren_herinnering_optout`), `herinnering_tijd_voor`,
  `zet_herinnering_tijd` (06:00–18:59 of None, audit `uren_herinnering_tijd_gewijzigd`); `WeekstaatBevroren` draagt `status` +
  `server_regel`; `zet_dag` vult ze bij een bevroren staat.
- **Routes**: `GET/PUT /uren/zzp/herinnering` (`vereis_veldrol`), `GET/PUT /uren/beheer/herinnering-tijd/{aid}` (`require_beheerder`),
  409-body op `PUT /uren/zzp/dag` mét `code/status/server_regel`.
- **CLI** `uren-herinneringen` (exit 1 alleen bij verzendfout). **deploy.yml**: `rlz-uren-herinneringen|uren-herinneringen|600` in de
  jobs-lus, case-tak samen met accordeur-herinneringen/nieuwe-facturen (MAIL+PUSH+FCM). **f3_jobs.sh**: schedulerregel
  `0,15,30,45 15-18 * * 1-5`. Guards bijgewerkt: `test_deploy_yml_image_uniform.VERWACHTE_JOBS`, `test_deploy_yml_envset_compleet.MAILENDE_JOBS`.
- **Reconciliatie** (`automatiseringen.py`): teller `UREN_HERINNERING` in VOLGORDE/LABEL, redenen `al_uren`/`opt_out`/`al_verzonden`/
  `stille_uren`/`geen_kanaal`/`niet_actief` (+ labels), `geen_kanaal` in HARDE_VOORWAARDEN mét DOEL_PAD `/veldwerkers`,
  vaste categorieën (al_uren, opt_out, geen_kanaal), actie `uren_herinnering_run` in `_ACTIES` en `bereken`.
- Gate-matrix: `GET/PUT /uren/beheer/herinnering-tijd/{aid}` toegevoegd aan `_kantoor_endpoints`.

## Tests (eigen DB `boekhouding_test_a5`)
| Aanroep | Uitkomst |
|---|---|
| `pytest tests/uren/test_herinnering_18_09.py` | 19 groen |
| `pytest tests/uren/test_herinnering_18_09.py tests/unit/test_optin_afwezig_pad_guard.py tests/unit/test_deploy_yml_envset_compleet.py tests/unit/test_deploy_yml_envvar_delimiters.py tests/unit/test_deploy_yml_image_uniform.py tests/unit/test_migratie_metadata_guard.py tests/unit/test_vaste_testconfig.py tests/reconciliatie/test_automatiseringen.py tests/reconciliatie/test_automatiseringen_herkoppeling.py tests/security/test_rol_endpoint_gates.py tests/uren/test_ux_run_a_18_09.py tests/uren/test_weekstaat_statusmachine.py tests/uren/test_veld_api.py` | 640 groen (3:36) |
| `ruff check` op eigen bestanden | schoon (`herinnering.py`), overige bestanden: alleen de E501's die HEAD al had |
| `python -m app.cli uren-herinneringen --help` | ok |

Incident: één per ongeluk gestarte pytest-aanroep zonder paden (lege `ls`-glob) op `boekhouding_test_a5` is binnen seconden gestopt;
alleen de eigen DB geraakt, daarna geen tests meer op die DB gedraaid.

## Beslispunten (gekozen)
1. Default 16:30, opt-out per gebruiker (contract); één herinnering per veldwerker per dag over álle administraties.
2. "Geen kanaal" claimt de dag (harde voorwaarde, LET-OP mét deeplink Beheer › Veldwerkers), morgen opnieuw.
3. 0-uren-regel telt niet als "al uren" (Σ > 0).
4. Scheduler start niet gepauzeerd (mail/push-kanaal is sinds 15/16-08 live geverifieerd).
5. Venster hard 06:00–18:59 voor de Beheerder-instelling; job stopt om 19:00.

## Gedeelde bestanden (met blokken 3/4B, parallel bewerkt — alleen additieve hunks van 5B)
`backend/app/uren/{models,router,schemas,service}.py`, `backend/app/db/models.py`, `backend/app/cli.py`,
`backend/app/reconciliatie/automatiseringen.py`, `backend/tests/security/test_rol_endpoint_gates.py`,
`backend/tests/unit/test_deploy_yml_{image_uniform,envset_compleet}.py`, `.github/workflows/deploy.yml`, `scripts/gcp/f3_jobs.sh`.
Eigen bestanden: `backend/app/uren/herinnering.py`, `backend/migrations/versions/0162_uren_herinnering.py`,
`backend/tests/uren/test_herinnering_18_09.py`.

## Open punten
- Frontend 5F: ⚙ Toegang-schakelaar, Instellingen-tijdveld, offline-wachtrij + conflict-sheet (contract_afwijkingen_5.md gelezen?).
- Coördinator: `make migrate` dev + live 200 op `GET /uren/zzp/herinnering` (veldtoken) en `GET /uren/beheer/herinnering-tijd/{aid}`; dump.
- Klikpunt Peter: scheduler aanmaken (boven).

---

# DEEL B — Rapport 18-09 — BLOK 5F: veld-app UX run B, frontend (offline werken + herinnering-schakelaar + herinneringstijd)

Opdracht: `opdrachten/lopend/2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md`, frontend-deel volgens `CONTRACT_5.md` (5F).
Backend = blok 5B (migratie 0162, motor, routes). Geen backend-bestanden geraakt.

**Werkt in productie: NIET GEMETEN** (deploy volgt via de Stop-hook). Meetrecept ná deploy (testaccount uitvoerder, PWA of native):
(1) vliegtuigstand aan → Mijn uren → kaart → "+ Uren" → 8 → Opslaan → toast "Geen verbinding — je regel is op dit toestel bewaard…",
kaart toont "● nog niet verzonden", dagbalk een oranje ●, banner "1 regel nog niet verzonden" mét "Nu verzenden"; (2) netwerk aan →
binnen een paar seconden toast "Bewaarde regel verzonden." en request-log `PUT /uren/zzp/dag` 200; (3) ⚙ Toegang toont de sectie
"Herinneringen" mét de schakelaar (request-log `GET /uren/zzp/herinnering` 200; schakelen = `PUT` 200); (4) kantoor-web Instellingen ›
Universal › Uren & materiaal toont "Herinnering einde werkdag (veld-app)" mét tijdveld 16:30 + chip "standaard"
(`GET /uren/beheer/herinnering-tijd/<aid>` 200 als Beheerder).

## Volgorde gevolgd
1. **Mockup eerst** — `mockup/uren-uitvoerder-v3.html`: scherm ⑤ (offline: banner + "Nu verzenden", bolletje per regel/kaart en in de
   dagbalk, indienen geblokkeerd tot verzonden, conflict-sheet mét beide standen en twee knoppen) en ⑥ (⚙ Toegang: schakelaar
   "Herinnering einde werkdag" · kantoor-web: tijdveld op Uren & materiaal + reconciliatie-tellers); Notities 12–13 (run B) toegevoegd,
   kop "run A + run B".
2. **Bouw** tegen CONTRACT_5 mét mocks.

## Gebouwd (frontend)
- `frontend/src/uren/urenOffline.ts` (nieuw, puur): IndexedDB `rlz-uren-offline` / store `wachtrij` (eigen DB náást het slot, zelfde
  open/transactie-patroon als `api/webVeiligeOpslag.ts`, sleutel-index onder `__index__` zodat fake én echte IDB zonder cursor werken);
  waarde versleuteld via `api/appSlot.ts::versleutelAlsSlotActief` (zelfde anker als het slot; zonder actief slot = `plain:`-fallback,
  dev). `isGeenVerbinding` = `TypeError` (fetch) óf `BackendOnbereikbaarError` (client vertaalt netwerk/502-504); `bevrorenConflict` leest de
  409-body `{code:'weekstaat_bevroren', status, server_regel}`; `verzendWachtrij(zend)`: geslaagd = weg, geen verbinding = stoppen (rest
  open), 409 bevroren = conflict markeren (blijft; één keer "nieuw" voor de sheet), andere fout = `fout` zichtbaar; `pasWachtrijToe` mengt
  de regels van één week in de kaarten (dag_uren, per kaart, per dag).
- `frontend/src/uren/UrenFlow.tsx`: `slaDagOp` (online = PUT, geen verbinding = wachtrij + toast) voor het invoerscherm én "Zelfde als
  gisteren"; `syncWachtrij` bij mount (app-opening), `online`-event en ná elke geslaagde verversing van de weekkaarten (`onVerverst`,
  alleen als er iets in de wachtrij staat — geen lus); ná een geslaagde ronde herladen de kaarten (`verversSleutel`) en toast "N bewaarde
  regels verzonden."; conflict → `OfflineConflictSheet` (beide standen, "Stand van kantoor houden" = regel weg / "Mijn regel bewaren tot de
  week weer open is" = blijft in de wachtrij en gaat mee zodra de week op corrigeren staat). WeekProjectenView: banner (`acc-notitie
  waarschuw`, "N regels nog niet verzonden — geen verbinding/verzenden lukte nog niet", knop "Nu verzenden" ≥ 48 px, conflict-/foutzin),
  chip "● nog niet verzonden" per kaart, oranje ● in de dagbalk, lokale uren tellen mee in de dagbalk; **indienen online-only**: mét
  bewaarde regels = toast "Indienen kan pas als de bewaarde regel(s) verzonden zijn", netwerkfout bij indienen = leesbare melding.
- `frontend/src/accordeur/appslot/HerinneringSchakelaar.tsx` (nieuw) + rij in `ToegangInstellingen.tsx` onder kop "Herinneringen", alleen
  voor veldrollen (`isVeldRol(useAuthOptioneel()?.rol)` — klant-accordeurs zien 'm niet; buiten een AuthProvider blijft de sectie weg);
  `GET/PUT /uren/zzp/herinnering`, toont de administratie-tijd in de uitleg.
- `frontend/src/instellingen/HerinneringTijdRij.tsx` (nieuw) onder de chips-rij op de tab Uren & materiaal (`AdministratieDetailPagina.tsx`):
  `<input type="time">`, chip "standaard", Opslaan (PUT `{tijd}`), "terug naar standaard" (PUT `{tijd:null}`), validatie 06:00–18:59 (contract 5B), 409 zonder uren-opt-in leesbaar.
- `frontend/src/uren/urenApi.ts` (`haalHerinnering`/`zetHerinnering`, `HerinneringInstellingDto`), `frontend/src/meerwerk/meerwerkApi.ts`
  (`haalHerinneringTijdBeheer`/`zetHerinneringTijdBeheer`) — additief.
- `frontend/src/accordeur/accordeur.css`: `.acc-offline-chip/.acc-offline-dot/.acc-offline-banner` (oranje = aandacht, nooit blokkerend;
  knop ≥ 48 px). Geen nieuwe tokens → contrast-test ongewijzigd groen.

## Tests
| Toets | Uitkomst |
|---|---|
| `vitest run src/uren/urenOffline.test.ts` (nieuw, fake IndexedDB, appSlot-mock) | 6 groen: versleuteld op het anker (geen leesbare tekst in IDB), vervangen zelfde dag, verwijderen/wissen, plain-fallback zonder slot, geen-verbinding-classificatie, geslaagd=weg + stoppen bij geen verbinding, 409 bevroren = conflict (één keer nieuw) + andere fout zichtbaar, mengen in de week |
| `vitest run src/uren/UrenFlow.offline.test.tsx` (nieuw, RTL achter login-gate + fake JWT) | 4 groen: netwerk uit bij Opslaan → regel in IDB + chip + dagbal-● + banner + indienen geweigerd (0 POST); "Nu verzenden" → PUT mét de bewaarde regel, banner/chip weg, toast; `online`-event verzendt; 409 bevroren bij app-opening → sheet mét beide standen ("6,0 u · ombouwen" vs "8,0 u · opbouwen"), "Stand van kantoor houden" = index leeg, 0 PUT |
| `vitest run src/accordeur/appslot/HerinneringSchakelaar.test.tsx` (nieuw) | 2 groen: GET → tijd zichtbaar + aan; schakelen = PUT `{uit:true}`; 403 = leesbare fout, stand blijft |
| `vitest run src/instellingen/HerinneringTijdRij.test.tsx` (nieuw) | 3 groen: validatie 06:00–18:59; laden mét chip "standaard", PUT `{tijd:'17:00'}`, "terug naar standaard" = PUT `{tijd:null}`; 409 zonder opt-in leesbaar |
| `vitest run src/uren src/accordeur src/instellingen src/styles` | 75 bestanden / 550 tests groen (bestaande run-A-, detacheerder-, Toegang- en contrast-tests ongewijzigd; querytelling van de bestaande veld-app-tests onveranderd — de offline-laag doet géén extra request zolang de wachtrij leeg is) |
| `tsc -b` | groen |
| Overflow-sweep `POORT=5203` | de tab Uren & materiaal zit NIET in de sweep-lijst (alleen `tab=boeken-ai`); gedraaid op de bestaande detailpagina-variant `…&tab=boeken-ai` — zie regel hieronder (coördinator: overweeg `&tab=uren-materiaal` toe te voegen aan `overflow_sweep.sh`; het harnas kent `?tab=` generiek maar mockt `/uren/beheer/*` niet — chips- én tijdrij tonen daar een laadfout, geen overflow) |

Sweep-uitkomst (, detailpagina , licht + donker × 1440/1170/1024/768): Sweep groen: 16 metingen zonder horizontale pagina-overflow. — de rij zelf (HerinneringTijdRij: input type=time 110 px + chip + knop, flex-wrap) volgt het InstellingRij-patroon van de chips-rij.

## Beslispunten (gekozen, conform CONTRACT_5)
1. Opt-out herinnering PER GEBRUIKER (schakelaar in ⚙ Toegang; alleen veldrollen). 2. Conflict: twee knoppen — "Stand van kantoor houden"
   (regel weg) / "Mijn regel bewaren" (blijft tot de week weer bewerkbaar is; nooit stil overschrijven). 3. Geen verbinding = fetch-TypeError
   ÓF `BackendOnbereikbaarError` (502–504/timeouts): ook bij een platte backend blijft de regel bewaard. 4. Indienen online-only en pas ná een
   lege wachtrij (anders dien je een halve week in). 5. Zonder actief slot (dev/kantoor) plain-opslag — de veld-app draait altijd achter het
   slot (0029); benoemd in de code. 6. `navigator.storage.persist()` stond al (run A) — niet dubbel aangeroepen.

## Contractafwijkingen verwerkt (`contract_afwijkingen_5.md` van 5B, gelezen volledig — punten 1–6)
1. **409-body onder FastAPI-`detail`** (`{"detail": {"detail": tekst, "code": "weekstaat_bevroren", "status", "server_regel"}}`): de
   client geeft het `detail`-object door als `ApiError.detail` — `bevrorenConflict` las dat al goed; nu expliciet gedocumenteerd, de
   binnentekst `detail` alleen als string overgenomen en defensief óók een extra nesting-niveau herkend. Bedragen als strings ("8.00",
   "40.00") gaan ongewijzigd door `urenLabel` (test uitgebreid).
2. `GET/PUT /uren/zzp/herinnering` → `{uit, tijd}`: exact zo gebouwd, geen wijziging.
3. `GET/PUT /uren/beheer/herinnering-tijd/{aid}` → `{tijd, standaard}`, PUT `{tijd|null}`: exact zo; **validatie aangepast naar
   06:00–18:59** (was 06:00–23:00; melding noemt de 19:00-grens van de job); **409 zonder uren-opt-in** = leesbare fout "Niet mogelijk:
   ‹servertekst›" in de rij, stand blijft (nieuwe test).
4–6. Reconciliatie-teller `uren_herinnering`, audit-namen, claim-kolom `detail`, sentinel `geen_tijd_bereikt = -1`: backend-intern, geen
   frontend-impact — kennisgenomen.
Hertest ná verwerking: `tsc -b` groen; `vitest run src/uren src/accordeur src/instellingen` 525 groen (styles-suite ongewijzigd, eerder 25 groen).

## Gedeelde bestanden
`frontend/src/meerwerk/meerwerkApi.ts` (additief, 2 functies — domein uren, buiten de 5F-lijst maar de bestaande plek van de beheer-routes),
`frontend/src/instellingen/AdministratieDetailPagina.tsx` (één import + één rij op de tab Uren & materiaal). Geen `api/types.ts`-wijziging nodig.

## Klikpunten Peter
- Vliegtuigstand-test op het testaccount (meetrecept punt 1–2); Instellingen › Universal › Uren & materiaal: tijd op 16:30 laten of aanpassen.
- Beslispunt bevestigen: opt-out per gebruiker (niet per toestel).

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (353 regels) — volledig (geërfd van de coördinator, vóór de start).
- `docs/regels/accordering-native-app.md` (271 regels) — volledig.
- `docs/regels/werkloop-productie.md` (55 regels) — volledig.
- `docs/regels/uren-planning-veldwerkers.md` (353 regels bij start) — volledig, vóór de start.
- `docs/regels/accordering-native-app.md` (271 regels) — volledig, vóór de start.
- `docs/regels/kantoor-frontend.md` (113 regels) — volledig (tijdveld op Instellingen).
