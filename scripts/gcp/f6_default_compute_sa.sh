#!/usr/bin/env bash
# F6 — default compute service account afknijpen/uitschakelen (hygiëne-run 2026-08-16).
#
# WIE DRAAIT DIT: Peter (owner-account). Code voert niets uit — dit script is het draaiboek.
#
# WAAROM: Google maakt in elk project automatisch het "default compute service account"
# (<projectnummer>-compute@developer.gserviceaccount.com) aan, standaard met de brede
# Editor-rol op het HELE project. Onze uitrol gebruikt het nergens — alle Cloud Run-services
# en -jobs draaien op de eigen least-privilege-SA's run-backend@/run-jobs@, deploys op
# deploy@ (F0). Zolang het default-SA actief is met Editor, is het een slapende sleutelbos:
# elke resource die er per ongeluk op zou landen, krijgt meteen projectbrede rechten.
#
# WAT HET DOET (drie stappen, elk idempotent — describe vóór mutatie, LES 2026-08-15):
#   1. VERIFICATIE (fail-closed): controleert dat GEEN Cloud Run-service of -job het
#      default-SA gebruikt (een lege serviceAccountName betekent: default in gebruik!).
#      Bij één treffer stopt het script zonder iets te wijzigen.
#   2. Verwijdert de roles/editor-binding van het default-SA (alleen als die er nog is).
#   3. Schakelt het default-SA uit (disable — OMKEERBAAR met
#      `gcloud iam service-accounts enable`; verwijderen doen we bewust niet).
#
# TERUGWEG: mocht ooit iets stilletjes op het default-SA leunen (bv. een legacy
# Cloud Build-trigger), dan faalt dat vanaf nu zíchtbaar met een auth-fout; herstel is
# één commando (enable) + alsnog een eigen SA voor die dienst inrichten.

set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"  # koppelcontract §2b, niet wijzigen

gcloud config set project "${PROJECT_ID}" --quiet

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
DEFAULT_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "Default compute SA: ${DEFAULT_SA}"

if ! gcloud iam service-accounts describe "${DEFAULT_SA}" >/dev/null 2>&1; then
  echo "Default compute SA bestaat niet (meer) in dit project — niets te doen."
  exit 0
fi

echo "== 1. Verificatie: geen Cloud Run-service of -job op het default-SA =="
GEBRUIKT=0
for SVC in $(gcloud run services list --region="${REGION}" --format='value(metadata.name)'); do
  SA="$(gcloud run services describe "${SVC}" --region="${REGION}" \
        --format='value(spec.template.spec.serviceAccountName)')"
  if [ -z "${SA}" ] || [ "${SA}" = "${DEFAULT_SA}" ]; then
    echo "   STOP: service ${SVC} draait op het default-SA (serviceAccountName='${SA:-<leeg>}')."
    GEBRUIKT=1
  else
    echo "   service ${SVC}: ${SA} — OK."
  fi
done
for JOB in $(gcloud run jobs list --region="${REGION}" --format='value(metadata.name)'); do
  # NB jobs nesten in de v1-YAML één niveau dieper dan services:
  # Job.spec.template (ExecutionTemplate) .spec (ExecutionSpec) .template (TaskTemplate)
  # .spec.serviceAccountName — het pad zonder de middelste .spec leest altijd leeg
  # (vals alarm F6-run 2026-08-21: alle jobs stonden gewoon op run-jobs@).
  SA="$(gcloud run jobs describe "${JOB}" --region="${REGION}" \
        --format='value(spec.template.spec.template.spec.serviceAccountName)')"
  if [ -z "${SA}" ] || [ "${SA}" = "${DEFAULT_SA}" ]; then
    echo "   STOP: job ${JOB} draait op het default-SA (serviceAccountName='${SA:-<leeg>}')."
    GEBRUIKT=1
  else
    echo "   job ${JOB}: ${SA} — OK."
  fi
done
if [ "${GEBRUIKT}" = "1" ]; then
  echo "AFGEBROKEN: eerst die service(s)/job(s) op een eigen SA zetten (deploy.yml), dan opnieuw draaien."
  exit 1
fi

echo "== 2. Editor-rol van het default-SA af (indien aanwezig) =="
HEEFT_EDITOR="$(gcloud projects get-iam-policy "${PROJECT_ID}" \
  --flatten='bindings[].members' \
  --filter="bindings.role:roles/editor AND bindings.members:serviceAccount:${DEFAULT_SA}" \
  --format='value(bindings.members)' || true)"
if [ -n "${HEEFT_EDITOR}" ]; then
  gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEFAULT_SA}" \
    --role="roles/editor" --quiet >/dev/null
  echo "   roles/editor verwijderd van ${DEFAULT_SA}."
else
  echo "   geen roles/editor-binding (meer) — al gedaan."
fi

echo "== 3. Default-SA uitschakelen (omkeerbaar) =="
DISABLED="$(gcloud iam service-accounts describe "${DEFAULT_SA}" --format='value(disabled)')"
if [ "${DISABLED}" = "True" ]; then
  echo "   ${DEFAULT_SA} staat al uit — al gedaan."
else
  gcloud iam service-accounts disable "${DEFAULT_SA}" --quiet
  echo "   ${DEFAULT_SA} uitgeschakeld."
fi

echo
echo "Klaar. Terugdraaien kan altijd met:"
echo "  gcloud iam service-accounts enable ${DEFAULT_SA}"
