#!/usr/bin/env bash
# OTA-webbundels (Peter 16-09, BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA)"): eenmalig door de OWNER —
#   scripts/gcp/app_bundels_bucket.sh            → toont wat er gedaan zou worden
#   scripts/gcp/app_bundels_bucket.sh --apply    → bucket + IAM
# Bucket `rlz-boekhouding-app-bundels` (europe-west4, uniform access, versioning aan, geen retentie: bundels zijn
# reproduceerbare build-artefacten, geen bewaarplicht). IAM: deploy@ mag objecten schrijven (objectCreator + viewer),
# de service-SA en run-jobs@ lezen (de backend serveert de zip zelf via GET /app/bundels/{id}.zip — de bucket blijft privé).
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
BUCKET="${BUCKET:-rlz-boekhouding-app-bundels}"
DEPLOY_SA="deploy@${PROJECT}.iam.gserviceaccount.com"
JOBS_SA="run-jobs@${PROJECT}.iam.gserviceaccount.com"
SERVICE_SA="$(gcloud run services describe rlz-backend --project "$PROJECT" --region "$REGION" --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
run() { echo "+ $*"; [[ $APPLY -eq 1 ]] && "$@"; return 0; }
echo "project=$PROJECT bucket=$BUCKET service-sa=${SERVICE_SA:-?} (dry-run: $((1-APPLY)))"
run gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "$REGION" --uniform-bucket-level-access --public-access-prevention
run gcloud storage buckets update "gs://$BUCKET" --versioning
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$DEPLOY_SA" --role roles/storage.objectCreator
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$DEPLOY_SA" --role roles/storage.objectViewer
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$JOBS_SA" --role roles/storage.objectViewer
[[ -n "$SERVICE_SA" ]] && run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SERVICE_SA" --role roles/storage.objectViewer
echo "klaar — daarna: deploy opnieuw draaien (de OTA-stap registreert de eerste bundel)"
