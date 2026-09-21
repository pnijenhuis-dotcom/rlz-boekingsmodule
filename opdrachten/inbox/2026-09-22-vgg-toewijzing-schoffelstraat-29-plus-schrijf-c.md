Domeinen: vgg-odoo-migratie, werkloop-productie
niet vóór: 2026-09-22 09:00

# VGG — Toewijzing pand Schoffelstraat 29 Purmerend + soort `verkoop` op RLZ-01-00000082 (beslispunt 1, Peter 21-09) → `plan` → SCHRIJF c

**Context:** rapport `docs/rapporten/2026-09-21-activa-fase1-bua-vgg-toewijzing-universal-overhead.md` sectie C, BESLISSINGEN "VGG — BESLISPUNT 1
BESLIST: TOEWIJZING PAND + SOORT VERKOOP RLZ-01-00000082 (Peter 21-09)". De CLI `pand-toewijzen` (commit 21-09) is pas live ná de deploy;
nooit lokaal tegen productie. Pand-bewijs (leesreplica 21-09): het bewijspaar (Receipt € 400.000,00, 19-03-2026, RLZ-id 8b079e5c…) is
afgeletterd tegen bankmutatie TransactionId `00112` = 20-03-2026 € 52.142,09 Ouwerkerk Notariaat "Betreft: schoffelstraat 29 te Purmerend,
ons dossier: 2026.079950.01". Het productie-pandenregister van VGG is LEEG (0 pand, 0 pand_boeking) — de CLI maakt het pand aan (herkomst mens).

## Stap 0 — deploy-check
`git fetch origin && git rev-list --count main..origin/main` = 0 (anders `merge --no-ff`); service `rlz-backend` ÉN job `rlz-reconciliatie` op
een image ≥ de commit van 21-09 mét `backend/app/panden/toewijzen_cli.py` (`gh run list --workflow=deploy.yml`, `gcloud run jobs describe
rlz-reconciliatie --region europe-west4 --format=json` → zelfde image). Niet aan de voorwaarde → dit bestand terug in `inbox/` mét een nieuwe
`niet vóór:`-regel.

## Stap 1 — dry-run (job-image, lees-only op RLZ: één `Receipts?$filter=…`-GET)
```
gcloud run jobs execute rlz-reconciliatie --project rlz-boekhouding --region europe-west4 --wait \
  --args="^|^-m|app.cli|pand-toewijzen|--administratie|Vastgoedgroep Nederland|--boekstuk|RLZ-01-00000082|--soort|verkoop|--adres|Schoffelstraat 29|--plaats|Purmerend|--dossier|2026.079950.01|--actor|p.nijenhuis@kempengroep.nl"
```
Verwacht: precies één RLZ-treffer (Receipts, € 400.000,00, 19-03-2026), pand "nieuw (herkomst mens, status verkocht, verkoopdatum 19-03-2026)",
pand_boeking "nieuw (soort verkoop, herkomst mens, zekerheid hoog)". Iets anders (0 of 2 treffers, bestaand pand op een ander adres) = STOP mét de
letterlijke uitvoer in het rapport.

## Stap 2 — schrijven (zelfde aanroep + `|--schrijf`), daarna idempotentie-toets (tweede `--schrijf` = "ongewijzigd"). Audit-rijen
`pand_toegewezen_mens` + `pand_boeking_toegewezen_mens` toetsen via `nameting -f onderdeel=query -f query="…"` of `db_lezen.sh` op de replica
(`--administratie cc07e461-3288-4065-85ed-9005495a22ea`).

## Stap 3 — `plan` (vier dry-runs, job-image): `ODOO_BRON_ADMINISTRATIE="Universal Verkoop" scripts/gcp/vgg_blok7_odoo_writes.sh plan`
Het stap0-rapport moet het bewijspaar RLZ-01-00000082 als **vertaalbaar** tonen (8000-regel → rol 803100 via de pand-toewijzing, analytic
`pand:<code>`). Blijft het "niet vertaalbaar (grootboek zonder Odoo-rekening: 8000)" → STOP mét de exacte reden, geen mapping verzinnen, rapport.

## Stap 4 — SCHRIJF c (alleen bij vertaalbaar): `scripts/gcp/vgg_blok7_odoo_writes.sh "SCHRIJF c"` (kill-switch als executie-override, één
bewijspaar posten + reconciliëren op company 6, terug-lezen). Het SCHRIJF-c-rapport = de GO-vraag aan Peter vóór `SCHRIJF d`; per-pand-sluit-eis
(7d) letterlijk in het rapport.

## Stap 5 — rapport `docs/rapporten/2026-09-22-vgg-toewijzing-schoffelstraat-schrijf-c.md` + INDEX + "## Gelezen regels"; "werkt in productie:
ja/nee" letterlijk; alinea "Uitgevoerd 22-09" onder de BESLISSINGEN-sectie van 21-09 en in `docs/regels/vgg-odoo-migratie.md`.
