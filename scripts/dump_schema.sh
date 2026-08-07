#!/bin/sh
# Ververst de referentie-dump backend/migrations/schema_referentie.sql vanaf
# boekhouding_test (die door de testsuite/afsluitroutine op migratie-head staat).
# Onderdeel van de migratie-afsluitroutine (CLAUDE.md, vastgoed-patroon geadopteerd
# 2026-08-07): na elke nieuwe migratie draaien en de dump meecommitten.
#
# Alembic (backend/migrations/versions/) blijft de bron van waarheid; deze dump is
# leesbaarheids-/reviewreferentie — nooit met de hand bewerken.
set -eu

cd "$(dirname "$0")/.."
DB="${1:-boekhouding_test}"

# pg_dump moet de serverversie matchen (PG16 op poort 5433, zie backend/Makefile).
# Override mogelijk via PG_DUMP=/pad/naar/pg_dump.
PG_DUMP="${PG_DUMP:-/opt/homebrew/opt/postgresql@16/bin/pg_dump}"
PSQL="${PSQL:-/opt/homebrew/opt/postgresql@16/bin/psql}"

HEAD=$("$PSQL" -h localhost -p 5433 -U postgres -d "$DB" -t -A -c "SELECT version_num FROM alembic_version")
{
  echo "-- ============================================================================="
  echo "-- GEGENEREERD BESTAND — NIET MET DE HAND BEWERKEN."
  echo "-- Alembic (backend/migrations/versions/) is de bron van waarheid voor het schema;"
  echo "-- dit bestand is een referentie-dump voor leesbaarheid en code-review."
  echo "-- Regenereren: scripts/dump_schema.sh (pg_dump --schema-only $DB @ head)."
  echo "-- Migratie-head bij deze dump: $HEAD"
  echo "-- ============================================================================="
  # pg_dump >= 18 voegt psql-metacommando's (\restrict/\unrestrict) toe; die horen niet in
  # een SQL-referentiebestand (vastgoed-les, doc-sync 07-08-2026).
  "$PG_DUMP" -h localhost -p 5433 -U postgres --schema-only --no-owner --no-privileges "$DB" \
    | sed '/^\\restrict/d; /^\\unrestrict/d'
} > backend/migrations/schema_referentie.sql

echo "schema_referentie.sql ververst vanaf $DB (head $HEAD)"
