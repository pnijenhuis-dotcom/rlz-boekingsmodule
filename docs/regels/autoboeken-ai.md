# Regels — Automatisch boeken, autoboek-kandidaten en de AI-plausibiliteitstoets

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Opt-in per leverancier en per administratie (leren ná drie identieke mens-boekingen), harde checks blijven blokkerend, volumerem, AI-toets als extra poort mét uitval = doorlopen zichtbaar, autonomie-toekomstlijn.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Automatisch boeken = opt-in per leverancier**; harde checks blijven áltijd blokkerend.
  **Status per harde/blokkerende check: canoniek in `docs/BESLISSINGEN.md` (verplichte eerste
  check, houd dáár actueel — gedocumenteerd ≠ gebouwd).** De korte opsomming van gebouwde checks, de
  per-leverancier-autoboeken-opt-in (GEBOUWD + GETEST 2026-08-09, migratie 0036 + `app/documenten/autoboeken.py`),
  de autoboek-kandidaten-motor (`app/autoboek_kandidaten/`, migratie 0095) en het principe **Automatisering-first
  (Peter, 2026-08-16, WERKWIJZE v1.10): mens-op-de-knop is een testfase-drempel en afwijkings-vangnet, geen
  einddoel — elk deterministisch pad krijgt een autoboek-opt-in volgens het vaste patroon (default UIT, harde
  checks blokkerend, volumerem, 'automatisch'-markering + audit, storno als terugweg)** staan in BESLISSINGEN
  "Harde/blokkerende checks", "AUTOBOEK-KANDIDATEN-MOTOR", "Autoboek-afweging overige deterministische paden" en het
  archief "Automatisch boeken".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Bank: historie-regel + AI-plausibiliteitstoets als poort (blok B bundel 10-09, besluit Peter 10-09; migratie 0129):** stap 3b `historie_regel` (IBAN + omschrijvingskern, bedrag vrij, ≥ 6 mnd dekking, ≥ 3 boekingen, 100 % = groen/automatisch kandidaat, k van n = oranje, nooit bij open posten voor de tegenpartij; cache `bank_historie_boeking`, backfill-CLI `bank-historie-backfill`) + `app/aitoets/plausibiliteit.py` als POORT vóór élke automatische bankboeking (vaste regel én historie; AVG-gate/API-key/kostengrens/AI-fout = zichtbaar overgeslagen, twijfel = open mét chip, audit per toets, sentinel-schema 0 unions) en optioneel op factuur-autoboekingen (`boeken_instelling.ai_toets_facturen_ingeschakeld`, default AAN, `GET/PUT /instellingen/boeken/ai-toets`); nameting `bank-voorstellen-lezen --met-ai-toets` — zie BESLISSINGEN "BANK — HISTORIE-REGEL + AI-PLAUSIBILITEITSTOETS ALS POORT"

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **AI-plausibiliteitstoets — uitval = doorlopen, zichtbaar (blok 4 vervolgrun 10-09 avond; besluit Peter 10-09; herziet de poort-semantiek van blok B; geen migratie):** technische uitval van de toets (AVG-gate uit, geen API-key, kostengrens, AI-fout) houdt geen automatische bank- of factuurboeking meer tegen — de deterministische poorten blijven de eis, de boeking draagt chip "zonder AI-toets" (`PlausibiliteitUitkomst.zonder_ai_toets` + `oorzaak`), audit `ai_plausibiliteitstoets` mét oorzaak + `automatisch_geboekt_zonder_ai_toets`, teller `ai_toets_overgeslagen` en een LET-OP "controleer steekproefsgewijs" mét deeplink; `twijfel` blijft NIET boeken, de AVG-gate blokkeert alleen de AI-call — zie BESLISSINGEN "AI-PLAUSIBILITEITSTOETS — UITVAL = DOORLOPEN, ZICHTBAAR".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Autoboeken per administratie — leren en boeken (blok A bundel 10-09, besluit Peter 10-09; herziet "kandidaten → mens klikt aan" 01-09; migratie 0128):** één Beheerder-schakelaar per administratie (default UIT, doorbelasting = 409), het systeem ACTIVEERT de per-leverancier-opt-in zelf ná ≥ 3 mens-boekingen op rij ongewijzigd (`autoboek_kandidaten/service.py::activeer_kwalificerend`, post-commit ná élke mens-boeking + dagelijks), per-leverancier-lijst = uitzonderingenlijst (uitzonderen mét reden / vrijgeven), storno/correctie van een automatische boeking = terug op "leert 0/3" (audit + tijdlijn), B3-AI-toets als extra poort, teller `autoboek_leren` + CLI `autoboek-leren-rapport` (lees-only meetrecept) — zie BESLISSINGEN "AUTOBOEKEN PER ADMINISTRATIE — LEREN EN BOEKEN"

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **AI-toets platform-opt-out zichtbaar (blok 3.2 nametingen-run 10-09 avond, besluit Peter; geen migratie):** `ai_toets_facturen_ingeschakeld` = UIT is niet meer stil — chip "AI-toets uit (platform)" + tijdlijnregel op elke automatische factuurboeking, teller `ai_toets_uit` en LET-OP "AI-toets staat platformbreed uit sinds <datum>" (actiemail, deeplink Instellingen › Boeken; óók bij 0 boekingen); mens-zette-uit ≠ toets-viel-uit (`PlausibiliteitUitkomst.ai_toets_uit` vs `zonder_ai_toets`) — zie BESLISSINGEN "AI-TOETS PLATFORM-OPT-OUT ZICHTBAAR".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Autoboeken — drempel telt drie identieke mens-boekingen (blok 3 vervolgrun 10-09 avond; besluit Peter 10-09; herziet de telling van blok A; geen migratie):** de reeks = langste staart van opeenvolgende mens-boekingen met onderling gelijke GB/btw/project (eerste boeking = 1/3, afwijkende boeking start een nieuwe reeks, automatisch telt niet en breekt niet, `reeks_vanaf` blijft), correcties blijven t.o.v. het voorstel gemeten en de service toetst dat het geheugen dezelfde waarden voorstelt als de reeks (`Reeks.reeks_waarden`); teksten "N identieke boekingen"; open beslispunt: één afwijkende boeking maakt de geheugen-stem blijvend "gesplitst" (oranje) — zie BESLISSINGEN "AUTOBOEKEN — DREMPEL TELT DRIE IDENTIEKE MENS-BOEKINGEN".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Autonomie-toekomstlijn (ontwerpnotitie blok E bundel 10-09, geen bouw; wacht op akkoord Peter):** vijf richtingen (1 boekhouden op uitzondering, 2 AI schrijft deterministische regels + backtest, 3 leren over administraties heen op RGS-niveau, 4 nachtelijke AI-onderzoeker, 5 AI-auditor-steekproef → foutkans) met volgorde-advies 2 → 5 → 3 → 4 → 1, harde grens "AI kiest nooit een rekening zonder deterministische toets; AI-uitval = doorlopen zonder AI, zichtbaar" — canoniek `docs/ONTWERP_AUTONOMIE_TOEKOMST.md`, zie BESLISSINGEN "ONTWERPNOTITIE AUTONOMIE-TOEKOMSTLIJN".

<!-- toegevoegd 18-09-2026, opdracht "SPOED-volumerem-alleen-automatisch" -->
- **Volumerem — alleen automatisch (SPOED Peter 18-09: "Dagelijkse limiet van 20 boekingen bereikt voor deze administratie" bij het
  HANDMATIG boeken van 180 BLOW-bonnen; geen migratie; BESLISSINGEN "VOLUMEREM — ALLEEN AUTOMATISCH (Peter 18-09)"; herziet punt 23
  opruimrun 28-08 voor de ná-klant-akkoord-rem):** (1) de 20/dag-rem `max_boekingen_per_dag_per_administratie` geldt UITSLUITEND voor
  automatische boekingen (autoboek-opt-ins, autoboek-kandidaten-activering, bank-auto-afletteren/-boeken, verkoop/Vastly-autoboek,
  omzet-auto, waarborg via systeem-actor, doorbelasting-spiegel die uit een automatische bron volgt); de teller telt alleen
  overgangen → geboekt mét de bestaande 'automatisch'-markering (`automatisch_geboekt` in het overgangsdetail; bank: `geboekt_door` =
  systeem-actor); een pad mét systeem-actor zónder markering telt óók als automatisch — nooit als mens. (2) Handmatig boeken
  (kantoor-actor op de knop, incl. bulk-selectie in de lijst) krijgt een eigen hoge noodrem
  `max_handmatige_boekingen_per_dag_per_administratie` = 500 (env-overschrijfbaar), tekst "Noodrem: N van 500 handmatige boekingen
  vandaag in deze administratie — neem contact op met de Beheerder", zichtbaar in het scherm (429) én in de reconciliatiemail
  (categorie `noodrem` = LET-OP). (3) Ná een compleet klant-akkoord (punt 23) geldt DEZELFDE 500-noodrem — één mens-teller (alle
  niet-automatische overgangen), één limiet; de setting `max_boekingen_na_klant_akkoord_per_dag_per_administratie` (200) is
  VERVALLEN (blijft leesbaar voor oude env-sets, stuurt niets meer). (4) Élke melding noemt de rem, de teller én de handeling —
  "Volumerem automatisch boeken: 20 van 20 automatische boekingen vandaag in deze administratie · handmatig boeken kan gewoon door";
  nooit alleen "limiet bereikt". (5) Alle remmen lopen via ÉÉN helper `app/documenten/volumerem.py` (`bepaal_herkomst`, `limiet_voor`,
  `melding`, `toets`, `toets_documentboekingen`, `toets_bankboekingen`): `documenten/boeken.py`, `omzet/boeken.py`, `verkoop/boeken.py`,
  `waarborg/boeken.py`, `doorbelasting/boeken.py` (herkomst reist mee vanuit de orkestratie; de doorbelastings-teller blijft de eigen
  dagteller — geen actor-kolom), `bank/boeken.py`, `bank/relatie.py`, `bank/afletteren.py` (altijd automatisch) en de herstel-CLI
  (`accordering/herstel.py`, env-naam per herkomst in de tekst). Bestaande bugfix "alleen échte overgangen" blijft. Guard
  `tests/documenten/test_volumerem.py`. De tijdelijke env-var `MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE=500` op de service (klikpunt
  Peter vóór de deploy) stond op 18-09 ~15:45 NIET op de service en hoort NIET in deploy.yml — de code-fix maakt hem overbodig.

<!-- toegevoegd 18-09-2026, opdracht "boeken-sneller-checks-en-doorloop" -->
- **Harde checks — cache-regel voor het externe deel (Peter 18-09 "Boeken sneller"; migratie 0165; BESLISSINGEN "BOEKEN
  SNELLER — CHECKS-CACHE + ACHTERGROND-SCHRIJVER (Peter 18-09)"):** de harde checks blijven server-side en blokkerend — ze worden
  alleen niet twee keer met DEZELFDE externe invoer gedraaid. Het externe deel (IBAN-seed, RLZ-/Odoo-duplicaatquery, kandidaten
  ± 60 d) wordt per document gecachet op de externe vingerafdruk (`app/documenten/checks_extern.py`) en bij boeken hergebruikt
  als de vingerafdruk gelijk is én het rapport ≤ 15 min oud is; een **boeken_mislukt-retry en het autoboek-pad
  ('automatisch'-markering) draaien ALTIJD vers** (`boeken.extern_checks_modus`); een storing wordt nooit gecachet. Autoboek-
  pad en accordering-staande-goedkeuring blijven op de synchrone `boek_document` (één schrijfroute, geen 202-shortcut);
  de menselijke boekknop gaat via de achtergrond-schrijver (`boek_wachtrij.py`) mét dezelfde poorten vóór `wordt_geboekt`.

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Automatisch boeken (checks-opsomming, per-leverancier-opt-in, autoboek-kandidaten-motor, automatisering-first) (CLAUDE.md `ed6d176` r. 438–480)

- **Automatisch boeken = opt-in per leverancier**; harde checks blijven áltijd blokkerend.
  **Status per harde/blokkerende check: canoniek in `docs/BESLISSINGEN.md` (verplichte eerste
  check, houd dáár actueel — gedocumenteerd ≠ gebouwd).** Kort: duplicaat, regeltelling (sinds 04-09 basis-expliciet, `regelsom.py`),
  verplichte velden, IBAN-wissel, duplicaat-bij-andere-crediteur (btw-nummer + referentie + bedrag,
  28-08 — Reference+bedrag zonder btw-match = oranje signaal), vraag-blokkeert-boeken,
  afwijzen-met-verplichte-reden en
  webhook-HMAC-per-verzendpoging (mét afleveraar, 2026-08-02), memoriaal-saldo-0
  (omzetmodule, 2026-08-07), het VGB-prefixfilter (e-mail-intake, 2026-08-07 — dekt het
  intake-kanaal; bij een latere leesroute uit gedeelde administraties dáár opnieuw toepassen)
  én btw-per-regel-=-factuur-btw (verkoop, blok A 2026-08-10 — categorie {S/E/Z/AE} + bedrag,
  eenhedennormalisatie fractie↔percentage in `app/sync/btw.py`, btw in het verkoopvoorstel
  auto-ingevuld + VERGRENDELD, ambiguïteit = eenmalige onthouden keuze per administratie,
  migratie 0038) én nooit-boeken-op-ankerdebiteur (route-A-nazorg 2026-08-14: verkoop-checks
  + `zorg_voor_debiteur`-slot + doorbelasting-whitelist-toets, bron `app/projecten/anker.py` —
  sinds de klant-loze schrijfroute (zelfde dag) een VANGNET: de motor maakt geen ankers meer
  aan, de checks blijven zolang er ergens een anker-debiteur bestaat)
  zijn gebouwd + getest; **per-leverancier-autoboeken-opt-in: GEBOUWD + GETEST (2026-08-09,
  migratie 0036 + `app/documenten/autoboeken.py`)** — boekt ná extractie uitsluitend bij
  opt-in aan (Beheerder-only, default UIT) + harde checks groen + voorstel volledig uit
  app-bevestigd boekingsgeheugen (seed-only/oranje weigert) + geen mogelijk-duplicaat/open
  vraag/afwijzing; volumerem en accorderingspoort onverkort; elk geval geauditeerd +
  tijdlijn-/werkvoorraadmarkering "automatisch". NB bank-autoboeken (opt-in per
  administrátie, vaste regels) staat hier los van (live sinds 2026-08-02).
  **Autoboek-kandidaten-motor (blok B 01-09, mockup `autoboek-kandidaten.html` = norm, migratie
  0095 — BESLISSINGEN "AUTOBOEK-KANDIDATEN-MOTOR" is canoniek):** `app/autoboek_kandidaten/` nomineert
  deterministisch (geen AI, geen RLZ-calls) per (administratie, leverancier) bij ≥ N opeenvolgende
  MENS-boekingen waarbij het geheugen-voorstel ongewijzigd is geboekt (N = Beheerder-instelling,
  default 5; correctie = teller opnieuw; automatisch telt niet) + volledig app-bevestigd geheugen +
  geen open vraag/afwijzing/duplicaatsignaal/veldwerker-koppeling. Dagelijks meeliftend in
  `sync-alles` (+ CLI `autoboek-kandidaten-herbereken`); scherm = het Autoboeken-nav-item
  (tabs Kandidaten/Actief/Heroverwegen, bulk "Autoboeken aanzetten (n)" mét LIVE hertoets per
  rij — niet meer kwalificerend = overgeslagen mét reden — via de BESTAANDE opt-in-schrijver;
  "Kandidaat verbergen" = snooze mét verplichte reden, filter "verborgen"; Heroverwegen =
  advies-only, uitzetten één klik mét audit). De per-leverancier-switch blijft op de
  administratie-detailpagina (tab Boeken & AI).
  **Automatisering-first (principe Peter, vastgelegd 2026-08-16, WERKWIJZE v1.10):
  mens-op-de-knop is een testfase-drempel en afwijkings-vangnet, geen einddoel — elk
  deterministisch pad krijgt een autoboek-opt-in volgens dit vaste patroon (default UIT,
  harde checks blokkerend, volumerem, 'automatisch'-markering + audit, storno als terugweg).
  Derde afnemer: verkoop-autoboeken (2026-08-16, zie "Verkoopfactuur-boekpad"); vierde:
  omzet-autoboeken (GO Peter 01-09, zie "Omzetboekingen"); doorbelasting-spiegels blijven
  gedocumenteerd-geparkeerd in BESLISSINGEN ("Autoboek-afweging overige deterministische
  paden") — bouw vergt apart akkoord.**

<!-- toegevoegd 21-09-2026, opdracht "BUG-iban-wissel-blijft-blokkerend-na-vier-ogen-akkoord-checks-cache" -->
- **Cache-regel aangescherpt — extern gecachet = RLZ-roundtrips, álle lokale toetsen draaien vers (BUG Peter 21-09; geen migratie;
  BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09"):** wat per document op vingerafdruk gecachet wordt
  (≤ 15 min) zijn uitsluitend de RLZ-/Odoo-roundtrips: de IBAN-seed (`BankRelations`) en de duplicaatquery's (referentie per
  crediteurrecord, kandidaten ± 60 d, over crediteuren heen). Álle lokale toetsen — de IBAN-wissel tegen de vertrouwde set, het
  module-duplicaat, btw/regeltelling/verplichte velden — draaien bij élke checks-run én op het boekmoment vers tegen de eigen database;
  de IBAN-wissel gebruikt de live set ∪ de seed-uitkomst uit de cache. Een mutatie van de vertrouwde set (vier-ogen-akkoord,
  bevestiging, seed/baseline, crediteur-samenvoegen) maakt de cache in dezelfde transactie ongeldig én verandert de vingerafdruk
  (set-hash), zodat boeken direct ná een akkoord binnen de 15 min slaagt zonder `boeken_mislukt`-retry of autoboek-markering. Retry
  ná boeken_mislukt en het autoboek-pad blijven ALTIJD vers (`boeken.extern_checks_modus`); een storing wordt nooit gecachet.
  Regel voor élke volgende cache in dit domein: eerst de lijst "welke handelingen maken dit ongeldig", dan pas de tijdsgeldigheid.
