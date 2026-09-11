#!/usr/bin/env bash
# Lees-only productie-nameting op de gedeployde job-image (regel Peter 08-09; §F7 route A, blok 1 nametingen-run 10-09).
#   scripts/gcp/nameting.sh <cli-commando> [args…]
# Voorbeelden:
#   scripts/gcp/nameting.sh reconciliatie-alles --alleen rlz_dubbel --lees-only
#   scripts/gcp/nameting.sh autoboek-leren-rapport --administratie <uuid>
#   scripts/gcp/nameting.sh bank-voorstellen-lezen --administratie "Administratiekantoor Nijenhuis" --met-ai-toets
#   scripts/gcp/nameting.sh rlz-lezen --administratie "Administratiekantoor Nijenhuis C.V." --pad PaymentTransactions --filter "PaymentBatchId ne null" --expand "Batch,PaymentReferenceList(\$expand=Document)" --top 5
# Alleen commando's uit de allowlist hieronder (lees-only); schrijvende nazorg blijft een expliciete opdracht van Peter
# via de bestaande scripts. Argumenten mét komma's zijn veilig: gcloud's ^|^-scheidingsteken.
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HIER/nameting_env.sh"
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
JOB="${JOB:-rlz-reconciliatie}"
# rlz-lezen (blok 10 11-09): één OData-GET op de RLZ-API van één administratie — het commando weigert zelf élke
# niet-GET en elk Actions-/Download-pad (app/rlz/lezen_cli.py), --top ≤ 50, uitvoer altijd geanonimiseerd.
ALLOWLIST="reconciliatie-alles autoboek-leren-rapport bank-voorstellen-lezen bank-historie-backfill boeken-status reconciliatie-acceptaties migratie-schoonlijst pandenregister-afleiden staande-goedkeuring-voorstellen-lezen rlz-lezen werkvoorraad-tellers-herrekenen"
CMD="${1:-}"; [[ -n "$CMD" ]] || { echo "gebruik: $0 <cli-commando> [args…]" >&2; exit 2; }
grep -qw -- "$CMD" <<<"$ALLOWLIST" || { echo "FOUT: '$CMD' staat niet in de lees-only allowlist ($ALLOWLIST)" >&2; exit 2; }
if [[ "$CMD" == "reconciliatie-alles" ]]; then
  printf '%s\n' "$@" | grep -qx -- "--lees-only" || { echo "FOUT: reconciliatie-alles alleen mét --lees-only via dit script (de echte run is de scheduler/'Nu draaien')" >&2; exit 2; }
fi
if [[ "$CMD" == "bank-historie-backfill" ]]; then
  # Ochtendrun 11-09: de backfill schrijft in de eigen cache — als nameting alleen de telling (--dry-run).
  printf '%s\n' "$@" | grep -qx -- "--dry-run" || { echo "FOUT: bank-historie-backfill alleen mét --dry-run via dit script (de echte vulling is een expliciete opdracht van Peter)" >&2; exit 2; }
fi
if [[ "$CMD" == "werkvoorraad-tellers-herrekenen" ]]; then
  # Blok 6 11-09: de herberekening schrijft de tellers-cache — als nameting alleen de vergelijking (--dry-run).
  printf '%s\n' "$@" | grep -qx -- "--dry-run" || { echo "FOUT: werkvoorraad-tellers-herrekenen alleen mét --dry-run via dit script (de echte herberekening loopt in sync-alles)" >&2; exit 2; }
fi
if [[ "$CMD" == "pandenregister-afleiden" ]] && printf '%s\n' "$@" | grep -qx -- "--schrijf"; then
  echo "FOUT: --schrijf is geen nameting" >&2; exit 2
fi
ARGS="-m|app.cli"; for a in "$@"; do ARGS="$ARGS|$a"; done
echo ">> gcloud run jobs execute $JOB ($CMD) onder ${NAMETING_SA:-gebruikerssessie}" >&2
UITVOER="$(gcloud run jobs execute "$JOB" --project "$PROJECT" --region "$REGION" --wait --format="value(metadata.name)" \
  "${NAMETING_GCLOUD_FLAGS[@]}" --args="^|^$ARGS" 2>&1 | tee /dev/stderr | tail -1)"
EXEC="$(grep -o 'rlz-[a-z-]*-[a-z0-9]\{5\}' <<<"$UITVOER" | tail -1)"
[[ -n "$EXEC" ]] || { echo "FOUT: geen executie-naam gevonden in de gcloud-uitvoer" >&2; exit 1; }
echo ">> uitvoer van $EXEC (Cloud Logging, chronologisch):" >&2
sleep 5
gcloud logging read "resource.type=\"cloud_run_job\" AND labels.\"run.googleapis.com/execution_name\"=\"$EXEC\"" \
  --project "$PROJECT" --limit 5000 --order=asc --format="value(textPayload)" "${NAMETING_GCLOUD_FLAGS[@]}"
