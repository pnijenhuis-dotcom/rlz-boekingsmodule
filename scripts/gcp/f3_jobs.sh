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
# IMAP-INTAKE: LIVE sinds 2026-08-15 (F3.4 — echte imaplib-bron, secret-versie gevuld,
# INTAKE_IMAP_*-env-vars via deploy.yml). Alleen een VERS aangemaakte scheduler start
# hier gepauzeerd (zelfde guard als rlz-accordeur-herinneringen): een kale bootstrap
# heeft eerst een deploy-run nodig die de env-vars aan de job hangt — daarna handmatig
# resumen. Een herdraai raakt de actieve cadans NIET (les 2026-08-16: het oude
# onvoorwaardelijke pauzeren zette de live intake stil; Peter herstelde met resume).
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
CLOUD_SQL="rlz-boekhouding:europe-west4:rlz-sql2"   # F5/besluit 0021: CMEK-herbouw

# Job → CLI-commando → scheduler-cadans (draaiboektabel §F3). De cadansen: sync 07:00
# (live verzet bij tranche 2, 2026-08-22 — was 03:00; hier gelijkgetrokken zodat een
# her-run niets terugzet), reconciliaties 06:30 (Europe/Amsterdam), afleveraar elke
# 5 min, intake elke 10 min.
JOBS=(
  "rlz-sync|sync-alles|3600|0 7 * * *"
  "rlz-reconciliatie|reconciliatie-alles|3600|30 6 * * *"
  "rlz-webhook-afleveraar|webhook-afleveren|600|*/5 * * * *"
  "rlz-intake-imap|intake-postvak-verwerken|900|*/10 * * * *"
  # Accordeur-herinneringen (berichten-bouwsteen 2026-08-15, mockup-besluit "dagelijkse push
  # 09:00 alleen bij >0 open"). Secret-slots/accessors: scripts/gcp/notificaties_infra.sh;
  # scheduler start GEPAUZEERD (zie onder) tot de live-verificatie (mail + push op Peters
  # iPhone) rond is.
  "rlz-accordeur-herinneringen|accordeur-herinneringen|600|0 9 * * *"
  # Nieuwe-facturen-bundelmelding (besluit Peter 2026-08-16: géén melding per factuur —
  # bundelen per accordeur, ~elke 10 min). De cron dekt alleen de meldingsuren; de code
  # dwingt de stille uren (20:00–08:00 Europe/Amsterdam) bovendien zelf af. Scheduler start
  # GEPAUZEERD (zie onder) tot de notificatie-live-verificatie rond is.
  "rlz-nieuwe-facturen|nieuwe-facturen-melden|600|*/10 8-19 * * *"
  # Extractie-wachtrij (feedbackronde 26-08 punt 4): on-demand getriggerd door de service bij
  # elk groot document (stap 8) + dit scheduler-VANGNET elke 10 min voor een gemiste trigger.
  # Lege wachtrij = snelle no-op. Start NIET gepauzeerd: dit is een vangnet, geen notificatie.
  "rlz-extractie-wachtrij|extractie-wachtrij-verwerken|1800|*/10 * * * *"
  # Synthetische bewaking (best-practice-besluit 1, 31-08): kwartier-probes (health/DB/
  # documentopslag/mailkanaal/RLZ-leesroute; 1×/uur AI-call + extractie-foutratio) mét eigen
  # SMTP-alerts. Start NIET gepauzeerd: dit ís het vangnet — een gepauzeerde bewaking bewaakt
  # niets. Exit is vrijwel altijd 0 (falende probes = eigen alert); exit 1 = de bewaking zelf
  # kon niet draaien → de F3.2-job-failure-alert hieronder is dan het vangnet-op-het-vangnet.
  "rlz-bewaking|bewaking-probe|300|*/15 * * * *"
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
    "content": "Een Cloud Run-job in ${PROJECT_ID} is gefaald (exit ≠ 0). Logs: Console → Cloud Run → Jobs → <jobnaam> → Logs. Context: docs/GCP_UITROL.md §F3.",
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

echo "== 3. Secret-slot IMAP (idempotent; de versie is sinds F3.4 gevuld) =="
if gcloud secrets describe INTAKE_IMAP_WACHTWOORD >/dev/null 2>&1; then
  echo "   secret INTAKE_IMAP_WACHTWOORD bestaat al."
else
  gcloud secrets create INTAKE_IMAP_WACHTWOORD \
    --replication-policy=user-managed --locations="${REGION}"
  echo "   secret-slot aangemaakt (versie toevoegen hoort bij de activatiestap, §F3.4)."
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

echo "== 6. Scheduler-cadans per job (draaiboektabel; verse cadansen starten gepauzeerd) =="
HERINNERINGEN_NIEUW=0
IMAP_NIEUW=0
NIEUWE_FACTUREN_NIEUW=0
for REGELS in "${JOBS[@]}"; do
  IFS='|' read -r NAAM _CLI _TIMEOUT CADANS <<< "${REGELS}"
  if gcloud scheduler jobs describe "${NAAM}" --location="${REGION}" >/dev/null 2>&1; then
    echo "   scheduler ${NAAM} bestaat al — overgeslagen."
  else
    [ "${NAAM}" = "rlz-accordeur-herinneringen" ] && HERINNERINGEN_NIEUW=1
    [ "${NAAM}" = "rlz-intake-imap" ] && IMAP_NIEUW=1
    [ "${NAAM}" = "rlz-nieuwe-facturen" ] && NIEUWE_FACTUREN_NIEUW=1
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
# IMAP-intake: LIVE sinds 2026-08-15 (F3.4). Alleen bij verse aanmaak pauzeren — een
# herdraai mag de actieve cadans nooit terugpauzeren (les 2026-08-16: het oude
# onvoorwaardelijke pauzeren zette de live intake stil). Resume ná de eerste
# deploy-run die de INTAKE_IMAP_*-env-vars aan de job hangt.
if [ "${IMAP_NIEUW}" = "1" ]; then
  gcloud scheduler jobs pause rlz-intake-imap --location="${REGION}" --quiet >/dev/null
  echo "   rlz-intake-imap GEPAUZEERD (verse aanmaak — resumen ná de eerste deploy-run)."
fi
# Accordeur-herinneringen: gepauzeerd tot de notificatie-secrets staan én de
# live-verificatie (één echte push + één echte mail) rond is — resume gebeurt in
# scripts/gcp/notificaties_infra.sh. Alleen bij verse aanmaak pauzeren: een herdraai van
# dit script mag een al-geactiveerde cadans nooit terugpauzeren.
if [ "${HERINNERINGEN_NIEUW}" = "1" ]; then
  gcloud scheduler jobs pause rlz-accordeur-herinneringen --location="${REGION}" --quiet >/dev/null
  echo "   rlz-accordeur-herinneringen GEPAUZEERD (activatie via notificaties_infra.sh)."
fi
# Nieuwe-facturen-bundelmelding: zelfde activatievoorwaarde als de herinnering (notificatie-
# secrets + live-verificatie); alleen bij verse aanmaak pauzeren, nooit terugpauzeren.
if [ "${NIEUWE_FACTUREN_NIEUW}" = "1" ]; then
  gcloud scheduler jobs pause rlz-nieuwe-facturen --location="${REGION}" --quiet >/dev/null
  echo "   rlz-nieuwe-facturen GEPAUZEERD (resume samen met/na de notificatie-live-verificatie)."
fi

echo "== 6. rlz-projecten-cijfers: on-demand job (achtergrondrun-fix 2026-08-23) =="
# Deze job heeft bewust GÉÉN scheduler: de sync-knop op de service zet een wachtrij-rij
# klaar en triggert één uitvoering (CIJFERS_SYNC_JOB_RESOURCE in deploy.yml, auth via de
# metadata-server); de dagelijkse verversing zit in rlz-sync (07:00). De job zelf wordt —
# net als de andere F3-jobs — door deploy.yml aangemaakt/bijgewerkt. Hier alleen de
# eenmalige IAM-binding: run-backend@ (de service) mag déze ene job uitvoeren
# (roles/run.invoker dekt run.jobs.run; job-niveau, least privilege — geen overrides nodig,
# de wachtrij-rij ís de opdracht).
if gcloud run jobs describe rlz-projecten-cijfers --region="${REGION}" --format="value(metadata.name)" >/dev/null 2>&1; then
  gcloud run jobs add-iam-policy-binding rlz-projecten-cijfers \
    --region="${REGION}" \
    --member="serviceAccount:run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --quiet >/dev/null
  echo "   run-backend@ mag rlz-projecten-cijfers uitvoeren (roles/run.invoker, job-niveau)."
else
  echo "   LET OP: job rlz-projecten-cijfers bestaat nog niet (eerste deploy-run maakt 'm) —"
  echo "   draai dit script daarna opnieuw voor de IAM-binding, anders faalt de sync-knop"
  echo "   zichtbaar met 'Achtergrondrun starten mislukt' (403)."
fi

echo "== 7. rlz-bank-sync: on-demand job (bank auto-verversing bij openen, 25-08 deel 4) =="
# Zelfde patroon als stap 6: geen scheduler, de service triggert één uitvoering per
# bankscherm-opening (BANK_SYNC_JOB_RESOURCE in deploy.yml); alleen de IAM-binding hier.
if gcloud run jobs describe rlz-bank-sync --region="${REGION}" --format="value(metadata.name)" >/dev/null 2>&1; then
  gcloud run jobs add-iam-policy-binding rlz-bank-sync \
    --region="${REGION}" \
    --member="serviceAccount:run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --quiet >/dev/null
  echo "   run-backend@ mag rlz-bank-sync uitvoeren (roles/run.invoker, job-niveau)."
else
  echo "   LET OP: job rlz-bank-sync bestaat nog niet (eerste deploy-run maakt 'm) —"
  echo "   draai dit script daarna opnieuw voor de IAM-binding, anders faalt de auto-verversing"
  echo "   zichtbaar met 'Achtergrondrun starten mislukt' (403); de handmatige knop werkt wel."
fi

echo "== 8. rlz-extractie-wachtrij: on-demand job + vangnet (feedbackronde 26-08 punt 4) =="
# Zelfde patroon als stap 6/7: de service triggert één uitvoering per groot document
# (EXTRACTIE_WACHTRIJ_JOB_RESOURCE in deploy.yml); daarnaast de */10-scheduler uit de JOBS-lijst
# als vangnet. Hier alleen de IAM-binding voor de trigger vanuit de service.
if gcloud run jobs describe rlz-extractie-wachtrij --region="${REGION}" --format="value(metadata.name)" >/dev/null 2>&1; then
  gcloud run jobs add-iam-policy-binding rlz-extractie-wachtrij \
    --region="${REGION}" \
    --member="serviceAccount:run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --quiet >/dev/null
  echo "   run-backend@ mag rlz-extractie-wachtrij uitvoeren (roles/run.invoker, job-niveau)."
else
  echo "   LET OP: job rlz-extractie-wachtrij bestaat nog niet (eerste deploy-run maakt 'm) —"
  echo "   draai dit script daarna opnieuw voor de IAM-binding; tot dan vangt alleen de"
  echo "   */10-scheduler grote documenten op (zichtbaar 'in wachtrij', nooit stil)."
fi

echo "== 9. rlz-eerste-sync: on-demand job (wizard Administratie toevoegen, 26-08 punt 5) =="
# Geen scheduler: de wizard triggert één uitvoering per nieuwe administratie
# (EERSTE_SYNC_JOB_RESOURCE in deploy.yml); alleen de IAM-binding hier.
if gcloud run jobs describe rlz-eerste-sync --region="${REGION}" --format="value(metadata.name)" >/dev/null 2>&1; then
  gcloud run jobs add-iam-policy-binding rlz-eerste-sync \
    --region="${REGION}" \
    --member="serviceAccount:run-backend@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --quiet >/dev/null
  echo "   run-backend@ mag rlz-eerste-sync uitvoeren (roles/run.invoker, job-niveau)."
else
  echo "   LET OP: job rlz-eerste-sync bestaat nog niet (eerste deploy-run maakt 'm) —"
  echo "   draai dit script daarna opnieuw; tot dan toont de wizard 'Achtergrondrun starten"
  echo "   mislukt' en kan de sync via de knop opnieuw gestart worden."
fi

echo
echo "Klaar. Verificatie F3 (draaiboek): per job één handmatige run —"
echo "  gcloud run jobs execute rlz-sync                --region=${REGION} --wait   # groen"
echo "  gcloud run jobs execute rlz-reconciliatie       --region=${REGION} --wait   # groen"
echo "  gcloud run jobs execute rlz-webhook-afleveraar  --region=${REGION} --wait   # groen (OVERGESLAGEN: toggle uit)"
echo "  gcloud run jobs execute rlz-intake-imap         --region=${REGION} --wait   # groen (live sinds F3.4)"
echo "NB de oude geforceerde-failure-test (intake-seam faalde bewust) bestaat niet meer —"
echo "de alertketen is op de F3-run 2026-08-14 bewezen (policy '${POLICY_NAAM}' → ${ALERT_EMAIL})."
