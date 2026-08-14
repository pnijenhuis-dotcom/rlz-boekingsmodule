#!/usr/bin/env bash
# =============================================================================
# F5 — opruimen oude Cloud SQL-instantie `rlz-sql` (besluit 0021 §6 stap 6).
#
# WAAROM VERWIJDEREN HIER MAG (expliciet gemotiveerd, akkoord Peter 2026-08-15):
# het harde principe "nooit data verwijderen" geldt voor RLZ en andere EXTERNE
# systemen en voor klant-/boekhouddata. `rlz-sql` is geen van beide: het is
# onze EIGEN infra-testinstantie met uitsluitend het Alembic-schema, het
# bootstrap-Beheerder-account en de accordeur-seed (SEED-PASSKEYTEST) — géén
# klantdata (F5-poort verbood die), alles herproduceerbaar met bestaande
# scripts. Laten staan kost ~€2/dag aan dubbele HA-instancekosten en laat een
# NIET-CMEK-instantie slingeren die verwarring kan zaaien over welke instantie
# de echte is.
#
# GUARDS: dit script weigert zolang rlz-sql2 niet RUNNABLE + CMEK-versleuteld
# is én de Cloud Run-service niet aantoonbaar op rlz-sql2 hangt. Draai het dus
# pas ná de groene verificatie (f1_migratie/f1_verificatie//health).
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"
OUD="rlz-sql"
NIEUW="rlz-sql2"
KEY_SQL_PAD="projects/${PROJECT_ID}/locations/${REGION}/keyRings/rlz/cryptoKeys/cmek-sql"

gcloud config set project "${PROJECT_ID}" --quiet

if ! gcloud sql instances describe "${OUD}" >/dev/null 2>&1; then
  echo "Instantie ${OUD} bestaat niet (meer) — niets te doen."; exit 0
fi

# Guard 1: rlz-sql2 bestaat, draait en is CMEK-versleuteld met cmek-sql.
STAAT="$(gcloud sql instances describe "${NIEUW}" --format='value(state)' 2>/dev/null || true)"
CMEK="$(gcloud sql instances describe "${NIEUW}" --format='value(diskEncryptionConfiguration.kmsKeyName)' 2>/dev/null || true)"
[[ "${STAAT}" == "RUNNABLE" ]] || { echo "STOP: ${NIEUW} is niet RUNNABLE (${STAAT:-afwezig})." >&2; exit 1; }
[[ "${CMEK}" == "${KEY_SQL_PAD}"* ]] || { echo "STOP: ${NIEUW} draagt niet de verwachte CMEK-key (${CMEK:-geen})." >&2; exit 1; }

# Guard 2: de Cloud Run-service hangt op rlz-sql2 (env + cloudsql-annotatie).
SERVICE_SQL="$(gcloud run services describe rlz-backend --region="${REGION}" \
  --format='value(spec.template.metadata.annotations."run.googleapis.com/cloudsql-instances")')"
[[ "${SERVICE_SQL}" == *":${NIEUW}"* ]] || {
  echo "STOP: rlz-backend hangt nog niet op ${NIEUW} (nu: ${SERVICE_SQL}) — eerst omhangen + /health." >&2; exit 1; }

echo "Guards groen: ${NIEUW} RUNNABLE + CMEK (${CMEK}); rlz-backend op ${SERVICE_SQL}."
echo "Te verwijderen: ${OUD} (eigen lege testinstantie — motivatie in de scriptkop)."

if [[ "${1:-}" != "--ja" ]]; then
  read -r -p "Typ '${OUD}' om definitief te verwijderen: " BEVESTIGING
  [[ "${BEVESTIGING}" == "${OUD}" ]] || { echo "Niet bevestigd — niets gedaan."; exit 1; }
fi

gcloud sql instances delete "${OUD}" --quiet
echo "KLAAR: ${OUD} verwijderd. NB de naam blijft ~1 week gereserveerd bij Google."
