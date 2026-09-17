# Rapport 17-09 (inbox-run) — VGG → Odoo, run 2 blok 11: pand = RLZ-project — STAP-0 dekking (lees-only) + instrument in de replay + pandenregister op projectsleutel

Opdracht: `opdrachten/gedaan/2026-09-17-vgg-blok-11-pand-uit-rlz-project.md`. Lees-only, geen RLZ-/Odoo-writes; migratie 0155
(afsluitroutine gedaan). **Werkt in productie: STAP-0-samples ja (rlz-lezen op de job-image, 17-09 ~12:30–12:50); volledige
dekking niet gemeten (instrument draait pas ná deploy in `vgg-replay`, nameting-onderdeel `c`); `--bron project` niet gemeten.**

## Blok A — STAP-0 lees-only (Vastgoedgroep, geanonimiseerd)

| Meting | Bron | Uitkomst |
|---|---|---|
| Projecten | `rlz-lezen --pad Projects --count` | **83, alle actief**; naam = adres (`<Straat> <nr> te <Plaats>`, initialen "B.4.T.A." ↔ "Bornholmstraat 49 Almere"); geen codeveld |
| Project op inkoopregel | documentvorm `PurchaseInvoices/{id}` RLZ-04-00000887 (15-09-2026, € 1.595,00) | 1 regel op **4200 mét Project** `aabcd3b8…` (= project B.4.T.A.) |
| Project op bank-direct memoriaal | documentvorm `ManualJournals/{id}` RLZ-28-00000061 (07-11-2025, € 135.000,00) | regels **1603 + 1001, Project `null`** op beide |
| Project op journaalregels | `JournalEntryLines?$expand=Account,Project,JournalEntry` (2.303 regels 2026) | 200, **geen Project-property** (expand stil genegeerd) |
| Project op bankmutaties | `PaymentTransactions` recordvorm | **veld afwezig** |
| Collectie-expand regels | `PurchaseInvoices?$expand=Entity,DocumentLineList(…)` / `ManualJournals` / `SalesInvoices` | 200 zónder regels (stil genegeerd, = STAP-0 13-09) → volledige dekking = documentvorm per document = replay |

Duiding: het project staat op de REGEL van facturen; de bankkant (aanbetalingen/notaris-ontvangsten als bank-directe memorialen) draagt
geen project. Verwachting voor de volledige meting: hoge dekking op inkoop-/verkoopregels, lage op 1405/16xx — precies de groep die het
pandenmodel voor aanbetalingen gebruikt. 83 projecten ↔ 94 adres-clusters: de clusters zijn versnipperd, niet de projecten.

## Instrument (blok A) — `app/migratie/project_dekking.py` in `vgg-replay`
Per DocumentType en grootboekgroep (pand-relevant = 7000 aankoop · 8xxx opbrengst · 1405 aanbetalingen · 46xx/70xx vaste lasten &
kosten) regels totaal/mét project/aandeel; lijst regels zonder project op pand-relevante rekeningen (boekstuk, type, rekening, bedrag);
Project-veld op bank; kruistoets project ↔ adres-cluster. Meetlat ≥ 90 % → oordeel in het rapport (markdown + JSON `project_dekking`).
Tests 4.

## Blok B — datalaag + `--bron project` (migratie 0155)
`pand.rlz_project_id` (uniek per administratie) + `rlz_project_naam`, herkomst `rlz_project`; `pandenregister-afleiden --bron project`:
Projects lezen, regels van álle documenten binnen het regelbudget (buiten budget zichtbaar geteld), pand per project (adres-code uit de
projectnaam waar parseerbaar → valt samen met een bestaand adres-pand), koppeling zekerheid hoog mét soort uit de grootboekregel
(7000/8xxx/1405), Overhead = geen pand, documenten zonder project → adres-terugval + signaal "koppel in Toewijzing of codeer in RLZ",
bankmutaties altijd via de terugval; schrijven idempotent, mens wint, project-pand verliest zijn sleutel nooit; `pand_per_document`
levert het project-pand aan de replay. **Default blijft `adres`** tot de meting ≥ 90 % toont. Tests 3 (+ bestaande panden/replay 340 groen).

## Migratie 0155 (afsluitroutine)
`alembic upgrade head` dev-DB: `Running upgrade 0154 -> 0155` · `alembic check` schoon · dump ververst (head 0155) · live-200: er is
geen HTTP-route die `pand` leest (CLI-module); het geraakte pad is de CLI/service tegen de gemigreerde test-DB (tests groen).

## Klikpunten Peter
Geen — de lijst "regels zonder project" komt uit de replay-meting ná deploy (mét boekstuk, rekening, bedrag).

## Beslispunten (default gekozen — `2026-09-17-beslispunten-peter.md` opdracht 5)
1. Default `--bron adres` tot de meting (opdracht: "default project zodra blok A groen").
2. Per-pand-sluitcontrole op projectbasis niet gebouwd: `JournalEntryLines` kent geen Project → over documentregels, ná de meting.
3. Pand-relevante groepen = 7000 / 8xxx / 1405 / 46xx-70xx (blok 7c-model); 10xx en overig tellen niet in de meetlat.
4. Meerdere projecten op één document → koppeling aan élk project (zichtbaar in de reden), nooit raden.

## Meetrecept (werkt in productie: ja/nee)
1. `gh workflow run nameting -f onderdeel=c` → `verkenning/nameting-vgg-replay-<dd-mm>.txt` sectie "Project-dekking" (aandeel pand-relevant, tabellen, regels zonder project, kruistoets).
2. `scripts/gcp/nameting.sh pandenregister-afleiden --administratie Vastgoedgroep --bron project --dry-run` → ≈ 83 panden, lijst ZONDER PROJECT.
3. Dekking ≥ 90 % → default omzetten (vervolg-opdracht); < 90 % → beslispunt Peter (coderen in RLZ vs adres-terugval).
