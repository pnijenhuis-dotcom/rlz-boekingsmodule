# Rapport 18-09 — Planning personeel v3 "dag-eerst" (mockup AKKOORD Peter 18-09 = bouwnorm) — backend + frontend

Opdracht: `opdrachten/gedaan/2026-09-18-planning-v3-dag-eerst-bouw.md`. Domeinen: uren-planning-veldwerkers, kantoor-frontend,
werkloop-productie. Migratie **0161** (`planning_reservering` + `veldwerker_afwezigheid`). Gebouwd door twee bouwagenten (4B backend,
4F frontend) op één bindend contract (`CONTRACT_4.md`, 10 geregistreerde afwijkingen — alle door 4F verwerkt); samengevoegd door de
coördinator.

**Werkt in productie: NIET GEMETEN** — deploy volgt via de Stop-hook ná deze run. De meetrecepten (Universal week 39) staan per deel
hieronder. **Één regel voor Peter:** de Personeel-tab is morgen per dág: sleep een project uit de balk naar een dag, klik de kaart en
kies de ploeg rechts, pak het bolletje en trek de kaart over de week; "Per project" is de leesweergave van dezelfde week.

## Coördinator — migratie-routine en live-200 (dev)

| Stap | Uitkomst |
|---|---|
| `make migrate` (dev `boekhouding`) | `Running upgrade 0159 -> 0160`, `0160 -> 0161`, `0161 -> 0162`; `alembic check`: "No new upgrade operations detected" |
| Live 200 (uvicorn 8011, Beheerder-token) | `GET /uren/kantoor/planning?administratie_id&jaar=2026&weeknummer=39` → 200 mét `reserveringen`/`afwezigheid`; `GET /uren/kantoor/afwezigheid` → 200 `[]`; `POST /uren/kantoor/planning/bulk` mét lege lijst → 422 (limiet-poort, route bereikbaar) |
| Schema-dump | ververst ná de volledige suite (`scripts/dump_schema.sh`, zie eindsamenvatting) |
| Contractafwijkingen 4B → 4F | dagdeel `heel|half`; `?administratie_id=` als query-param op élke POST; `aangemaakt` bevat ook conflict-items; `beeindigd_op` op AfwezigheidDto — alle verwerkt |

---

# DEEL A — Rapport blok 4B — Planning personeel v3 "dag-eerst": BACKEND (migratie 0161, bulkroute, reservering, afwezigheid)

Opdracht: `opdrachten/lopend/2026-09-18-planning-v3-dag-eerst-bouw.md` slices 1 (leesroute), 2+3 (bulkroute), 5 (afwezigheid), 6 (guards).
Contract: `CONTRACT_4.md`; afwijkingen in `contract_afwijkingen_4.md` (10 punten — belangrijkste: dagdeel = heel|half, POST-routes
vereisen `?administratie_id=` als query-param, `aangemaakt` bevat ook conflict-items). Eigen test-DB `boekhouding_test_a4`.

**Werkt in productie: NIET GEMETEN** (deploy volgt; coördinator doet `make migrate` dev + live-200 + dump). Meetrecept ná deploy
(Universal week 39): `POST /uren/kantoor/planning/bulk?administratie_id=…` mét 2 personen × di–vr → 200, `resultaten[*].uitkomst`
gedaan; dezelfde set nogmaals → alles `overgeslagen`; `GET /uren/kantoor/planning` draagt `reserveringen`/`afwezigheid`/
`pool[].afwezig_tot`; audit_event `planning_bulk` + `planning_gepland` mét `bulk_correlatie_id` (lees-only replica).

## Feiten vooraf (code gelezen)
| Vraag | Bevinding |
|---|---|
| Bestaande helpers | `plan_toewijzing`/`verwijder_toewijzing` openen elk hun EIGEN `scoped_session` → niet herbruikbaar binnen één transactie. Gerefactord naar `_plan_in_sessie`/`_verwijder_in_sessie` (sessie als parameter); de losse routes wikkelen die nu. Gedrag van de losse routes ongewijzigd (35 bestaande planning-tests groen). |
| Dagdeel | `PlanningDagdeel` = `heel`/`half` (contract zei ochtend/middag → afwijking 1). |
| Scope-poort | `vereis_administratie_scope` leest `administratie_id` als QUERY-parameter — óók op POST (bestaand patroon verwijderen/verplaatsen/dagdeel) → afwijking 10. |
| Afwezigheid in datamodel | bestond niet (grep leeg) — nieuw `veldwerker_afwezigheid`. |
| RLS-patroon | 0060/0145: `ENABLE + FORCE ROW LEVEL SECURITY`, policy op `platform.current_administratie_id()`, grants aan `boekhouding_app`. |

## Gebouwd
- **Migratie 0161** `planning_reservering` (id, administratie_id, project_id [FK samengesteld naar project_cache], datum,
  aangemaakt_door/op; UNIQUE administratie×project×datum; RLS FORCE; grants SELECT/INSERT/UPDATE/DELETE) en `veldwerker_afwezigheid`
  (id, administratie_id, gebruiker_id, van, tot [CHECK tot ≥ van], reden, aangemaakt_door/op, beeindigd_op; RLS FORCE; grants
  SELECT/INSERT/UPDATE — géén DELETE). Modellen in `app/uren/models.py`.
- **`planning.plan_bulk`** (`POST /uren/kantoor/planning/bulk`): één transactie; per item `gedaan | overgeslagen | conflict`; conflict
  (`project` = die dag al elders gepland, mét projectnaam; `afwezig` = binnen een afwezigheidsperiode) wordt WÉL gepland en
  gemarkeerd (kantoor beslist, nooit blokkerend); idempotent (bestaande identieke toewijzing = overgeslagen; dubbel in dezelfde
  aanroep = overgeslagen); `verwijderen=true` = exact de opgegeven items weg (ongedaan maken; onbestaand = overgeslagen); échte fout
  (onbekend/inactief project, niet-planbare persoon, geen opt-in, geen recht) → hele transactie terug (UrenFout → 4xx); limiet 200
  (service 422 + pydantic `max_length=200`); bronnen `vulhandvat|ploeg|ongedaan`. Audit: per (persoon, dag) de bestaande acties
  `planning_gepland`/`planning_verwijderd` mét `bulk_correlatie_id`, `bron` (+ `conflict`), plus één samenvattende rij `planning_bulk`
  (tellers). Melding-rij per veldwerker × week (15-09) en `achteraf`-vlag blijven via de gedeelde helper. Set-based: bestaande
  toewijzingen in één query, afwezigheid in één query, projecten/personen één keer per uniek id, projectkoppeling één keer per
  (persoon, project) — SELECT-aantal is onafhankelijk van het aantal items (test).
- **Reservering**: `POST /uren/kantoor/planning/reservering` (201 nieuw / 200 bestaand, idempotent; alleen actieve projecten),
  `POST …/reservering/verwijderen` (204, idempotent); audit `planning_gereserveerd`/`planning_reservering_verwijderd`. De rij blijft
  staan als er een persoon op de kaart komt (drager; frontend ontdubbelt op project×datum).
- **Afwezigheid**: `GET /uren/kantoor/afwezigheid?administratie_id&gebruiker_id?`, `POST …/afwezigheid` (201; overlap → 409
  leesbaar; alleen ZZP'er/uitvoerder), `POST …/afwezigheid/beeindigen` (200; alleen vervroegen, ≥ van; `beeindigd_op` gezet; audit
  oud→nieuw). Nooit DELETE. Recht: module-recht 'Meerwerk & urenstaten' ÓF 'veldwerkerbeheer' (`require_veldwerkerbeheer_of_meerwerk_recht`
  + servicespiegel `_vereis_afwezigheid_recht`) + scope.
- **Leesroute** `GET /uren/kantoor/planning` additief: `reserveringen[]` (deze week, mét projectnaam), `afwezigheid[]` (alle rijen die
  de week overlappen), `pool[].afwezig_tot` (laatste `tot` van overlappende afwezigheid). Twee extra statements, constant.
- **Gate-sweep** `tests/security/test_rol_endpoint_gates.py`: zes nieuwe endpoints in de kantoor-lijst (veldrollen 403, fail-closed).

## Tests (eigen DB `boekhouding_test_a4`)
| Aanroep | Uitkomst |
|---|---|
| `pytest tests/uren/test_planning_v3_18_09.py` (nieuw) | 13 groen: vulhandvat 2×4 gedaan + audit correlatie/bron + idempotent; ongedaan = exact de set; conflict project/afwezig WEL gepland + gemarkeerd (+ audit `conflict`); echte fout rolt alles terug; limiet/bron/dubbel; SELECT-aantal 1 item == 4 items; reservering idempotent+audit+leesroute+inactief weigert; afwezigheid toevoegen/overlap 409/beëindigen (vervroegen, verlengen weigert)/pool.afwezig_tot/dag weer planbaar; recht meerwerk-óf-veldwerkerbeheer + alleen planbare personen; API bulk/ongedaan/422/reservering 201→200/lijst/afwezigheid 201/409/beëindigen; rolpoort (veldrol, zonder recht, zonder scope) 403 + niets geschreven; RLS: FORCE op beide tabellen, geen DELETE-grant afwezigheid, andere scope ziet 0 rijen |
| `pytest tests/uren/test_planning.py tests/uren/test_planning_urenstatus.py tests/uren/test_planning_filters.py tests/uren/test_planning_signaal.py tests/uren/test_werkopdracht.py tests/security/test_rol_endpoint_gates.py tests/unit/test_migratie_metadata_guard.py tests/unit/test_optin_afwezig_pad_guard.py tests/uren/test_planning_v3_18_09.py` | 573 groen (3 min 29) — bestaand planning-gedrag ongewijzigd, model ↔ migratie in de pas, gate-sweep incl. nieuwe routes |
| `ruff check` op de geraakte bestanden | schoon voor mijn regels (models.py r. 1055 = bestaande E501 uit HEAD; gate-test 11 bestaande E501 uit HEAD) |

## Beslispunten (gekozen)
1. **Conflict = wél plannen + markeren** (mockup-notitie "afwezig/dubbel = oranje, nooit blokkerend"); het item telt in `aangemaakt`
   zodat "Ongedaan maken" het ook weghaalt.
2. **Reservering blijft staan als drager** zodra er een persoon op de kaart komt — één kaart per project × dag wordt door de frontend
   afgeleid (ontdubbelen op project_id+datum); verwijderen is altijd expliciet + geaudit.
3. **Afwezigheid alleen voor planbare personen** (ZZP'er/uitvoerder); verlengen = nieuwe periode (beëindigen kan alleen vervroegen).
4. **Bulk-idempotentie binnen de set**: een dubbel item in dezelfde aanroep = overgeslagen (geen 422).
5. **Geen nieuwe `dag_totalen`** op de leesroute (opdracht: client-side som is goedkoop).

## Gedeelde bestanden
`app/uren/router.py`, `schemas.py`, `models.py` worden óók door blok 5B (herinnering) additief bewerkt — beide sets bestaan naast elkaar
(import-check groen, herinnering-routes aanwezig). `tests/security/test_rol_endpoint_gates.py`: alleen zes regels toegevoegd.

## Klikpunten Peter
- Ná deploy in Universal week 39: kaart selecteren → handvat ma→vr → toast "… 4 kopieën" → "Ongedaan maken" haalt precies die weg.
- Beheer › Veldwerkers › dossier › "Afwezig" toevoegen → de pool toont "afwezig t/m …", plannen op zo'n dag kleurt oranje (niet geblokkeerd).

---

# DEEL B — Rapport 18-09 — Planning personeel v3 "dag-eerst" — FRONTEND (blok 4F)

Opdracht: `opdrachten/lopend/2026-09-18-planning-v3-dag-eerst-bouw.md` (mockup `mockup/planning-v3-dag-eerst.html` AKKOORD Peter 18-09
= bouwnorm incl. notities + beslispunten). Contract: `CONTRACT_4.md`; backend = blok 4B (eigen rapport). Domeinen: uren-planning-veldwerkers,
kantoor-frontend. Migratie 0161 = 4B.

**Werkt in productie: NIET GEMETEN** — deploy volgt ná de run. Meetrecept ná deploy (Universal week 39): (1) projecttegel naar een dag
slepen → grijze kaart "gereserveerd" (request-log `POST /uren/kantoor/planning/reservering` 201); (2) kaart mét ploeg selecteren →
handvat ma→vr slepen → 4 kopieën + toast "Gekopieerd naar di–vr · N persoon-dagen" (`POST /uren/kantoor/planning/bulk` 200, bron
`vulhandvat`) → Ongedaan maken → dezelfde route mét `verwijderen: true`; (3) klik kaart → paneel rechts → vinkje → Opslaan (N) →
één bulk-call, kaart toont de nieuwe initialen; (4) toggle "Per project" toont dezelfde aantallen per cel als de kaarten; (5) Beheer ›
Veldwerkers › dossier → "Afwezig" toevoegen → in de planning: pool "afwezig t/m …", paneel uitgeschakeld, conflictenbalk bij plannen.
Screenshots van de kliktest graag terug in het rapport van de nameting.

## Feiten vooraf (code gelezen)

| Vraag | Bevinding |
|---|---|
| Datalaag | `GET /uren/kantoor/planning` leverde al álle actieve projecten mét `per_datum` per rij — de weergave draait, geen tweede leesroute. Additief (4B): `reserveringen`, `afwezigheid`, `pool[].afwezig_tot`. |
| Drag-mechaniek | Transport-tab had de payload-vorm `t:`/`bak:` + dragOver-state inline; geëxtraheerd naar `planning/useDagDrop.ts` (één implementatie), Transport-gedrag ongewijzigd (5 tests groen). |
| Sticky dagkop | de fix van vandaag (`.tabel-scroll.sticky-koppen.plan-scroll`) hergebruikt op het dag-eerst-grid én de per-project-tabel; guard `stickyDagkop.test.ts` verbreed naar drie grids. |
| "Starttijd" | bestaat niet als veld; de kaart en het paneel tonen de geldende werkopdracht-tekst (dag-override wint), "wijzigen" = de bestaande dag-override-dialoog. |
| Afwezigheid | bestond niet in het datamodel; 4B levert tabel + routes; de UI zit in het dossier-dialoog (`gebruikers/DossierModal.tsx`, één regel — gedeeld bestand). |
| Playwright | niet in de repo → gedrag met vitest (pointer-events voor het handvat, drag via payload), visueel via het nieuwe planning-harnas + overflow-sweep + screenshots. |

## Gebouwd (bestanden)

- **Puur:** `frontend/src/planning/dagEerst.ts` (rij-grid → dagkolommen, dagtotalen, `laagsteStatus`, `conflictenVoorWeek`/`conflictenUniek`,
  `beschikbaarheid`, `poolStand`/`afwezigTot`, `vulhandvatVoorbeeld`/`handvatBereik`, `projectTegels`, `perProjectRijen`, `werkopdrachtOpDag`,
  `parseKaartParam`, `initialen`), `planning/planBulkOngedaan.ts` (toast-tekst, ongedaan-stand, Cmd/Ctrl-Z-toets), `planning/useDagDrop.ts`.
- **Componenten:** `DagEerstGrid.tsx` (grid, kaarten, drop, handvat, ghosts, weekend-toggle), `ProjectBalk.tsx`, `ConflictenBalk.tsx`,
  `PloegPaneel.tsx`, `PerProjectWeergave.tsx`, `veldwerkers/AfwezigKaart.tsx`; `PlanningScreen.tsx` herschreven (grid-deel), pool uitgebreid
  (vrij/afwezig, filter "alleen vrij", 100 + "… N meer"), toggle Per dag/Per project (localStorage), toast + ongedaan, deeplink `?kaart=`.
- **API:** `planningApi.ts` additief — `PlanningReserveringDto`, `AfwezigheidDto`, bulk-types, `planBulk`, `maakReservering`,
  `verwijderReservering`, `haalAfwezigheidOp`, `voegAfwezigheidToe`, `beeindigAfwezigheid`; `PlanningWeekDto.reserveringen/afwezigheid`,
  `pool[].afwezig_tot`, optioneel `pool[].dossier_onvolledig`.
- **CSS:** `styles/components.css` blok "Planning v3" (`plan-kaart`, `plan-av`, `plan-pbalk`, `plan-conf`, `plan-handvat`, `plan-toggle`,
  `plan-paneel`, `plan-toast`, …) — uitsluitend bestaande tokens (contrast-test groen).
- **Harnas + sweep:** `harness-planning.html` + `src/dev/visueelHarnasPlanning.tsx` (83 projecten, 12 veldwerkers, reservering, afwezigheid,
  dubbel, > 5 op één kaart; varianten `?perproject=1`, `?kaart=1`, `?tab=transport`, `?donker=1`); opgenomen in `scripts/overflow_sweep.sh`.
- **Mockups:** v3-kop → "AKKOORD Peter 18-09 · BOUWNORM"; `planning-steigerbouw.html` → titel + banner "VERVANGEN door planning-v3-dag-eerst.html (18-09)".

## Contract-afwijkingen 4B (verwerkt)

1. `dagdeel` = `heel | half` (bestaande enum) → types + items aangepast. 2. `AfwezigheidDto.beeindigd_op` additief → opgenomen.
3. `aangemaakt` bevat gedaan ÉN conflict-items → de client stuurt exact die set terug bij ongedaan (zo gebouwd). 4–9 geen frontend-impact
(server-gedrag); 10 (scope als QUERY-param op élke POST) → alle nieuwe calls dragen `?administratie_id=` (getest).

## Tests

| Toets | Uitkomst |
|---|---|
| `vitest run src/planning/dagEerst.test.ts` (nieuw) | 12 groen: laagste status, rij-grid → dagkolommen + dagtotalen + reservering, kaartfilter, conflicten (dubbel/afwezig/dossier/> 5), beschikbaarheid + poolstand, vulhandvat (overslaan, conflict-voorspelling, weekgrens), projectbalk-sortering + diakrieten, per-project-rijen, deeplink, toast-tekst/ongedaan-stand/Cmd-Z |
| `vitest run src/planning/PlanningScreen.test.tsx` (herschreven) | 20 groen: dagkoppen + kaart + projectbalk + signalen; week-URL; klik-alternatief tegel → dag = reservering (scope-query); gereserveerde kaart; zoeken/lege uitkomst; 68 projecten = één request + "+ 56"; ploeg-paneel → één bulk-call + toast + Ongedaan maken (verwijderen:true, correlatie-id, exacte set); bevestiging bij verwijderen mét uren (nee = geen POST); vulhandvat di–wo (ghosts, 4 items, toast); overslaan + stopt bij vrijdag; conflictenbalk → spring + paneel; afwezigheid (pool, filter, paneel uitgeschakeld, conflict); verwijderen; dagdeel; ná einddatum; 403; 409; werkopdracht → dag-override-dialoog; Per project (rij, cellen, weekstaten-link, klik → Per dag, localStorage); deeplink `?kaart=`; urenstatus kaartniveau + tooltip + achteraf; filter zonder uren = kaartfilter |
| `vitest run src/veldwerkers/AfwezigKaart.test.tsx` (nieuw) | 2 groen: lijst/toevoegen/beëindigen (geen DELETE), 403 = geen kaartje |
| `stickyDagkop.test.ts`, `TransportTab.test.tsx`, `src/styles` (contrast), `src/gebruikers`, `src/veldwerkers`, `proxyDekking` | 262 tests / 24 bestanden groen (`vitest run src/planning src/veldwerkers src/styles src/gebruikers src/api/proxyDekking.test.ts`) |
| `tsc -b` | groen voor mijn bestanden (één fout in `src/uren/urenOffline.ts` van blok 5F op het moment van meten — niet van 4F) |
| `POORT=5202 HARNASSEN_ALLEEN=harness-planning scripts/overflow_sweep.sh` | 24/24 ✅ (3 varianten × licht/donker × 1440/1170/1024/768), geen pagina-overflow; de projectbalk scrolt intern |
| Screenshots | `<scratchpad>/screens_4F/*.png` (24) — o.a. `harness-planning.html_licht_1440px.png` (grid + balk + conflicten + pool), `…_kaart_1_licht_1440px.png` (kaart geselecteerd, handvat, ploeg-paneel mét beschikbaarheid), `…_perproject_1_licht_1440px.png` |

**Kliktest (in het harnas, visueel gecontroleerd):** dagkoppen mét totaal; Arnhem ma–wo 4 man, Rijssen wo 6 man = conflict ×4 (> 5, Sanli
dubbel, Onel dossier, Genc afwezig) mét oranje initialen; Breda do = "gereserveerd · nog geen ploeg"; conflictenbalk "5 conflicten deze week"
+ "+ 2 meer"; pool: Yücetaş/Genc "afwezig t/m …", Sanli 6 dg oranje; `?kaart=1`: kaart geselecteerd (teal rand, handvat rechts, per-persoon
½/✕), paneel "4 gekozen · beschikbaarheid voor ma 14-9" mét vrij/al op ‹project›/afwezig (uitgeschakeld), "Zelfde ploeg als vorige
werkdag" terecht uitgeschakeld (ma = eerste dag), Opslaan (4) uitgeschakeld zonder diff.

## Beslispunten (gekozen) en open punten

- Paneel in de zijkolom boven de pool (geen vaste overlay) · reserveringsrij blijft drager, UI ontdubbelt · persoon op lege dagruimte =
  niets (hint) · `?uren=` = kaartfilter · "starttijd" = werkopdracht-tekst + dag-override.
- **Open 1:** `pool[].dossier_onvolledig` (conflict "ZZP'er zonder dossier") is frontend-klaar maar wordt door 4B nog niet geleverd —
  additief verzoek aan de backend; tot dan geen dossier-conflict in de balk.
- **Open 2:** werkopdracht toevoegen voor een project ZONDER kaart deze week (de oude ⊕ per projectrij) loopt nu via Werkopdrachten-tab
  of het paneel ná plannen — bewust, gemeld.
- **Open 3:** het vulhandvat is pointer-based (muis/trackpad getest in vitest); op touch is `touch-action: none` gezet maar niet op een
  toestel getoetst. Playwright ontbreekt (eerlijk gemeld).
- Herschreven tests: `PlanningScreen.test.tsx` volledig — de oude selectors (`cel-…`, "Overige actieve projecten", "deze week: N man")
  bestaan niet meer; dekking per gedrag is behouden (zie tabel).

## Gedeelde bestanden (buiten de 4F-grenzen, additief)

`frontend/src/gebruikers/DossierModal.tsx` (import + één render-regel `AfwezigKaart`), `frontend/src/planning/TransportTab.tsx` (alleen
hook-extractie), `frontend/src/styles/components.css` (nieuw blok onderaan het planning-deel), `frontend/scripts/overflow_sweep.sh`
(harnas toegevoegd), `mockup/planning-steigerbouw.html` (kop/banner).

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (353 regels) — volledig (geërfd van de coördinator + opdracht).
- `docs/regels/kantoor-frontend.md` (113 regels), `docs/regels/werkloop-productie.md` (55 regels) — volledig.
- `docs/regels/uren-planning-veldwerkers.md` (353 regels) — volledig (geërfd van de coördinator).
- `docs/regels/kantoor-frontend.md` (113 regels) — volledig.
- `docs/regels/werkloop-productie.md` (55 regels) — volledig.
