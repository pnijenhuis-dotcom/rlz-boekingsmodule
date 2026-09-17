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
