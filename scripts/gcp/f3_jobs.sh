#!/usr/bin/env bash
# =============================================================================
# F3 — Jobs (docs/GCP_UITROL.md §F3): Scheduler → Cloud Run jobs + job-failure-alerting.
#
# WIE DRAAIT DIT: het org-owner-account (Peter, of Code onder de owner-gcloud zoals bij
# de F3-run 2026-08-14) — monitoring-kanalen, IAM-bindings en scheduler-jobs vergen
# rechten die deploy@ bewust niet heeft (least privilege, F0 4.5).
#
# WAT DIT SCRIPT NIET DOET: de job-DEFINITIES onderhouden — dat doet de deploy-workflow
# (.github/workflows/deploy.yml, stap "F3-jobs bijwerken": create-or-update op elke push,
# zelfde beeld als de service). Stap 4 hieronder is alléén bootstrap voor het geval dit
# script vóór de eerstvolgende deploy-run draait (describe-vóór-create: een bestaande
# job wordt nooit overschreven — deploy.yml is de canonieke config).
#
# VOLGORDE IS BEWUST (opdracht 2026-08-14): de alerting (F3.2) staat VOORAAN — geen gat
# tussen oud en nieuw vangnet; de lokale dagelijkse run blijft het echte vangnet tot de
# cutover (F1.6 stap 7, ná F5).
#
# IMAP-INTAKE: gebouwd maar NIET actief — de job bestaat, zijn scheduler wordt hier
# meteen GEPAUZEERD aangemaakt en het secret-slot INTAKE_IMAP_WACHTWOORD staat klaar
# zonder versie. Activeren kan pas ná Peters facturen@-mailbox + app-wachtwoord +
# DPA-check (AVG-checklist D): secret-versie toevoegen, INTAKE_IMAP_*-env-vars aan de
# job hangen (deploy.yml), scheduler resumen. Tot die tijd meldt de job de inactieve
# seam expliciet (exit 1) — bewust, geen stille no-op.
#
# IDEMPOTENT (F0-les 2026-08-14): describe-vóór-create op élke resource — herdraaien
# na een deelfout is altijd veilig.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"                            # koppelcontract §2b, niet wijzigen
JOBS_SA="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
ALERT_EMAIL="Peter@ak-nijenhuis.nl"              # kantoor-adres (zelfde als bootstrap-Beheerder)
POLICY_NAAM="RLZ Cloud Run job-failure (F3.2)"
KANAAL_NAAM="RLZ kantoor-e-mail (job-alerts)"
CLOUD_SQL="rlz-boekhouding:europe-west4:rlz-sql"

# Job → CLI-commando → scheduler-cadans (draaiboektabel §F3). De cadansen: sync 03:00,
# reconciliaties 06:30 (Europe/Amsterdam), afleveraar elke 5 min, intake elke 10 min.
JOBS=(
  "rlz-sync|sync-alles|3600|0 3 * * *"
  "rlz-reconciliatie|reconciliatie-alles|3600|30 6 * * *"
  "rlz-webhook-afleveraar|webhook-afleveren|600|*/5 * * * *"
  "rlz-intake-imap|intake-postvak-verwerken|900|*/10 * * * *"
)

gcloud config set project "${PROJECT_ID}" --quiet

echo "== 1. API's (Cloud Scheduler + Monitoring) =="
for API in cloudscheduler.googleapis.com monitoring.googleapis.com; do
  if gcloud services list --enabled --filter="name:${API}" --format="value(name)" | grep -q .; then
    echo "   ${API} staat al aan."
  else
    gcloud services enable "${API}"
    echo "   ${API} aangezet."
  fi
done

echo "== 2. F3.2 — job-failure-alerting EERST (geen gat tussen oud en nieuw vangnet) =="
# 2a. Notificatiekanaal (e-mail kantoor). NB idempotentie-check bewust met lokale
# match op displayName: de Monitoring-API heeft een eigen filtersyntax die de
# gcloud-quoting rond haakjes/spaties niet verdraagt (F3-run 2026-08-14).
KANAAL=$(gcloud beta monitoring channels list --format="value(name,displayName)" \
  | awk -F'\t' -v naam="${KANAAL_NAAM}" '$2==naam {print $1; exit}')
if [ -n "${KANAAL}" ]; then
  echo "   kanaal bestaat al: ${KANAAL}"
else
  KANAAL=$(gcloud beta monitoring channels create \
    --display-name="${KANAAL_NAAM}" \
    --type=email \
    --channel-labels="email_address=${ALERT_EMAIL}" \
    --format="value(name)")
  echo "   kanaal aangemaakt: ${KANAAL} (${ALERT_EMAIL})"
fi

# 2b. Alert-policy: élke gefaalde job-taakpoging (exit ≠ 0) → e-mail. De metric
# completed_task_attempt_count met result=failed dekt scheduler-runs én handmatige runs;
# groupByFields zet de jobnaam in de melding. duration 0s + trigger count 1 = één
# failure is genoeg (dit is een vangrail, geen ruisfilter).
BESTAAND=$(gcloud beta monitoring policies list --format="value(name,displayName)" \
  | awk -F'\t' -v naam="${POLICY_NAAM}" '$2==naam {print $1; exit}')
if [ -n "${BESTAAND}" ]; then
  echo "   policy bestaat al: ${BESTAAND}"
else
  POLICY_JSON=$(mktemp)
  cat > "${POLICY_JSON}" <<EOF
{
  "displayName": "${POLICY_NAAM}",
  "documentation": {
    "content": "Een Cloud Run-job in ${PROJECT_ID} is gefaald (exit ≠ 0). Logs: Console → Cloud Run → Jobs → <jobnaam> → Logs. Context: docs/GCP_UITROL.md §F3. NB rlz-intake-imap is tot de DPA-check bewust inactief (seam-melding = exit 1) en zijn scheduler staat gepauzeerd — een alert dáárover betekent dat iemand de job handmatig draaide.",
    "mimeType": "text/markdown"
  },
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Gefaalde Cloud Run-job-taakpoging",
      "conditionThreshold": {
        "filter": "resource.type = \\"cloud_run_job\\" AND metric.type = \\"run.googleapis.com/job/completed_task_attempt_count\\" AND metric.labels.result = \\"failed\\"",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "perSeriesAligner": "ALIGN_DELTA",
            "crossSeriesReducer": "REDUCE_SUM",
            "groupByFields": ["resource.labels.job_name"]
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "0s",
        "trigger": { "count": 1 }
      }
    }
  ],
  "alertStrategy": { "autoClose": "1800s" },
  "notificationChannels": ["${KANAAL}"]
}
EOF
  gcloud beta monitoring policies create --policy-from-file="${POLICY_JSON}"
  rm -f "${POLICY_JSON}"
  echo "   policy aangemaakt → meldt naar ${ALERT_EMAIL}."
fi

echo "== 3. Secret-slot IMAP (klaarzetten zonder versie — activatie ná DPA-check) =="
if gcloud secrets describe INTAKE_IMAP_WACHTWOORD >/dev/null 2>&1; then
  echo "   secret INTAKE_IMAP_WACHTWOORD bestaat al."
else
  gcloud secrets create INTAKE_IMAP_WACHTWOORD \
    --replication-policy=user-managed --locations="${REGION}"
  echo "   secret-slot aangemaakt (géén versie — de job mount 'm pas bij activatie)."
fi
gcloud secrets add-iam-policy-binding INTAKE_IMAP_WACHTWOORD \
  --member="serviceAccount:${JOBS_SA}" \
  --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
echo "   accessor voor ${JOBS_SA} staat."

echo "== 4. Job-definities (bootstrap — deploy.yml is de canonieke config) =="
# Default: hetzelfde beeld als de live service. F3_IMAGE_OVERRIDE bestaat voor het geval
# de jobs een verser beeld nodig hebben dan de laatste deploy (F3-run 2026-08-14: de
# sync-alles-OVERGESLAGEN-fix zat nog niet in het live beeld) — de eerstvolgende
# deploy-run trekt alles weer gelijk.
IMAGE="${F3_IMAGE_OVERRIDE:-$(gcloud run services describe rlz-backend --region="${REGION}" \
  --format="value(spec.template.spec.containers[0].image)")}"
echo "   beeld voor de bootstrap: ${IMAGE}"
for REGELS in "${JOBS[@]}"; do
  IFS='|' read -r NAAM CLI TIMEOUT _CADANS <<< "${REGELS}"
  if gcloud run jobs describe "${NAAM}" --region="${REGION}" >/dev/null 2>&1; then
    echo "   job ${NAAM} bestaat al — overgeslagen (deploy.yml onderhoudt 'm)."
    continue
  fi
  gcloud run jobs deploy "${NAAM}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --service-account "${JOBS_SA}" \
    --set-cloudsql-instances "${CLOUD_SQL}" \
    --set-env-vars "ENVIRONMENT=production,CLOUD_SQL_VERBINDING=${CLOUD_SQL},DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten,KMS_MASTERKEY_SLEUTEL=projects/${PROJECT_ID}/locations/${REGION}/keyRings/rlz/cryptoKeys/masterkey" \
    --set-secrets "APP_DB_WACHTWOORD=APP_DB_PASSWORD:latest" \
    --command python \
    --args="-m,app.cli,${CLI}" \
    --max-retries 0 \
    --task-timeout "${TIMEOUT}" \
    --quiet
  echo "   job ${NAAM} aangemaakt (${CLI})."
done

echo "== 5. Scheduler mag de jobs starten (run.invoker voor ${JOBS_SA}, per job) =="
for REGELS in "${JOBS[@]}"; do
  IFS='|' read -r NAAM _ _ _ <<< "${REGELS}"
  gcloud run jobs add-iam-policy-binding "${NAAM}" \
    --region="${REGION}" \
    --member="serviceAccount:${JOBS_SA}" \
    --role="roles/run.invoker" --quiet >/dev/null
  echo "   ${NAAM}: invoker staat."
done

echo "== 6. Scheduler-cadans per job (draaiboektabel; IMAP meteen gepauzeerd) =="
for REGELS in "${JOBS[@]}"; do
  IFS='|' read -r NAAM _CLI _TIMEOUT CADANS <<< "${REGELS}"
  if gcloud scheduler jobs describe "${NAAM}" --location="${REGION}" >/dev/null 2>&1; then
    echo "   scheduler ${NAAM} bestaat al — overgeslagen."
  else
    gcloud scheduler jobs create http "${NAAM}" \
      --location="${REGION}" \
      --schedule="${CADANS}" \
      --time-zone="Europe/Amsterdam" \
      --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${NAAM}:run" \
      --http-method=POST \
      --oauth-service-account-email="${JOBS_SA}" \
      --attempt-deadline=180s \
      --quiet
    echo "   scheduler ${NAAM} aangemaakt (${CADANS} Europe/Amsterdam)."
  fi
done
# IMAP-intake: bouwen maar NIET activeren (opdracht 2026-08-14) — pauzeren is idempotent.
gcloud scheduler jobs pause rlz-intake-imap --location="${REGION}" --quiet >/dev/null
echo "   rlz-intake-imap GEPAUZEERD (activatie ná mailbox + app-wachtwoord + DPA-check)."

echo
echo "Klaar. Verificatie F3 (draaiboek): per job één handmatige run —"
echo "  gcloud run jobs execute rlz-sync                --region=${REGION} --wait   # groen"
echo "  gcloud run jobs execute rlz-reconciliatie       --region=${REGION} --wait   # groen"
echo "  gcloud run jobs execute rlz-webhook-afleveraar  --region=${REGION} --wait   # groen (OVERGESLAGEN: toggle uit)"
echo "  gcloud run jobs execute rlz-intake-imap         --region=${REGION} --wait   # FAALT bewust (seam) = alert-test"
echo "De gefaalde intake-run is meteen de geforceerde-failure-test: binnen ~5-10 min hoort"
echo "een alertmail op ${ALERT_EMAIL} te landen (policy '${POLICY_NAAM}')."
