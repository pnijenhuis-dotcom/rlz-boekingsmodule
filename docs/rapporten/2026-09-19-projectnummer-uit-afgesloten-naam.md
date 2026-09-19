# Projectnummer óók lezen uit "Afgesloten NNNNN …"-namen (bijvangst nameting 19-09)

**Opdracht:** `opdrachten/gedaan/2026-09-19-projectnummer-uit-afgesloten-naam.md` (19-09, bijvangst rapport
`2026-09-19-projectverdeling-afgesloten-projecten-en-rlz-kant-meting.md` sectie "Nameting ná deploy"). **Geen migratie, geen AI, geen
RLZ-write.** **Werkt in productie: niet gemeten** — de code deployt ná deze run; het meetrecept staat als vervolg-opdracht
`opdrachten/inbox/2026-09-19-nameting-projectnummer-afgesloten-na-deploy.md` en is als onderdeel in de nameting-workflow opgenomen.
**BESLISSINGEN:** "PROJECTEN — STATUS AFGESLOTEN + PROJECTNUMMER UNIEK (Peter 18-09)" rij B4. **Regels:**
`docs/regels/verplichtingen-projecten-voorraad.md` alinea "Projectnummer óók lezen uit 'Afgesloten NNNNN …'-namen" +
`docs/regels/reconciliatie.md` alinea "Blok `projecten` — `project_nummer_dubbel` telt óók …".

## Één regel voor Peter
Universal zet "Afgesloten" vóór de naam van een afgerond project (94 van 170); de module las het projectnummer alleen aan het begin
van de naam en zag daardoor "Afgesloten 26064 Apeldoorn (Ben Kuijer)" náást "26064 Harskamp (vd Brandhof)" niet als dubbel — en
blokkeerde een nieuw "26064 …" er ook niet tegen. Sinds deze run leest één functie het nummer óók achter dat woord, in de 409-poort,
de dagelijkse controle, het dubbelen-rapport én het voorstel voor het volgende nummer. Klikpunt: Harskamp (vd Brandhof) komt drie
keer voor (26064, 26084 twee keer — allemaal actief in RLZ); samenvoegen is mens-werk, nooit verwijderen.

## 1. Wat er stond en waarom het misging
- `app/projecten/nummer.py::_NUMMER_PREFIX` = `^\s*(\d{3,6})(?!\d)`: nummer alleen aan het begin. "Afgesloten 26064 …" gaf `None`
  en telde als naamloos — onzichtbaar voor `project_nummer_dubbel`, `projecten-dubbele-nummers` en de 409-poort (`vereis_nummer_vrij`).
- RLZ-kant `RlzClient.find_projects_by_name_prefix` = `startswith(Name,'26064 ')`: dezelfde blinde vlek live in RLZ.
- `app/projecten/kantoor.py::volgende_projectnummer` had een EIGEN regex (`_NUMMER_PATROON`, 3–5 cijfers) — twee lezers voor één
  begrip; ook die zag een "Afgesloten 26140 …" niet en kon een bezet nummer voorstellen.
- Het is de normale situatie bij Universal, geen randgeval: leesreplica 19-09 94 van 170 projecten mét het voorvoegsel.

## 2. STAP-0 op de RLZ-OData-filter (lees-only, `nameting.sh rlz-lezen`, Universal Steigerbouw `3ee6edf0…`)
| # | `$filter` op `Projects` | Uitkomst |
|---|---|---|
| A | `startswith(Name,'26064 ') or startswith(Name,'Afgesloten 26064 ')` | **200, count 2**: `4dfd2322…` "26064 Harskamp (vd Brandhof)" (actief, begin 05-05) + `36d04825…` "Afgesloten 26064 Apeldoorn (Ben Kuijer)" (actief, begin 08-05) |
| B | `contains(Name,'26064')` | 200, count 2 — zelfde twee; treft ook "…126064…" en vergt altijd een lokale toets |
| C | `startswith(Name,'Afgesloten 26064 ')` | 200, count 1 — alleen Apeldoorn |
| D | `contains(Name,'Harskamp') or contains(Name,'26084')` | 200, **count 3**: "26064 Harskamp (vd Brandhof)", "26084 (Harskamp) van den Brandhof" (begin 01-06), "26084 Harskamp (vd Brandhof)" (begin 26-05) — alle drie actief |

**Keuze:** de OData-`or` werkt op Projects → **één GET** met twee `startswith`-delen (`find_projects_by_name_prefixes`), daarna lokale
toets op `cijfer_prefix`. `contains` niet gekozen (meer ruis, geen winst). Vastgelegd in api-verkenning "Projects — or-filter op Name
(STAP-0 19-09)". Bijvangst instrument: `rlz-lezen` anonimiseert `Name` tot initialen maar laat `Description` staan, en op Projects is dat
dezelfde tekst — de volledige projectnaam mét opdrachtgever-naam komt dus tóch in de uitvoer. Vervolgpunt, niet in deze run gewijzigd.

## 3. Gebouwd (deterministisch, één nummerlezer)
| Onderdeel | Gedrag | Code |
|---|---|---|
| Nummerlezer | `cijfer_prefix` = cijfer-prefix ná een optioneel afsluitwoord (`zonder_afgesloten_voorvoegsel`, hergebruik `omzet.naam_zegt_afgesloten`: eerste woord, hoofdletterongevoelig, ook "afgesloten:"); "Project afgesloten 26064" = géén markering; "Afgesloten" zonder nummer = None; "261270" blijft geen treffer voor 26127 | `projecten/nummer.py` |
| Cache-toets | voorselectie `like '<nr>%' OR ilike 'afgesloten%'`, exacte toets lokaal (status/actief maakt niet uit: bezet is bezet) | `nummer.treffers_in_cache` |
| RLZ-toets | één GET `startswith(Name,'<nr> ') or startswith(Name,'Afgesloten <nr> ')`; client zonder de or-methode = twee GET's; dedup per project-id; lokale `cijfer_prefix`-toets | `rlz/client.py::find_projects_by_name_prefixes`, `nummer.treffers_in_rlz`, `nummer.rlz_prefixen` |
| 409-poort | nieuw "26064 Harskamp" naast bestaand "Afgesloten 26064 Apeldoorn" (cache óf RLZ) → `ProjectnummerBestaatAl` "26064 bestaat al: Afgesloten 26064 Apeldoorn (Ben Kuijer), lopend — openen?", niets aangemaakt | `nummer.vereis_nummer_vrij` (ongewijzigd, gebruikt de lezer) |
| Reconciliatie | `project_nummer_dubbel` ziet het paar (vingerafdruk administratie + nummer ongewijzigd; stand `meten` blijft) | `nummer.dubbele_nummers`/`cli_blok` (ongewijzigd, gebruikt de lezer) |
| CLI | `projecten-dubbele-nummers` toont 26064 mét beide kanten + voorstel "blijft" | `projecten/cli_cmd.py` (ongewijzigd) |
| Volgend nummer | `volgende_projectnummer` gebruikt dezelfde lezer (≤ 5 cijfers, jaarprefix); `kantoor._NUMMER_PATROON` + `import re` verwijderd | `projecten/kantoor.py` |
| Nameting | workflow-onderdeel `projecten-afgesloten` draait óók `reconciliatie-alles --alleen projecten --lees-only` en `projecten-dubbele-nummers --administratie "Universal Steigerbouw"` | `.github/workflows/nameting.yml` |

Frontend: geen wijziging (geen nummer-afleiding in de frontend; `projectcode`-chips komen van de server). "Wat is nieuw" aangevuld.
`app/projecten/match.py::_NUMMER_PREFIX` (projectnummer uit FACTUURTEKST) is bewust niet geraakt — ander begrip (werknummers, `[…]`-vormen).

## 4. Tests
- `tests/projecten/test_status_en_nummer.py` +3: `test_cijfer_prefix_leest_door_het_afsluitwoord_heen` (incl. "Afgesloten" zonder nummer = None,
  "261270" ≠ 26127, "Project afgesloten …" geen markering), `test_afgesloten_naam_in_rlz_of_cache_bezet_het_nummer` (409 RLZ-kant mét één
  or-GET `("26064 ", "Afgesloten 26064 ")`, 409 cache-kant, "Afgesloten 260660" is geen treffer voor 26066), `test_oudere_client_zonder_or_route_krijgt_twee_prefix_gets`;
  `TestDubbeleNummers` uitgebreid mét de 26064-casus (rapportregels + reconciliatieblok: twee afwijkingen 26064 en 26127, namen in het detail).
- `tests/projecten/test_kantoor_module.py::test_volgende_projectnummer`: "Afgesloten 26140 …" telt door naar 26141; "261500" telt niet.
- Test-fake `FakeProjectClient.find_projects_by_name_prefixes` registreert de aanroepen.
- Gericht: 32 passed. Ruff: geen nieuwe meldingen t.o.v. HEAD (de resterende E501's in deze bestanden bestonden al).
- Volledige backend-suite: **6793 passed, 1 skipped, 21 deselected** (45:26, eigen werkboom, ná alle wijzigingen).
- Docs-guards (CLAUDE.md↔BESLISSINGEN, regels-INDEX, rapporten-INDEX/gelezen regels, nameting.yml-options, changelog): 44 passed (ná de suite gedraaid, nooit parallel); vitest `changelog.test.ts` 4 passed.

## 5. Keuzes (Peter kijkt niet mee)
1. **`or`-filter, geen `contains`:** STAP-0 A groen; `contains` zou ook "…126064…" treffen en levert niets extra.
2. **Alleen het eerste woord telt als afsluitmarkering** (zelfde definitie als `naam_zegt_afgesloten` van 19-09 ochtend) — één begrip
   "naam zegt afgesloten" in de hele module; "Project afgesloten 26064" wordt bewust NIET als nummer gelezen (geen raden).
3. **`volgende_projectnummer` mee op de ene lezer** (opdracht punt 1) met behoud van de 3–5-cijfergrens van het oude patroon.
4. **Backwards-compat in `treffers_in_rlz`:** een client mét alleen de oude methode krijgt twee GET's (oudere fakes/adapters breken niet).
5. **Nameting niet in deze run:** deploy loopt pas ná de push door de Stop-hook (regel Peter 08-09) → vervolg-opdracht + workflow-onderdeel.

## 6. Klik-/beslispunten Peter
- **Harskamp (vd Brandhof) drie keer** (26064 + 2 × 26084, alle drie actief in RLZ; STAP-0 D): samenvoegen is mens-werk — welke blijft,
  verliezers ná verhuizing op afgesloten/IsActive uit, nooit verwijderen. Ná deploy toont `projecten-dubbele-nummers` de tellers per kant.
- **26064 Apeldoorn (Ben Kuijer) heet "Afgesloten" maar staat in RLZ actief** → staat al in de LET-OP-lijst "afsluiten?" (8 stuks).
- **Instrument:** `rlz-lezen` laat `Description` op Projects ongeanonimiseerd — als de anonimisering een PII-vangnet moet zijn, `Description`
  toevoegen (kleine wijziging in `app/rlz/lezen_cli.py`, aparte opdracht).
- **Bijvangst werkboom:** er stond bij de start een nieuwe inbox-opdracht `2026-09-19-cc-inbox-lock-per-opdracht-en-wachten-op-suite.md`
  van een andere sessie (ongecommit); niet aangeraakt, niet meegecommit.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (372 regels — stand ná deze run; vóór de run 349)
- `docs/regels/reconciliatie.md` (115 regels — stand ná deze run; vóór de run 107)
