#!/usr/bin/env bash
# =============================================================================
# F1 — Alembic 0001→head tegen de Cloud SQL-instantie (docs/GCP_UITROL.md §F1.1)
#
# VERBINDINGSROUTE (gedocumenteerde keuze): de Cloud SQL Auth Proxy lokaal —
# IAM-authenticatie + TLS zonder authorized networks; de instantie heeft een
# publiek IP maar accepteert alleen proxy-/connectorverbindingen. Installatie:
#   brew install cloud-sql-proxy          (macOS)
# Vereist verder: gcloud ingelogd met een account dat de secrets mag lezen
# (org-owner of een account met secretAccessor + cloudsql.client) en een
# gebouwde backend-venv (make -C backend install).
#
# WAT HET DOET (idempotent — Alembic slaat gedraaide revisies zelf over):
#   1. proxy starten op 127.0.0.1:5434 (5433 is de lokale PG16)
#   2. alembic upgrade head als postgres (owner-rol: DDL/migraties); migratie
#      0001 maakt de least-privilege-rol boekhouding_app aan met APP_DB_PASSWORD
#      uit Secret Manager — precies de twee rollen zoals lokaal
#   3. metadata-guard tegen dat schema: `alembic check` (zelfde vergelijking als
#      tests/unit/test_migratie_metadata_guard.py). ⚠️ NOOIT pytest met
#      TEST_DATABASE_URL op de cloud-database richten: tests/conftest.py
#      TRUNCATE't de testdatabase — alembic check is de veilige, gelijkwaardige
#      toets (env.py importeert álle model-modules, dus de vergelijking is
#      volledig)
#   4. alembic_version tonen (verwacht: head)
#
# Wachtwoorden komen uit Secret Manager en worden nooit geëchood (besluit 0012).
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
SQL_INSTANCE="rlz-sql"
DB_NAAM="boekhouding"
PROXY_POORT="5434"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="${REPO_ROOT}/backend"

command -v cloud-sql-proxy >/dev/null || {
  echo "STOP: cloud-sql-proxy niet gevonden. Installeer: brew install cloud-sql-proxy" >&2; exit 1; }
[[ -x "${BACKEND}/.venv/bin/alembic" ]] || {
  echo "STOP: backend-venv ontbreekt. Draai eerst: make -C backend install" >&2; exit 1; }

gcloud config set project "${PROJECT_ID}" --quiet
CONNECTION_NAME="$(gcloud sql instances describe "${SQL_INSTANCE}" --format='value(connectionName)')"
echo "== Cloud SQL Auth Proxy naar ${CONNECTION_NAME} op 127.0.0.1:${PROXY_POORT} =="

cloud-sql-proxy "${CONNECTION_NAME}" --port "${PROXY_POORT}" --address 127.0.0.1 &
PROXY_PID=$!
trap 'kill "${PROXY_PID}" 2>/dev/null || true' EXIT INT TERM

# Wachten tot de proxy luistert (max ~30 s).
for _ in $(seq 1 30); do
  if (echo > "/dev/tcp/127.0.0.1/${PROXY_POORT}") 2>/dev/null; then break; fi
  sleep 1
done
(echo > "/dev/tcp/127.0.0.1/${PROXY_POORT}") 2>/dev/null || {
  echo "STOP: proxy niet bereikbaar op poort ${PROXY_POORT}." >&2; exit 1; }

OWNER_PW="$(gcloud secrets versions access latest --secret=DB_OWNER_WACHTWOORD)"
APP_DB_PASSWORD="$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)"
export APP_DB_PASSWORD  # migratie 0001 leest dit voor de rol boekhouding_app
export DATABASE_URL="postgresql+psycopg://postgres:${OWNER_PW}@127.0.0.1:${PROXY_POORT}/${DB_NAAM}"
unset OWNER_PW

cd "${BACKEND}"
echo "== alembic upgrade head (toon 'Running upgrade X -> Y'-regels) =="
.venv/bin/alembic upgrade head

echo "== metadata-guard: alembic check (model == gemigreerde cloud-database) =="
.venv/bin/alembic check

echo "== alembic_version in de cloud-database =="
.venv/bin/python - <<'PY'
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    versie = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    rollen = conn.execute(text("SELECT rolname FROM pg_roles WHERE rolname = 'boekhouding_app'")).scalars().all()
print(f"alembic_version = {versie}")
print(f"rol boekhouding_app aanwezig = {bool(rollen)}")
engine.dispose()
PY

echo "== KLAAR — F1.1/F1.2-verificatie gedaan. Volgende: f1_verificatie.py (GCS+KMS). =="
