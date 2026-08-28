#!/usr/bin/env bash
# =============================================================================
# Native push (fase 3, Android/FCM) — afronding verzendkant, spiegel van
# apns_afronden.sh maar ZONDER secret: Firebase is op 28-08 aan HETZELFDE GCP-
# project (rlz-boekhouding) toegevoegd, dus de backend verstuurt via FCM HTTP v1
# met de eigen Cloud Run-identiteit (Application Default Credentials via de
# metadata-server) — géén service-account-key, niets te roteren.
#
# WIE DRAAIT DIT: het org-owner-account (eenmalig; idempotent, veilig opnieuw).
# Uitgevoerd op 2026-08-28 (owner-account) — zie BESLISSINGEN "ANDROID-BOUWRONDE 28-08".
#
# WAT ER GEBEURT, IN VOLGORDE:
#   1. API-check: fcm.googleapis.com moet aan staan (Firebase-toevoeging deed dat al;
#      hier alleen controleren, nooit stil inschakelen).
#   2. IAM: roles/firebasecloudmessaging.admin voor run-jobs@ (notificatie-jobs
#      versturen) én run-backend@ (handmatige herinner-knop verstuurt vanuit de
#      service; registratie-endpoint is fail-closed 409 zonder config). Least
#      privilege: dit is de smalste voorgedefinieerde rol met
#      cloudmessaging.messages.create.
#   3. FCM_PROJECT_ID op service + de twee notificatie-jobs per direct (spiegel van
#      de deploy.yml-stappen; de eerstvolgende deploy herbevestigt exact dezelfde
#      config). Geen geheim — het project-id staat ook in google-services.json.
#   4. Verificatie zonder toestel: policy-troubleshoot bewijst dat beide identiteiten
#      cloudmessaging.messages.create hebben, en een validate_only-call tegen de
#      FCM v1-API met een bewust ongeldig token bewijst dat de API voor dit project
#      antwoordt (verwacht: 400 INVALID_ARGUMENT — niet 403/404). Het echte
#      ontvangstbewijs is de Android-kliktest (PLAY_DRAAIBOEK.md §8).
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"
JOBS_SA="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
BACKEND_SA="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"
FCM_ROL="roles/firebasecloudmessaging.admin"

gcloud config set project "${PROJECT_ID}" --quiet

echo "== Stap 1/4: FCM-API ingeschakeld? =="
if gcloud services list --enabled --format="value(config.name)" | grep -qx "fcm.googleapis.com"; then
  echo "   fcm.googleapis.com staat aan."
else
  echo "   FOUT: fcm.googleapis.com staat NIET aan — voeg Firebase toe aan het project via"
  echo "   console.firebase.google.com (Analytics UIT) en draai dit script opnieuw. Gestopt."
  exit 1
fi

echo
echo "== Stap 2/4: IAM ${FCM_ROL} voor run-jobs@ + run-backend@ (idempotent) =="
for SA in "${JOBS_SA}" "${BACKEND_SA}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA}" \
    --role="${FCM_ROL}" \
    --condition=None --quiet >/dev/null
  echo "   ${SA}: ${FCM_ROL} staat."
done

echo
echo "== Stap 3/4: FCM_PROJECT_ID op service + notificatie-jobs (spiegel van deploy.yml) =="
gcloud run services update rlz-backend \
  --region "${REGION}" \
  --update-env-vars "FCM_PROJECT_ID=${PROJECT_ID}" \
  --quiet
echo "   rlz-backend bijgewerkt (FCM-registratie-endpoint is ná de code-deploy open i.p.v. 409)."
for NJOB in rlz-accordeur-herinneringen rlz-nieuwe-facturen; do
  gcloud run jobs update "${NJOB}" \
    --region "${REGION}" \
    --update-env-vars "FCM_PROJECT_ID=${PROJECT_ID}" \
    --quiet
  echo "   ${NJOB} bijgewerkt."
done

echo
echo "== Stap 4/4: verificatie zonder toestel =="
# Binding-check via de policy zelf (policy-troubleshoot vergt een extra API — die schakelen we
# niet in voor één check). De rol bevat cloudmessaging.messages.create (gcloud iam roles describe).
LEDEN="$(gcloud projects get-iam-policy "${PROJECT_ID}" \
  --flatten="bindings[].members" --filter="bindings.role:${FCM_ROL}" --format="value(bindings.members)")"
for SA in "${JOBS_SA}" "${BACKEND_SA}"; do
  if printf '%s\n' "${LEDEN}" | grep -qx "serviceAccount:${SA}"; then
    echo "   ${SA} → ${FCM_ROL} (cloudmessaging.messages.create): GRANTED"
  else
    echo "   FOUT: ${SA} staat niet in de ${FCM_ROL}-binding."; exit 1
  fi
done
# validate_only tegen de echte API: een bewust ongeldig token → 400 INVALID_ARGUMENT bewijst
# dat de API voor dit project luistert (403 = IAM/API-probleem, 404 = verkeerd project).
WERK="$(mktemp)"
HTTP="$(curl -s -o "${WERK}" -w '%{http_code}' \
  -X POST "https://fcm.googleapis.com/v1/projects/${PROJECT_ID}/messages:send" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
  -d '{"validate_only":true,"message":{"token":"ongeldig-testtoken","notification":{"title":"t","body":"b"},"data":{"url":"/accordeur"}}}')"
echo "   FCM v1 validate_only (ongeldig token) → HTTP ${HTTP}: $(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); e=d.get("error",{}); print(e.get("status"), "-", e.get("message","")[:90])' "${WERK}" 2>/dev/null || cat "${WERK}")"
rm -f "${WERK}"
if [ "${HTTP}" != "400" ]; then
  echo "   FOUT: verwachtte 400 INVALID_ARGUMENT (token ongeldig = API luistert) — gestopt."
  exit 1
fi
echo
echo "KLAAR. Ontvangstbewijs op een Android-toestel = native/PLAY_DRAAIBOEK.md §8 (meldingen"
echo "aanzetten in de app → handmatige herinner-knop of een run van rlz-accordeur-herinneringen)."
