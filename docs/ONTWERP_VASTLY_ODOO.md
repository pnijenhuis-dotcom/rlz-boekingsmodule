# Ontwerp — Vastly-klant op een Odoo-boekhouding (verkoop, waarborg, bank/afletteren, webhooks)

**Status:** ONTWERP TER AKKOORD Peter (vraag Peter 19-09: "voor Vastly kunnen wij ook een Odoo-boekhouding koppelen? Maakt dat veel
uit?" + "VGG is daar niet de juiste voor: handelt in vastgoed, verhuurt niet — ARVUM B.V. of Rubicon Investments wél"). Geen bouw
vóór akkoord. Bronnen: `../Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md` v1.20 (§2c, §2d, §3, §8), `verkenning/odoo-verkenning.md`
§2.4, §3, §11.1–11.5, §12.4, `docs/regels/vgg-odoo-migratie.md`, `docs/regels/bank.md`, `docs/regels/omzet.md`, `app/odoo/*`,
`app/backends/*`. Auteur: Cowork 19-09-2026.

## 0. Antwoord in één alinea

Voor Vastly maakt het niets uit: Vastly praat nooit rechtstreeks met de boekhouding (contract v1.10: vastgoed schrijft niet in RLZ;
documenten komen als UBL via de boekhoudmail binnen, wij boeken, wij sturen de webhooks `factuur_geboekt`/`factuur_afgeletterd`
terug). Welke boekhouding erachter zit is een keuze per administratie in ónze module. Voor ons maakt het wél uit: van de vier
Vastly-stromen is er in de Odoo-adapter nu één klaar (inkoop), één half (memoriaal via de VGG-replay) en zijn er twee niet gebouwd
(verkoopfacturen schrijven, bank + afletteren). Die twee zijn precies wat ook nodig is voor élke verhurende Odoo-administratie, dus dit
ontwerp is generiek en de pilot is een verhuurder.

## 1. Wat een Vastly-administratie van de boekhouding vraagt (contract) en wat de Odoo-adapter nu kan

> **Bron-vs-realiteit-toets uitgevoerd door CC 19-09** (opdracht `opdrachten/gedaan/2026-09-19-ontwerp-vastly-odoo-toetsen-en-pilotmeting.md`,
> rapport `docs/rapporten/2026-09-19-ontwerp-vastly-odoo-toets.md`): élke rij hieronder is tegen de code (`app/backends/*`, `app/odoo/*`,
> `app/migratie/odoo_schrijf.py`, `app/verkoop/boeken.py`, `app/waarborg/boeken.py`, `app/bank/*`, `app/documenten/webhook.py`,
> `app/registersync/*`) en tegen odoo-verkenning §2.4/§3/§11/§12 + koppelcontract v1.20 gelegd. Correcties staan ín de rij als
> "gecorrigeerd door CC 19-09: …"; de stand-kolom is waar nodig bijgesteld. Niets gebouwd.

| Stroom (contract) | RLZ-pad (gebouwd) | Odoo-pad | Stand |
|---|---|---|---|
| Inkoopfacturen van de administratie (gewone intake) | PurchaseInvoices + Uploads + 17 | `in_invoice` + `action_post` (adapter blok E, live 04-09) — `app/backends/port.py::InkoopPort` (6 operaties) + `app/odoo/inkoop.py::OdooInkoopPort`; routering uitsluitend in `app/backends/registry.py::inkoop_port_voor` | **klaar** (bevestigd) |
| VASTLY-VERKOOP huurfacturen (UBL 380, §2d) + creditnota's (381) | SalesInvoices (`app/verkoop/boeken.py`), debiteur = échte huurder | `out_invoice`/`out_refund` — alleen mapping (§2.4), geen schrijfpad in `app/odoo/`. *Gecorrigeerd door CC 19-09:* een `out_invoice`-create bestaat wél, maar uitsluitend in de VGG-replay (`app/migratie/vertaling.py`, `cli_odoo.py`) achter de kill-switch `migratie_odoo_writes_ingeschakeld` en is in productie nooit gepost; `verkoop/boeken.py:209` opent rechtstreeks `_rlz_client_voor` en faalt op een Odoo-administratie met `GeenRlzCredentials` ("… is voor Odoo-administraties (nog) niet beschikbaar", `rlz/credentials.py:147-151`) — geen `NietOndersteund` uit de port, dus geen zichtbare capability-melding op het document | **te bouwen** (bevestigd) |
| VASTLY-WAARBORG (§2d-waarborgroute) → memoriaal op 0204 | ManualJournals (`app/waarborg/boeken.py`) | `entry` op MEM. *Gecorrigeerd door CC 19-09:* de schrijfvorm is bewezen in STAP-0 cyclus B (odoo-verkenning §4.2, company 1, 02-09) en zit als primitieve in `app/migratie/odoo_schrijf.py::maak_concept_move`/`post_move` (achter de kill-switch); de VGG-replay zelf heeft nog géén memoriaal gepost (SCHRIJF c wacht op beslispunt 1, regels vgg-odoo-migratie blok 12). `waarborg/boeken.py:80` gaat rechtstreeks via `_rlz_client_voor` (zelfde `GeenRlzCredentials`-uitval); `grep -ri waarborg app/odoo app/migratie app/backends` = 0 treffers | **half** — mechaniek bewezen, geen boekpad, geen port |
| Bank: sync, matchmotor, afletteren (actie 15), webhook `factuur_afgeletterd` (schema 2.0, bron `OpenAmount`) | volledig RLZ-specifiek (`app/bank/*`, 10 modules mét `RlzClient`) | `account.bank.statement.line` schrijven (§11.1, velden live), reconcile-route niet bewezen (§11.4 stap 4 open). *Gecorrigeerd door CC 19-09:* de primitieven bestaan al — `odoo_schrijf.py::maak_statement_line` (create + anker `unique_import_id`/`ref`), `reconcile` mét route-registry i `set_line_bank_statement_line` / ii `account.move.line.write`+`reconcile` / iii `account.reconcile.model.action_reconcile`, en `koppel_los` = `remove_move_reconcile` — alle achter de kill-switch, geen van drie routes live bewezen. `app/bank/` kent geen Odoo-pad: `sync_run.py:277` slaat een Odoo-administratie zichtbaar over ("bank loopt niet via Reeleezee"), `bank/reconciliatie.py:211` = `RLZ_ONLY_OVERGESLAGEN`. `fields_get` 19-09 (company 3, lees-only): `statement.line.is_reconciled` boolean readonly stored, `statement.line.amount_residual` float readonly stored, `unique_import_id` readonly=True (aanname §11.1 blijft: zetbaar via create = te bewijzen) | **te bouwen + STAP-0 nodig** (bevestigd; STAP-0 = de bestaande primitieven live bewijzen, geen nieuwe code vóór het bewijs) |
| Grootboek-sync §2c (`platform.grootboekrekening`, Vastly leest read-only voor `AccountingCost`) | RLZ `Ledgers` 4-cijferig | Odoo `account.account` 6-cijferig (sync bestaat, `app/odoo/sync.py::lees_grootboek`, upsert identiek aan de RLZ-sync; `code` is `text` zonder lengtelimiet — Bonte Hoeve op de leesreplica 19-09: 356 rekeningen, álle 6 tekens). *Gecorrigeerd door CC 19-09:* `ledger_id` van een Odoo-rekening = UUIDv5 (`odoo_uuid(company, "account.account", id)`), níét het Odoo-int-id; `is_totaalrekening` altijd `False`; `soort` = RLZ-AccountType-equivalent via `soort_voor_account_type` (vertaald, niet "onvertaald doorgezet" zoals §2c voor RLZ zegt) | **klaar aan onze kant; Vastly-kant toetsen** (zie §4.5) |
| Registersync §8 (huurders/objecten ↔ debiteuren/projecten) | debiteur = RLZ Customer, object = RLZ Project | debiteur = `res.partner` — *gecorrigeerd door CC 19-09:* `app/odoo/partners.py` maakt/zoekt uitsluitend CREDITEUREN ("+ Nieuwe crediteur", `supplier_rank`); een huurder-partner (`customer_rank`) uit de UBL is nieuw werk (zoek-vóór-create op KvK/naam, patroon §2.1). Object = analytic account plan Project (VGG-patroon pand = analytic; `mapping.py::aanmaken_analytic_accounts` bestaat). Registersync levert vandaag Odoo-administraties gewoon mee (`registersync/service.py:69`, geen backend-veld) mét `rlz_admin_id` = sentinel `odoo:<host>:<company>` — géén UUID, in strijd met §8 "rlz_admin_id = RLZ-adminId" → addendum-punt (§2.4) | **patroon bekend; huurder-partner te bouwen; §8-sentinel = contractpunt** |
| Webhook `factuur_geboekt` (rlz_document_id, referentie, adminId, regels) | — | payload-velden krijgen Odoo-id's (`odoo_uuid`). *Gecorrigeerd door CC 19-09:* dit gebeurt VANDAAG AL zonder addendum — `documenten/boeken.py:549` zet `rlz_document_id = uitkomst.extern_document_id` (Odoo: UUIDv5 van de move), `_sla_webhook_op` (`:311`, aangeroepen `:622-629`) filtert alleen op `is_vastgoed`, `rlz_admin_id` in de payload = de sentinel `odoo:<host>:<company>`, `rlz_boekstuknummer` = Odoo `name` (bv. `F/2026/00027`); er is géén `backend`-veld (`webhook.py:104-151`, schema 1.2). Vandaag dekt geen enkele is_vastgoed-administratie een Odoo-backend (leesreplica 19-09: alle zes op `rlz`), dus het is een latent drift-risico, geen productiefout. `factuur_afgeletterd` vuurt voor Odoo nooit (`bank/vastly.py:82` leeft in de bank-sync die Odoo overslaat en leest `BaseRemainingAmount`) | **contract-addendum nodig (v1.21)** (bevestigd, urgenter dan gedacht: gedrag bestaat al) |

*Gecorrigeerd door CC 19-09 — twee stromen die het ontwerp niet noemt en die voor een Vastly-administratie wél meelopen:* (a) **omzet-Receipts en
Kempen-doorbelasting** (`omzet/boeken.py:432`, `doorbelasting/boeken.py:502…1364`) zijn eveneens hard RLZ via `_rlz_client_voor` — Rubicon is
doorbelasting-DOEL (spiegel-inkoopfacturen landen dáár; BESLISSINGEN "Spiegelkant geverifieerd via Rubicon"), dus een Rubicon-op-Odoo vereist
óók de doorbelastings-spiegel via de `InkoopPort` (bestaat) mét de webhook-vorm §3 doorbelasting-spiegelkant; (b) **route A projectaanmaak §5**
(`app/projecten/`, klant-loze `PUT Projects`) is RLZ-only — voor een Odoo-administratie moet `rlz_project_id` de analytic-account-UUIDv5 worden
(mapping-soort `project` bestaat, de aanmaak-motor niet). Beide horen in de fasering (§4) als fase 2b resp. 3b.

## 2. Ontwerp per stroom

### 2.1 Verkoopfacturen naar Odoo (VASTLY-VERKOOP 380/381, later ook omzet-Receipts en doorbelasting)
- Nieuwe port `VerkoopPort` naast `InkoopPort` (`app/backends/port.py`), RLZ-implementatie = bestaande `verkoop/boeken.py`-motor
  verplaatst achter de port; Odoo-implementatie `app/odoo/verkoop.py`: `account.move.create` `move_type out_invoice`, `journal_id` = het
  verkoopdagboek uit de koppeling-probe (per company vastgesteld, 14-09), `partner_id` = huurder-partner (registersync §8),
  `invoice_date` = factuurdatum, `date` = BookDate-equivalent, `ref` = Vastly-factuurnummer + markering (Odoo neemt regel-1-Description
  niet over: marker naar `ref`, §2.4), regels `invoice_line_ids` met `account_id` uit de §2c-code via de grootboekmapping, `tax_ids`
  uit de btw-mapping (verkoopcodes 7/6/5/19 zijn company-1-id's — per company uit `odoo_rekening_mapping`, nooit hardcoden), `analytic_distribution` = object/pand; `action_post`. Creditnota = `out_refund` +
  `reversed_entry_id` waar `cac:BillingReference` de bron noemt. *Gecorrigeerd door CC 19-09 (`fields_get account.move`, company 3,
  lees-only):* `reversed_entry_id` is **readonly** (net als `invoice_origin`) — een 381-creditnota mét kruisverwijzing loopt dus via de
  `account.move.reversal`-wizard op het origineel (§3.3; let op de cent-override-spiegeling), óf als losse `out_refund` mét de bron alleen in
  `ref`/`narration` (geen `payment_state reversed` op het origineel). Keuze = beslispunt 6 (§5). `journal_id` komt uit
  `odoo_koppeling.journal_sale_id` (bestaat: VGG 48, Bonte Hoeve 72, Nieuwenhoven 80, RVN 88 — leesreplica 19-09).
- Idempotentie (§3.1: geen client-GUID's): zoek-vóór-create op `(company, journal, ref)` + lokale mapping document ↔ move-id (zelfde
  patroon als inkoop). Storno = reversal als apart document (§3.3) — de tijdlijn toont beide.
- Consument-facturen (BR-NL-10, §2d-nuance) en entity-loze kasomzet blijven RLZ-only tot beslispunt §5.2(6) uit de verkenning is
  genomen; voor Vastly is dat irrelevant (altijd een huurder).
- PDF: Odoo rendert via de HTTP-rapportroute mét sessie (§2.4 open) — voor de Vastly-stroom niet nodig (Vastly maakt de PDF), wél voor
  doorbelasting; buiten scope.

- *Toegevoegd 22-09 (BUG Peter, casus VGG / Studio Lacy Lion 2026-042; migratie 0170):* het kenmerk `administratie.btw_plichtig` geldt óók
  hier. Een NIET-btw-plichtige Vastly-/verhuurder-administratie (VGG: `tax_ids = []` in de replay, `odoo/rj220.py`) krijgt op Odoo een
  company ZONDER btw-mapping: de `VerkoopPort`-Odoo-implementatie zet dan élke regel bruto (`price_unit` incl., `tax_ids = [[6, 0, []]]`) —
  dezelfde regel als RLZ (bruto in de omzet, TaxAmount 0, "geen btw"-code) — en de harde check "Btw in niet-btw-plichtige administratie"
  blokkeert élke regel mét btw vóór de write. De ARVUM-pilot (parallel-modus) erft het kenmerk uit de RLZ-administratie: Arvum B.V. staat in
  RLZ op `EnableTaxReporting: true` (STAP-0 22-09), dus mét btw-mapping; VGG staat op false → zonder. De rekening-/btw-mapping-stap van de
  wizard (§2.1 hierboven) slaat de btw-mapping over als `btw_plichtig = false` en toont dat als chip, nooit stil.

### 2.2 Waarborg-memoriaal naar Odoo
- Bestaande `app/waarborg/boeken.py` achter een `MemoriaalPort`; Odoo-implementatie hergebruikt de memoriaal-move-schrijver van de
  VGG-replay (`entry` op MEM, debet/credit uit `DebitAmount`/`CreditAmount`, nooit `NetAmount`), balansrekening = Odoo-tegenhanger
  van 0204 (mapping per administratie, mét voorstel "naamgelijke rekening → kandidaat"). `bericht_id` (UUIDv5 van Vastly) blijft de
  idempotentiesleutel → `ref`.

### 2.3 Bank en afletteren op Odoo — het echte werk
Twee ontwerpen liggen voor (verkenning 11.5 (1)); dit ontwerp kiest **B als eindbeeld, A als brug**:
- **A (brug, testfase):** wij schrijven `account.bank.statement.line`s vanuit onze bank-sync (bron: RLZ-`PaymentTransactions` zolang de
  administratie nog RLZ-bank heeft, daarna CAMT/CSV-aanlevering aan ons), één `account.bank.statement` per aanleverdag mét
  `balance_end_real` (gratis saldo-poort `is_valid`), `ref` = deterministische mutatie-UUID, `unique_import_id` als tweede slot
  (te bewijzen in STAP-0). Onze matchmotor (GROEN/ORANJE, `bron`-label) blijft leidend; Odoo-reconciliatiemodellen alleen lezen
  (11.2, advies bevestigd: geen `auto_reconcile`-modellen).
- **B (eindbeeld):** Odoo's eigen banksynchronisatie/CAMT-import levert de regels; wij LEZEN `statement.line`s en schrijven alleen de
  tegenboeking (factuur-reconcile of kosten + analytic). Kleinste schrijfoppervlak, Odoo blijft eigenaar van het bankboek.
- **Afletteren = reconcile op de `account.move.line`-kant** (de UI-widget bestaat niet als API-model): kandidaat-routes uit §11.4 stap 4
  (i/ii/iii) in een **STAP-0 op één verhurende company** vaststellen vóór er een regel code komt. Deelbetaling en betalingsverschil
  (RLZ: deel-LinkedAmount / `IsCompletelyPaid`) worden in Odoo `partial reconcile` + write-off-regel; terugdraaien = reconcile losmaken
  (`remove_move_reconcile`, publiek? — STAP-0).
- **Afgeletterd-signaal voor `factuur_afgeletterd` (schema 2.0):** `amount_residual` op de factuur-move (= `OpenAmount`-equivalent,
  contractregel "bron altijd het open bedrag, nooit een vlag") + `payment_state`; cumulatief `betaald_bedrag` = totaal − residual;
  idempotent per (document, volgnummer) zoals nu.
  *Getoetst door CC 19-09 (`fields_get`, company 3, lees-only — geen writes):* `account.move.amount_residual` én `amount_residual_signed`
  zijn `monetary`, readonly, **stored** (dus filterbaar/sorteerbaar, geschikt als bron); `payment_state` is een stored selection
  `not_paid | in_payment | paid | partial | reversed | blocked | invoicing_legacy`. Live verdeling op company 3 (geposte verkoopfacturen,
  `read_group`): `not_paid` 104 / residual € 228.010,99 · `paid` 6 / 0,00 · `reversed` 1 / 0,00 — het signaal werkt op echte data.
  **Aanscherping uit de toets:** `in_payment` betekent in Odoo "betaling geregistreerd (account.payment), bank nog niet gematcht" en zet
  `amount_residual` al op 0 vóór er een bankregel is — voor het contract (bron = open bedrag, afgeletterd = bank bevestigt) mag
  `in_payment` NIET als `afgeletterd` gemeld worden: scenario `afgeletterd` alleen bij `payment_state ∈ {paid, reversed}` ÉN residual 0;
  `partial` → `deel_afgeletterd` (residual > 0); `in_payment` → geen event (wachten op de bankmatch) + reconciliatie-LET-OP als het
  > 14 d blijft staan; `blocked` → geen event. Op de statement-line-kant bestaat óók `amount_residual` (float, stored) naast `is_reconciled`
  (boolean) — de bedragregel van het contract geldt daar net zo (`is_reconciled` alleen als extra signaal, zoals RLZ's `IsComplete`).
  Terugweg `remove_move_reconcile`: als primitieve al aanwezig (`odoo_schrijf.py::koppel_los`), publiek/live niet bewezen — STAP-0.

### 2.4 Webhooks en contract
- `factuur_geboekt`/`factuur_afgeletterd`: payload ongewijzigd qua velden; `rlz_document_id` draagt de backend-id, nieuw veld
  `backend` ("rlz" | "odoo") + `schema_version`-bump → koppelcontract **v1.21-addendum**, akkoord beide projecten (contract v1.5-regel).
- Vastly's registersync (§8) en grootboekkoppeling (§2c) lezen de gedeelde platform-tabellen; die worden per administratie al uit de
  juiste bron gevuld (`app/odoo/sync.py`). Toets aan de Vastly-kant: verwacht Vastly ergens een 4-cijferige RLZ-code (validatie op
  lengte/formaat)? Zo ja: addendum.

### 2.4a Vastly-kant getoetst (CC 19-09, read-only in `/Users/mr.x/Vastgoed software`, pad:regel in het rapport §3)
Wat NIET breekt bij een Odoo-administratie: `code` wordt nergens op lengte/formaat gevalideerd (`code text`, `ORDER BY code`
lexicografisch — alleen gemengde lengtes binnen één administratie sorteren scheef); `cbc:AccountingCost` komt ongewijzigd uit
`grootboek_code` (`ubl.py:222/293/373/434`); `rlz_document_id`, `ledger_id`, `administratie_id` moeten een UUID zijn — een UUIDv5 uit een
Odoo-id voldoet, een rauw int niet; `rlz_boekstuknummer` wordt nergens geparsed; de entiteit ↔ administratie-koppeling loopt op de
platform-UUID `platform.administratie.id` (kolom heet misleidend `entiteit.rlz_administratie_id`), niet op de RLZ-adminId; registersync-
client valideert `rlz_admin_id` niet als UUID (`text`), dus de sentinel past daar.

Wat WÉL breekt of aandacht vraagt (→ addendum v1.21, concept in `../Platform/OPEN_ITEMS.md`):
1. **Webhook-lookup `rlz_webhook.py:456-467`:** `rlz_admin_id or administratie_id` → `uuid.UUID(...)` → `entiteit.rlz_administratie_id`.
   Een sentinel `odoo:<host>:<company>` faalt de UUID-parse en eindigt **stil** in `onbekende_administratie` + `200 genegeerd` (geen 4xx —
   onze outbox zegt "afgeleverd"). NB: dezelfde code neemt bij een RLZ-administratie eerst `rlz_admin_id` (= RLZ-GUID) en vergelijkt die met
   een kolom die de platform-UUID draagt — dat is een vraag aan Vastly óók voor vandaag (rapport §3, punt "Verificatie Vastly").
2. **`grootboekrekening.soort` = int 1..4 (Reeleezee AccountType, DB-check `0017:68`):** onze Odoo-sync vertaalt `account_type` al naar die vier
   codes (`soort_voor_account_type`) — contractueel vastleggen dat `soort` een backend-neutrale vierdeling is, niet "onvertaald RLZ".
3. **Waarborg-default `0204`** hard in Vastly (`waarborg_bericht.py:140/171/221`, `config_defaults.py:134`, `schema.sql:2701`,
   `WaarborgVerzendDialog.tsx:112`) + XML-attribuut `rlzAdminId` (gevuld met de platform-UUID): bij een Odoo-administratie is `0204` ongeldig
   → gereedheid-signaal "bestaat niet in je administratie" — per-administratie override is er al; default en label zijn RLZ-gekleurd.
4. **Klantzichtbare "RLZ"-teksten** (`verhuurder_gegevens.py:41/171`, `gereedheid.py:641`, app `mijn-gegevens/index.tsx:107`) en `backend`
   hardcoded `'rlz'` (`grootboek.py:113`, `repos.py:5995`, `api.ts:210`; onbekende backend rendert als "ODOO" via `toUpperCase()`) —
   beslispunt 5 is daarmee geen "wil je", maar "de label-map bestaat al en wordt op vier plekken omzeild".
5. `bron ∈ {module_storno, rlz_ui_detectie}` op `factuur_gestorneerd` en de schema-versies per event (1.0/1.1/1.2, 2.0) zijn hard; een
   Odoo-storno (reversal) meldt zich als `module_storno`, een Odoo-UI-reversal als `rlz_ui_detectie` — naam RLZ-gekleurd, semantiek klopt.

### 2.5 Wat NIET verandert
Intake, splitsing, extractie, harde checks, accordering, autoboek-opt-ins, reconciliatie-blokken — alles boven de port. De regel
"nooit `RlzClient` in nieuwe module-code" (seam-eis) maakt dit mogelijk. *Gecorrigeerd door CC 19-09:* de bankmodule is NIET de enige plek
zonder seam — de port bestaat alleen voor inkoop (`app/backends/port.py`: één `InkoopPort`; `grep VerkoopPort|MemoriaalPort|BankPort` = 0).
Verkoop (`verkoop/boeken.py:209`), waarborg (`waarborg/boeken.py:80`), omzet (`omzet/boeken.py:432`), doorbelasting
(`doorbelasting/boeken.py:502…1364`) én bank (10 modules) roepen alle rechtstreeks `_rlz_client_voor`/`RlzClient` aan. Guardrail 0016
("`if backend == 'odoo'` elders = ontbrekende port-operatie") wordt daarnaast op ~15 plekken omzeild via `is_odoo_sentinel`/
`actieve_administraties_per_backend` (overslaan, geen boekpad). Het werk zit dus in drie ports (Verkoop, Memoriaal, Bank) plus het
achter-de-port-zetten van vier bestaande motoren — niet alleen in de bank.

## 3. Pilot: ARVUM B.V. of Rubicon Investments B.V.
- **Rubicon** is de geregistreerde eerste Vastly-scope (contract v1.8, entiteitenregister 0009-b), waarborg-GB 0204 geverifieerd,
  doorbelasting-spiegelkant via Rubicon getest, eerste productieboekingen van de bankmodule (08-08) waren Rubicon. Alles wat er aan
  Vastly-koppeling bestaat is op Rubicon bewezen → als pilot heb je de rijkste vergelijking RLZ ↔ Odoo. Nadeel: het is de
  best-lopende Vastly-administratie; een overstap raakt lopende productie.
- **ARVUM B.V.**: accordering aan (3 lagen, 4 accordeurs); Vastly-status en bankvolume ken ik niet uit de bronnen — vóór de keuze
  meten (lees-only): aantal huurfacturen/maand, bankmutaties/maand, open posten, waarborgen, of ARVUM al in het entiteitenregister
  van Vastly staat.
  *Gecorrigeerd door CC 19-09 (leesreplica + RLZ GET, rapport `2026-09-19-ontwerp-vastly-odoo-toets.md` §2):* ARVUM heeft 3 lagen mét
  **3** accordeurs (dezelfde drie gebruikers als bij Rubicon — één kantoorbrede accordeursketen, geen afdelings-/leveranciersroutes);
  `is_vastgoed` staat op ARVUM **al AAN** (met `verkoop_autoboeken` als spiegel), terwijl `Platform/registers/entiteiten.md` nog
  "geoormerkt kandidaat, is_vastgoed pas bij het Vastly-moment" zegt — registerdrift, gemeld in het rapport; `afgeletterd_event`
  staat alleen bij Rubicon aan. Bankvolume ARVUM ≈ 10–20 mutaties/maand op één betaalrekening (+ spaarrekening), Rubicon ≈ 35–45 op
  de betaalrekening + vijf systeem-/RC-rekeningen (RC Inpensas Beheer −€ 49.500, Verrekeningen, Overloop).
- **Meetuitkomst die het advies stuurt (CC 19-09):** **geen van beide administraties heeft ooit een VASTLY-VERKOOP-document of
  VASTLY-WAARBORG-bericht via de module ontvangen** (`document.soort in (verkoopfactuur, waarborg)` = 0, `verkoop_boeking` = 0,
  `waarborg_bericht` = 0; RLZ `SalesInvoices` sinds 01-03-2026: Rubicon 0, ARVUM 2 — geen Vastly-nummers). De Vastly-verkoop- en
  waarborgstroom draait in productie voor géén enkele administratie; alleen de kostenstroom loopt (Rubicon: 2 × `factuur_geboekt`
  afgeleverd 11-09). De "rijkste vergelijking RLZ ↔ Odoo" die het ontwerp aan Rubicon toeschrijft bestaat voor verkoop/waarborg dus niet
  — voor beide is de pilot op die twee stromen greenfield. Wat Rubicon wél extra draagt: doorbelasting-DOEL (spiegel-inkoop uit Kempen
  Facilities), 30 memorialen in 2026, 19 debiteuren, 11 projecten, 52 open bankmutaties, live Vastly-push.
- *Gecorrigeerd door CC 19-09 (agent pilotmeting, leesreplica + RLZ GET onder nameting@):* "of ARVUM al in het entiteitenregister van Vastly
  staat" is aan de objectkant al beantwoord: **Vastly heeft beide administraties al via route A (§5) bediend** — `platform.audit_event`
  tabel `projectaanvraag`: ARVUM 4 × `projectaanvraag_verwerkt` + 4 × `project_aangemaakt_in_rlz` (01/02-09-2026; de vier projecten in
  `project_cache` zijn adressen: Cavalier 4 Emmeloord, Hanzeweg 17 Barneveld, Moezelweg 136A/136B Europoort; RLZ `Projects` `@odata.count`
  4, alle `IsActive`, `BeginDate` 01-09-2026), Rubicon 11 × beide acties (01/02-09; RLZ `Projects` 11, `Customers` 19; ARVUM `Customers` 5).
  De waarborg-balansrekening `0204 Waarborgsommen` (soort 3) staat in het §2c-register van BEIDE administraties (leesreplica 19-09), dus
  de §6.4-inventarisatie voor ARVUM is impliciet gedaan. Wat er bij beide nog NIET is: één VASTLY-VERKOOP-UBL of VASTLY-WAARBORG-bericht in
  de intake (0), en een `factuur_afgeletterd`-rij (0 — ARVUM heeft de tier-vlag uit, Rubicon aan maar geen standwijziging gemeld). RLZ
  `Receipts` sinds 01-03-2026 (alle documenttypen, mét bank-directe boekingen type 19): ARVUM 89, Rubicon 235 — de RLZ-kant leeft dus
  wél, alleen niet via Vastly-verkoop. Onboarding-voorwaarde hieronder is daarmee kleiner dan het ontwerp dacht: objecten en register
  staan; alleen de boekhoudmail-stroom (huurfacturen 380/381 + waarborg) moet voor de pilot-administratie aangezet worden aan Vastly-kant.
- **Advies (bijgesteld door CC 19-09):** kies op basis van die meting de kleinste verhuurder mét alle vier de stromen (verkoop, waarborg,
  bank, inkoop). Dat is **ARVUM B.V.** — kleinste bank (één betaalrekening), geen doorbelastingsspiegel, geen live Vastly-push die je
  raakt, 5 debiteuren/4 projecten, `is_vastgoed` staat al — **onder de voorwaarde dat Vastly ARVUM eerst onboardt (entiteitenregister
  + huurfacturen via de boekhoudmail)**; zonder die stap heeft géén pilot een verkoopstroom om te bewijzen. Rubicon = tweede, ná de
  eerste cent-exacte maand, omdat daar Kempen-doorbelasting + de live push meelopen (fase 2b). Kleine volumes = korte bewijscyclus, en de
  aanlevering kan tijdelijk dubbel (RLZ blijft schaduw tot de eerste maand cent-exact sluit — zelfde regel als Bloxs-schaduw in Vastly).
- Kanteldatum-patroon = de Universal-overstapwizard (ingang B: mapping grootboek/btw/projecten, historie-dedup, boekingsgeheugen-
  vertaling `app/odoo/mapping.py`). Nieuw t.o.v. Universal: debiteuren/huurders-mapping (§8) en het bankboek.

## 4. Fasering (elke fase eindigt met "werkt in productie: ja/nee")
0. *(toegevoegd door CC 19-09)* **Voorwaarde vóór alles:** de pilot-administratie heeft een Odoo-company (klikpunt Peter in Odoo —
   vandaag bestaat er voor ARVUM noch Rubicon een company; `odoo_koppeling` kent alleen company 3/6/9/10/11) én Vastly levert er
   huurfacturen/waarborgen aan (meting 19-09: nu nul). Zonder beide is fase 2 niet meetbaar.
1. **STAP-0 bank op Odoo (lees-only + TEST-writes op de pilot-company):** statement.line create + `unique_import_id`-gedrag,
   statement met `balance_end_real`, reconcile-route i/ii/iii, partial reconcile + write-off, losmaken, `amount_residual`-semantiek.
   Uitkomst: één gekozen route, vastgelegd in odoo-verkenning §14. *CC 19-09:* de primitieven staan al in `app/migratie/odoo_schrijf.py`
   (kill-switch) — STAP-0 = die bewijzen, niet herschrijven; daarna verhuizen ze naar `app/odoo/bank.py` achter een `BankPort`.
2. **VerkoopPort + Odoo-verkoop** (VASTLY-VERKOOP 380/381) mét webhook-addendum v1.21 én huurder-`res.partner` (customer_rank, zoek-vóór-
   create); nameting op de pilot: 3 huurfacturen + 1 creditnota cent-exact in Odoo, `factuur_geboekt` ontvangen door Vastly. Creditnota-vorm
   volgens beslispunt 6.
   2b. *(toegevoegd door CC 19-09)* **Doorbelastings-spiegel + omzet-Receipts achter de port** — nodig zodra een doorbelasting-DOEL
   (Rubicon) of een omzet-administratie overstapt; niet voor ARVUM.
3. **MemoriaalPort + waarborg** naar Odoo.
   3b. *(toegevoegd door CC 19-09)* **Route A projectaanmaak (§5) voor Odoo**: `rlz_project_id` = analytic-account-UUIDv5, aanmaak via
   `mapping.py::aanmaken_analytic_accounts`-patroon; contractueel valt dit onder hetzelfde v1.21-addendum (id-semantiek).
4. **Bank brug A** (wij schrijven statement lines) + afletteren via de gekozen route + `factuur_afgeletterd`; matchmotor ongewijzigd,
   Odoo-modellen alleen lezen; saldo-poort als harde check.
5. **Overstap pilot** via de wizard; RLZ schaduw één maand; reconciliatie-blok `odoo_vs_rlz` tijdelijk.
6. **Bank eindbeeld B** zodra Odoo-synchronisatie voor de pilot staat (klikpunt Peter in Odoo): schrijver uit, lezer aan.

## 5. Beslispunten voor Peter
1. Pilot: Rubicon (rijkste bewijs, meeste risico) of ARVUM (eerst meten) — of een derde kleine verhuurder.
2. Bank: akkoord op "B eindbeeld, A brug"? Of direct B (dan is de brug-code verspild werk, maar de overstap wacht op Odoo's banksync).
3. Contract-addendum v1.21 (`backend`-veld in de webhooks) mét Vastly-kant-toets op 6-cijferige grootboekcodes — mag ik dat als
   OPEN_ITEM naar het Platform zetten?
4. Volgorde t.o.v. VGG: VGG-replay (SCHRIJF c → volledige run) blijft eerst; fase 1 (STAP-0 bank) kan parallel omdat het lees-only +
   TEST-writes op de pilot-company is. Akkoord?
5. Vastly-kant: wil je dat Vastly straks per klant ziet welke boekhouding erachter zit (alleen informatief, bv. voor supportvragen)?
6. *(toegevoegd door CC 19-09)* Creditnota 381 op Odoo: via de `account.move.reversal`-wizard op het origineel (kruisverwijzing +
   `payment_state reversed`, maar cent-override-spiegeling en `invoice_date` = wizarddatum) óf als losse `out_refund` mét de bron in
   `ref` (eenvoudiger, geen Odoo-koppeling tussen de twee)? Advies: wizard, omdat Vastly's `BillingReference` precies die koppeling
   uitdrukt en Odoo's factuur-matching er op leunt.

*Aanvulling CC 19-09 op beslispunt 1:* de meting zegt ARVUM (§3); beslispunt 1 blijft open omdat de voorwaarde (Vastly onboardt ARVUM,
Odoo-company voor ARVUM) een klikpunt van Peter/Vastly is, geen module-keuze. *Op beslispunt 3:* het concept-addendum staat als
voorstel in `../Platform/OPEN_ITEMS.md` (item "RLZ → Vastly: concept-addendum v1.21 — backend-neutrale id's", 19-09); niets in het
contract gewijzigd.

## 6. Risico's, eerlijk
- Reconcile via API in Odoo 19 is nog niet bewezen (§11.4 stap 4 open). Als geen route publiek blijkt, valt afletteren terug op
  Odoo's UI (mens) en kan `factuur_afgeletterd` alleen uit `amount_residual` gelezen worden — dat werkt wel, maar dan doet Odoo het
  afletteren en niet onze motor. Dat is te leven mee (Odoo = leidend), maar het breekt de "minimale mens"-lijn voor die administratie.
- Twee bronnen van waarheid tijdens de schaduwmaand: alleen aanvaardbaar met een dagelijkse cent-exacte vergelijking, nooit langer.
- Odoo-nummering is leidend (§3.4); Vastly's factuurnummer staat in `ref`, niet in `name` — Vastly's eigen nummer blijft de referentie
  in de webhook, dus geen wijziging aan de Vastly-kant.
