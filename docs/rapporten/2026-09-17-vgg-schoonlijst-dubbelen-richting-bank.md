# Rapport 17-09 (inbox-run) — VGG schoonlijst: dubbel = richting + tegenrekening + bankbevestigd; RLZ-01-00000006 en bankregel "test" herleid mét bron

Opdracht: `opdrachten/gedaan/2026-09-17-vgg-schoonlijst-dubbelen-richting-en-bank.md`. Lees-only, geen RLZ-/Odoo-writes, geen migratie.
**Werkt in productie: blok A niet gemeten (schoonlijst-CLI draait pas ná deploy op de job-image); blok B en C JA — gemeten met
`scripts/gcp/nameting.sh rlz-lezen` op de gedeployde job-image (17-09 ~11:45–12:10, geanonimiseerde uitvoer).**

## Blok A — dubbel-toets herzien (`app/migratie/schoonlijst.py`, `bankdekking.py`)
Wortel: `teken_van(ManualJournals, BaseInvoiceAmount)` gaf voor béide memorialen +1 (documentbedrag altijd positief) → één inkomende
mutatie voor "twee boekingen" → "dubbel"; richting/tegenrekening zaten niet in de toets, regels werden nooit gelezen.
Nu: groep ± 3 d; `Profiel` (richting + tegenrekening(en) mét zijde) uit de REGELS via de documentvorm (blok 7c), alleen voor
kandidaten, gecachet; ongelijk profiel → "zelfde bedrag, verschillend kenmerk (bij · 1603/C vs af · 1602/D) — geen dubbel";
bankdekking mét de richting uit de regels; memoriaal mét bankregel = bankbevestiging verplicht; élke rij draagt `bank_regels`
(datum, bedrag, richting, tegenpartij-initialen, id8) + `bank_toets`. Tests: casus 00000061/062 → géén kandidaat; gelijk profiel
2 boekingen/2 mutaties → bank-bevestigd mét beide bankregels; 2/1 → kandidaat mét de ene bankregel; bank niet gelezen → kandidaat
mét "bankbevestiging verplicht". Suites: schoonlijst 60 + bankdekking + bank_toets + rlz_dubbel(snede2) — 204 groen.

## Blok B — RLZ-01-00000006 herleid (bron: `rlz-lezen` op Vastgoedgroep, 4 collecties, filter `ReceiptNumber eq 'RLZ-01-00000006'`)

| Veld | Uitkomst |
|---|---|
| Collectie | **Receipts** (SalesInvoices, PurchaseInvoices, ManualJournals: 0 treffers) |
| RLZ-id | `e37e36fb…` (geanonimiseerd tot 8 tekens; volledig id via `rlz-lezen` zonder anonimisering is er bewust niet) |
| Type / status | DocumentType 10 (verkoop) · **Status 1 = concept** |
| Datum / bedrag | **2025-08-13** · BaseInvoiceAmount **€ 43.666,14** · BookDate leeg (concept) |
| Omschrijving | "Overdracht Rijswijkseweg 409 te Den Haag, ons dossier: 2025.0787 58.01" (notaris-afrekening) |
| Relatie | geen Entity |
| Duiding | = het "01-06 Rijswijkseweg"-concept uit de kopie-lijst van 12-09 (concept náást een geboekt exemplaar) — geen systeemhuls |

## Blok C — bankregel "test" herleid (bron: `rlz-lezen PaymentTransactions`, filter Reference/Name bevat test, `$expand=PaymentAccount,PaymentReferenceList($expand=Document)`, `$count=true`)

| Veld | Uitkomst |
|---|---|
| Aantal treffers | **1** (`@odata.count` 1) |
| Mutatie-id | `aa06acac…` |
| Datum / bedrag | **15-08-2026** · **€ −1,00** · OpenAmount −1,00 (**niet afgeletterd**), IsComplete false |
| Tegenpartij | initialen **J.K.E.O.** = "J. Koppe en/of W.L.J.F. Koppe" — Peters vermoeden klopt letterlijk; tegen-IBAN …4533 |
| Rekening | ING …9295 (V.N.B.), Type 1 |
| Omschrijving | "test" |
| Koppeling | alleen de RLZ-systeemhuls RLZ-09-00001092 (DocumentType 19, IsSystemGenerated, concept) |
| Duiding | testoverboeking van € 1,00 die nog open staat; géén dubbel, géén modulefout |

## Klikpuntenlijst SCHRIJF c — herschreven (regel Peter 17-09: bron-id + datum + bedrag + link/citaat, anders niet opnemen)
1. **Bankregel "test"** — mutatie `aa06acac…`, 15-08-2026, € −1,00, open, J. Koppe en/of W.L.J.F. Koppe, ING …9295 (citaat `rlz-lezen` 17-09 hierboven): boeken (bankkosten/privé) of terugboeken in RLZ — Peters keuze.
2. **RLZ-01-00000006** — Receipt-concept `e37e36fb…`, 13-08-2025, € 43.666,14, "Overdracht Rijswijkseweg 409" (citaat `rlz-lezen` 17-09): kopie van de geboekte overdracht? Beoordelen in RLZ; verwijderen doet alleen een mens.
3. **IBAN BNK1 (Odoo company 6)** — ongewijzigd uit `docs/rapporten/2026-09-16-vgg-schrijf-b.md` (geen RLZ-object; Odoo-instelling).
Ingetrokken: "dubbel € 135.000 RLZ-28-00000061/062" (bevestigd géén dubbel: ontvangst Midden Nederland 1603 ↔ 1001 en betaling Tupker Beheer 1602 ↔ 1001, 07-11-2025, `verkenning/nameting-vgg-replay-13-09.txt` r.1105–1106).

## Beslispunten (default gekozen — `2026-09-17-beslispunten-peter.md` opdracht 4)
1. Snede 2 (`rlz_dubbel.py`): tegenrekening-toets NIET gebouwd (richting is bij inkoopfacturen per definitie gelijk; regels per paar over álle administraties = webfilter-risico). Alternatief: alleen voor de clusters "waarschijnlijk dubbel" regels lezen.
2. Bankrekening-herkenning in memorialen op RGS-groep 10xx (1001 bank, 1011/1012 kruisposten/onderweg, 1000 kas). Alternatief: PaymentAccounts-grootboekkoppeling lezen.
3. Profiel-split gebeurt NA de kenmerk-split (adres/nummer) — een ongelijk profiel wint altijd, ook bij gelijk kenmerk.

## Meetrecept blok A (ná deploy)
`scripts/gcp/nameting.sh migratie-schoonlijst --administratie Vastgoedgroep` → 00000061/062 onder "zelfde bedrag, verschillend
kenmerk" mét "richting/tegenrekening verschilt"; élke dubbel-rij mét `bank_regels` + `bank_toets`; `regels_niet_gelezen` = 0.
