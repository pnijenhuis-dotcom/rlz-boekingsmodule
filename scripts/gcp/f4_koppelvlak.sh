#!/usr/bin/env bash
# =============================================================================
# F4 — Koppelvlak vastgoed: secret-slots + bindings voor beide kanalen.
# Draaiboek: docs/F4_ACTIVATIE_RUNBOOK.md (stap 0 + stap 2 daarvan).
#
# WIE DRAAIT DIT: Peter (owner-account). IDEMPOTENT (describe-vóór-create,
# F0-les): herdraaien is altijd veilig; een secret dat al een versie heeft
# wordt nooit stil overschreven (rotatie = bewuste, aparte actie).
#
# Kan NU al, vóór vastgoeds cutover: zonder invoer maakt het alleen de
# container + binding aan (en genereert desgewenst ons eigen inkomende
# secret); de WEBHOOK_HMAC_SECRET-versie mag leeg blijven tot de uitwisseling.
#
# Twee kanalen, twee secrets (bewust NOOIT hergebruiken — config.py):
#   WEBHOOK_HMAC_SECRET         uitgaand:  wij tekenen, vastgoed verifieert.
#                               Container + accessors bestaan sinds F1
#                               (run-backend@ + run-jobs@) — hier alleen de
#                               versie-stap. Waarde komt VAN VASTGOED (of via
#                               de Secret Manager-verwijzing in vastly-504108,
#                               zie runbook stap 2 — dan hier gewoon Enter).
#   PROJECTAANVRAAG_HMAC_SECRET inkomend:  vastgoed tekent, wij verifiëren.
#                               Container ontbrak nog (F4-gap 2026-08-14).
#                               WIJ zijn de bron: dit script genereert 'm.
#                               Accessor ALLEEN run-backend@ (het endpoint
#                               draait in de service; geen enkele job leest
#                               dit secret — least privilege).
#
# SECRETS (besluit 0012): waarden nooit in code/logs/chat. Overdracht van het
# gegenereerde inkomende secret aan vastgoed: door Peter, via een veilig
# kanaal — ophalen kan met:
#   gcloud secrets versions access latest --secret=PROJECTAANVRAAG_HMAC_SECRET
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"                       # koppelcontract §2b, niet wijzigen
RUN_BACKEND="run-backend@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}" --quiet
echo "== F4-koppelvlak-secrets voor project ${PROJECT_ID}, regio ${REGION} =="

# --- Helpers (zelfde patroon als f1_data.sh) ---------------------------------
secret_bestaat() { gcloud secrets describe "$1" >/dev/null 2>&1; }

secret_heeft_versie() {
  [[ -n "$(gcloud secrets versions list "$1" --filter="state=ENABLED" \
       --format="value(name)" --limit=1 2>/dev/null)" ]]
}

maak_secret_leeg() { # alleen de container, nog geen waarde
  secret_bestaat "$1" || gcloud secrets create "$1" \
    --replication-policy="user-managed" --locations="${REGION}"
}

zet_secret_waarde_indien_leeg() { # $1=naam, waarde via stdin — nooit als argument
  if secret_heeft_versie "$1"; then
    echo "   ${1}: heeft al een versie — ongemoeid gelaten (rotatie = bewuste actie)."
  else
    gcloud secrets versions add "$1" --data-file=- >/dev/null
    echo "   ${1}: versie gezet."
  fi
}

# URL-safe genereren (geen '+', '/' of '='; bewust geen head -c i.v.m.
# SIGPIPE + pipefail — zelfde afweging als f1_data.sh).
genereer_urlsafe() {
  local ruw
  ruw="$(openssl rand -base64 96 | tr -d '\n' | tr '+/' '-_' | tr -d '=')"
  printf '%s' "${ruw:0:$1}"
}

# ----------------------------------------------------------------------------
# 1. Inkomend kanaal: PROJECTAANVRAAG_HMAC_SECRET — container + binding.
#    Binding is idempotent (add-iam-policy-binding voegt niets toe als het
#    member+role-paar al bestaat).
# ----------------------------------------------------------------------------
maak_secret_leeg PROJECTAANVRAAG_HMAC_SECRET
gcloud secrets add-iam-policy-binding PROJECTAANVRAAG_HMAC_SECRET \
  --member="serviceAccount:${RUN_BACKEND}" \
  --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
echo "   PROJECTAANVRAAG_HMAC_SECRET: container + accessor (alleen run-backend@) staan."

# 2. Inkomend secret genereren — wij zijn de bron van dit secret. 64 tekens
#    URL-safe; alleen als er nog geen versie is.
if secret_heeft_versie PROJECTAANVRAAG_HMAC_SECRET; then
  echo "   PROJECTAANVRAAG_HMAC_SECRET: heeft al een versie — genereren overgeslagen."
else
  read -r -p "   PROJECTAANVRAAG_HMAC_SECRET nu genereren en zetten? [j/N] " antwoord
  if [[ "${antwoord}" =~ ^[jJ] ]]; then
    genereer_urlsafe 64 | zet_secret_waarde_indien_leeg PROJECTAANVRAAG_HMAC_SECRET
    echo "   Overdracht aan vastgoed (veilig kanaal, nooit chat/git):"
    echo "     gcloud secrets versions access latest --secret=PROJECTAANVRAAG_HMAC_SECRET"
  else
    echo "   Overgeslagen — container bestaat, versie volgt later."
  fi
fi

# ----------------------------------------------------------------------------
# 3. Uitgaand kanaal: WEBHOOK_HMAC_SECRET-versie (waarde komt van vastgoed).
#    Container + accessors bestaan sinds F1; Enter = overslaan (bijv. bij de
#    Secret Manager-verwijzing-route via vastly-504108, runbook stap 2).
# ----------------------------------------------------------------------------
maak_secret_leeg WEBHOOK_HMAC_SECRET   # vangnet, bestaat normaliter al (F1)
if secret_heeft_versie WEBHOOK_HMAC_SECRET; then
  echo "   WEBHOOK_HMAC_SECRET: bestond al met versie."
else
  read -r -s -p "   Waarde voor WEBHOOK_HMAC_SECRET (van vastgoed; Enter = nu overslaan): " waarde
  echo
  if [[ -n "${waarde}" ]]; then
    printf '%s' "${waarde}" | zet_secret_waarde_indien_leeg WEBHOOK_HMAC_SECRET
  else
    echo "   WEBHOOK_HMAC_SECRET: overgeslagen — container bestaat, versie volgt bij de uitwisseling."
  fi
  unset waarde
fi

# ----------------------------------------------------------------------------
# 4. Verificatie (geen waarden, alleen status): welke slots hebben een versie?
# ----------------------------------------------------------------------------
echo "== Status F4-secrets (versie ja/nee, waarden blijven geheim) =="
for s in WEBHOOK_HMAC_SECRET PROJECTAANVRAAG_HMAC_SECRET; do
  if secret_heeft_versie "$s"; then
    echo "   ${s}: versie AANWEZIG"
  else
    echo "   ${s}: container zonder versie (activatie wacht — runbook stap 2)"
  fi
done
echo "== Klaar. Vervolg: docs/F4_ACTIVATIE_RUNBOOK.md =="
