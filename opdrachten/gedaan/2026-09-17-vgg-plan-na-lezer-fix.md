uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-vgg-plan-na-lezer-fix.md

# OPDRACHT 17-09 (avond) — VGG → Odoo: `plan` ná deploy van de lezer-fix (blok 12) — SCHRIJF c ALLEEN als het bewijspaar vertaalbaar is

Domeinen: vgg-odoo-migratie

Vervolg op `docs/rapporten/2026-09-17-vgg-schrijf-c-na-deploy.md` (§3 meetrecept, §5 beslispunt 1).
**Schrijvend op company 6 — alleen via `scripts/gcp/vgg_blok7_odoo_writes.sh` op de gedeployde job-image; nooit via nameting.sh.**

## Stap 0
- Deploy van de commit "fix(VGG → Odoo blok 12 …)" van 17-09 avond groen (`gh run list --workflow=deploy.yml --limit 1`); service = jobs (`deploy_check` in het script). Niet gedeployd = stoppen, melden (geen run op oud beeld).
- `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"`.

## Stap 1 — `plan` (dry-run, lees-only)
- `scripts/gcp/vgg_blok7_odoo_writes.sh plan`. Toets tegen het meetrecept: stap0-rapport draagt "replay-mapping: Odoo-rekeningen gelezen uit company 6 via de doelkoppeling: 361" (niet "replay zonder Odoo-rekeningen"); `vgg-odoo-migratie --dry-run` ≈ 224 vertaalbare documenten (was 58) en de pand-eis toont meetbare "SIGNAAL: sluit niet"-regels (39 verwacht) i.p.v. "niet meetbaar — doelkoppeling ontbreekt".
- Bewijspaar: toont het stap0-rapport "out_invoice RLZ-01-00000082 ↔ N bankregel(s)" (vertaalbaar) → stap 2. Toont het nog "niet vertaalbaar (grootboek zonder Odoo-rekening: 8000 …)" → STOPPEN, rapporteren: beslispunt 1 (Toewijzing pand + soort verkoop / mapping 8000) staat open bij Peter. Stap 4 IBAN-stand BNK1: leeg = KLIKPUNT Peter, melden.

## Stap 2 — SCHRIJF c (alleen bij vertaalbaar bewijspaar + IBAN gevuld)
- `scripts/gcp/vgg_blok7_odoo_writes.sh SCHRIJF c` → rapport mét Odoo-move-ids, `name`, `state`, `is_reconciled`, saldocontrole (Σ regels = € 400.000,00 cent-exact), stand company 6. Dit rapport = GO-moment Peter voor SCHRIJF d (nieuwe inbox-opdracht, nooit in deze run).

## Afronding
BESLISSINGEN "VGG — CONCEPT → AUTO-POSTEN NÁ GROENE TOETS (Peter 17-09)": alinea "werkt in productie" voor de lezer-fix (ja/nee) + SCHRIJF c; rapport + INDEX; opdracht → gedaan.
