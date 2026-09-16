# Rapport 16-09 (avond) — VGG → Odoo, run 2 blok 9: SCHRIJF b = het 1001-model in de replay + vierde meting (géén Odoo-writes)

**In gewone taal:** een memoriaal dat in Reeleezee rechtstreeks op de bankrekening 1001 boekt, telde in het Odoo-doelmodel dubbel: de
bankregel (statement line) voedt de bank al, en de memoriaalregel deed dat nog eens. De replay legt nu per zo'n regel vast of hij
één-op-één tegenover een bankmutatie staat. Zo ja: de regel gaat naar de "outstanding"-rekening van het bankdagboek en de bankregel
lettert daartegen af — de bank telt dan één keer. Zo nee: de regel blijft op de tussenrekening mét de reden erbij (geen mutatie binnen
drie dagen, of twee kandidaten waaruit een mens moet kiezen). Elk verschil dat in de vier afletter-groepen overblijft krijgt een
benoemde categorie mét regel — nooit meer "onverklaard".

**Opdracht:** `opdrachten/gedaan/2026-09-16-vgg-schrijf-b-1001-model.md`. Geen migratie, geen RLZ-/Odoo-writes.
**Werkt in productie: niet gemeten** — de code staat vóór de deploy en de gcloud-sessie is verlopen (`gcloud auth print-access-token`
faalt op `info@vastly.software`); de vierde meting staat als vervolg-opdracht `opdrachten/inbox/2026-09-17-vgg-vierde-meting-na-deploy.md`.

## Blok A — 1001-model (GEBOUWD, lees-only, `backend/app/migratie/model_1001.py`)

| Stap | Regel |
|---|---|
| Selectie | memoriaalregel op een RLZ-bankgrootboek: tabelcode 1001 (`rekening_mapping`, doel `bank_statement_lines`) of een Ledgers-rij mét `UseForPaymentAccount`; bedrag = debet − credit (debet ↔ mutatie +) |
| Bewijs 1 | `PaymentReferenceList` van de mutatie wijst naar het memoriaal, zelfde tekenrichting, cent-exact; gelijke kandidaten worden alleen gepaard als het memoriaal evenveel gelijke 1001-regels heeft (datumvolgorde), anders meerduidig |
| Bewijs 2 | alleen als bewijs 1 leeg is: vrije mutaties (geen reconcile, geen directe tegenregels), zelfde richting, cent-exact, \|Δ datum\| ≤ 3 d; precies één = gekoppeld; een mutatie wordt nooit twee keer geclaimd |
| Gekoppeld | regel → outstanding-/suspense-rekening BNK1 (echte Odoo-id via de 1012-resolutie; anders pseudo-sleutel `impliciet:outstanding-bnk1` + LET-OP "KLIKPUNT PETER", `account_id` None — nooit de bankrekening zelf); tegenregel van de statement line gaat van tussenrekening naar diezelfde sleutel, `bank.reconcile` draagt `via_outstanding` + bewijs |
| Geen kandidaat | tussenrekening, reden "geen bankmutatie binnen ± 3 d" |
| Meerduidig | niet toegewezen, eigen teller, tussenrekening, reden noemt de kandidaat-mutaties |
| Balansguard | debet/credit van de regel veranderen niet — "memoriaal uit balans" blijft ROOD-bepalend (test) |
| Rapport | sectie "1001-model (blok 9, SCHRIJF b)": tellers + tabel per regel (boekstuk, regel, datum, bedrag, uitkomst, bestemming, bewijs, mutatie + datum, Δ dagen, kandidaten, reden); JSON `model_1001`; statusregel "… 1001-model n gekoppeld / m zonder mutatie / k meerduidig" |
| Groepstoets | per groep `rest[]`: crediteuren/debiteuren = afletterstand (SCHRIJF c); tussenrekening = 1001 zonder mutatie (n×) / 1001 meerduidig (n×) / open bankmutaties (n×) / restant afletterstand; bank = open bankmutaties / 1001-rest (RLZ wél op 1001) / restant "RLZ-opruimpunten / afletterstand" mét de drie opruimpunten; Σ categorieën = groepsverschil |

Verwachting voor de vierde meting: bank- en tussenrekeninggroep 0,00 óf mét benoemde rest; debiteuren/crediteuren blijven rood tot
SCHRIJF c. Het rapport benoemt ook het KLIKPUNT (outstanding-rekening BNK1 nog niet ingesteld — stand 15-09).

## Blok B — bewijspaar buiten juli 2025 (recept voor SCHRIJF c, NIET uitgevoerd)

Gekozen (lees-only, uit `verkenning/nameting-vgg-replay-15-09.txt`, regel "Niet vertaalbaar"): **RLZ-01-00000082** — verkoopfactuur
2026-03-19, € 400.000,00, Ouwerkerk Notariaat (partner uit de gekoppelde bankmutatie), grootboek 8000 "Omzet verkopen".

| Onderdeel | Verwachte Odoo-vorm (company 6) |
|---|---|
| Partner | `res.partner` "Ouwerkerk Notariaat" — zoek-vóór-create op naam (+ IBAN uit de bankmutatie), nooit een dummy |
| Factuur | `account.move` `out_invoice`, dagboek F (48), `invoice_date`/`date` 2026-03-19, `ref` kaal `RLZ-01-00000082`, `invoice_origin` = `mig:<anker>` (UUIDv5), één regel `price_unit` 400.000,00, `account_id` = RJ-220-rol `opbrengst_panden` **803100 (id 3608)** via de rol-herclassificatie van de koopsom-regel (op 15-09 stond 8000 nog als "grootboek zonder Odoo-rekening" op documentniveau — de vierde meting moet laten zien dat de rol 'm dekt), `tax_ids` [] (VGG niet btw-plichtig), analytic = pand-code uit Toewijzing |
| Statement line | `account.bank.statement.line` op BNK1 (53), `amount` +400.000,00, `date` = mutatiedatum, `payment_ref` = ontknipte omschrijving, `unique_import_id` = `mig:<anker mutatie>`, partner idem |
| Reconciliatie | statement line ↔ debiteuren-regel van de factuur (rekening debiteuren van company 6); open 0 → post `Closed` |
| Pand | verkoop-regel → pand via Toewijzing; kostprijs verkochte panden 701300 = apart RJ-220-memoriaal (voorraad → kostprijs), geen onderdeel van dit paar |
| Open punten | pand-code niet op documentniveau in het 15-09-rapport; IBAN op BNK1 nog leeg (12-09); outstanding-rekening = KLIKPUNT |

## Blok C — vierde meting: NIET GEMETEN

- `gcloud auth print-access-token` faalt (sessie verlopen) → geen enkele productie-lezing mogelijk in deze run; bovendien staat de code
  vóór de deploy (push via de Stop-hook). Vervolg-opdracht `opdrachten/inbox/2026-09-17-vgg-vierde-meting-na-deploy.md`: stap 0 gcloud +
  deploy-check service = jobs, dan `scripts/gcp/vgg_blok7_nameting.sh c` → `verkenning/nameting-vgg-replay-<dd>-09-cc.txt` (suffix `-cc`),
  regels tellen tegen de JSON (eerste echte meting van `print_gedoseerd`), oordeel in drie standen.
- Meetlat: ROOD alleen nog op debiteuren/crediteuren (afletterstand, SCHRIJF c); tussenrekening + bank 0,00 of mét benoemde rest; sectie
  "1001-model" mét tellers > 0. Wijkt het af: rapport, geen doorrekenen.

## Klikpunten Peter vóór SCHRIJF c (checklist)

1. Outstanding-payments-rekening op BNK1 instellen (Boekhouding › Dagboek BNK1 › Uitgaande betalingen › Outstanding-rekening) — dan
   mapt 1012 zichzelf én krijgt het 1001-model een echte rekening (nu pseudo-sleutel + KLIKPUNT). Kent BNK1 ook een aparte Outstanding
   Receipts: melden (beslispunt 3).
2. IBAN op BNK1 (laatste lezing 12-09: leeg).
3. RLZ-opruimpunten: RLZ-01-00000006 (concept), dubbel € 135.000 RLZ-28-00000061/062, bankregel "test".
4. gcloud opnieuw inloggen zodat de vervolg-opdracht kan meten.

## Testbeeld
- `tests/migratie/test_model_1001.py` (13 tests: bewijs 1, bewijs 2 Δ 2 d, geen kandidaat, meerduidig, tekenrichting, balansguard, groepstoets
  bank/tussenrekening als spiegelbeeld mét Σ rest = verschil, pseudo-sleutel nettoot, outstanding bekend, mini-VGG ongewijzigd GROEN,
  markdown/JSON/statusregel); `test_blok7d.py` STAP-0-fixture mét de twee bankmutaties (bank op groepsniveau); `test_rekening_mapping.py`
  tekst. Uitkomst tests/migratie + docs-guards: zie het slotrapport `2026-09-16-inbox-afgewerkt-3.md` (tijdens deze run draaide een
  tweede CC-proces de test-DB opnieuw op, waardoor losse runs sporadisch "schema platform does not exist" gaven; de herhaalde run is de
  maatstaf). Ruff schoon op de eigen bestanden.

## Beslispunten
Zie `docs/rapporten/2026-09-16-beslispunten-peter.md` — opdracht 13.
