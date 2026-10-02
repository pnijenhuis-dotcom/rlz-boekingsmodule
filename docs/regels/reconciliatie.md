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

<!-- toegevoegd 21-09-2026, opdracht "BUG-groepssaldi-alle-35-administraties-fout-rlz-enumfilter-en-odoo-deprecated" -->
- **Regressie-detector `groep_saldo_fout` — een `fout` in de nachtelijke groepssaldi-stand is een LET-OP mét systeemmail, geen grijze kaart
  (21-09; geen migratie; BESLISSINGEN "GROEPSSALDI — PRODUCTIEFOUT 16→21-09 (enumfilter + deprecated)"):** `automatiseringen.groep_saldi_bevinding` (in `registreer`)
  leest per lid van élke actieve groep de LAATSTE rij van `groep_saldo_stand` in de eigen administratie-scope (`saldi.standen_met_fout`;
  de cache-policy is scope/Beheerder — nooit in `scoped_session(None)`, les 19-09) en maakt bij ≥ 1 status `fout` één platformbrede
  LET-OP: aantal leden/groepen, eerste vijf "naam: melding", deeplink `/?groep=<id>`, vingerafdruk stabiel per set falende leden.
  De categorie zit in `REGRESSIE_CATEGORIEEN` → `run.is_regressie` → systeemmail + audit `automatisering_regressie` + bewakingsprobe
  (regel 1 "regressies = systeemfout — automatisch gemeld"); bewust NIET via `meten`: een detector op een codefout is geen nieuwe
  domeinbevinding. `ongeldig` (webfilter) en `geen_rekening` zijn geen regressie; "geen stand" evenmin (de run van 06:30 loopt vóór
  `sync-alles` 07:00 — een gisteren toegevoegd lid heeft dan nog geen stand). Aanleiding: 16→21-09 stonden 35/35 leden van "Kempen groep"
  op `fout` (RLZ-enumfilter + Odoo `deprecated`) en het enige signaal was "meting mislukt" op een kaart die niemand las. **Verwacht ná
  deploy: de run van 22-09 06:30 leest nog de stand van 21-09 (oude image) en meldt de LET-OP precies één keer mét audit; de `sync-alles`
  van 22-09 07:00 schrijft de eerste groene stand en op 23-09 is de LET-OP weg.** Test `tests/groepen/test_saldi.py::TestStandSysteemEnDetector`.
  **Gemeten 22-09 (nameting-opdracht, leesreplica + Cloud Logging, scheduler-run `e315ceae` 04:30–04:46 UTC op image `fb63be5`) — de detector
  WERKT IN PRODUCTIE: JA:** precies één bevinding `let_op` / blok `automatisering` / administratie NULL / `reden: groep_saldo_fout` / `aantal: 35` /
  `stand_datum: 2026-09-21` mét de tekst "35 administratie(s) in 1 groep(en) (Kempen groep) … status fout — voorbeelden: ARVUM B.V.: GET
  /…/Ledgers -> 400 …", en om 04:46:28 UTC één audit `automatisering_regressie` mét `categorie: groep_saldo_fout`, `aantal: 35`, `run_id`
  e315ceae — exact de verwachting van 21-09. De LET-OP staat NIET in de job-stdout (`registreer` print alleen de tellerregels; de bevinding
  leeft in `reconciliatie_bevinding`) — een meetrecept op deze detector leest dus de tabel of `/reconciliatie`, niet het log. De systeemmail
  bleef `uitgeschakeld` (ontvangerslijst leeg), de bewakingsprobe `automatisering_regressie` is het mailende kanaal. **Vervolg:** de stand van
  22-09 was opnieuw rood (29/35 `fout`, tweede enum-veld `Status` — zie `administraties-instellingen.md`), dus de run van 23-09 06:30 meldt de
  LET-OP nog één keer mét een NIEUWE vingerafdruk (andere set: 29 leden) en de eerste groene stand komt pas van `sync-alles` 23-09 07:00 op
  de image mét de fix van 22-09; verwacht weg op 24-09 (vervolg-opdracht `niet vóór: 2026-09-23 09:00`). **Gemeten 23-09 (rapport
  `docs/rapporten/2026-09-23-nameting-groepssaldi-status-enum-fix.md`): exact zo — run `40b5d45c` (04:30–04:48 UTC) schreef één LET-OP `aantal` 29,
  `stand_datum` 2026-09-22, vingerafdruk `c5d03e2307a75d02` + één audit `automatisering_regressie` 04:48:43 UTC; de stand van 23-09 is 35 × `ok`,
  dus verwacht op 24-09: 0 rijen `groep_saldo_fout` (LET-OP's krijgen geen `reconciliatie_auto_gesloten`-audit — dat dekt afwijkingen + fouten).**

<!-- toegevoegd 21-09-2026, opdracht "corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten" -->
- **Storno vanuit de module ≠ verdwenen document (21-09; geen migratie; BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW
  KLAARZETTEN (Peter 21-09)"):** "Corrigeren…" vuurt het `factuur_gestorneerd`-event DIRECT mét bron `module_storno` in dezelfde
  boekstand-reeks als het geboekt-event (vastgoed-administraties; inkoop én Vastly-verkoop); `storno_detectie.py` (bron
  `rlz_ui_detectie`, latentie tot de volgende run) blijft alleen voor storno's die iemand tóch rechtstreeks in de RLZ-UI doet. De routes
  blijven gescheiden: een extern stuk dat NIET meer bestaat (404) is `ontbreekt_in_rlz/odoo` → "Opnieuw boeken" achter de aangiftepoort
  (herboeken.py); de corrigeer-dialoog wijst dan naar Inzicht › Reconciliatie en storneert niets. Een gecorrigeerd document staat op
  `klaar_om_te_boeken` mét een concept in RLZ; blijft de herboeking uit, dan meldt de bestaande opruimlijst/omzet-reconciliatie dat
  concept (geen nieuwe bevindingssoort). Een kassarapport-correctie die ná het memoriaal strandt zet de registratie op `HALF_GEBOEKT`
  (`half_geboekt_detail.bron = correctie`) — de omzet-reconciliatie rapporteert die rijen al.

<!-- toegevoegd 23-09-2026, opdracht "intake-tweede-postvak-facturen-kempengroep-direct-plus-postvakbewaking-en-message-id" -->
- **Blok `intake` — postvak-bewaking "ontvangen vs verwerkt" (Peter 22-09; migratie 0171; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)"):**
  `app/intake/bewaking.py::cli_blok` (in `run.BLOKKEN` en `cli._reconciliatie_alles`, ná `activa`) telt per kanaal AAN DE BRON: alle
  berichten in INBOX + spam-map sinds gisteren 00:00 NL (IMAP `SINCE`, daarna op de Date-kop begrensd), gelezen én ongelezen, en legt dat
  naast de verwerkt-administratie (`intake_bericht_verwerkt` ∪ `intake_bericht.message_id`) en de uitkomsten per bijlage (documenten /
  verzamelbak / niet verwerkbaar uit `intake_bericht.detail` — géén Document-query over RLS heen). CLI-regel `INTAKE postvak <adres>
  (<kanaal>) sinds …: N in het postvak (INBOX a, spam b), K bekend/verwerkt (…), dubbel via forward d, VERSCHIL v`. **Verschil > 0 =
  afwijking `intake_postvak_verschil`** (platformbreed, administratie NULL, vingerafdruk per kanaal × set Message-ID's; `detail.berichten`
  ≤ 50 mét message_id/afzender/onderwerp/map/gelezen/datum) — **direct in `actie`** (`SoortDefinitie.direct_actie_reden`, tweede
  uitzondering ná `intussen_extern_geboekt`; besluit Peter in de opdracht "verschil > 0 = actie-bevinding mét de Message-ID's en knop Nu
  verwerken": een telling aan de bron mét de Message-ID's als bewijs en één deterministische handeling), explosie-rem blijft. Handeling
  "Nu verwerken" (`frontend/src/reconciliatie/NuVerwerkenActie.tsx`, élke kantoorrol) = `POST /reconciliatie/intake/{kanaal}/nu-verwerken`
  → `app/intake/nu_verwerken.py` start de intake-job van het kanaal on-demand (`settings.intake_imap_job_resource` /
  `intake_kempengroep_imap_job_resource`, v2 `:run`, run.invoker voor run-backend@ — f3_jobs.sh stap 6; dev = thread), 202 + audit
  `intake_postvak_nu_verwerken`; 404 onbekend kanaal, 502 = start mislukt mét reden. De service leest nooit zelf IMAP (geen credentials).
  **Uit Spam verwerkt** (laatste 7 dagen) = LET-OP `intake_uit_spam` per (kanaal, afzender) mét domein — handeling: afzender/domein in
  Google Workspace toestaan of DKIM/DMARC laten fixen; 'Gezien' mét reden. **Verbinding mislukt = FOUT** `intake_postvak_verbinding`; een
  kanaal MÉT job (`KANALEN_MET_JOB` = facturen, facturen_kempengroep) zonder instellingen op de reconciliatie-job = FOUT
  `intake_postvak_niet_geconfigureerd` (systeemfout, nooit stil — deploy.yml geeft rlz-reconciliatie de INTAKE-envset + beide secrets);
  declaraties@ (geen job) = zichtbaar OVERGESLAGEN. Dagtellers: teller `INTAKE_POSTVAK` ("Intake-postvakken …") uit audit
  `intake_postvak_run` — gedaan = verwerkt, verwacht = verwerkt + overgeslagen, zachte redenen `postvak_al_bekend` /
  `postvak_niet_verwerkbaar` / `postvak_uit_spam` / `postvak_dubbel_via_forward` (overgangsperiode forward), `detail.per_kanaal`.
  Leesbare teksten in `teksten.py` (`_intake`, LET-OP `intake_uit_spam`, FOUT blok intake); frontend `BLOK_LABEL.intake` = "Postvak".
  Meetlat ná deploy: `reconciliatie-alles --alleen intake --lees-only` → per kanaal een `INTAKE`-regel (geen FOUT `niet_geconfigureerd`),
  en de scheduler-run van 06:30 → blok `intake` mét `gecontroleerd` 2. Tests `tests/reconciliatie/test_intake_bewaking.py` (pure toets,
  cli_blok mét nep-lezer, FOUT-paden, spam-LET-OP, dagteller, route 202/502/404/401).

<!-- toegevoegd 02-10-2026, opdracht "run-A" punt 14 — DOEL: docs/regels/reconciliatie.md -->
- **Dagteller "Accordeur-meldingen push-only" (punt 14 run A, Peter 02-10; geen migratie; BESLISSINGEN "RUN A 02-10 — BOEKEN,
  PROJECTEN, MELDINGEN, KLEINE BUGS (Peter 02-10)" punt 14):** teller `accordeur_meldingen` in `app/reconciliatie/automatiseringen.py`
  (stand `altijd`, bron audit `accordeur_melding_run` van de jobs `nieuwe-facturen-melden` en `accordeur-herinneringen`): gedaan =
  `verzonden_push`, overgeslagen `geen_push` (nieuwe reden-categorie, label "geen push-inschrijving of push mislukt (geen e-mail —
  besluit 02-10)", vaste categorie → óók als 0 zichtbaar), `fout` = mislukt; `detail.geen_push_per_soort`. Bewust geen harde
  voorwaarde/LET-OP: een accordeur zonder toestel krijgt sinds 02-10 niets, en dat is de bedoeling — de teller maakt het zichtbaar,
  de bestaande koppelroute (telefoon/app koppelen) is de handeling. Volledige regel: `docs/regels/accordering-native-app.md` alinea
  "Accordeur-meldingen push-only".

<!-- toegevoegd 02-10-2026, opdracht "run-A" punt 17 — DOEL: docs/regels/reconciliatie.md -->
- **Webhook-outbox: 409 `niet_koppelbaar` = wachten op de ontvanger, nooit een dead-letter (punt 17 run A, Peter 02-10; migratie 0175;
  BESLISSINGEN "RUN A 02-10 — BOEKEN, PROJECTEN, MELDINGEN, KLEINE BUGS (Peter 02-10)" punt 17):** Vastly antwoordt sinds 24-09 op een
  event dat het (nog) niet kan koppelen `409 {"resultaat":"niet_koppelbaar","reden": onbekende_administratie | onbekend_document |
  referentie_conflict}` (koppelcontract §3c, voorstel-3c-409). Tot 02-10 viel dat onder de gewone retry (8 pogingen, exponentiële backoff
  ≤ 3600 s) en stond het event ná ≈ 2 uur definitief `mislukt` — een verloren bericht voor iets dat alleen "nog niet" was. Regel: (1) een
  409 mét `resultaat: niet_koppelbaar` is geen fout van ons: de outbox-rij krijgt de eigen status **`wacht_op_ontvanger`**
  (`WebhookStatus.WACHT_OP_ONTVANGER`, CHECK-constraint 0175) mét een vaste cadans gerekend vanaf de EERSTE 409
  (`wacht_op_ontvanger_sinds`): opnieuw ná 1 uur, ná 6 uur, ná 24 uur, daarna dagelijks (`webhook_afleveraar.WACHT_CADANS`,
  `volgende_wacht_poging` — altijd strikt ná "nu", een late job-run doet nooit twee pogingen), hooguit **14 dagen** (`WACHT_MAX`); daarna
  pas `mislukt` mét de letterlijke reden uit de body ("ontvanger kon niet koppelen binnen 14 dagen: ‹reden›", audit
  `webhook_niet_koppelbaar_verlopen`). Geen instelling (Peter 30-09 "hou het simpel"). (2) 409-pogingen tellen in `wacht_pogingen` en
  tellen NIET mee voor de dead-letter-grens van 8; een andere niet-2xx ná een 409 houdt het bestaande gedrag (8 pogingen, backoff). De
  nonce-replay-409 (`{"fout": …}`, zonder `resultaat`) blijft de gewone retry. Een 2xx ná het wachten = gewoon `afgeleverd` (audit draagt
  `wachtte_sinds`/`wacht_pogingen`). (3) Zichtbaar, nooit stil: reconciliatieblok **`webhooks`** (`app/documenten/webhook_reconciliatie.py`,
  laatste blok in `run.BLOKKEN` en `cli._reconciliatie_alles`) maakt per administratie in eigen RLS-scope één bevinding per rij —
  `webhook_wacht_op_ontvanger` (event, referentie, reden, sinds, volgende poging, pogingen; stand **`meten`**: het systeem herhaalt zelf,
  een actiemail over iets dat vanzelf oplost is de ruis die Peter 02-10 "geen mails meer" niet wil) en `webhook_niet_koppelbaar_verlopen`
  (ná 14 dagen; **direct in `actie`**, `direct_actie_reden` — hier is een mens nodig: melden bij Vastly; het bewijs is Vastly's eigen reden;
  explosie-rem blijft). Beide rijen dragen de statuschip ("wacht op ontvanger · volgende poging … · reden") en de handeling **"Nu
  opnieuw"** (`frontend/src/reconciliatie/WebhookActies.tsx`, `POST /reconciliatie/webhooks/{outbox_id}/nu-opnieuw`, élke kantoorrol →
  `webhook_afleveraar.nu_opnieuw`: één directe afleverronde buiten de cadans om, audit `webhook_nu_opnieuw` mét actor; op een verlopen rij
  begint de 14-dagen-telling opnieuw; 404 buiten scope, 409 als de rij niet wacht; aflevering uit = 200 mét die reden in `uitkomst`). Er
  is geen outbox-scherm in de kantoor-UI — déze bevinding + `db-lezen webhook-outbox` (versie 2: `wacht_op_ontvanger_sinds`,
  `wacht_pogingen`, `volgende_poging_op`, audit-acties `webhook_wacht_op_ontvanger`/`webhook_niet_koppelbaar_verlopen`/
  `webhook_nu_opnieuw`) zijn de zichtbaarheid. `webhook-herzenden`/`webhook-redrive` zetten de wacht-velden terug; een wachtende rij
  geldt bij herzenden als "al openstaand — niet herzonden". (4) Contract-eigenaar-antwoord: §3-notitie 02-10 in het koppelcontract (geen
  wire-wijziging, geen versiebump — Vastly bouwt niets) + OPEN_ITEMS r. 1475 "Antwoord RLZ 02-10" + `registers/schema-versions.md`;
  **beslispunten Peter, niet door CC genomen:** accordering van §3c (voorstel-3c-409 → contractversie; v1.21 is intussen door de §2d-bump
  bezet) en de 7-dagen-cadans voor élke andere niet-2xx. De elf events van 01-10 zijn `verwerkt` — niets herzonden, geen data-stap.
  Meetlat ná deploy: dispatch-onderdeel `webhook-wacht` (`reconciliatie-alles --alleen webhooks --lees-only` + request-log "Nu opnieuw";
  verwacht direct ná deploy `WEBHOOKS   0 outbox-rij(en)`). Tests `tests/documenten/test_webhook_wacht_op_ontvanger.py` (cadans, 409 →
  wacht zonder dead-letter, 2xx ná wachten, 14 dagen → mislukt mét reden en niet meer geprobeerd, nonce-replay ongewijzigd, 8 pogingen
  ongeacht 409's, herzenden reset, nu_opnieuw (wacht/verlopen/weigering), blok + leesbare teksten + `--alleen webhooks --lees-only`
  letterlijk, route 200/409/404/401 + aflevering-uit, db-lezen v2), gouden set casus **an** `TestNietKoppelbaarInDeKeten`, vitest
  `WebhookActies.test.tsx`; blokkenlijst-guards (`test_rlz_dubbel`, `test_activa/test_reconciliatie`, `test_soort_stand`) bijgewerkt.

<!-- toegevoegd 02-10-2026 avond, opdracht "besluiten-run-a-verwerken-409-cadans-contract-dubbele-projecten" (besluit 4a + 4b, capture-at-acceptance) -->
- **Webhook-outbox: 7-dagen-storingscadans voor élke andere niet-2xx, 4xx = direct mislukt; §3c geaccordeerd (koppelcontract v1.22)
  (Peter 02-10 17:1x "Ik volg jouw advies" op run-A-beslispunt 17; geen migratie, geen instelling; BESLISSINGEN "RUN A 02-10 — BOEKEN,
  PROJECTEN, MELDINGEN, KLEINE BUGS (Peter 02-10)" punt 17 alinea "BESLIST 02-10"):** (1) **Storing = cadans tot 7 dagen.** Antwoordt de
  ontvanger anders dan 2xx en is het geen 409 `niet_koppelbaar` — 5xx, 429, timeout/verbindingsfout, nonce-replay-409 (`{"fout": …}`) —
  dan volgt de rij DEZELFDE cadans als het wachten (`webhook_afleveraar.STORING_CADANS` = 1 u → 6 u → 24 u → dagelijks) maar hooguit
  **7 dagen** (`STORING_MAX`): status blijft `openstaand` mét `volgende_poging_op`, audit `webhook_poging_mislukt` per poging; zou de
  volgende cadansstap voorbij de 7 dagen vallen, dan `mislukt` mét de laatste fout als reden ("aflevering mislukt binnen 7 dagen (N
  pogingen): HTTP 503 …", audit `webhook_aflevering_verlopen`). De cadans telt in storingspogingen (`pogingen − wacht_pogingen`; de
  volgende poging ligt nooit vóór de stap, een stilstaande job schuift mee): negen pogingen op 0, 1, 7, 31, 55, 79, 103, 127 en 151 uur,
  de tiende zou op 175 uur vallen en komt er niet. HERZIET "8 pogingen, exponentiële backoff ≤ 3600 s, dead-letter ≈ 2 uur" (instellingen
  `webhook_max_pogingen`/`webhook_backoff_*` vervallen). (2) **4xx ≠ 409/429 = direct `mislukt`.** Een 400/401/404/422 zegt iets over óns
  bericht (schema, handtekening, GUID) — herhalen geeft hetzelfde antwoord: direct `mislukt` mét "ontvanger weigerde het bericht (HTTP
  400): ‹body› — payloadfout, herhalen zinloos" (audit `webhook_geweigerd_4xx`), nooit een stille retry. 409 `niet_koppelbaar` houdt zijn
  eigen regel (wacht_op_ontvanger, 14 dagen — RLZ-keuze 02-10), 429 is een storing. (3) **Zichtbaar mét handeling:** derde bevindingssoort
  in blok `webhooks`: **`webhook_aflevering_mislukt`** — direct in **`actie`** (`direct_actie_reden`: mens nodig — storing melden bij
  Vastly / ons bericht fixen; bewijs = het letterlijke antwoord van de ontvanger; explosie-rem blijft), `detail.reden_soort` =
  `storing_verlopen` | `payloadfout`, `storing_pogingen`, `max_dagen` 7; leesbare tekst "Event bereikt Vastly al 7 dagen niet" /
  "Vastly weigerde het event (bericht afgekeurd)"; statuschip "mislukt na 7 dagen storing · ‹fout› · N pogingen" / "geweigerd (payloadfout,
  herhalen zinloos) · ‹fout›" en dezelfde handeling **"Nu opnieuw"** (`nu_opnieuw` accepteert zo'n rij via `is_verlopen_of_geweigerd`: terug
  naar `openstaand` mét vers 7-dagen-budget, `pogingen` 0, audit `webhook_nu_opnieuw`); een oude dead-letter zonder prefix blijft
  webhook-redrive-terrein (409 in de router). CLI-slotregel `WEBHOOKS … N ná 14 dagen mislukt, M ná 7 dagen storing of 4xx geweigerd`;
  `db-lezen webhook-outbox` v3 kent de twee nieuwe audit-acties. Geen outbox-scherm (ongewijzigd). (4) **Contract (4b):** §3c is
  geaccordeerd → koppelcontract **v1.22** (wijzigingslog + §3c-kop definitief; vastgoed-kant verandert niets aan de wire, alleen het label
  `voorstel-3c-409` → `1.22` in `rlz_webhook.KOPPELCONTRACT_VERSIE`/`ANTWOORDVORM_LABEL` is aan Vastly), OPEN_ITEMS-item "contractvoorstel
  §3 — retry-cadans" afgemeld, `registers/schema-versions.md` rij antwoordvorm = v1.22; Platform apart gecommit. Guards:
  `tests/documenten/test_webhook_afleveraar.py::TestRetryEnDeadLetter` (cadans 9 pogingen/7 dagen, 4xx direct, 429 = storing, 401 =
  direct mislukt), `test_webhook_wacht_op_ontvanger.py::TestStoringscadans7Dagen` (puur + blok + teksten + Nu opnieuw + CLI-vorm),
  soort_stand-pin, vitest `WebhookActies.test.tsx` (derde soort), gouden set casus an. Meetlat ná deploy: bestaand dispatch-onderdeel
  `webhook-wacht` (`reconciliatie-alles --alleen webhooks --lees-only` + request-log "Nu opnieuw"; verwacht `… 0 ná 7 dagen storing of 4xx
  geweigerd` zolang Vastly bereikbaar is) + `db-lezen webhook-outbox`. Werkt in productie: niet gemeten (aanwezig-pad pas bij een échte
  storing of 4xx).

<!-- toegevoegd 02-10-2026 avond, opdracht "run-D-alles-in-een" blok A -->
- **Btw-afronding RLZ < 0,10 = automatisch geaccepteerd mét audit `btw_afronding_rlz`; RLZ boekt MINDER = soort
  `btw_rlz_lager_dan_factuur` in `meten` (besluit Peter 29-09 "onder de € 0,10 lekker boeken … wel dan altijd in ons voordeel";
  geen migratie; BESLISSINGEN "RUN D 02-10 — BTW < € 0,10, PROJECTMATCH, AFWIJZEN, IC 12 RICHTINGEN, PO STAP-0, NATIVE 1.3 (Peter 02-10)" blok A; VERBREDING van de ≤ € 0,05-regel van 15-09, uitsluitend voor déze oorzaak):** (1) de
  documenten-reconciliatie leest sinds 02-10 náást het bedrag óók btw en netto van het externe stuk (`ToetsUitkomst.btw_bedrag`/
  `netto_bedrag`: RLZ `TotalTaxAmount`/`TotalNetAmount` op PurchaseInvoices — api-verkenning: op ManualJournals is dat veld géén
  btw, op DocumentType 1 wél; Odoo `amount_tax`/`amount_untaxed`) en Σ btw / Σ netto van de module-regels (`_Geboekt.btw_lokaal`/
  `netto_lokaal`, scalar-subquery's op `boekvoorstel_regel`). (2) **Pure regel** `reconciliatie.btw_afronding_richting`: alle
  vier bedragen bekend, netto gelijk op de cent (≤ 0,01) én 0 < |Δ btw| < € 0,10 → het verschil is uitsluitend RLZ's btw-
  herrekening per tarief; `rlz_meer` (RLZ boekt méér voorbelasting dan de factuur = in ons voordeel) → de afwijking blijft
  `bedrag_wijkt_af` mét context `btw_afronding=rlz_meer` + `btw_lokaal`/`btw_extern` en wordt in de vastgelegde run door het
  systeem geaccepteerd (`cli._auto_accepteer_afrondingen`: reden "btw-afronding RLZ < 0,10 (netto gelijk, RLZ boekt niet minder
  voorbelasting)", `extra.regel = run D 02-10 blok A`, **eigen audit-actie `btw_afronding_rlz`** via `service.auto_accepteer(…,
  audit_actie=…)`, dagteller `auto_geaccepteerd` op het blok, lees-only run = markering "wordt in de dagelijkse run automatisch
  geaccepteerd"); deze oorzaak gaat vóór de generieke 0,05-regel (die blijft voor verschillen zonder btw-gegevens — afwezig-pad,
  guard). `rlz_minder` (RLZ boekt MINDER voorbelasting dan de factuur) → **geen acceptatie** maar de bevindingssoort
  **`btw_rlz_lager_dan_factuur`** (blok `documenten`, `sinds` 02-10, code-default `meten` — regel 2: eerst tellen hoe vaak dit
  voorkomt vóór er een handeling (storno + herboeken achter de aangiftepoort) aan hangt; nooit stil), detail "eigen=€… rlz=€… btw
  eigen=€913,27 rlz=€913,21", leesbare tekst "RLZ boekt minder btw dan de factuur" (`teksten._documenten`, doe: geen handeling
  nodig voor het boeken — factuur-btw leidend; wil je het exact, corrigeer in RLZ; meetfase). Geen btw-oorzaak aantoonbaar
  (netto verschoven, Δ ≥ 0,10, bedragen ontbreken) = gewoon `bedrag_wijkt_af` (0,05-regel of actie). (3) Meetlat: querybibliotheek
  `db-lezen btw-afronding --administratie … --param dagen=14` (soorten `check_groen_met_verschil` / `acceptatie_btw_afronding` /
  `rlz_lager_dan_factuur`), job-log van de échte run op "btw-afronding RLZ", dispatch-onderdeel `btw-afronding` (vier plekken).
  Guards: `tests/documenten/test_btw_afronding_run_d.py::TestReconciliatiePuur` + `::TestReconciliatieRun` (acceptatie mét audit
  `btw_afronding_rlz` en zonder `reconciliatie_auto_geaccepteerd`, rlz_minder = bevinding in meten zonder acceptatie, afwezig-pad =
  regel 15-09, lees-only markeert), `test_soort_stand.py` (registry), `test_auto_acceptatie_afronding.py` ongewijzigd groen. Werkt
  in productie: niet gemeten (eerste échte run 03-10 06:30; onderdeel `btw-afronding`).

<!-- toegevoegd 02-10-2026 avond, opdracht "run-D-alles-in-een" blok D — DOEL: docs/regels/reconciliatie.md -->
- **Blok `intercompany` — richtingen, drie soorten, Verkoop uit Odoo ná de knip, handeling "Factuur opvragen" (run D 02-10 blok D,
  Peter 02-10; geen migratie; BESLISSINGEN "RUN D 02-10 — BTW < € 0,10, PROJECTMATCH, AFWIJZEN, IC 12 RICHTINGEN, PO STAP-0, NATIVE
  1.3 (Peter 02-10)" blok D):** het blok toetst sinds 02-10 ÁLLE geordende paren binnen een handelsgroep (`factuurmatch.
  bouw_richtingen`; Universal: 4 BV's = 12 richtingen; richting zonder debiteur-/crediteurrecord = `ZONDER RECORDS`-regel, 0/0, geen
  call; één bekende kant = getoetst mét lege andere kant — géén LET-OP "niet getoetst" meer), produceert per richting
  `ic_inkoop_ontbreekt` (**direct `actie`**, `direct_actie_reden`; handeling "Factuur opvragen bij ‹BV›" = mailconcept via `POST
  /reconciliatie/intercompany/{bevinding_id}/factuur-opvragen`, audit `ic_factuur_opgevraagd_concept`, nooit automatisch verzonden;
  frontend `IcActies.tsx`), `ic_verkoop_ontbreekt` (`meten`) en `ic_bedrag_afwijking` (`meten`) — ze vervangen
  `ic_ontbreekt_bij_ontvanger`/`_verkoper`/`ic_bedrag_verschilt` (oude namen blijven geregistreerd; open oude bevindingen sluiten via
  `reconciliatie_auto_gesloten` bij de eerstvolgende run; `ic_status_verschilt` en `ic_spiegel_rood` ongewijzigd). Sleutel mét én
  zonder `RLZ-`-prefix in de match en de onderweg-set (+ origineel achter een `afgevoerd_duplicaat`), concept-hulzen geteld. Een
  administratie mét twee systemen rond een kanteldatum (leesbron + knip, of overstap + RLZ-verleden) wordt als `GesplitsteBron`
  gelezen (RLZ vóór, Odoo ná; partij op identiteit KvK/naam waar de entity-id's niet gelden). De explosie-rem (> 50/run → `meten` +
  systeemfout-LET-OP) geldt onverkort — verwacht voor Nederland → Steigerbouw zolang de 36 nooit aangeleverde facturen niet via de
  intake komen. Slotregel `N/M richting(en) getoetst (K zonder records), …`. Meetlat: dispatch-onderdeel `ic-aansluiting`
  (`reconciliatie-alles --alleen intercompany --lees-only` + lees-only CLI `ic-aansluiting-rapport` + request-log factuur-opvragen),
  querybibliotheek `db-lezen ic-aansluiting --administratie …`. Volledige regel: `docs/regels/doorbelasting-intercompany.md` alinea
  "IC-controle Universal — alle 12 richtingen". Werkt in productie: niet gemeten.

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

<!-- toegevoegd 21-09-2026, opdracht "BUG-rlz-boek-wachtrij-job-zonder-command-python-exec-failed-deploy-yml" -->
- **`wordt_geboekt_verouderd` gepromoveerd: boeking > herstelgrens op wordt_geboekt = REGRESSIE-LET-OP `boek_wachtrij_gestrand`
  mét actie "Opnieuw indienen" + kwartier-probe (21-09; geen migratie; BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)"):**
  de bevindingssoort stond sinds 18-09 als `afwijking` in `meten` (facet "in meting", nooit een mail) en de systeemmail is in
  productie `uitgeschakeld` — vijf hangende boekingen (18→21-09) gaven daardoor nul signaal. Sinds 21-09: (1)
  `automatiseringen.boek_wachtrij_gestrand_bevindingen` (in `registreer`) maakt per document dat langer dan
  `BOEK_WACHTRIJ_HERSTEL_MINUTEN` (10) op wordt_geboekt staat één LET-OP op blok `automatisering` mét administratie, categorie
  `BOEK_WACHTRIJ_GESTRAND` ∈ `REGRESSIE_CATEGORIEEN` → `is_regressie` → systeemmail + audit `automatisering_regressie` +
  bewakingsprobe `automatisering_regressie` (die alert mailt naar `bewaking_alert_ontvanger`, ook als de systeemmail uit staat);
  de tekst draagt de reden uit het jongste `boek_wachtrij_trigger`-audit ("trigger mislukt: <fout>" | "trigger geslaagd maar de job
  rondde de boeking niet af" | "geen trigger-spoor"); detail `afwijking_soort: wordt_geboekt_verouderd`, `document_id`, `sinds`,
  `minuten`, `trigger_*`, `doel_pad` = het document; vingerafdruk per document × indienmoment (één mail per hangende boeking);
  bewust NIET via `meten` (detector op een infra-/codefout, geen nieuwe domeinbevinding — zelfde lijn als `groep_saldo_fout`).
  Het documenten-blok produceert de `afwijking` niet meer (alleen nog een informatieve CLI-regel); de registry-entry blijft
  (`gepromoveerd_op` 21-09, tekst-guard). (2) Frontend: `OpnieuwIndienenActie` (blok automatisering + `detail.reden ==
  boek_wachtrij_gestrand` + `document_id`) = primaire knop op de rij, roept de documentroute `…/boek-wachtrij/opnieuw-indienen` aan,
  toont de trigger-uitkomst; deeplink "Naar het document →". (3) **Snelle weg:** bewakingsprobe `boek_wachtrij_gestrand`
  (`app/bewaking/service.py`, elk kwartier): ≥ 1 document > herstelgrens = 'fout' → alert ná twee metingen (~30 min) mét per
  document minuten + trigger-reden, herstelmelding zodra leeg. (4) Teller `boek_wachtrij` in de reconciliatiemail telt
  `opnieuw_ingediend_24u`. Tests `tests/documenten/test_boek_wachtrij.py::TestNietsStil21_09::
  test_gestrande_boeking_is_regressie_let_op_met_trigger_reden_en_probe_fout`, vitest `OpnieuwIndienenActie.test.tsx`.
  Feit productie (leesreplica 21-09, per administratie): 5 boekingen ingediend 19-09 06:55 (Nijenhuis 75b35516), 21-09 07:20
  (Belastingbutler), 07:53 ×2 (Old Dutch), 10:46 (Nijenhuis) → alle vijf `afgerond geboekt` door verwerker `job` 21-09 15:31
  ná Peters `--command python`; 140 trigger-audits `geslaagd`, 0 `mislukt`. Rapport `docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md`.

<!-- toegevoegd 22-09-2026, opdracht "nameting-jobs-start-en-boek-wachtrij-trigger" -->
- **Gemeten 22-09 — `boek_wachtrij_gestrand` (afwezig-pad) en de auto-sluiting van `wordt_geboekt_verouderd` (BESLISSINGEN "F3-JOBS — COMMAND PYTHON
  IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)" alinea "Gemeten 22-09"; rapport `docs/rapporten/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md`):**
  kwartier-probe `rlz-bewaking` 22-09 11:15–13:00 UTC: acht metingen, élke keer `boek_wachtrij_gestrand=ok`; scheduler-run `e315ceae` (04:30–04:46
  UTC, image `fb63be5`): bevindingen `let_op`/`fout` = precies één (`groep_saldo_fout`), **0 × `boek_wachtrij_gestrand`** — er hing niets (leesreplica
  `wordt_geboekt` 0), dus het afwezig-pad klopt; het aanwezig-pad (LET-OP + systeemmail + probe `fout` bij een écht hangende boeking) is alleen in
  de gouden set (casus **ai**) bewezen, niet in productie — er is sinds de fix geen boeking meer blijven hangen. De oude in-meting-afwijking
  `wordt_geboekt_verouderd` (document `75b35516`, 19-09) is door dezelfde run gesloten: audit `reconciliatie_auto_gesloten` 04:46:28 UTC, soort
  `wordt_geboekt_verouderd` / `afwijking` / blok `documenten` / aantal 1, `samenvatting.delta.verdwenen_afwijkingen` 13. **Werkt in productie: JA
  (afwezig-pad + auto-sluiting); aanwezig-pad niet gemeten.** Meetles: `automatisering_regressie=fout` in de bewakingsregel is een
  verzamelsignaal (hier `groep_saldo_fout`) — lees de categorie in `reconciliatie_bevinding`/audit vóór je 'm aan een feature toeschrijft.

<!-- toegevoegd 22-09-2026, opdracht "ter-accordering-dagelijkse-rlz-bestaanscheck-intussen-buiten-de-module-geboekt" -->
- **Blok `documenten` — hercontrole open documenten + bevindingssoort `intussen_extern_geboekt` DIRECT in `actie` (Peter 22-09; geen
  migratie; BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK 'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)"):**
  `reconcilieer_administratie` toetst ná de geboekte documenten ook élk open document (`HERCONTROLE_STATUSSEN`, klaar_om_te_boeken >
  `HERCONTROLE_KLAAR_MINIMUM` = 1 dag) op "intussen buiten de module geboekt" met de bestaanscheck (zie `duplicaten-crediteuren.md`); een
  administratie zonder geboekte documenten maar mét open werk loopt óók mee. Rapportvelden `hercontrole_getoetst`/`hercontrole_overgeslagen`
  → CLI-regels `HERCONTROLE <adm>: N open document(en) vers getoetst …, K overgeslagen` + `OVERGESLAGEN document=…: reden` (storing/geen
  credential = géén bevinding, nooit stil — principe 4). **Uitzondering op regel 2 ("élke nieuwe bevindingssoort start in `meten`"), besluit Peter
  in de opdracht ("start in meten? NEE"):** `SoortDefinitie.direct_actie_reden` — een soort die een BESTAANDE harde check herhaalt en een bestaand
  boekstuk als bewijs draagt mag direct in `actie` (actiemail) starten; de guard `test_soort_stand.py` eist een reden ≥ 20 tekens en pint de lijst
  van zulke soorten (nu exact `intussen_extern_geboekt`); de explosie-rem (> 50/run → meten + systeemfout-LET-OP) geldt onverkort. Urgentie 1
  (direct onder "verdwenen"). De rij draagt twee handelingen (routes `POST /reconciliatie/documenten/{id}/extern-geboekt/afwijzen|toch-verschillend`,
  élke kantoorrol; frontend `ExternGeboektActies`); "Toch verschillend" door een Beheerder accepteert de bevinding in dezelfde handeling, door een
  andere rol niet — dan verdwijnt ze bij de volgende run als `reconciliatie_auto_gesloten`. Meetlat ná deploy: nameting-onderdeel `reconciliatie`
  (`reconciliatie-alles --lees-only`) → `HERCONTROLE`-regels per administratie + `intussen_extern_geboekt`-regels; verwacht op de stand van 22-09:
  Bouwadvies 8, Molenhof Beheer 1, Rubicon 1 (RLZ-kant) + de Odoo-kant van Universal Steigerbouw (43 open, vooraf niet meetbaar).

<!-- toegevoegd 23-09-2026, opdracht "nameting-ter-accordering-bestaanscheck-na-deploy" (poging 1) -->
- **Gemeten 23-09 — hercontrole + `intussen_extern_geboekt` WERKT IN PRODUCTIE: JA (BESLISSINGEN "TER ACCORDERING — DAGELIJKSE BESTAANSCHECK
  'INTUSSEN BUITEN DE MODULE GEBOEKT' (Peter 22-09)" alinea "Gemeten 23-09"; rapport `docs/rapporten/2026-09-23-nameting-ter-accordering-bestaanscheck-na-deploy.md`):**
  échte run `40b5d45c` (04:30–04:48 UTC, image `ac7639b`): 12 `HERCONTROLE`-regels, 82 open documenten vers getoetst, 0 overgeslagen, 11
  bevindingen = exact de verwachting van 22-09 (Bouwadvies 8, Molenhof 1, Rubicon 1) + Universal Steigerbouw 1 van 43 (RLZ-04-00003305; Universal
  draait in productie op RLZ — het bouwrapport van 22-09 noemde ten onrechte Odoo); `mail_status` `actie=verzonden`, delta nieuwe_afwijkingen 49 /
  verdwenen 11; het bot-bestand van 13:20 UTC (`3e358ba`, onderdeel `alles`) toont dezelfde 11 treffers. Twee meetlessen: (1) een `HERCONTROLE`-regel
  verschijnt alleen voor administraties mét open werk op dat moment — het aantal regels verschilt dus per run (12 om 04:30, 15 om 13:20 na het
  aanbieden van VGG-documenten), tel op documenten, niet op regels; (2) de stand (`actie`/`meten`) staat niet in `reconciliatie_bevinding.detail`
  maar in de registry — een meting op de stand leest `soort_stand.py` of het facet `soort=aandacht`, niet de rij. **Niet gemeten:** de handelingen
  (0 POSTs, 0 audits — ongebruikt) → dispatch-onderdeel `extern-geboekt` + vervolg-opdracht poging 2 (`niet vóór: 2026-09-24 09:00`).

<!-- toegevoegd 23-09-2026, opdracht "nameting-btw-plichtig-vgg-data-stap-en-lacy-lion" (poging 1) -->
- **Gemeten 23-09 — LET-OP `btw_status_bevestigen`: afwezig-pad JA, aanwezig-pad niet gemeten (BESLISSINGEN "BTW-PLICHTIG PER ADMINISTRATIE —
  NIET-PLICHTIG = BTW IN DE KOSTEN, HARDE CHECK (Peter 22-09)" alinea "Gemeten 23-09"):** de run van 23-09 04:30 UTC (`40b5d45c`) draaide vóór de
  eerste sync mét RLZ-signaal en produceerde 0 × `detail.automatisering = btw_status` (verwacht 0); de enige kandidaat (VGG, signaal false uit de
  sync van 05:03) is om 16:45 door de data-stap bevestigd (bron mens) en valt dus vóór de run van 24-09 uit de detector — de LET-OP-rij is in
  productie niet gezien en er is geen tweede kandidaat. Meetles: een LET-OP mét `administratie_id` staat onder RLS — een telling zonder
  `--administratie` op de replica geeft stil 0 (zelfde les als `reconciliatie_bevinding`-sweep en `audit_event`); toets een 0 altijd ook in de
  scope van de verwachte administratie vóór je 'm "verwacht 0" noemt. Rapport `docs/rapporten/2026-09-23-nameting-btw-plichtig-vgg-data-stap-en-lacy-lion.md`.

## Verwijsregels uit CLAUDE.md — WOORDELIJK verplaatst 02-10-2026 avond (bijvangst opdracht "besluiten-run-a-verwerken"; CLAUDE.md > 90k tekens)

> Blok "Reconciliatie, bewaking en meldingen", regel 6. De volledige regelalinea's hierboven blijven canoniek; dit zijn de letterlijke verwijsregels zoals ze tot 02-10 avond in CLAUDE.md stonden (per punt staat in CLAUDE.md nu één regel + verwijzing).

- (CLAUDE.md regel 6) Blok `webhooks` (run A punt 17, Peter 02-10, migratie 0175): een Vastly-409 `niet_koppelbaar` is status `wacht_op_ontvanger` mét cadans 1 u → 6 u → 24 u → dagelijks (max 14 dagen, daarna `mislukt` mét reden), nooit een dead-letter ná 8 pogingen; bevinding per rij (`webhook_wacht_op_ontvanger` in `meten`, `webhook_niet_koppelbaar_verlopen` direct `actie`) mét statuschip + "Nu opnieuw"; §3-notitie 02-10 in het koppelcontract, accordering §3c + 7-dagen-cadans = beslispunten Peter; dispatch-onderdeel `webhook-wacht` — zie BESLISSINGEN "RUN A 02-10 — BOEKEN, PROJECTEN, MELDINGEN, KLEINE BUGS (Peter 02-10)".
