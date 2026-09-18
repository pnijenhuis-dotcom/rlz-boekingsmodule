# Rapport 18-09 — Veld-app 12 UX-verbeteringen, run A (Peter 18-09 "alle punten"): punten 1–3 en 6–12 gebouwd; run B klaargezet

Opdracht: `opdrachten/gedaan/2026-09-18-veldapp-ux-verbeteringen-12-punten.md`. Domeinen: uren-planning-veldwerkers,
accordering-native-app. Migratie 0159 (`administratie.uren_omschrijving_chips`). Gebouwd + getest 18-09-2026 in de inbox-run
(frontend + docs door de coördinator, backend door een bouwagent op een eigen test-DB).

**Werkt in productie: NIET GEMETEN** — meetrecept in `opdrachten/inbox/2026-09-18-veldapp-uitvoerder-nameting.md` (punt 10:
kopie-knop mét `bron=kopie` in het audit-event, tikknoppen, chips-endpoint 200, indienen zonder m² via de samenvatting, chips-rij in
Instellingen, migratie-log `0158 -> 0159`).

## UX-review vóór de bouw (verplicht blok)

Mockup v3 `mockup/uren-uitvoerder-v3.html` (schermen ① kaart, ② daginvoer, ③ indien-samenvatting, ④ terugkoppeling + elf
ontwerpnotities) is vóór de bouw geschreven op basis van v2 (project-eerst) en getoetst aan designpass v2 / KP7: teal = actie
(tikknop "on", primaire knop), groen = status (✓ goedgekeurd), oranje = signaal (vergeten dag, afgekeurd); één primaire knop per
kaart, tekstlinks eronder; lege stand = actie; tikdoelen ≥ 48 px; geen tekst < 14 px in de veld-app. Past in de bestaande IA (zelfde
schermen, geen nieuwe tab); geen mockup-aanpassing van het kantoor nodig behalve één InstellingRij (chips).

## Gebouwd (run A)

| # | Punt | Wat er staat |
|---|---|---|
| 1 | Zelfde als gisteren | tekstlink op de kaart (alleen mét `laatste_regel` én bewerkbare week); kopieert uren, m², omschrijving, doorfactureren van de LAATSTE regel op dat project (ook vorige week) naar de gekozen dag; `PUT /uren/zzp/dag` mét `bron: "kopie"` → audit `weekstaat_dag_gezet.bron=kopie`; toast met wat gekopieerd is |
| 2 | Uren als tikknoppen | 4 · 6 · 8 · 10 + −/+ per half uur (0–24); "ander aantal…" opent pas een numeriek veld |
| 3 | Omschrijving-chips | `GET /uren/zzp/omschrijving-chips?administratie_id=` (default opbouwen · afbreken · ombouwen · transport · overig); "overig"/geen chip = vrij tekstveld; Beheerder beheert per administratie in Instellingen › administratie › Uren & materiaal (`OmschrijvingChipsRij`, `PUT /uren/beheer/omschrijving-chips/{aid}`, 1–10 × ≤ 30 tekens uniek, audit oud→nieuw); opslag = tekst in `weekstaat_dag.opmerking` |
| 6 | Tikdoelen / één primaire knop | `.acc-veld .acc-btn/.acc-plus/.acc-functab { min-height: 48px }`; "+ Uren" primair (bij afgekeurd: "Aanpassen"); "Zelfde als gisteren" + "Meerwerk melden" als `acc-tekstlink` |
| 7 | Leesbaarheid buiten | `.acc-veld`-scope: meta/chips/small/sectielabels/hulptekst/tekstlinks 14 px (guard `uren/veldTekst.test.ts`); contrast-test +1: `--acc-muted` ≥ 4,5:1 op bg en panel in beide modi |
| 8 | Indienen met samenvatting | sheet "Week N indienen?": dagen · uren · projecten · regels zonder m² · niet doorfactureren; ontbrekende werkdag(en) als waarschuwing (niet blokkerend); "Ja, indienen" → per weekstaat `POST /uren/zzp/indienen` |
| 9 | Vergeten dag | werkdag vóór vandaag zonder uren = `.acc-dagknop.vergeten` (oranje rand) + notitie onder de kaarten |
| 10 | Terugkoppeling | kaart: "✓ Goedgekeurd door X — getekende urenstaat" / "Afgekeurd door X: "reden" — tik op Aanpassen…" + primaire knop Aanpassen (opent de weekstaat, die al op corrigeren staat); weekchip "afgekeurd — aanpassen" |
| 11 | Doorfactureren ingeklapt | chip + "standaard voor dit project" (of "standaard: …") + "wijzigen" → dropdown |
| 12 | Velden verbergen | `isM2Project(contract_m2)`: m²-project toont m² direct; anders "▸ meer (m², omschrijving)" |

**Backend (bouwagent, eigen test-DB `boekhouding_test_a6`).** Migratie 0159: `platform.administratie.uren_omschrijving_chips`
JSONB NULL (NULL = default vijf). `service`: `STANDAARD_OMSCHRIJVING_CHIPS`, `omschrijving_chips(administratie)`,
`valideer_omschrijving_chips` (1–10, gestript, ≤ 30 tekens, uniek case-insensitief), `zet_omschrijving_chips` mét audit
`uren_omschrijving_chips_gewijzigd` (oud `{chips, standaard}` → nieuw), `zet_dag(bron)` → `weekstaat_dag_gezet.nieuwe_waarde.bron`.
Routes: `GET /uren/zzp/omschrijving-chips?administratie_id=` (veldrol + scope + opt-in) en `GET|PUT
/uren/beheer/omschrijving-chips/{aid}` (Beheerder-only) → `{"chips": [...], "is_standaard": bool}` (`is_standaard` additief:
handig voor "terug naar standaard"); `PUT /uren/zzp/dag` accepteert `bron: "handmatig" | "kopie"` (anders 422). Kaartvelden:
`laatste_regel` (DISTINCT ON per project over álle weken, alleen de eigen regels), `dagen_zonder_m2`, `contract_m2` (uit de
specs-join, ook in `_planning_stand.vul_projectgegevens`) — één extra statement per administratie, de querytelling-meetlat blijft
constant. Gate-matrix: beide beheer-routes toegevoegd (A2-tellers 6 → 8). Twijfels van de agent, overgenomen als beslispunt: de
beheer-routes eisen de uren-opt-in (409 anders — zelfde patroon als dossier-documenttypen); audit-event op `tabel=administratie`,
`module=boekhouding`; geen CHECK op de JSONB-vorm (validatie in de service, "tekst-lijst, geen enum").

## Tests

| Suite | Uitkomst |
|---|---|
| Frontend `src/uren` (UrenFlow.uxA.test 6 nieuw, veldTekst 2 nieuw, detacheerder-test aangepast, project-eerst-tests) | 22 groen |
| Frontend `OmschrijvingChipsRij.test` 2 + `instellingenRegistry.test` | 19 groen |
| Frontend `styles/contrast.test` (+1 veld-app-hulptekst) | 16 groen |
| Frontend changelog-guard | groen |
| Backend `tests/uren` (incl. nieuw `test_ux_run_a_18_09.py` 17 tests) + `tests/security/test_rol_endpoint_gates.py` + `tests/unit/test_migratie_metadata_guard.py` (eigen DB bouwagent) | 764 groen; `alembic check`: "No new upgrade operations detected" |
| `tsc -b` | groen |
| Volledige frontend-suite | zie `2026-09-18-inbox-afgewerkt.md` |

## Migratie-afsluitroutine (0159)

1. `make migrate` dev-database `boekhouding`: `Running upgrade 0158 -> 0159, Veld-app 12 UX-verbeteringen, run A (akkoord Peter 18-09): omschrijving-chips per administratie.` ✔
2. Live 200 ná de upgrade (eigen uvicorn 8012, token dev-Beheerder): `GET /uren/beheer/omschrijving-chips/3ee6edf0-5cb8-4f98-bba1-16fb97ae6873` → 200 `{"chips":["opbouwen","afbreken","ombouwen","transport","overig"],"is_standaard":true}`; `/health` 200 ✔ (alleen GET's, geen PUT op dev-data)
3. `scripts/dump_schema.sh boekhouding_test_a6` vanuit de repo-root → `schema_referentie.sql` head 0159 mét `uren_omschrijving_chips jsonb`, header teruggezet op `boekhouding_test` ✔

## Beslispunten (gekozen)

1. "Aanpassen" = openen van de al-bewerkbare afgekeurde week (geen extra statusovergang; de afkeur-audit is de bron).
2. Chips: 1–10, ≤ 30 tekens, uniek; "overig" mag ontbreken — de app biedt dan zelf het vrije veld; opslag als tekst (geen enum).
3. Kopie overschrijft een al gevulde gekozen dag — één tik is de bedoeling; de toast zegt wat er staat.
4. Chips worden per administratie één keer per app-sessie opgehaald (cache in de flow); de weekstaat-route gebruikt dezelfde
   daginvoer mét de gecachte chips en zonder contract-m² (m² onder "meer").
5. Run B (dag-einde-herinnering, offline) staat als eigen inbox-opdracht `2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md`
   mét beslispunten vooraf (herinneringstijd 16:30, opt-out per gebruiker).

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (300 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/accordering-native-app.md` (264 regels) — volledig, vóór de start (Domeinen-kopregel).
