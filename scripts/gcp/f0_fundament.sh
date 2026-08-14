#!/usr/bin/env bash
# =============================================================================
# F0 — Fundament GCP-uitrol RLZ Boekingsmodule (docs/GCP_UITROL.md, §F0)
#
# WIE DRAAIT DIT: Peter, als org-owner van de PDL Powerhouse-organisatie
# (het org-beheeraccount — hetzelfde account als bij vastly-504108).
# Cloud Shell of lokale gcloud; eerst `gcloud auth login` met dat account.
#
# WAT HET DOET (besluiten 2026-08-12, beslispunten 1/2/10):
#   1. project `rlz-boekhouding` aanmaken onder de PDL-org + billing koppelen
#   2. benodigde API's aanzetten
#   3. EU-locatie-org-policy: eerst checken of vastgoed 'm al op org-niveau
#      heeft gezet, anders op projectniveau zetten
#   4. drie service-accounts (run-backend@ / run-jobs@ / deploy@) met exact de
#      F0-rollen uit het draaiboek (secret-/bucket-bindings volgen in F1)
#   5. WIF-pool + GitHub-OIDC-provider met repo-conditie (vastgoed-patroon)
#   6. Artifact Registry (Docker) in europe-west4
#   7. verificaties + de resourcenamen die Code nodig heeft voor de
#      dummy-push-testworkflow (de laatste F0-verificatiestap)
#
# ⚠️ LES UIT DE UITVOERING (2026-08-15): dit script was NIET idempotent —
# `set -e` + een `create` op een al bestaande resource = script stopt halverwege
# en de uitrol blijft half staan (drie hervatpogingen nodig). Fundament-scripts
# schrijven we voortaan vanaf het begin idempotent: describe-vóór-create op
# élke resource, zodat herdraaien altijd veilig is. De idempotente afronding
# die F0 daadwerkelijk compleet maakte staat in `f0_hervat3.sh`; dit script
# blijft staan als het volledige, genummerde F0-naslagpakket (incl. project-
# aanmaak + org-policy, die in de hervatting niet meer nodig waren).
# f1_data.sh (F1) volgt het idempotente patroon vanaf regel één.
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------
# IN TE VULLEN DOOR PETER (het script weigert te draaien met placeholders):
# ----------------------------------------------------------------------------
ORG_ID="273731008371"             # org vastly.software — afgelezen uit de console 2026-08-15
BILLING_ACCOUNT_ID="019A81-D30602-A2EFE4"  # "My Billing Account" (actief) — console 2026-08-15

# Al besloten / vooringevuld — alleen aanpassen als de werkelijkheid afwijkt:
PROJECT_ID="rlz-boekhouding"      # beslispunt 1 (cijfersuffix alleen bij ID-botsing)
REGION="europe-west4"             # koppelcontract §2b, niet wijzigen
GITHUB_REPO="pnijenhuis-dotcom/rlz-boekingsmodule"  # check: repo van de deploy-workflow

if [[ "${ORG_ID}" == "INVULLEN" || "${BILLING_ACCOUNT_ID}" == "INVULLEN" ]]; then
  echo "STOP: vul eerst ORG_ID en BILLING_ACCOUNT_ID in (bovenin dit script)." >&2
  exit 1
fi

echo "== F0 voor project ${PROJECT_ID} in org ${ORG_ID}, regio ${REGION} =="

# ----------------------------------------------------------------------------
# 1. PROJECT + BILLING
# ----------------------------------------------------------------------------

# 1.1 Project aanmaken onder de PDL Powerhouse-org (botst de ID: suffix toevoegen
#     en PROJECT_ID hierboven aanpassen, zelfde patroon als vastly-504108).
gcloud projects create "${PROJECT_ID}" \
  --organization="${ORG_ID}" \
  --name="RLZ Boekingsmodule"
# Verificatie: project bestaat en hangt onder de org (parent.id = ORG_ID).
gcloud projects describe "${PROJECT_ID}" --format="value(projectId,parent.id,lifecycleState)"

# 1.2 Billing-account van de org koppelen (zonder billing werken de API's niet).
gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT_ID}"
# Verificatie: billingEnabled moet True zijn.
gcloud billing projects describe "${PROJECT_ID}" --format="value(billingEnabled)"

# 1.3 Alles hierna richt zich op dit project.
gcloud config set project "${PROJECT_ID}"

# 1.4 Projectnummer opvragen — nodig voor de WIF-principalSet verderop.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
echo "Projectnummer: ${PROJECT_NUMBER}"

# ----------------------------------------------------------------------------
# 2. API'S AANZETTEN (alles wat F0–F3 nodig heeft; aanzetten kost niets)
# ----------------------------------------------------------------------------

# 2.1 Run/SQL/Secrets/KMS/Storage voor de fases F1–F3, Artifact Registry + IAM
#     Credentials + STS voor de deploy-keten (WIF), orgpolicy voor stap 3.
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudkms.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  orgpolicy.googleapis.com
# Verificatie: de lijst toont o.a. run, sqladmin, secretmanager, artifactregistry.
gcloud services list --enabled --format="value(config.name)" | sort

# ----------------------------------------------------------------------------
# 3. EU-LOCATIE-ORG-POLICY (AVG-stap-2-vinkje; mogelijk al gezet door vastgoed)
# ----------------------------------------------------------------------------

# 3.1 EERST CHECKEN of de policy al op org-niveau bestaat (vastgoed kan 'm bij
#     vastly-504108 org-breed gezet hebben) — bestaat hij daar met in:eu-locations,
#     dan is stap 3.2 overbodig.
gcloud org-policies describe gcp.resourceLocations --organization="${ORG_ID}" \
  || echo "Geen org-brede policy gevonden → stap 3.2 uitvoeren (projectniveau)."

# 3.2 ALLEEN als 3.1 niets (bruikbaars) opleverde: policy op projectniveau zetten —
#     alle resources beperkt tot EU-locaties.
cat > /tmp/eu-locations-policy.yaml <<EOF
name: projects/${PROJECT_ID}/policies/gcp.resourceLocations
spec:
  rules:
    - values:
        allowedValues:
          - in:eu-locations
EOF
gcloud org-policies set-policy /tmp/eu-locations-policy.yaml
# Verificatie: de EFFECTIEVE policy op het project moet in:eu-locations tonen
# (ongeacht of hij van org- of projectniveau komt).
gcloud org-policies describe gcp.resourceLocations --project="${PROJECT_ID}" --effective

# ----------------------------------------------------------------------------
# 4. SERVICE-ACCOUNTS (least privilege, vastgoed-patroon — draaiboek F0.4)
#    NB: Secret Manager- en bucket-bindings zijn per-resource en volgen in F1,
#    zodra die resources bestaan. Hier alleen wat F0 kan zetten.
# ----------------------------------------------------------------------------

# 4.1 run-backend@ — runtime van de Cloud Run-service.
gcloud iam service-accounts create run-backend \
  --display-name="RLZ backend runtime (Cloud Run service)"

# 4.2 run-jobs@ (NB "jobs" faalt: SA-naam moet 6-30 tekens zijn) — runtime van de Cloud Run-jobs (sync, reconciliatie, afleveraar, intake).
gcloud iam service-accounts create run-jobs \
  --display-name="RLZ jobs runtime (Cloud Run jobs)"

# 4.3 deploy@ — CI/CD via GitHub Actions + WIF (geen langlevende keys).
gcloud iam service-accounts create deploy \
  --display-name="RLZ deploy (GitHub Actions via WIF)"

# 4.4 Cloud SQL Client voor beide runtime-SA's (verbinden met de F1-instantie).
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client" --condition=None
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:run-jobs@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client" --condition=None

# 4.5 deploy@: images pushen naar Artifact Registry + Cloud Run-revisies uitrollen.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer" --condition=None
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.developer" --condition=None

# 4.6 deploy@ mag de twee runtime-SA's "gebruiken" (vereist om een Cloud
#     Run-service/job uit te rollen die als run-backend@/run-jobs@ draait) —
#     bewust op SA-niveau gebonden, niet projectbreed.
gcloud iam service-accounts add-iam-policy-binding \
  "run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
gcloud iam service-accounts add-iam-policy-binding \
  "run-jobs@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# Verificatie: drie SA's zichtbaar…
gcloud iam service-accounts list --format="table(email,displayName)"
# …en de projectrollen per SA kloppen met het draaiboek.
gcloud projects get-iam-policy "${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:iam.gserviceaccount.com" \
  --format="table(bindings.members,bindings.role)"

# ----------------------------------------------------------------------------
# 5. WORKLOAD IDENTITY FEDERATION — GitHub Actions (vastgoed-patroon,
#    beslispunt 10): pool + OIDC-provider met harde repo-conditie, daarna
#    mag alleen díé repo deploy@ impersoneren.
# ----------------------------------------------------------------------------

# 5.1 WIF-pool voor GitHub Actions.
gcloud iam workload-identity-pools create github \
  --location=global \
  --display-name="GitHub Actions"

# 5.2 OIDC-provider op GitHubs token-issuer, met de repo-conditie als slot:
#     alleen workflows uit ONZE repo krijgen een token.
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --location=global \
  --workload-identity-pool=github \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '${GITHUB_REPO}'"

# 5.3 Koppeling: workflows uit de repo mogen deploy@ impersoneren.
gcloud iam service-accounts add-iam-policy-binding \
  "deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}" \
  --role="roles/iam.workloadIdentityUser"

# Verificatie: provider ACTIVE + de attribute-condition toont de juiste repo.
gcloud iam workload-identity-pools providers describe github-oidc \
  --location=global --workload-identity-pool=github \
  --format="value(state,attributeCondition)"

# ----------------------------------------------------------------------------
# 6. ARTIFACT REGISTRY — één Docker-repository in europe-west4
# ----------------------------------------------------------------------------

# 6.1 Docker-repository voor de backend-images (F2-Dockerfile pusht hierheen).
gcloud artifacts repositories create rlz \
  --repository-format=docker \
  --location="${REGION}" \
  --description="RLZ Boekingsmodule container-images"
# Verificatie: repository bestaat in de juiste regio.
gcloud artifacts repositories list --location="${REGION}" --format="table(name,format)"

# ----------------------------------------------------------------------------
# 7. SLOT — de waarden die Code nodig heeft voor de dummy-push-testworkflow
#    (laatste F0-verificatie: een image via WIF naar de registry pushen)
# ----------------------------------------------------------------------------
cat <<EOF

================================================================================
F0 GEDRAAID. Geef deze waarden door aan Code (mogen gewoon in de chat/repo —
het zijn resourcenamen, geen secrets):

  PROJECT_ID       = ${PROJECT_ID}
  PROJECT_NUMBER   = ${PROJECT_NUMBER}
  WIF_PROVIDER     = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-oidc
  DEPLOY_SA        = deploy@${PROJECT_ID}.iam.gserviceaccount.com
  REGISTRY         = ${REGION}-docker.pkg.dev/${PROJECT_ID}/rlz

Code bouwt hiermee de GitHub Actions-testworkflow (google-github-actions/auth
met bovenstaande WIF_PROVIDER + DEPLOY_SA) die een dummy-image pusht — slaagt
die run, dan is de hele F0-deploy-keten bewezen en is F0 af.
================================================================================
EOF
