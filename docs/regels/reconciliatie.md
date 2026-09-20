# Regels — Reconciliatie, bewaking en meldingen

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Dagelijkse reconciliatie-blokken (documenten, bank, omzet, doorbelasting, intercompany, RC, rlz_dubbel, dubbele betaling), tellers per automatisering, actiemail + systeemmail, synthetische bewaking, bevindingssoorten in `meten`.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie `rlz_dubbel` alleen op referentie (blok 7):** bedrag+datum vervallen, placeholder-referenties tellen als leeg; BOOT 202632703/04 = aanvaarde grens — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 7".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Synthetische bewaking + alerting** (job `rlz-bewaking` elk kwartier, `app/bewaking/`, post-deploy-smoketest;
  migratie 0092) — zie BESLISSINGEN "SYNTHETISCHE BEWAKING + ALERTING".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie-melding + Inzicht › Reconciliatie** (`reconciliatie-alles`, mail alleen als er iets te melden is,
  `/reconciliatie`; migratie 0114) — zie BESLISSINGEN "RECONCILIATIE-MELDING + INZICHT".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie 07-09 (A11/A12/A8):** verdwenen extern document = `ontbreekt_in_rlz`/`ontbreekt_in_odoo` (zwaarste categorie) mét actie "Opnieuw boeken" zonder tegenboeking (`app/documenten/herboeken.py`, GEBOEKT → KLAAR_OM_TE_BOEKEN, boek_cyclus +1); documenten-blok backend-agnostisch via `InkoopPort.toets_geboekt` (Odoo: posted/amount_total/onbekende reversal), bank/omzet/doorbelasting blijven RLZ-only en slaan Odoo-administraties zichtbaar over; bevindingen leesbaar (titel/wat/doe, `app/reconciliatie/teksten.py`) en acceptatie direct zichtbaar — zie BESLISSINGEN "A11 — DOCUMENTEN-RECONCILIATIE", "A12 — RECONCILIATIE BACKEND-AGNOSTISCH", "RECONCILIATIE-TEKSTEN LEESBAAR + ACCEPTATIE-BUG".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie-herzieningen vervolgrun 07-09 (blok 3 + 4, correcties Peter):** herboeken van een verdwenen document BLOKKEERT als de boekdatum in een ingediende btw-periode valt ("btw mogelijk al aangegeven — suppletie-pad", 409); alleen een Beheerder zet door met expliciete bevestiging + reden (audit + tijdlijn); Odoo-variant via lock dates; fail-closed bij onleesbare aangiftestatus — A11-rij "Volumerem / aangifte-poort — HERZIEN 07-09". RLZ-verleden van een overgestapte administratie wordt tegen RLZ getoetst via de bewaarde credential (`client_voor_rlz_verleden`), nooit meer "niet van toepassing" — zie BESLISSINGEN "RLZ-VERLEDEN VAN EEN OVERGESTAPTE ADMINISTRATIE".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Tellers per automatisering in de reconciliatie (blok 3 herstelrun 07-09):** per automatisering per etmaal verwacht/gedaan/overgeslagen mét reden uit bestaande audit-/run-sporen (`app/reconciliatie/automatiseringen.py`, geen migratie), LET-OP mét deeplink bij een ontbrekende harde voorwaarde en bij zeven dagen stil; uit = één regel — zie BESLISSINGEN "TELLERS PER AUTOMATISERING IN DE RECONCILIATIE".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Automatiserings-tellers weg van het werkscherm (blok 5 bundel 08-09; feedback Peter "wat moet ik hiermee"; geen migratie):** het blok "Automatiseringen" staat op Instellingen › Boeken platformbreed (één regel "N aan · M let-op", open bij LET-OP mét "Naar de instelling →", uit-regels niet getoond, sleutel-agnostisch), Inzicht › Reconciliatie toont alleen bevindingen mét handeling, de mail draagt het volledige blok alleen bij een LET-OP (anders "Automatiseringen: alles gelopen (N aan)"); productie 08-09: de LET-OP "duplicaat-afvoer 155× geen eigenaar" stamt van vóór 0121 (laatste weigering 07-09 16:57) en verdwijnt bij de run van 09-09 — zie BESLISSINGEN "AUTOMATISERINGS-TELLERS WEG VAN HET WERKSCHERM".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatiemail = ACTIEMAIL + SYSTEEMMAIL (blok 1 bundel 09-09, feedback Peter 09-09 "veel te veel input"; geen migratie):** kantoor krijgt alleen bij bevindingen mét handeling één mail "N zaken vragen je aandacht" (één regel per zaak, één link naar /reconciliatie, max 10 + "en N andere", guard-test `tests/reconciliatie/test_actiemail_guard.py`); de volledige inhoud gaat als "[systeem] …" naar setting `reconciliatie_beheer_ontvangers`; regressie-LET-OPs (o.a. `geen_eigenaar`) = "Systeemfout — automatisch gemeld" + audit `automatisering_regressie` + bewakingsprobe — zie BESLISSINGEN "RECONCILIATIEMAIL = ACTIEMAIL + SYSTEEMMAIL".
<!-- bundel-10-09:E -->
<!-- bundel-10-09:A -->
<!-- bundel-10-09:B -->
<!-- bundel-10-09:C -->
<!-- bundel-10-09:D_backend -->
<!-- bundel-10-09:D_docs -->
<!-- bundel-10-09:F -->

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie-nazorg 15-09 (besluiten Peter 14/15-09 "systeem bepaalt of actie nodig is", "kunnen de mails uit?"; geen migratie):** bedragverschil ≤ € 0,05 op een geboekt document = automatisch geaccepteerd mét audit `reconciliatie_auto_geaccepteerd` + dagteller; cent-fix aan de bron (`regelsom.py::corrigeer_btw_centen`, laatste btw-dragende regel, alleen in wat naar RLZ gaat, storno spiegelt); genormaliseerde referentie < 3 tekens = placeholder in `rlz_dubbel`; systeemmail alleen bij LET-OP/systeemfout/blok-fout en code-default ontvangerslijst LEEG (status `uitgeschakeld`, actiemail kantoor ongewijzigd) — zie BESLISSINGEN "RECONCILIATIE-NAZORG 15-09 — AFRONDING ≤ 0,05, CENT-FIX AAN DE BRON, KORTE REFERENTIES, SYSTEEMMAIL ALLEEN BIJ LET-OP".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Intercompany-factuurmatch + RC-aansluiting (Peter 16-09; migratie 0148):** identiteit per administratie uit RLZ `AdministrationSettings` (KvK + naam; géén btw in RLZ) / Odoo `res.company`, IC-relaties AFGELEID (kvk > btw > naam; doorbelasting-rijen = bevestigd; naam-only pas actief ná Beheerder-bevestiging) en RC-koppelingen afgeleid uit balansrekeningnamen (+ Beheerder-afkortingen), Beheerder-blok op Instellingen › Boeken (`app/intercompany/`, `IntercompanyRelaties.tsx`); twee dagelijkse reconciliatieblokken ná documenten: `intercompany` (verkoop bij A ↔ inkoop bij B per actief paar: nummer_norm > bedrag+datum ±7 d > bedrag; soorten `ic_ontbreekt_bij_ontvanger`/`_verkoper`, `ic_bedrag_verschilt`, `ic_status_verschilt` > 7 d; "onderweg in module" ≠ bevinding; doorbelastingspaar rood = systeemfout `automatisering_regressie`) en `rekening_courant` (saldo_a + saldo_b = 0 via `JournalEntryLines` Debit−Credit / Odoo `account.move.line`; Δ mét verklaring welke mutatie aan welke kant ontbreekt, ±5 d, nooit raden; `rc_stand` als vensterbegin); lees-only, webfilter = meting ongeldig, meetlatten `reconciliatie-alles --alleen intercompany|rekening_courant --lees-only` — zie BESLISSINGEN "INTERCOMPANY-FACTUURMATCH + RC-AANSLUITING (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Dubbele betaling — herdefinitie + bevindingssoorten starten in `meten` (SPOED Peter 17-09 "en 1204 andere — hier doe ik niks mee"; migratie 0153):** dubbel betaald = betalingen > facturen van de crediteur (± 30 d, drie eigen caches, dedup), periodiek (week…jaar-patroon, incasso, terugkerend) = nooit, `sterk` bij één betaling zonder RLZ-document; élke nieuwe bevindingssoort start in stand `meten` (registry `app/reconciliatie/soort_stand.py`, facet "in meting", nooit actiemail/KPI) tot Beheerder-promotie (`PUT …/instelling/soort-stand`, CLI `bevindingssoort-stand`), explosie-rem > 50/run → terug naar meten + systeemfout-LET-OP, actiemail ≤ 3 regels per administratie mét teller in de afkap, verdwenen oude bevindingen = audit `reconciliatie_auto_gesloten` — zie BESLISSINGEN "DUBBELE BETALING — HERDEFINITIE: BETALING ZONDER FACTUUR + BEVINDINGSSOORTEN STARTEN IN METING (Peter 17-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie-blok `rlz_dubbel` (blok 6 bundel 08-09; advies, schrapbaar in twee regels):** per RLZ-administratie PurchaseInvoices laatste 400 dagen, paren binnen dezelfde crediteur op genormaliseerde referentie en/of cent-exact bedrag + datum, nooit als beide van de module (UUIDv5), bevinding `dubbel_in_rlz` mét beide boekstuknummers, geen automatische actie — zie BESLISSINGEN "RECONCILIATIE — PERIODIEKE TOETS 'MOGELIJK DUBBEL GEBOEKT IN RLZ'".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Reconciliatie `rlz_dubbel` — clusters + referentie-classificatie (blok 1 vervolgrun 10-09 avond; herziet "RECONCILIATIE — PERIODIEKE TOETS" + blok 7; geen migratie):** één bevinding per crediteur + genormaliseerde referentie (álle boekstuknummers, vingerafdruk `cluster=<rlz_admin>|<entity>|<ref>`), referenties die een IBAN, een klant-/contractnummer (≥ 3× met ≥ 2 bedragen) of een placeholder zijn worden mét teller uitgesloten (`app/reconciliatie/referentie_classificatie.py`), rangorde "Waarschijnlijk dubbel in RLZ" (twee concepten, zelfde dag, zelfde bedrag) vs "Zelfde referentie, controleer", overgang oud → cluster zonder migratie (open paar-bevindingen vervangen onder eigen vingerafdruk, paar-acceptaties overgedragen), lees-only meetlat `reconciliatie-alles --alleen rlz_dubbel --lees-only [--administratie …]` — zie BESLISSINGEN "RECONCILIATIE RLZ_DUBBEL — CLUSTERS EN REFERENTIE-CLASSIFICATIE".

<!-- toegevoegd 19-09-2026, opdracht "kassarapport-automatisch-type-wijzigen-en-reconciliatie-acties-automatiseren" -->
- **Patroon "vaststaande actie = het systeem doet het" (Peter 19-09; BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING
  ZONDER HANDELING SWEEP (Peter 19-09)"):** is de actie op een bevindingssoort deterministisch én altijd dezelfde (de knop doet
  precies één ding, zonder mens-oordeel), dan is de melding een testfase-drempel die voorbij is (principe 7 (2)+(3)): het systeem
  voert de actie zelf uit volgens het vaste patroon — doen + tijdlijnregel + audit per document + terugweg mét verplichte reden +
  leren van de terugweg (ná 2 correcties op dezelfde sleutel weer melden) + dagteller verwacht/gedaan/overgeslagen in de
  reconciliatiemail; opt-out per administratie alleen als testfase. Eerste afnemer: `kassarapport_in_werkvoorraad` bij een
  parser-treffer (`app/omzet/autotype.py`, zie `docs/regels/omzet.md`). Een soort waarvan de actie een oordeel vraagt (accepteren
  mét reden, herboeken achter de aangiftepoort, storno) blijft een melding. De sweep over álle bevindingssoorten in productie
  (aantal open, actie, deterministisch ja/nee, voorstel per soort — incl. de 174 "fouten" en de 492 "in meting" van 19-09) staat als
  agenda in het rapport `docs/rapporten/2026-09-19-kassarapport-autotype-en-signalering-sweep.md`; niets daarvan is gebouwd buiten
  de kassarapport-typering.

<!-- toegevoegd 19-09-2026, opdracht "projectnummer-uit-afgesloten-naam" -->
- **Blok `projecten` — `project_nummer_dubbel` telt óók "Afgesloten NNNNN …"-namen (19-09; geen migratie):** de bevindingssoort
  gebruikt sinds 19-09 dezelfde nummerlezer `nummer.cijfer_prefix` die door het afsluitwoord van Universal heen leest, zodat "Afgesloten
  26064 Apeldoorn" + "26064 Harskamp" één afwijking `project_nummer_dubbel` nummer 26064 geeft (vingerafdruk administratie + nummer,
  ongewijzigd; stand `meten` blijft). Verwacht effect Universal ná deploy: 3 → 4 dubbelen (26053, 26064, 26084, 26149) — **gemeten 19-09 17:15 op
  `1dab82c` (run 35450280469): 4, exact als verwacht; werkt in productie JA** (rapport `2026-09-19-projectnummer-uit-afgesloten-naam.md`
  sectie "Nameting ná deploy"). Volledige tekst: `docs/regels/verplichtingen-projecten-voorraad.md` alinea "Projectnummer óók lezen uit
  'Afgesloten NNNNN …'-namen".

<!-- toegevoegd 19-09-2026, opdracht "ic-spiegel-rood-174-doorbelastingsparen-verkoop-niet-gevonden" -->
- **Systeemfout ic_spiegel_rood 174× — IC-verkoopkant leest `SalesInvoices` ∪ `Receipts`; aansluitingsblok per scope (19-09; geen
  migratie; BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)", rij "Systeemfout ic_spiegel_rood 174×"):** de `SalesInvoices`-COLLECTIE van RLZ toont via
  de API aangemaakte verkoopfacturen niet (record-GET wél; STAP-0 19-09) — élke module-verkoop (doorbelasting, Vastly, omzet) was
  daardoor onzichtbaar voor het intercompany-blok: 174 rode spiegelparen "verkoopfactuur niet gevonden bij de bron-administratie" en
  hun spiegels als `ic_ontbreekt_bij_verkoper`. De verkoopkant is sinds 19-09 de unie `SalesInvoices` ∪ `Receipts` (zelfde
  Entity-/datumfilter, Receipts alleen `DocumentType` 10, ontdubbeld op id — `factuurmatch.VERKOOP_COLLECTIES`); dezelfde lezer dient
  het aansluitingsblok. Het aansluitingsblok `doorbelasting_aansluiting` gaf sinds 16-09 een VALSE nul ("0 bron-administraties mét
  whitelist"): `doorbelasting_mapping` heeft alleen een scope-policy (FORCE RLS), lezen zonder scope = 0 rijen in productie —
  sinds 19-09 per administratie in eigen scope (test onder de app-rol). Les voor élk reconciliatieblok: een blok dat "niets te
  toetsen" meldt terwijl de configuratie bestaat is een systeemfout, geen OK; tabellen zonder NULL-/Beheerder-clausule nooit in
  `scoped_session(None)` lezen. Meetlat ná deploy: `reconciliatie-alles --alleen intercompany --lees-only` → 0 × `ic_spiegel_rood`,
  `--alleen doorbelasting_aansluiting` → 1 bron-administratie (Kempen Facilities, 8 doelen). Tellers: uitkomst `gebundeld` van de
  extractie-wachtrij-trigger telt als zachte overslaan-reden `trigger_gebundeld` (nooit LET-OP) — zie `docs/regels/intake-extractie.md`.
  **Gemeten 19-09 17:30 op `a731dd4` (executies whzvz/txspn): `ic_spiegel_rood` 0, spiegelparen 174/174 groen, aansluitingsblok 1 bron /
  8 doelen / 1652 sluiten / 108 afwijkingen — werkt in productie JA** (rapport `2026-09-19-nameting-ic-spiegel-rood-na-deploy.md`). De
  `--alleen`-keuzelijst van `reconciliatie-alles` is sinds 19-09 letterlijk `run.BLOKKEN` (guard `tests/unit/test_reconciliatie_alleen_keuzelijst.py`):
  een blok dat in de run zit maar niet los meetbaar is, is een meetlat die op de job-image met argparse-exit 2 strandt (zo ging het met
  `doorbelasting_aansluiting` op 19-09). Eén feit in twee blokken (99 × KF → Molenhof Beheer als `ic_ontbreekt_bij_ontvanger` én als
  `da_ontbreekt_in_doel`) is bekend en bewust: de standen per soort regelen de melding (IC-soort in `meten`, `da_*` code-default `actie` → de
  explosie-rem doet bij > 50 zijn werk).

<!-- toegevoegd 19-09-2026 avond, opdracht "nameting-ic-spiegel-rood-echte-run-en-aansluiting-alleen" (poging 1) -->
- **Verdwenen FOUTEN verdwijnen niet stil — delta, herstelregel en audit `reconciliatie_auto_gesloten` generiek (19-09 avond; geen migratie;
  BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)" rij "Nameting ic_spiegel_rood échte run —
  POGING 1"):** tot 19-09 kende `bepaal_delta` alleen `verdwenen_afwijkingen` (soort `afwijking`), toonde de systeemmail alleen "Hersteld — N
  afwijking(en)" en schreef `_audit_verdwenen_dubbele_betaling` het audit uitsluitend voor `dubbele_betaling_vermoed` — een gefixte systeemfout
  (174 × `ic_spiegel_rood`, soort `fout`) zou bij de eerstvolgende run zonder enig spoor verdwijnen, terwijl de regel hierboven ("verdwenen
  bevindingen sluiten mét audit") generiek geformuleerd was: gedocumenteerd ≠ gebouwd, kernprincipe 4. Sinds 19-09 avond: `Delta.verdwenen_fouten`
  (concept weg = verdwenen; concept terug als andere soort = verschoven), `Delta.verdwenen` = afwijkingen + fouten, `is_leeg` telt ze mee,
  systeemmail "Hersteld — N fout(en) uit de vorige run niet meer gezien", `_audit_verdwenen_bevindingen` = per (soort × bevindingssoort ×
  administratie) één `reconciliatie_auto_gesloten` mét `soort` (= `detail.afwijking_soort`, anders `<blok>:<soort>`), `bevinding_soort`, `blok`,
  `administratie_id`, `aantal`, `vingerafdrukken` ≤ 200, `reden` ("niet meer geproduceerd door run <id> — fout uit de vorige run verdwenen (blok
  …)"; `dubbele_betaling_vermoed` houdt zijn herdefinitie-reden); en `reconciliatie_run.samenvatting["delta"]` (nieuwe_afwijkingen/let_op/
  geaccepteerd/fouten, verdwenen_afwijkingen/fouten, blokken_fout) omdat de systeemmail in productie `uitgeschakeld` is en de herstelregel anders
  nergens meetbaar is. Verdwenen fouten alléén maken géén systeemmail nodig (`systeemmail_nodig` ongewijzigd: herstel is informatie, geen
  handeling). Tests `tests/reconciliatie/test_run.py` (delta, `bouw_mail`) + `test_soort_stand.py::test_verdwenen_fout_en_afwijking_automatisch_
  gesloten_met_audit`. **Gemeten 20-09 (poging 2, scheduler-run `55facc7c` 04:30–04:44 UTC op image `0453020`, executie `kv8v6` — werkt in
  productie JA):** NULL-scope-bevindingen `intercompany`/`fout` 174 → 0; `samenvatting["delta"]` = `verdwenen_fouten` 174, `verdwenen_afwijkingen` 10,
  `nieuwe_afwijkingen` 111, `nieuwe_let_op` 10, `nieuwe_fouten` 0, `blokken_fout` []; audit `reconciliatie_auto_gesloten` 04:44:54 UTC: precies één rij
  `ic_spiegel_rood` / `fout` / `intercompany` / administratie NULL / aantal 174 / 174 vingerafdrukken / reden "niet meer geproduceerd door run 55facc7c… —
  fout uit de vorige run verdwenen (blok intercompany)", plus vijf rijen voor de 10 verdwenen afwijkingen (`ic_ontbreekt_bij_ontvanger` 3 + 1,
  `ic_ontbreekt_bij_verkoper` 1, `kassarapport_in_werkvoorraad` 4, `dubbele_betaling_vermoed` 1 mét zijn herdefinitie-reden). Let op: de KOLOM
  `audit_event.administratie_id` is bij álle zes rijen NULL (de run schrijft in `scoped_session(None)`, zie memory "audit_event mét administratie_id
  vereist scope"); de administratie van de verdwenen bevinding staat in `nieuwe_waarde.administratie_id`. De systeemmail bleef `uitgeschakeld`
  (`mail_status` `actie=verzonden;systeem=uitgeschakeld`), dus de herstelregel is uitsluitend via delta + audit gemeten — precies de reden waarom
  `samenvatting["delta"]` bestaat. Rapport `2026-09-20-nameting-ic-spiegel-rood-echte-run-poging-2.md`. Les voor élk meetrecept:
  een verwachting op een audit-/mail-spoor eerst in de code aanwijzen (welke functie schrijft het, voor welke soorten) vóór je 'm als "verwacht"
  opschrijft — anders meet je een gegarandeerde 0.

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Synthetische bewaking + alerting (CLAUDE.md `ed6d176` r. 632–644)

- **Synthetische bewaking + alerting (best-practice-besluit 1, 31-08 — aanleiding: twee stille
  productie-incidenten 30/31-08; migratie 0092):** Cloud Run-job `rlz-bewaking` elk kwartier
  (`app/bewaking/`, statusrijen `platform.bewaking_probe_run`/`bewaking_storing`): health, DB +
  migratieversie, documentopslag-leesproef, mailkanaal-config, lichte RLZ-leesroute op de
  TEST-administratie (nooit writes); 1×/uur schema-zelftest + minimale echte AI-call
  (`claude-haiku-4-5`, onder de kostenmeter, bron `bewaking`) én het foutpiek-signaal
  (extractie-foutratio per uur ≥ 50 % bij ≥ 3 pogingen). Alerts via het eigen SMTP-kanaal naar
  p.nijenhuis@kempengroep.nl: pas bij 2 opeenvolgende fouten, idempotent per storing
  (kolom-is-None), expliciete herstelmelding. Job-exit-contract: falende probes = exit 0 (eigen
  alert); exit 1 alleen als de bewaking zelf niet draait → F3.2-vangnet. Post-deploy-smoketest
  in deploy.yml (health + gepoorte route moet 401 geven + one-off `rlz-smoketest`-job met de
  CLI `deploy-smoketest`) — een kapotte deploy is per direct luid rood. Zie BESLISSINGEN
  "SYNTHETISCHE BEWAKING + ALERTING".

### Domeinbeslissingen — Reconciliatie-melding + Inzicht › Reconciliatie (CLAUDE.md `ed6d176` r. 645–658)

- **Reconciliatie-melding + Inzicht › Reconciliatie (opdracht 06-09, migratie 0114 — BESLISSINGEN
  "RECONCILIATIE-MELDING + INZICHT" is canoniek):** `reconciliatie-alles` (job `rlz-reconciliatie`,
  06:30 — blijft vóór de sync: alle vier blokken toetsen LIVE tegen RLZ) legt élke run vast
  (`boekhouding.reconciliatie_run` + `reconciliatie_bevinding`, ook bij een blokcrash; CLI-uitvoer
  identiek + RUN-slotregel), bepaalt de delta t.o.v. de vorige afgeronde run en mailt via het
  bewakingskanaal ALLEEN als er iets te melden is (nieuwe afwijkingen/LET-OP's/geaccepteerd/fouten,
  omgevallen blok, verdwenen afwijking = herstelregel; ongewijzigde LET-OP-set = geen mail; mailfout
  maakt de job nooit rood → bewakingsprobe `reconciliatie_mail`; exit 1 blijft exit 1, F3.2 blijft
  het vangnet). Kantoor-UI: KPI-kaart "Reconciliatie" (alleen bij teller > 0) → `/reconciliatie`
  (Inzicht-kantoorbreed lijstpatroon, RLS-scope): afwijking → "Accepteren…"/"Intrekken" (bestaande
  schrijver, Beheerder), LET-OP → "Gezien" (snooze mét reden, vervalt ná `gezien_dagen` = 90) +
  deeplink, "Nu draaien" (Beheerder, 202 + poll, on-demand job — klikpunt f3_jobs.sh stap 11).
  Opruimlijst dedupliceert per RLZ-concept (blok D). De lokale dagelijkse `make reconciliatie-alles`
  is per 06-09 vervallen als vangnet (GCP_UITROL §F3.7). `app/reconciliatie/{run,kantoorbreed}.py`.
