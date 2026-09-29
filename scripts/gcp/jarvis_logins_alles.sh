#!/usr/bin/env bash
# Jarvis-logins 29-09 — ALLES IN ÉÉN RUN (owner-sessie, éénmalig).
# Stap 0 IAM → stap 1 wacht op deploy → stap 2 dry-run → stap 3 executie → stap 4 meetlat.
# Stopt bij de eerste afwijking. Toont nooit een waarde (besluit 0012).
set -euo pipefail
cd "$(dirname "$0")/../.."
P=rlz-boekhouding; R=europe-west4; J=rlz-reconciliatie
LOG="docs/rapporten/2026-09-29-credential-naar-secretmanager.terminal.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%F %T') stap 0 — IAM"
bash scripts/gcp/credential_naar_secretmanager_iam.sh

echo "=== stap 1 — wachten tot de image het commando draagt (max 30 min)"
SHA=$(git rev-parse --short HEAD)
for i in $(seq 1 60); do
  IMG=$(gcloud run jobs describe $J --region $R --project $P --format="value(spec.template.spec.template.spec.containers[0].image)")
  echo "   image: $IMG"
  if gcloud run jobs execute $J --region $R --project $P --wait --args="^|^-m|app.cli|credential-naar-secretmanager|--help" >/dev/null 2>&1; then break; fi
  [ $i -eq 60 ] && { echo "FOUT: commando na 30 min nog niet op de image — deploy nakijken"; exit 1; }
  sleep 30
done

echo "=== stap 2 — dry-run"
gcloud run jobs execute $J --region $R --project $P --wait --args="^|^-m|app.cli|credential-naar-secretmanager|--dry-run"
echo "=== stap 3 — executie"
gcloud run jobs execute $J --region $R --project $P --wait --args="^|^-m|app.cli|credential-naar-secretmanager"
echo "=== stap 4 — meetlat (verwacht 18 × '1 ENABLED')"
n=0
for X in UNIVERSAL_NEDERLAND UNIVERSAL_VERKOOP UNIVERSAL_MATERIAAL UNIVERSAL_STEIGERBOUW BWC_STEIGERS BRADWOLFF_CONSTRUCTIE INPENSAS_BEHEER BRADWOLFF_HOLDING DE_WIT_BEHEER_OSS; do
  for S in RLZ_WS_USER_$X RLZ_WS_PASSWORD_$X; do
    V=$(gcloud secrets versions list "$S" --project $P --filter="state=ENABLED" --format="value(name)" | tr '\n' ' ')
    echo "   $S: ${V:-GEEN}"; [ -n "$V" ] && n=$((n+1))
  done
done
echo "=== KLAAR: $n van 18 secrets hebben een actieve versie. Log: $LOG"
