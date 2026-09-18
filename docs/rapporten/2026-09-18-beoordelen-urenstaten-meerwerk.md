# Rapport 18-09 — BUG chip "14 meerwerk/urenstaten te beoordelen" → lege Meerwerk-pagina: Beoordelen op één plek; uitvoerder keurt alles in scope

Opdracht: `opdrachten/gedaan/2026-09-18-BUG-chip-meerwerk-urenstaten-lege-pagina.md`. Domeinen: uren-planning-veldwerkers,
werkvoorraad-controlescherm, kantoor-frontend. Geen migratie. Gebouwd + getest 18-09-2026 in de inbox-run.

**Werkt in productie: NIET GEMETEN** — meetrecept in de inbox-opdracht `2026-09-18-veldapp-uitvoerder-nameting.md` (punt 9): op
Universal Steigerbouw chip-aantal == som tab-aantallen (verwacht 14 urenstaten · 0 meerwerk zolang niemand keurt), en Irfan
(uitvoerder) ziet in zijn app de ingediende weekstaten van anderen zonder projectkoppeling.

## Databewijs (lees-only, replica `rlz-sql2-lees`, 18-09 ~11:30, `scripts/gcp/db_lezen.sh` als nameting@, actor Beheerder `2f2262cd…`)

| Toets | Uitkomst |
|---|---|
| Administratie | `platform.administratie` naam ILIKE '%universal%' → Universal Steigerbouw B.V. = `3ee6edf0-5cb8-4f98-bba1-16fb97ae6873` (actief, uren-opt-in aan) |
| Weekstaten `ingediend` | **14** — allemaal week 2026-W37, `ingediend_op` 2026-09-15: H. Ucan 1 (26021 Tilburg), M. Sanli 4 (26030 Scherpenzeel, 26019 Bennekom, 26021 Tilburg, 26129 Hilversum), R. Yücetaş 4 (idem), V. Ponchev 1 (25162 Groesbeek), S. Hasturk 4 (idem); id's o.a. `a5ce8ef1…`, `fd9e12df…`, `d61b328e…`, `9f55c3fd…`, `dd551784…`, `7bb620f2…`, `d5a9e34e…`, `7b606ec5…`, `768f0e4e…`, `ae56d615…`, `5dd6995a…`, `edd83606…`, `bae47e81…`, `a3914cfa…` |
| Meerwerk `gemeld` / `goedgekeurd` | **0** |
| Conclusie | de "14" waren ingediende weekstaten; de chip telde `meerwerk_te_beoordelen + meerwerk_nog_doorbelasten + urenstaten_wachten_op_keuring` (`DocumentenDeelscherm.tsx`) en linkte naar een pagina met alleen meerwerk-statussen |

Les (voor de volgende lezer): `weekstaat`/`meerwerk` hebben geen Beheerder-clausule in hun RLS-policy — zonder
`--administratie <uuid>` gaf de eerste query stil 0 rijen (memory `db-lezen-weekstaat-meerwerk-administratie-scope`).

## Gebouwd

1. **Beoordelen (kantoor).** `/meerwerk` heet Beoordelen mét tabs **Urenstaten (N)** (nieuw `meerwerk/UrenstatenTab.tsx`: veldwerker
   · project · week · uren · m² · ingediend op; Goedkeuren primair + ⋯ Afkeuren… mét verplichte reden / Weekstaat openen) en
   **Meerwerk (M)** (bestaande vier statussen); `?tab=urenstaten|meerwerk`, `?weekstaat=` (planning-grid) blijft het paneel
   erboven. Chip = "N urenstaten · M meerwerk te beoordelen" (`beoordelenChip.ts`), landt op de tab mét werk; klantpagina-stand
   krijgt de rij "Urenstaten — ingediend, te keuren" + badge. Lege stand (KP7): "Geen urenstaten te beoordelen — laatste keuring
   <datum>" + "Planning openen →". Tabelpatroon Gebruikers & toegang: kolomminima uit één bron (`beoordelenKolommen.ts`, som
   1012 px < 1094 op 1440), `GebruikerRijMenu` (generiek), harnas `harness-werkvoorraad.html?beoordelen=1` toegevoegd aan
   `overflow_sweep.sh` (14 rijen, langste projectnamen, namens-regel).
2. **Eén definitie voor teller en tab.** `GET /uren/kantoor/weekstaten?administratie_id=` (`overzichten.kantoor_weekstaten`) en de
   uitvoerder-keurlijst delen `_ingediende_staten` (set-based: staten, sommen, namen, projectnamen in vier statements);
   guard-test `test_guard_chip_teller_is_som_van_de_tabs` (`uren_stand.urenstaten_wachten_op_keuring == len(items)`,
   `meerwerk_te_beoordelen == len(gemeld)`).
3. **Kantoor-keuring als vangnet.** `POST /uren/kantoor/weekstaten/{adm}/{id}/goedkeuren|afkeuren` onder het module-recht "Meerwerk &
   urenstaten" + scope; `service.keur_week_goed/af(kantoor=True)` = dezelfde statusmachine, factuurmatch-hook en audit, mét
   `keurder: kantoor` in het audit-event. Dit sluit open punt 5 van de feedback-run (uitvoerder-staat zonder tweede uitvoerder).
4. **Uitvoerder keurt álle ingediende urenstaten in zijn scope** (besluit Peter 18-09, letterlijk in de opdracht): `te_keuren` =
   alle ingediende staten van de administraties mét opt-in in zijn scope, behalve de eigen; `_vereis_keurrecht` = rol uitvoerder +
   scope-rij op de administratie (server-side, náást RLS) + nooit de eigen staat. `uren_project_toewijzing` stuurt alleen nog
   "gepland bovenaan". Guards: nieuw account zonder koppelingen ziet alles; buiten scope blijft dicht.
5. **Gate-matrix** (`tests/security/test_rol_endpoint_gates.py`) kent de drie nieuwe kantoor-routes.

## Tests

| Suite | Uitkomst |
|---|---|
| `tests/uren` + `tests/security/test_rol_endpoint_gates.py` (eigen test-DB) | <<UREN_SECURITY>> |
| Nieuw `tests/uren/test_beoordelen_18_09.py` | 7 tests: guard alle staten zonder koppeling, keuren zonder koppeling (eigen staat nooit), buiten scope dicht, chip == tabs, kantoor goed-/afkeuren via API + audit `keurder: kantoor` + 422 zonder reden, 403 zonder recht/veldrol, uitvoerder-lijst == kantoor-tab |
| Aangepast | `test_weekstaat_statusmachine::test_uitvoerder_zonder_toewijzing_keurt_wel` (was `…keurt_niet` — gedragswijziging Peter 18-09); fixture `gekoppelde_uitvoerder` en `test_planning_filters` geven de uitvoerder scope (zoals élk echt veldaccount) |
| Frontend `vitest run src/meerwerk src/werkvoorraad/KlantStanden.test.tsx` | 33 groen (MeerwerkScreen.test 4 nieuw, beoordelenChip 3, beoordelenKolommen 2) |
| `tsc -b`, changelog-guard, registry-test, CLAUDE.md-/regels-guards | groen |
| `HARNASSEN_ALLEEN=beoordelen scripts/overflow_sweep.sh` (harnas `?beoordelen=1`, 14 rijen, licht+donker × 1440/1170/1024/768) | 8 metingen groen, geen horizontale pagina-overflow |

## Beslispunten (gekozen)

1. Route blijft `/meerwerk` (deep-links planning-grid/chips blijven werken); alleen titel en breadcrumb "Beoordelen".
2. Kantoor-afkeuren vraagt alleen de reden (geen correctievoorstellen per dag — die blijven de app-keuring); uitbreiden kan op het
   bestaande `correcties`-veld.
3. Geen nieuw menu-item: Beoordelen blijft de klantpagina-ingang (chip + stand-rij); registry ongewijzigd.
4. "Nog doorbelasten" telt niet mee in de chip (dat is facturatiewerk, geen beoordeling) — het houdt zijn eigen badge en rij.

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (300 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/werkvoorraad-controlescherm.md` (185 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/kantoor-frontend.md` (106 regels) — volledig, vóór de start (Domeinen-kopregel).
