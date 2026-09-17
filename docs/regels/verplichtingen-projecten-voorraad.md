# Regels — Verplichtingen/offertes, projecten, projectverdeling, contract-ontleding en voorraad

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Documenttype `verplichting` + factuur↔offerte-match (nooit blokkerend), projectenmodule en projectcode-generatie, Inzicht › Projecten/Projectverdeling, pro rato, contract-ontleding auto-first, mini-voorraad en voorraad-aansluiting (mi-schema, nooit RLZ-writes).

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Hercontrole projectverdeling (blok 10; migratie 0124):** lege omzetstand = bevinding "omzetcijfers ontbreken" mét actie cijfers-sync, geen signaal onder de drempel, hercontrole alleen ná afsluiting van de referentiemaand — zie BESLISSINGEN "HERCONTROLE PROJECTVERDELING — VALSE SIGNALEN, CADANS, BEVINDING".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verplichtingen — offerte-accordering + factuur↔offerte-match** (documenttype `verplichting`, géén RLZ-/Odoo-boeking,
  deterministische match-motor `app/verplichting/match.py`, nooit blokkade; migratie 0110) — zie BESLISSINGEN
  "VERPLICHTINGEN + FACTUUR↔OFFERTE-MATCH 04-09", mockup `offerte-matching.html`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Offerte-match — wachtende verplichting zichtbaar, termijnen, achteraf koppelen (Peter 15-09, casus Olieman 32948; geen migratie):** een verplichting van de leverancier die nog niet goedgekeurd is (of op een ander crediteurrecord met dezelfde naam staat) geeft geen stil `geen_verplichting` meer maar `niet_toetsbaar` mét reden + verwijzing ("Open de verplichting →", "Koppel offerte…", nooit blokkerend); melding/DTO dragen het termijnnummer ("1e termijn € 20.000 van € 85.000"); bij goedkeuring worden open én GEBOEKTE facturen van de crediteur alsnog gematcht en een geboekte factuur achteraf verrekend (tijdlijn "achteraf gekoppeld aan offerte …", audit `verplichting_achteraf_gekoppeld`) — zie BESLISSINGEN "OFFERTE-MATCH — WACHTENDE VERPLICHTING ZICHTBAAR, TERMIJNEN, ACHTERAF KOPPELEN (Peter 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verplichting — projectveld: lege stand zichtbaar + projectcode (Peter 16-09, casus Offerte S00642 Bouwadvies Oost Nederland; geen migratie):** combobox app-breed leeg ≠ laden ≠ fout (eigen blok buiten de gevirtualiseerde 0-px-container, props `laden`/`laadFout`/`onOpnieuw`), alle hook-aanroepers geven laden/fout door, lege projectlijst = "Geen projecten in deze administratie — Project aanmaken →" + voetoptie "+ Nieuw project…", projectcode = cijfer-prefix van de RLZ-naam (RLZ heeft géén codeveld, STAP-0 16-09), inactief zichtbaar onderaan mét chip — zie BESLISSINGEN "VERPLICHTING — PROJECTVELD: LEGE STAND ZICHTBAAR + PROJECTCODE (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Mini-voorraad speciale producten** (mi-schema, stand = Σ append-only mutaties, MENS-MANIPULATIE ONMOGELIJK;
  migratie 0116) — zie BESLISSINGEN "MINI-VOORRAAD SPECIALE PRODUCTEN" (+ "— FRONTEND").

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Inzicht › Projectverdeling** (`/projectverdeling`, `document/HerverdeelDialoog.tsx`) en **Catalogus-leesroute
  smal** (`require_catalogus_lezer`) — zie BESLISSINGEN "MINI-RUN 06-09 — OVERZICHT" blokken B en C.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Pro-rato-periode "heel jaar" (D4 07-09; migratie 0119):** `Periode(maand|jaar)`, jaar = afgesloten kalendermaanden, bevroren jaarstand mét dekkingslabel, hercontrole tegen de actuele jaarstand — zie BESLISSINGEN "FIXRUN 07-09 — BLOK D4".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Projecten** (module, zichtbaar per rol + per administratie-toggle): project verplicht = hard
  blokkerend, géén "geen project"-optie; overhead → intern OVH-project (uitgesloten van bewaking).
  Budget uit offerte-ontleding (status offerte ≠ opdracht; meerwerk = aparte budgetversie).
  Werksoort = omzet-GB ↔ kosten-GB-mapping (default per administratie, override per project/regel).
  Signalen: kosten > gefactureerd per werksoort; budgetoverschrijding; weekanalyse (inkoop zonder
  omzet); m²-voortgang uit factuurregels. Integrale marge = analytische laag (AK-opslag instelbaar,
  dekkingscontrole vs OVH-project) — nooit geboekt in RLZ.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Projectcode-generatie** volgens naamconventie van de klant (bijv. Universal: "26xxx Plaats
  (Opdrachtgever)"), synct bij aanmaken naar RLZ.
  Kantoor-projectenmodule (mockup projecten-invoer.html, migratie 0062) + cijfers-sync als ACHTERGRONDRUN (migratie
  0063) — zie BESLISSINGEN "PROJECTENMODULE KANTOOR" + "CIJFERS-SYNC-CRASH".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Inzicht › Projecten kantoorbreed + projectdetail-verrijking (C5 07-09):** `GET /projecten/kantoorbreed` (lijstpatroon, chips resultaat/verplichtingen/weekstaten/m² uit caches), route `/projecten` zonder param = kantoorbreed, chip "Projecten" op de klant-documentenlijst — zie BESLISSINGEN "INZICHT › PROJECTEN KANTOORBREED".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Contract-ontleding AUTO-FIRST (D6 07-09, besluit Peter 06-09; migratie 0118 — HERZIET de 22-08-regel "voorstel per regel, mens bevestigt"):** kopvelden soort werk / contract-m² / doorlopende huur als sentinel-strings (schema 0 unions), ontleding schrijft specs + staffels DIRECT met herkomst `contract` (chip "uit contract", correctie → `mens`, audit oud→nieuw), meerwerk-prijsvoorstel blijft mens-besluit — zie BESLISSINGEN "CONTRACT-ONTLEDING: KOPVELDEN + AUTO-FIRST".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Voorraad-aansluiting fase 1** (`mi`-schema, controle-laag, NOOIT RLZ-writes; opt-in `voorraad_ingeschakeld`;
  RLZ-verkoopfacturen als uitstroom-leesroute; normalisatie v2; Odoo als LEESBRON vanaf de voorraad-knip; migraties
  0086–0088/0102) — zie BESLISSINGEN "BOUWRUN 28-08 AVOND" blok D, "OPDRACHT 29-08" blok A/B, "OPDRACHT 30-08",
  "ODOO-ADAPTER FASE 1".

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Verplichtingen: offerte-accordering + factuur↔offerte-match (CLAUDE.md `ed6d176` r. 420–432)

- **Verplichtingen — offerte-accordering + factuur↔offerte-match (besluiten Peter 04-09, mockup `offerte-matching.html` ①–⑧ = norm,
  migratie 0110 — BESLISSINGEN "VERPLICHTINGEN + FACTUUR↔OFFERTE-MATCH 04-09" is canoniek):** één documenttype `verplichting` (soort-label
  offerte/prijsopgave/opdrachtbevestiging), door de intake-AI herkend (sentinel-veld `ds`; twijfel = verzamelbak "factuur of offerte? — kies
  bij toewijzen", nooit stil als factuur), eigen werkvoorraad-tab + reviewscherm `/verplichting/…` (veldvoorstel-patroon mét herkomst-chips,
  `app/extractie/verplichting.py` achter de bestaande gates), daarna de BESTAANDE accorderingsflow (lagen/drempels op het bedrag excl., app-kaart;
  staande goedkeuring uitgesloten) → nieuwe terminale status `geaccordeerd` (wie/wanneer/bedrag vastgelegd) — **géén RLZ-/Odoo-boeking**,
  dossierstuk 7 jaar. Deterministische match-motor `app/verplichting/match.py` (sleutel crediteur-kenmerk + project, offertenummer versterkt,
  meerdere kandidaten = "Koppel offerte…" éénmalig + onthouden): CUMULATIEF verbruik = som van de GEBOEKTE gematchte facturen, binnen = totaal ≤
  offertebedrag zonder tolerantie; verbruik bijgewerkt ín de boek-transactie, teruggedraaid bij tegenboeken/storno; groene melding + verbruiksbalk
  op controlescherm én accordeur-kaart mét vooringevuld vinkje (optie A: de mens tikt), buiten offerte/geen match = oranje vlag mét bedrag erover
  + werkvoorraad-teller "buiten offerte" (duplicaat-patroon) + handelingsperspectief "meerwerk = aparte verplichting" — nooit blokkade;
  afgewezen/vervallen verplichting stopt nieuwe matches, verrekende facturen blijven; Inzicht › Verplichtingen `/verplichtingen` kantoorbreed
  (overschreden bovenaan, uitklap gekoppelde facturen).

### Domeinbeslissingen — Mini-voorraad speciale producten (CLAUDE.md `ed6d176` r. 659–674)

- **Mini-voorraad speciale producten (mini-run 06-09 blok F, besluiten Peter 04/05-09, mockup `mini-voorraad.html`
  ①–⑧ = norm, migratie 0116, mi-schema — BESLISSINGEN "MINI-VOORRAAD SPECIALE PRODUCTEN" (+ "— FRONTEND") is canoniek):**
  opt-in per administratie `mini_voorraad_ingeschakeld` (Beheerder, default UIT; Universal Steigerbouw activeert Peter
  zelf). Instroom ín de GEBOEKT-transactie (`app/mini_voorraad/instroom.py::registreer_bij_boeking`, ná
  `bevries_bij_boeking`): per productregel deterministisch artikelcode (`a`) → exacte `omschrijving_norm` per leverancier
  (bestaande mi-normalisatie-sleutels) → anders NIEUW product mét vlag "nieuw — controleer naam" (de stroom stopt nooit);
  dienst-/transportregels uit via `classificeer_soort`; omschrijving = LETTERLIJK de factuurtekst (= sleutel), "Naam
  bevestigen" wijzigt alleen de weergavenaam; tegenboeken/storno spiegelt automatisch (`registreer_storno`, ook in het
  vastgoed-storno-detectiepad). **MENS-MANIPULATIE ONMOGELIJK (kernbesluit Peter 05-09):** de stand = Σ van de append-only
  `mi.mini_voorraad_mutatie` (instroom/storno/uitstroom/beschadiging); geen corrigeer-/samenvoeg-/stand-endpoint bestaat
  (testsweep bewaakt de routerlijst); de enige mens-ingang is de beschadigingsmelding VERPLICHT mét project (wie/waar/
  wanneer — gebeurtenis, geen correctie); producten archiveren, nooit verwijderen; telverschillen blijven signaal in de
  voorraad-aansluiting (virtuele groep "Speciale producten (mini-voorraad)", informatief) en de materiaallijst-dialoog
  toont de stand alleen-lezen. UI: tab "Mini-voorraad" in Instellingen › Materiaalcatalogus (volle breedte, kolommen
  product · stand · acties, Voorraadlog ▸ = append-only uitklap mét bron-link), toast + tijdlijnregel ná boeken.
  Uitstroom via verkoopfacturen = fase 2 (datamodel klaar). Router `/mini-voorraad/{aid}/…` kantoorrol + scope.

### Domeinbeslissingen — Inzicht › Projectverdeling (CLAUDE.md `ed6d176` r. 683–685)

- **Inzicht › Projectverdeling (mini-run 06-09 blok B):** `/projectverdeling` = kantoorbrede hercontrole-tabel op het
  bestaande endpoint (`?administratie_id=&q=` additief, tellers), zwaarste afwijking eerst, "Herverdelen…" = de
  uitgelichte `document/HerverdeelDialoog.tsx` (één bron met het controlescherm), KPI-kaart "Projectverdeling" alleen > 0.

### Domeinbeslissingen — Catalogus-leesroute smal (CLAUDE.md `ed6d176` r. 686–689)

- **Catalogus-leesroute smal (mini-run 06-09 blok C, herziet C2 04-09):** de drie catalogus-GET's dragen
  `require_catalogus_lezer` (Beheerder ÓF B+P ÓF kantoorrol mét module-recht 'Meerwerk & urenstaten'; motor-spiegel
  `_vereis_catalogus_lezer`), muteren blijft `require_beheerder_of_bp`; Transport-tab/catalogusbeheer tonen een laadfout
  als rode melding mét server-detail — nooit meer een valse lege lijst.

### Domeinbeslissingen — Projectcode-generatie + kantoor-projectenmodule + cijfers-sync (CLAUDE.md `ed6d176` r. 1108–1129)

- **Projectcode-generatie** volgens naamconventie van de klant (bijv. Universal: "26xxx Plaats
  (Opdrachtgever)"), synct bij aanmaken naar RLZ.
  **Kantoor-projectenmodule (mockup projecten-invoer.html, akkoord + GEBOUWD + GETEST
  2026-08-22, migratie 0062 — BESLISSINGEN "PROJECTENMODULE KANTOOR" is canoniek):**
  projectenlijst + detail met specs/contract-&-offerte-upload/verrekenstaffels/leverancier-
  werknummers (schrijven = Beheerder + Boekhouding+Projecten, lezen = kantoorrol + scope),
  contract-ontleding als AI-VOORSTEL per regel (per-administratie AVG-gate
  ai_extractie_ingeschakeld + AI-kostengrens; bevestigen = deterministisch opslaan), nieuw
  project via de bestaande RLZ-projectmotor-bouwstenen ("26127 Tilburg (Heijmans)"), en het
  resultaat per project + cumulatief overzicht (analytische laag — project_regel_cache uit
  RLZ-Lines mét projectref, `make projecten-cijfers-sync`; onderweg = getekende onverrekende
  uren × tarief (ontbrekend tarief = onbepaalbaar, nooit gokken) + goedgekeurd meerwerk;
  werkweek-herleiding via verrekende weekstaten; zelfde rekenfunctie voor detail én
  overzicht; nooit geboekt in RLZ, excl. AK-opslag; géén suppletie-signaal — besluit 22-08).
  **Cijfers-sync = ACHTERGRONDRUN (fix 504-crash, 2026-08-23, migratie 0063 — BESLISSINGEN
  "CIJFERS-SYNC-CRASH" is canoniek):** de ⟳-knop antwoordt 202 + statusrij
  (`project_cijfers_sync_run`, UI pollt bezig/klaar/fout mét zichtbare foutreden en
  leesfouten-teller), motor gepagineerd per documenttype/RLZ-pagina (nooit volledige
  collecties in één request — dat gaf de 504); voertuig cloud = on-demand job
  `rlz-projecten-cijfers` (metadata-server-trigger, IAM f3_jobs.sh stap 6), dev = thread;
  dagelijkse verversing draait mee in de rlz-sync-job van 07:00. Een onleesbaar document
  (RLZ-403) telt als leesfout en wordt nooit vals als "verdwenen" gemarkeerd.

### Domeinbeslissingen — Voorraad-aansluiting fase 1 + normalisatie v2 + Odoo-leesbron (CLAUDE.md `ed6d176` r. 1325–1361)

- **Voorraad-aansluiting fase 1 (bouwrun 28-08 blok D, mockup `voorraad-aansluiting.html`,
  migratie 0086 — eerste bewoner van het `mi`-schema):** controle-laag, géén tweede
  voorraadadministratie en NOOIT RLZ-writes. Opt-in `voorraad_ingeschakeld` (Beheerder-only, default
  UIT; sinds 29-08 AAN voor Universal Verkoop, Universal Nederland, Universal Steigerbouw, Bradwolff
  Constructie en BWC Steigers — in de cloud gekoppeld; eerste vulling 29-08 avond, zie BESLISSINGEN
  "OPDRACHT 29-08" blok A "Eerste voorraad-vulling"). Instroom = regel-niveau feiten uit het inkoop-veldvoorstel
  (AI-regelschema levert nu óók eenheid `e` + stuksprijs `p`), uitstroom = verkoopfactuurregels van de
  in de app geboekte verkoopdocumenten (UBL-hoeveelheden) **én — blok A 29-08, STAP-0 groen, migratie
  0087 — de EIGEN RLZ-verkoopfacturen van de administratie via de dagelijkse leesroute
  `app/voorraad/rlz_uitstroom.py` (meelopend in `sync-alles`, incrementeel vanaf max(datum) − 14 dagen,
  alleen Status 2/3, aantal = `Quantity` mét teken — creditregels zijn al negatief, nooit dubbel
  flippen; `voorraad-rlz-sync --volledig` voor de eerste run; strikt GET-only). **Odoo als LEESBRON vanaf de
  voorraad-knip (Odoo-adapter blok D 03-09, migratie 0102): alleen-lezen koppeling op een RLZ-administratie,
  `app/odoo/verkoop_uitstroom.py` leest geposte out_invoice/out_refund (creditnota = negatief) vanaf
  `voorraad_knip_datum`, de RLZ-route registreert ≥ knip niet meer — zie BESLISSINGEN "ODOO-ADAPTER FASE 1".**
  Normalisatie VOLAUTOMATISCH: dienst-regel zonder AI, bestaande regel deterministisch,
  eerste match = AI-voorstel (`ClaudeExtractieClient.vraag_json`, zelfde kostenpoort) direct
  toegepast, onzeker telt mee mét vlag, geen AI = "niet genormaliseerd" (prominente teller);
  correctie optioneel en herrekent historie. Aansluitscherm (menu Inzicht › Voorraad): per
  artikelgroep begin + inkoop − verkoop = theoretisch vs telling, tolerantie 1% default, bron per
  kolom (incl. herkomst per regel: app-document vs "RLZ-verkoopfactuur nr"), drill-down + dagstanden;
  invoer (nieuwe groep, tolerantie) via designpass-v2-dialogen (blok B 29-08). **Normalisatie v2
  (besluiten Peter 29-08 avond, GEBOUWD 30-08, migratie 0088 — BESLISSINGEN "OPDRACHT 30-08" is
  canoniek): "uitgesloten" is een SOORT-label (artikel/dienst/transport) — dienst-/transportregels
  blijven bewaard en queryable (`regels?soort=`, omzet-informatie voor MI) en tellen alleen niet;
  `normalisatie_status` = puur zekerheid ('uitgesloten' = legacy pre-0088, omgezet door de
  hernormalisatie; migratie puur DDL want Alembic op Cloud SQL heeft geen BYPASSRLS). Dienst-regex
  uitgebreid op de 29-08-bevindingen (kilometers/reistijd/inspectie/keuring/kalibratie/huurperiode)
  MÉT dienst-inzage per tekst + correctie (eis Peter: nooit blind vertrouwen). Artikelcode als
  deterministische sleutel per RICHTING (verkoop: "(560140.4)" uit de Description; inkoop: nieuw
  AI-regelveld `a`) in `mi.artikelcode_koppeling` — inkoop- en verkoopcodes nooit gelijkgesteld;
  prioriteit handmatig > tekstregel > code > regex > AI (batches van 40); codes-inzage + correctie
  per code; steigerdelen 3 m ≠ 5 m (prompt). Hernormalisatie zonder RLZ-calls: `make
  voorraad-hernormaliseer` (rapport per BV + AI-maandmeter); tegen de cloud via
  `backend/scripts/cloud_cli.py` — cloud-run 30-08 = klikpunt (deploy 0088 + `gcloud auth login`).**
  `app/voorraad/`; BESLISSINGEN "BOUWRUN 28-08 AVOND" blok D + "OPDRACHT 29-08" blok A/B +
  "OPDRACHT 30-08".
