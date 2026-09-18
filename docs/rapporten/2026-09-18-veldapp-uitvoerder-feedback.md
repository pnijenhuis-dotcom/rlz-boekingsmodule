# Rapport 18-09 — Veld-app uitvoerder: feedback Peter 18-09 (m² optioneel, doorfactureren per regel, alle projecten, planning weg)

Opdracht: `opdrachten/gedaan/2026-09-18-veldapp-uitvoerder-feedback-m2-doorfactureren-projecten.md`. Domeinen:
uren-planning-veldwerkers, accordering-native-app. Migratie 0158. Gebouwd + getest 18-09-2026; Peter keek niet mee — keuzes
staan hieronder onder "Beslispunten".

**Werkt in productie: NIET GEMETEN** — de code staat op main ná deze commit; de deploy loopt via de Stop-hook-push. Het
meetrecept (weekstaat indienen zonder m² op het testaccount = 200) staat klaar als vervolg-opdracht
`opdrachten/inbox/2026-09-18-veldapp-uitvoerder-nameting.md` (stap 0 = deploy-check service én jobs). Lokaal ná `make migrate`:
`GET /uren/zzp/week-projecten`, `GET /uren/uitvoerder/projecten` en `GET /uren/zzp/weekstaat` geven **200** voor een
uitvoerder-account (dev-database, 61 actieve projecten in de lijst, `doorfactureren_standaard` in de lookup).

## Feiten vooraf — letterlijk bewezen in de code (opdracht: "bewijs dat eerst")

| Vraag | Bevinding |
|---|---|
| Waar zit de m²-verplichting? | **Nergens.** `WeekstaatDag.m2` is nullable (`Numeric(8,2)`, `ck_weekstaat_dag_m2: m2 IS NULL OR m2 >= 0`), `service.zet_dag(m2: Decimal \| None = None)` valideert alleen `m2 < 0`, `DagZettenRequest.m2: Decimal \| None = None`; in de app stond het veld al als "m² gebouwd (optioneel)" en de Opslaan-knop toetst alleen `uren`. Wél: placeholder "0" op het veld en de dagchip toonde "8,0 u · —" bij leeg. |
| Waar staat "+ ander project"? | Als aparte `acc-btn secundair`-knop ónder de weekprojectenlijst (`WeekProjectenView` → scherm `anderProject` → `AnderProjectView` met zoekveld → `GET /uren/zzp/projecten-keuze`). De uitvoerder kon die knop nooit bereiken (zie volgende rij). |
| Kernoorzaak achter punt 1 + 3 | **De rol uitvoerder had géén weekstaat-pad.** App-tabs uitvoerder = Projecten · Planning · Te keuren; de backend weigerde hard: `_vereis_invuller` → "Weekstaten horen bij een gebruiker met de rol ZZP'er" en `_vereis_namens_of_zelf` → "Alleen een ZZP'er heeft eigen weekstaten". Het enige hoeveelheidsveld dat de uitvoerder tegenkwam was **meerwerk "Aantal" (eenheid default m², verplicht > 0)** — vermoedelijk dát is de "verplichte m²" uit de feedback. |
| Projectenlijst uitvoerder | Alleen projecten met een rij in `uren_project_toewijzing` (`overzichten.uitvoerder_projecten`); projectdetail en meerwerk melden eisten die koppeling ook. |
| Planning-grid en m² | `planningApi.ts::urenKort` toonde bij `m2` null/0 al alleen uren — geen wijziging nodig. |

## Gebouwd

**Blok A — m² optioneel.** `urenLabel` toont zonder m² alleen uren ("8,0 u", geen "· —"/"· 0 m²"); m²-veld placeholder
"leeg = niet ingevuld", leeg blijft `null` (nooit 0); `totaal_m2` telt alleen ingevulde regels (was al zo). Guard-test
`tests/uren/test_uitvoerder_feedback_18_09.py::TestM2Optioneel` — dag zetten zonder m² = 200, indienen = 200, `m2` null.

**Blok B — Doorfactureren per regel (migratie 0158).** Kolom `weekstaat_dag.doorfactureren boolean NOT NULL DEFAULT true`
(bestaande regels = true, het oude gedrag). Default voor een NIEUWE regel = `service.standaard_doorfactureren`: project mét ≥ 1
verrekenbare staffel (`project_staffel.verrekenbaar`, contract-ontleding) → Doorfactureren, anders Niet — zichtbaar als
"standaard voor dit project: …" naast de dropdown; mens wint (expliciete waarde in de PUT), bijwerken zonder keuze houdt de
bestaande stand; audit `weekstaat_dag_gezet` draagt `doorfactureren` oud→nieuw. DTO's: `DagDto.doorfactureren`,
`WeekstaatDto.doorfactureren_standaard/totaal_uren_niet_doorfactureren/totaal_m2_niet_doorfactureren/dagen_buiten_planning`,
`WeekstaatZoekDto.doorfactureren_standaard` (ook zonder staat). Zichtbaar in: dag-invoer (dropdown), weekstaat (chip "niet
doorfactureren" + balk "waarvan niet doorfactureren"), keuring in de app (chip + balk) en een NIEUW kantoor-weekstaatpaneel
`frontend/src/meerwerk/WeekstaatPaneel.tsx` op `/meerwerk?administratie=…&weekstaat=<id>` — de link die het planning-grid sinds
15-09 al legde maar die nergens landde — mét filter "alleen niet doorfactureren", kolommen Doorfactureren/Planning en "Door te
belasten = totaal − niet doorfactureren". De **factuurmatch (ZZP-inkoopkant) telt onverkort álle uren**: de ZZP'er krijgt betaald
ongeacht de keuze; alleen de klant-kant splitst.

**Blok C — Alle projecten, gepland bovenaan; uitvoerder schrijft eigen uren.** `overzichten.week_projecten_zzp` levert ÁLLE
actieve projecten van de administraties mét opt-in in de scope (set-based: één `ProjectCache ⟕ ProjectSpecificatie`-query per
administratie, gemerged met de bestaande planning/staten-stand); sortering te doen → gepland → mét staat → naam. De app toont
"Gepland deze week" (chip "gepland") en "Andere projecten" (chip "niet gepland"), één zoekveld over beide; `AnderProjectView` en
het scherm `anderProject` zijn verwijderd (`GET /uren/zzp/projecten-keuze` blijft bestaan, ongebruikt). Een dag op een niet-gepland
project krijgt in de weekstaat de chip "niet gepland" en telt via `buiten_planning`/`dagen_buiten_planning` in de keuring, het
kantoor-paneel en het bestaande planning-signaal "buiten planning" — geen blokkade. **Uitvoerder = invuller:** `INVULLER_ROLLEN`
= ZZP'er + uitvoerder (alleen voor zichzelf; een detacheerder werkt nooit namens een uitvoerder), tab "⏱ Mijn uren" mét exact de
ZZP-flow (weken → projecten → weekstaat → dag → indienen → Ingediend). **Vier-ogen:** `_vereis_keurrecht(staat_gebruiker_id)`
weigert de eigen staat, `te_keuren` en de projecttellers laten eigen staten weg; een andere uitvoerder op het project keurt (test).
Uitvoerder-projectenlijst = alle actieve projecten (gekoppeld bovenaan, kop "Andere projecten"), projectdetail en meerwerk melden
op élk actief project in scope (niet-actief zonder koppeling = GeenToegang) — de koppeltabel is een filter, geen poort meer.

**Blok D — Planning uit de uitvoerder-app.** Allowlist `frontend/src/auth/rollen.ts::PLANNING_TAB_ROLLEN = ['zzper',
'detacheerder']` + `toontPlanningTab` (fail-closed, test); de uitvoerder-tabs zijn Projecten · Mijn uren · Te keuren; deep-link
`?planning=` landt voor hem op Mijn uren. Backend-leesroute `/uren/zzp/planning` blijft (bron "gepland bovenaan"); meldingen
"planning gewijzigd" blijven. Kantoor-web ongewijzigd behalve het nieuwe paneel.

**Docs/mockup:** `mockup/uren-uitvoerder.html` (tabs, weekprojectenlijst met beide secties, dropdown, "+ ander project"-view
vervallen), `docs/regels/uren-planning-veldwerkers.md` (nieuwe alinea), BESLISSINGEN "VELD-APP UITVOERDER — FEEDBACK 18-09",
CLAUDE.md één verwijsregel (50.771 tekens), `WAT_IS_NIEUW.md` 2026-09-18.

## Beslispunten (Peter keek niet mee — gekozen en vastgelegd)

1. **Doorfactureren op regelniveau** (dag × project), niet op de hele weekstaat — conform de default in de opdracht.
2. **Default zonder staffel = Niet doorfactureren** (letterlijk "anders Niet"). Let op: de meeste projecten hebben (nog) geen
   verrekenbare staffel → de dropdown staat daar standaard op "Niet doorfactureren". Wil Peter "Doorfactureren" als default voor
   vaste-aanneemsom-projecten, dan is dat één regel in `standaard_doorfactureren`.
3. **Meldingen "planning gewijzigd" blijven** voor de uitvoerder (default van de opdracht).
4. **Meerwerk "Aantal" bewust ongewijzigd** (verplicht > 0): het is de meerwerkhoeveelheid voor de prijsstelling, niet de
   weekstaat-m²; met "Mijn uren" hoeft de uitvoerder er niet meer langs om uren/m² te schrijven.
5. **Uitvoerder keurt nooit zijn eigen staat.** Gevolg: zonder tweede uitvoerder op het project blijft zijn staat op `ingediend`.
   Voorstel (niet gebouwd): kantoor-keuring onder het module-recht "Meerwerk & urenstaten" als vangnet — besluit Peter.
6. **Projectdetail + meerwerk voor élk actief project** in de scope van de uitvoerder (specs mét prijzen waren al zichtbaar voor
   gekoppelde projecten; Peter vroeg letterlijk "alle projecten zien"). Scope + opt-in + RLS ongewijzigd.

## Tests

| Suite | Uitkomst |
|---|---|
| `backend/tests/uren` (incl. nieuwe `test_uitvoerder_feedback_18_09.py`, 13 tests) | 254 groen |
| Volledige backend-suite (`pytest tests --ignore=tests/integration`, gedraaid in de inbox-run 18-09 10:07–11:33) | 6487 groen, 1 skipped (1 u 26 min) |
| Frontend `vitest run` (volledig) | 211 bestanden / 1707 tests groen (incl. `rollen.planningtab.test.ts`, `urenLabel.test.ts`, herschreven `UrenFlow.detacheerder.test.tsx`) |
| `tsc -b` | groen |
| Guards | `test_claude_md_beslissingen_verwijzingen`, `test_regels_index`, `test_migratie_metadata_guard`, `alembic check` ("No new upgrade operations detected"), changelog-vorm: groen |

Aangepaste bestaande tests (gedragswijziging 18-09, geen regressie): `test_planning_filters.py` (weekprojectenlijst bevat nu álle
actieve projecten; API-test verwacht twee kaarten), `test_meerwerk_statusmachine.py::test_alleen_uitvoerder_op_actief_project`
(was: alleen gekoppelde uitvoerder).

## Migratie-afsluitroutine

1. `make migrate` dev-database: `Running upgrade 0157 -> 0158, Veld-app uitvoerder — feedback 18-09 blok B …` ✔
2. Live 200 ná de upgrade op poort 8000 (eigen uvicorn, dev-DB, token voor het lokale uitvoerder-testaccount "peter's test 2" —
   daarvoor lokaal status `uitgenodigd → actief` + voorwaarden-akkoord gezet): `/health` 200, `/uren/zzp/week-projecten` 200
   (61 projecten, 0 gepland), `/uren/uitvoerder/projecten` 200, `/uren/zzp/weekstaat` 200 → `{"weekstaat":null,
   "doorfactureren_standaard":false}` ✔
3. `scripts/dump_schema.sh` vanuit de repo-root: `schema_referentie.sql ververst vanaf boekhouding_test (head 0158)`, kolom
   `doorfactureren boolean DEFAULT true NOT NULL` in de dump ✔

## Open punten / vervolg

- Nameting ná deploy (inbox-opdracht): weekstaat indienen zonder m² op het testaccount = 200; "Mijn uren"-tab zichtbaar voor de
  uitvoerder, planningstab weg; kantoor-paneel opent vanuit het grid.
- Beslispunt 5 (keuring van uitvoerder-staten zonder tweede uitvoerder) en beslispunt 2 (default zonder staffel) bij Peter.
- Bestaande ruff-format-drift in `app/uren/models.py`, `overzichten.py`, `router.py` en I001/F401 in
  `test_meerwerk_statusmachine.py` dateren van vóór deze run en zijn bewust niet meegeformatteerd (memory: geen hele mappen
  formatten).

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (247 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/accordering-native-app.md` (264 regels) — volledig, vóór de start (Domeinen-kopregel).
