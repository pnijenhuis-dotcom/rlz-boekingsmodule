#!/usr/bin/env bash
# =============================================================================
# Accordeur-notificaties — infra (berichten-bouwsteen 2026-08-15).
#
# NB: voor de VOLLEDIGE afronding (slots + VAPID-generatie + wachtwoord-invoer +
# deploy + job-run + scheduler-resume in één interactieve gang) is er sinds
# 2026-08-15 scripts/gcp/notificaties_afronden.sh — dat omvat dit script.
#
# WIE DRAAIT DIT: het org-owner-account (Peter) — secret-slots, IAM-accessors en
# scheduler-resume vergen rechten die deploy@ bewust niet heeft (zelfde grondhouding als
# scripts/gcp/f3_jobs.sh). IDEMPOTENT: describe-vóór-create op elke resource.
#
# WAT DIT SCRIPT DOET
#   1. Drie secret-slots klaarzetten (zonder waarde):
#        BERICHTEN_SMTP_WACHTWOORD  — Google Workspace app-wachtwoord van het verzendadres
#        PUSH_VAPID_PRIVATE_KEY     — Web Push VAPID private key (geheim)
#        PUSH_VAPID_PUBLIC_KEY      — VAPID public key (geen geheim, maar zelfde slot-flow
#                                     zodat sleutelpaar altijd samen roteert)
#      + accessors: run-jobs@ (herinnering-job) en run-backend@ (uitnodigingsmail + het
#      push-config-endpoint; de PRIVATE key krijgt bewust GEEN run-backend@-accessor).
#   2. (Toont) hoe de waarden erin gaan — via stdin, nooit als argument/in chat.
#   3. Ná de live-verificatie: scheduler rlz-accordeur-herinneringen hervatten.
#
# VOORAF NODIG (handwerk Peter, geen gcloud):
#   - Verzendadres = facturen@ak-nijenhuis.nl (BESLUIT Peter 2026-08-15: geen aparte
#     gebruiker/licentie; Reply-To p.nijenhuis@kempengroep.nl houdt antwoorden buiten de
#     intake). App-wachtwoord genereren op het facturen@-account (label "RLZ berichten" —
#     apart van het IMAP-app-wachtwoord, zodat roteren onafhankelijk kan).
#   - VAPID-sleutelpaar genereren: backend/.venv/bin/python scripts/genereer_vapid_sleutels.py
#     (éénmalig; een nieuwe private key maakt alle bestaande push-subscripties ongeldig).
#
# NB de job-definitie zelf (rlz-accordeur-herinneringen) + envs/secrets-mounts komen uit
# .github/workflows/deploy.yml; job-IAM + scheduler (GEPAUZEERD) uit f3_jobs.sh. Volgorde:
# dit script → deploy (of f3_jobs.sh met F3_IMAGE_OVERRIDE) → verificatie → stap 3.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"
JOBS_SA="run-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
BACKEND_SA="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}" --quiet

echo "== 1. Secret-slots (zonder waarde) + accessors =="
maak_slot() {
  local NAAM="$1"
  if gcloud secrets describe "${NAAM}" >/dev/null 2>&1; then
    echo "   secret ${NAAM} bestaat al."
  else
    gcloud secrets create "${NAAM}" --replication-policy=user-managed --locations="${REGION}"
    echo "   secret-slot ${NAAM} aangemaakt (nog géén versie)."
  fi
}
geef_accessor() {
  local NAAM="$1" SA="$2"
  gcloud secrets add-iam-policy-binding "${NAAM}" \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
  echo "   ${NAAM}: accessor ${SA} staat."
}

maak_slot BERICHTEN_SMTP_WACHTWOORD
geef_accessor BERICHTEN_SMTP_WACHTWOORD "${JOBS_SA}"
geef_accessor BERICHTEN_SMTP_WACHTWOORD "${BACKEND_SA}"

maak_slot PUSH_VAPID_PRIVATE_KEY
geef_accessor PUSH_VAPID_PRIVATE_KEY "${JOBS_SA}"
# Bewust GEEN run-backend@: alleen de herinnering-job verstuurt push (least privilege).

maak_slot PUSH_VAPID_PUBLIC_KEY
geef_accessor PUSH_VAPID_PUBLIC_KEY "${JOBS_SA}"
geef_accessor PUSH_VAPID_PUBLIC_KEY "${BACKEND_SA}"

echo
echo "== 2. Waarden toevoegen (handwerk — via stdin, NOOIT als argument of in chat) =="
echo "   printf '%s' '<app-wachtwoord>'  | gcloud secrets versions add BERICHTEN_SMTP_WACHTWOORD --data-file=-"
echo "   printf '%s' '<private-key-b64>' | gcloud secrets versions add PUSH_VAPID_PRIVATE_KEY  --data-file=-"
echo "   printf '%s' '<public-key-b64>'  | gcloud secrets versions add PUSH_VAPID_PUBLIC_KEY   --data-file=-"
echo "   (sleutels uit: backend/.venv/bin/python scripts/genereer_vapid_sleutels.py)"
echo
echo "== 3. Daarna: deploy opnieuw draaien (mount de secrets), dan live verifiëren =="
echo "   - één handmatige run:  gcloud run jobs execute rlz-accordeur-herinneringen --region=${REGION} --wait"
echo "     (met ≥1 accordeur mét open accordering: verwacht 1 push op de iPhone-PWA of 1 mail)"
echo "   - pas ná groene verificatie de cadans aan:"
echo "     gcloud scheduler jobs resume rlz-accordeur-herinneringen --location=${REGION}"
