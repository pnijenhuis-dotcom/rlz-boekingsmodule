# Regels — Bank: sync, matchmotor, afletteren, splitsen, batches

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Bank-sync automatisch (07:00) zonder knoppen, voorstel-volgorde exact → gedeeltelijk → vaste regel/historie-regel → RLZ-voorstel → handmatig, afletteren via actie 15 op de PaymentTransaction, batch-stap, open bedrag als maat, zoekveld, Ponto = Jarvis.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Bank**: klantenlijst → rekening (alle `PaymentAccounts` incl. kas). Voorstel-volgorde:
  1) exacte match naam+factuurnr+**bedrag** → auto-afletteren; 2) gedeeltelijke match → bevestigen;
  3) vaste regels (geheugen; na 3× zelfde handmatige boeking regel voorstellen); 4) RLZ's eigen
  voorstel (bron tonen — **schrijf-PoC 2026-08-02: voedingsbron bestaat wél, auto-gevuld
  `MatchedPaymentItem` bij exacte bedrag-match — de eerdere STAP-0-conclusie "geen voedingsbron"
  is herzien**); 5) handmatig. Afletteren gaat NIET door de klant-accorderingsflow.
  Bankmodule GEBOUWD + GETEST (2026-08-02); afletteren-tegen-open-post sinds 2026-08-09 ÉCHT via de API
  (`app/bank/afletteren.py`, zie "Reeleezee API" hierboven); bank-autoboeken opt-in per administratie; bank-verdieping
  25-08 deel 4 (auto-verversing, "Koppel aan relatie" = aanbetalingsdocument, splitsen; migratie 0071) en blok E 01/02-09
  (knoppen weg, voorstel-kaart). Zie BESLISSINGEN "Bankmodule — GEBOUWD + GETEST", "Afletteren-tegen-open-post:
  GEKRAAKT", "RLZ-FEEDBACKRONDE 25-08 DEEL 4", "BANKSCHERM BLOK E"; RLZ-feiten in api-verkenning "Bankmodule
  schrijf-PoC" + "Bankmutatie op een RELATIE + mutatie SPLITSEN — STAP-0 (25-08)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Bank-sync automatisch, geen knoppen (blok 1 bundel 08-09, besluit Peter 08-09; geen migratie):** `sync-alles` (07:00) draait de bank-sync voor álle actieve administraties via `bank/sync_run.py::sync_alle_via_runs` (bank_sync_run-rij mét `resultaat.bron = "sync_alles"`, Odoo/geen credential = zichtbaar overgeslagen, geen fout), klantenlijst toont de laatste sync-tijd, versheid = zichtbare chip, reconciliatie-teller `bank_sync` (LET-OP "geen bank-sync-run" platformbreed + kapotte login per administratie), bank-levenscyclus volgt het afgehandeld-patroon (`?toon_oud=true`, 30 dagen) — zie BESLISSINGEN "BANK-SYNC AUTOMATISCH, GEEN KNOPPEN".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Nameting-instrument matchmotor (blok 0 bundel 09-09):** LEES-ONLY CLI `bank-voorstellen-lezen --administratie … [--rekening-iban] [--filter]` op de gedeployde job-image (vervangt het proxy-script; regel Peter 08-09) — zie BESLISSINGEN "BUNDEL 09-09 — BLOK 0".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Matchmotor bank herzien (blok 2 bundel 08-09; migratie 0127):** open-post-voorstel op score teken + naam/IBAN + factuurnummer als HEEL token + bedrag cent-exact — GROEN (auto-afletteren-kandidaat) = alle vier, ORANJE (bevestigen) = geen teken-mismatch + twee van drie, label `bron` zegt exact wat matchte; IBAN↔RLZ-entity-geheugen `bank_relatie_iban` leert bij élke bevestigde aflettering (`app/bank/iban_geheugen.py`); gouden-set-casus `l_bank_cv_08-09` — zie BESLISSINGEN "MATCHMOTOR BANK — NAAM/IBAN + NUMMER + BEDRAG + TEKEN".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Matchmotor bank — klantreferentie als nummer (Peter 15-09, casus Clean Care Arnhem; geen migratie):** het nummer-criterium toetst naast RLZ's volgnummer (`PaymentItem.Reference` "706") óók de klantreferentie van het document (`Document.Reference` = `InvoiceNumber` 2025689, ≥ 4 tekens, geen IBAN/placeholder) als heel token → label "referentie 2025689", groen mét naam + bedrag + teken; kaart toont `Document.Date` als factuurdatum (nooit `PaymentItem.BookDate` = vervaldatum); gouden-set-casus y — zie BESLISSINGEN "MATCHMOTOR BANK — KLANTREFERENTIE ALS NUMMER (Peter 15-09)" + api-verkenning "PaymentItems — klantreferentie en factuurdatum".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Bankscherm — zoekveld + batch-stap + compacte koppelingstekst (Peter 16-09, screenshot Bouwadvies; geen migratie):** zoekveld client-side op naam/IBAN/omschrijving/bedrag/nummer mét `?zoek=`, teller en klik-op-naam (`bank/bankZoek.ts`); matchmotor-stap 0 "batch" = `PaymentBatchId` van de bankregel == `PaymentTermList.PaymentBatchInformation` van de open posten (sync-expand `Document($expand=Entity,PaymentTermList)` mét terugval), Σ = open bedrag → groen, anders oranje mét verschil, nooit bij `ReturnReason`; afletteren = N × actie 15 via `POST …/afletteren-batch` (server herberekent, idempotent per post); > 1 RLZ-koppeling = één regel + uitklap — zie BESLISSINGEN "BANKSCHERM — ZOEKVELD, BATCH-STAP (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Betalen via Ponto = JARVIS, niet deze module (besluit Peter 16-09 22:00; docs-only):** de RLZ-module bouwt geen Ponto-client/betaalmodule, blijft de enige schrijver naar RLZ/Odoo, levert Jarvis de feitenset `betaalbaar` en ontvangt betaal-events (HMAC, 0023-vorm) → `QuickPaymentSelection` "Betaald per bank" + afletteren via de batch-stap; kantoor betaalt als vertegenwoordiger, SCA bankzijde — zie BESLISSINGEN "BETALEN — EIGENAAR JARVIS, RLZ LEVERT FEITEN EN ONTVANGT STATUS (besluit Peter 16-09 22:00" (registerrij).

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Incasso-/betaalbatches uit RLZ — STAP-0 lees-only (blok 10 run 11-09 middag; geen bouw, geen migratie):** de batch leeft op de bankregel (`PaymentTransaction.PaymentBatchId` + `$expand=Batch` → `PaymentTransactionBatch {BatchId, FileName, RemainingAmount}`) en de factuur draagt DEZELFDE sleutel vooraf (`PaymentTermList.PaymentBatchInformation`, bewezen 12/12 op Universal Steigerbouw); geen batch-collectie in de API (`Remittances` = kasafsluiting, `DirectDebits`/`CreditTransfers` = kandidatenlijsten), R-transacties alleen als `ReturnReason` (count 0) + actie 115; lees-only CLI `rlz-lezen` (weigert élke niet-GET en elk Actions-pad, `--top` ≤ 50, altijd geanonimiseerd, in de nameting-allowlist); voorstel matchmotor-stap "batch" (sleutel + som = groen, N × actie 15) wacht op akkoord — zie BESLISSINGEN "INCASSO-/BETAALBATCHES UIT RLZ — STAP-0 LEES-ONLY" + api-verkenning "Incasso-/betaalbatches — STAP-0 11-09".

<!-- uit CLAUDE.md § Werkwijze -->
- **Bank — deels afgeletterde mutaties: open bedrag is de maat (nachtrun 10/11-09 blok 3; bug Peter Zilver Beheer; migratie 0131):** `open_bedrag` stuurt voorstellen, boeken (dekking ≠ open = 409 "Bedrag dekt niet het open bedrag van de mutatie …"), regels, historie en splitsen; verversronde haalt OpenAmount + `PaymentReferenceList` op (`bank_mutatie.rlz_koppelingen`); lijst toont "€ 5.023,09 · open € 2.511,05" + chip "deels afgeletterd in RLZ"; gouden-set-casus `l_bank_cv_08-09` uitgebreid; verrekening bank↔bank = STAP-0 lees-only (bestaat niet in de RLZ-API; keuze RLZ-vorm bij Peter) — zie BESLISSINGEN "BANK — DEELS AFGELETTERDE MUTATIES" + api-verkenning "Verrekening tussen twee bankmutaties — STAP-0".

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Bank (bankmodule, afletteren, bank-verdieping 25-08 deel 4, blok E) (CLAUDE.md `ed6d176` r. 767–828)

- **Bank**: klantenlijst → rekening (alle `PaymentAccounts` incl. kas). Voorstel-volgorde:
  1) exacte match naam+factuurnr+**bedrag** → auto-afletteren; 2) gedeeltelijke match → bevestigen;
  3) vaste regels (geheugen; na 3× zelfde handmatige boeking regel voorstellen); 4) RLZ's eigen
  voorstel (bron tonen — **schrijf-PoC 2026-08-02: voedingsbron bestaat wél, auto-gevuld
  `MatchedPaymentItem` bij exacte bedrag-match — de eerdere STAP-0-conclusie "geen voedingsbron"
  is herzien**); 5) handmatig. Afletteren gaat NIET door de klant-accorderingsflow.
  **Bouwstatus: bankmodule GEBOUWD + GETEST (2026-08-02); afletteren-tegen-open-post sinds
  2026-08-09 ÉCHT via de API (seam-swap na de capture-replay — zie "Reeleezee API" hierboven
  en BESLISSINGEN "Afletteren-tegen-open-post: GEKRAAKT")** — `backend/app/bank/` +
  `frontend/src/bank/` + migratie 0026. De seam
  (`app/bank/afletteren.py::voer_afletter_actie_uit`) legt de koppeling via
  `RlzClient.link_payment_item` mét directe verificatie (OpenAmount-hertoets +
  PaymentReferenceList-leesspoor); het assist-pad is de expliciete FALLBACK bij een API-fout
  (opdracht blijft zichtbaar klaargezet mét foutmelding; de sync-verificatie dekt die route).
  Vóór elke link-call een vooraf-toets tegen de ACTUELE RLZ-staat (kliktest-fix 2026-08-09:
  "Nu afletteren" op een intussen al afgeletterde mutatie gaf een kale 404 — géén
  casing-probleem, client gepind op de bewezen `/Actions`-vorm): mutatie al dicht →
  "geverifieerd — al afgeletterd in RLZ" (geen fout, eigen chip), doel-post niet meer in de
  open-items-collectie → duidelijke fout vóór de call; verse OpenAmount leidend voor
  LinkedAmount.
  Stap 1 (exacte match) lettert automatisch af tijdens de bank-sync achter de opt-in
  `bank_autoboeken_ingeschakeld` + eigen volumerem, vóór de vaste regels; zonder opt-in en
  voor stap 2 (deelmatch, LinkedAmount = min(|mutatie|,|post|)) is het één-klik — nooit auto.
  Stap 3/5 = direct-op-grootboek, echt gebouwd (deterministisch client-GUID, failsafes +
  volumerem + duplicaatchecks tegen verse RLZ-staat, storno actie 19 met verplichte reden);
  autoboeken van vaste regels = opt-in per administratie (zelfde vlag, default UIT, bovenop
  de boeken-failsafes).
  Vastly-terugkoppeling: `factuur_afgeletterd`-event via de bestaande webhook-afleveraar
  (detectie op documentstatus 3; formele opname in koppelcontract §3 nog af te stemmen met
  vastgoed). Failsafe: `make bank-reconciliatie` vangt in de RLZ-UI teruggedraaide
  boekingen/afletteringen. Zie api-verkenning.md "Bankmodule schrijf-PoC" + "Bankmodule
  FALLBACK-PoC" en BESLISSINGEN "Bankmodule — GEBOUWD + GETEST".
  **Bank-verdieping feedbackronde 25-08 deel 4 (besluiten Peter, GEBOUWD + GETEST 2026-08-25,
  migratie 0071 — BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 4" is canoniek; RLZ-feiten in
  api-verkenning "Bankmutatie op een RELATIE + mutatie SPLITSEN — STAP-0 (25-08)"):**
  (2) **auto-verversing bij openen** — cache direct + "laatst ververst HH:MM", 202+status-poll
  (`app/bank/sync_run.py`, tabel `bank_sync_run`, job `rlz-bank-sync`/CLI `bank-sync-wachtrij`),
  drempel `bank_auto_ververs_drempel_minuten` = 5 (jongere sync = `overgeslagen`) — **HERZIEN 01/02-09
  (blok E, BESLISSINGEN "BANKSCHERM BLOK E"): de knoppen "Verversen uit Reeleezee"/"Nu verifiëren" zijn
  weg; versheid + klein ⟳ (noodrem, `?forceer=true` slaat alleen de drempel over) staan vast in de
  paneelkop, de verificatie van wachtende afletteropdrachten lift in élke ronde mee (`afletteren_wachtend`,
  alleen gemeld als er iets wachtte), succes = toast, fouten persistent; voorstel-kaart mét doel-post-specs
  uit `payment_item_cache` (`bank/doelpost.py`, mockup `bank-voorstel-kaart.html`), match-chip
  groen/oranje, deelmatch "restant € X blijft open" + "Afletteren (deel)", geen match = tekstregel, zelfde
  kaart in splitsen (`VoorstelKaart.tsx`)**; (3) **derde verwerkroute "Koppel aan relatie"** — RLZ kent geen relatie-boeking zonder
  document (Entity op BMDB/memoriaal = 500), de bewezen vorm is het **aanbetalingsdocument**:
  PurchaseInvoice (crediteur, één regel op systeemrekening 1403, expliciet 0%-"Nul tarief" —
  zonder tarief rekent RLZ 21%) resp. SalesInvoice (debiteur, 1806) + actie 15; verrekening =
  tegenregel −X op 1403 ín de latere factuur (actie 34 blijft dood); storno = actie 19 op het
  aanbetalingsdocument (mutatie volledig terug); de open aanbetaling per relatie leeft in
  `bank_relatie_boeking` (`app/bank/relatie.py`), zichtbaar in het paneel "Openstaande
  aanbetalingen" + **aanbetaling-open-signaal op het controlescherm** (`aanbetaling_signaal.py`,
  Entity + leverancier-IBAN, knop "Verrekenregel toevoegen", hook `markeer_verrekend_bij_boeking`
  ín de boek-transactie) — signaal, geen blokkade, geen werkvoorraad-chip; (4) **splitsen** —
  geordende compositie open posten → relaties → grootboek via de bestaande motoren
  (`app/bank/splitsen.py`; Σ delen = mutatie server-side blokkerend; half-verwerkt zichtbaar +
  hervatten; storno per deel — een afletter-deel alleen via storno van de factuur in RLZ).
  ⚠️ **Nieuw RLZ-feit: her-PUT op een gestorneerd BankMutationDirectBooking = 204 zónder effect
  (actie 17 = 409)** → de directe boeking gebruikt sinds 25-08 een **cyclus-GUID**
  (`rlz_bank_boeking_cyclus_id`) én verifieert ná élke PUT de verse OpenAmount; deel-BMDB's
  accepteren een deelbedrag. Storno van een factuur-deel op een meervoudig gekoppelde mutatie
  laat OpenAmount tijdelijk stale (huls) — reconciliatie-aandachtspunt (parkeerpost).
