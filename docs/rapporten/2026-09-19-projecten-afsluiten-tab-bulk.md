# Projecten › tab "Afsluiten? (N)" mét bulk-afsluiten en "Niet afsluiten" (opdracht Peter 19-09)

**Opdracht:** `opdrachten/gedaan/2026-09-19-projecten-afsluit-kandidaten-scherm-bulk-afsluiten.md` (Peter 19-09: "welk project is
afgesloten? dat onderscheid maken wij nu nog niet" — voorwaarde voor de verdeelsleutel-opdracht van dezelfde ochtend).
**Migratie 0167** (dev-DB `boekhouding` én `boekhouding_test` op head, `alembic check` schoon, `schema_referentie.sql` ververst). Geen
RLZ-write in deze run. **Werkt in productie: niet gemeten** — de code deployt ná deze run; meetrecept onderaan, vervolg-opdracht
`opdrachten/inbox/2026-09-19-nameting-projecten-afsluiten-tab-na-deploy.md`. Live-200 lokaal: `GET /projecten/afsluit-kandidaten`,
`…?reden=naam_afgesloten&toon_uitgesteld=true` en `GET /projecten/{aid}/afsluit-instelling` → 200 op een eigen uvicorn (8017) ná de upgrade.
**BESLISSINGEN:** "PROJECTEN — TAB AFSLUITEN? MÉT BULK-AFSLUITEN EN NIET-AFSLUITEN (Peter 19-09)".

> **Nameting ná deploy 19-09 avond:** `docs/rapporten/2026-09-19-nameting-projecten-afsluiten-tab-na-deploy.md` — motor werkt in
> productie (8/8 dezelfde kandidaten op de job-image), tab-route nog door niemand geopend; **correctie:** 25017 heeft géén
> eindfactuur-reden (jongste verkoopregel = termijn 03-06); bijvangst-fix eindfactuur-keuze deterministisch.

## Één regel voor Peter
Projecten (per administratie én kantoorbreed) heeft een tab **"Afsluiten? (N)"**: bij Universal staan daar ná de deploy **8 projecten**,
alle acht omdat hun naam met "Afgesloten" begint terwijl ze in Reeleezee actief staan (25017 Kudo Arnhem óók omdat de eindfactuur
geboekt is); vinkjes + "Afsluiten (8)" sluit ze in één keer af via de bestaande route (Reeleezee eerst inactief, dan de status; uitkomst
per rij), waarna de verdeelsleutel van vanochtend ze niet meer meeneemt. Geen enkel Universal-project is zes maanden stil; als je het
venster op 4 maanden zet komen 25157 Harderwijk en 26064 Apeldoorn er ook op "geen activiteit" bij. Niets sluit automatisch.

## Wat gebouwd is

**Motor (`backend/app/projecten/afsluiten.py`).** Eén kandidatenmotor voor de tab, de chip op Inzicht › Projecten en de CLI
`projecten-afsluit-kandidaten`. Kandidaat = lopend + actief project mét één of meer redenen:

| Reden | Toets (deterministisch) |
|---|---|
| `stil` | geen inkoop-/verkoopregel (project_regel_cache), weekstaat, planning of verplichting in de laatste N maanden; N per administratie (`project_afsluit_stil_maanden`, default 6, 1..36) |
| `eindfactuur` | de jongste verkoopregel van het project draagt "eindfactuur", "eindafrekening" of "slotfactuur" in omschrijving of referentie |
| `naam_afgesloten` | naam begint met "Afgesloten" (zelfde helper als de LET-OP in blok `projecten`) terwijl het project actief staat |
| `looptijd_verstreken` | `project_specificatie.looptijd_tot` ligt vóór vandaag |

Keuze (vastgelegd in de regels): een project **zonder énige activiteit telt niet als stil** — de cache kent geen aanmaakdatum, en een
gisteren aangemaakt project mag nooit "afsluiten?" heten; de redentekst zegt "geen inkoop, verkoop, uren of planning bekend (leeftijd
onbekend — telt niet als stil)". Dit herziet het 18-09-criterium "stil ≥ 90 dagen ÉN contract-m² bereikt", dat bij Universal nul
kandidaten gaf omdat geen project contract-m² heeft. Per rij: laatste activiteit (soort, datum, bedrag, boekstuk) en open posten als
chip "let op" (inkoop nog niet geboekt mét bedrag, open offerte, ongekeurde weekstaten) — informatie, geen blokkade. Sortering:
"Afgesloten …"-namen bovenaan, dan meeste redenen, dan langst stil.

**Handelen.** `POST /projecten/afsluiten-bulk` loopt per project door de bestaande 0160-flow (`status.sluit_project_af`: bron eerst
inactief mét terugleesverificatie — RLZ wint; Odoo archived; audit `project_afgesloten`; herberekening van nog niet geboekte
projectverdelingen) en geeft per rij `gelukt` / `bron_weigert` mét reden / `al_afgesloten` / `niet_gevonden` / `geen_toegang`. Eén
bron-client per administratie; geen credential = leesbare reden per rij, geen 500. De rolpoort (Beheerder + Boekhouding+Projecten) staat
fail-closed vóór de eerste bron-call. `POST /projecten/{aid}/{pid}/niet-afsluiten` vereist een reden (422 leeg), schrijft
`project_afsluit_uitstel` mét een snapshot van de laatste activiteit en audit `project_afsluiten_uitgesteld` oud→nieuw; de rij komt
terug zodra er activiteit ná het snapshot is en blijft tot dan zichtbaar onder "Toon uitgesteld (N)". `GET/PUT
/projecten/{aid}/afsluit-instelling` zet het stil-venster (audit).

**UI (`frontend/src/projecten/AfsluitKandidatenTab.tsx`).** In beide lijsten als `segment`-tab mét teller uit dezelfde bron als de
tabel, deeplink `?tab=afsluiten` (kantoorbreed) en `?administratie=…&tab=afsluiten` (per administratie; de administratie-link in de
kantoorbrede tab springt daarheen). Zoekveld, `Select` op reden mét tellers per reden, chip "N met open posten", vinkjes + kolomkop
alles-kiezen, "Afsluiten (N)" (uit bij 0) → dialoog mét optionele reden/datum → uitkomst-badge per rij + overzicht "Laatste bulk-actie"
dat ná herladen blijft staan; "Niet afsluiten…" = `linkbtn` + dialoog mét verplichte reden; "Openen →" naar het detail; lege stand is
een zin. Boekhouding ziet de tab zonder knoppen (`magAfsluitenBedienen`; de server beslist). De chip "N kandidaat afsluiten →" op
Inzicht › Projecten is nu een sprong naar de tab. Tabel in `.tabel-scroll`; harnas-variant
`harness-werkvoorraad.html?projecten=1&tab=afsluiten` in `overflow_sweep.sh`.

**Rechten.** Lezen: élke kantoorrol binnen scope. Handelen (bulk, niet afsluiten, stil-venster): Beheerder + Boekhouding+Projecten —
Haci/Iris bij Universal hebben die rol nodig. Klant-accordeur en veld-app: 403 (kantoorrouter).

## Meting Universal Steigerbouw (leesreplica 19-09 ~09:30, administratie 3ee6edf0, venster 6 maanden = grens 19-03-2026)

83 lopende, actieve projecten. **8 kandidaten**, allemaal op "naam zegt afgesloten":

| Project | Laatste activiteit | Stil (dagen) | Redenen | Regels inkoop/verkoop |
|---|---|---|---|---|
| Afgesloten 25017 Kudo Arnhem-Kronenburg fase 2 | verkoop 03-06-2026 | 108 | naam, **eindfactuur** | 94 / 17 |
| Afgesloten 25157 Harderwijk (Wessels) | verkoop 30-03-2026 | 173 | naam | 3 / 7 |
| Afgesloten 26064 Apeldoorn (Ben Kuijer) | inkoop 11-06-2026 | 100 | naam | 2 / 8 |
| Afgesloten 25116 Oosterhout (Huvanco) | inkoop 23-07-2026 | 58 | naam | 6 / 11 |
| Afgesloten 25147 Ommeren (van Kessel) | inkoop 23-07-2026 | 58 | naam | 6 / 15 |
| Afgesloten 26012 Tilburg (van Kasteren) | inkoop 02-09-2026 | 17 | naam | 18 / 14 |
| Afgesloten 26051 Opijnen (van kessel bouw) | inkoop 02-09-2026 | 17 | naam | 9 / 2 |
| Afgesloten 26091 Amersfoort (Ben Kuijer) | verkoop 15-09-2026 | 4 | naam | 7 / 1 |

Per reden: naam zegt afgesloten 8 · eindfactuur 1 · geen activiteit 0 · looptijd verstreken 0. Geen ongekeurde weekstaten op deze acht
(open-posten-chip blijft leeg; inkoop-nog-niet-geboekt en open offertes zijn op de replica niet mee-gemeten en verschijnen in de tab).
De twee uit het 18-09-rapport (26012 Tilburg, 26051 Opijnen — de enige mét geboekte verdelingsdelen) staan erbij; in totaal zijn het
acht, zoals het 19-09-verdeelsleutelrapport al telde. Bijvangst: 11 projecten zonder énige activiteit (o.a. "26149" en "26149 Poeldijk,
Anjerstraat 245 (Weboma)", en "26064 Harskamp (vd Brandhof)" náást "Afgesloten 26064 Apeldoorn") — dubbele nummers, zie CLI
`projecten-dubbele-nummers`; geen `looptijd_tot` gevuld bij Universal, dus de vierde reden werkt pas als specificaties gevuld worden.

## Beslispunten Peter
1. **Stil-venster Universal:** 6 maanden (default) laten, of 4 — dan komen 25157 Harderwijk en 26064 Apeldoorn er óók op "geen activiteit"
   bij. Instelbaar op de tab zelf (Beheerder/B+P), geen code nodig.
2. **De acht afvinken (morgen, Peter/Haci):** daarna verdwijnt de LET-OP "naam zegt afgesloten" uit reconciliatieblok `projecten` en neemt
   de verdeelsleutel ze niet meer mee. Open punt uit het ochtendrapport blijft: de € 1.239,05 al geboekte verdeling op 26012/26051 laten staan.
3. **`looptijd_tot` vullen** bij de projectspecificaties (contract-ontleding vult 'm waar het contract een einddatum noemt) zodat de
   reden "looptijd verstreken" gaat werken.

## Keuzes in deze run (Peter kijkt niet mee)
- Geen activiteit ≠ stil (zie boven); "afgesloten" midden in een naam telt niet (eerste woord, zoals de LET-OP).
- Het stil-venster staat op de tab (per administratie) en niet als extra instelling in Instellingen › Administraties: het hoort bij wie
  de lijst afwerkt (Beheerder + B+P, `_vereis_schrijfrol`), audit oud→nieuw; geen registry-wijziging nodig.
- "Tijdlijn per project" = het audit_event (`project_afgesloten`, `project_afsluiten_uitgesteld`) — een project heeft geen eigen
  tijdlijntabel; het detail toont status/afgesloten-op/reden zoals sinds 0160.
- De oude motor `status.kandidaat_afsluiten_per_project` (m²-criterium) is verwijderd; de chip en de CLI lezen de nieuwe.
- Uitstel intrekken bestaat niet als knop: opnieuw beoordelen = afsluiten vanaf het detail, of nieuwe activiteit brengt de rij terug.

## Tests
- Backend `tests/projecten/test_afsluiten.py` (10, groen): redenen puur (venstergrens 6/3 mnd, geen activiteit ≠ stil, eindfactuur-regex,
  naam eerste woord, looptijd vandaag ≠ verstreken), motor op DB (laatste activiteit mét boekstuk/bedrag, open inkoop, sortering),
  chip kantoorbreed uit dezelfde motor, API lijst/filter/zoek/422, niet-afsluiten 422 leeg → onthouden → nieuwe activiteit → terug,
  audit oud→nieuw, rechten (Boekhouding 403 op alle drie de handelingen, B+P 200, accordeur 403), stil-venster GET/PUT/422/audit, bulk
  uitkomst per rij (gelukt / al afgesloten / geen toegang / niet gevonden / bron weigert / geen credential), bulk leeg 422, CLI.
- Frontend `AfsluitKandidatenTab.test.tsx` (7, groen): rijen/chips/open posten, filter + zoek naar de server, bulk mét bevestiging en
  uitkomst per rij, niet-afsluiten mét verplichte reden + "Toon uitgesteld", per administratie zonder administratiekolom + stil-venster
  PUT, rechtenhelper, `?tab=afsluiten` op beide lijsten. `tsc -b` schoon; bestaande projecten-tests aangepast (kandidaat-test verhuisd).
- Volledige backend-suite en overflow-sweep (ingevuld door de run "inbox-afgewerkt" 19-09 — de bouwrun eindigde vóór zijn suite klaar was, het werk stond tot die run ongecommit): **suite 6791 passed, 0 failed (1:09 u, eigen test-DB `boekhouding_test_autotype`, eindstand werkboom incl. kassarapport-autotype); overflow-sweep groen, 232 metingen.**

## Meetrecept ná deploy (vervolg-opdracht in de inbox)
Stap 0 deploy-check service én jobs; dan `gh workflow run nameting.yml -f onderdeel=projecten-afgesloten` (draait nu óók
`projecten-afsluit-kandidaten --administratie "Universal Steigerbouw"`): verwacht "Totaal: 83 lopende projecten beoordeeld, 8 kandidaat
afsluiten (… naam zegt afgesloten 8 …)" of minder als er al afgevinkt is; Cloud Logging `GET /projecten/afsluit-kandidaten` 200 voor
3ee6edf0. Dan "werkt in productie: ja/nee" hier en in BESLISSINGEN.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (309 regels bij het lezen; 349 ná deze run)
- `docs/regels/kantoor-frontend.md` (123 regels bij het lezen; 133 ná deze run)
