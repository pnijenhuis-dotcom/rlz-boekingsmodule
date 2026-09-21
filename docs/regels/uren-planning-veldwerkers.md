# Regels — Uren & meerwerk, planning, werkopdrachten, veldwerkers

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Steigerbouw-tak (opt-in per administratie): weekstaat per project, hybride keuring, factuurmatch, ZZP-dossier + KvK, planning-agenda mét urenstatus, transport, werkopdrachten, Beheer › Veldwerkers, materiaal.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Kantoor-signaal "geplande week zonder weekstaat"** (`app/uren/planning_signaal.py`, geen blokkade; migratie 0115)
  — zie BESLISSINGEN "PLANNING-SIGNAAL 'GEPLANDE WEEK ZONDER WEEKSTAAT'".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Uren & meerwerk (steigerbouw-tak, opt-in per administratie — alleen Universal initieel):** WEEKSTAAT PER PROJECT,
  rollen ZZP'er/uitvoerder/detacheerder in de bestaande native app, hybride keuring op weekniveau, factuurmatch
  (fase 1–4), ZZP-dossier + handhaving + KvK, geofence-stempels BASIS (native achtergrondlocatie alleen op branch
  `feat/geofence-native` — NIET mergen/releasen), prijsafspraken, planning-agenda (grid v3), transport v2 dag-agenda,
  werkopdrachten, fijnmazig recht "veldwerkerbeheer", detacheerder-filters. **Seam-eis steigerbouw-run: nieuwe
  module-code roept nooit RlzClient aan; adapter-grepen per blok in BESLISSINGEN "ODOO-ADAPTER — GREPEN".** Zie
  BESLISSINGEN "Ontwerpronde uren & uitvoerder + meerwerk-kantoor", "UREN & MEERWERK — BOUW", "FACTUURMATCH
  ZZP-/BUREAUFACTUREN" (fase 1–4), "STEIGERBOUW-RUN 25-08" blokken A–D, "BOUWRUN 28-08 AVOND" blok C, "OPDRACHT 29-08"
  blok C, "PLANNING-AGENDA STEIGERBOUW", "PLANNING-UITBREIDING 31-08", "DETACHEERDER-FILTERS VELD-APP"; mockups
  `uren-uitvoerder.html`, `meerwerk-kantoor.html`, `planning-steigerbouw.html`, `planning-werkopdracht-transport.html`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Planning — urenstatus in het grid + terugwerkende kracht (Peter/Haci 15-09; migratie 0145):** per kaartje de urenstatus uit de weekstaat (grijs geen · blauw ingevuld "8 u · 42 m²" · groen gekeurd · oranje afgekeurd/vraag, tooltip, klik = weekstaat; één statement per week, querytelling-meetlat), weektotaal-chip per projectrij, filter `?uren=zonder|ongekeurd`; planning in een verstreken/lopende week = audit `achteraf`/`week_status`, chip "achteraf", één gebundelde melding per veldwerker × week via `planning_wijziging_melding` + de 10-min-job (`planning_meldingen.py`, deep-link `/accordeur?planning=JJJJ-Wnn`), veld-app chips week N−2/N−1/deze week — zie BESLISSINGEN "PLANNING — URENSTATUS IN HET GRID + TERUGWERKENDE KRACHT (Peter/Haci 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Veldwerkers-run 14-09 (besluiten Peter 14-09 punt 1+2; migratie 0141 = RLS-policy detacheerder_koppeling):** het recht 'veldwerkerbeheer' dekt nu óók het veldwerkers-overzicht en de koppelingen (detacheerder↔ZZP'er incl. bureau-tarief mét audit oud→nieuw, crediteur incl. autoboek-opt-in, projectkoppeling verwijderen) en het ZZP-dossier kantoorkant (`require_veldwerkerbeheer_of_meerwerk_recht`), altijd binnen de eigen scope (server-side per aanroep + RLS); rechten toekennen en dossier-documenttypen blijven Beheerder-only; eigen pagina **Beheer › Veldwerkers** (`/veldwerkers`, kantoorbreed, administratie = filter, kolom Dossier uit de bestaande dossier-DTO, filter `dossier_onvolledig`, één primaire knop + ⋯), /gebruikers blijft Beheerder-only mét account-tabel + link — zie BESLISSINGEN "VELDWERKERS-RUN 14-09 — RECHT VERBREED + /VELDWERKERS + DOSSIER-KOLOM".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Veldwerker-dialogen zonder picker-poort (C3 07-09):** dossier/crediteur-koppelen openen voorgeselecteerd via `gebruikers/standaardAdministratie.ts` (één in scope → recentste planning/koppeling → uren-opt-in), picker = wissel-filter — zie BESLISSINGEN "FIXRUN 07-09 — BLOK C3". **KvK-lookup productie (E7 07-09):** `KVK_BASE_URL=https://api.kvk.nl/api/v1/basisprofielen` + secret `KVK_API_KEY` (Vastly-sleutel, zelfde BV) in deploy.yml; lokaal zonder beide = testomgeving — zie BESLISSINGEN "E7 — KVK-LOOKUP PRODUCTIE".

<!-- toegevoegd 18-09-2026, opdracht "veldapp-uitvoerder-feedback-m2-doorfactureren-projecten" -->
- **Veld-app uitvoerder — feedback 18-09 (uitvoerder via Peter 18-09; migratie 0158 = `weekstaat_dag.doorfactureren`; BESLISSINGEN
  "VELD-APP UITVOERDER — FEEDBACK 18-09"):** (A) **m² is optioneel** op élke weekstaat-regel (uren verplicht); leeg blijft NULL,
  nooit 0; chips tonen dan alleen uren ("8 u" — `urenLabel`/`weekTotaalLabel`/planning-grid `urenKort`); sommen tellen alleen
  ingevulde regels; een regel zonder m² is geen fout en geen signaal; guard `tests/uren/test_uitvoerder_feedback_18_09.py`
  (indienen zonder m² = 200). (B) **Doorfactureren-keuze per REGEL** (dag × project — beslispunt regelniveau, niet de hele
  weekstaat): dropdown "Doorfactureren / Niet doorfactureren"; default = `service.standaard_doorfactureren` (project mét ≥ 1
  verrekenbare staffel uit de contract-ontleding → Doorfactureren, anders Niet), zichtbaar als chip "standaard voor dit
  project"; mens wint, audit oud→nieuw op `weekstaat_dag_gezet`; DTO's dragen `doorfactureren` per dag +
  `totaal_uren/m2_niet_doorfactureren` + `doorfactureren_standaard` (ook op de lookup zonder staat); keuring (app) en het
  kantoor-weekstaatpaneel (`/meerwerk?administratie=…&weekstaat=<id>`, `meerwerk/WeekstaatPaneel.tsx`, filter "alleen niet
  doorfactureren", "door te belasten = totaal − niet doorfactureren") tonen de regels apart; de FACTUURMATCH (ZZP-inkoopkant)
  telt onverkort álle uren — de ZZP'er krijgt betaald ongeacht de keuze. (C) **Alle projecten, gepland bovenaan; "achteraf"-
  staat:** `week_projecten_zzp` geeft ÁLLE actieve projecten van de administraties mét opt-in in de scope (set-based: één
  projectquery per administratie), geplande projecten en projecten mét een staat bovenaan (chip "gepland"), de rest doorzoekbaar
  eronder mét chip "niet gepland" (informatief, geen blokkade — `buiten_planning` per dag + `dagen_buiten_planning` per staat
  voeden de keuring, het kantoor-paneel en het bestaande planning-signaal "buiten planning"); de aparte stap "+ ander project"
  is VERVALLEN (`GET /uren/zzp/projecten-keuze` blijft bestaan, ongebruikt door de app). **De uitvoerder heeft nu eigen
  weekstaten** ("soort urenstaat achteraf"): `INVULLER_ROLLEN` = ZZP'er + uitvoerder (alleen voor zichzelf — namens-invoer
  blijft detacheerder→ZZP'er), tab "⏱ Mijn uren" mét exact de ZZP-flow; **hij keurt zijn eigen staat nooit** (vier-ogen:
  `_vereis_keurrecht(staat_gebruiker_id)`, te-keuren-lijst en projecttellers zonder eigen staten) — een andere uitvoerder op
  het project keurt; is die er niet, dan blijft de staat op `ingediend` (open punt: kantoor-keuring, zie rapport). De
  uitvoerder-projectenlijst, het projectdetail en meerwerk melden dekken sinds 18-09 élk ACTIEF project in de scope (koppeling =
  filter "gekoppeld bovenaan", geen poort; niet-actief zonder koppeling = GeenToegang). (D) **Planning uit de uitvoerder-app:**
  geen planningstab/-route voor de rol uitvoerder (allowlist `frontend/src/auth/rollen.ts::toontPlanningTab` = ZZP'er +
  detacheerder, fail-closed; deep-link `?planning=` landt voor hem op Mijn uren); planning blijft voor kantoor (grid) en als
  bron voor "gepland bovenaan"; meldingen "planning gewijzigd" BLIJVEN (beslispunt default). Kantoor-web ongewijzigd behalve het
  nieuwe weekstaatpaneel. Mockup `uren-uitvoerder.html` 1-op-1 mee bijgewerkt.

<!-- toegevoegd 18-09-2026, opdracht "veldapp-project-eerst-flow" -->
- **Veld-app — PROJECT EERST (Peter 18-09: "Niet beter om eerst het project te selecteren en dan de uren-/meerwerkknop?
  Anders druk je op een knop en moet je eerst gaan zoeken."; akkoord Cowork; bouwnorm `mockup/uren-uitvoerder-v2.html`
  scherm ①, notitie "Project eerst"; geen migratie; BESLISSINGEN "VELD-APP — PROJECT EERST (Peter 18-09)"):** de
  weekweergave van de uitvoerder én de ZZP-/namens-flow is een lijst PROJECTKAARTEN: de geplande projecten van die week
  (chip "gepland") ∪ de projecten waar deze week al uren op staan ∪ de projecten waar deze gebruiker deze week meerwerk op
  meldde (chip "niet gepland" als ze niet gepland zijn) ∪ de projecten die de gebruiker zelf toevoegde. Per kaart: dagtotaal van
  de in de dagbalk gekozen dag, weektotaal, laatste omschrijving, doorfactureren-chip (N dagen niet doorfactureren, anders de
  projectdefault), meerwerk-teller, statuschip, en twee knoppen **"+ Uren"** (primair) en **"Meerwerk melden"** (alleen een
  uitvoerder, nooit namens — backend `meld_meerwerk`) — beide starten mét het project én de dag al ingevuld (geen projectkeuze
  meer in het formulier; ander project = terug naar de kaartenlijst). Kaarttitel = de weekstaat van dat project (dagen, indienen,
  correctievoorstellen). Onderaan **"+ Ander project toevoegen aan mijn week"** → `GET /uren/zzp/week-projecten?alles=true`
  (álle actieve projecten in scope, doorzoekbaar, kaarten die al in de week staan blijven weg) → kaart erbij zonder uren; een
  kaart zonder regels leeft in app-state per week en verdwijnt bij weekwissel. **"Week indienen (N u)"** op de kaartenlijst dient
  élke concept-/corrigeren-staat mét uren van die week in (per project = per weekstaat, bestaande route, dossier-blokkade 423
  zichtbaar). Backend: `overzichten.week_projecten_zzp(alles=False)` = kaartsamenstelling gepland ∪ mét staat ∪ mét meerwerk
  (eigen meldingen, `datum_uitgevoerd` in de week, alleen actieve projecten); `alles=True` = de keuzelijst; kaartvelden
  `dag_uren`/`laatste_omschrijving`/`dagen_niet_doorfactureren`/`doorfactureren_standaard`/`meerwerk_aantal` op
  `WeekProjectKaartDto`; set-based: vast aantal statements per administratie ongeacht het aantal kaarten (`_planning_stand`
  vult projectnaam/soort werk sinds 18-09 in één query i.p.v. twee `session.get`'s per item) — querytelling-meetlat
  `tests/uren/test_project_eerst_18_09.py`. `GET /uren/zzp/projecten-keuze` blijft bestaan (ongebruikt). Meerwerk-tab in de
  onderbalk (uitvoerder-projectenlijst → projectdetail) blijft het overzicht van gemelde meerwerken; werkbonnen ongewijzigd;
  planning voor de uitvoerder blijft weg (blok D 18-09).

<!-- toegevoegd 18-09-2026, opdracht "BUG-chip-meerwerk-urenstaten-lege-pagina" -->
- **Beoordelen — urenstaten en meerwerk op één plek + uitvoerder keurt alles in scope (bug Peter 18-09 "chip 14
  meerwerk/urenstaten te beoordelen → lege Meerwerk-pagina 0/0/0/0"; geen migratie; BESLISSINGEN "BEOORDELEN — URENSTATEN
  EN MEERWERK OP ÉÉN PLEK; UITVOERDER KEURT ALLES IN SCOPE (Peter 18-09)"):** (1) De kantoorpagina `/meerwerk` heet
  **Beoordelen** en draagt twee tabs: **Urenstaten (N)** — álle ingediende weekstaten van de administratie (veldwerker, project,
  week, uren, m², ingediend op; acties Goedkeuren (primair) + ⋯ Afkeuren… mét verplichte reden / Weekstaat openen) en
  **Meerwerk (M)** — de bestaande vier statussen; `?tab=urenstaten|meerwerk`. De chip op de klantpagina/documentenlijst zegt
  "N urenstaten · M meerwerk te beoordelen" (`meerwerk/beoordelenChip.ts`; "nog doorbelasten" telt bewust niet mee) en landt
  op de tab mét werk; de klantpagina-stand krijgt een rij "Urenstaten — ingediend, te keuren". Teller en tab delen de
  definitie: `uren_stand.urenstaten_wachten_op_keuring` == `GET /uren/kantoor/weekstaten` (`overzichten._ingediende_staten`,
  gedeeld met de uitvoerder-keurlijst) — guard `tests/uren/test_beoordelen_18_09.py::test_guard_chip_teller_is_som_van_de_tabs`.
  Lege stand = context + actie (KP7): "Geen urenstaten te beoordelen — laatste keuring <datum>" + "Planning openen →".
  Tabel volgens het Gebruikers & toegang-patroon: kolomminima uit één bron (`meerwerk/beoordelenKolommen.ts`, som 1012 px
  < 1094 op 1440), één primaire knop + ⋯ (`GebruikerRijMenu`), harnas `harness-werkvoorraad.html?beoordelen=1` in de
  overflow-sweep. (2) **Kantoor-keuring** = vangnet: `POST /uren/kantoor/weekstaten/{adm}/{id}/goedkeuren|afkeuren` onder het
  module-recht "Meerwerk & urenstaten" + scope, zelfde statusmachine/factuurmatch-hook als de app-route, audit
  `weekstaat_goedgekeurd` mét `keurder: kantoor` (sluit het open punt "geen tweede uitvoerder" van de feedback-run). (3)
  **Uitvoerder keurt álle ingediende urenstaten van de administratie(s) in zijn scope — besluit Peter 18-09, letterlijk:
  "uitvoerder moet gewoon alle ingediende urenstaten controleren, los van welk project hij gepland staat."** Geen beperking per
  project; `uren_project_toewijzing` stuurt alleen nog "gepland bovenaan" in de projectlijst, nooit de keurbevoegdheid
  (`_vereis_keurrecht`: rol uitvoerder + scope-rij op de administratie + nooit de eigen staat). Guard: nieuw uitvoerder-account
  zonder koppelingen ziet direct álle ingediende weekstaten van de administratie
  (`test_guard_nieuw_uitvoerder_account_zonder_koppelingen_ziet_alle_ingediende_staten`); scope blijft de poort
  (`test_buiten_scope_blijft_dicht`). Databewijs productie 18-09 (lees-only replica, `scripts/gcp/db_lezen.sh`): Universal
  Steigerbouw B.V. (`3ee6edf0…`) had 14 weekstaten `ingediend` (week 2026-W37, ingediend 2026-09-15, 5 veldwerkers × 4 projecten)
  en 0 meerwerk `gemeld`/`goedgekeurd` — de "14" waren dus urenstaten. Les: `weekstaat`/`meerwerk` dragen geen
  Beheerder-RLS-clausule — lees ze op de replica altijd mét `--administratie <uuid>`.

<!-- toegevoegd 18-09-2026, opdracht "veldapp-ux-verbeteringen-12-punten" (run A) -->
- **Veld-app — 12 UX-verbeteringen, run A (Peter 18-09 "geef de opdracht voor alle punten"; bouwnorm
  `mockup/uren-uitvoerder-v3.html` + v2; migratie 0159 = `administratie.uren_omschrijving_chips`; BESLISSINGEN "VELD-APP — 12
  UX-VERBETERINGEN (Peter 18-09)"):** (1) **"Zelfde als gisteren"** op elke projectkaart: de LAATSTE dagregel van deze gebruiker op
  dat project (ook uit een vorige week — `WeekProjectKaartDto.laatste_regel`) gaat mét uren, m², omschrijving én doorfactureren
  naar de in de dagbalk gekozen dag; één tik, direct opgeslagen, audit `weekstaat_dag_gezet` mét `bron=kopie`
  (`DagZettenRequest.bron`, default `handmatig`). (2) **Uren als tikknoppen** 4 · 6 · 8 · 10 en −/+ per half uur (0–24); een
  toetsenbord alleen via "ander aantal…". (3) **Omschrijving als chips** — default opbouwen · afbreken · ombouwen · transport ·
  overig; per administratie door de Beheerder instelbaar (Instellingen › administratie › Uren & materiaal, `PUT
  /uren/beheer/omschrijving-chips/{aid}`, 1–10 chips ≤ 30 tekens uniek, audit `uren_omschrijving_chips_gewijzigd`; app leest
  `GET /uren/zzp/omschrijving-chips`); "overig" (of geen chip) = vrij tekstveld; opslag als tekst in `weekstaat_dag.opmerking`,
  GEEN enum. (6) **Tikdoelen ≥ 48 px**, per kaart één primaire knop ("+ Uren", bij een afgekeurde week "Aanpassen"); "Zelfde als
  gisteren" en "Meerwerk melden" als tekstlinks eronder (KP7). (7) **Leesbaarheid buiten**: binnen `.acc-veld` geen tekst < 14 px
  (chips, meta, hulptekst, sectielabels — guard `uren/veldTekst.test.ts`), hulptekst `--acc-muted` ≥ 4,5:1 op bg én panel in beide
  modi (contrast-test). (8) **Week indienen met samenvatting** (sheet): "N dagen · U u · P projecten · R regels zonder m² · D niet
  doorfactureren" + bevestigen; ma–vr zonder uren = waarschuwing, niet blokkerend (`urenApi.indienSamenvatting`). (9) **Vergeten dag**:
  werkdag t/m gisteren zonder uren = oranje rand in de dagbalk + notitie (`vergetenDagen`). (10) **Terugkoppeling** op de kaart per
  week: ✓ goedgekeurd door X / afgekeurd door X mét reden + knop "Aanpassen" (opent de weekstaat die al op `corrigeren` staat; geen
  extra statusovergang, de bestaande keur-audit blijft de bron); weekchip "afgekeurd — aanpassen". (11) **Doorfactureren ingeklapt**:
  chip + "standaard voor dit project" + "wijzigen"; de dropdown pas ná tikken. (12) **Velden verbergen**: m² (en het vrije
  omschrijvingsveld zonder chip) onder "▸ meer" als het project geen m²-project is (`contract_m2` leeg/0 — `isM2Project`); een
  m²-project toont m² direct; chips altijd zichtbaar. Punten 4 (dag-einde herinnering) en 5 (offline) = **run B**, eigen
  inbox-opdracht `2026-09-18-veldapp-ux-run-b-offline-en-herinnering.md`. Meldingen bij afkeuring lopen via de bestaande
  keur-lijn (app én kantoor-keuring).

<!-- toegevoegd 18-09-2026, opdracht "klein-zoekveld-klantenlijst-en-planning-dagkop-sticky" -->
- **Planning — sticky dagkop (Peter 18-09, screenshot: ná verticaal scrollen waren de dagkoppen MA 14-9 … VR 18-9 weg en de
  kolommen onleesbaar; geen migratie; BESLISSINGEN "ZOEKVELD KLANTENLIJST + STICKY DAGKOP PLANNING (Peter 18-09)"):** het
  Personeel-grid én de Transport-dagagenda staan in `.tabel-scroll.sticky-koppen.plan-scroll` — het grid scrolt intern (max-hoogte
  `max(420px, 100vh − 250px)`, zelfde patroon als de klantenlijst/administraties-lijst), de `thead`-cellen (dagen + projectkolom-kop)
  plakken bovenaan mét dekkende achtergrond (`--panel`, vandaag-tint blijft) en onderrand/schaduw zodat kaartjes er niet doorheen
  schijnen; rij-koppen in de `tbody` zijn door hun rij begrensd en bewegen niet. Guard `planning/stickyDagkop.test.ts` (bron + CSS);
  Playwright staat niet in de repo → kliktest in het rapport. Het patroon is de bouwsteen voor de v3-dagkop (planning dag-eerst).

<!-- toegevoegd 18-09-2026, opdracht "planning-v3-dag-eerst-bouw" — BACKEND-deel (4B); frontend-deel volgt uit 4F -->
- **Planning v3 "dag-eerst" — datalaag en bulkroute (mockup `planning-v3-dag-eerst.html` AKKOORD Peter 18-09; migratie 0161;
  BESLISSINGEN "PLANNING V3 — DAG-EERST (Peter 18-09)"):** (1) **`boekhouding.planning_reservering`** = kaart zonder ploeg (project ×
  dag, UNIQUE per administratie; RLS FORCE zoals planning_toewijzing, DELETE toegestaan): een projecttegel naar een dag slepen
  reserveert "hier werken we die dag" vóór de ploeg bekend is; komt er een persoon op, dan blijft de rij als drager staan en toont de UI
  één kaart (ontdubbelen op project × datum); verwijderen is expliciet + geaudit (`planning_gereserveerd` / `planning_reservering_verwijderd`).
  Routes `POST /uren/kantoor/planning/reservering` (201 nieuw / 200 bestaand) en `…/reservering/verwijderen` (204). (2)
  **`boekhouding.veldwerker_afwezigheid`** = MINIMAAL "op deze dagen niet plannen" ([van, tot] inclusief, reden vrije tekst; RLS FORCE,
  géén DELETE-grant): geen verlofadministratie, geen saldo, geen goedkeuring; overlap = 409, beëindigen = `tot` vervroegen +
  `beeindigd_op` (audit oud→nieuw), verlengen = nieuwe periode; alleen ZZP'er/uitvoerder; recht 'Meerwerk & urenstaten' ÓF
  'veldwerkerbeheer' + scope (`GET/POST /uren/kantoor/afwezigheid`, `…/afwezigheid/beeindigen`). In de planning: `pool[].afwezig_tot`,
  `PlanningWeekDto.afwezigheid`, plannen op zo'n dag = conflict `afwezig` (oranje, NIET blokkerend). (3) **Bulkroute**
  `POST /uren/kantoor/planning/bulk` (`bron` vulhandvat | ploeg | ongedaan; `items` ≤ 200; `verwijderen`; `correlatie_id`) = vulhandvat,
  ploeg-paneel en "Ongedaan maken" in ÉÉN transactie via de gedeelde helpers `_plan_in_sessie`/`_verwijder_in_sessie` (dezelfde audit per
  (persoon, dag), `achteraf`-vlag, weekstaat-koppeling en melding-rij per veldwerker × week als de losse routes): per item `gedaan` |
  `overgeslagen` (bestond al / stond niet gepland / dubbel in de aanroep — idempotent) | `conflict` (`project` = die dag al elders gepland
  mét projectnaam, `afwezig`) — een conflict wordt WÉL gepland en gemarkeerd (kantoor beslist); een échte fout (onbekend/inactief project,
  niet-planbare persoon, geen opt-in, geen recht) rolt alles terug. `aangemaakt` = de daadwerkelijk geplaatste (of verwijderde) items —
  ongedaan maken = exact die set terug met `verwijderen: true`. Audit: `planning_gepland`/`planning_verwijderd` mét `bulk_correlatie_id` +
  `bron` (+ `conflict`), plus één rij `planning_bulk` mét tellers. Set-based (leeswerk onafhankelijk van het aantal items; guard in
  `tests/uren/test_planning_v3_18_09.py`). Élke POST onder `/uren/kantoor/…` draagt `?administratie_id=` als query-param (scope-poort,
  bestaand patroon). Dagdeel blijft `heel`/`half`.

<!-- toegevoegd 18-09-2026, opdracht "planning-v3-dag-eerst-bouw" — FRONTEND-deel (4F); het backend-deel (bulkroute, tabellen, RLS) staat in regels_4B -->
- **Planning personeel v3 — DAG-EERST, frontend (Peter 18-09 letterlijk: "Projecten mag hier weg, dat moet hetzelfde zijn als
  transport: dat wij projecten kunnen slepen naar de verschillende dagen in de week", "makkelijke manier om dat project over de hele
  week te slepen (vergelijkbaar met Excel cellen slepen)", "klik op dat project, dan wil ik de hele lijst met ZZP'ers om te selecteren
  wie er die dag ingepland worden … slepen de ZZP'ers ook mee"; mockup `mockup/planning-v3-dag-eerst.html` = bouwnorm incl. notities
  ①–⑨ en de twee beslispunten (kaart zonder ploeg = JA "gereserveerd"; vulhandvat over de weekgrens = NEE); migratie 0161;
  BESLISSINGEN "PLANNING V3 — DAG-EERST (Peter 18-09)"):** de Personeel-tab is een DAG-EERST-grid (`planning/DagEerstGrid.tsx`,
  pure transformatie in `planning/dagEerst.ts`): vijf dagkolommen ma–vr (za/zo alleen als er iets op staat, inklapbaar), sticky dagkop
  mét datum en dagtotaal ("12 man · 3 projecten" — hergebruik `.tabel-scroll.sticky-koppen.plan-scroll`), per dag ÉÉN kaart per
  project mét ploeg-initialen (uitvoerder = `--ok`-rand, conflict = `--warn`-rand, ½ = halve dag), aantal, urenstatus-stip op
  kaartniveau = de LAAGSTE status van de ploeg (vraag < geen < ingevuld < gekeurd; tooltip per persoon; klik = weekstaat), geldende
  werkopdracht-tekst (dag-override wint), chips "achteraf"/"conflict", ⚠ ná einddatum; een kaart zónder ploeg = "gereserveerd"
  (grijs, dashed; `planning_reservering`) en verdwijnt als aparte kaart zodra er een persoon op staat (frontend ontdubbelt op
  project × datum, de reserveringsrij blijft drager). **Projectbalk** boven het grid (`ProjectBalk.tsx`): álle actieve projecten,
  zoekveld diakriet-loos (`normaliseerTekst` uit `bankZoek.ts`), gepland deze week eerst ("ma–wo · 4 man"), rest mét chip "niet
  gepland", 12 tegels + "+ N" → volledige lijst, horizontaal scrollbaar BINNEN de pagina; tegel slepen naar een dag = reservering,
  klik-alternatief = tegel selecteren en dag aanklikken (DnD is nooit de enige weg). **Slepen** via de gedeelde hook
  `planning/useDagDrop.ts` (uit de Transport-tab geëxtraheerd, gedrag daar ongewijzigd): pool → kaart = toevoegen (`planToewijzing`),
  initiaal → andere kaart = verplaatsen (`verplaatsToewijzing`), mét Alt/Option = kopiëren. **Conflictenbalk** (`ConflictenBalk.tsx`,
  `conflictenVoorWeek`): dubbel op één dag (uit `per_datum`, dus vóór er uren zijn), afwezig, > 5 op één kaart (besluit C), ZZP'er
  zonder dossier (optionele pool-vlag `dossier_onvolledig` — nog niet geleverd door de backend); elk item klikbaar → springt naar de
  kaart en licht 'm op; nooit blokkerend. **Vulhandvat** (mockup ②): kaart selecteren → bolletje rechts (teal = actie) → met de muis
  over de dagen slepen (pointer-events); ghost-kaarten tonen vooraf "kopie · zelfde ploeg" of "kopie · N conflict" (oranje) en
  "overgeslagen — staat hier al" (bestaande kaart van hetzelfde project wordt NOOIT dubbel of vervangen); loslaten = ÉÉN
  `POST /uren/kantoor/planning/bulk` (bron `vulhandvat`), toast onderin "Gekopieerd naar di–vr · 16 persoon-dagen · 1 conflict —
  Ongedaan maken · Toon conflict" (10 s); Ongedaan maken / Cmd/Ctrl-Z = dezelfde bulkroute mét `verwijderen: true` en exact de door
  de server teruggegeven `aangemaakt`-set + correlatie-id; het handvat stopt bij vrijdag (beslispunt ⑥ = nee). **Ploeg kiezen**
  (mockup ③, `PloegPaneel.tsx`): klik op kaart → paneel in de zijkolom (geen modaal; patroon MateriaalstandPaneel), kop project + dag
  + werkopdracht/starttijd ("wijzigen" = bestaande dag-override), zoekveld, volledige lijst mét vinkjes en beschikbaarheid voor DIE dag
  ("vrij" groen · "al op ‹project›" oranje, wél kiesbaar · "afwezig t/m …" grijs, uitgeschakeld), uitvoerder-chip, "Zelfde ploeg als
  ‹vorige werkdag met planning op dit project›", "Toepassen op hele week" (vinkjesstand naar alle werkdagen via de bulkroute, zelfde
  overslaan-regel); Opslaan (N) = diff → één bulk-call (verwijderen + toevoegen); iemand mét ingevulde uren van de planning halen =
  bevestiging mét urenstand ("… heeft 8 u ingevuld op deze dag — toch van de planning halen? De uren blijven staan."). **Toggle "Per
  project"** (mockup ④, `PerProjectWeergave.tsx`): dezelfde respons gedraaid — rij per project mét planning, cel = aantal + status-stip +
  conflict-chip, weekkolom "N mandagen · uren x/y · conflicten" + de weekstaten-link, regel "N actieve projecten zonder planning ·
  tonen"; GEEN bewerkacties — klik op een cel = terug naar "Per dag" mét die kaart geselecteerd; stand per gebruiker in localStorage
  (`planning-weergave`). **Pool**: "N dg" + "· vrij" (0 dagen) of "afwezig t/m …" (niet sleepbaar), filter "alleen vrij", eerste 100 +
  "… N meer". **Afwezigheid** (slice 5, `veldwerkers/AfwezigKaart.tsx` in het dossier-dialoog): lijst, toevoegen (van/tot/reden),
  beëindigen = `tot` vervroegen — nooit verwijderen; plannen op zo'n dag = oranje conflict, niet blokkerend. **Deeplink** `?kaart=
  <project_id>|<datum>` landt op de kaart (selectie + oplichten) — signalen/conflicten linken daarop. Ongewijzigd: `?week=`,
  `?uren=`-filter (nu als KAARTfilter: alleen passende ploegleden blijven), meldingen per veldwerker × week, werkopdracht-popup +
  dag-override (📋 op de kaart/in het paneel), "+ Project aanmaken", "+ ZZP'er"/archiveren, controle-meldingen, Transport- en
  Werkopdrachten-tabs. Guards: `planning/dagEerst.test.ts` (12), `PlanningScreen.test.tsx` (herschreven, 20 — dekking plannen/
  verwijderen/dagdeel/403/409/urenstatus/filters/één request blijft), `veldwerkers/AfwezigKaart.test.tsx` (2), `stickyDagkop.test.ts`
  (drie grids), harnas `harness-planning.html` (+ `?perproject=1`, `?kaart=1`) in de overflow-sweep. `mockup/planning-steigerbouw.html`
  (22-08) = historie ("VERVANGEN door planning-v3-dag-eerst.html (18-09)"; de Transport-tab en werkopdracht-popup erin blijven norm).

<!-- toegevoegd 18-09-2026, opdracht "veldapp-ux-run-b-offline-en-herinnering" (run B, backend) -->
- **Veld-app — UX run B, punt 4 dag-einde herinnering (backend; akkoord Peter 18-09 "alle punten"; migratie 0162 =
  `administratie.uren_herinnering_tijd` TIME NULL, `gebruiker.uren_herinnering_uit`, claim-tabel `boekhouding.uren_herinnering`
  UNIQUE (gebruiker, datum); BESLISSINGEN "VELD-APP — 12 UX-VERBETERINGEN (Peter 18-09)" alinea "Run B"):** motor
  `app/uren/herinnering.py::verstuur_dag_einde_herinneringen` — Cloud Run-job `rlz-uren-herinneringen` (CLI `uren-herinneringen`,
  scheduler elk kwartier 15:00–18:45 ma–vr Europe/Amsterdam, `f3_jobs.sh`); de job toetst zélf per administratie mét opt-in de
  tijd (kolom of default 16:30 `STANDAARD_HERINNERING_TIJD` — geen instelling = default doorlopen, kernprincipe 7) en stopt
  om 19:00; kandidaten = actieve ZZP'ers/uitvoerders (`INVULLER_ROLLEN`, detacheerder nooit) mét scope op zo'n administratie,
  per administratie in haar eigen RLS-scope; overslaan altijd geteld: al uren vandaag (som `weekstaat_dag.uren` > 0 over álle
  opt-in-administraties), opt-out PER GEBRUIKER (beslispunt: niet per toestel), al verzonden (claim vóór verzenden = idempotent),
  stille uren 20:00–08:00, account niet actief, geen kanaal (= claim `geen_kanaal` + de ENIGE harde voorwaarde → LET-OP mét
  deeplink `/veldwerkers`); verzending push-anders-mail (`app/berichten/verzending.py`), tekst "Nog geen uren voor vandaag",
  deep-link `/accordeur?uren=vandaag`, verzendfout = `mislukt` zonder claim (volgende run herkanst, job exit 1). Elke run =
  audit `uren_herinnering_run` (administratie-loos, tellers) → reconciliatie-teller `uren_herinnering` "Uren-herinnering einde
  werkdag (veld-app)" met verwacht/gedaan/overgeslagen per reden (`automatiseringen.py`). Routes: `GET/PUT /uren/zzp/herinnering`
  (eigen opt-out, audit `uren_herinnering_optout`), `GET/PUT /uren/beheer/herinnering-tijd/{aid}` (Beheerder-only, 06:00–18:59 of
  null = default, audit `uren_herinnering_tijd_gewijzigd`). Offline-contract (punt 5): `PUT /uren/zzp/dag` op een bevroren staat
  geeft 409 mét `code: weekstaat_bevroren`, `status` en `server_regel` (uren/m2/opmerking/doorfactureren of null) zodat de app
  beide standen toont. Guards `tests/uren/test_herinnering_18_09.py` (marker `afwezig_pad`), rolpoort-matrix, deploy-guards
  (`rlz-uren-herinneringen` in VERWACHTE_JOBS + MAILENDE_JOBS). Klikpunt Peter: scheduler aanmaken (`scripts/gcp/f3_jobs.sh`
  stap 6 herdraaien of het losse `gcloud scheduler jobs create`-commando uit het rapport).

<!-- toegevoegd 18-09-2026, opdracht "veldapp-ux-run-b-offline-en-herinnering" (run B, frontend-deel) -->
- **Veld-app — run B, frontend (Peter 18-09 "alle punten"; bouwnorm `mockup/uren-uitvoerder-v3.html` schermen ⑤ + ⑥, notities 12–13;
  BESLISSINGEN "VELD-APP — 12 UX-VERBETERINGEN (Peter 18-09)" alinea "Run B"):** (5) **Offline werkt** — een dagregel die niet
  verzonden kan worden (fetch-`TypeError` óf `BackendOnbereikbaarError`) gaat in de lokale wachtrij `frontend/src/uren/urenOffline.ts`
  (IndexedDB `rlz-uren-offline` náást het slot, waarde versleuteld op HETZELFDE anker als het app-slot via
  `appSlot.versleutelAlsSlotActief`; zonder actief slot `plain:`-fallback — dev), blijft zichtbaar mét chip "● nog niet verzonden" op de
  kaart, oranje ● in de dagbalk (lokale uren tellen mee) en een banner "N regels nog niet verzonden" mét "Nu verzenden"; verzenden bij het
  openen van de app, bij `online` en ná elke geslaagde verversing van de weekkaarten (`UrenFlow.syncWachtrij`), geslaagd = weg + toast;
  409 `weekstaat_bevroren` (week intussen ingediend/gekeurd) = conflict-sheet mét beide standen ("Stand van kantoor houden" = regel weg,
  "Mijn regel bewaren tot de week weer open is" = blijft) — nooit stil overschrijven; andere serverfout blijft zichtbaar in de banner;
  **indienen is online-only** en pas als de wachtrij van die week leeg is. "Zelfde als gisteren" loopt door dezelfde `slaDagOp`. Guards
  `uren/urenOffline.test.ts` (6) + `uren/UrenFlow.offline.test.tsx` (4, netwerk-uit/online/409). (4) **Dag-einde herinnering, app-kant**
  — ⚙ Toegang › "Herinneringen" › schakelaar "Herinnering einde werkdag" (`GET/PUT /uren/zzp/herinnering`, opt-out PER GEBRUIKER —
  beslispunt: de herinnering hoort bij de persoon, niet bij één toestel; alleen veldrollen zien de rij, `HerinneringSchakelaar.tsx`);
  kantoor-web Instellingen › administratie › Uren & materiaal › "Herinnering einde werkdag (veld-app)" = tijdveld (`GET/PUT
  /uren/beheer/herinnering-tijd/{aid}`, chip "standaard", "terug naar standaard" = null → 16:30, validatie 06:00–18:59 (server 422; 409 zonder uren-opt-in leesbaar),
  `instellingen/HerinneringTijdRij.tsx`). Motor, job, migratie 0162 en reconciliatie-tellers: blok 5B.

<!-- toegevoegd 21-09-2026, opdracht "planning-conflictenbalk-onleesbaar-oude-week-dubbele-veldwerkers-zonder-handeling" -->
- **Planning — conflictenPANEEL mét handeling + dubbele veldwerkers op harde sleutels (Peter 21-09, Universal /planning: "17
  conflicten deze week — ma 7-9: M. Demir op 25137 Bergeijk én 26082 Eindhoven … ik kan er niet uithalen wat het conflict is";
  migratie 0169 = `boekhouding.planning_conflict_akkoord`; BESLISSINGEN "PLANNING — CONFLICTENPANEEL MÉT HANDELING + DUBBELE
  VELDWERKERS (Peter 21-09)"):** (A) De conflictenbalk (`ConflictenBalk.tsx`, inline `linkbtn`-lap) is VERVANGEN door
  `planning/ConflictenPaneel.tsx`: kop "N conflicten in week 39" — de GETOONDE week; "deze week" alleen als dat de huidige is
  (`conflictWeekLabel`) —, gegroepeerd per dag (`groepeerConflictenPerDag`), per rij persoon · projecten · SOORT ("dubbel gepland" /
  "afwezig" / "> 5 op kaart" / "ZZP'er zonder dossier", `CONFLICT_SOORT_LABEL`) · HANDELING (Kernprincipe 7.2: signalering zonder
  handeling is niet af): dubbel → **"Houd ‹A›"** / **"Houd ‹B›"** (de andere kaart(en) van die persoon-dag weg via de bestaande
  bulkroute `POST /uren/kantoor/planning/bulk` mét `verwijderen: true` en nieuwe bron `conflict` — audit `planning_verwijderd` mét
  `bron`, toast "Ongedaan maken" plaatst exact de verwijderde set terug via bron `ongedaan`) en **"Beide (halve dagen)…"** = bewust
  gehouden mét VERPLICHTE reden (≥ 3 tekens): `POST /uren/kantoor/planning/conflict-akkoord` (`planning.bevestig_conflict`) zet álle
  kaartjes van die persoon × dag op dagdeel `half` (audit `planning_dagdeel_gezet` mét `bron: conflict_akkoord`) en schrijft een rij
  `planning_conflict_akkoord` mét de planningsstand (`project_ids` = gesorteerde project-id's als tekst) + reden + audit
  `planning_conflict_akkoord`; afwezig → **"Van planning halen"** (bulkroute) / **"Tóch plannen…"** (akkoord soort `afwezig`, geen
  dagdeel-wijziging); > 5 → **"Ploeg aanpassen"** (kaart + paneel); dossier → **"Dossier openen →"** (`/veldwerkers`); élke rij
  óók "Toon in grid". **De rij verdwijnt tot de planning wijzigt:** `zonderAkkoord` verbergt een dubbel-/afwezig-conflict alleen zolang
  de huidige stand (gesorteerde project-id's van persoon × dag) exact gelijk is aan `project_ids` van een akkoord van dezelfde soort;
  een extra of verdwenen kaart maakt het conflict weer zichtbaar. Akkoorden zijn idempotent op dezelfde stand (zelfde rij terug),
  nooit DELETE (RLS FORCE, grants zonder DELETE), 404 zonder planning die dag, 422 zonder dubbel bij soort `dubbel`; `PlanningWeekDto`
  draagt `conflict_akkoorden`. Ingeklapt 3 rijen, "Alle N tonen" = tabel — altijd in `.tabel-scroll` (óók ingeklapt; sweep 768 px
  liep op de acties-kolom), nooit een inline lap tekst. Nooit blokkerend — kantoor beslist. (B) **Alleen huidige + toekomstige
  dagen tellen als conflict** (`conflictenVanaf(conflicten, vandaag)`): een conflict op een verstreken dag is geen planningsconflict
  maar historie (hoogstens een urenstaat-toets) — het paneel meldt "N op verstreken dagen niet getoond (zie Per project)";
  kaart-chips en de "Per project"-weergave tonen álle conflicten onverkort. **Waarom het grid op week 37 stond:** géén bug in de
  weekkeuze — `?week=` is een bewuste deeplink (planning-signaal "geplande week zonder weekstaat", projectdetail) en de URL draagt
  de week; alleen de balk-tekst "deze week" was fout. De subkop draagt nu een weekchip **"verstreken week" / "lopende week"**
  (`weekStand`, data-testid `week-stand`) zodat een oude week nooit voor de huidige doorgaat; de laatst bekeken week wordt NIET
  onthouden buiten de URL. (C) **Dubbele veldwerkers — alleen HARDE sleutels, nooit naamgelijkenis of planningspatroon (correctie
  Peter 21-09: "V. Ponchev"/"Z.V. Panchev" en "M. Demir"/"R. Demir" zijn broers die als ploeg samen gepland staan; Cowork las
  "zelfde projecten, zelfde dagen" verkeerd als dubbele records):** lees-only CLI `veldwerkers-dubbelen (--administratie X |
  --alles)` (`app/uren/dubbelen.py` + `dubbelen_cli.py`) — per administratie de veldwerkers mét scope (ZZP'er/uitvoerder/
  detacheerder), sleutels KvK (`veldwerker_dossier.kvk_nummer`), IBAN (via `veldwerker_crediteur.vendor_id` → `leverancier_iban`,
  genormaliseerd) en e-mail (`gebruiker.e_mail`, lower/trim — de kolom is uniek, dus in de praktijk 0; de toets staat er voor het
  geval een import of pseudonimisering dat doorbreekt); telefoon = "niet toetsbaar" (geen veld op `platform.gebruiker`) en wordt
  als zodanig gemeld; ≥ 2 personen mét dezelfde waarde = KANDIDAAT (beoordelen), nooit samenvoegen, géén UI-chip; guard-test
  `test_puur_alleen_harde_sleutels_nooit_naam` (broers = 0, identieke naam mét eigen sleutels = 0). In de nameting-allowlist en als
  dispatch-onderdeel `veldwerkers-dubbelen` in `nameting.yml` (meetrecept: TOTAAL-regel mét 0 fouten; Universal verwacht 0 clusters).
  (D) Guards: `tests/uren/test_planning_conflicten_21_09.py` (halve dagen + akkoord + idempotent + nieuwe stand = nieuwe rij +
  historie blijft, afwezig-pad, 404/422, route rolpoort/scope/200/422, "Houd" via bulk bron `conflict` + ongedaan, dubbelen puur/
  normalisatie/DB-rapport/CLI lees-only), `planning/dagEerst.test.ts` (paneel vanaf vandaag + groepering + weeklabel; akkoord
  verbergt alleen bij exact dezelfde stand), `PlanningScreen.test.tsx` (paneel-rij mét handelingen, Houd → bulk `conflict`
  `verwijderen` + ongedaan = zelfde set, Beide → akkoord mét reden + rij weg, verstreken dag = tekstregel + weekchip "lopende week",
  deeplink oude week = "verstreken week"; vaste `Date` via `vi.useFakeTimers({ toFake: ['Date'] })`), rolpoort-matrix, workflow-
  guard `test_onderdeel_veldwerkers_dubbelen_alleen_op_verzoek_en_lees_only`; harnas `harness-planning.html` mét vaste "vandaag"
  (di 15-9-2026) in de overflow-sweep (24/24). Mockup `planning-v3-dag-eerst.html` notitie "Conflictenbalk" + balk-voorbeeld 1-op-1
  bijgewerkt (UX-review: zelfde plek boven het grid, geen nieuwe route of tegel — past in de IA).

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Kantoor-signaal "geplande week zonder weekstaat" (CLAUDE.md `ed6d176` r. 675–682)

- **Kantoor-signaal "geplande week zonder weekstaat" (mini-run 06-09 blok A, migratie 0115 — BESLISSINGEN
  "PLANNING-SIGNAAL 'GEPLANDE WEEK ZONDER WEEKSTAAT'"):** `app/uren/planning_signaal.py` — deterministisch per
  (veldwerker, project, ISO-week): gepland (`planning_toewijzing`) én ouder dan het veld-app-venster
  (`overzichten.OPEN_WEKEN_VENSTER`, één bron) én geen weekstaat óf alleen concept/corrigeren → kantoorbrede lijst
  `/meerwerk/planning-signalen` (inzicht-lijstpatroon, module-recht + scope) mét per rij "Herinnering sturen"
  (push-anders-mail, max 1/dag, dagrij-claim; de herinnerde week komt in de veld-app terug tot ingediend) of "Afmelden…"
  mét reden (`boekhouding.planning_signaal_afhandeling`, audit); KPI-kaart + klantenlijst-kolom "Weekstaten ontbreken"
  (`planning_signalen`, alleen > 0). Geen blokkade.

### Domeinbeslissingen — Uren & meerwerk (steigerbouw-tak: weekstaten, factuurmatch, dossier, geofence, prijsafspraken, planning, transport, werkopdrachten, veldwerkerbeheer) (CLAUDE.md `ed6d176` r. 1130–1324)

- **Uren & meerwerk (steigerbouw-tak — ontwerpronde + BOUW GO Peter 2026-08-21):**
  het fase-4-item "urenportaal ZZP'ers" is naar voren getrokken; twee mockups definitief
  goedgekeurd: `mockup/uren-uitvoerder.html` (veldkant, zelfde native app als de accordeur,
  drie rollen) + `mockup/meerwerk-kantoor.html` (kantoorkant, stijl kantoor-modern) — UX
  ligt vast, 1-op-1 voortbouwen. Scope: steigerbouw-specifiek, **opt-in per administratie**
  (alleen Universal initieel); onderdeel van de projectadministratie maar **niet leidend**
  ervoor — de generieke projectenmodule blijft eigen ontwerp en wordt alleen gevoed
  (m²-voortgang, meerwerklijst, getekende urenstaten). **Datamodel-besluit (21-08):
  WEEKSTAAT PER PROJECT** — één staat per persoon per project per week; zelfde dag op twee
  projecten = twee staten. Rollen in de bestaande native app: **ZZP'er** (weekstaat per
  project — uren + optionele m² per dag, indienen per week, deadline ma 09:00),
  **uitvoerder** (specs/contract alleen-lezen mét prijzen, meerwerk melden zonder prijzen,
  **HYBRIDE keuring op WEEKNIVEAU (aanvulling Peter 22-08, migratie 0059)** — week akkoord
  óf week afkeuren met verplichte reden, hele week terug naar "corrigeren", ZZP'er dient de
  wéék opnieuw in; bij afkeuren kan de keurder per dag een CORRECTIEVOORSTEL meegeven
  (uren/m²/opmerking) dat de ZZP'er letterlijk in zijn corrigeer-scherm ziet — de keurder
  wijzigt nooit zelf andermans uren; geen dag-keuring, dagen alleen ter controle. Elke
  afkeuring mét voorstel wordt geregistreerd (`weekstaat_correctie`: ingediend vs.
  voorgesteld/goedgekeurd, optelbaar per veldwerker, alléén zichtbaar voor kantoor —
  het goedgekeurde totaal blijft de toetsbron voor de factuurmatch) en **detacheerder** (besluit 21-08, vervángt de 17-08-rollen
  teamleider/manager: vult weekstaten in namens door kantoor gekoppelde ZZP'ers, exact
  dezelfde schermen/velden, geen projectinhoud — per project alleen nummer + plaats; elk
  namens-scherm draagt "· namens <ZZP'er>", elke invoer vastgelegd als "ingevuld door X
  namens Y", audit + zichtbaar bij de keuring). Kantoor beheert keurders per
  uitvoerder↔project én detacheerder↔zzp'er (Beheerder-only, audit). Goedgekeurde staat =
  getekende urenstaat, onmuteerbaar (wijzigen alleen via nieuwe afkeuring) = basis
  factuurmatch. **Factuurmatch: verkenning + fasering AKKOORD (Peter 2026-08-21, vier
  richtingbesluiten — BESLISSINGEN "FACTUURMATCH ZZP-/BUREAUFACTUREN" is canoniek):**
  (1) bureau-tarief per detacheerder↔zzp'er-koppeling = hoofdmechanisme (bureaufactuur =
  som van uren × tarief per ZZP'er; ontbrekend tarief = match alleen op uren, oranje "geen
  tarief bekend", geen blokkade; los ZZP-tarief op de veldwerker↔crediteur-koppeling);
  (2) boeken bij afwijking mág mét expliciete bevestiging ("geboekt ondanks
  match-afwijking", tijdlijn + audit), autoboek-slot strikt groen incl. bedrag;
  (3) afwijking = vlag + eigen teller/chip (duplicaat-patroon), geen enum-status;
  (4) autoboek-opt-in per veldwerker-koppeling (default UIT). **Fase 1 GEBOUWD + GETEST
  (2026-08-21, migratie 0057)**: veldwerker_crediteur + bureau-tarieven + factuurmatch(-staat)
  + weekstaat-verrekening (dubbeltelling-preventie) + deterministische motor
  `app/uren/factuurmatch.py`. **Fase 2 pipeline-integratie GEBOUWD + GETEST (2026-08-21,
  migratie 0058 — BESLISSINGEN "Fase 2" is canoniek)**: match-run ná
  extractie/voorstel-opslag/staat-goedkeuring + herbereken-endpoint met staten-selectie
  (altijd systeem-actor — RLS bureau-tarieven), boeken-mét-expliciete-bevestiging ("geboekt
  ondanks match-afwijking" in tijdlijn + audit; bevestiging persistent op de match-rij,
  herberekening wist 'm; zelfde poort bij ter-accordering-aanbieden), staten-verrekening ín
  de boek-transactie + afkeur-blokkade op verrekende weken, werkvoorraad-teller/chip/banner
  (duplicaat-patroon), concept-mail aan de veldwerker (mens bewerkt + verstuurt expliciet,
  nooit auto) én weigering van de oude leverancier-autoboek-opt-in voor gekoppelde
  crediteuren (runtime-vangnet + 409 bij aanzetten). **Fase 3 kantoor-UI GEBOUWD + GETEST
  (2026-08-22 — BESLISSINGEN "Fase 3" is canoniek)**: veldwerkers-paneel met
  crediteur-koppeling + ZZP-uurtarief + bureau-tarief per detacheerder↔zzp'er
  (Beheerder-only endpoints, geaudit) én de match-sectie op het controlescherm
  (uitkomst-chip, verschil-per-week-uitsplitsing, periode-keuze/herberekenen met
  weekstaat-selectie via de kandidaat-staten-leesroute, concept-mail-paneel);
  mockup meerwerk-kantoor.html mee bijgewerkt. **Fase 4 autoboek-slot GEBOUWD + GETEST
  (2026-08-22, geen migratie — kolom 0057): opt-in per veldwerker-koppeling (Beheerder-only
  endpoint + switch in de crediteur/tarief-modal, ⚡-badge), slot uitsluitend groen bij
  match-uitkomst `match` (bedrag getoetst — tarief verplicht) mét ≥ 1 getekende staat,
  bovenop álle bestaande inkoop-autoboekpoorten (app-bevestigd geheugen, harde checks,
  duplicaat/vraag, volumerem, accorderingspoort); bron `veldwerker_opt_in` in tijdlijn +
  audit; twee triggers (ná extractie én ná weekstaat-goedkeuring die de match groen maakt);
  staat overal UIT — activeren per koppeling is klikwerk Peter.**
  **ZZP-dossier + handhaving + KvK (steigerbouw-run 25-08 blok A, besluiten Peter 23/24-08,
  GEBOUWD + GETEST 2026-08-25, migratie 0072 — BESLISSINGEN "STEIGERBOUW-RUN 25-08 — BLOK A"
  is canoniek):** per veldwerker (ZZP'er/uitvoerder) × administratie een dossier met
  Beheerder-instelbare documenttypen (default kopie ID/steigerpas/VCA vol/AVB/KvK-uittreksel;
  virtueel tot de eerste PUT), statusmodel ontbreekt → ter controle (upload kantoor óf app, ook
  detacheerder namens) → goedgekeurd/afgewezen-met-reden, verlopen + 30-dagen-vooraankondiging;
  kopie ID volgt de BSN-regel (nooit extraheren/indexeren, gemaskeerde weergave, élke inzage
  geauditeerd). Handhaving: herinner-knop (push-anders-mail, max 1/dag, "N van 3"); ná de 3e
  herinnering blokkeert weekstaat-INDIENEN (HTTP 423, óók namens) — dagen zetten blijft mogelijk,
  deblokkade zodra alles geüpload is (ter controle telt), afwijzing heractiveert, teller-reset
  pas bij volledig goedgekeurd. KvK-lookup = eigen kopie Vastly-patroon (`app/integraties/
  kvk.py`, testomgeving default, `KVK_API_KEY`/`KVK_BASE_URL` productie), mens bevestigt.
  Daarnaast: veldwerker aanmaken zónder mail (`uitnodiging_later`), Beheerder-only e-mail
  wijzigen (`PATCH /auth/gebruikers/{id}/e-mail`, verse uitnodiging bij niet-geactiveerd) en het
  signaal > N uur per dag (`administratie.uren_dagmax_uren`, default 12 — som over álle
  weekstaten per kalenderdag, oranje vlag, geen blokkade). **Seam-eis steigerbouw-run: nieuwe
  module-code roept nooit RlzClient aan; adapter-grepen per blok in BESLISSINGEN "ODOO-ADAPTER
  — GREPEN"; de Odoo-feiten voor de adapter staan in `verkenning/odoo-verkenning.md` (STAP-0 02-09).**
  **Geofence-stempels BASIS (bouwrun 28-08 blok C, mockup `geofence-stempels.html`, migratie 0085;
  jurist akkoord 28-08 — regeling in de voorwaarden/privacyverklaring alinea 4, tekstversie
  `2026-08-28-v2`, géén apart instemmingsscherm):** projectzone op de projectspecs (adres + lat/lon +
  straal; geen zone = geen stempels), `boekhouding.werkstempel` APPEND-ONLY met fail-closed intake
  `POST /uren/stempels` (alleen de veldwerker zelf, nooit namens; alleen projecten mét zone in
  scope), eigen stempels in de veld-app, keuringskolom "gestempeld aanwezig" (Σ in/uit-paren,
  onvolledig paar sluit op middernacht mét markering, > 1,0 u afwijking = oranje vlag — nooit
  korting; geen stempels = toets zwijgt). **Native achtergrondlocatie: GEBOUWD OP
  BRANCH `feat/geofence-native` (29-08) — NIET gemerged, NIET releasen:** iOS CLLocationManager-
  regiobewaking + Android GeofencingClient, zones uit de weekplanning (`GET /uren/stempels/zones`,
  max 20), éénmalige OS-permissiestap, buffer + nazenden via `POST /uren/stempels` bij app-opening;
  kabeltest-draaiboek `native/GEOFENCE_KABELTEST.md` (branch). Xcode Cloud bouwt vanaf main; de
  `ACCESS_BACKGROUND_LOCATION`-guard in `bouw_android_release.sh` blijft op main; store-motivering +
  release = versie 1.1 ná de eerste store-goedkeuring. BESLISSINGEN "BOUWRUN 28-08 AVOND" blok C +
  "OPDRACHT 29-08" blok C.
  **Prijsafspraken per project × veldwerker (steigerbouw-run 25-08 blok B1, GEBOUWD + GETEST
  2026-08-25, migratie 0073 — BESLISSINGEN "STEIGERBOUW-RUN 25-08 — BLOK B" is canoniek):**
  tarief mét eenheid uur óf m² + ISO-week-venster, append-only (intrekken met reden), overlap
  geweigerd; factuurmatch-tariefresolutie per weekstaat: projectafspraak wint → koppeling-tarief →
  onbepaalbaar (nooit gokken), m² rekent met goedgekeurde weekstaat-m², geldt óók voor
  bureaufacturen; de match-sectie toont altijd de tariefbron. Weeknummers in alle steigerbouw-
  datumweergaves (B2, `datumMetWeek`).
  **Slimme landing + Planning-menu (steigerbouw-run 25-08 blok C, GEBOUWD 2026-08-25 —
  BESLISSINGEN "BLOK C"):** `GET /uren/kantoor/mijn-toegang` voedt `useMijnToegang`; een
  mono-klant-medewerker (één administratie in scope, geen Beheerder) landt op zijn klantpagina,
  mét module-recht + opt-in op `/meerwerk?administratie=X`; fail-closed = werkvoorraad. Planning
  als zijbalk-item bij module-recht + opt-in. **Koude start rlz-backend ≈ 15 s (gemeten 25-08) → WARME START aangezet (besluit Peter 25-08,
  uitgevoerd 26-08): `--min-instances 1` request-based verankerd in deploy.yml, ≈ € 7/mnd — rapport
  + verificatie in `docs/COLD_START_ONDERZOEK_25-08.md`; alleen de service, jobs ongemoeid.**
  **Transportplanning + bestellingen + materiaalstand (steigerbouw-run 25-08 blok D, besluiten
  Peter 24-08, GEBOUWD + GETEST 2026-08-25, migratie 0074 — BESLISSINGEN "BLOK D" is canoniek;
  mockup planning-steigerbouw Transport-tab + popup = norm):** `app/materiaal/` — catalogus per
  leverancier (seed uit de bestellijst-xlsx, m² = Σ(aantal × lengte)/4,6), bestellingen mét
  append-only revisies (PDF-bon per mail via het bestaande SMTP-kanaal, update-mail = alleen
  gewijzigde regels oud→nieuw, mailfout = geen revisie), transport levering/retour per project ×
  dag (**seam `zet_transport_status(bron=)`** voor het
  latere verhuursysteem/veld-aftekening), materiaalstand + huurperiode per item, wachtrisico-
  kruissignaal op beide planning-tabs, materiaalmatch (D6: verhuur-crediteur vs aantal ×
  huurperiode; zelfde vlag-patroon + boekpoort als de urenmatch; m²-toetsbron in de keuring).
  Nieuwe module-code roept nergens RlzClient aan (seam-eis).
  **Transport v2 = DAG-AGENDA + statusflow-her-enum (opdracht 31-08, mockup
  `planning-werkopdracht-transport.html` = norm, migratie 0091 — BESLISSINGEN
  "PLANNING-UITBREIDING 31-08" is canoniek):** de Transport-tab is een dag-agenda zónder
  projectrijen (kaart = projectnr + klant + adres uit de specs + ▲/▼ + materiaal + voertuig +
  planner + status; sleepbaar tussen dagen mét klik-alternatief; werkbakje: zoek → chip → sleep
  of klik-klik; signaalkaart "nog te plannen" bij een verstuurde bestelling zonder
  transportregel). **Status: gereserveerd (rood, uit het werkbakje) → bevestigd (oranje,
  VERPLICHTE voertuigtoezegging combi/voorwagen + mail aan het TRANSPORT-CONTACT) → definitief
  (groen, materiaallijst + transportplanner + volledige lijst aan het MATERIAAL-CONTACT) →
  geleverd (grijs); wijzigen ná definitief = delta-mail (alleen oud→nieuw); dag verschuiven =
  terug naar gereserveerd (voertuig vervalt, lijst blijft); álle mails mail-first (mailfout =
  502, geen stille wijziging); legacy 'gepland' gedraagt zich als gereserveerd
  (`effectieve_status` — migratie puur DDL).** Leverancier draagt twee contactpersonen
  (transport-/materiaal-contact, leverancierbeheer); leverancier-/catalogusbeheer sinds 31-08
  voor Beheerder ÓF B+P (`require_beheerder_of_bp`).
  **Werkopdrachten per project × periode (31-08, zelfde mockup/migratie):** `app/uren/
  werkopdracht.py` — APPEND-ONLY (groep_id + versies, DB-grant zonder UPDATE/DELETE; historie
  in de popup), meerdere/overlappende per project, dag-override sparse (alleen die dag wint);
  paarse chip + ⊕ per projectrij op de Personeel-tab, override via de dagcel; de veld-app toont
  de geldende tekst alleen-lezen per geplande dag — bewust GEEN push bij tekstwijziging.
  **Fijnmazig recht "veldwerkerbeheer" (31-08, 0019-patroon, eigen module-sleutel
  `boekhouding.veldwerkerbeheer` — PK-les: één gebruiker draagt meerwerk- én dit recht):**
  B+P mét het recht mag UITSLUITEND veldwerkers aanmaken (incl. uitnodiging_later) en
  archiveren binnen de eigen scope (zelf-gepoorte SECURITY DEFINER-scope-toets
  `platform.veldwerker_scope_binnen_actor`, fail-closed) — nooit kantoorrollen of rol-/
  scope-mutaties; toekennen Beheerder-only (/gebruikers-switch); ingang "+ ZZP'er"/🗑 in de
  planning-zijbalk; "+ Project aanmaken" terug op /planning (B+P, bestaande projectmotor).
  NB de module-recht-houderslijst leest sinds 31-08 mét actor (RLS-leesbug /gebruikers:
  actor-loze sessie zag stil nul rijen — kolom toonde overal "uit").
  **Planning-agenda steigerbouw (ontwerpronde v2 + BOUW akkoord Peter 22-08, mockup
  `planning-steigerbouw.html` = norm; GEBOUWD + GETEST 2026-08-22, migratie 0060 —
  BESLISSINGEN "PLANNING-AGENDA STEIGERBOUW" is canoniek):** kantoor plant ZZP'ers/
  uitvoerders per dag op ACTIEVE projecten (weekgrid `/planning`, sleepbare kaartjes,
  dagdeel heel/half; ingang op de klantpagina). Harde failsafe = samengestelde PK
  persoon×project×dag; besluit A: plannen maakt de projectkoppeling automatisch aan
  (geaudit, bron 'planning'); besluit B: veldwerker ziet de eigen planning ALLEEN-LEZEN in
  de app (tab "📅 Planning", ook detacheerder-namens; geen veld-mutatiepad); besluit C:
  > 5 geplande dagen p.p./week = zacht signaal. Planning = TOETSBRON weekstaten: uren
  buiten planning = oranje `buiten_planning`-vlag bij de keuring (geen blokkade); dubbele
  dag zonder dekking = interne melding + 30-dagen-teller per ZZP'er, uitsluitend kantoor.
  Toegang onder module-recht "Meerwerk & urenstaten" + uren-&-meerwerk-opt-in.
  **Jaaragenda + bruikbaarheids-fixes (besluiten Peter 22-08, GEBOUWD + GETEST zelfde dag —
  geen migratie):** vrij vooruit plannen onbegrensd (géén week-kopieerknop — het hele jaar
  wordt vooruit gevuld; project-einddatum = zacht oranje signaal, geen blokkade), week in de
  URL (`?week=2026-W41`) mét weekkiezer, drag & drop gerepareerd + volwaardig klik-alternatief
  (cel aanklikken → persoon kiezen), opmaak conform de bijgewerkte mockup.
  **Grid v3 (besluit Peter 23-08, GEBOUWD + GETEST zelfde dag — vervángt het 22-08-grid-filter
  "alleen projecten mét planning + zoekrij", dat gaf een leeg grid waarin je niet kon
  beginnen):** het weekgrid toont ÁLLE actieve projecten in twee blokken — mét planning
  bovenaan (volle rijen), de rest compact onder een scheidingskop, direct beplanbaar via klik
  én drag & drop — mét live filterveld + telling "N actieve projecten · M mét planning"; de
  "+ project toevoegen"-rij en het endpoint `/uren/kantoor/planning/projecten` zijn VERVALLEN,
  de planning-GET levert alles (incl. specs-metadata, gebatcht) in één request — vlot bij 68
  actieve projecten (Universal). Veld-app-planningtab ongewijzigd. BESLISSINGEN
  "PLANNING-AGENDA" (rij GRID V3) is canoniek.
  **Detacheerder-filters veld-app — planning stuurt wat je ziet (opdracht Peter 04-09 blok A +
  addendum C, GEBOUWD + GETEST 04-09, geen migratie — BESLISSINGEN "DETACHEERDER-FILTERS VELD-APP"
  is canoniek):** de ZZP-/namens-flow is WEEK-EERST: mijn weken (huidige week + weken mét planning in
  het 6-weken-venster + élke week met een staat in concept/corrigeren) → projecten in die week (alleen
  waar ingepland, plus projecten met een bestaande staat) → weekstaat; uitwijk "+ ander project" =
  volledige doorzoekbare lijst actieve projecten, de `buiten_planning`-vlag vangt die uren bij de
  keuring. Werklijst detacheerder = alleen ZZP'ers mét een handeling (`te_doen`), niets = "✓ Alles is
  bij" + ↻, wie bij is onder "Ook zonder werk". **Projecttoegang is volledig planning-gestuurd:** de
  koppeling `uren_project_toewijzing` ontstaat uitsluitend automatisch via één helper
  `service.zorg_voor_projectkoppeling(bron=)` — bij plannen ('planning') én bij de eerste dagregel op
  een ongekoppeld actief project ('weekstaat'); de handmatige koppelroute/-UI is vervallen, bestaande
  koppelingen blijven staan, het veldwerkers-paneel toont "actief op N projecten (via planning)"
  alleen-lezen mét herkomst. Filtergedrag, geen rechtenwijziging: scope + koppeltabel + RLS ongewijzigd.
  Mockup `uren-uitvoerder.html` 1-op-1 mee bijgewerkt.
  Meerwerk-kantoorkant: gemeld → goedgekeurd-nog-doorbelasten → doorbelast/afgewezen(eigen
  rekening, verplichte reden); contract-toets stelt prijs voor uit de offerte-staffel, mens
  bevestigt (nooit auto-boeken); goedgekeurd + 2 weken niet op een verkoopfactuur =
  werkvoorraad-signaal (sluit aan op de item-niveau-doorbelastingscontrole); omschrijvingen
  altijd voluit. Toegang: één module-recht "Meerwerk & urenstaten" per kantoormedewerker
  (0019-patroon, Beheerder-only, audit, server-side incl. menu/standen/zoeken/API;
  klantscope blijft eronder gelden). Bouwstatus: zie BESLISSINGEN "Ontwerpronde uren &
  uitvoerder + meerwerk-kantoor" + "UREN & MEERWERK — BOUW".
