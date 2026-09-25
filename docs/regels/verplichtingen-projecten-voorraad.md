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

<!-- toegevoegd 18-09-2026, opdracht "projecten-status-afsluiten-en-nummer-uniek" -->
- **Projecten — status afgesloten + projectnummer uniek (Peter 18-09: "Bij steigerbouw moeten projecten een status krijgen; als
  een project afgesloten is kan het uit de lijst" en "Per abuis 2× hetzelfde projectnummer aangemaakt — moet geblokkeerd
  worden"; migratie 0160 = `project_cache.status/afgesloten_op/afgesloten_door/afsluit_reden` + index; BESLISSINGEN
  "PROJECTEN — STATUS AFGESLOTEN + PROJECTNUMMER UNIEK (Peter 18-09)"):** (A) `project_cache.status` = MODULE-status
  `lopend`/`afgesloten` náást `is_actief` (spiegel van RLZ `IsActive`/Odoo `active`). Afsluiten (`app/projecten/status.py`,
  knop "Afsluiten…" op het projectdetail, Beheerder + Boekhouding+Projecten via `_vereis_schrijfrol`, reden + datum
  optioneel) zet EERST de bron inactief — RLZ: klant-loze `PUT Projects/{id}` mét de bestaande naam + `IsActive:false` en
  TERUGLEESVERIFICATIE (bevestigt RLZ niet → 502, status ongewijzigd: RLZ wint); Odoo: `active=False` op de analytic account
  via de company-gebonden client (`odoo_id` uit `odoo_id_koppeling`/brondata, archiveren, nooit unlink) — en pas dán de
  status + `is_actief=false` + audit `project_afgesloten` oud→nieuw; heropenen (`project_heropend`) is het spiegelbeeld.
  Gevolg: álle keuzelijsten (planning, weekstaat, verplichting, controlescherm-combobox, betaallijst) filteren al op
  `is_actief` — één mechanisme, geen tweede waarheid; de combobox toont een afgesloten project onderaan mét chip "inactief"
  (patroon 16-09) zodat een document dat er al op staat leesbaar blijft. Lijst per administratie: afgesloten standaard weg
  (`alleen_actief` = ook `status != afgesloten`), toggle "Toon afgesloten (N)" (`alleen_actief=false`, teller
  `aantal_afgesloten`), rij grijs mét chip; Inzicht › Projecten: toggle `?afgesloten=1`/`toon_afgesloten`, facet
  `afgesloten`, afgesloten rijen onderaan, tellers `afgesloten`/`kandidaat_afsluiten`. Een factuurregel naar een afgesloten
  project = ORANJE SIGNAAL "Project afgesloten: ‹naam› (afgesloten op ‹datum›)" (`checks.check_project_afgesloten`, in beide
  rapport-takken van `boekvoorstel`, alleen als er iets te melden is) — nagekomen facturen bestaan, nooit blokkerend.
  **Kandidaat afsluiten** (automatisering-first, nooit automatisch): geen weekstaat, planning, verplichting of factuurregel in
  90 dagen ÉN gebouwd-m² ≥ contract-m² (beslispunt: het model kent geen contractsom; m²-voortgang is de deterministische
  maat; zonder contract-m² geen kandidaat, wél de reden zichtbaar) → chip "kandidaat afsluiten" + facet; set-based
  (`status.kandidaat_afsluiten_per_project`, vier statements per administratie). (B) **Projectnummer uniek**
  (`app/projecten/nummer.py`): het nummer is de cijfer-prefix van de naam (RLZ kent géén codeveld, STAP-0 16-09), uniek
  BINNEN de administratie over álle projecten (lopend + afgesloten, actief + inactief) — getoetst op de cache én live in RLZ
  (`RlzClient.find_projects_by_name_prefix`, `startswith(Name,'26127 ')`; "261270" is geen treffer); bezet = 409
  `projectnummer_bestaat_al` mét het bestaande project ("26127 bestaat al: 26127 Tilburg (Heijmans), lopend — openen?",
  dialoog toont "Openen"), alleen exact dezelfde naam op het eigen deterministische GUID is de idempotente herhaal-klik
  (bestond_al). Volgnummer-voorstel = eerstvolgende vrije nummer van het jaar (bestaand `volgende_projectnummer`, voorgevuld).
  **Herstel bestaande dubbelen** = lees-only CLI `projecten-dubbele-nummers [--administratie]` (beide id's, facturen/
  weekstaten/planning per kant, voorstel "blijft" = meeste activiteit; samenvoegen = klikpunt Peter, verliezer daarna op
  afgesloten/IsActive uit, nooit verwijderen) en `projecten-afsluit-kandidaten [--administratie] [--dagen] [--alles]` — beide
  in de nameting-allowlist (`scripts/gcp/nameting.sh`), nooit vanuit een run tegen productie. **Reconciliatie-soort
  `project_nummer_dubbel`** (blok `projecten`, `nummer.cli_blok` in `reconciliatie-alles` + `run.BLOKKEN`; vingerafdruk
  administratie + nummer) start in stand `meten` (registry `soort_stand.py`) voor dubbelen die buiten de module om in RLZ
  ontstaan. Tests `tests/projecten/test_status_en_nummer.py` (15), `tests/keten/test_v_project_afgesloten_signaal.py` (2),
  frontend `projecten/ProjectStatus.test.tsx` (4). Uren-/planningcode is NIET geraakt (blok 4 bouwt daar): het filter loopt
  volledig via `is_actief`.

<!-- toegevoegd 18-09-2026, opdracht "BUG-offerte-verbruik-telt-onderweg-facturen-niet" -->
- **Offerte-verbruik = geboekt + onderweg (BUG Peter 18-09 20:04, accordeur-app, Bouwadvies Oost Nederland, offerte "zonder nummer"
  € 1.192.922,50 — letterlijk: "ik heb net een factuur geaccordeerd van deze partij voor € 20.000, deze boeking zegt nu binnen
  offerte (50.000 van bedrag), maar dat moet nu 20.000 + 50.000 (70.000) zijn, hij moet wel doortellen."; migratie 0166 = index
  `ix_verplichting_match_administratie_verplichting`; BESLISSINGEN "OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)"; HERZIET
  het CONTRACT_B-besluit 04-09 "verbruik = uitsluitend geboekt" en de voorwaarschuwing 0.1 "open facturen informatief, buiten het
  verbruik"):** (1) **Verbruik = geboekt + onderweg.** Geboekt = `Verplichting.verbruikt_bedrag_excl` (de boekstand, bijgeschreven
  ín de boek-transactie — auditspoor `verplichting_verbruik_bijgewerkt` ongewijzigd). Onderweg = Σ `VerplichtingMatch.bedrag_excl`
  van de ándere documenten met uitkomst binnen/buiten op dezelfde verplichting waarvan de status niet terminaal en niet GEBOEKT is
  (ter_accordering, klaar_om_te_boeken, wordt_geboekt, boeken_mislukt, te_controleren, vraag_open, …;
  `match_pipeline.ONDERWEG_UITGESLOTEN_STATUSSEN` = terminale statussen + geboekt), `verrekend_op IS NULL`, het eigen document
  uitgezonderd. Onderweg wordt per toets berekend (één groepsquery `onderweg_per_verplichting`, per administratie), nooit
  opgeslagen; `details` op de matchrij draagt de splitsing `verbruik_geboekt` / `verbruik_onderweg` / `onderweg_aantal` /
  `onderweg_ter_accordering`. Bij drie accorderingslagen zit een factuur dagen tot weken in de accordering — twee facturen tegelijk
  "binnen offerte" terwijl de som erbuiten valt was de normale situatie, geen randgeval. (2) **Toets en tekst:** binnen/buiten op
  (geboekt + onderweg + eigen bedrag) ≤ offertebedrag, zonder tolerantie. Melding/kaart: "€ 70.000,00 van € 1.192.922,50 · waarvan
  € 20.000,00 nog niet geboekt (1 factuur ter accordering)" — "ter accordering" als álle onderweg-facturen ter accordering staan,
  anders "in behandeling" (`match.onderweg_tekst`, frontend-spiegel `verplichting/verbruikPresentatie.ts::onderwegTekst`); één DTO
  voor kantoor-controlescherm (`VerplichtingMatchDto`) en accordeur-app (`OfferteMatchKortDto`: `termijn`, `verbruik_geboekt`,
  `verbruik_onderweg`, `onderweg_aantal`, `onderweg_ter_accordering`). Balk: geboekt vol, onderweg GEARCEERD, eigen factuur
  gemarkeerd (`VerbruiksBalk` segmenten, `verbruikSegmenten` = verhoudingen van server-bedragen; de vette tekst toont het
  cumulatief ná deze factuur). Termijnnummer telt geboekt én onderweg ("2e termijn"), een afgewezen/verwijderde factuur is geen
  termijn meer. (3) **Volgorde-effect — herberekening bij statuswissel, nooit stil.** `documenten.service._schrijf_overgang`
  (de ENIGE statusmutator) registreert via `match_pipeline.registreer_statuswissel` élke overgang waarbij het document anders gaat
  meetellen (`telt_als_onderweg(van) != telt_als_onderweg(naar)`: afgewezen, verwijderd, geboekt, hersteld) én een binnen/buiten-
  match heeft; ná de commit (`after_commit` op die sessie — eigen transacties, nooit blokkerend) herberekent
  `herbereken_na_statuswissel` de andere open documenten op dezelfde verplichting; verandert uitkomst of verbruik-ná, dan komt op
  dát document een tijdlijnregel "offerte-toets herberekend: buiten → binnen — verbruik ná deze factuur … (aanleiding: factuur
  ‹ref› afgewezen (was te controleren))" + audit `verplichting_match_herberekend` (systeem-actor). Een overgang binnen onderweg
  (te_controleren → klaar_om_te_boeken → ter_accordering) herberekent niets. Gevolg (bewust, per de regel): staan er twee open
  facturen waarvan de som boven de offerte komt, dan zijn ná herberekening BEIDE "buiten" — de zin "waarvan € X nog niet geboekt"
  zegt waarom; buiten offerte blijft niet-blokkerend (bestaande bevestiging bij boeken). (4) **Dezelfde drie getallen overal:**
  `VerbruikStand`/`VerbruikDto` en `KantoorRijDto` dragen `verbruikt_excl` (geboekt), `onderweg_excl`/`onderweg_aantal`/
  `onderweg_ter_accordering`, `restant_excl` (= totaal − geboekt − onderweg, negatief = overschreden), `percentage` (geboekt +
  onderweg) en `percentage_geboekt`; `open_facturen_*` = de oude naam van onderweg, gelijk gehouden; status "overschreden" op
  Inzicht › Verplichtingen = geboekt + onderweg > totaal (`bereken_verbruik_stand`, puur, één bron voor reviewscherm en
  kantoorbreed). (5) **Nazorg productie:** matchrijen van vóór de deploy dragen onderweg = 0 tot een trigger komt → CLI
  `verplichting-match-herberekenen [--administratie] [--dry-run]` (`app/verplichting/cli_cmd.py`, SCHRIJVEND, niet in de
  nameting-allowlist) herberekent álle open gematchte inkoopdocumenten; uitvoeren als `gcloud run jobs execute` op de gedeployde
  image, vervolg-opdracht in de inbox. Nulmeting leesreplica 18-09 20:50: Bouwadvies verplichting 34aaf45b (zonder nummer,
  € 1.192.922,50, boekstand 0) heeft drie facturen ter accordering — 32948 € 20.000, 32949 € 50.000, 33122 € 80.000 — élk met
  `verbruik_voor` 0; ná deploy + herberekening hoort 32949 € 150.000,00 van € 1.192.922,50 te tonen mét "waarvan € 100.000,00 nog
  niet geboekt (2 facturen ter accordering)" (Peters "70.000" gold vóór 33122 een minuut later binnenkwam). Guards:
  `tests/verplichting/test_match.py::TestOnderwegTeltMee` (puur), `tests/verplichting/test_verbruik.py::TestOnderweg` (20k
  onderweg + 30k op 48.500 → buiten; afwijzen 20k → herberekening → 30k binnen mét tijdlijnregel + audit; statuswissel binnen
  onderweg herberekent niet; ter accordering = label; eigen document nooit dubbel; geboekt + onderweg 0 = bestaand gedrag),
  `TestHerberekenCli`, vitest `verbruikPresentatie.test.ts`, `OfferteMatchMelding.test.tsx`, `GoedkeurenFlow.verplichting.test.tsx`,
  `VerplichtingenScreen.test.tsx`, `VerplichtingReviewScreen.test.tsx`, `ProjectDetailVerrijking.test.tsx`.

<!-- toegevoegd 18-09-2026 avond, opdracht "facturen-zonder-project-universal-rapport-en-inbox-hygiene" -->
- **Facturen zonder project — lees-only rapport (18-09 avond, TODO Peter 23-08 "eerst rapport, dan beslissen"; geen migratie;
  BESLISSINGEN "FACTUREN ZONDER PROJECT — LEES-ONLY RAPPORT + INBOX-HYGIËNE (18-09 avond)"):** CLI `facturen-zonder-project
  (--administratie X | --alle-projectverplicht) [--jaar] [--rlz]` (`app/projecten/zonder_project.py`, nameting-allowlist) toont per
  project-verplichte administratie de in de module geboekte inkoopfacturen mét een regel zonder `project_id`. Een regel is GEDEKT als
  het document een bevroren projectverdeling van dezelfde `boek_cyclus` draagt (de RLZ-adapter splitst dan per project — in RLZ staat
  het project wél); alleen niet-gedekte regels zijn een bevinding. Per rij: boekstuk, referentie, leverancier, factuur-/boekdatum,
  geboekt op/door (jongste GEBOEKT-overgang; `automatisch_geboekt` = "automatisch"), regel, grootboek, netto/btw, aangifte-stand
  (`AangiftePoort`) en herstelroute als VOORSTEL: (a) open periode → storno 19 → project → her-PUT (zelfde client-GUID's) → 17,
  (b) ingediend → tegenboek-pad, geen credential → "toets nodig" zichtbaar. Projectvoorstel uitsluitend deterministisch (één
  bevestigde werknummer-mapping van de leverancier óf één project in ≥ 3 eigen geboekte facturen; meerduidig = "mens nodig", nooit
  raden). `--rlz` = dezelfde toets RLZ-kant, uitsluitend GET (Status 2/3, `Lines?$expand=Account,Project`, regel zonder Project op
  4xxx/7xxx); module-documenten herkend op client-GUID, het verschil = facturen van vóór/buiten de module. Meting 18-09 (leesreplica):
  Universal 59 geboekt, 5 mét lege projectkolom, alle 5 gedekt (pro rato juli 2026, 8 projecten) → 0 bevindingen; Q3 2026 open. De CLI
  schrijft niets; herstellen in bulk = nieuwe opdracht ná besluit Peter. Guard `tests/projecten/test_zonder_project.py`.

<!-- toegevoegd 19-09-2026, opdracht "projectverdeling-sluit-afgesloten-projecten-uit-en-rlz-kant-meting" -->
- **Projectverdeling sluit afgesloten projecten uit + naam-LET-OP + RLZ-kant-meting (19-09, nazorg rapport 2026-09-18-facturen-zonder-
  project beslispunt 3; geen migratie; BESLISSINGEN "PROJECTVERDELING SLUIT AFGESLOTEN PROJECTEN UIT + RLZ-KANT-METING FACTUREN ZONDER PROJECT (19-09)"):** (A1) de omzet-gewogen
  verdeelsleutel (`app/projectverdeling/omzet.py::omzet_per_project`) neemt uitsluitend projecten mét `is_actief` (bron-spiegel) ÉN
  module-status ≠ `afgesloten` (0160) op het moment van berekenen/boeken; een project waarvan de NAAM met "Afgesloten" begint maar dat
  actief staat, blijft in de sleutel — nooit stil uitsluiten op naam — en is een LET-OP `project_naam_afgesloten_status_actief` in het
  reconciliatieblok `projecten` ("naam zegt afgesloten, status actief — afsluiten?", actie Projecten › Afsluiten…; registry `meten`,
  vingerafdruk administratie + project; `omzet.naam_zegt_afgesloten` = eerste woord, hoofdletterongevoelig). (A2) Afsluiten/heropenen
  (`status._wissel`) roept ná de statuswissel `projectverdeling/afgesloten.py::herbereken_na_projectstatus_veilig` aan: nog niet
  geboekte verdelingen (status `voorstel`, document niet geboekt/verwijderd) waarvan het snapshot het project draagt worden live
  herrekend, het snapshot (`verdeling`/`omzetstanden`/`pro_rato_bedrag`) teruggeschreven en per gewijzigd document één tijdlijnregel
  "verdeling herberekend: ‹project› afgesloten" (heropenen: "… heropend", dan álle pro-rato-voorstellen van de administratie) + audit
  `projectverdeling_herberekend` oud→nieuw; geboekte verdelingen blijven staan (boekstand; herverdelen = de bestaande tegenboek-route);
  een fout in de herberekening maakt het afsluiten nooit ongedaan (logregel, de volgende lezing rekent tóch live). (A3) Lees-only CLI
  `projectverdeling-afgesloten-rapport (--administratie X | --alle-projectverplicht)` (`app/projectverdeling/cli_cmd.py`, nameting-
  allowlist, workflow-onderdeel `projecten-afgesloten` mét de RLZ-kant-meting): actieve projecten mét "Afgesloten"-naam, geboekte
  verdelingsdelen op projecten die nú afgesloten/inactief zijn of "Afgesloten" heten (boekstuk, referentie, leverancier, project,
  bedrag, datum) mét voorstel per rij (afgesloten/inactief → "storno 19 + herverdeling, aangiftepoort toetsen"; alleen naam → "laten
  staan tot afgesloten") en de overhead die via de sleutel loopt (regels zonder project op 4xxx; Σ pro rato = wat een OVH-project zou
  vangen) — niets uitvoeren, OVH-project nooit zelf aanmaken (beslispunt Peter). **Meting Universal 19-09 (leesreplica + job-image):**
  170 projecten (83 actief), 94 mét "Afgesloten"-naam waarvan 8 in RLZ nog actief en 0 module-afgesloten; 5 geboekte verdelingen (pro
  rato augustus 2026, 8 delen — het 18-09-rapport zei "juli", de kolom zegt 2026-08-01) leggen € 1.239,05 op "Afgesloten 26012 Tilburg
  (van Kasteren)" (7,69 %) en "Afgesloten 26051 Opijnen" (2,44 %); álle 5 geboekte pro-rato-documenten zijn overhead (4499 ×3 € 599,32,
  4003 € 11.000, 4606 € 630 = € 12.229,32; onderweg Exact 4410 € 31,50); RLZ-kant 2026: 1.296 geboekte PurchaseInvoices gelezen, 0
  leesfouten, 0 documenten mét kostenregel zonder Project (alle vijf project-verplichte administraties: 1.628 gelezen, 0) → bulk-herstel
  niet nodig. Tests `tests/projectverdeling/test_afgesloten.py`.

<!-- toegevoegd 19-09-2026, opdracht "projecten-afsluit-kandidaten-scherm-bulk-afsluiten" -->
- **Projecten — tab "Afsluiten? (N)" mét bulk-afsluiten en "Niet afsluiten" (Peter 19-09: "welk project is afgesloten? dat onderscheid
  maken wij nu nog niet"; voorwaarde voor de verdeelsleutel-opdracht van dezelfde ochtend; migratie 0167 =
  `platform.administratie.project_afsluit_stil_maanden` (smallint, default 6) + `boekhouding.project_afsluit_uitstel` (PK project +
  administratie, reden NOT NULL, door, op, snapshot `laatste_activiteit`; RLS op administratie, geen DELETE-grant); BESLISSINGEN
  "PROJECTEN — TAB AFSLUITEN? MÉT BULK-AFSLUITEN EN NIET-AFSLUITEN (Peter 19-09)"; HERZIET het 18-09-kandidaatcriterium "stil ≥ 90 dagen ÉN
  contract-m² bereikt"):** (1) **Eén motor** `app/projecten/afsluiten.py` voor de tab per administratie, de kantoorbrede tab op Inzicht ›
  Projecten, de chip "N kandidaat afsluiten →" en de lees-only CLI `projecten-afsluit-kandidaten [--administratie] [--maanden] [--alles]`.
  Kandidaat = lopend + actief project mét één of meer REDENEN, deterministisch: `stil` (geen inkoop-/verkoopregel, weekstaat, planning of
  verplichting in de laatste N maanden; N = `project_afsluit_stil_maanden`, 1..36, instelbaar per administratie op de tab zelf door
  Beheerder + Boekhouding+Projecten, audit `project_afsluit_stil_maanden_gewijzigd`), `eindfactuur` (jongste VERKOOPregel draagt
  eindfactuur/eindafrekening/slotfactuur in omschrijving of referentie), `naam_afgesloten` (`omzet.naam_zegt_afgesloten`, status actief —
  nooit stil uitsluiten op naam, wél aanbieden), `looptijd_verstreken` (`project_specificatie.looptijd_tot` < vandaag). **Een project
  zonder énige activiteit telt NIET als stil** (de cache kent geen aanmaakdatum; een gisteren aangemaakt project mag nooit "afsluiten?"
  heten) — de redentekst zegt dat wel. Per rij: laatste activiteit (soort inkoop/verkoop/uren/planning/offerte, datum, bedrag, boekstuk)
  en open posten als chip "let op" — inkoop nog niet geboekt (boekvoorstelregels op het project van documenten buiten
  `ONDERWEG_UITGESLOTEN_STATUSSEN`), verplichting open (GEACCORDEERD, niet vervallen, verbruik < bedrag), uren niet gekeurd (weekstaat ≠
  goedgekeurd) — informatie, nooit een blokkade. Sortering: "Afgesloten …"-namen bovenaan, dan meeste redenen, dan langst stil. (2)
  **Bulk "Afsluiten (N)"** (`POST /projecten/afsluiten-bulk`, max 200 items, optionele reden/datum voor álle) loopt per project door de
  bestaande 0160-flow `status.sluit_project_af` (bron eerst inactief mét terugleesverificatie, RLZ wint; Odoo archived; audit
  `project_afgesloten`; herberekening projectverdeling) mét uitkomst per rij `gelukt` / `bron_weigert` (mét de reden, o.a. geen
  credential) / `al_afgesloten` / `niet_gevonden` / `geen_toegang` (administratie buiten scope); één bron-client per administratie; de
  rolpoort (Beheerder + B+P, `kantoor._SCHRIJF_ROLLEN`) staat fail-closed VÓÓR de eerste bron-call en geeft 403 als geheel. NOOIT
  automatisch — de knop blijft van een mens. (3) **"Niet afsluiten"** (`POST /projecten/{aid}/{pid}/niet-afsluiten`, reden VERPLICHT →
  422 leeg) upsert `project_afsluit_uitstel` mét snapshot van de laatste activiteit + audit `project_afsluiten_uitgesteld` oud→nieuw;
  de rij verdwijnt uit de kandidaten tot er activiteit ná het snapshot is (dan opnieuw kandidaat) en blijft zichtbaar onder "Toon
  uitgesteld (N)" mét reden/sinds — niets verdwijnt stil. (4) **Rechten:** lezen = élke kantoorrol binnen scope (`vereis_kantoorrol` +
  `mijn_administraties`), handelen = Beheerder + Boekhouding+Projecten (Haci/Iris-patroon), Boekhouding leest alleen (knoppen weg via
  `magAfsluitenBedienen`, server beslist), klant-accordeur/veld-app 403. (5) **UI:** `frontend/src/projecten/AfsluitKandidatenTab.tsx`
  in beide lijsten als `segment`-tab "Afsluiten? (N)" (`?tab=afsluiten`, teller uit dezelfde bron als de tabel), zoekveld + `Select`
  op reden mét tellers per reden, chip "N met open posten", vinkjes + kolomkop alles-kiezen, uitkomst-badge per rij + overzicht
  "Laatste bulk-actie" (blijft staan ná herladen), "Openen →" naar het detail, administratie-link = deeplink `?administratie=…&tab=afsluiten`;
  lege stand is een zin. Tabel in `.tabel-scroll`; harnas `harness-werkvoorraad.html?projecten=1&tab=afsluiten` in de overflow-sweep.
  (6) **Meting Universal Steigerbouw 19-09 (leesreplica, venster 6 mnd, vandaag 19-09):** 83 lopende actieve projecten, **8 kandidaten —
  álle 8 op `naam_afgesloten`** (25017 óók `eindfactuur`: verkoopregel "Eindfactuur", laatste activiteit 03-06), **0 op `stil`** (het
  jongste "Afgesloten"-project 26091 had 15-09 nog een verkoopregel; 25157 Harderwijk is 173 dagen stil — net binnen 6 mnd), 0 op
  looptijd (geen `looptijd_tot` gevuld), 11 projecten zonder énige activiteit (o.a. 26149 tweemaal en 26064 Harskamp náást "Afgesloten
  26064 Apeldoorn" = dubbele nummers → CLI `projecten-dubbele-nummers`). Rapport `docs/rapporten/2026-09-19-projecten-afsluiten-tab-bulk.md`.
  Tests `tests/projecten/test_afsluiten.py` (10), vitest `AfsluitKandidatenTab.test.tsx` (7).

<!-- toegevoegd 19-09-2026, opdracht "projectnummer-uit-afgesloten-naam" -->
- **Projectnummer óók lezen uit "Afgesloten NNNNN …"-namen (19-09, bijvangst nameting rapport 2026-09-19-projectverdeling-afgesloten-
  projecten-en-rlz-kant-meting sectie "Nameting ná deploy"; geen migratie, geen RLZ-write; BESLISSINGEN "PROJECTEN — STATUS AFGESLOTEN +
  PROJECTNUMMER UNIEK (Peter 18-09)" rij B4):** Universal zet het woord "Afgesloten" VÓÓR de projectnaam als afsluitmarkering (94 van 170
  projecten) — de nummer-extractie van 18-09 (`^\s*(\d{3,6})(?!\d)`) las het nummer alleen aan het begin en zag "Afgesloten 26064
  Apeldoorn (Ben Kuijer)" náást "26064 Harskamp (vd Brandhof)" niet als dubbel; dezelfde blinde vlek zat in de 409-poort
  (`startswith(Name,'26064 ')`). Sinds 19-09 is `nummer.cijfer_prefix` de ENIGE nummerlezer: cijfer-prefix ná een optioneel
  afsluitwoord (`zonder_afgesloten_voorvoegsel`, hergebruik `omzet.naam_zegt_afgesloten` = eerste woord, hoofdletterongevoelig;
  "Project afgesloten 26064" is géén markering, "Afgesloten" zonder nummer = None, "261270" blijft geen treffer voor 26127) — gebruikt
  door `project_nummer_dubbel` (reconciliatieblok `projecten`), `vereis_nummer_vrij` (409-poort: nieuw "26064 X" naast een bestaand
  "Afgesloten 26064 Y" = 409 mét het bestaande project, cache- én RLZ-kant), `projecten-dubbele-nummers` en `volgende_projectnummer`
  (een nummer dat alleen nog op een afgesloten-gemarkeerd project staat is bezet; het oude `kantoor._NUMMER_PATROON` is verwijderd).
  Cache-voorselectie `like '<nr>%' OR ilike 'afgesloten%'`, exacte toets lokaal. RLZ-kant: één GET `startswith(Name,'26064 ') or
  startswith(Name,'Afgesloten 26064 ')` (`RlzClient.find_projects_by_name_prefixes`; STAP-0 19-09 op Universal: 200, `@odata.count` 2,
  beide kanten — api-verkenning "Projects — or-filter op Name"); een client zonder die methode krijgt twee `startswith`-GET's; het
  antwoord wordt altijd lokaal op `cijfer_prefix` getoetst en per project-id gededupliceerd. Samenvoegen van dubbelen blijft mens-werk
  (klikpunt), nooit verwijderen. Nameting ná deploy = vervolg-opdracht (verwacht 4 × `project_nummer_dubbel` bij Universal: 26053, 26064,
  26084, 26149; `projecten-dubbele-nummers --administratie "Universal Steigerbouw"` toont 26064 mét beide kanten + voorstel "blijft");
  workflow-onderdeel `projecten-afgesloten` draait sinds 19-09 óók `reconciliatie-alles --alleen projecten --lees-only` en
  `projecten-dubbele-nummers`. **Gemeten 19-09 17:15 ná deploy `1dab82c` (service én jobs; nameting-run 35450280469, opdracht
  `2026-09-19-nameting-projectnummer-afgesloten-na-deploy`): werkt in productie JA — 4 × `project_nummer_dubbel` (26053, 26064, 26084,
  26149; was 3), 26064 mét beide id's; het voorstel "blijft" valt op "Afgesloten 26064 Apeldoorn" (10 factuurregels vs 0 bij Harskamp) —
  correct volgens de heuristiek, maar het wijst naar het als afgesloten gemarkeerde project: klikpunt Peter, geen systeemvoorkeur;
  vervolgpunt (niet gebouwd) = expliciete regel "let op: naam zegt afgesloten" bij zo'n voorstel.** Tests `tests/projecten/test_status_en_nummer.py` (+3: prefix door het afsluitwoord, 409 cache + RLZ mét
  or-GET, oudere client twee GET's; dubbelen-test mét de 26064-casus), `test_kantoor_module.py::test_volgende_projectnummer` (+ "Afgesloten
  26140" telt door). Rapport `docs/rapporten/2026-09-19-projectnummer-uit-afgesloten-naam.md`.

<!-- toegevoegd 19-09-2026 avond, opdracht "nameting-projecten-afsluiten-tab-na-deploy" -->
- **Tab "Afsluiten? (N)" — nameting ná deploy + eindfactuur-reden deterministisch bij meerdere regels op één datum (19-09 avond; geen
  migratie, geen RLZ-write; BESLISSINGEN "PROJECTEN — TAB AFSLUITEN? MÉT BULK-AFSLUITEN EN NIET-AFSLUITEN (Peter 19-09)" statusalinea):**
  **werkt in productie: JA (motor op de job-image), niet gemeten (de tab zelf — `GET /projecten/afsluit-kandidaten` is op 19-09 door geen
  mens aangeroepen; Peter/Haci openen 'm morgen).** Meting op service én jobs `a3eac85` (bevat `86ecbad` = 0167 + motor): nameting-run
  35450280469 (bot-bestand `verkenning/nameting-projecten-afgesloten-19-09.txt`, `d724769`) en herhaling 35454573374 geven bij Universal
  "83 lopende projecten beoordeeld, 8 kandidaat afsluiten (geen activiteit 0, eindfactuur geboekt 0, naam zegt afgesloten 8, looptijd
  verstreken 0), 0 uitgesteld" — dezelfde acht als op de replica; leesreplica: `project_cache` Universal 83 lopend+actief / 87
  lopend+inactief / 0 afgesloten, `project_afsluit_uitstel` 0, stil-venster 6, 0 audit-events `project_afgesloten`/`_uitgesteld`/
  `_stil_maanden_gewijzigd` → er is nog niets afgevinkt. **Correctie op het bouwrapport:** "25017 óók eindfactuur" was fout — de jongste
  verkoopregel van 25017 is 03-06 "Hefsteiger compleet 2e van 2 termijnen)" (808010818); de "Eindafrekening" (808010670) is van 06-03 en
  telt volgens de regel (jongste verkoopregel) terecht niet: ná een eindafrekening zijn er nog twee termijnen gefactureerd. **Latente
  niet-determinisme gefixt:** `_laatste_regel_per_project` koos bij meerdere regels op dezelfde jongste datum (een factuur mét meerdere
  regels — de normale situatie) de eerste rij in databasevolgorde, zodat de reden `eindfactuur` op de replica anders kon uitvallen dan op
  de primary; sinds 19-09 avond wint een regel mét de eindfactuur-tekst, anders de eerste op (`rlz_document_id`, `id`) — een reden mag
  nooit van de rijvolgorde afhangen. Guard `tests/projecten/test_afsluiten.py::test_eindfactuur_meerdere_regels_op_jongste_datum_is_deterministisch`
  (drie regels op één datum mét de eindfactuurregel als tweede ingevoegd → reden; de 25017-casus → geen reden; tegenproef zónder fix rood).
  Rapport `docs/rapporten/2026-09-19-nameting-projecten-afsluiten-tab-na-deploy.md`.

<!-- toegevoegd 21-09-2026, opdracht "activa-mva-akkoord-fase-1-plus-bua-rekeningen-meting-plus-vgg-toewijzing-schrijf-c" blok D (capture-at-acceptance) -->
- **Universal Steigerbouw — overhead via de omzetsleutel over de actieve projecten, GÉÉN OVH-project (besluit Peter 21-09: "Universal moet
  juist overhead verdelen over projecten, zo houden"; geen migratie, geen code-wijziging; BESLISSINGEN "UNIVERSAL — OVERHEAD VIA DE
  OMZETSLEUTEL, GEEN OVH-PROJECT (Peter 21-09)"):** de regel "overhead → intern OVH-project (uitgesloten van bewaking)" is een KLANTKEUZE, geen
  systeemnorm: een OVH-project bestaat alleen waar de klant dat wil; voor Universal is het patroon de omzet-gewogen pro-rato-verdeling
  (`app/projectverdeling/omzet.py`) over de actieve, niet-afgesloten projecten (19-09-regel). De module maakt nooit zelf een OVH-project aan,
  stelt het voor Universal ook niet meer voor, en het lees-only rapport `facturen-zonder-project` telt overhead mét bevroren verdeling niet
  als bevinding (was al zo; guard `tests/projecten/test_zonder_project_universal_overhead.py`: DCTE 4499/Floor Beheer 4003/Kader 4606
  gedekt → 0 bevindingen, dezelfde factuur zónder verdeling = wél bevinding). Beslispunt "(2) OVH-project Universal aanmaken" uit de
  rapporten 18-09 en 19-09 is hiermee GESLOTEN: nee. De € 1.239,05 op de twee "Afgesloten"-projecten (beslispunt 1, 19-09) blijft een
  apart klikpunt (eerst de 8 actieve "Afgesloten"-projecten afsluiten via Projecten › Afsluiten?).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 3 -->
- **Project-bronvolgorde — factuur en cachecode vóór het geheugen, geheugen altijd zichtbaar (Peter 25-09, feedbackrun A blok 3 / FV-02
  in aangepaste vorm; geen migratie; BESLISSINGEN "PROJECT-BRONVOLGORDE — FACTUUR EN CACHECODE VÓÓR HET GEHEUGEN, GEHEUGEN ALTIJD
  ZICHTBAAR (Peter 25-09)"):** het leverancier-geheugen blijft (auto-first, autoboeken) maar is voor het PROJECT de LAATSTE bron en nooit
  stil. Volgorde per regel (`regel_prefill.verrijk_prefill`): (1) projectreferentie/werknummer op de factuur — bestaand blok 10
  (`match.bepaal_project_uit_factuur`: exacte code groen > bevestigde werknummer-mapping groen > onbevestigd/fuzzy oranje); (2) klant-loze
  projectcode-herkenning op het FORMAAT van de administratie: `match.ProjectcodeFormaat.uit_kandidaten` leidt uit de projectcache de
  nummerlengtes en de tweecijferige jaarvoorvoegsels van de bestaande codes af (Universal: 3-cijferig en JJnnn mét JJ = 25/26 — nooit
  hardcoded, nooit vrije tekst; een administratie zonder cijfer-prefixen heeft een leeg formaat en slaat de stap over), `nummers_in` leest
  cijfer-tokens (3–6 cijfers, niet als deel van een bedrag/datum) uit `proj`-tekst, regelomschrijving en UBL-`cbc:Note` (sinds 25-09 als
  `note` in het UBL-veldvoorstel; `_ubl_project_tekst` valt erop terug), `bepaal_project_uit_tekst`: precies één project mét die
  cijfer-prefix (`nummer.cijfer_prefix`) → `project_bron = factuur` (groen); meerdere nummers/projecten → `factuur_meerduidig` (niets
  invullen, chip + keuze); (3) geheugen — alleen als (1)/(2) niets gaven én de regel nog geen `project_bron` draagt: gevuld mét
  `prefill_herkomst.project = leverancier_geheugen` én `project_bron = geheugen` (chip "voorstel uit historie", oranje-informatief; weg
  zodra de mens het veld aanraakt). **Conflict:** noemt de factuur een nummer in het formaat dat niet de code van het geheugen-project is
  (`match.factuur_noemt_ander_project`), dan wordt NIETS ingevuld: `project_bron = factuur_conflict` mét detail "Factuur noemt ‹nr› — …
  kies zelf" (chip "factuur noemt een ander project — kies zelf", alleen zolang het veld leeg is); bij projectplicht blijft de harde check
  "Verplichte velden" de poort. **Afgesloten/inactief:** nooit voorstellen tenzij de factuur er exact naar verwijst — stap 2 kent daarvoor
  óók de inactieve projecten (`laad_projectkandidaten(…, inclusief_inactief=True)`; het oranje signaal `check_project_afgesloten` blijft
  de waarschuwing), werknummer/fuzzy/geheugen alleen actieve; wijst alleen de historie naar een inactief project → niets,
  `project_bron = geheugen_afgesloten`. Geen bron + geen geheugen + projectplicht = leeg (check rood, bestaand). **Autoboek-pad**
  (`autoboeken.probeer_autoboeken_na_extractie`): de conflict-toets loopt per regel VÓÓR de geheugen-poort → weiger-reden "factuur noemt
  projectnummer ‹nr› — niet het geheugen-project; mens kiest het project" (audit `autoboeken_geweigerd`); een geheugen-project zonder
  conflict boekt zoals vóór 25-09 (opt-in per leverancier, alle harde checks). Frontend: `ProjectBron` + `geheugen` en `factuur_conflict`
  (`regelVoorstelChips.bepaalProjectFactuurChip`, bestaande chip-plek in de projectkolom; de generieke GeheugenChipBlok zwijgt dan).
  Meetlat: bibliotheekquery `project-prefill-herkomst` (per administratie, optioneel `project_bron`) — herkomst `leverancier_geheugen`
  zónder `project_bron` mag ná de deploy niet meer voorkomen; dispatch-onderdeel `project-bronvolgorde`. Guards
  `tests/documenten/test_project_bronvolgorde.py`, `test_project_uit_factuur.py` (inactief-regel herschreven), gouden-set-casus i
  `TestBronvolgordeProject`, keten-export casus a (RLZ-UBL: project 26084 uit `cbc:Note`), vitest `regelVoorstelChips.test.ts`.
  Werkt in productie: niet gemeten.

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 9 (FV-12) -->
- **Knop "Verdelen over projecten" mét de standaard-verdeelsleutel van de administratie (Peter 25-09, FV-12; geen migratie;
  BESLISSINGEN "COMFORT CONTROLESCHERM — BIJLAGEVERWIJZING, KOP → REGELS, REKENEN IN BEDRAGVELDEN, SPLITTER, VERDELEN-KNOP, PERIODE
  VAN–TOT (Peter 25-09)"):** naast "+ Regel toevoegen" staat bij projectplicht een `btn secondary` "Verdelen over projecten" (zelfde
  actie als de tekstknop en de lege-projectkolom-actie van 04-09). Het Projectverdeling-blok opent met de STANDAARDSLEUTEL van de
  administratie — `app/projectverdeling/service.py::standaard_sleutel`, nooit hardcoded per klant: (1) een expliciete
  administratie-instelling (bestaat nog niet; de Beheerder-tab kent alleen drempel en wachtweken — zodra die er komt wint die),
  (2) de meest gebruikte sleutel in de GEBOEKTE verdelingen van de laatste 12 maanden van die administratie (`omzet_maand` |
  `omzet_jaar` | `vaste_regels`; Universal = omzetsleutel komt zo uit de historie, besluit Peter 21-09), (3) default `omzet_maand`;
  gelijkspel = omzet_maand > omzet_jaar > vaste_regels. Veld `standaard_sleutel` op de verdeling-DTO; het blok toont "standaard voor
  deze administratie: …", de standaard staat in het geopende blok als chip en de ~20 methode-opties staan achter de `linkbtn`
  "Anders…"; de verdeling blijft achteraf aanpasbaar (bestaand). Guard `tests/projectverdeling/test_standaard_sleutel.py`, vitest
  `ProjectverdelingBlok.test.tsx`.

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
