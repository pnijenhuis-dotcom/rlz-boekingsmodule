#!/usr/bin/env bash
# Sourceable helper voor productie-NAMETINGEN (GCP_UITROL §F7 route A, uitgevoerd 10-09-2026 — blok 1 nametingen-run).
# Regel Peter 08-09: productie alleen via de bestaande Cloud Run-jobs op de gedeployde image; nametingen lopen onder
# het serviceaccount nameting@rlz-boekhouding.iam.gserviceaccount.com (custom rol nametingUitvoerder, job-scoped op
# rlz-reconciliatie + run.viewer/logging.viewer projectbreed; GEEN cloudsql.client, GEEN secretmanager, GEEN deploy/IAM).
#
# Gebruik in een script:   source "$(dirname "$0")/nameting_env.sh"   (daarna: gcloud … "${NAMETING_GCLOUD_FLAGS[@]}")
#
# Volgorde van credential-resolutie (niets stil — elke tak print wat hij doet):
#   1. ~/Sleutels/nameting.env aanwezig → sourcen. Verwacht daarin (geen secrets in de repo, bestand buiten de werkboom):
#        NAMETING_SA=nameting@rlz-boekhouding.iam.gserviceaccount.com
#        GOOGLE_APPLICATION_CREDENTIALS=$HOME/Sleutels/nameting-sa.json      # SA-key (route A6) — zie let-op hieronder
#      Staat de key er → gcloud auth activate-service-account (sessie verloopt nooit; ADC voor scripts via die env).
#   2. Geen key (10-09: org-policy `iam.managed.disableServiceAccountKeyCreation` op organisatie 273731008371 blokkeert
#      `keys create`; beslispunt Peter) → impersonatie: `--impersonate-service-account=$NAMETING_SA` op élke gcloud-
#      aanroep. Vereist een geldige GEBRUIKERSsessie (info@vastly.software heeft roles/iam.serviceAccountTokenCreator op
#      het SA) — de dagelijkse herlogin blijft dan bestaan, maar élke job-start staat in de audit op naam van het SA.
#   3. Geen env-bestand → huidig gedrag (gebruikerssessie, geen impersonatie) mét melding.
set -euo pipefail
NAMETING_ENV="${NAMETING_ENV:-$HOME/Sleutels/nameting.env}"
NAMETING_GCLOUD_FLAGS=()
if [[ -f "$NAMETING_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$NAMETING_ENV"
  : "${NAMETING_SA:=nameting@rlz-boekhouding.iam.gserviceaccount.com}"
  if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" && -f "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS
    gcloud auth activate-service-account "$NAMETING_SA" --key-file="$GOOGLE_APPLICATION_CREDENTIALS" --quiet >/dev/null
    gcloud config set account "$NAMETING_SA" --quiet >/dev/null
    echo ">> nameting: serviceaccount-key actief ($NAMETING_SA)" >&2
  else
    NAMETING_GCLOUD_FLAGS=(--impersonate-service-account="$NAMETING_SA")
    echo ">> nameting: geen SA-key (org-policy) — impersonatie van $NAMETING_SA op de gebruikerssessie" >&2
  fi
else
  echo ">> nameting: $NAMETING_ENV ontbreekt — gebruikerssessie zonder impersonatie (huidig gedrag)" >&2
fi
export NAMETING_GCLOUD_FLAGS
