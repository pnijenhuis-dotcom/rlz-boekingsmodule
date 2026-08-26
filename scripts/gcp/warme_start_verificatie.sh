#!/usr/bin/env bash
# Verificatie WARME START rlz-backend (besluit Peter 25-08, C3-vervolg —
# docs/COLD_START_ONDERZOEK_25-08.md). Twee checks, beide rapporteren:
#   1. de live revisie draagt minScale 1 (gcloud describe);
#   2. een verse request ná > 20 min stilte antwoordt < 2 s (voorheen 14,6–16,9 s).
# Alleen-lezen: wijzigt niets. Vereist een ingelogde gcloud (`gcloud auth login`) voor check 1;
# check 2 draait ook zonder gcloud. Exit 1 zodra één van beide niet klopt.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
URL="${APP_URL:-https://app.administratiekantoornijenhuis.nl}/health"
MAX_S="${MAX_S:-2.0}"

rc=0
echo "== 1. minScale op de live revisie (${PROJECT_ID}/${REGION}/rlz-backend)"
if min=$(gcloud run services describe rlz-backend --region "$REGION" --project "$PROJECT_ID" \
      --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])" 2>&1); then
  rev=$(gcloud run services describe rlz-backend --region "$REGION" --project "$PROJECT_ID" \
      --format="value(status.latestReadyRevisionName)")
  if [ "$min" = "1" ]; then echo "   OK  minScale=1 (revisie ${rev})"
  else echo "   FOUT minScale='${min:-<niet gezet>}' (revisie ${rev}) — verwacht 1"; rc=1; fi
else
  echo "   OVERGESLAGEN gcloud niet bruikbaar: ${min}"; echo "   → draai 'gcloud auth login' en herhaal."; rc=1
fi

echo "== 2. verse request ${URL} (pas zinvol ná > 20 min zonder verkeer)"
t=$(curl -s -o /dev/null -w '%{time_total}' --max-time 60 "$URL")
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL")
if awk -v t="$t" -v m="$MAX_S" 'BEGIN{exit !(t+0 < m+0)}'; then echo "   OK  ${t}s (HTTP ${code}) — < ${MAX_S}s"
else echo "   FOUT ${t}s (HTTP ${code}) — ≥ ${MAX_S}s: koude start nog aanwezig?"; rc=1; fi
echo "   (gemeten $(date '+%Y-%m-%d %H:%M:%S'))"
exit $rc
