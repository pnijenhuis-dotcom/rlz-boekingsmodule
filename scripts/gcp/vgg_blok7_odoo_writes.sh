#!/usr/bin/env bash
# Run 2 VGG blok 7 — STAP 2: eerste Odoo-writes op company 6 (besluiten Peter 12-09 punt 1/2/3).
#   scripts/gcp/vgg_blok7_odoo_writes.sh plan            → alleen de dry-runs (leest, schrijft niets; geen kill-switch)
#   scripts/gcp/vgg_blok7_odoo_writes.sh SCHRIJF a|b|c   → de echte writes, per stap, expliciet
#     a = odoo-koppeling-migratiedoel --schrijf (DB-rij) + vgg-rekeningen --maak-aan (4 rekeningen + Overhead; besluit 1)
#     b = (zit in c) partners-stap = stap 0 van vgg-odoo-stap0 (besluit 3)
#     c = vgg-odoo-stap0 --schrijf (stap 0–6: partners, inkoopfactuur GEPOST, memoriaal/verkoop concept, statement lines,
#         reconcile, terugweg — besluit 2; IBAN op BNK1 leeg → stap 4/5 overgeslagen en gemeld)
# Regels: uitsluitend op de GEDEPLOYDE job-image (rlz-reconciliatie), kill-switch alleen als executie-override
# (--update-env-vars op `jobs execute` raakt de job-definitie niet), company-pin in de code, elke write terug-gelezen,
# audit per call. Nooit via nameting.sh (die weigert beide commando's hard). Twijfel = stoppen en vragen.
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
JOB="${JOB:-rlz-reconciliatie}"
ADMIN="${VGG_ADMINISTRATIE:-Vastgoedgroep}"
BRON="${ODOO_BRON_ADMINISTRATIE:-Universal Steigerbouw}"
COMPANY="${ODOO_COMPANY:-6}"
MODUS="${1:-plan}"; STAP="${2:-}"

execute() {  # execute <kill-switch 0|1> <cli-args…>
  local ks="$1"; shift
  local args="-m|app.cli"; for a in "$@"; do args="$args|$a"; done
  local extra=()
  [[ "$ks" == "1" ]] && extra=(--update-env-vars "MIGRATIE_ODOO_WRITES_INGESCHAKELD=true")
  echo ">> gcloud run jobs execute $JOB  [$*]  kill-switch=$ks" >&2
  local uitvoer exec_naam
  uitvoer="$(gcloud run jobs execute "$JOB" --project "$PROJECT" --region "$REGION" --wait \
    --format="value(metadata.name)" "${extra[@]}" --args="^|^$args" 2>&1 | tee /dev/stderr | tail -1)"
  exec_naam="$(grep -o 'rlz-[a-z-]*-[a-z0-9]\{5\}' <<<"$uitvoer" | tail -1)"
  [[ -n "$exec_naam" ]] || { echo "FOUT: geen executie-naam in de gcloud-uitvoer" >&2; return 1; }
  sleep 5
  gcloud logging read "resource.type=\"cloud_run_job\" AND labels.\"run.googleapis.com/execution_name\"=\"$exec_naam\"" \
    --project "$PROJECT" --region "$REGION" --limit 5000 --order=asc --format="value(textPayload)" 2>/dev/null \
    || gcloud logging read "resource.type=\"cloud_run_job\" AND labels.\"run.googleapis.com/execution_name\"=\"$exec_naam\"" \
      --project "$PROJECT" --limit 5000 --order=asc --format="value(textPayload)"
}

case "$MODUS" in
  plan)
    execute 0 odoo-koppeling-migratiedoel --administratie "$ADMIN" --bron-administratie "$BRON" --company "$COMPANY" --dry-run
    execute 0 vgg-rekeningen --administratie "$ADMIN" --company-id "$COMPANY"
    execute 0 vgg-odoo-stap0 --administratie "$ADMIN" --dry-run --stap 0-6 --max-per-type 1
    ;;
  SCHRIJF)
    case "$STAP" in
      a)
        execute 0 odoo-koppeling-migratiedoel --administratie "$ADMIN" --bron-administratie "$BRON" --company "$COMPANY" --schrijf
        execute 1 vgg-rekeningen --administratie "$ADMIN" --company-id "$COMPANY" --maak-aan
        ;;
      b|c)
        execute 1 vgg-odoo-stap0 --administratie "$ADMIN" --schrijf --stap 0-6 --max-per-type 1
        ;;
      *) echo "gebruik: $0 SCHRIJF a|b|c" >&2; exit 2 ;;
    esac
    ;;
  *) echo "gebruik: $0 plan | SCHRIJF a|b|c" >&2; exit 2 ;;
esac
