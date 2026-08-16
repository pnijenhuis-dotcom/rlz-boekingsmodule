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
#   3. metadata-guard tegen dat schema: dezelfde tabelniveau-vergelijking als
#      tests/unit/test_migratie_metadata_guard.py, inline (⚠️ NOOIT pytest met
#      TEST_DATABASE_URL op de cloud-database richten: tests/conftest.py
#      TRUNCATE't de testdatabase). NB `alembic check` was hier eerder bewust
#      NIET de toets (les F1-uitvoering 2026-08-14: pre-existente model↔DDL-
#      representatiedrift); die drift is in de hygiëne-run 2026-08-16
#      gelijkgetrokken (type_annotation_map + index-declaraties in de
#      modellen) — `alembic check` is sindsdien schoon, maar deze snelle
#      tabelniveau-vergelijking blijft als onafhankelijke cloud-toets staan.
#   4. alembic_version tonen (verwacht: head)
#
# Wachtwoorden komen uit Secret Manager en worden nooit geëchood (besluit 0012).
# =============================================================================
set -euo pipefail

PROJECT_ID="rlz-boekhouding"
SQL_INSTANCE="rlz-sql2"   # F5/besluit 0021: CMEK-herbouw (was rlz-sql t/m 2026-08-14)
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

echo "== metadata-guard: tabelniveau-vergelijking model == gemigreerde cloud-database =="
# Zelfde vergelijking als tests/unit/test_migratie_metadata_guard.py, maar tegen
# DATABASE_URL (de cloud-database) i.p.v. de testdatabase. Zie kopcommentaar
# waarom `alembic check` hier niet bruikbaar is.
.venv/bin/python - <<'PY'
import importlib
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect

BEWUST_ZONDER_MODEL = {"platform.alembic_version", "public.alembic_version"}

for pad in sorted(Path("app").rglob("models.py")):
    importlib.import_module(".".join(pad.with_suffix("").parts))
from app.db.models import Base

meta_tabellen = {f"{t.schema}.{t.name}" for t in Base.metadata.tables.values()}
engine = create_engine(os.environ["DATABASE_URL"])
try:
    inspector = inspect(engine)
    db_tabellen = {
        f"{schema}.{tabel}"
        for schema in ("platform", "boekhouding")
        for tabel in inspector.get_table_names(schema=schema)
    } - BEWUST_ZONDER_MODEL
finally:
    engine.dispose()

zonder_model = sorted(db_tabellen - meta_tabellen)
zonder_migratie = sorted(meta_tabellen - db_tabellen)
if zonder_model or zonder_migratie:
    raise SystemExit(
        f"METADATA-GUARD FAALT — in cloud-DB zonder model: {zonder_model}; "
        f"in model zonder cloud-tabel: {zonder_migratie}"
    )
print(f"OK: {len(meta_tabellen)} modeltabellen == {len(db_tabellen)} cloud-tabellen (platform+boekhouding).")
PY

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
