# Rapport 18-09 — Projecten (steigerbouw): status "afgesloten" + projectnummer uniek

Opdracht: `opdrachten/gedaan/2026-09-18-projecten-status-afsluiten-en-nummer-uniek.md` (Peter 18-09: "Bij steigerbouw moeten
projecten een status krijgen; als een project afgesloten is kan het uit de lijst." · "Per abuis 2× hetzelfde projectnummer
aangemaakt — moet geblokkeerd worden."). Domeinen: verplichtingen-projecten-voorraad, uren-planning-veldwerkers. Migratie
**0160** (`project_cache.status/afgesloten_op/afgesloten_door/afsluit_reden` + index (administratie_id, status) + CHECK).
Gebouwd + getest 18-09-2026 (bouwagent blok 3, inbox-run 2).

**Werkt in productie: NIET GEMETEN** — deploy volgt via de Stop-hook ná de run. Meetrecept ná deploy:
1. Universal Steigerbouw › Projecten › "+ Nieuw project" met een BESTAAND nummer (bv. 26127) en een TEST-plaats → 409
   "26127 bestaat al: ‹naam›, lopend — openen?" mét knop "Openen"; niets aangemaakt (request-log `POST /projecten/{aid}` 409;
   `rlz-lezen Projects --filter "startswith(Name,'26127 ')"` toont géén nieuwe rij).
2. Een TEST-project afsluiten (detail › Afsluiten…, reden "nameting") → 200, chip "afgesloten op …", `rlz-lezen Projects/{id}` →
   `IsActive: false`, project weg uit de planning-projectbalk en de weekstaat-projectkeuze in de veld-app; "Heropenen" → `IsActive:
   true`, terug in de lijsten. Audit `project_afgesloten`/`project_heropend` op de replica (`db_lezen.sh … platform.audit_event`).
3. Lees-only rapporten via de nameting-job (allowlist): `projecten-dubbele-nummers --administratie "Universal Steigerbouw"` (Peter's
   casus: beide id's + tellers per kant + voorstel "blijft") en `projecten-afsluit-kandidaten` (welke van de actieve
   VGG/Universal-projecten voldoen aan het kandidaat-criterium, mét bron per regel). Klaar om ná deploy te draaien; niets
   uitgevoerd tegen productie in deze run.

## Feiten vooraf (code gelezen)

| Vraag | Bevinding |
|---|---|
| Waarom glipte een dubbel nummer erdoor? | `kantoor.maak_project_aan` toetste alleen de EXACTE naam (`find_projects_by_name`); zelfde nummer + andere plaats = ander GUID-pad? Nee: hetzelfde deterministische GUID (`rlz_steiger_project_id` = administratie + nummer) → `bestaand` gevonden → "bestond_al" met de OUDE naam terug, of — als het tweede project rechtstreeks in RLZ was aangemaakt — geen enkele toets. RLZ kent géén codeveld (STAP-0 16-09): het nummer is de cijfer-prefix van de naam. |
| Is er al een status? | Nee. `project_cache.is_actief` spiegelt RLZ `IsActive`; álle keuzelijsten (planning `_vereis_actief_project`, `overzichten.week_projecten_zzp`, verplichting-extractie, kantoorbreed, projectverdeling, cijfers) filteren daar al op. De combobox toont inactief onderaan mét chip (16-09). |
| Contractsom voor "verkoop = contractsom"? | Bestaat niet in het model (geen kolom, geen staffel-som). Wél `contract_m2` (specificatie/contract-ontleding) en `gebouwd_m2` (goedgekeurde weekstaten). |
| Odoo-projecten | `project_cache.brondata.odoo_id` + `odoo_id_koppeling` (model `account.analytic.account`); geen projecten-port in `app/backends` — alleen `OdooClient.write`. |

## Gebouwd

**Blok A — status.** `project_cache.status` (lopend/afgesloten) is de MODULE-status náást `is_actief` (spiegel van de bron).
`app/projecten/status.py::sluit_project_af/heropen_project`: rolpoort `_vereis_schrijfrol` (Beheerder + B+P), eerst de bron —
RLZ klant-loze `PUT Projects/{id}` mét de BESTAANDE naam (PUT = create-or-update, nooit een andere naam sturen) + `IsActive:false`
en terugleesverificatie (`IsActive` niet overgenomen → `BronWeigert` → 502, status ongewijzigd: RLZ wint); Odoo `active=False` via
de company-gebonden client + teruglezen — dán status + `is_actief` + afsluit-spoor + audit oud→nieuw (`project_afgesloten`/
`project_heropend`). Routes `POST /projecten/{aid}/{pid}/afsluiten` (reden/datum optioneel) en `…/heropenen` (409 al in die
stand, 502 bron weigert). Lijst per administratie: `alleen_actief` = ook `status != afgesloten`; `aantal_afgesloten` voedt de
toggle "Toon afgesloten (N)" (`alleen_actief=false`, rij grijs mét chip). Detail draagt status/afgesloten_op/door/reden.
Inzicht › Projecten: `toon_afgesloten`-param (`?afgesloten=1`), facetten `afgesloten` en `kandidaat_afsluiten`, tellers
`afgesloten`/`kandidaat_afsluiten`, afgesloten rijen onderaan. Frontend: `ProjectDetailScreen` (chip in de kop, "Afsluiten…"-dialoog
mét reden + datum, "Heropenen"), `ProjectenScreen` en `ProjectenKantoorbreedScreen` (toggles, chips), `projectenApi.ts`.
**Oranje signaal**: `checks.check_project_afgesloten` (ok=True, signaal=True, "Project afgesloten: ‹naam› (afgesloten op ‹datum›) —
nagekomen factuur? Boeken kan; heropen …") via `boekvoorstel._project_afgesloten_check` in BEIDE rapport-takken (normaal + RLZ-
storing), alleen als er een afgesloten project op een regel staat. **Kandidaat afsluiten**: `status.kandidaat_afsluiten_per_project`
(set-based, vier statements per administratie: weekstaten via ISO-week, planning, verplichtingen, factuurregels): stil ≥ 90 dagen
ÉN gebouwd-m² ≥ contract-m² → chip "kandidaat afsluiten" (teller + rij mét reden-tooltip); nooit automatisch afsluiten.

**Blok B — nummer uniek.** `app/projecten/nummer.py`: `cijfer_prefix`, `treffers_in_cache` (naam LIKE + exacte prefix),
`treffers_in_rlz` (nieuw `RlzClient.find_projects_by_name_prefix` = `startswith(Name,'26127 ')`, actief én inactief),
`vereis_nummer_vrij` in `maak_project_aan` direct ná de GUID-lookup: élke treffer (cache óf RLZ, lopend óf afgesloten) →
`ProjectnummerBestaatAl` → router 409 mét gestructureerd detail (`code`, `nummer`, `bestaand_project_id`, `bestaand_naam`,
`status`, `bron`); alleen exact dezelfde naam op het eigen GUID = idempotente herhaal-klik (`bestond_al`). `NieuwProjectModal`
toont de melding + "Openen" (kiest het bestaande project). Volgnummer-voorstel (`volgende_projectnummer`) blijft het
eerstvolgende vrije nummer van het jaar, voorgevuld. **Dubbelen**: `nummer.dubbele_nummers` + `rapportregels` (per kant facturen/
weekstaten/planning, voorstel "blijft" = meeste activiteit) → lees-only CLI `projecten-dubbele-nummers`; **reconciliatie-soort
`project_nummer_dubbel`** (blok `projecten`, `nummer.cli_blok` in `reconciliatie-alles` + `run.BLOKKEN`, registry `soort_stand`
stand `meten`, tekst in `teksten._projecten`, vingerafdruk administratie+nummer). CLI's `projecten-afsluit-kandidaten` en
`projecten-dubbele-nummers` (`app/projecten/cli_cmd.py`) in de nameting-allowlist.

## Tests

| Toets | Uitkomst |
|---|---|
| `tests/projecten/test_status_en_nummer.py` (nieuw, eigen DB `boekhouding_test_a3`) | 15 groen: afsluiten → bron eerst, audit, heropenen; RLZ-conflict = 502 + ongewijzigd; rolpoort; Odoo-fake `write active=False`; lijst/toggle/teller + `lijst_projects` onderaan; kantoorbreed toggle/facet/tellers; API 200/409/heropenen; kandidaat (stil+contract / recent / geen contract); nummer 409 + idempotent + afgesloten bezet + RLZ-extern + prefix exact; API 409-detail; `cijfer_prefix`; dubbele nummers + blok + `meten` + leesbare tekst; signaal |
| `tests/keten/test_v_project_afgesloten_signaal.py` (nieuw — gouden-set-guard `test_keten_guard` groen) | 2 groen: signaal op PROJECT_26049, lijstroute houdt afgesloten zichtbaar onderaan |
| Bestaande suites: `tests/projecten` (alle), keten u/k, `reconciliatie/test_soort_stand|test_teksten|test_run`, `security/test_rol_endpoint_gates`, `unit/test_keten_guard|test_migratie_metadata_guard|test_optin_afwezig_pad_guard`, `documenten/test_checks`, `tests/sync` | 819 groen (achtergrondrun 6 min 18 s op eigen DB; één bestaande assertie op de exacte tellers-dict in `test_kantoorbreed.py` aangevuld met de twee additieve tellers `kandidaat_afsluiten`/`afgesloten` — daarna 24/24 in projecten) |
| Frontend `vitest run src/projecten` | 5 bestanden / 18 groen (nieuw `ProjectStatus.test.tsx` 4: dialoog → POST reden+datum → chip + Heropenen; lijst-toggle `alleen_actief=false` + grijze rij; kantoorbreed chips + `toon_afgesloten`; modal 409 → melding + Openen) |
| `tsc -b` | groen |
| `POORT=5204 HARNASSEN_ALLEEN="harness-werkvoorraad.html?projecten=1" overflow_sweep.sh` | 8/8 ✅ |
| ruff | eigen bestanden schoon (E501 in `cli.py`/`teksten.py` = pre-existing) |

## Beslispunten (gekozen)

1. **Kandidaat-criterium zonder contractsom**: gebouwd-m² ≥ contract-m² is de deterministische maat; zonder contract-m² geen
   kandidaat (reden zichtbaar: "geen contract-m² bekend"). Peter kan het criterium bijstellen.
2. **Combobox verbergt afgesloten projecten niet**: onderaan mét chip "inactief" (16-09-patroon) — een document dat er al op staat
   blijft leesbaar en een nagekomen factuur kan er bewust op (oranje signaal). Planning/weekstaat/verplichting filteren wél hard
   (`is_actief`).
3. **Uren-/planningcode niet geraakt** (blok 4 bouwt daar): het filter loopt via `is_actief`, dat afsluiten op false zet.
4. **Odoo via `OdooClient` rechtstreeks** (geen projecten-port bestaat) — adapter-seam-grep voor BESLISSINGEN "ODOO-ADAPTER — GREPEN".
5. **Nummer-poort vóór de idempotentie**: zelfde nummer + andere plaats op hetzelfde GUID was tot nu een stille "bestond_al" met de
   oude naam; nu 409 — alleen exact dezelfde naam blijft de herhaal-klik.

## Klikpunten Peter

- Testproject afsluiten + heropenen (meetrecept 2); nieuw project met bestaand nummer → 409 (meetrecept 1).
- Ná deploy: rapporten `projecten-dubbele-nummers` en `projecten-afsluit-kandidaten` via de nameting-job lezen → welke dubbeling
  samenvoegen (welke blijft, wat verhuist) — nooit automatisch, RLZ-project nooit verwijderen.

## Gedeelde bestanden (buiten de blokgrenzen, additief)

- `backend/app/rlz/client.py` — één methode `find_projects_by_name_prefix` (administraties-domein).
- `backend/app/sync/models.py` — kolommen op `ProjectCache` + constanten `PROJECT_STATUS_*`.
- `backend/app/documenten/checks.py` + `boekvoorstel.py` — het oranje signaal (toegestaan door de opdracht; keten-test toegevoegd).
- `backend/app/reconciliatie/{soort_stand,teksten,run}.py`, `backend/app/cli.py` (blok + import + 2 commando's), `scripts/gcp/nameting.sh` (allowlist).
- NIET geraakt maar wenselijk: `frontend/src/reconciliatie/reconciliatieApi.ts::BLOK_LABEL` mist `projecten: 'Projecten'` (valt terug op de ruwe naam).

## Gelezen regels

- `docs/regels/verplichtingen-projecten-voorraad.md` (178 regels) — volledig, vóór de start.
- `docs/regels/uren-planning-veldwerkers.md` (353 regels) — volledig, vóór de start.
- `docs/regels/werkloop-productie.md` (55 regels) — volledig (run-brede werkloop).
- `docs/regels/kantoor-frontend.md` (113 regels) — volledig (schermwerk).
