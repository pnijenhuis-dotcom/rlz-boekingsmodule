#!/usr/bin/env bash
# =============================================================================
# Registersync-koppelvlak (koppelcontract §8 v1.18, 2026-08-28): secret-slot
# REGISTERSYNC_HMAC_SECRET — container + binding + (optioneel) genereren.
#
# WIE DRAAIT DIT: Peter (owner-account). IDEMPOTENT (describe-vóór-create,
# F0-les; zelfde helpers als f4_koppelvlak.sh): herdraaien is altijd veilig;
# een secret dat al een versie heeft wordt nooit stil overschreven.
#
# Eén koppelvlak = één secret (compartimentering): dit secret is NIET het
# webhook-secret en NIET het projectaanvraag-secret. Inkomend kanaal: Vastly
# tekent `GET /koppelvlak/vastgoed/register`, wij verifiëren. WIJ zijn de bron
# van dit secret. Accessor ALLEEN run-backend@ (het endpoint draait in de
# service; geen enkele job leest dit secret — least privilege).
#
# NÁ dit script (klikpunt Peter, twee stappen):
#   1. deploy.yml: de --set-secrets-lijst van de service uitbreiden met
#        REGISTERSYNC_HMAC_SECRET=REGISTERSYNC_HMAC_SECRET:latest
#      (staat daar al als commentaarregel klaar). Bewust NIET vooraf gedaan:
#      Cloud Run weigert een revisie die naar een secret zonder versie wijst —
#      een deploy vóór dit script zou rood worden. Zonder de env-var antwoordt
#      het endpoint zichtbaar 503 `niet_geconfigureerd` (fail-closed), nooit
#      een stil fallback.
#   2. Overdracht aan Vastly via een veilig kanaal (nooit chat/git, besluit 0012):
#        gcloud secrets versions access latest --secret=REGISTERSYNC_HMAC_SECRET
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"                       # koppelcontract §2b, niet wijzigen
RUN_BACKEND="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET="REGISTERSYNC_HMAC_SECRET"

gcloud config set project "${PROJECT_ID}" --quiet
echo "== Registersync-secret voor project ${PROJECT_ID}, regio ${REGION} =="

secret_bestaat() { gcloud secrets describe "$1" >/dev/null 2>&1; }

secret_heeft_versie() {
  [[ -n "$(gcloud secrets versions list "$1" --filter="state=ENABLED" \
       --format="value(name)" --limit=1 2>/dev/null)" ]]
}

genereer_urlsafe() { # URL-safe, geen head -c (SIGPIPE + pipefail — f1-les)
  local ruw
  ruw="$(openssl rand -base64 96 | tr -d '\n' | tr '+/' '-_' | tr -d '=')"
  printf '%s' "${ruw:0:$1}"
}

secret_bestaat "${SECRET}" || gcloud secrets create "${SECRET}" \
  --replication-policy="user-managed" --locations="${REGION}"
gcloud secrets add-iam-policy-binding "${SECRET}" \
  --member="serviceAccount:${RUN_BACKEND}" \
  --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
echo "   ${SECRET}: container + accessor (alleen run-backend@) staan."

if secret_heeft_versie "${SECRET}"; then
  echo "   ${SECRET}: heeft al een versie — genereren overgeslagen (rotatie = bewuste actie)."
else
  read -r -p "   ${SECRET} nu genereren en zetten? [j/N] " antwoord
  if [[ "${antwoord}" =~ ^[jJ] ]]; then
    genereer_urlsafe 64 | gcloud secrets versions add "${SECRET}" --data-file=- >/dev/null
    echo "   ${SECRET}: versie gezet (waarde niet getoond — besluit 0012)."
  else
    echo "   Overgeslagen — container bestaat, versie volgt later."
  fi
fi

cat <<TXT

Volgende stappen (klikpunt Peter):
  1. deploy.yml → --set-secrets van de service: regel
       REGISTERSYNC_HMAC_SECRET=REGISTERSYNC_HMAC_SECRET:latest
     toevoegen (commentaarregel staat klaar) en committen → deploy.
  2. Overdracht aan Vastly via een veilig kanaal:
       gcloud secrets versions access latest --secret=${SECRET}
  3. Kanaaltest: GET https://app.administratiekantoornijenhuis.nl/koppelvlak/vastgoed/register
     mét X-Registersync-Timestamp/-Nonce/-Signature → 200 mét tellingen; zonder headers → 401.
TXT
