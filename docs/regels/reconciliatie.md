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
