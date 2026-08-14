#!/usr/bin/env bash
# =============================================================================
# F0 — HERVATTING 3, IDEMPOTENT (les uit hervat 1+2: "create" op een bestaande
# resource + set -e = stop). Deze versie checkt vóór elke create of de resource
# al bestaat en slaat 'm dan over — veilig om herhaald te draaien tot alles
# staat. Doet: SA's, bindings, WIF, Artifact Registry, slot-output.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
PROJECT_NUMBER="652591056217"
REGION="europe-west4"
GITHUB_REPO="pnijenhuis-dotcom/rlz-boekingsmodule"

gcloud config set project "${PROJECT_ID}" --quiet

sa_bestaat() {
  gcloud iam service-accounts describe \
    "$1@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1
}

# --- 4. SERVICE-ACCOUNTS (aanmaken indien afwezig) ----------------------------
sa_bestaat run-backend || gcloud iam service-accounts create run-backend \
  --display-name="RLZ backend runtime (Cloud Run service)"
sa_bestaat run-jobs || gcloud iam service-accounts create run-jobs \
  --display-name="RLZ jobs runtime (Cloud Run jobs)"
sa_bestaat deploy || gcloud iam service-accounts create deploy \
  --display-name="RLZ deploy (GitHub Actions via WIF)"

# Bindings zijn van zichzelf idempotent (herhalen = geen wijziging).
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client" --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:run-jobs@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client" --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer" --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.developer" --condition=None --quiet >/dev/null

gcloud iam service-accounts add-iam-policy-binding \
  "run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" --quiet >/dev/null
gcloud iam service-accounts add-iam-policy-binding \
  "run-jobs@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" --quiet >/dev/null

echo "== Service-accounts =="
gcloud iam service-accounts list --format="table(email,displayName)"

# --- 5. WORKLOAD IDENTITY FEDERATION (aanmaken indien afwezig) -----------------
gcloud iam workload-identity-pools describe github --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create github \
    --location=global \
    --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers describe github-oidc \
  --location=global --workload-identity-pool=github >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc github-oidc \
    --location=global \
    --workload-identity-pool=github \
    --display-name="GitHub OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'"

gcloud iam service-accounts add-iam-policy-binding \
  "deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}" \
  --role="roles/iam.workloadIdentityUser" --quiet >/dev/null

echo "== WIF-provider (verwacht: ACTIVE + repo-conditie) =="
gcloud iam workload-identity-pools providers describe github-oidc \
  --location=global --workload-identity-pool=github \
  --format="value(state,attributeCondition)"

# --- 6. ARTIFACT REGISTRY (aanmaken indien afwezig) ------------------------------
gcloud artifacts repositories describe rlz --location="${REGION}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create rlz \
    --repository-format=docker \
    --location="${REGION}" \
    --description="RLZ Boekingsmodule container-images"

echo "== Artifact Registry =="
gcloud artifacts repositories list --location="${REGION}" --format="table(name,format)"

# --- 7. SLOT --------------------------------------------------------------------
cat <<EOF

================================================================================
F0 COMPLEET. Geef deze waarden door aan Code (jobs-SA heet run-jobs@):

  PROJECT_ID       = ${PROJECT_ID}
  PROJECT_NUMBER   = ${PROJECT_NUMBER}
  WIF_PROVIDER     = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-oidc
  DEPLOY_SA        = deploy@${PROJECT_ID}.iam.gserviceaccount.com
  JOBS_SA          = run-jobs@${PROJECT_ID}.iam.gserviceaccount.com
  REGISTRY         = ${REGION}-docker.pkg.dev/${PROJECT_ID}/rlz
================================================================================
EOF
