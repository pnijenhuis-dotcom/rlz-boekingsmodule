# Rapport 18-09 — Klant-accordering: overflow-bug, zoekveld + filters, accordeur uitnodigen/koppelen, leveranciersroute "bovenop" (inbox-run 3, agent A)

Opdracht: `opdrachten/gedaan/2026-09-18-klein-klant-accordering-zoekveld-en-accordeur-uitnodigen-knop.md` (punten 0–5).
Domeinen: accordering-native-app, kantoor-frontend, werkvoorraad-controlescherm. Migratie **0164**.

## Samenvatting (één regel voor Peter)
Instellingen › Klant-accordering heeft nu een zoekveld, filters en per administratie de stand in één oogopslag; de knoppen die op 1385 px
buiten beeld stonden staan links onder het blok; "geen accordeur" heeft twee knoppen (uitnodigen voorgevuld / bestaande koppelen); en een
leveranciersroute kan "bovenop de gewone route" (extra laag vóór of ná) — voor Bouwadvies hoeft u de drie gewone lagen niet meer te kopiëren.

## Gedaan / niet gedaan
| Punt | Stand | Kern |
|---|---|---|
| 0 overflow 1385 px | **gedaan** | Oorzaak: kale `<table>`s (staande goedkeuringen, 7-koloms toestellentabel) als grid-item rekten het paneel op; `.actions` (flex-end) hing aan die te brede rechterrand → knoppen buiten beeld. Fix: tabellen in `.tabel-scroll`, grid `minWidth: 0`, lagen-rijen wrappen, actieknoppen links (`flex-start`); filter-segment wrapt. Sweep-harnas `harness-instellingen.html?pad=/instellingen/accordering&administratie=<id>` (twee varianten) meet óók 1385 en 1280 px. |
| 1 zoekveld + chips + samenvatting + deeplink | **gedaan** | `GET /accordering/overzicht` (kantoorrol, scope) → zoekveld (`?zoek=`, `/`-focus, teller "N van M", lege stand mét actie), chips Alle/Accordering aan/Met leveranciersroute/Zonder accordeur (`?filter=`), samenvatting "aan · 2 lagen · 1 route · 3 accordeurs" + chip "actie nodig" bij 0 accordeurs; `?administratie=<id>` klapt open + laadt + scrolt. |
| 2 melding mét acties | **gedaan** | `GeenAccordeursMelding`: "Accordeur uitnodigen →" (Gebruikers & toegang, formulier direct open mét rol Klant-accordeur + administratie via `?uitnodig=accordeur&administratie=`) en "Bestaande accordeur koppelen →" (Beheerder; dialoog over `GET /accordering/accordeur-kandidaten`, aanvinken = bestaande `POST /auth/gebruikers/{id}/scope`, audit server-side). Óók in de route-editor. |
| 3 combobox leveranciers | **gedaan** | `SearchableCombobox` mét `GET …/accordering/leverancier-kandidaten` (open documenten bovenaan, label "· N open"); terugval kale crediteurenlijst. |
| 4 guards | **gedaan** | zie Tests. |
| 5 route "bovenop" | **gedaan** | migratie 0164 `modus`/`positie` + check-constraints; `effectieve_route_lagen` (pure); aanbieden + herberekening; doorwerking gewone route in bovenop-rondes; tijdlijn "Route: gewoon + extra laag …"; UI KeuzeKaarten + chip + samenvatting. |

## Feiten / metingen
- Overflow-sweep accordering-harnas (POORT 5201, 2 varianten × licht/donker × 1440/1170/1024/768/1385/1280 = 24 metingen): **groen, 24/24** ná de fixes (eerste meting mét gerenderde tabellen: 1024/768 rood op de vierde filterchip `button [878..1030]` → segment wrapt; een tussenmeting gaf 1× ❓ door een tijdelijke parse-fout in een sibling-bestand, herhaald groen).
- Harnas-gap gevonden (pre-existing): `InstellingenScreen.laadAlles()` wacht op vijf calls; `/instellingen/duplicaat-autoafvoer`, `/groepen` en `/uren/kantoor/mijn-toegang` waren niet gemockt → élke sectie mét administraties (accordering, doorbelasting) toonde in het harnas "backend niet bereikbaar" en de sweep meette een leeg paneel. Nu gemockt.
- Screenshot 1024 px (ná fix, vóór segment-wrap): alles in beeld behalve de vierde filterchip → segment wrapt nu.
- Backend: `/accordering/overzicht` = één statement per administratie (drie scalar-subquery's) — de accordering-tabellen dragen alleen een scope-RLS-policy; bij ≫ 200 administraties een Beheerder-leespolicy overwegen (beslispunt).

## Tests
- Backend (eigen test-DB `boekhouding_test_a2`): `tests/accordering/test_leverancier_route.py` 12 groen (6 nieuw: bovenop vóór/ná + detail + herberekening bij positiewissel; doorwerking gewone route in bovenop-ronde en níét in vervangt-ronde + drempel per laag; validatie modus/positie; pure `effectieve_route_lagen`; overzicht + leverancier-kandidaten + bovenop via de API + 409); `tests/security/test_rol_endpoint_gates.py` groen (matrix +2 routes); `tests/accordering` volledig: 139 groen, **2 rood buiten mijn blok** (`test_wachtrij_querytelling.py`: `DocumentAlAanwezig: Al aanwezig als "factuur-0.pdf"` — de nieuwe byte-identiek-upload-409 van opdracht 3/agent C raakt fixtures die dezelfde PDF-bytes twee keer uploaden; coördinator/agent C); `test_migratie_metadata_guard.py` groen op 0164.
- Les eigen test-DB: de stub 0165 stond als lege migratie op mijn DB toen agent D 'm vulde → `downgrade base` viel op `DROP TABLE boek_wachtrij_claim`; hersteld met `UPDATE alembic_version SET version_num='0164'` (0163 stond al gevuld). Zie memory [[parallelle-bouwagenten-recept]] (migratiestubs-race, nu óók op een eigen DB als een sibling ná jouw eerste run vult).
- Frontend: `tsc -b` groen voor mijn bestanden (rode regels van andere agenten: `BoekvoorstelPanel.tsx` `btw_kolom_percentage`/`bedrag_niet_gelezen`, `BtwAftrekUitgeslotenBlok.tsx` parse-fout — tijdelijk, niet van mij); vitest `AccorderingInstellingen.test.tsx` (4), `LeverancierRoutes.test.tsx` (5), `GebruikersScreen.test.tsx` (+1, 43 totaal in de vier bestanden), `UitnodigModal.test.tsx`, `AccorderingApparaten.test.tsx`, `BulkAccorderingDialog.test.tsx`, `AccordeurAdministraties.test.tsx`, `accorderingRouteTijdlijn.test.ts` (2), `styles/contrast.test.ts`, `instellingenRegistry.test.ts` — alle groen.
- Gouden set: ik raakte `frontend/src/document/{accorderingRouteTijdlijn.ts,DocumentDetailScreen.tsx}` (tijdlijnregel); `tests/keten` niet aangeraakt door mij — de keten-guard is in deze run groen via de casussen van agenten B/C (coördinator toetst `tests/keten -q` centraal).

## Migratie-routine
- Gedaan (agent): 0164 gevuld (schema-only, pure DDL, check-constraints), model + `test_migratie_metadata_guard.py` groen op eigen DB.
- Coördinator: `make migrate` tegen de dev-DB (`Running upgrade 0163 -> 0164`), live-200 op `GET /accordering/overzicht`, `GET /administraties/{id}/accordering/leverancier-kandidaten`, `GET/POST …/accordering/leverancier-routes` (body mét `modus`/`positie`), `scripts/dump_schema.sh` vanuit de repo-root.

## Klikpunten Peter
1. `/instellingen/accordering?zoek=blow` → één regel; chip "Zonder accordeur (N)" → BLOW mét "actie nodig"; openklappen → melding mét "Accordeur uitnodigen →" en "Bestaande accordeur koppelen →".
2. Bouwadvies Oost Nederland op 1385 px (`/instellingen/accordering?administratie=<id>`): geen horizontale scroll; "+ Laag toevoegen", "Opslaan", "+ Leveranciersroute" en "Toegang intrekken" in beeld.
3. Bouwadvies: "+ Leveranciersroute" → naam, twee leveranciers via de combobox, "Bovenop de gewone route" + "Ná de laatste laag", accordeur kiezen → Opslaan; lijst toont chip "bovenop de gewone route"; een nieuwe factuur van die leverancier krijgt gewone lagen + de extra laag (tijdlijn "Route: gewoon + extra laag …").
(Geen geldbedragen in deze klikpunten.)

## Beslispunten
- (i) Akkoord-behoud bij herberekening ongewijzigd (bundel 09-09): een gegeven akkoord dat door modus-/positiewissel of een gewone-route-wijziging naar een LATERE positie verschuift, vervalt (test documenteert dit). Versoepelen = apart besluit.
- (ii) "Bestaande accordeur koppelen" = alleen toevoegen; loskoppelen blijft op Gebruikers & toegang (vervallen-rondes-waarschuwing).
- (iii) Overzicht-route N statements voor N administraties (RLS); Beheerder-leespolicy op `accordering_laag`/`accordering_leverancier_route` als het kantoor richting 200+ gaat.
- (iv) Leveranciersroute-editor toont "Extra laag N" bij bovenop; drempel per extra laag blijft mogelijk (zelfde regel).

## Nameting-recept (ná deploy, lees-only, `nameting.sh`/Cloud Logging)
1. Deploy-check: service én jobs op het beeld van de commit mét 0164; migratie-job logt `Running upgrade 0163 -> 0164`.
2. Request-log: `GET /accordering/overzicht` 200 door Peter/kantoor ná het openen van Instellingen › Klant-accordering; `GET /administraties/<blow>/accordering/leverancier-kandidaten` 200 bij het openen van de route-editor.
3. Klikpunt 1 en 2 door Peter (geen data-wijziging). Klikpunt 3 = mensbesluit; ná zijn klik: `db-lezen`/replica `boekhouding.accordering_leverancier_route WHERE modus='bovenop'` ≥ 1 rij (Bouwadvies), audit `accordering_leveranciersroute_gewijzigd` mét `modus: bovenop`.
4. Rapportregel: werkt in productie: ja/nee per punt.

**werkt in productie: niet gemeten** (een deploy binnen de run bestaat niet).

## Geraakte bestanden
backend: `app/accordering/{models,service,schemas,router}.py`, `migrations/versions/0164_accordering_leverancier_route_modus.py`, `tests/accordering/test_leverancier_route.py`, `tests/security/test_rol_endpoint_gates.py`.
frontend: `src/instellingen/{AccorderingInstellingen.tsx,LeverancierRoutes.tsx,GeenAccordeursMelding.tsx(nieuw),AccorderingInstellingen.test.tsx(nieuw),LeverancierRoutes.test.tsx}`, `src/accordering/accorderingApi.ts`, `src/gebruikers/{UitnodigModal.tsx,GebruikersScreen.tsx,GebruikersScreen.test.tsx}`, `src/document/{accorderingRouteTijdlijn.ts(nieuw),accorderingRouteTijdlijn.test.ts(nieuw),DocumentDetailScreen.tsx}`, `src/dev/visueelHarnasInstellingen.tsx`, `scripts/overflow_sweep.sh`.
Scratchpad: `regels_A.md`, `beslissingen_A.md`, `claude_md_A.md`, `watisnieuw_A.md`.

## Gelezen regels
- `docs/regels/accordering-native-app.md` (321 regels)
- `docs/regels/kantoor-frontend.md` (123 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- Overige domeinen van deze inbox-run (door de coördinator vooraf volledig gelezen): `docs/regels/autoboeken-ai.md` (122 regels), `docs/regels/btw.md` (150 regels), `docs/regels/intake-extractie.md` (270 regels), `docs/regels/duplicaten-crediteuren.md` (119 regels), `docs/regels/uren-planning-veldwerkers.md` (472 regels)
