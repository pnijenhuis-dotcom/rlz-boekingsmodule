#!/usr/bin/env bash
# OTA-webbundels (Peter 16-09, BESLISSINGEN "NATIVE APP — LIVE UPDATES (OTA)"): eenmalig door de OWNER —
#   scripts/gcp/app_bundels_bucket.sh            → toont wat er gedaan zou worden
#   scripts/gcp/app_bundels_bucket.sh --apply    → bucket + IAM (idempotent: bestaat de bucket al → alleen versioning + IAM)
# Bucket `rlz-boekhouding-app-bundels` (europe-west4, uniform access, versioning aan, geen retentie: bundels zijn
# reproduceerbare build-artefacten, geen bewaarplicht). IAM: deploy@ mag objecten schrijven (objectCreator + viewer),
# de service-SA en run-jobs@ lezen (de backend serveert de zip zelf via GET /app/bundels/{id}.zip — de bucket blijft privé).
#
# SPOED 17-09: de eerste run (Peter 17-09 ~09:15) toonde `service-sa=?` — `gcloud run services describe` gaf in die sessie niets
# terug, waardoor de binding voor de service-SA stil werd overgeslagen en de backend de bundel-zip niet kon lezen. Nu:
# (1) service-SA lees-only uit de service, anders de DEFAULT compute-SA `<projectnummer>-compute@developer.gserviceaccount.com`
#     (Cloud Run zonder expliciete SA draait daarop) — nooit meer `?`, nooit meer stil overslaan; (2) `SERVICE_SA=…` als env
#     overschrijft (productie 17-09: run-backend@rlz-boekhouding.iam.gserviceaccount.com); (3) bucket-create alleen als hij
#     nog niet bestaat, zodat een herhaalde --apply ná een reauth-onderbreking gewoon doorgaat met versioning + IAM.
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
BUCKET="${BUCKET:-rlz-boekhouding-app-bundels}"
DEPLOY_SA="deploy@${PROJECT}.iam.gserviceaccount.com"
JOBS_SA="run-jobs@${PROJECT}.iam.gserviceaccount.com"
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
run() { echo "+ $*"; [[ $APPLY -eq 1 ]] && "$@"; return 0; }

if [[ -z "${SERVICE_SA:-}" ]]; then
  SERVICE_SA="$(gcloud run services describe rlz-backend --project "$PROJECT" --region "$REGION" \
    --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
  SERVICE_SA_BRON="service rlz-backend"
  if [[ -z "$SERVICE_SA" ]]; then
    PROJECTNUMMER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null || true)"
    [[ -n "$PROJECTNUMMER" ]] || { echo "FOUT: service-SA én projectnummer niet leesbaar (gcloud-sessie verlopen? 'gcloud auth login' en opnieuw)" >&2; exit 2; }
    SERVICE_SA="${PROJECTNUMMER}-compute@developer.gserviceaccount.com"
    SERVICE_SA_BRON="DEFAULT compute-SA (service draagt geen expliciete serviceAccountName)"
  fi
else
  SERVICE_SA_BRON="env SERVICE_SA"
fi
echo "project=$PROJECT bucket=$BUCKET service-sa=$SERVICE_SA ($SERVICE_SA_BRON) (dry-run: $((1-APPLY)))"

if gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" --format='value(name)' >/dev/null 2>&1; then
  echo "= bucket gs://$BUCKET bestaat al — create overgeslagen, versioning + IAM worden (opnieuw) gezet"
else
  run gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "$REGION" --uniform-bucket-level-access --public-access-prevention
fi
run gcloud storage buckets update "gs://$BUCKET" --versioning
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$DEPLOY_SA" --role roles/storage.objectCreator
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$DEPLOY_SA" --role roles/storage.objectViewer
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$JOBS_SA" --role roles/storage.objectViewer
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SERVICE_SA" --role roles/storage.objectViewer
echo "klaar — controle: gcloud storage buckets get-iam-policy gs://$BUCKET | grep -c $SERVICE_SA  (verwacht ≥ 1); daarna deploy opnieuw draaien (de OTA-stap registreert de eerste bundel)"
