# Regels — Kempen-doorbelasting en intercompany

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Tweezijdige motor bron-verkoop + spiegel-inkoop ("Boeken + doorbelasten"), whitelist + doelentiteiten, IC-vlag, tegenboek-pad ná ingediende aangifte, aansluiting KF ↔ doelentiteiten, herkoppeling, intercompany slaat klant-accordering over.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Kempen-doorbelasting** (besluit Peter 2026-08-13; canoniek `verkenning/16_DOORBELASTING_KEMPEN.md` + BESLISSINGEN
  registerrij "KEMPEN-DOORBELASTING" + archief "Domeinbeslissingen — Kempen-doorbelasting"): tweezijdige motor bron-verkoop + spiegel-inkoop, "Boeken + doorbelasten", whitelist +
  "+ Doelentiteit toevoegen", IC-vlag, storno-blokkade ná ingediende aangifte (`app/rlz/aangifte.py`) → TEGENBOEK-PAD,
  rechtsgeldige factuur-PDF, doorbelasting × projecten. Zie ook BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt A,
  "ONBOARDING-BATCH 15-08", "Doorbelasting-kliktest-nazorg", "TEGENBOEK-PAD", "GECOMBINEERDE RUN 26-08" blok A,
  "GECOMBINEERDE RUN 01-09" blok B, "RLZ-FEEDBACKRONDE 25-08 DEEL 2" punt 2.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Doorbelasting — aansluiting KF ↔ doelentiteiten + herkoppeling doelentiteit (Peter 12-09/16-09; geen migratie):** whitelist-rijen zonder doel koppelt het systeem op exacte genormaliseerde naam (onboarding + dagelijks; bijna-match/meerdere = LET-OP "Koppel administratie…", nooit raden; `app/doorbelasting/herkoppeling.py`, teller `doorbelasting_herkoppeling`); lees-only CLI `doorbelasting-aansluiting --bron … --jaar …` + dagelijks reconciliatieblok `doorbelasting_aansluiting` (bron-verkoop geboekt+concept ↔ inkoop in álle doelentiteiten op álle crediteurrecords van de bron-identiteit, dezelfde motor als het IC-blok, soorten sluit/ontbreekt/bedrag/status/doel-niet-in-module/inkoop-zonder-verkoop, inhaalpad als actie waar een spiegel-taak bestaat) — zie BESLISSINGEN "DOORBELASTING — AANSLUITING KF ↔ DOELENTITEITEN + HERKOPPELING (Peter 12-09/16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Bugfix 14-09 — Instellingen › Doorbelasting 500 op een administratie zonder instellingen-rij (melding Peter 14-09):** een kaal geconstrueerd ORM-object heeft geen kolom-defaults (die gelden pas bij INSERT) → `DoorbelastingInstelling.standaard()` is de ENIGE bron voor de niet-opgeslagen standaardstand (route, checks, bulk-verdeling); opruimlijst-scan zonder RLZ-credential = zichtbare fout-regel i.p.v. 500 — zie BESLISSINGEN "BUGFIX 14-09 — INSTELLINGEN › DOORBELASTING 500 OP ADMINISTRATIE ZONDER INSTELLINGEN-RIJ".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Intercompany slaat klant-accordering over (blok 4 bundel 08-09 avond, besluit Peter 08-09; geen migratie):** leverancier met IC-vlag (actieve rij in `intercompany_tegenpartij` van de ADMINISTRATIE VAN HET DOCUMENT — één leesbron `app/doorbelasting/intercompany.py`, ook voor bank) in een administratie mét klant-accordering → zelfde flow, géén ronde, direct de boekstap (handmatig én autoboek), tijdlijn + audit "intercompany — klant-accordering overgeslagen (leveranciersregel)", DTO-veld `accordering_overgeslagen_reden`, knop "Boeken", historie "overgeslagen — intercompany"; lege IC-tabel = gewone flow; een lopende ronde blijft leidend — zie BESLISSINGEN "INTERCOMPANY SLAAT KLANT-ACCORDERING OVER".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Intercompany-leveranciers instelbaar (nachtrun 08/09-09, besluit Peter op beslispunt 1; geen migratie):** Beheerder-blok "Intercompany — accordering overslaan" op Instellingen › Administraties › ‹BV› › Klant-accordering (crediteur-combobox, herkomst-chip `handmatig`/`doorbelasting`, verwijderen = `actief=False`, audit + historie), routes `…/intercompany-leveranciers`, CLI `intercompany-leverancier-markeren`; eenmalige rij Universal Nederland → Universal Steigerbouw ná deploy via Cloud Run-job — zie BESLISSINGEN "INTERCOMPANY-LEVERANCIERS INSTELBAAR + EENMALIGE RIJ UNIVERSAL".

<!-- toegevoegd 19-09-2026, opdracht "ic-spiegel-rood-174-doorbelastingsparen-verkoop-niet-gevonden" -->
- **Doorbelastingsparen in de IC-toets en de aansluiting — verkoopkant via `Receipts`, whitelist per scope (19-09; geen migratie;
  BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)", rij "Systeemfout ic_spiegel_rood 174×"):** de doorbelastings-verkoopfactuur (PUT `SalesInvoices/{uuid5}`,
  Entity = `doel_customer_guid`, Date/BookDate = factuurdatum bron) staat in RLZ wél als record maar NIET in de
  `SalesInvoices`-collectie; alleen de `Receipts`-collectie toont 'm (STAP-0 19-09: Kempen Facilities → Mantelzorgwoningen, count 8 op
  Entity + datum, `DocumentType` 10). Het IC-blok én het aansluitingsblok lezen de verkoopkant daarom als `SalesInvoices` ∪ `Receipts`.
  De GUID-afleiding (`rlz_doorbelasting_verkoop_id`) en de IC-relaties (basis `doorbelasting`, entity = `doel_customer_guid`) waren
  correct — de hypothese "verkeerd GUID/boek_cyclus" uit de opdracht is weerlegd. `bronnen_met_whitelist` leest de whitelist sinds
  19-09 per administratie in eigen scope (patroon `relaties._doorbelasting_kandidaten`); zonder scope gaf FORCE RLS in productie 0
  rijen en meldde het aansluitingsblok drie dagen "geen administratie met een actieve doorbelasting-whitelist". Verwachting ná
  deploy: 174 → 0 `ic_spiegel_rood`, spiegelparen 174/174 groen, aansluiting KF: 8 doelen gelezen (Kempen Chalets/Rubicon zonder
  boekingen in het venster = 0 sluit, geen bevinding).
  **Gemeten 19-09 (rapport `2026-09-19-nameting-ic-spiegel-rood-na-deploy.md`): 174 → 0, alle vijf doelen N/N groen, Mantelzorgwoningen 51/51/51;
  aansluiting KF 8 doelen, 1652 van 1758 verkopen sluiten — werkt in productie JA.** De verwachting "0 afwijkingen" was ongegrond: 108 afwijkingen,
  waarvan 99 × Kempen Facilities → Molenhof Beheer `da_ontbreekt_in_doel` (KF-verkopen zonder inkoop bij Molenhof Beheer op enig KF-crediteurrecord —
  klikpunt Peter: worden die daar anders geboekt?), 3 × verkocht aan Oirschot Recreatie / ingeboekt bij Veldhoven Recreatie (24712615/24712648/
  24712802), 2 × nummer-verwisseling 24712869/24712873 € 69,82, 1 × kliktest-spiegel 24713191 (16-08). De verkoopkant via `Receipts` maakt óók
  KF-verkopen zichtbaar die vóór de fix voor het IC-blok onzichtbaar waren (+2 `ic_ontbreekt_bij_ontvanger` Molenhof Beheer 24712908/24712909).
  **Gemeten 19-09 avond (poging 1, executie `j6kgg`, image `aef301f`): `reconciliatie-alles --alleen doorbelasting_aansluiting --lees-only` werkt op
  de job-image (geen argparse-fout meer), 1 bron / 8 doelen / 1758-1660-1652 / 108 afwijkingen (99/3/3/2/1) identiek — werkt in productie JA**
  (rapport `2026-09-19-nameting-ic-spiegel-rood-echte-run-poging-1.md`); de auto-sluiting van de 174 fouten volgt in poging 2 ná de run van 20-09.
  **Gemeten 20-09 in de échte scheduler-run `55facc7c` (poging 2, rapport `2026-09-20-nameting-ic-spiegel-rood-echte-run-poging-2.md`): IC-blok
  "spiegelparen 174 groen / 0 rood, 0 fout(en)", de 174 × `ic_spiegel_rood` automatisch gesloten mét audit; aansluitingsblok KF 8 doelen,
  1744 verkoop / 1649 inkoop / 1641 sluiten, 105 afwijkingen (96 Molenhof Beheer + 3 Oirschot `da_ontbreekt_in_doel`, 4 `da_inkoop_zonder_verkoop`,
  2 `da_bedrag_afwijkt`) — 108 → 105 is géén regressie maar het 400-dagen-venster dat van 2025-08-15 naar 2025-08-16 schoof: precies de drie
  Molenhof-Beheer-verkopen van 15-08-2025 vielen eruit (lees-only 19-09: 3 × `datum=2025-08-15`). De explosie-rem zette `da_ontbreekt_in_doel`
  (99 > 50) naar `meten` mét audit `bevindingssoort_naar_meten` + `automatisering_regressie` + LET-OP `bevindingssoort_explodeert`; de 3 Oirschot-
  rijen vallen mee onder die stand (soort als geheel), de 6 andere `da_*` blijven `actie`. Klikpunt Molenhof Beheer (worden KF-verkopen daar buiten
  de KF-crediteurrecords geboekt?) staat open — pas ná dat antwoord mag `da_ontbreekt_in_doel` terug naar `actie`.**

<!-- toegevoegd 21-09-2026, opdracht "corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten" -->
- **Correctie van een doorbelaste bron-inkoopfactuur neemt de spiegels mee (21-09; geen migratie; BESLISSINGEN "CORRIGEREN VANUIT DE
  MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)"):** "Corrigeren…" op een geboekte inkoopfactuur mét niet-gestorneerde
  doorbelasting-boekingen leest éérst `storno_toets_voor_document` (aangiftepoort op bron-verkoop én spiegel-inkoop, fail-closed) —
  één geblokkeerde kant blokkeert de hele correctie ("beide kanten of geen", nooit half); is alles vrij, dan draait per boeking de
  bestaande motor `storno_doorbelasting_boeking` (spiegel → bron-verkoop, eigen transacties, `doorbelasting_gestorneerd`-tijdlijn en
  `_meld_spiegel_gestorneerd`) VÓÓR de storno van het eigen stuk; mislukt een spiegel-storno, dan stopt de correctie mét een fout die
  benoemt welke doelen al terug zijn (audit `document_correctie_mislukt`) en blijft de bron lokaal GEBOEKT. De run gaat via de motor
  naar `gestorneerd`; de mens zet de doorbelasting ná de herboeking opnieuw klaar ("Boeken + doorbelasten"). De gele balk en de
  tijdlijnregel `gecorrigeerd` noemen de teruggedraaide doelentiteiten.

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Kempen-doorbelasting (motor, spiegel, storno-blokkade, tegenboek-pad, factuur-PDF, projecten) (CLAUDE.md `ed6d176` r. 829–936)

- **Kempen-doorbelasting (besluit Peter 2026-08-13, hoort bij de livegang; canoniek
  `verkenning/16_DOORBELASTING_KEMPEN.md` + BESLISSINGEN "KEMPEN-DOORBELASTING")**: tweezijdige
  motor op het HUIDIGE patroon (2025/2026, granulair per document; historie = archief). Actie
  "Doorbelasten…" op een GEBOEKTE inkoopfactuur (toggle per bron-administratie, default UIT —
  alleen Kempen Facilities) **én — besluit Peter 25-08, herziet 13-08 — het optionele
  controlescherm-blok "Doorbelasten na boeken" op een NOG NIET geboekt document (run-fase
  `klaargezet`, migratie 0065): boek- en doorbelasting-checks samen groen → knop "Boeken +
  doorbelasten" → orkestratie `app/doorbelasting/orkestratie.py` draait beide bestaande
  motoren in één gang (inkoop → verkopen → spiegels; fout ná de inkoopboeking = zichtbaar op de
  run, half-geboekt-patroon); bij klant-accordering gaat de verdeling mee (accordeur ziet ze
  alleen-lezen, bevroren tot het besluit) en boekt alles ná het laatste akkoord. Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt A** →
  regelverdeling in % (exact 100%, grootste-rest-centen) over de geseede mapping-whitelist
  (doelentiteit ↔ customer-GUID, server-side afgedwongen, `make doorbelasting-seed-kempen`;
  **sinds 01-09 óók via "+ Doelentiteit toevoegen" op Instellingen › Doorbelasting — mockup
  `doorbelasting-doel-toevoegen.html` = norm, Beheerder-only POST naast het wijzig-endpoint:
  debiteur-lookup op naam in de bron-RLZ mét deterministische bijna-match (Mantelzorg-les
  enkelvoud/meervoud: match altijd expliciet bevestigen, nooit stil koppelen), geen match =
  idempotente aanmaak via `zorg_voor_debiteur`, provisie-GB vooringevuld op rekeningcode,
  IC default aan — BESLISSINGEN "GECOMBINEERDE RUN 01-09" blok B**) →
  per doelentiteit: verkoopfactuur in de bron (kostenregels + losse provisieregel, provisie-%
  en vlak btw-tarief als config) + spiegel-inkoopfactuur in de doel-administratie (idempotente
  crediteur-aanmaak, Reference = verkoopnummer — bron éérst, STAP-0 2026-08-13),
  half-geboekt-patroon omzetmotor + `spiegel_open`-taak bij niet-onboarded doel (nooit stil
  half), storno beide kanten (reden verplicht), `make doorbelasting-reconciliatie` (vierde
  bron in reconciliatie-alles). **Spiegel-webhook (akkoord Peter 2026-08-14, gebouwd + getest
  zelfde dag, migratie 0046)**: een spiegel-inkoopfactuur in een `is_vastgoed`-doel vuurt óók
  `factuur_geboekt` (standaard inkoop-veldvorm, leverancier = Kempen Facilities, referentie =
  spiegel-Reference) — `webhook_uitgaand.administratie_id` draagt dan de dóél-administratie
  (document_id blijft het bron-document); afleveraar levert per coalesce onder het doel,
  nooit dubbel. Koppelcontract v1.13 §3 "Doorbelasting-spiegelkant". **Spiegelkant geverifieerd via Rubicon (§2c)**: kosten-GB's
  type 2 (géén activering), 21% aftrekbare voorbelasting, eigen provisierekening 4808;
  ⚠️ RC geldt dáár niet → **intercompany-vlag per mapping-rij** (blok 2, migratie 0045):
  IC-open-posten uit álle afletter-voorstellen + fail-closed poort
  (`IntercompanyPostUitgesloten`); `payment_item_cache.entity_guid` via geneste expand
  `Document($expand=Entity)`. Bouwstatus: blokken 0–2 gebouwd 2026-08-13 (migraties
  0044/0045), UI + motor-tests in afronding — zie BESLISSINGEN.
  **GEACTIVEERD (onboarding-batch 2026-08-15, BESLISSINGEN "ONBOARDING-BATCH 15-08"):**
  Facilities + 5 doelen (Molenhof B/V, Oirschot Recreatie, OVB, Veldhoven) onboarded
  (smoketest-protocol: rechten-probe, syncs, TEST-boeking+storno geverifieerd), whitelist
  geseed + live geverifieerd, per rij provisie-GB (4173/4808) + IC-vlag (álle 5 doelen hebben
  RC Kempen Facilities — anders dan Rubicon, dus IC=true; alleen Rubicon-rij false; §2c-vervolg
  in verkenning/16), toggle AAN alleen Facilities. ⚠️ Drie doelen activeren deels op
  AccountType-3-rekeningen (spiegelverdeler kiest dan een activarekening). NIJENHUIS
  (kantoor-administratie) na credential-herstel zelfde dag alsnog onboarded — 11/11.
  **Kliktest Peter UITGEVOERD (2026-08-16, volledige cyclus geslaagd; nazorg in twee rondes
  — BESLISSINGEN "Doorbelasting-kliktest-nazorg" (ronde 1: opslag-bug + client-validatie) en
  "ronde 2")**: "verkopen op concept" = correct gedrag ná Peters eigen storno;
  RLZ-UI-vindbaarheids-hypothese (ontbrekende DocumentCategory) WEERLEGD — beide kanten
  krijgen automatisch de categorie/boekstuk-reeks van Peters historische praktijk
  (api-verkenning "DocumentCategory & boekstuk-reeksen": reeks-prefix volgt de categorie;
  Verkopen→Facturen-lijst toont API-facturen sowieso niet, dat is RLZ-collectie-gedrag);
  storno beide kanten geverifieerd (5 spiegels Status 1; bron-concepten daarna handmatig in
  de RLZ-UI verwijderd — bevestiging Peter open). **Randgeval storno-ná-btw-aangifte
  (vraag Peter 15-08) ONDERZOCHT: RLZ weigert actie 19 NIET** — het verschuift de
  terugdraai-btw zelf als negatieve TaxSource naar de eerstvolgende open aangifte-periode
  (api-verkenning "Actie 19 in een periode met ingediende btw-aangifte"); foutvertaling +
  alles-of-niets-zorg vervallen. **Vervolg-besluit Peter 15-08, GEBOUWD + GETEST 2026-08-16:
  harde STORNO-BLOKKADE ná ingediende aangifte** — poort `app/rlz/aangifte.py` (TaxDeclarations
  Status 2/3 dekt de boekdatum = storno geblokkeerd, fail-closed bij onleesbaarheid, 404/
  concept vrij) vóór álle bestaande storno-paden: bank-direct én doorbelasting (alles-of-niets
  over bron + doel, per kant zichtbaar waarom; UI-knop disabled mét melding via de
  storno-toets-leesroute; interne rollback-storno's ín een boek-transactie bewust niet gepoort
  — btw-netto-nul). **Het tegenboek-pad is GEBOUWD + GETEST
  (2026-08-22, migratie 0061 — mockup tegenboek-mockup.html; het suppletie-signaal is
  definitief GESCHRAPT, besluit Peter 22-08): is storno door de aangifte-poort geblokkeerd,
  dan biedt het controlescherm (en het ⋯-menu in het archief) "Tegenboeken…" — een NIEUWE
  PurchaseInvoice met gespiegelde negatieve regels op dezelfde Entity, boekdatum vandaag
  (btw = negatieve voorbelasting in de open periode, STAP-0 api-verkenning "Tegenboek-pad
  STAP 0"); volledig (chip TEGENGEBOEKT + kruisverwijzing) óf tegenboeken-én-opnieuw-boeken
  (GEBOEKT→te_controleren, boek_cyclus+1 — herboeking op een eigen RLZ-GUID, uitgezonderd
  van het duplicaatsignaal); harde checks onverkort, verplichte reden, betaalstatus-
  waarschuwing (open creditpost); vastgoed krijgt het als factuur_geboekt-event met
  negatieve regels (creditnota-norm §3a) mét — sinds 2026-08-23, akkoord Vastly, schema
  1.1→1.2/contract v1.17 — het optionele veld `corrigeert_document_id` (= rlz_document_id
  van het origineel, UITSLUITEND op tegenboeking-events; de herboeking draagt het níét),
  bewust géén factuur_gestorneerd. Zie BESLISSINGEN "TEGENBOEK-PAD".** Kliktest-herstart geverifieerd (BESLISSINGEN
  "KLIKTEST-HERSTART"): her-PUT op een bestaand concept vervángt de DocumentLineList (live
  bewezen, api-verkenning "Her-PUT op een bestaand concept"). **Kliktest 2 strandde alsnog
  op de bijlage-upload (nazorg ronde 3, gefikst + getest 2026-08-16): RLZ's /Uploads kent
  géén her-PUT** (bestaand GUID = 400, verbruikt GUID van een verwijderd document = 404;
  api-verkenning "Uploads bij een herstart-boekcyclus") — bijlage-idempotentie loopt sindsdien
  in álle motoren via `app/rlz/bijlage.py::zorg_voor_bijlage` (aanwezigheids-check via de
  Uploads-leesroute + deterministische cyclus-GUID's). **RECHTSGELDIGE FACTUUR-PDF (blok A
  gecombineerde run 26-08, besluit Peter, migratie 0077 — BESLISSINGEN "GECOMBINEERDE RUN
  26-08" blok A is canoniek):** ná de verkoopboeking rendert de motor RLZ's eigen factuur
  (`GET SalesInvoices/{id}/Download` mét `Accept: application/pdf` — route A; stamgegevens/
  btw-nummer zijn via de API níét leesbaar, dus geen eigen generator), toetst deterministisch
  op de gerenderde tekst (nummer = spiegel-Reference, KvK, btw-nummer, geboekte bedragen
  cent-exact) en zet 'm als bijlage op BEIDE kanten (spiegel: eerste bijlage, bon tweede;
  `zorg_voor_bijlage(op_bestandsnaam=True)` = meerdere bijlagen per document); ontbreekt =
  `factuur_pdf_status ontbreekt` mét reden, nooit blokkerend; download op de run; nazorg
  `make doorbelasting-facturen-herstel` (`DRY_RUN=1` eerst). `app/doorbelasting/factuur.py`.
  **Opruimlijst achtergebleven
  RLZ-concepten (2026-08-16): de doorbelasting-reconciliatie signaleert Status-1-concepten
  van gestorneerde/vervallen runs (beide kanten, informatief — nooit exit 1) + scanknop op
  Instellingen → Doorbelasting; de app verwijdert NOOIT in RLZ (kernprincipe 3, expliciet
  herbevestigd door Peter) — opruimen is klikwerk in de RLZ-UI, indien gewenst.**
  **Doorbelasting × projecten (besluit Peter 25-08 "optie 2", GEBOUWD + GETEST 2026-08-25,
  migratie 0067 — BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 2" punt 2 is canoniek):** per
  verdeelregel een project uit de DOEL-administratie (verplicht + blokkerende check zodra dat
  doel `project_verplicht` aan heeft; spiegel-regels dragen `Project:{id}`, webhook `project_id`
  per regel), multi-project binnen een doelentiteit (alle actieve projecten; basis naar rato
  contract-m² — ontbrekende m² = geweigerd, nooit gokken — óf gelijk per object; centen
  server-side via de herbruikbare pure motor `app/doorbelasting/verdeelhulp.py`; één
  spiegel-regel per project), verdeelsleutels per bron-administratie (naam + versie,
  append-only, één klik toepassen, herleidbaar op de run + audit). Verdeelhulp-UI voor gewone
  regel-splitsing zonder doorbelasting = parkeerpost.
