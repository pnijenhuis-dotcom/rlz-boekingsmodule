uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-vgg-schrijf-c-na-deploy.md

# OPDRACHT 17-09 — VGG → Odoo: SCHRIJF c ná deploy (bewijspaar RLZ-01-00000082 posten + reconcilieren) en de zesde meting (project-dekking)

Domeinen: vgg-odoo-migratie

Vervolg op `docs/rapporten/2026-09-17-vgg-vijfde-meting-en-auto-posten.md` (aanvulling Peter 17-09 "1 boeking testen, dan alles definitief").
**Schrijvend op company 6 — alleen via `scripts/gcp/vgg_blok7_odoo_writes.sh` op de gedeployde job-image; nooit via nameting.sh.**

## Stap 0
- Deploy van de commits van 17-09 (`--boekstuk` op `vgg-odoo-stap0`, `vgg-odoo-migratie`, Project in de document-vorm-expand) groen; service = jobs
  (`deploy_check` in het script).
- `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"` (bron-key; Universal Steigerbouw heeft in productie geen Odoo-koppeling).

## Stap 1 — plan (dry-run, lees-only)
- `scripts/gcp/vgg_blok7_odoo_writes.sh plan` → `vgg-odoo-stap0 --dry-run --boekstuk RLZ-01-00000082`: paar = "out_invoice RLZ-01-00000082 ↔ N bankregel(s)",
  stap 4 toont de IBAN-stand op BNK1 (KLIKPUNT Peter als leeg → stoppen, melden); `vgg-odoo-migratie --dry-run`: plan-tellers (documenten, bankregels,
  zonder partner, pand-eis afwijkingen).
- Zesde meting: `gh workflow run nameting -f onderdeel=c` → sectie "Project-dekking" nu mét `Project` (aandeel pand-relevant, ≥ 90 % = beslispunt "default
  `--bron project`"); kolom "RJ-220-tegenzijde → rol" controleren (vijfde meting: 0 van 164 gevuld terwijl de herclassificatie wél op 133/3180 landt).

## Stap 2 — SCHRIJF c (mét IBAN op BNK1)
- `scripts/gcp/vgg_blok7_odoo_writes.sh SCHRIJF c` → stap 0–6 op het bewijspaar: partner, verkoopfactuur GEPOST, statement line(s), reconcile (route i/ii/iii),
  terugweg. Rapport mét Odoo-move-ids, `name`, `state`, `is_reconciled`, saldocontrole (Σ regels = € 400.000,00 cent-exact) en de stand in company 6.

## Stap 3 — GO Peter → SCHRIJF d
- Het rapport van stap 2 is het GO-moment (één woord van Peter). Daarna, als NIEUWE inbox-opdracht: `SCHRIJF d` = `vgg-odoo-migratie --schrijf` (concepten →
  toets → auto-posten → reconcile) mét het volledige rapport (fasen A–D, tellers, stand). Rood in fase B = niets gepost — rapporteren, niet repareren zonder Peter.

## Afronding
BESLISSINGEN "VGG — CONCEPT → AUTO-POSTEN NÁ GROENE TOETS (Peter 17-09)" + RUN 2 BLOK 10/11: "werkt in productie: ja/nee"; rapport + INDEX; opdracht → gedaan.
