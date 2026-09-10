#!/usr/bin/env bash
# Ochtendrun 11-09 blok 2.1 — leesrecht voor de deploy-drift-probe (app/bewaking/deploy_drift.py) en de
# post-deploy-smoketest: het runtime-serviceaccount van de jobs (run-jobs@) leest via de Cloud Run Admin API het
# beeld van de service en van élke job in de locatie. roles/run.viewer = uitsluitend lezen (services/jobs/revisies/
# executions), géén run.jobs.run, géén IAM. Eenmalig als OWNER draaien (deploy@ heeft geen IAM-rechten; Claude Code
# mocht deze binding op 10/11-09 niet zetten — classifier). Idempotent.
#
# Controle ná het draaien: de eerstvolgende run van rlz-bewaking toont deploy_drift=ok in de joblog
# (`gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="rlz-bewaking"' --limit 20`),
# en de smoketest van de volgende deploy zegt "service en N job(s) op <sha>". Zonder dit recht: probe 'fout' mét
# "403 … run.viewer" (alert ná 2 metingen) en een rode smoketest — zichtbaar, nooit stil.
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
SA="run-jobs@${PROJECT}.iam.gserviceaccount.com"
echo ">> roles/run.viewer → ${SA} (projectbreed, lees-only)"
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/run.viewer" \
  --condition=None \
  --format="value(bindings.filter(role:roles/run.viewer).members.flatten())" | tr ';' '\n' | grep -F "${SA}" \
  && echo ">> gezet."
