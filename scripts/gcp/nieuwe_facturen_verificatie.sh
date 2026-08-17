#!/usr/bin/env bash
# =============================================================================
# Nieuwe-facturen-bundelmelding — herhaalbare live-verificatie (2026-08-17).
#
# Aanleiding: de eerste handmatige run van rlz-nieuwe-facturen verstuurde niets.
# Dat was correct gedrag (run om 06:54 NL = stille uren; en het TEST-document
# was op 16-08 al goedgekeurd → 0 aan de beurt) — maar er was geen kant-en-klare
# manier om de melding wél aantoonbaar te zien. Dit script is die manier.
#
# WAT HET DOET, IN VOLGORDE (veilig opnieuw te draaien — dát is het punt):
#   1. tijdvenster-check: tussen 08:00 en 20:00 NL (daarbuiten verstuurt de job
#      per ontwerp niets — stille uren, besluit Peter 2026-08-16);
#   2. Cloud SQL Auth Proxy starten (poort 5434) als die nog niet draait;
#   3. prep: backend/scripts/cloud_verificatie_nieuwe_facturen.py — biedt
#      TEST-ACC-NOTIF-01 opnieuw ter accordering aan en reset de gemeld-claim
#      (alleen dit account + dit document, op de SEED-PASSKEYTEST-administratie);
#   4. één handmatige jobrun (--wait) + de joblog erbij.
#
# VERWACHT RESULTAAT (elke keer):
#   - push op de iPhone-PWA: "Er staat 1 factuur voor u klaar."
#   - joblog: "Nieuwe-facturen-meldingen: 1 push, 0 e-mail, 1 document(en)
#     nieuw gemeld, ..."
# Het goedkeuren van de factuur in de app is NIET nodig voor herhaling: dit
# script zet de uitgangssituatie zelf telkens opnieuw klaar.
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
REGION="europe-west4"
JOB="rlz-nieuwe-facturen"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${REPO_ROOT}/backend/.venv/bin/python"

gcloud config set project "${PROJECT_ID}" --quiet

echo "== Stap 1/4: tijdvenster (stille uren 20:00–08:00 Europe/Amsterdam) =="
UUR="$(TZ=Europe/Amsterdam date +%-H)"
if (( UUR >= 20 || UUR < 8 )); then
  echo "   Het is nu $(TZ=Europe/Amsterdam date +%H:%M) NL-tijd — stille uren."
  echo "   De job verstuurt dan per ontwerp niets. Draai dit script tussen 08:00 en 20:00."
  exit 1
fi
echo "   $(TZ=Europe/Amsterdam date +%H:%M) NL-tijd — binnen het venster."

echo
echo "== Stap 2/4: Cloud SQL Auth Proxy (poort 5434) =="
PROXY_PID=""
if nc -z 127.0.0.1 5434 2>/dev/null; then
  echo "   er luistert al iets op 5434 — bestaande proxy hergebruikt."
else
  cloud-sql-proxy "${PROJECT_ID}:${REGION}:rlz-sql2" --port 5434 --gcloud-auth &
  PROXY_PID=$!
  trap '[ -n "${PROXY_PID}" ] && kill "${PROXY_PID}" 2>/dev/null || true' EXIT
  for _ in $(seq 1 20); do
    nc -z 127.0.0.1 5434 2>/dev/null && break
    sleep 0.5
  done
  nc -z 127.0.0.1 5434 2>/dev/null || { echo "   FOUT: proxy kwam niet op."; exit 1; }
  echo "   proxy gestart (pid ${PROXY_PID})."
fi

echo
echo "== Stap 3/4: uitgangssituatie klaarzetten (prep-script) =="
APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
  "${PYTHON}" "${REPO_ROOT}/backend/scripts/cloud_verificatie_nieuwe_facturen.py"

echo
echo "== Stap 4/4: jobrun + logcontrole =="
gcloud run jobs execute "${JOB}" --region "${REGION}" --wait
EXECUTIE="$(gcloud run jobs executions list --job "${JOB}" --region "${REGION}" --limit 1 --format='value(metadata.name)')"
echo "   executie: ${EXECUTIE} — logregels (kan ~15 s op log-ingestie wachten):"
sleep 15
gcloud logging read \
  "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB}\" AND labels.\"run.googleapis.com/execution_name\"=\"${EXECUTIE}\"" \
  --format='value(textPayload)' --limit 20 | sed '/^$/d; s/^/   | /'

echo
echo "VERWACHT: push op de iPhone \"Er staat 1 factuur voor u klaar.\" en hierboven"
echo "de regel 'Nieuwe-facturen-meldingen: 1 push, 0 e-mail, 1 document(en) nieuw gemeld, ...'."
echo "Klopt dat, dan is de live-verificatie geslaagd — de scheduler hervatten kan met:"
echo "  gcloud scheduler jobs resume ${JOB} --location ${REGION}"
