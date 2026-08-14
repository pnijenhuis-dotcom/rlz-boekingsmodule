#!/usr/bin/env bash
# =============================================================================
# F2 — Services (docs/GCP_UITROL.md §F2): domein + https voor de Cloud Run-service.
#
# WIE DRAAIT DIT: Peter (org-owner-account). Code voert niets uit.
#
# WAT DIT SCRIPT NIET DOET: de service `rlz-backend` en de job `rlz-migratie` zelf —
# die maakt de deploy-workflow aan (create-or-update, .github/workflows/deploy.yml;
# eerste push naar main ná de F2-commit doet het). Dit script doet alleen wat een
# owner-account + DNS-toegang vergt: domein-verificatie + domain mapping.
#
# VOORAF (eenmalig, buiten gcloud): het domein administratiekantoornijenhuis.nl moet
# geverifieerd zijn voor het account dat dit draait. Check: stap 1 hieronder. Zo niet:
#   gcloud domains verify administratiekantoornijenhuis.nl
# (opent Webmaster Central; verificatie via een TXT-record dat Peter in de DNS zet).
#
# IDEMPOTENT (F0-les 2026-08-14): describe-vóór-create op élke resource — herdraaien
# na een deelfout is altijd veilig.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"                            # koppelcontract §2b, niet wijzigen
SERVICE="rlz-backend"
DOMEIN="app.administratiekantoornijenhuis.nl"    # beslispunt 3; apex blijft vrij voor de website

gcloud config set project "${PROJECT_ID}" --quiet

echo "== 1. Domein-verificatie check =="
# Domain mapping vereist dat het (apex-)domein geverifieerd is voor dit account.
if gcloud domains list-user-verified --format="value(id)" | grep -q "administratiekantoornijenhuis.nl"; then
  echo "   geverifieerd: administratiekantoornijenhuis.nl"
else
  echo "   NIET geverifieerd — draai eerst:  gcloud domains verify administratiekantoornijenhuis.nl"
  echo "   (TXT-record in de DNS zetten, daarna dit script opnieuw draaien)"
  exit 1
fi

echo "== 2. Service-bestaanscheck =="
# De mapping heeft de service nodig; die komt uit de eerste deploy-workflow-run.
if ! gcloud run services describe "${SERVICE}" --region="${REGION}" >/dev/null 2>&1; then
  echo "   service ${SERVICE} bestaat nog niet — eerst de deploy-workflow laten draaien"
  echo "   (GitHub → Actions → deploy → groen), daarna dit script opnieuw."
  exit 1
fi
echo "   service ${SERVICE} bestaat."

echo "== 3. Domain mapping ${DOMEIN} → ${SERVICE} =="
if gcloud beta run domain-mappings describe --domain="${DOMEIN}" --region="${REGION}" >/dev/null 2>&1; then
  echo "   mapping bestaat al — overgeslagen."
else
  gcloud beta run domain-mappings create \
    --service="${SERVICE}" \
    --domain="${DOMEIN}" \
    --region="${REGION}"
fi

echo "== 4. DNS-records (Peter zet deze bij de domeinbeheerder) =="
gcloud beta run domain-mappings describe --domain="${DOMEIN}" --region="${REGION}" \
  --format="table(status.resourceRecords[].name,status.resourceRecords[].type,status.resourceRecords[].rrdata)"
echo
echo "Klaar. Na het zetten van het DNS-record provisiont Google het managed certificaat"
echo "automatisch (kan 15 min – enkele uren duren; status: bovenstaand describe-commando)."
echo
echo "F2-slotverificatie (draaiboek): https://${DOMEIN}/health → 200; kantoor-login incl."
echo "TOTP; échte passkey-registratie + ontgrendeling op een telefoon; PDF uit de"
echo "GCS-bucket; accordeur-PWA installeerbaar."
