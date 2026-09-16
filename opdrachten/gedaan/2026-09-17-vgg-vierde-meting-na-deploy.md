> uitgevoerd 2026-09-16 (nacht), rapport: docs/rapporten/2026-09-16-vgg-vierde-meting.md

# OPDRACHT 17-09 — VGG run 2 blok 9 vervolg: VIERDE METING ná deploy (lees-only; géén Odoo-writes)

Vervolg op `opdrachten/gedaan/2026-09-16-vgg-schrijf-b-1001-model.md` (rapport `docs/rapporten/2026-09-16-vgg-schrijf-b.md`): het 1001-model
staat in de code maar is niet gemeten — de gcloud-sessie was verlopen en de code stond vóór de deploy.

## Stap 0 — voorwaarden (stoppen mét melding als één ontbreekt)
- `gcloud auth print-access-token` werkt (Peter logt zo nodig eerst in; CC kan dat niet).
- Deploy van de commits van 16-09 avond groen; service én álle jobs op hetzelfde image (`scripts/gcp/vgg_blok7_nameting.sh` toetst dat zelf
  en stopt bij drift).

## Stap 1 — meting
- `scripts/gcp/vgg_blok7_nameting.sh c` → `vgg-replay --dry-run` op de job-image; uitvoer bewaren als
  `verkenning/nameting-vgg-replay-<dd>-09-cc.txt` (suffix `-cc`: de nameting-bot schrijft dezelfde bestandsnamen per datum).
- Rapportregels tellen tegen de JSON (eerste echte meting van `print_gedoseerd`, nazorg blok 8).

## Stap 2 — oordeel (drie standen), geen doorrekenen bij afwijking
- Verwacht: ROOD uitsluitend op debiteuren/crediteuren (afletterstand, SCHRIJF c); tussenrekening + bank 0,00 óf mét benoemde restcategorieën
  (Σ categorieën = groepsverschil); sectie "1001-model" mét tellers (gekoppeld via koppeling/bedrag+datum, zonder mutatie, meerduidig);
  LET-OP "KLIKPUNT PETER" zolang de outstanding-rekening op BNK1 niet is ingesteld.
- Wijkt het af (bv. restant bank ≠ 0 buiten de opruimpunten, of veel meerduidig): rapporteren mét de regels uit de 1001-tabel, niets bouwen.

## Afronding
- BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 9 …": uitkomstentabel toevoegen (letterlijk, mét "werkt in productie: ja/nee").
- Rapport `docs/rapporten/2026-09-1x-vgg-vierde-meting.md` + INDEX; beslispunten alleen bij een afwijking.
