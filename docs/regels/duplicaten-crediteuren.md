# Regels — Duplicaten en crediteuren

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Harde check "Duplicaat (module)", auto-afvoer, status `afgevoerd_duplicaat`, RLZ-/Odoo-bestaanscheck, referentie-normalisatie, nabundel-motor, crediteur-dedup en dubbelen-clusters, bulk-afvoer, medewerker-wensen 04-09.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Crediteur-dedup + duplicaat over crediteuren heen** (btw-/KvK-nummer als crediteur-kenmerk, `check_duplicaat_over_
  crediteuren`: zelfde btw-nummer = BLOKKEREND, anders ORANJE SIGNAAL; migratie 0082) — zie BESLISSINGEN "OPRUIMRUN 28-08"
  punt 14.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Crediteuren-dubbelen schaalbaar (B13 07-09; migratie 0117):** eenduidige clusters handelt het systeem af (`app/crediteuren/afhandeling.py`, dagelijks in `sync-alles`), verliezers zijn in de MODULE onbruikbaar via één bron `crediteuren/voorkeur.py` (alle voorstel-/match-/geheugen-/Odoo-partner-paden), RLZ-werklijst = optionele CSV-export, terugdraaibaar — zie BESLISSINGEN "CREDITEUREN-DUBBELEN SCHAALBAAR".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Crediteuren-dubbelen nazorg (blok 5 vervolgrun 07-09; besluiten Peter op B13-beslispunten 1/2/7):** N = 3 blijft; alleen-KvK-clusters zijn EENDUIDIG (alleen-btw blijft twijfel); legacy-werklijst eenmalig omgezet in markeringen (CLI `crediteuren-werklijst-nazorg`, live 07-09: 2 regels) — zie BESLISSINGEN "VERVOLGRUN 07-09 — BLOK 5".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Medewerker-wensen 04-09** (A duplicaat-auto-afvoer STANDAARD AAN achter één platformbrede noodrem, B splitsing
  bijlage-bewust + "nooit splitsen" per afzender, C projectverdeling pro rato omzet, D regel-niveau GB-voorstel, E
  btw-default per administratie, F bugfix Huvanco/`regelsom.py`; migraties 0105–0109) — zie BESLISSINGEN
  "MEDEWERKER-WENSEN 04-09" (canoniek per blok), mockup `projectverdeling-en-regelvoorstellen.html`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Bulk-afvoer op de Mogelijk-duplicaat-tab (B2 07-09):** checkbox + "alle N" server-side + "Afvoeren als duplicaat (n)" over de bestaande per-document-route, buiten de 20/dag-rem, uitkomst per rij — zie BESLISSINGEN "BULK-AFVOER OP DE MOGELIJK-DUPLICAAT-TAB".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Duplicaten hoofdmodel (blok 1 vervolgrun 07-09; besluit Peter "duplicaten eruit, geen lijst"):** harde check "Duplicaat (module)" tegen de EIGEN DB (sha256 / genormaliseerde referentie + bedrag over álle crediteur-records / crediteur+referentie bij ander bedrag), directe auto-afvoer (a)/(b) buiten de 20/dag-rem, mens-override alleen via afmelden mét reden, Archief-filter "afgevoerd" + Zoeken-chip, CLI `duplicaten-backfill` (live 07-09: Universal 110, Kempen Facilities 6); UBL+PDF = bundel, nooit duplicaat — zie BESLISSINGEN "DUPLICATEN HOOFDMODEL".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Herstelrun 07-09 blok A (Kempen-"duplicaten" = niet dubbel in RLZ; RLZ-duplicaatcheck cent-exact client-side; "Tegenboeken…" direct bij een geboekt module-duplicaat; RLZ negeert document-`Description` op PurchaseInvoices → kop als `Header`, afkap 200):** zie BESLISSINGEN "HERSTELRUN 07-09 — BLOK A" + api-verkenning "Description op PurchaseInvoices — STAP 0 07-09".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Duplicaten blok D herstelrun 07-09 (beeld-sha van een gebundeld document = categorie (a) zonder migratie, gesplitste delen nooit (b)/(c) zonder referentie/totaal, Odoo-crediteur zonder partner-koppeling = leesbare blokkerende check i.p.v. 500; live Universal 12 Floor-PDF's afgevoerd):** zie BESLISSINGEN "HERSTELRUN 07-09 — BLOK D".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Duplicaten-UI — eigen status `afgevoerd_duplicaat` (blok 3 bundel 08-09; migratie 0122; herziet "afgevoerd = afgewezen mét kruisverwijzing"):** telt in geen werkvoorraad-teller/-tab mee, terugvindbaar via Archief/Zoeken + toggle "Toon afgevoerde documenten", reden "automatisch (duplicaatregel)", backfill-CLI `duplicaat-status-backfill` — zie BESLISSINGEN "DUPLICATEN-UI — EIGEN STATUS `afgevoerd_duplicaat`".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Duplicaat-poort op het boekmoment + dubbele betaling + bewust verwijderd (Peter 16-09; Zenvoices-casus Hello Kitchen / Kempen Facilities; migratie 0147):** één referentie-normalisatie `app/documenten/referentie.py` (spaties tussen cijfergroepen = groepering: "2 4594 001722" ≡ "24594001722"; kolom `boekvoorstel.referentie_norm`, CLI `referentie-norm-backfill`), RLZ-/Odoo-bestaanscheck via `extern_bestaan.zoek_extern_bestaand` (kandidaten in ± 60 d over álle crediteurrecords van dezelfde identiteit, client-side genormaliseerd; zelfde referentie = blokkerend mét boekstuk, zelfde bedrag+datum = oranje) als signaal bij intake én harde check op het boekmoment/autoboek-pad, lees-only CLI `duplicaat-extern-rapport`; bank-bevinding + chip `dubbele_betaling_vermoed` (twee uitgaande betalingen, zelfde IBAN + cent-exact bedrag ≤ 60 d, niet periodiek); knop "Bewust verwijderd in RLZ" op `ontbreekt_in_rlz` (vaste reden, document → `afgevoerd_duplicaat`, terugweg "Terugdraaien…"); gouden-set-casus aa — zie BESLISSINGEN "DUPLICAAT-POORT OP HET BOEKMOMENT + DUBBELE BETALING + BEWUST VERWIJDERD (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **RLZ-bestaanscheck op het juiste moment (blok 4):** al geboekt in RLZ/Odoo = direct `afgevoerd_duplicaat` mét boekstuknummer (UBL bij intake, PDF ná extractie), geen credential = zichtbaar overgeslagen; chip "N exemplaren samengevoegd/afgevoerd" — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 4".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Rapport verwijderde documenten Universal Steigerbouw 08-09 (blok 8, alleen lezen):** 222 verwijderd "dubbel", 197 zonder ander exemplaar — zie BESLISSINGEN "RAPPORT VERWIJDERDE DOCUMENTEN UNIVERSAL STEIGERBOUW 08-09".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Nabundel-motor dubbel-exemplaren (blok 2 vervolgrun 07-09; herziet 03-09 "niet bouwen"):** byte-identieke PDF-/UBL-exemplaren uit hetzelfde intake-bericht worden samengevouwen (`samengevoegd` mét verwijzing, nooit verwijderd, terugdraaibaar); AFGEWEZEN telt als terminaal en ontgrendelt het paar; herdraai Universal Steigerbouw live 07-09 (26 paren) — zie BESLISSINGEN "B2 — NABUNDEL-MOTOR".

<!-- toegevoegd 18-09-2026, opdracht "boeken-sneller-checks-en-doorloop" -->
- **RLZ-/Odoo-bestaanscheck op het boekmoment — cache op vingerafdruk (Peter 18-09 "Boeken sneller"; migratie 0165):** de
  externe duplicaatquery (`extern_bestaan.zoek_extern_bestaand` over álle crediteurrecords van de identiteit, ± 60 d) en de
  query over crediteuren heen lopen sinds 18-09 PARALLEL met de IBAN-seed en worden per document gecachet in
  `boekhouding.check_extern_cache` op de vingerafdruk (crediteur + cluster, referentie genormaliseerd, factuurdatum, totaal,
  factuur-IBAN, boek_cyclus, backend); geldig ≤ 15 min bij gelijke vingerafdruk. De harde check "Duplicaatcheck" blijft
  blokkerend; op het boekmoment wordt het gecachete rapport alleen hergebruikt onder dezelfde voorwaarden — een retry ná
  boeken_mislukt en het autoboek-pad toetsen altijd vers tegen RLZ/Odoo. Een RLZ-fout in de query ("Duplicaatcheck kon niet
  uitgevoerd worden") blijft blokkerend en wordt nooit gecachet.

<!-- toegevoegd 22-09-2026, opdracht "ter-accordering-dagelijkse-rlz-bestaanscheck-intussen-buiten-de-module-geboekt" -->
- **De RLZ-/Odoo-bestaanscheck loopt sinds 22-09 óók dagelijks over élk OPEN document (Peter 22-09, casus Bouwadvies F/2026/01235; geen
  migratie; BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)"):** dezelfde motor
  `extern_bestaan.zoek_extern_bestaand` (alle crediteurrecords van de identiteit, ± 60 d, genormaliseerde referentie) draait in het
  reconciliatieblok `documenten` voor ter_accordering / wacht_op_iban / klaar_om_te_boeken > 1 dag — bewust ZONDER de checks-cache van 0165
  (dít is de vers-toets, één client per administratie, één keer per document per dag). Een blokkerende treffer buiten de module (zelfde
  genormaliseerde referentie, met of zonder gelijk bedrag, ook een RLZ-concept) = bevinding `intussen_extern_geboekt`; een bedrag-datum-signaal
  niet. **"Toch verschillend — doorgaan"** is de mens-uitzondering op de EXTERNE check (naast "Geen duplicaat — afmelden" op de module-check):
  tijdlijnregel `extern_duplicaat_toch_verschillend` mét de externe id's, audit, checks-cache van de crediteur ongeldig; de id reist daarna als
  uitgezonderde id mee in `check_duplicaat` (via `keten` in `boekvoorstel._extern_rapport`, `intussen_extern_geboekt.afgemelde_extern_ids`) en
  telt niet meer in de hercontrole — een NIEUW extern stuk blokkeert weer. `CheckResultaat.data["extern_geboekt"]` draagt sinds 22-09 de kern
  van de eerste treffer buiten de module (extern_id, boekstuk, referentie, stand, bedrag, datum) voor de accordering-boekfout. Storing in de
  hercontrole = géén bevinding, wél zichtbaar overgeslagen (`HERCONTROLE`-/`OVERGESLAGEN`-regels in de run).

<!-- toegevoegd 23-09-2026, opdracht "nameting-ter-accordering-bestaanscheck-na-deploy" (poging 1) -->
- **Gemeten 23-09 — de dagelijkse bestaanscheck over open documenten werkt in productie: JA (BESLISSINGEN "TER ACCORDERING — DAGELIJKSE
  BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)" alinea "Gemeten 23-09"):** run `40b5d45c` toetste 82 open documenten in 12
  RLZ-administraties vers (0 overgeslagen, geen credential-/storingsregel) en vond 11 blokkerende treffers, 10 op `match_basis` `referentie` en 1 op
  `referentie_ander_bedrag` (Bouwadvies F/2026/00053: module € 2.381,75 vs RLZ-04-00000516). Universal Steigerbouw (43 open) is in productie een
  RLZ-administratie en gaf 1 treffer (Floor Bouwliftenservice 26191 → RLZ-04-00003305, € 802,23 beide kanten). "Toch verschillend" is nog door
  niemand gebruikt (0 audits `extern_duplicaat_toch_verschillend`), dus `afgemelde_extern_ids` is in productie nog leeg — de uitzonderingsroute
  blijft "niet gemeten" tot de eerste klik (dispatch-onderdeel `extern-geboekt`).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 2 -->
- **Crediteur-naamclusters — gelijkende naam is oranje, nooit automatisch samengevoegd (Peter 25-09, FV-21 gebruikersfeedback
  Universal: `Floor Bouwliftenservice`/`Floor bouwliftenservice`, `Universal Nederland B.V.`/`Universal nederland B.V.`; geen
  migratie; BESLISSINGEN "CREDITEUR-NAAMCLUSTERS — GELIJKENDE NAAM IS ORANJE, NOOIT AUTOMATISCH SAMENGEVOEGD (Peter 25-09)"):**
  (1) **Eén normalisatie** `app/crediteuren/naam.py::normaliseer_crediteurnaam` — casefold, diakrieten weg, rechtsvorm-tokens
  (b.v./bv/b v, n.v./nv, v.o.f./vof, c.v./cv) weg, "holding" blijft ONDERSCHEIDEND (regel intake 27/28-08), leestekens en spaties
  weg → één sleutel ("floorbouwliftenservice"); gebruikt door de naam-sleutel van `dubbele_crediteuren` én door de extractie-match
  (`controle._genormaliseerd`), zodat "FLOOR BOUWLIFTENSERVICE B.V." op de factuur exact op de crediteur landt en "Jansen Holding"
  niet stil op "Jansen B.V.". Gelijkend-maar-anders ("Universal Verkoop", "Bouwadvies West") = andere sleutel = géén cluster.
  (2) **Alleen-naam = oranje.** Een cluster dat uitsluitend op de naam-sleutel matcht (geen btw/KvK/IBAN-sleutel, geen gedeeld
  KvK) is NOOIT eenduidig (`afhandeling.classificeer`, reden `REDEN_ALLEEN_NAAM`); `auto_afhandelen` slaat 'm over — het systeem
  voegt nooit samen op naam (verschillende entiteiten met gelijkende naam bestaan). Het dubbelen-scherm toont de chip
  "gelijkende naam — bevestig" (oranje `Badge warn`, `service.CHIP_NAAM_BEVESTIG`) mét de bestaande handelingen "Voorkeur kiezen…"
  (= bevestigen via `afhandelen`, bron mens) en "Geen dubbel — afmelden" (reden verplicht). KvK-conflict blijft "verschillend
  KvK — géén dubbel" mét afmelden primair. btw-/KvK-/IBAN-clusters en de grens N = 3 ongewijzigd.
  (3) **Ná bevestiging** leest alles over het cluster: verliezer → `voorkeur_vendor_id` (`crediteuren/voorkeur.py`), geheugen/
  kenmerk/IBAN's verhuisd (bestaand `handel_af`); `kandidaten_met_kenmerken` en `_raad_vendor_id` geven de voorkeur → een nieuwe
  factuur mét afwijkende schrijfwijze koppelt aan het bevestigde cluster, nooit een nieuwe crediteur. Vóór bevestiging geven twee
  bruikbare records mét dezelfde sleutel géén suggestie (nooit auto-toewijzen bij twijfel).
  (4) **Lees-only CLI** `crediteuren-naamclusters (--alles | --administratie <uuid|naamdeel>) [--detail] [--json-uit]`
  (`app/crediteuren/naamclusters_cli.py`, nameting-allowlist, dispatch-onderdeel `crediteuren-naamclusters`): per administratie
  in eigen RLS-scope clusters/crediteuren/KvK-conflict/afgemeld/bevestigd (mens), kapotte administratie = FOUT-regel, TOTAAL-regel
  eindigt op "automatisch samengevoegd op naam: 0 (nooit)". Guards `tests/crediteuren/test_naam.py`, `test_naamclusters.py`
  (élke CLI-vorm letterlijk), gouden-set-casus b `TestSchrijfwijzeFloor`, vitest `CrediteurenDubbelenScreen.test.tsx`. Werkt in
  productie: niet gemeten.

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 5 -->
- **Crediteur bewerken — kenmerk 'handmatig', IBAN uitsluitend via de wisselroute (Peter 25-09; FV-15; geen migratie; BESLISSINGEN
  "CREDITEUR AANMAKEN ALS ZIJPANEEL NAAST DE FACTUUR + CREDITEUR BEWERKEN (Peter 25-09)"):** KvK/btw uit het bewerk-paneel worden in
  `crediteur_kenmerk` opgeslagen mét bron `handmatig` (`sync/service._zet_kenmerk_handmatig`) — de bestaande regel in
  `neem_over_uit_veldvoorstel` laat een handmatig nummer nooit meer door de factuur overschrijven; een ongeldige vorm (KvK ≠ 8 cijfers,
  btw zonder proef) is een zichtbare waarschuwing, niet opgeslagen. De naam van een ándere niet-verdwenen crediteur is een 409 mét dat
  id (nooit twee gelijke namen). Vertrouwde IBAN's veranderen NOOIT via deze route: `CrediteurWijzigInput` heeft geen `iban` (422), het
  paneel toont de set lees-only en verwijst naar de IBAN-wissel/vier-ogen-route (`IbanAanbiedenVorm`); bij AANMAKEN blijft het IBAN
  meegaan als vertrouwd (bestaande regel 02-09). Meetlat `db-lezen crediteur-mutaties` (audit `crediteur_aangemaakt_in_rlz` +
  `crediteur_gewijzigd` mét oud→nieuw naast de cache-rij).

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Crediteur-dedup + duplicaat over crediteuren heen (CLAUDE.md `ed6d176` r. 374–386)

- **Crediteur-dedup + duplicaat over crediteuren heen (opruimrun 28-08 punt 14, besluiten Peter
  27-08, migratie 0082 `crediteur_kenmerk`):** de extractie leest het BTW-NUMMER (primair) en
  KvK-nummer (secundair) van de leverancier; code valideert (NL-vorm + elfproef óf mod-97 =
  "geverifieerd", `app/extractie/btw_nummer.py`), herkomst-chip bij de crediteur, opslag per
  crediteur zodra het boekvoorstel mét crediteur wordt opgeslagen (bron 'factuur', handmatig wint,
  audit). Crediteur-voorstel matcht éérst op btw-/KvK-nummer (RLZ-KvK uit de vendor-brondata als
  fallback), dan pas fuzzy op naam (Wola/Wola b.v.). Nieuwe check "Duplicaat bij andere
  crediteur" (`check_duplicaat_over_crediteuren`, Reference+bedrag zónder Entity-filter mét
  `$expand=Entity`): zelfde btw-nummer = BLOKKEREND, anders ORANJE SIGNAAL (`CheckResultaat.signaal`
  — ok, geen blokkade); de bestaande zelfde-crediteur-check blijft de harde poort. Instellingen ›
  Crediteuren = dubbel-signalering per administratie (btw/KvK/IBAN/genormaliseerde naam) mét
  KvK-controle (hergebruik A3-client) — samenvoegen blijft RLZ-mensenwerk, wij verwijderen niets.
  `app/documenten/crediteur_kenmerk.py`; BESLISSINGEN "OPRUIMRUN 28-08" punt 14.

### Domeinbeslissingen — Medewerker-wensen 04-09 (A–F) (CLAUDE.md `ed6d176` r. 387–419)

- **Medewerker-wensen 04-09 (besluiten Peter 04-09; mockup `projectverdeling-en-regelvoorstellen.html` = norm
  voor C/D/E incl. notities ①–⑨; migraties 0105–0108 — BESLISSINGEN "MEDEWERKER-WENSEN 04-09" is canoniek per blok):**
  (A) **Duplicaat-auto-afvoer** — harde match (crediteur op btw-nummer + referentie + bedrag; origineel geboekt óf
  ouder in de werkvoorraad) → automatisch "Afgewezen — duplicaat van …" mét kruisverwijzing beide kanten, audit,
  tijdlijn; **sinds blok A1 04-09 (besluit Peter, migratie 0109) STANDAARD AAN voor de hele module achter één
  platformbrede noodrem** `platform.duplicaat_afvoer_instelling` (Instellingen › Boeken, `make duplicaat-autoafvoer-uit
  BEHEERDER_ID=`; de per-administratie-toggle van 0105 is vervallen, kolom blijft) + volumerem 20/dag; **blok A2: een hard
  duplicaat bij de klant-accordeur of met een open vraag wordt óók afgevoerd — ronde vervalt en vraag sluit mét reden
  "afgevoerd als duplicaat van ‹ref›" (slotbericht in de thread, buiten de configuratie-banner), alleen geboekt/
  boeken_mislukt/wacht_op_iban nooit;** één-klik "Afvoeren als duplicaat" (rijmenu + controlescherm) altijd; zachte
  signalen voeren nooit af; terughalen = heropenen (`app/documenten/duplicaat_afvoer.py`). (B) **Splitsing bijlage-bewust** (schemaveld `fp` = integer,
  code rekent bijlagepagina's; "factuur + N bijlagepagina's" in het voorstel) + **"nooit splitsen" per afzender**
  (`intake_splitsing_uitsluiting`, geleerd via "Is één factuur" mét vink, kantoorbrede match vóór de AI-call, beheer
  op de detailpagina tab Algemeen "Intake-regels"; `app/intake/splitsing_uitsluiting.py`). (C) **Projectverdeling
  pro rato omzet** BINNEN de administratie (`app/projectverdeling/`): vaste regels + restant naar rato van de geboekte
  verkoopomzet van de vorige maand (projectcijfers-cache; omzetloos/OVH uit; grootste-rest-centen; omzetstanden
  bevroren bij boeken), **beschikbaar op élk inkoopdocument van een administratie mét projectplicht/actieve projecten
  (addendum 04-09 blok B: lege project-kolom biedt "Verdelen over projecten…" aan, `openVerzoek`; de check
  "Verplichte velden" benoemt de actie)**, per-leverancier-opt-in `projectverdeling_pro_rato` = uitsluitend
  PREFILL-trigger (geen poort), harde check "Projectverdeling", RLZ =
  regels splitsen / Odoo = `analytic_distribution`, maandelijkse hercontrole in `sync-alles` (drempel
  `projectverdeling_drempel_pct` 5 %) mét actie "Herverdelen…" (= bestaand tegenboek-én-opnieuw-boeken, mens
  bevestigt); flankerend "inkoop zonder omzet" pas ná `inkoop_zonder_omzet_wachtweken` (4). (D) **Regel-niveau
  GB-voorstel**: regel-geheugen op (crediteur-kenmerk, genormaliseerde omschrijving) uit `boeking_observatie` (groen
  "uit geheugen"; seed-only oranje) → AI-classificatie uitsluitend uit de historische GB's van de leverancier (≥ 2
  kandidaten, achter AI-gate + kostenmeter, persistent in `regel_gb_classificatie`, oranje "AI-voorstel — bevestig")
  → leeg; autoboek-slot wordt er nooit groen van (`app/geheugen/regel_gb.py`, `documenten/regel_prefill.py`).
  (E) **Btw-default per administratie** `standaard_taxrate_id` (Beheerder, default UIT): factuur → geheugen →
  default (chip "standaard administratie") → leeg — **blok A3 04-09 (besluit Peter): een door de scan BEWUST leeg
  gelaten 0 %-/ambigu-veld (`btw_afleiding_reden` btw_nul/meerduidig/geen_match → `btw_bewust_leeg`) wordt níét door de
  default gevuld; de default vult uitsluitend velden waarvoor scan én geheugen niets hadden.** (F) **Bugfix Huvanco**: kortingsregels als negatieve regel (prompt +
  UBL `AllowanceCharge`), regeltelling via één gedeelde beslisboom `documenten/regelsom.py` (netto-vs-excl,
  netto+btw-vs-incl, nooit stil excl-vs-incl; lege btw = 0 alleen op een gesynct 0%-tarief).

<!-- toegevoegd 21-09-2026, opdracht "BUG-iban-wissel-blijft-blokkerend-na-vier-ogen-akkoord-checks-cache" -->
- **Crediteur-samenvoegen maakt de externe checks-cache ongeldig (BUG Peter 21-09; geen migratie; BESLISSINGEN "CHECKS-CACHE —
  INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09"):** `crediteuren/service.verhuis_ibans` kopieert de vertrouwde IBAN's van de verliezer
  naar de voorkeur en roept in dezelfde transactie `checks_extern.maak_ongeldig_voor_vendor` aan voor voorkeur én bron — de
  vertrouwde set van de voorkeur is veranderd, dus een gecacht extern rapport (0165) van een document op die crediteur mag niet meer
  gelezen worden. De invalidatie raakt álle documenten van het identiteitscluster (`duplicaat_module.identiteit_vendor_ids`: zelfde
  vendor/voorkeur-cluster, KvK- óf btw-nummer). Guard `tests/unit/test_leverancier_iban_invalidatie_guard.py`: élke module die een
  `LeverancierIban(`-rij construeert (leverancier_iban, iban_accordering, crediteuren/service) draagt de invalidatie; een nieuwe
  schrijver moet daar bewust worden toegevoegd.
