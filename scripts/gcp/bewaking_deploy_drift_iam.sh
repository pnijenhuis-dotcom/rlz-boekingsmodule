#!/usr/bin/env bash
# Ochtendrun 11-09 blok 2.1 — leesrecht voor de deploy-drift-probe (app/bewaking/deploy_drift.py) en de
# post-deploy-smoketest: het runtime-serviceaccount van de jobs (run-jobs@) leest via de Cloud Run Admin API het
# beeld van de service en van élke job in de locatie. roles/run.viewer = uitsluitend lezen (services/jobs/revisies/
# executions), géén run.jobs.run, géén IAM. Eenmalig als OWNER draaien (deploy@ heeft geen IAM-rechten; Claude Code
# mocht deze binding op 10/11-09 niet zetten — classifier). Idempotent: staat de binding al, dan exit 0 zonder mutatie.
#
# Nazorg 11-09 middag (blok 4a): de controlestap gebruikte een ongeldige --format-transform (`members.flatten`,
# gcloud kent die niet op een gefilterde lijst); Peter zette de binding 11-09 handmatig. De controle leest nu de
# policy mét `--flatten="bindings[].members"` + `--filter` en vergelijkt letterlijk op het member-lid.
#
# Controle ná het draaien: de eerstvolgende run van rlz-bewaking toont deploy_drift=ok in de joblog
# (`gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="rlz-bewaking"' --limit 20`),
# en de smoketest van de volgende deploy zegt "service en N job(s) op <sha>". Zonder dit recht: probe 'fout' mét
# "403 … run.viewer" (alert ná 2 metingen) en een rode smoketest — zichtbaar, nooit stil.
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
SA="run-jobs@${PROJECT}.iam.gserviceaccount.com"
MEMBER="serviceAccount:${SA}"
ROLE="roles/run.viewer"

heeft_binding() {
  gcloud projects get-iam-policy "${PROJECT}" \
    --flatten="bindings[].members" \
    --filter="bindings.role:${ROLE} AND bindings.members:${MEMBER}" \
    --format="value(bindings.members)" | grep -Fxq -- "${MEMBER}"
}

if heeft_binding; then
  echo ">> ${ROLE} → ${SA} staat al (geen wijziging)."
  exit 0
fi

echo ">> ${ROLE} → ${SA} (projectbreed, lees-only)"
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="${MEMBER}" \
  --role="${ROLE}" \
  --condition=None \
  --format=none

if heeft_binding; then
  echo ">> gezet."
else
  echo "FOUT: binding niet terug te lezen ná add-iam-policy-binding" >&2
  exit 1
fi
