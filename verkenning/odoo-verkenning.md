# Odoo STAP-0-verkenning — universal-steigers.odoo.com (02-09-2026)

**Status: UITGEVOERD — feitenbasis voor het adapter-bouwplan (besluit 0016). Adapter fase 1 GEBOUWD 03-09 (blokken 0–E) en de keten LIVE BEWEZEN 04-09 op company 1 — zie §7. Afrondingsrun 04-09: Universal Verkoop (company 3) LIVE als alleen-lezen leesbron in de cloud, overstap-generale VOORBEREID (script) — zie §8.**
Opdracht Peter 02-09: alleen verkennen naar het RLZ-patroon (`api-verkenning.md`); schrijven beperkt tot exact
twee bewijs-cycli mét `TEST-`-prefix, tegengeboekt via Odoo's eigen reversal, niets verwijderd, geen Odoo-
instellingen gewijzigd. Scripts: `verkenning/odoo_stap0_client.py` (JSON-2-client, audit-log, kill-switch
`verkenning/POC_STOP`), `odoo_stap0_inventaris.py` (deel 1, read-only), `odoo_stap0_bewijs.py` (deel 4:
`a` / `a2` / `b` / `opruimen` / `status`, elk idempotent). Ruwe uitvoer + audit-log (23 schrijfacties, elk
mét reden) in `verkenning/output/odoo_stap0_*.{json,log,jsonl}` (gitignored). Secrets zijn nergens gelogd.

Leeswijzer: §0 samenvatting · §1 verbinding & inventaris · §2 veld-voor-veld-mapping · §3 semantiekverschillen ·
§4 bewijs-cycli A/B · §5 conclusie, beslispunten, klikpunten · §6 product-semantiek · §7 keten-cyclus · §8 afrondingsrun 04-09 (leesbron cloud + overstap-generale).

---

## §0 Samenvatting (de tien feiten die het bouwplan sturen)

1. **Odoo 19.0+e (Enterprise, Odoo Online), API = JSON-2** (`POST /json/2/<model>/<method>`, bearer-API-key,
   uitsluitend benoemde argumenten). XML-RPC/JSON-RPC bestaan nog maar zijn "scheduled for removal in Odoo 22".
   Externe API alleen op het Custom-plan — werkt hier, dus het plan is Custom.
2. **De database is MULTI-COMPANY: 10 bedrijven in één database**, waaronder vier Universal-BV's én zes
   niet-Universal-entiteiten (Roompot Nieuwkoop, Roompot Nature Resort, Bonte Hoeve, Camping Nieuwenhoven,
   Caravanpark De Visotter, Vastgoedgroep Nederland). **Universal Steigerbouw B.V. = company 1 en was leeg
   (0 boekingen)**; **Universal Verkoop B.V. (company 3) draait al live** (2.989 geposte boekingen, 20
   verkoopfacturen, 8 inkoopconcepten uit OCR). De API-gebruiker is Accounting/Administrator + `base.group_system`
   op álle 10 bedrijven. Elke adapter-call moet daarom expliciet op `company_id` scopen (context
   `allowed_company_ids` + `company_id` in de vals) — de administratie-als-backend-grens uit besluit 0016 wordt
   hier "administratie = Odoo-company binnen één gedeelde database".
3. **`ODOO_DB` in `verkenning/.env` is NIET de databasenaam** (server: `KeyError`); Odoo Online is single-db per
   host — de `X-Odoo-Database`-header weglaten (mét verkeerde header: 404 "No database is selected"). Dát was de
   oorzaak van de 404's van het oude scriptje van 15-07.
4. **Boekdatum-les herhaalt zich: zonder expliciete `date` zet Odoo de boekdatum op het MAANDEINDE van de
   factuurmaand** (factuurdatum 15-08 → `date` 31-08, want de factuur werd in september ingevoerd) — niet op de
   systeemdatum zoals RLZ, en óók niet op de factuurdatum. `date` is los schrijfbaar en blijft staan door het
   posten heen. Álle motoren moeten `date` = factuurdatum expliciet meegeven (besluit Peter 27-08 ongewijzigd).
5. **Cent-exactheid is haalbaar:** regel = `quantity 1 × price_unit = netto` (exact), btw berekent Odoo zelf
   (company 1: `round_globally`); een afwijkende factuur-btw wordt gezet door `write balance` op de tax-regel van
   het concept — 21,00 → 21,01 bleef staan door het posten heen, `amount_tax`/`amount_total`/crediteurenregel
   volgden mee. **Maar: de reversal-wizard herberekent de btw uit de regels en neemt zo'n override NIET mee**
   (creditnota 131,90 tegen factuur 131,91 → origineel bleef `partial` met € 0,01 open). De adapter moet de
   creditnota-tax-regel vóór het posten spiegelen (bewezen in A2).
6. **Project per regel werkt via `analytic_distribution = {"<analytic_account_id>": 100}`**; bij posten ontstaan
   `account.analytic.line`-rijen (bedrag −netto voor kosten, `general_account_id`, `date`, `ref`) — dé leesroute
   voor de projectcijfers (filterbaar, anders dan het JSON-veld op de regel). Reversal geeft +netto-regels.
7. **Terugdraaien = apart document** (`account.move.reversal` → `in_refund` "RBILL/2026/09/0001", ref
   "Omgekeerde boeking van: BILL/2026/08/0001, <reden>"), origineel blijft `posted` en krijgt `payment_state
   reversed`. Voor een factuur komt de creditnota als CONCEPT terug (zelf posten; posten lettert automatisch af),
   voor een memoriaal (`entry`) post de wizard direct. **Odoo kent daarnaast wél een actie-19-analoog:
   `button_draft` zet een gepost document terug naar concept** (bewezen; nummer blijft staan) — alleen zonder
   hash-lock/lock-date, en het is een governance-keuze, geen technische onmogelijkheid.
8. **Geen client-GUID's, geen ingebouwde idempotentie**: `create` geeft een server-int-id; een tweede create met
   dezelfde `ref`+partner maakt gewoon een tweede concept, mét signaal `duplicated_ref_ids` op beide (verdwijnt
   zodra het duplicaat geannuleerd is). Idempotentie = zoek-vóór-create op (company, partner, ref, move_type,
   state ≠ cancel) + eigen id-mapping; de domeincolommen `rlz_document_id` zijn `uuid`, Odoo-id's zijn int.
9. **Bijlage = `ir.attachment` (res_model/res_id/datas) + `register_as_main_attachment(force=True)`** — plain
   create maakt 'm niet automatisch hoofdbijlage. **Bijlagen pas NÁ het posten**: company 1 staat op
   `extract_in_invoice_digitalization_mode = auto_send` (OCR op inkoopconcepten met hoofdbijlage — zou onze
   regels overschrijven); op een gepost document blijft `extract_state = no_extract_requested` (bewezen).
10. **Saldo-0 wordt bij `create` afgedwongen** (HTTP 422 `UserError` "De boeking is niet in balans.", niets
    bewaard) — een create mét geneste regels is één transactie (atomair); bijlage en posten zijn losse calls.
    Nummering pas bij posten (`name` = False in concept; `BILL/2026/08/0001`, maandreset; creditnota's eigen reeks
    `RBILL/`). Lock dates staan overal op False; API-keys leven max. 3 maanden (Odoo-eis).

---

## §1 Verbinding & inventaris (read-only, `odoo_stap0_inventaris.py`)

### 1.1 Verbinding, versie, API-vorm

| Feit | Waarneming |
|---|---|
| Host / versie | `universal-steigers.odoo.com`, `server_version 19.0+e` (Enterprise, Odoo Online) — via `/web/webclient/version_info` én `xmlrpc/2/common version()` |
| Werkende API | **JSON-2**: `POST /json/2/<model>/<method>`, headers `Authorization: bearer <key>`, `Content-Type: application/json`; body = benoemde argumenten (`ids`, `domain`, `fields`, `vals_list`, `context`, …). `GET` op die route = 404 "Did you mean POST". |
| Database | `ODOO_DB`-waarde uit `.env` ≠ echte databasenaam (XML-RPC `authenticate` → `KeyError: '<waarde>'`). Zonder `X-Odoo-Database` werkt JSON-2 (single-db-host). |
| Legacy-RPC | XML-RPC/JSON-RPC nog aanwezig; docs 19.0: "scheduled for removal in Odoo 22 (fall 2028)". Adapter begint op JSON-2. |
| Plan | Docs: externe API alleen op *Custom*-plan (niet One App Free/Standard) — werkt, dus Custom. |
| Context-doorgifte | top-level `context` in de body werkt (`allowed_company_ids: [1]` → 8 dagboeken i.p.v. 80). |
| API-keys van de gebruiker (`res.users.apikeys`) | twee: "Nijenhuis Module" (aangemaakt 24-08, **verloopt 2026-11-22**) en "N-Module" (aangemaakt 02-09, `expiration_date` False). Odoo-docs: "not possible to create keys that last for more than three months" → **rotatie-klikpunt elk kwartaal**, zichtbaar beheerd (credential-store, besluit 0012). |

### 1.2 API-gebruiker en rechten

- `uid 6`, lid van 20 Administrator-groepen (Accounting/Administrator, Project/Administrator, Purchase, Sales, Inventory, Documents/System Administrator, …), `base.group_system` = True, `analytic.group_analytic_accounting` = True, `Multi Companies`.
- `company_id` = 1 (Universal Steigerbouw), **`company_ids` = alle 10 bedrijven**.
- `has_access` read/create/write/unlink = ✓ op `account.move`, `account.move.line`, `res.partner`, `account.account`, `account.tax`, `account.journal`, `account.analytic.*`, `ir.attachment`, `ir.model.data`, `res.company`, `account.payment`, `account.bank.statement.line` (alleen `unlink` op de wizard `account.move.reversal` ✗ — transient).
- **Beoordeling:** dit is een volledige beheerder over tien juridische entiteiten van meerdere eigenaren. Voor de koppeling is een aparte technische gebruiker per administratie(-groep) met alleen Accounting-rechten en `company_ids` beperkt tot de eigen BV('s) de hygiënische keuze — beslispunt §5.2 (1).

### 1.3 Bedrijven in de database

| id | Bedrijf | KvK | Boekingen (`account.move`) | Analytic-plannen in gebruik |
|---|---|---|---|---|
| **1** | **Universal Steigerbouw B.V.** | 94539820 | **0 vóór de verkenning** (5 ná: de twee cycli) | Project (Internal, Field Service) |
| 2 | Universal Nederland B.V. | 72404272 | 0 | Project |
| 3 | Universal Verkoop B.V. | 76726932 | **2.989 entry posted, 20 out_invoice posted, 7 out_invoice cancel, 8 in_invoice draft (`extract_state waiting_validation` = OCR-concepten mét PDF), 1 in_receipt draft, 1 out_refund cancel** | Project |
| 4 | Universal Materiaal B.V. | 85018902 | 0 | Project |
| 5 | Caravanpark "De Visotter" B.V. | 28094368 | 1 in_invoice cancel | Project, Projectlocatie (150), Taakfases, Taken, Kostensoort |
| 6 | Vastgoedgroep Nederland B.V. | 97433861 | 0 | Project |
| 7 | Roompot Nature Resort Nieuwkoop OG B.V. | 54054990 | 0 | Project, Projectlocatie (80), … |
| 8 | Roompot Nieuwkoop B.V. | 81051158 | 0 | idem |
| 9 | Bonte Hoeve B.V. | 94415900 | 0 | idem |
| 10 | Camping "Nieuwenhoven" B.V. | 21011383 | 0 | idem |

Universal Verkoop factureert al in Odoo (verkoopfacturen `F/2026/00027`, betaaltermijn 30 Days, Peppol-module actief) en ontvangt inkoopfacturen via OCR — dat raakt onze voorraad-uitstroom-leesroute (`app/voorraad/rlz_uitstroom.py` leest nu RLZ; Universal Verkoop's nieuwe verkoop staat in Odoo) — zie §5.2 (9).

### 1.4 Instellingen company 1 (relevant voor de adapter)

| Instelling | Waarde | Gevolg |
|---|---|---|
| Valuta / land / template | EUR, Netherlands, `chart_template nl` | NL-rekeningschema (Engelstalige namen) |
| `tax_calculation_rounding_method` | **`round_globally`** | btw per tarief over de som van de bases, niet per regel — cent-verschil t.o.v. per-regel-rekenen mogelijk; override-pad §4 A5 dekt het |
| `anglo_saxon_accounting` | True | voorraad-/kostprijsmechaniek van Odoo (stock_account) actief — ons kostprijsmemoriaal blijft een gewone `entry` |
| default btw inkoop / verkoop | 21% (id 14) / 21% ST (id 7) | wordt op regels zonder `tax_ids` NIET automatisch gezet via API-create zonder product (regel B: `tax=[]` bleef leeg) |
| `extract_in_invoice_digitalization_mode` | **`auto_send`** | OCR op inkoopconcepten met hoofdbijlage → bijlage pas ná posten (§4 A8) |
| `extract_out_invoice_digitalization_mode` | manual_send | — |
| `autopost_bills` (company) + `res.partner.autopost_bills` | True / default `'ask'` per partner | Odoo stelt na herhaalde handmatige validatie auto-posten voor; irrelevant voor API-posten, wel relevant als Odoo's mail-alias ook facturen ontvangt |
| `vat_check_vies` | False | fictief elfproef-geldig btw-nummer werd geaccepteerd (base_vat = formaatcheck) |
| Lock dates (`fiscalyear/tax/sale/purchase/hard_lock_date`) | **alle False**, geen `account.lock_exception` | gedrag rond lock dates NIET live testbaar (geen instelling gewijzigd) — docs §3.5 |
| `restrict_mode_hash_table` (per dagboek) | False op alle 8 dagboeken | geen onveranderlijkheidshash → `button_draft` mogelijk; `inalterable_hash` = False op alle documenten |
| Boekjaar | 31-12 | — |

### 1.5 Rekeningschema (`account.account`)

Rekeningen zijn in Odoo 17+ bedrijfsgedeeld (`company_ids`), 6-cijferig NL-template. Per type (company 1): asset_current 20 · asset_fixed 48 · asset_prepayments 2 · asset_receivable 2 · equity 6 · equity_unaffected 2 · **expense 128** · expense_depreciation 5 · **expense_direct_cost 29** · income 33 · income_other 7 · liability_current 75 · liability_non_current 16 · liability_payable 2 (+ cash/bank/off-balance; volledige lijst in `odoo_stap0_inventaris.json`). Kernrekeningen: `130000 Creditors` (id 131, payable, reconcile), `110000 Debtors` (id 121), `152000 Pre-tax high` / `152100 Pre-tax low` (voorbelasting 21/9 — automatisch via het tarief), `150000 Deferred VAT high rate` (af te dragen), `300100 Raw materials 1` (id 208), `424000 Tools` (id 258), `420100 Machine rental` (id 252), `700100 Cost price NL trade goods 1` (id 336, default van dagboek BILL), `800100 Turnover NL trade goods 1` (id 365, default van INV). Veldnamen: `code`, `name`, `account_type`, `reconcile`, `deprecated`, `tax_ids`, `tag_ids`, `company_ids`, `active`, `internal_group`, `non_trade`. → sync-doel voor onze `ledger_cache` (RLZ `Ledgers`); `deprecated`/`active` = "verdwenen"-signaal.

### 1.6 Btw-codes (`account.tax`, company 1: 31 codes = 16 inkoop, 15 verkoop) mét aangifte-mapping

De aangifte-rubriek zit niet op het tarief maar op de **repartition-lines → `account.account.tag`** (`invoice_repartition_line_ids` → `tag_ids`; tags `applicability = taxes`, land NL, namen = rubrieken). Relevante codes:

| id | type | naam | % | label op factuur | btw-rekening | rubriek-tags (base / tax) |
|---|---|---|---|---|---|---|
| 14 | inkoop | 21% | 21 | 21% VAT | 152000 Pre-tax high | tax: **5b** |
| 13 | inkoop | 9% | 9 | 9% VAT | 152100 Pre-tax low | tax: 5b |
| 17 / 16 | inkoop | 21% S / 9% S (diensten) | 21 / 9 | | 158000 / 158100 …services | tax: 5b |
| 15 / 18 | inkoop | 21% O / 21% S O (variabel/gedeeltelijk aftrekbaar) | 21 | variable VAT | 152000 / 158000 | tax: 5b |
| **20** | inkoop | **21% R (verlegd)** | 21 | 21% VAT reverse charge | 150400 Chargeable reverse charge VAT + 158000 | base: **2a**, tax: 2a + 5b |
| 22 / 21 | inkoop | 21% EX EU / 9% EX EU (verwerving) | 21 / 9 | 21% EU / 0% EU | 151600/151700 + 152400/152500 | base 4b, tax 4b + 5b |
| 30 / 29 / 31 / 35 / 34 | inkoop | … EX O EU (import buiten EU) | | 0% Non-EU | 1513xx/1514xx + 1528xx/… | base 4a, tax 4a + 5b |
| 7 | verkoop | 21% ST | 21 | 21% VAT | 150000 Deferred VAT high rate | base 1a, tax 1a |
| 6 | verkoop | 9% ST | 9 | 9% VAT | 150100 | base 1b, tax 1b |
| 5 | verkoop | 0% | 0 | 0% VAT | — | base 1e |
| 19 | verkoop | 0% R (verlegd) | 0 | 0% VAT reverse charge | — | base 1e |
| 32 / 33 | verkoop | 0% EX / EX I (export) | 0 | | — | base 3a |
| 23 / 24 / 25 | verkoop | 0% EX EU G/T/S (ICL goederen/…/diensten) | 0 | 0% EU | — | base 3bg / 3bt / 3bs |
| 26 | verkoop | 0% EU I | 0 | | — | base 3c |

Waarnemingen: (a) er is **geen inkoop-0%-code** — "btw-vrijgesteld/nul" op een inkoopregel = géén `tax_ids` (Odoo boekt dan geen btw en geen rubriek); RLZ's "Nul tarief" heeft dus een ander anker; (b) **"btw verlegd" (bouwketen-norm) = code 20 `21% R`** — boekt 21 % af te dragen (2a) én terug als voorbelasting (5b), netto 0, exact de Nederlandse aangiftevorm; (c) codes zijn per company (id's verschillen per bedrijf: 21% = 14 in company 1, 200 in company 7) → sync per administratie, nooit hardcoden (zelfde regel als RLZ TaxRates); (d) velden `amount`, `amount_type` (`percent`), `type_tax_use`, `invoice_label`, `tax_group_id`, `price_include_override`, `active`. Onze `app/sync/btw.py`-normalisatie (fractie↔percentage) is hier niet nodig: `amount` = 21.0.

### 1.7 Dagboeken (`account.journal`, company 1)

| id | code | type | naam | default-rekening | eigen creditreeks |
|---|---|---|---|---|---|
| 8 | INV | sale | Sales | 800100 | ja |
| **9** | **BILL** | **purchase** | Purchases | 700100 | **ja → `RBILL/`** |
| 13 | BNK1 | bank | Bank | 103001 | — |
| **10** | **MISC** | general | Miscellaneous Operations | — | — |
| 36 | STJ | general | Voorraadwaardering | — | — |
| 11 / 12 / 14 | EXCH / CABA / TAX | general | koers / cash-basis / btw-aangifte | — | — |

Nummering: **geen `ir.sequence` voor boekingen** (94 sequences zijn voor stock/expenses/batches); de naam wordt bij posten afgeleid van het dagboek + de laatste naam in het dagboek: `BILL/2026/08/0001` (maandreset, `sequence_prefix "BILL/2026/08/"`, `sequence_number 1`), creditnota `RBILL/2026/09/0001`, memoriaal `MISC/2026/08/0001`. Company 3 gebruikt jaarreset (`F/2026/00027`) — het resetpatroon volgt de eerste boeking in het dagboek. Concept = `name False` (UI toont "Draft"). `payment_reference` op verkoopfacturen wordt automatisch = `name`.

### 1.8 Partners (`res.partner`)

135 partners; 127 bedrijfsgedeeld (`company_id False`), de rest = de bedrijfspartners zelf. Velden: `vat` (btw-nummer, formaatcheck base_vat), `company_registry` (KvK — er is géén `l10n_nl_kvk`), `supplier_rank`/`customer_rank`, `property_supplier_payment_term_id`, `property_account_payable_id` (auto 130000), `bank_ids` (IBAN's), `peppol_eas` (auto **`0106`** = KvK-schema) + `peppol_endpoint`, `autopost_bills`, `invoice_sending_method`, `invoice_edi_format`, `ref`, `is_company`, `country_id`. → ons `crediteur_kenmerk` (btw > KvK) heeft in Odoo een natuurlijk thuis dat RLZ mist (btw-nummer is in RLZ niet leesbaar via de API — casus Labo Derva).

### 1.9 Analytic (projecten)

- **Plannen** (`account.analytic.plan`, geen company-veld in 19): Project (id 1, `default_applicability optional`), Projectlocatie (8), Taakfases (9), Taken (10), Kostensoort (11) — de laatste vier worden door de recreatie-bedrijven gebruikt (150 locaties bij De Visotter, 80 bij Roompot).
- **587 analytic accounts** totaal; company 1: `Internal` (1), `Field Service` (5) + een gedeelde `Test Thomas` (758, company False). Module `project` is geïnstalleerd: `project.project` per bedrijf (Intern/Buitendienst/Field Service/Odoo/Visotter 001–006), elk met een analytic account.
- **Regelvelden** op `account.move.line`: `analytic_distribution` (json `{"<analytic_account_id>": <percentage>}`), `distribution_analytic_account_ids` (afgeleid), `analytic_line_ids`, `analytic_precision`, `has_invalid_analytics`. Meerdere plannen tegelijk = meerdere sleutels (Odoo verdeelt per plan; 100 % per plan).
- Ons RLZ-`Project` per regel → analytic account in plan **Project** (§2). Projectaanmaak (route A, projectmotor) → `account.analytic.account.create({name, code, plan_id 1, company_id})` — bewezen in A2 (`[TEST-STAP0] TEST-ODOO-STAP0 Project`, code als prefix in de weergavenaam).

### 1.10 Overige stamgegevens

- Betaaltermijnen (`account.payment.term`): Immediate, 15/21/30/45/60 dagen, End of Following Month, "30 dagen - 3% binnen 7 dagen", … — wij zetten `invoice_date_due` expliciet mét `invoice_payment_term_id False` (bewezen; §4 A).
- Fiscale posities per bedrijf (NL Domestic, EU intra B2B, VAT reverse charge, …) — niet nodig zolang wij het tarief per regel zelf kiezen.
- Modules relevant (330 geïnstalleerd): `account`, `account_accountant`, `account_reports`, `analytic`, `project`, `project_account`, `hr_timesheet`, `l10n_nl`, `l10n_nl_reports`, `account_invoice_extract(+_purchase)`, `account_peppol`, `account_edi_ubl_cii`, `base_vat`, `documents_account`, `account_asset`, `account_budget`, `account_online_synchronization`, `account_bank_statement_import_camt/csv/ofx`, `account_iso20022`, `purchase`, `sale`, `stock`, `stock_account`, `account_inter_company_rules`.

### 1.11 Foutsemantiek en rate-observatie

| Situatie | HTTP | body |
|---|---|---|
| succes | 200 | JSON-return (create → `[id]`, write → `true`, action_post → `false`, reverse_moves → act_window-dict) |
| `UserError` (onbalans) | **422** | `{"name":"odoo.exceptions.UserError","message":"De boeking is niet in balans.", "arguments":[…], "context":{}, "debug":"Traceback…"}` |
| private methode (`_compute_…`) | 403 | `odoo.exceptions.AccessError` "Private methods … cannot be called remotely" |
| onbekend model / methode | 404 | `werkzeug.exceptions.NotFound` |
| onbekend veld | 500 | `builtins.ValueError` "Invalid field '…'" |
| ontbrekend argument (`has_group` zonder `group_ext_id`) | 422 | `werkzeug.exceptions.UnprocessableEntity` |
| `read` op niet-bestaand id | 200 | **lege lijst — géén MissingError** (adapter toetst op lengte) |
| verkeerde `X-Odoo-Database` | 404 | HTML "No database is selected" |
| zonder/ongeldige key | 401 | (docs) |

Rate: 40 opeenvolgende `search_count` = 7,4 s (120 / 200 / 226 ms min/mediaan/max), geen 429. Odoo-docs noemen geen rate limit; Odoo Online kent wel worker-tijdslimieten. Adapter: throttling + retry/backoff zoals de RLZ-client, en per document weinig calls (create-met-regels = 1 call).

---

## §2 Veld-voor-veld-mappingtabel (RLZ-motor → Odoo → bewijsstatus)

Legenda bewijs: **✓ LIVE** = geschreven én terug-gelezen in cyclus A/B · **✓ LIVE (lezen)** = alleen gelezen · **≈** = mapping uit veldenlijst/docs, niet live geschreven · **✗ afwijking** = geen equivalent, gevolg benoemd.

### 2.1 Crediteur (RLZ `PUT Vendors/{guid}`; onze `crediteur_kenmerk`)

| Wij schrijven naar RLZ | Odoo-equivalent | Bewijs / gevolg |
|---|---|---|
| `id` (client-GUID, UUIDv5) | — server-int `res.partner.id` (141) | **✗ afwijking**: eigen id-mapping + zoek-vóór-create op `vat`, anders naam (bewezen zoekpad `["|",["vat","=",…],["name","=",…]]`) |
| `Name` | `name` | ✓ LIVE |
| `PaymentDueDays` | `property_supplier_payment_term_id` (many2one `account.payment.term`) | ≈ — wij zetten de vervaldatum per document (2.2) |
| `crediteur_kenmerk.btw_nummer` (RLZ: niet schrijfbaar/leesbaar) | `vat` = "NL123456782B01" | ✓ LIVE — base_vat formaatcheck (elfproef) passeert; VIES uit |
| `crediteur_kenmerk.kvk_nummer` | `company_registry` = "12345678" | ✓ LIVE; `peppol_eas` werd automatisch `0106` |
| (RLZ Vendor is per administratie) | `company_id` = 1 óf False (gedeeld over de groep) | ✓ LIVE met `company_id 1`; **beslispunt** §5.2 (4) |
| `supplier_rank` | `supplier_rank 1`, `is_company True`, `country_id 165` | ✓ LIVE; `property_account_payable_id` auto 130000 |
| IBAN (`Vendors/{id}/BankRelations`, leesroute IBAN-wissel) | `bank_ids` → `res.partner.bank.acc_number` | ≈ (lezen) — IBAN-wissel-check kan hier direct op |

### 2.2 Inkoopfactuur (RLZ `PUT PurchaseInvoices/{guid}` + `/Uploads` + actie 17; `app/documenten/boeken.py`)

| Wij schrijven naar RLZ | Odoo-equivalent (`account.move`, `move_type in_invoice`) | Bewijs / gevolg |
|---|---|---|
| `id` = `rlz_herboeking_id(document_id, boek_cyclus)` (UUIDv5) | — server-int (3049); herboeking = nieuwe create | **✗ afwijking**: kolom `rlz_document_id uuid` past niet; adapter houdt (document_id, boek_cyclus) ↔ odoo-id; idempotentie §3.1 |
| `Entity.id` | `partner_id` | ✓ LIVE |
| `Reference` (factuurnummer leverancier) | `ref` = "TEST-ODOO-STAP0-A" | ✓ LIVE — voedt óók Odoo's `duplicated_ref_ids` |
| — (RLZ heeft geen betalingskenmerk-veld) | `payment_reference` = "TEST-STAP0-A-KENMERK" | ✓ LIVE (komt in de naam van de crediteurenregel: "TEST-ODOO-STAP0-A - TEST-STAP0-A-KENMERK") — nieuw veld, optioneel |
| `Date` (factuurdatum, ISO-datetime) | `invoice_date` = "2026-08-15" (kale datum) | ✓ LIVE |
| `BookDate` (boekdatum = factuurdatum, STAP-0 28-08) | **`date`** — **default zónder opgave = 2026-08-31 (maandeinde factuurmaand)** | ✓ LIVE: write `date` 2026-08-20 → 2026-08-15, blijft na posten; chatter trackt de wijziging. **Altijd expliciet zetten.** |
| `DueDate` | `invoice_date_due` = "2026-09-14" + `invoice_payment_term_id False` | ✓ LIVE — `date_maturity` op de crediteurenregel = 2026-09-14; zonder `False` op de termijn herleidt Odoo de vervaldatum uit de partner-termijn |
| `Description` (document) | `narration` (html) | ✓ LIVE |
| — | `journal_id` = 9 (BILL) — verplicht veld, per company | ✓ LIVE (RLZ leidt het dagboek uit het documenttype af; Odoo wil het expliciet) |
| — | `company_id` = 1 + context `allowed_company_ids [1]` | ✓ LIVE — **verplicht in deze multi-company-db** |
| regel `Account.id` | `invoice_line_ids[].account_id` (258 / 252) | ✓ LIVE |
| regel `TaxRate.id` | `tax_ids = [[6,0,[14]]]` (21 %) / `[[6,0,[13]]]` (9 %) | ✓ LIVE — Odoo maakt zelf de tax-regels (152000 D 21,00 / 152100 D 0,90, tag 5b) |
| regel `NetAmount` | `quantity 1` × `price_unit 100.00` → `price_subtotal 100.00` | ✓ LIVE cent-exact; `balance 100.00` |
| regel `TaxAmount` (wij sturen de factuur-btw) | **berekend** door Odoo (`round_globally`); afwijkende factuur-btw = `write {"balance": 21.01}` op de tax-regel (`display_type tax`, `tax_line_id 14`) in concept | ✓ LIVE: 21,00 → 21,01; `amount_tax 21.91`, `amount_total 131.91`, crediteurenregel C 131,91, `tax_totals` 21.01 — blijft na posten. ⚠️ reversal spiegelt dit niet (§3.3) |
| regel `Project.id` | `analytic_distribution = {"847": 100}` | ✓ LIVE op beide regels; ná posten `account.analytic.line` 7/8: amount −100 / −10, `account_id 847`, `general_account_id 424000/420100`, `date 2026-08-15`, `ref TEST-ODOO-STAP0-A`, `partner_id` |
| regel `Description` | `name` | ✓ LIVE |
| `/Uploads` (`id`, `FileName`, `Content` b64) — PUT, herstart-idempotentie via `zorg_voor_bijlage` | `ir.attachment.create({name, res_model "account.move", res_id, datas b64, mimetype})` (id 1433) + `register_as_main_attachment(force=True)` | ✓ LIVE: bytes identiek (sha1-checksum 407fb006…, 402 B), `message_main_attachment_id` gezet pas ná de expliciete registratie; `attachment_ids [1433]`. **Volgorde: ná `action_post`** (OCR auto_send op concepten). Idempotentie = zoek op (res_model, res_id, name/checksum). |
| actie 17 Book | `action_post(ids=[…])` | ✓ LIVE: state draft → posted, `name BILL/2026/08/0001`, `posted_before True` |
| readback `ReceiptNumber` (boekstuknummer) | `name` | ✓ LIVE |
| readback `Status` 1/2/3 | `state` (draft/posted/cancel) × `payment_state` (not_paid/partial/in_payment/paid/reversed) | ✓ LIVE: 1 ≈ draft; 2 ≈ posted + not_paid/partial; 3 ≈ posted + paid/reversed; **cancel = nieuw** (§3.2) |
| readback `OpenAmount` / `BaseRemainingAmount` | `amount_residual` | ✓ LIVE (131.91 → 0.01 → 0.00) |
| duplicaatquery `Entity+Reference+bedrag` (`find_purchase_invoices_by_reference`) | `search_read` `[["ref","=",…],["partner_id","=",…],["move_type","=","in_invoice"],["company_id","=",1],["state","!=","cancel"]]` + `amount_total` | ✓ LIVE (het idempotentie-zoekpad van het script) + Odoo's eigen `duplicated_ref_ids` (§3.6) |
| actie 19 Correct (zelfde document → concept) | **`account.move.reversal` → apart `in_refund`-document** (§3.3); óók mogelijk: `button_draft` (zelfde document → draft) | ✓ LIVE beide |

### 2.3 Kostprijs-memoriaal (RLZ `PUT ManualJournals/{guid}?autoCorrect=false` + actie 17; `app/omzet/boeken.py::_boek_memoriaal`)

| Wij schrijven naar RLZ | Odoo-equivalent (`account.move`, `move_type entry`) | Bewijs |
|---|---|---|
| `id` (client-GUID) | server-int (3053) | ✗ afwijking, als 2.2 |
| `JournalEntryDiary.id` (memoriaal-dagboek per administratie) | `journal_id` = 10 MISC (alternatief 36 STJ "Voorraadwaardering") | ✓ LIVE |
| `Reference` | `ref` = "TEST-ODOO-STAP0-B" | ✓ LIVE |
| `Date` + `BookDate` (periode-einde) | `date` = "2026-08-15" (één veld; geen `invoice_date`) | ✓ LIVE |
| regel `Account.id` | `line_ids[].account_id` (336 / 208) | ✓ LIVE |
| regel `CreditOrDebit` 1/2 + `DebitAmount`/`CreditAmount` | `debit` / `credit` (het teken zit in het veld, geen aparte richtingsvlag); `balance` = debit − credit | ✓ LIVE (D 250 / C 250) |
| regel `Description` | `name` | ✓ LIVE |
| saldo-0 (onze harde check + RLZ) | **Odoo weigert bij `create`: 422 UserError "De boeking is niet in balans."** — niets bewaard | ✓ LIVE (onbalans 250/240) |
| `autoCorrect=false` | n.v.t. (Odoo corrigeert niets stil) | — |
| `/Uploads` (zelfde PDF als de omzetboeking) | `ir.attachment` op de `entry` (zelfde model) | ≈ niet apart bewezen — zelfde mechaniek als 2.2 |
| actie 17 | `action_post` → `MISC/2026/08/0001` | ✓ LIVE |
| actie 19 | reversal-wizard → **direct geposte** tegenboeking `MISC/2026/09/0001`, ref "Reversal of: MISC/2026/08/0001, <reden>" | ✓ LIVE |
| één-transactie-garantie omzet (verkoop + memoriaal) | twee losse creates/posts — geen atomiciteit over calls; half-geboekt-patroon blijft | ≈ (docs: elke call eigen transactie) |

### 2.4 Verkoopfactuur (RLZ `PUT SalesInvoices/{guid}`; omzet-Receipts, Vastly-verkoop, doorbelasting) — **alleen mapping, geen bewijs-boeking**

| Wij schrijven naar RLZ | Odoo-equivalent (`move_type out_invoice` / `out_refund`) | Status / gevolg |
|---|---|---|
| `Entity.id` (debiteur) | `partner_id` (customer) | ≈ (company 3 leest zo) |
| entity-loze Receipt (kasomzet, besluit 08-08 "geen dummy-debiteur") | **✗ afwijking**: `out_invoice` vereist een partner bij posten; Odoo heeft geen debiteurloze verkoopfactuur (wel `entry` op omzet/btw/kas — dan geen btw-per-regel-mechaniek maar handmatige btw-regels mét tags) | **beslispunt** §5.2 (6) |
| `DocumentCategory` ("Verkoopfactuur (Omzet)") | geen categorie-concept → `journal_id` (INV of een eigen verkoopdagboek per stroom) | ≈ |
| `Reference` (RLZ overschrijft met eigen nummer) / `InvoiceNumber` | `name` = dagboekreeks bij posten (company 3: `F/2026/00027`); `name` is schrijfbaar maar dan buiten de reeks | ≈ — Odoo's nummer is leidend, zoals bij RLZ |
| `Date`/`BookDate` | `invoice_date` / `date` (default voor verkoop = `invoice_date`, docs) | ≈ |
| regels `Account`/`TaxRate`/`NetAmount`/`TaxAmount`/`Description` | `invoice_line_ids` als 2.2 met verkoop-codes 7 (21% ST), 6 (9% ST), 5 (0%), 19 (0% R verlegd), 23–25 (ICL), 32 (export) | ≈ (velden gelezen op `F/2026/00027`: tax-regel 150000 C 86,14, tag 1a, debiteurenregel 110000) |
| `Quantity`/`Price` (voorraad-uitstroom) | `quantity` / `price_unit` native, `product_id` optioneel | ≈ — rijker dan RLZ |
| duplicaat-marker in regel-1-Description (`OMZ-…-VK`, `VASTLY-VERKOOP nr ·`) | `ref` / `invoice_origin` — Odoo neemt de document-Description níét over uit regel 1 | ≈ — marker kan naar `ref` (netter) |
| creditnota 381 | `out_refund` (eigen reeks `RINV`/… als `refund_sequence`) | ≈ |
| `GET SalesInvoices/{id}/Download` (rechtsgeldige PDF, blok A 26-08) | `invoice_pdf_report_id` ontstaat bij "verzenden"; rendering via `ir.actions.report` is een private methode → niet via JSON-2, wel via de HTTP-rapportroute mét sessie | **open** — apart STAP-0 vóór de doorbelasting-flow |
| webhook `factuur_geboekt` | ongewijzigd (domein) | — |

### 2.5 Project (RLZ `PUT {adminId}/Projects/{guid}` klant-loos; `app/projecten/`)

| RLZ | Odoo | Bewijs |
|---|---|---|
| `id` UUIDv5(administratie, pand_referentie) | server-int (847) + zoek-vóór-create op `name`/`code` | ✓ LIVE |
| `Name` (max 50) | `name` (geen 50-grens gezien; `code` apart, weergave "[code] name") | ✓ LIVE |
| `IsActive` | `active` (archiveren = False) | ✓ LIVE (opruimstap) |
| — | `plan_id` = 1 (Project), `company_id` | ✓ LIVE |
| `project_cache` | `account.analytic.account` search_read `[["plan_id","=",1],["company_id","in",[X,False]]]` | ✓ LIVE (lezen) |
| projectcijfers-sync (RLZ `JournalEntryLines` + Project-expand) | `account.analytic.line` (`account_id`, `amount`, `date`, `general_account_id`, `move_line_id`, `ref`) | ✓ LIVE (lezen ná posten) |

### 2.6 Buiten scope van deze verkenning (alleen benoemd)

Bank (RLZ `PaymentTransactions`, actie 15, `BankMutationDirectBookings`) → Odoo `account.bank.statement.line` + reconciliatiemodel; `account_online_synchronization` is geïnstalleerd (Odoo haalt zelf bank op). Waarborg-memoriaal = 2.3. Aangifte-poort (RLZ `TaxDeclarations`) → `tax_lock_date` op `res.company` + `l10n_nl_reports` (lezen). Afletteren-tegen-open-post → `account.move.line.reconcile` (bewezen als mechaniek in A: crediteurenregels origineel ↔ creditnota).

---

## §3 Semantiekverschillen t.o.v. RLZ (adapter-huiswerk, geen domein-vertakking — guardrail 0016)

### 3.1 Geen client-GUID's → idempotentie-strategie

- RLZ: `PUT` met UUIDv5 is create-or-update; een her-PUT is idempotent. **Odoo: `create` geeft een nieuw int-id, altijd** — de dubbele create in A maakte gewoon concept 3050 naast 3049.
- Strategie (bewezen zoekpad): vóór élke create `search_read` op `(company_id, partner_id, ref, move_type, state != cancel)`; treffer → hergebruik (concept: door-posten; gepost: klaar). Mapping `(document_id, boek_cyclus) → odoo_move_id` lokaal vastleggen zodra de create antwoordt; verlies van het antwoord (time-out ná commit) wordt door het zoekpad opgevangen. `ref` = factuurnummer leverancier blijft de natuurlijke sleutel — en voedt tevens Odoo's eigen duplicaat-signaal (3.6).
- Optioneel anker: `ir.model.data` (externe id "rlz.<uuid>", `has_access create` ✓) — niet live getest (schrijfbudget), kandidaat voor het bouwplan.
- Onze `rlz_document_id`-kolommen zijn `uuid`; Odoo-id's zijn int → adapter heeft een eigen id-kolom/-tabel nodig (0016-prep: koppeling+credential-model). Bijlage-idempotentie: zoek `ir.attachment` op `(res_model, res_id, checksum)` i.p.v. cyclus-GUID.

### 3.2 Boeken = `action_post`; statusmodel

| RLZ | Odoo |
|---|---|
| Status 1 Tentative/Concept | `state draft` (`name` False, geen nummer) |
| Status 2 Open (geboekt, niet volledig afgeletterd) | `state posted` + `payment_state not_paid` / `partial` / `in_payment` |
| Status 3 Closed (afgeletterd, `BaseRemainingAmount 0`) | `state posted` + `payment_state paid` / `reversed`; `amount_residual 0` |
| — | **`state cancel`** (geannuleerd concept; nooit geboekt) — RLZ kent dit niet; ons statusmodel moet 'm kunnen tonen (bv. het geannuleerde duplicaat 3050) |
| actie 17 op een concept | `action_post(ids)`; nummer + `posted_before` + chatter "Draft → Posted" |
| actie 17 op gepost = 409 | `action_post` op gepost = no-op (`false`) |

### 3.3 Terugdraaien = reversal als APART document — gevolgen voor storno-paden en tijdlijn

- **Odoo-norm:** `account.move.reversal.create({move_ids, reason, journal_id, date, company_id})` + `reverse_moves(ids)` → nieuw document met `reversed_entry_id` = origineel; origineel krijgt `reversal_move_ids` + chatter "This entry has been reversed" en `payment_state reversed` zodra de creditnota gepost en afgeletterd is. Factuur → **concept**-creditnota (`in_refund`, `RBILL/…`, `invoice_date` = wizard-datum); `entry` → **direct gepost**. De reversal spiegelt regels én `analytic_distribution` (analytic lines +100/+10).
- **⚠️ Cent-override wordt niet gespiegeld:** de wizard herberekent de btw uit de regels (21,00), niet uit de geposte tax-regel (21,01) → creditnota 131,90 vs 131,91, origineel `partial` met € 0,01. Adapter: creditnota-tax-regel(s) vóór het posten gelijkzetten aan het origineel (A2: `write balance -21.01` → posten → origineel `reversed`, residu 0).
- **Actie-19-analoog bestaat:** `button_draft(ids)` zet een gepost document terug naar concept (A2, creditnota 3051: posted → draft, nummer `RBILL/2026/09/0001` blijft, afletterng automatisch losgemaakt, chatter "Posted → Draft"). Voorwaarden: geen lock-date over de boekdatum en geen hash-dagboek. **Aanbeveling: nooit gebruiken in de adapter** (het is het Odoo-equivalent van "aanpassen ná boeken" — in strijd met de audit-lijn die Peter juist in RLZ mist), behalve als expliciete Beheerder-noodrem.
- **Gevolgen voor onze paden:**
  - *Storno inkoop (actie 19 → `te_controleren`, zelfde document)*: in Odoo blijft het origineel gepost en komt er een creditnota → dit is ons **TEGENBOEK-pad** (22-08) 1-op-1; "tegenboeken én opnieuw boeken" = wizard `is_modify=True` (maakt óók een nieuw concept-kopie) of onze eigen herboeking op een nieuw odoo-id (boek_cyclus+1). De storno-poort ná ingediende aangifte (`app/rlz/aangifte.py`) wordt een `tax_lock_date`-toets; het tegenboek-pad hoeft niet meer als uitzondering te gelden — het ís de norm.
  - *Tijdlijn/archief*: "gestorneerd" toont in Odoo-administraties altijd twee documenten (nummer origineel + nummer creditnota, kruisverwijzing zoals de chip TEGENGEBOEKT); `factuur_gestorneerd` (koppelcontract §3b) blijft semantisch "boekstand 0" — de webhook-payload kan de creditnota-id als `corrigeert_document_id`-tegenhanger dragen (contractvraag voor vastgoed, geen wijziging nodig voor de RLZ-administraties).
  - *Bank-storno's, omzet-één-transactie-rollback*: rollback = reversal + posten (twee calls) i.p.v. één actie 19; een mislukte tweede call = zichtbaar half-geboekt (patroon bestaat al).
  - *Reconciliatie-CLI's* (`storno_detectie.py`: "Status 1 geworden") → hier: `reversal_move_ids` gevuld óf `state` van posted naar draft/cancel (button_draft-detectie).

### 3.4 Nummering bij posten

Concept heeft geen nummer (`name False`); het nummer ontstaat bij `action_post` uit dagboek + laatste naam (maand- of jaarreset volgt de eerste boeking; company 1 BILL = maand). `RBILL/` voor creditnota's (`refund_sequence True`), `MISC/` memoriaal. Reset-naar-concept behoudt het nummer (geen gat). Het boekstuknummer dat wij tonen (`rlz_boekstuknummer`) = `name` ná posten — pas dan beschikbaar (RLZ geeft `ReceiptNumber` óók pas ná actie 17: gelijk).

### 3.5 Lock dates / ingediende btw-periodes

Niet live getest (alle lock dates False; instellingen niet gewijzigd). Uit de 19.0-docs (year-end): "Lock Everything" **verhindert posten met een boekdatum op/vóór de lock date en verplaatst bij een poging de boekdatum automatisch naar de dag ná de lock date**; uitzonderingen per gebruiker/iedereen mét reden (gelogd op de company-chatter, model `account.lock_exception`); de **Hard Lock date is onomkeerbaar**. Aparte `tax_lock_date` (btw-aangifte), `sale_lock_date`, `purchase_lock_date`, `fiscalyear_lock_date`, `hard_lock_date` op `res.company`. Gevolg: (a) de datum-verschuiving is RLZ's "TaxSource naar de eerstvolgende open periode" in een andere jas — maar op de HELE boekdatum, niet alleen de btw; onze aangifte-poort moet `date` vóóraf toetsen tegen `tax_lock_date`/`hard_lock_date` en het document niet stil laten verschuiven; (b) `button_draft`/reversal op een gelockte periode = geweigerd → storno-poort-vertaling bestaat al (`app/rlz/aangifte.py`-patroon).

### 3.6 Duplicaat-signalering van Odoo zelf

`account.move.duplicated_ref_ids` (computed, readonly): op het concept 3050 stond `[3049]` en op 3049 `[3050]` — zelfde partner + zelfde `ref` (Odoo kijkt ook naar bedrag/datum-nabijheid bij lege ref). Ná `button_cancel` van 3050 was 3049's signaal leeg (geannuleerde documenten tellen niet). Odoo blokkeert het posten van een duplicaat in 17+ niet hard (UI-waarschuwing) — niet live bewezen (budget: het duplicaat is bewust nooit gepost). Ónze duplicaatcheck blijft de poort (kernprincipe 5); Odoo's signaal is een gratis tweede lijn, leesbaar vóór het posten — anders dan RLZ's actie 138.

### 3.7 Atomiciteit, foutsemantiek, limieten

- Eén `create` mét geneste `invoice_line_ids`/`line_ids`-commando's is één transactie: de onbalans-create liet niets achter. Document + regels zijn dus atomair; **posten en bijlage zijn losse calls** → tussenstanden zijn zichtbare Odoo-concepten (nooit stil), het zoekpad uit 3.1 hervat.
- Fouten: HTTP-status per exceptietype (§1.11); `message` is gelokaliseerd (nl_NL van de API-gebruiker) — foutvertaling op `name` (`odoo.exceptions.UserError`/`AccessError`/`ValidationError`), niet op tekst.
- `read` op een onbekend id geeft `[]` (geen 404) → "bestaat het nog"-toetsen op lengte.
- Rate: geen gepubliceerde limiet; ~200 ms per call sequentieel; worker-time-outs op Odoo Online → geen bulk-reads zonder paginering (`limit`/`offset`), zelfde les als de 504 van de cijfers-sync.
- API-key: max 3 maanden → kwartaalrotatie als beheerde handeling (credential-store); `res.users.apikeys` is leesbaar voor een vervaldatum-bewaking (bewaking-probe).
- Digitalisering: `extract_in_invoice_digitalization_mode auto_send` + BILL-dagboek-alias kunnen concepten aanmaken náást de onze → de mail-intake-route moet per administratie eenduidig zijn (klikpunt §5.3).

---

## §4 Bewijs-cycli (live, company 1, alles `TEST-`, audit-log 23 regels)

### 4.1 Cyclus A — inkoop "TEST-ODOO-STAP0-A" (`odoo_stap0_bewijs.py a` + `a2`)

| # | Stap | Uitkomst (terug-gelezen) |
|---|---|---|
| A1 | `res.partner.create` TEST-crediteur (vat NL123456782B01, KvK 12345678, company 1) | id 141; `vat`/`company_registry` exact terug; payable 130000 auto; `peppol_eas 0106`; `autopost_bills ask` |
| A2 | `account.analytic.account.create` (plan Project, code TEST-STAP0, company 1) | id 847, weergave "[TEST-STAP0] TEST-ODOO-STAP0 Project" |
| A3 | `account.move.create` in_invoice, journal 9, ref, payment_reference, invoice_date 15-08, **geen `date`**, due 14-09, term False, 2 regels (424000 € 100 @21 % · 420100 € 10 @9 %, analytic 847 = 100 %) | id 3049, `name False`, `state draft`; **`date 2026-08-31`**; untaxed 110,00 / tax 21,90 / total 131,90; regels: product 100/10 (analytic {'847': 100}), tax 152000 D 21,00 (tag 5b) + 152100 D 0,90, payment_term 130000 C 131,90 mat 14-09; `duplicated_ref_ids []`, `extract_state no_extract_requested` |
| A4 | boekdatum-test: `write date 2026-08-20` → `write date 2026-08-15` | `date` volgt exact; `invoice_date` ongewijzigd; chatter trackt "Date (Journal Entry) 31-08 → 20-08 → 15-08" |
| A5 | btw-cent-override: `account.move.line.write {balance: 21.01}` op de 21 %-tax-regel | tax 21,91 / total 131,91 / residu 131,91; crediteurenregel C 131,91; `tax_totals` groep VAT 21% = 21.01 |
| A6 | dubbele create (zelfde partner + ref, één regel € 1, concept) | id 3050; `duplicated_ref_ids` 3050→[3049] én 3049→[3050]; `button_cancel` → `state cancel`, `name False` (nooit gepost, niet verwijderd); daarna 3049 `dup []` |
| A7 | `action_post` | `name BILL/2026/08/0001`, `state posted`, `date 2026-08-15`, `due 2026-09-14`, bedragen ongewijzigd (21,01 blijft), `payment_state not_paid`, `sequence_prefix BILL/2026/08/` nr 1, `inalterable_hash False`; analytic lines 7/8: −100,00 / −10,00 op 847, general_account 424000/420100, date 15-08, ref TEST-ODOO-STAP0-A |
| A8 | `ir.attachment.create` (PDF 402 B) ná posten; `register_as_main_attachment(force=True)` | id 1433, checksum 407fb006…, `res_model account.move`/`res_id 3049`; `attachment_ids [1433]`; `message_main_attachment_id` pas ná registratie; `datas` terug = byte-identiek; `extract_state` blijft `no_extract_requested` |
| A9 | `account.move.reversal.create` (reason, journal 9, date 02-09) + `reverse_moves` | act_window `res_id 3051`: `in_refund` **draft**, ref "Omgekeerde boeking van: BILL/2026/08/0001, STAP-0 storno TEST-ODOO-STAP0-A", `reversed_entry_id 3049`, invoice_date/date/due 02-09, regels gespiegeld incl. analytic; **tax 21,00 (niet 21,01) → total 131,90** |
| A10 | `action_post` creditnota | `RBILL/2026/09/0001`, posted; auto-afletterng: creditnota `paid`/residu 0; **origineel `partial`, residu 0,01** |
| A11 (a2) | `button_draft` creditnota → `write balance -21.01` op haar 21 %-regel → `action_post` | draft (nummer blijft), chatter "Posted → Draft" + "Balance −21,0 → −21,01" + "131,9 → 131,91"; ná posten: creditnota 131,91 `paid`; **origineel `payment_state reversed`, `amount_residual 0.0`**, crediteurenregels beide `reconciled True`; creditnota-analytic lines +100 / +10 |
| A12 (opruimen) | `write active False` op partner 141 en analytic 847 | gearchiveerd, niets verwijderd |

Eindstand company 1 ná A: `BILL/2026/08/0001` posted/reversed 131,91 · concept 3050 cancel (€ 1, TEST-ref) · `RBILL/2026/09/0001` posted/paid 131,91. Grootboek-netto 0; voorbelasting 5b netto 0.

### 4.2 Cyclus B — memoriaal "TEST-ODOO-STAP0-B" (`odoo_stap0_bewijs.py b`)

| # | Stap | Uitkomst |
|---|---|---|
| B1 | `create` entry MISC, D 700100 250,00 / C 300100 **240,00** | **HTTP 422 `odoo.exceptions.UserError` "De boeking is niet in balans."**; `search_read` op ref = [] → niets bewaard |
| B2 | `create` entry MISC, date 15-08, ref, D 700100 250,00 / C 300100 250,00 | id 3053 draft, `name False`, total 250,00 (regels display_type product, quantity 1) |
| B3 | `action_post` | `MISC/2026/08/0001`, posted, date 15-08 |
| B4 | reversal-wizard (journal 10, date 02-09) + `reverse_moves` | id 3054 **direct posted** `MISC/2026/09/0001`, ref "Reversal of: MISC/2026/08/0001, STAP-0 storno TEST-ODOO-STAP0-B" (Engels — de factuur-variant was Nederlands), regels gespiegeld (C 250 / D 250), `reversed_entry_id 3053`; origineel `reversal_move_ids [3054]` |

Eindstand: twee geposte memorialen die elkaar opheffen. Chatter op alle vijf documenten bevat elke overgang (aanmaak, datumwijzigingen, status, balance-edits per regel, reversal-links, betaalstatus) — Odoo's audit-spoor is per veld en per regel.

---

## §5 Conclusie

### 5.1 Aanbevolen adapter-aanpak (bouwplan volgt ná akkoord)

1. **Fundament eerst (0016-prep, eigen migratie):** koppeling+credential-model per administratie (`backend_type reeleezee|odoo`, credential-verwijzing, backend-config = `odoo_url` + **`company_id`**), adapter-registry, port-interface uit de bestaande seams. Externe-id-opslag: een `extern_document_id text` naast de bestaande `rlz_*`-uuid-kolommen (of een mappingtabel `(document_id, boek_cyclus) → extern id`) — het domein blijft uuid-vrij van Odoo. Rechten-probe bij opzetten (0016 §5): versie, `has_access` op de modellen, `company_ids` bevat de company, BILL/MISC/INV aanwezig, tarieven 14/13/20 + equivalenten, lock dates, API-key-vervaldatum, digitaliseringsmodus.
2. **Stamgegevens-sync (read-only, laag risico):** `account.account` → ledger-cache (code/naam/type/`deprecated`), `account.tax` → taxrate-cache (naam/`amount`/type_tax_use/rubriek-tags — 21% R = "verlegd"), `res.partner supplier_rank>0` → vendor-cache (mét `vat`/`company_registry` → voedt `crediteur_kenmerk` direct), `account.analytic.account` plan Project → project-cache, `account.payment.term`. Alles per company. Dit dekt ook de adapter-grepen uit de steigerbouw-run (VendorCache, `Boekvoorstel.vendor_id`, materiaal-leverancier).
3. **Flow 1 = inkoop** (zoals opgedragen): `zorg_voor_crediteur` (zoek op vat → KvK → naam, create mét vat/company_registry) → `create` in_invoice mét `date` = factuurdatum, `invoice_date_due` + term False, regels `quantity 1 × price_unit`, `tax_ids`, `analytic_distribution` → tax-cent-override alleen als factuur-btw ≠ berekend (chip + audit) → `action_post` → bijlage + `register_as_main_attachment` → readback `name`/`state`/`amount_residual`. Storno-capability = reversal + spiegel-override + posten (+ afletterng-check); `tegenboeken` = dezelfde operatie (het tegenboek-pad wordt de norm); `button_draft` niet in de capability-set.
4. **Flow 2 = memoriaal/omzet** (entry, saldo-0 door Odoo dubbel bewaakt; reversal auto-post). Kasomzet vergt eerst het beslispunt (6).
5. **Flow 3 = verkoop** (Vastly-verkoop, doorbelasting) ná een eigen STAP-0 voor de PDF-rendering en de Peppol-vraag. **Bank = Odoo-native laten** (online synchronisatie staat al aan) tenzij Peter anders beslist — geen actie-15-analoog nodig.
6. **Tests:** capability-contract (niet-ondersteund = zichtbare fout), mapping-tests op de vals-bouwers (cent-exact, date expliciet, company overal), idempotentie-zoekpad, reversal-spiegel.

### 5.2 Open beslispunten voor Peter

1. **Eén database, tien entiteiten, één alles-kunnende API-gebruiker.** Wil je per Universal-BV (of per eigenaargroep) een aparte technische Odoo-gebruiker met alleen Accounting-rechten en beperkte `company_ids`, zodat een fout in onze code nooit in Roompot/Bonte Hoeve kan schrijven? (Klikwerk Peter in Odoo: Settings › Users.)
2. **Storno-semantiek vastleggen:** reversal (creditnota, twee documenten, Odoo-norm) als enige storno-weg; `button_draft` uitgesloten. Tijdlijn-/archiefweergave toont voor Odoo-administraties beide nummers. Akkoord?
3. **Boekdatum:** `date` = factuurdatum expliciet (besluit 27-08 blijft) — Odoo's maandeinde-default bewust overrulen. Akkoord?
4. **Crediteur-scope:** partner per company (`company_id`) of groepsgedeeld (`company_id False`, zoals de 127 bestaande partners)? Gedeeld past bij een groep die onderling factureert (Universal Nederland is al partner van Universal Verkoop); per company is de RLZ-analogie.
5. **Btw-nul/vrijgesteld inkoop:** geen `tax_ids` (geen rubriek) vs een eigen 0 %-inkoopcode laten aanmaken (klikpunt). Verlegd = `21% R` (bewezen aanwezig).
6. **Kasomzet zonder debiteur:** Odoo kent geen debiteurloze verkoopfactuur → (a) toch een systeem-debiteur "Kasomzet" per Odoo-administratie (herziet besluit 08-08 alleen voor Odoo, in de adapter), of (b) omzet als `entry` met handmatige btw-regels + rubriek-tags (geen factuur-object, wel correcte aangifte). Aanbeveling (a) — Odoo's btw-mechaniek blijft dan intact.
7. **Cent-override-beleid:** factuur-btw ≠ Odoo-berekening → tax-regel overschrijven (bewezen) mét oranje chip, of factuur terug naar de mens? Aanbeveling: overschrijven binnen ± € 0,02 per tarief (onze netto+btw=incl-check blijft de poort), daarboven mens.
8. **`ref` = factuurnummer leverancier, `payment_reference` = betalingskenmerk** (nieuw veld dat RLZ mist) — meenemen uit de extractie?
9. **Universal Verkoop draait al in Odoo:** de voorraad-uitstroom-leesroute (`rlz_uitstroom.py`) leest voor die BV nu RLZ, terwijl nieuwe verkoop in Odoo staat (`F/2026/…`). Wanneer schakelt die BV om, en is de leesroute (eerste Odoo-adapter-afnemer, read-only) de logische eerste stap?
10. **API-key-beheer:** kwartaalrotatie (max 3 maanden) als beheerde handeling + bewaking op `expiration_date`; de key "N-Module" (02-09) staat zonder vervaldatum — bewust?

### 5.3 Klikpunten Odoo (instellingen die door Peter aan/uit moeten — niet door de verkenning gezet)

| # | Waar in Odoo | Wat | Waarom |
|---|---|---|---|
| K1 | Settings › Users & Companies › Users | aparte technische gebruiker(s) per administratie(-groep), Accounting-rechten, `Allowed Companies` beperkt; API-key met 3-maands-looptijd | beslispunt (1), (10) |
| K2 | Accounting › Configuration › Settings › Digitization (per company) | `Vendor bills: Do not digitize` (of minimaal niet `auto_send`) voor administraties waar onze module de intake is; BILL-dagboek-alias uit of eenduidig | dubbele concepten uit OCR naast onze boekingen |
| K3 | Accounting › Accounting › Lock Dates | beleid: `tax_lock_date` ná elke ingediende aangifte, `fiscalyear_lock_date` ná jaarafsluiting; Hard Lock alleen bewust | onze storno-/aangiftepoort krijgt een echte toets; nu alles open |
| K4 | Accounting › Configuration › Journals › BILL/INV/MISC › "Lock Posted Entries with Hash" | aan = onveranderlijkheid (blokkeert `button_draft`) | audit-lijn; beslispunt (2) |
| K5 | Accounting › Configuration › Taxes | zo nodig 0 %-inkoopcode (beslispunt 5); controleren dat de NL-codes op Universal Steigerbouw actief blijven | mapping 2.2 |
| K6 | Accounting › Configuration › Analytic Plans › Project | `Applicability` op Mandatory voor project-verplichte administraties (optioneel — onze harde check blijft de poort) | tweede slot voor `project_verplicht` |
| K7 | Contacts | partner-instelling `autopost_bills` = Never voor leveranciers die via onze module lopen (alleen relevant bij OCR-intake) | geen Odoo-auto-post buiten onze poorten |
| K8 | Settings › Companies | vertalingen rekeningnamen (nu Engels) — cosmetisch | leesbaarheid voor de kantoormedewerkers |

Voor de twee bewijs-cycli was **geen enkel klikpunt nodig**: alles werkte met de bestaande inrichting.

---

## §6 Fase 1 (03-09-2026) — product-semantiek + live-correcties op STAP-0 (blok B, `verkenning/odoo_stap0_producten.py`)

Live op company 1 (TEST-ref `TEST-ODOO-FASE1-PRODUCTEN`, factuur `BILL/2026/09/0001` 115,91 → reversal
`RBILL/2026/09/0002`, origineel `reversed`/residu 0,00; TEST-partner + TEST-product gearchiveerd, niets verwijderd).
Ruwe uitvoer `verkenning/output/odoo_fase1_producten.json` (gitignored).

| # | Vraag | Uitkomst (terug-gelezen) | Gevolg adapter |
|---|---|---|---|
| P1 | Productregel ZONDER `account_id` | rekening = `product.category.property_account_expense_categ_id` (700100) — de categorie, niet het product (`property_account_expense_id` False) | wij sturen ALTIJD een expliciete `account_id` uit het boekvoorstel; categorie = alleen terugval |
| P2 | Productregel MÉT expliciete `account_id` 424000 | blijft staan ná posten (424000 Tools), analytic + tax ongewijzigd | het boekvoorstel bepaalt de rekening — bewezen |
| P3 | `quantity 4 × price_unit 12,34` | `price_subtotal 49,36` cent-exact; `tax_ids []` blijft leeg (géén auto-`supplier_taxes_id`) | regelniveau aantal × prijs werkt; 0 %-inkoop = géén tax_ids bewezen |
| P4 | `analytic_distribution` op productregel | `account.analytic.line` mét `product_id` (bv. `[AKN-TEST0001] …`) én `unit_amount` = quantity (4,0 / 3,0), `amount` −netto, `general_account_id` | Jarvis/MI leest product + aantal + bedrag + rekening + project uit `account.analytic.line` — acceptatiecriterium aantoonbaar |
| P5 | Anglo-saxon + posten leveranciersfactuur zonder PO | `stock.move` vóór/ná 0/0; categorie `periodic`/`standard`; type `consu`, `is_storable` False → gewone kostenboeking, geen tussenrekening/kostprijsmechaniek | brug maakt `consu`-producten (geen voorraadwaardering in Odoo — die blijft onze mi-laag/telling) |
| P6 | Eigen brug-product (template `consu`, `default_code AKN-…`, categorie uit catalogus) zonder `account_id` | rekening uit de categorie (700100); `standard_price 0` | brug = lookup op `default_code` → naam → aanmaak; categorie alleen bestaande Odoo-categorie op naam (inrichtingskeuze Odoo, adapter maakt geen categorieën) |
| C1 | `account.account.deprecated` | **bestaat niet in Odoo 19** (`ValueError: Invalid field`) — STAP-0 §1.5 was hierin onjuist; `active` is het signaal | sync filtert op `active = True` |
| C2 | Instellingen company 1 (live 03-09) | `fiscalyear_lock_date` = `tax_lock_date` = **2025-12-31** (K3 gezet), `extract_in_invoice_digitalization_mode` = **`no_send`** (K2 gezet); company 3 nog `auto_send`, geen lock dates | lock-date-poort vóór de create (`app/odoo/fouten.py::lock_date_melding`), bijlage blijft ná posten |
| C3 | API-keys | "Facturatie" (verloopt 2027-08-12), "Nijenhuis Module" (2026-11-22), "N-Module" (02-09, géén vervaldatum) | probe `api_key` informatief; rotatie blijft klikpunt |
| C4 | `res.partner.bank` | IBAN-leesroute voor de IBAN-wissel-check = `acc_number`/`active` per partner | `OdooLeesFacade.get("Vendors/{id}/BankRelations")` |
| C5 | Reversal-wizard | `reverse_moves` geeft act_window mét `res_id` (creditnota, `in_refund`, draft); zonder btw-override geen residu | adapter spiegelt override alleen als er één was |

Ontwerpgevolg (blok C): regels gaan als `quantity × price_unit` mét `product_id` waar de materiaalbrug een product kent
én `aantal × stuksprijs = netto` cent-exact uit het veldvoorstel volgt; anders `1 × netto` (nooit gokken). Rekening,
btw en project komen ALTIJD expliciet uit het boekvoorstel — Odoo leidt niets af.

## §7 Adapter keten-cyclus — LIVE 04-09-2026 (blok F, GO Peter 03-09; via de app-API, geen los script)

Volledige keten op **company 1 (Universal Steigerbouw B.V., leeg)** via de eigen HTTP-API (uvicorn 8011, dev-DB ná
migratie 0104, Beheerder-token) — géén rechtstreekse Odoo-schrijfcalls buiten het opruimen (archiveren, zie stap 12).
Ruwe request/response-log (API-key geredigeerd): `verkenning/output/odoo_keten_cyclus_2026-09-04.jsonl` (gitignored,
33 regels). Echte factuur-PDF: `20260066.pdf` (Confide BV, btw verlegd, 9 regels, € 10.323,49) mét TEST-referentie
`TEST-ODOO-KETEN-20260066` op de TEST-crediteur "TEST-ODOO-KETEN Leverancier (niet gebruiken)". Niets verwijderd in
Odoo; géén writes op company 3; géén RLZ-writes.

| # | Stap (app-route) | Uitkomst (terug-gelezen uit Odoo waar relevant) |
|---|---|---|
| 1 | `POST /instellingen/odoo/verbinding-testen` | 200 — 10 companies, alle `al_gekoppeld: false` |
| 2 | `POST /instellingen/odoo/koppelen` company 1 | **eerste poging 500** (UniqueViolation op het sentinel `odoo:universal-steigers.odoo.com:1` — een halve-stand-rij uit de migratie-herdraai van 0101 droeg het nog; gefixt: sentinel-dragers tellen als "al gekoppeld" → leesbare 422); tweede poging **201**, probe 29/29 groen (lock dates 31-12-2025 informatief), eerste sync 355 grootboek · 17 btw · 4 crediteuren · 4 projecten |
| 3 | `GET /administraties/{id}/odoo` | stand mét `stamgegevens {355,17,4,4}`, `probe_rapport`, `laatste_sync_op` |
| 4 | `POST /administraties/{id}/crediteuren` (controlescherm-pad "+ Nieuwe crediteur") | 201 → `res.partner` 160, groepsgedeeld (`company_id False`), vendor-UUID `2bd67f6d-…` |
| 5 | Materiaal: leverancier + categorie + 2 producten (`PUT /materiaal/{id}/…`) → `POST …/odoo/producten-brug` | `uren_meerwerk` moest AAN (materiaal-opt-in, 409 anders); brug: gevonden 0, **aangemaakt 2** (`product.product` 9261 `[AKN-9C4F8801] Huur dixi per week`, 9262 `[AKN-B94F8304] Materialen ventilatie`, `consu`, company 1) |
| 6 | `POST /administraties/{id}/documenten` (PDF-upload) | 201 in 22 s, AI-extractie 9 regels mét `hoeveelheid`/`stuksprijs`/`eenheid` (bv. 7 × 42,35 = 296,45; 25,5 uur × 60,50), kop: btw 0,00 + "BTW verlegd", btw-nummer geverifieerd, IBAN gelezen |
| 7 | `PUT …/boekvoorstel` (vendor TEST, referentie TEST-…, 9 regels mét `21% R` (verlegd) + project op élke regel, `regels_samenvoegen false`) | 200; harde checks 8/8 groen (duplicaatcheck via de Odoo-leesfacade, IBAN-baseline vastgelegd) |
| 8 | `POST …/boeken` — **eerste poging** | **502** "Je kunt geen boeking maken met een gearchiveerde analytische rekening: TEST-ODOO-STAP0 Project" — het gekozen project was het in STAP-0 gearchiveerde analytic account, dat de sync tóch aanbood (`active in (True, False)`). App: status `boeken_mislukt` mét de leesbare Odoo-fout; het Odoo-concept (draft, marker in `invoice_origin`, `date = invoice_date = 2026-06-05`) bleef staan. **Drie fixes:** (a) sync leest alleen `active = True` analytic accounts (her-sync: `projects verdwenen 1`); (b) een hergebruikt concept krijgt kop + regels VERVERST uit het actuele voorstel (`[5,0,0]` + verse regels) vóór het posten — anders zou het oude regels posten; (c) de leesfacade meldt een eigen concept (marker) onder het deterministische eigen id, zodat de duplicaatcheck de retry niet blokkeert (dat deed 'm wél: "Duplicaatcheck ✗" ná de eerste poging) |
| 9 | `PUT …/boekvoorstel` (project "Test Thomas") + `POST …/boeken` — **tweede poging** | **200 → `BILL/2026/06/0001`**, `state posted`, `company_id 1`, partner 160, journal 9 Purchases, `ref TEST-ODOO-KETEN-20260066`, `invoice_origin AKN:<doc>:0:boeking`, **`date 2026-06-05 = invoice_date`** (niet Odoo's maandeinde), due 2026-06-19, `amount_untaxed = amount_total = 10323.49`, tax 0,00 (verlegd: tax_ids [20] op élke regel); 9 regels: **`Huur dixi per week` = product 9261, qty 7 × 42,35 = 296,45; `Materialen ventilatie` = product 9262, qty 1 × 583,56**; overige 1 × netto zonder product; `analytic_distribution {758: 100}` op élke regel → 9 `account.analytic.line`-rijen mét `product_id`, `unit_amount` (7,0), `amount` −netto, `general_account_id`; bijlage `20260066.pdf` (159.990 B) ná posten; tijdlijn-detail `odoo_hergebruikt + odoo_concept_ververst`, `regels_met_product 2` |
| 10 | App-weergave | lijst + detail: **"Geboekt in Odoo · BILL/2026/06/0001 · Universal Steigerbouw B.V."** + vindplaats-hint met company; `tegenboek-toets`: storno geblokkeerd mét Odoo-reden ("corrigeren = creditnota (reversal)"), tegenboeken aangeboden, betaalstatus open 10.323,49 |
| 11 | `POST …/tegenboeken` (volledig, reden verplicht) | **200 → `RBILL/2026/09/0003`** `in_refund posted`, `reversed_entry_id = 3084 BILL/2026/06/0001`, `ref TB TEST-ODOO-KETEN-20260066`, marker `…:0:tegenboeking`, `date 2026-09-04` (bewust vandaag), totaal 10.323,49, `residual 0.0 paid`; origineel: `payment_state reversed`, `amount_residual 0.0`, `reversal_move_ids [3087]`; bijlage op de creditnota. App ná fix (d): **"Reversal · RBILL/2026/09/0003 ↔ BILL/2026/06/0001"** — vóór de fix viel de regel terug op de RLZ-vorm omdat de tegenboek-gebeurtenis (geboekt→geboekt) als jongste GEBOEKT-overgang gold |
| 12 | Opruimen (rechtstreeks, `write active=False`) | partner 160 en templates 9447/9448 gearchiveerd — nooit `unlink`; het TEST-paar BILL/RBILL blijft staan (norm) |
| 13 | `POST /administraties/{rlz-admin}/odoo/overstap` (ingang B, validatie) | 422 "Company 1 is al gekoppeld aan een andere administratie" — niets opgeslagen; de volledige overstap-cyclus (probe + sync) is niet live gedraaid (company 1 was al bezet) |

**Conclusie:** de adapter-keten intake → extractie → checks → boeken → bijlage → reversal is live bewezen op company 1,
inclusief BookDate = factuurdatum, cent-exacte totalen, product-regels via de catalogus-brug en `analytic_distribution`
op regelniveau. De vier gevonden gebreken (sentinel-500, gearchiveerde analytic accounts in de sync, stale concept bij
hergebruik, eigen concept in de duplicaatcheck, jongste-overgang bij tegenboeking) zijn in dezelfde run gefixt en getest.

## §8 Afrondingsrun 04-09 — Universal Verkoop als leesbron in de CLOUD (blok D, uitgevoerd) + overstap-generale (blok C2, voorbereid)

### 8.1 Blok D — company 3 als alleen-lezen leesbron (cloud-DB rlz-sql2, 04-09 19:20–19:35, strikt GET)

Via het cloud_cli-recept (Auth Proxy 5434, KMS-unwrap met de gcloud-gebruikerstoken; secrets alleen in de procesomgeving) en de
BESTAANDE CLI `odoo-leesbron` (= de motor van de Beheerder-endpoints, systeem-actor). Geen enkele write in Odoo of RLZ.

| Stap | Uitkomst |
|---|---|
| Voorstand | Universal Verkoop `0d66ff75-…` (voorraad-opt-in AAN, geen Odoo-koppeling): feitenlaag `rlz_verkoop` 3.498 regels / 1.300 facturen (02-01 t/m 01-09-2026), waarvan 1 factuur gedateerd 01-09 |
| `odoo-leesbron --company-id 3 --knip 2026-09-01` | `OK leesbron gekoppeld: company 3 (Universal Verkoop B.V.), knip 2026-09-01`; leesprobe 8/8 groen: verbinding, company, lezen res.company / account.move / account.move.line / product.product / res.partner, verkoopfacturen ok (33 geposte verkoopfacturen) |
| `voorraad-rlz-sync --volledig` (MET_AI) | RLZ vanaf 01-01: 1.304 gelezen, 1.299 verwerkt (3.497 regels), 4 concept, **1 ná de knip → opgeruimd**; Odoo company 3 vanaf 01-09: 35 gelezen, **30 verwerkt (83 regels)**, 5 niet geboekt (concept), 0 weg na annulering, **0 dubbel met RLZ** |
| Verificatie | `odoo_verkoop` 83 regels / 30 facturen, alle ≥ knip (01-09 t/m 04-09), referenties `F/2026/000nn`; `rlz_verkoop` 3.497 / 1.299, alle ≤ 31-08; overlap referenties 0; RLZ-regels ≥ knip 0. Normalisatie Odoo-regels: 66 genormaliseerd (18 artikel / 31 dienst / 17 transport) + 17 onzeker, 35 mét artikelgroep; artikelcode uit de omschrijving herkend (`[560366] Duw- en trekschoren …`). Aansluitscherm toont per regel "Odoo-verkoopfactuur F/2026/…" (`voorraadApi.ts::bronLabel`). Audit `voorraad_odoo_uitstroom_gesynct` |

Bevindingen: (1) één RLZ-verkoopfactuur gedateerd 01-09-2026 valt met de exacte knip buiten beide bronnen — Peter checkt in RLZ
welke dat is en of Odoo 'm dekt; anders knip → 02-09; (2) 5 Odoo-concepten tellen pas ná posten; (3) cloud-code en -DB stonden
op 0110 — de UI toont de leesbron direct (chip "Odoo · leesbron", rij Leesbron voorraad).

### 8.2 Blok C2 — overstap-generale ingang B: VOORBEREID (04-09 middag) → GEDRAAID + LIVE BEWEZEN 04-09 avond, zie §9.3 (het script is voor blok A/B/C1 herzien)

Testcase = de RLZ-testadministratie in de dev-DB (`faae29c5-…`, RLZ `8dbfb856-…`): 903 geheugen-observaties (2 app-bevestigd op
leverancier Action), 38 grootboekrekeningen + 11 btw-tarieven in gebruik, 4-cijferige RLZ-codes (4304 Brandstof auto, 4510, 4306, 4405 …)
tegenover Odoo's 6-cijferige codes op company 1 — de mapping-regel "code + 00" wordt daar écht getoetst. Draaiboek =
`verkenning/odoo_overstap_generale.py` (9 stappen, stop-op-fout, log `output/odoo_overstap_generale_<datum>.jsonl`, key geredigeerd):

0 voorwaarden → 1 nulmeting geheugen Action (RLZ-UUID's) → 2 RLZ-leg VÓÓR de overstap (TEST-PDF, voorstel op het geheugen-gb, boeken in de
RLZ-TESTadministratie mét TEST-referentie, storno actie 19) → 3 `POST …/odoo/overstap/voorbereiden` + mapping (voorstel; rijen zonder
voorstel = gelogde generale-keuze) → 4 `POST …/odoo/overstap` (overgangsdatum 01-09-2026) → 5 geheugen Action NÁ = gemapte Odoo-rekening,
`app_bevestigd` gelijk (assert) → 6 Odoo-leg (TEST-crediteur, factuurdatum 03-09, BILL op company 1, tegenboeken → RBILL) → 7 document
vóór de overgangsdatum → leesbare weigering (adapter-poort; assert) → 8 C1 live (01-10 → 409, terug → 200) → 9 opruimen (partner
archiveren, nooit unlink).

**Blokkade:** company 1 hangt in de dev-DB aan de dev-Odoo-administratie van het ketenbewijs (`fa3f83ae-…`); `_gekoppelde_companies`
telt koppeling-rijen én sentinel-dragers (bewust, bug (a) 04-09) → overstap = 422 "company 1 is al gekoppeld". Vrijmaken = dev-hygiëne
(archiveren + sentinel `…:1:generale-04-09-vrijgemaakt` + koppeling-URL `vrijgemaakt-generale-04-09.invalid`; rijen blijven bestaan) —
deze dev-DB-mutatie weigerde de permissie-classifier van de sessie tweemaal → **klikpunt Peter**: het script staat in de scratchpad
(`dev_company1_vrijmaken.py`, inhoud hieronder), daarna `cd backend && .venv/bin/python ../verkenning/odoo_overstap_generale.py` met
uvicorn op :8011 (dev-DB ≥ 0111).

```python
# dev_company1_vrijmaken.py — dev-DB `boekhouding`, NIET de cloud; niets verwijderd
AID = uuid.UUID("fa3f83ae-979c-4e84-851c-62b980390fe0"); BEHEERDER = uuid.UUID("2f2262cd-0423-4910-b7b5-335ba37a6ef5")
with scoped_session(None, actor_id=BEHEERDER) as s:
    a = s.get(Administratie, AID); k = s.get(OdooKoppeling, AID)
    if a.rlz_admin_id == "odoo:universal-steigers.odoo.com:1":
        a.rlz_admin_id = "odoo:universal-steigers.odoo.com:1:generale-04-09-vrijgemaakt"
        a.naam += " — gearchiveerd 04-09 (company 1 vrijgemaakt voor de overstap-generale)"
        a.actief = False; a.gearchiveerd_op = datetime.now(UTC); a.gearchiveerd_door = BEHEERDER
        if k is not None: k.odoo_url = "https://vrijgemaakt-generale-04-09.invalid"
```

**Open beslispunt (raakt de opdrachtformulering "document vóór de datum boekt RLZ"):** ná de overstap draagt `rlz_admin_id` het
Odoo-sentinel; een pre-datum-document wordt door de adapter-poort leesbaar geweigerd (beslispunt 3 blok E) en kan vanuit de app niet meer
in RLZ geboekt worden. Datum-ROUTER (boeken via `rlz_admin_id_voor_overstap`) = aparte bouwopdracht; zie BESLISSINGEN blok C2.


## §9 Odoo-slotstuk 04-09 — lock-date-gedrag (A2), knipcheck Universal Verkoop (C3) en de overstap-generale (blok D)

### 9.1 A2 — wat doet Odoo met een inkoopfactuur gedateerd in een afgesloten (aangegeven) periode? LIVE, company 1 (04-09 20:11)

Company 1 draagt `fiscalyear_lock_date = tax_lock_date = 2025-12-31` (purchase/hard lock leeg). Twee TEST-facturen (partner 165
"TEST-ODOO-A2 Lockdate-leverancier", € 100 + 21 %, rechtstreeks via de client — geen app-pad; log
`verkenning/output/odoo_a2_lockdate_2026-09-04.jsonl`):

| # | Ingestuurd | Odoo ná `action_post` | Btw-regel gedateerd |
|---|---|---|---|
| A | `invoice_date = date = 2025-12-15` (≤ beide lock dates) | **niet geweigerd** — `date` STIL verschoven naar **2026-01-31** (het maandEINDE ná de lock date, niet lock + 1), `invoice_date` blijft 15-12-2025 → `BILL/2026/01/0001` | 31-01-2026 |
| B | `invoice_date = 2025-12-15`, `date = 2026-01-01` expliciet | geaccepteerd zoals ingestuurd → `BILL/2026/01/0002` | 01-01-2026 |

Opruiming: beide gereversed via de `account.move.reversal`-wizard (`RBILL/2026/09/0004` ↔ 0001, `RBILL/2026/09/0005` ↔ 0002,
origineel `payment_state reversed`, restant 0); partner 165 gearchiveerd. Niets verwijderd. NB `_reverse_moves` is een private
methode (403 via JSON-2) — de wizard is de enige route (zoals de adapter al doet).

**Conclusie + ontwerpbesluit (opdracht A2: "btw nooit stil in een al aangegeven periode; zelfde semantiek als RLZ's
TaxSource-verschuiving"):** Odoo doet het WEL automatisch, maar (a) stil en (b) naar het maandeinde ná de lock — voor een
lock op 31-12 landt de btw dus op 31-01 i.p.v. op de eerste open dag. Daarom bepaalt de adapter de boekdatum zelf,
deterministisch (`app/odoo/fouten.py::bepaal_boekdatum`): factuurdatum ≤ een lock date → `date` = hoogste geraakte lock date
+ 1 dag (= eerste dag van de eerstvolgende open periode, RLZ-semantiek), `invoice_date` blijft de factuurdatum, en de
verschuiving is ZICHTBAAR (tijdlijn-detail `boekdatum_verschoven`, regel op "Geboekt in Odoo", chip). Post-write leest de
adapter `date` terug — een afwijking is een waarschuwing op de boeking (de boeking stáát). De tegenboeking (reversal, boekdatum
vandaag) houdt de bestaande lock-date-WEIGERING. Accountants-nuance voor de Universal-overstap: zet in Odoo de
`tax_lock_date` op de laatste periode die vanuit RLZ is aangegeven — dan landt de btw van élke nakomer automatisch en zichtbaar
in de eerstvolgende open Odoo-periode (klikpunt Peter).

### 9.2 C3 — knipfactuur-check Universal Verkoop (cloud, strikt read-only, 04-09 20:22)

Recept: Auth Proxy 5434 + `cloud_env.sh MET_ODOO=1`, RLZ `GET SalesInvoices` mét `$filter=Date ge 2026-09-01T00:00:00Z and Date lt
2026-09-02T00:00:00Z` op de administratie Universal Verkoop (`0d66ff75-…`, leesbron company 3, knip 01-09-2026), Odoo read-only client.

| Bron | Uitkomst |
|---|---|
| RLZ, Date = 01-09-2026 | precies één: **50212299** (Bots Bouwgroep B.V., Date = BookDate 01-09, Status 2, € 3.257,93 excl.); ná 01-09: 0 |
| Odoo company 3, 25-08 t/m 02-09 | F/2026/00002 (27-08, SMA BV), F/2026/00003 (31-08, Berghege), **vijf op 01-09**: F/2026/00004 (Bots Bouwgroep, € 465,00 excl., S00041) t/m 00008, daarna 02-09 e.v. |
| Match 50212299 ↔ Odoo | geen: de enige Bots-Bouwgroep-factuur in Odoo is F/2026/00004 met een ander bedrag → **50212299 staat alleen in RLZ** |

**Bevinding:** de premisse van de opdracht ("óf in Odoo, óf alleen in RLZ → knip 02-09") houdt niet — op 01-09 hebben BEIDE
systemen echte facturen. Knip → 02-09 zou de RLZ-factuur binnenhalen maar de vijf Odoo-facturen van 01-09 uit de
voorraad-aansluiting stoten (de Odoo-route leest ≥ knip); de huidige knip 01-09 mist de ene RLZ-factuur. De knip is daarom
NIET gewijzigd. Voorstel (beslispunt Peter, BESLISSINGEN "ODOO-SLOTSTUK 04-09" blok C3): de Odoo-leesroute knip-onafhankelijk
naar beneden (alle geposte Odoo-verkoopfacturen tellen — ander systeem; de referentie-dedup tegen RLZ blijft) en de knip alleen
als RLZ-bovengrens → knip 02-09 + `voorraad-rlz-sync --volledig`. Dan tellen óók F/2026/00002 (27-08) en 00003 (31-08) mee —
vraag: zijn die twee echt en níét óók in RLZ geboekt?

### 9.3 Blok D — overstap-generale ingang B: LIVE BEWEZEN (dev-omgeving, 04-09 20:52–20:59)

Draaiboek `verkenning/odoo_overstap_generale.py` (herzien voor blok A/B/C1: 9 stappen, stop-op-fout, `--vanaf-stap`/`--ref-rlz`/
`--vendor-odoo` voor een hervatting) via de eigen HTTP-API (uvicorn :8011, dev-DB ná migratie 0113, Beheerder-token). Log
`verkenning/output/odoo_overstap_generale_2026-09-04.jsonl` (gitignored; API-key geredigeerd). Vooraf (dev-hygiëne, niets verwijderd):
company 1 vrijgemaakt (dev-administratie `fa3f83ae` gearchiveerd + sentinel/URL onherkenbaar), klant-accordering van de testadministratie
UIT gezet via de API (3 lopende TEST-rondes zichtbaar vervallen — anders weigert stap 2 "bied ter accordering aan") en de Beheerder als
eigenaar gezet (anders weigert de auto-afvoer zichtbaar met "Deze administratie heeft geen eigenaar" — audit `duplicaat_afvoer_geweigerd`).
Testcase: RLZ-testadministratie `faae29c5-…` (RLZ `8dbfb856-…`), leverancier Action mét 2 app-bevestigde observaties.

| # | Stap | Uitkomst |
|---|---|---|
| 0 | voorwaarden | `/health` 200; `verbinding-testen`: company 1 `al_gekoppeld: false` |
| 1 | nulmeting geheugen Action | gb `4104 Energiekosten (gas/elektra)` (RLZ-UUID, `app_bevestigd: true`, gesplitste stem), btw `NL, Hoog Tarief` 21 % |
| 2 | RLZ-leg VÓÓR de overstap | TEST-PDF mét btw-nummer `NL812345678B01` + RLZ-project → boekvoorstel op het geheugen-gb → **geboekt in RLZ `RLZ-04-00002044`** (`22e3ad56-…`) → storno actie 19 = 204, Status 1 (opruiming; app-status blijft geboekt = de historie voor stap 7b) |
| 3 | `voorbereiden` | telling grootboek 38 (12 mét voorstel: 4 `zelfde_code`… en `code_verlengd`), btw 11 (3 `tarief`), **project 1 (0 voorstel — geen nummer in "TEST-ROUTE-A Pand Dorpsstraat 1")**; 355 Odoo-rekeningen, 17 taxen; generale-keuzes gelogd (26 gb handmatig = dichtstbijzijnde code×100, 8 btw handmatig, project → "Test Thomas" handmatig) |
| 4 | `overstap` (kanteldatum 01-09-2026, mapping gb/btw/project) | **201**; sync ledgers 355 / taxrates 17 / vendors 6 / projects 3 (RLZ-rijen verdwenen 342/22/209/1); stand: company 1, `rlz_admin_id_voor_overstap = 8dbfb856-…`; **hervertaling: 6 open documenten / 6 regels, grootboek 6 · btw 6 · project 1 vertaald, 0 leeg**; `projecten_aangemaakt 0` |
| 5 | geheugen Action NÁ | gb = **`411000 Property rental`** (de gemapte Odoo-rekening, `app_bevestigd: true` ongewijzigd), btw = Odoo `21%`, **project = Odoo "Test Thomas"** (mapping v1 handmatig) — assert ok; 5b: 6 regels dragen `overstap_vertaling` (bv. `4104 → 411000`, `NL, Hoog Tarief → 21%`) |
| 6 | Odoo-leg (factuurdatum 03-09) | **eerste twee pogingen 502** "account.tax ade43b00-… is niet bekend in de Odoo-koppeling" — adapterbug: `_verlegde_taxrates` nam de VERDWENEN RLZ-verlegd-tarieven mee (dragen geen Odoo-id); gefixt (alleen niet-verdwenen rijen, regressietest `test_basis.py::TestVerlegdeTaxratesNaOverstap`); daarna **`BILL/2026/09/0002`** posted (date = invoice_date 03-09) → tegenboeken → **`RBILL/2026/09/0006`**, app "Reversal · RBILL/2026/09/0006 ↔ BILL/2026/09/0002" |
| 7a | nakomer factuurdatum 20-08 (< kanteldatum) | **boekt gewoon in Odoo: `BILL/2026/08/0002`** (date 20-08) → reversal `RBILL/2026/09/0007` — geen poort meer (blok A) |
| 7b | nakomer = de RLZ-leg (zelfde btw-nummer/referentie/bedrag, Odoo-crediteur) | **Duplicaatcheck rood: "1 factuur … al geboekt in Reeleezee vóór de overstap (boekstuk RLZ-04-00002044)"** (uit de eigen DB-historie, geen RLZ-call); ná het zetten van de eigenaar **automatisch afgevoerd bij binnenkomst**: status `afgewezen`, reden "Duplicaat van TEST-GENERALE-RLZ-… (boekstuk RLZ-04-00002044 / document test-generale-rlz.pdf van 2026-09-04, al geboekt)", systeem-actor |
| 7c | nakomer factuurdatum 15-12-2025 (≤ tax_lock_date 31-12-2025) | **`BILL/2026/01/0003` mét `date 2026-01-01`, `invoice_date 2025-12-15`**; app "boekdatum 01-01-2026 · factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode" → reversal `RBILL/2026/09/0008` |
| 8 | kanteldatum 01-09 → 01-10 → 01-09 | **200 / 200** (geen 409 meer; audit oud→nieuw 2×) |
| 9 | opruimen | TEST-crediteur (partner 168) gearchiveerd; de crediteuren van de twee gestrande runs (166, 167) achteraf óók; twee gestrande stap-6-documenten staan in de dev-testadministratie op `boeken_mislukt` mét de leesbare 502-reden (dev-data) |

**Conclusie:** de overstap-keten ingang B is live bewezen — mapping gb/btw/project → kanteldatum → hervertaling open voorstellen →
geheugen draagt gemapte rekening én project → Odoo-boeking ná én vóór de kanteldatum → dedup over de backend-grens mét auto-afvoer →
boekdatum-verschuiving bij een afgesloten periode → kanteldatum vrij te wijzigen. Eén adapterbug gevonden en gefixt in de run (stap 6).
TEST-paren op company 1 (norm: blijven staan): BILL/2026/09/0002 ↔ RBILL/2026/09/0006, BILL/2026/08/0002 ↔ RBILL/2026/09/0007,
BILL/2026/01/0003 ↔ RBILL/2026/09/0008 (+ de A2-paren uit §9.1). De dev-testadministratie draait sindsdien op Odoo (company 1).
De echte Universal-Steigerbouw-overstap volgt uitsluitend op een expliciete GO van Peter.
