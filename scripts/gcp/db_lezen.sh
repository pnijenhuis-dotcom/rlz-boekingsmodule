#!/usr/bin/env bash
# Feiten eerst (besluit Peter 17-09 punt 2): vrije SELECT voor CC op de LEESREPLICA `rlz-sql2-lees` via de Cloud SQL Auth Proxy
# mét IAM-authenticatie als nameting@ (SELECT-only rol `rlz_lezer`, migratie 0154; pgaudit op de replica = 100 % audit).
#   scripts/gcp/db_lezen.sh "SELECT …"  [--als <beheerder-uuid>] [--administratie <uuid>] [--max 5000]
# Amendement op de regel van 08-09: dit is een lokaal proces tegen een REPLICA met een rol die niets kan schrijven — nooit tegen
# de primary. Waarborgen: (1) alleen SELECT/WITH, één statement (dezelfde poort als app/lezen/sql_poort.py, hier in bash);
# (2) BEGIN READ ONLY; (3) app.current_actor_id = een Beheerder (RLS-scope = alles; default: env LEES_ACTOR_ID) — zonder actor
# ziet de lezer onder RLS niets; (4) rijenplafond; (5) nooit een schrijvend commando (psql -c op één string, geen scriptbestand).
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HIER/nameting_env.sh"
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
REPLICA="${REPLICA:-rlz-sql2-lees}"
DB="${DB:-boekhouding}"
POORT="${LEES_PROXY_POORT:-5440}"
IAM_DB_USER="${IAM_DB_USER:-nameting@${PROJECT}.iam}"
SQL="${1:-}"; shift || true
ALS="${LEES_ACTOR_ID:-}"; MAX=5000; ADM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --als) ALS="$2"; shift 2 ;;
    --max) MAX="$2"; shift 2 ;;
    --administratie) ADM="$2"; shift 2 ;;  # RLS-scope op één administratie (bank_mutatie e.d. hebben geen Beheerder-clausule)
    *) echo "onbekend argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "$SQL" ]] || { echo "gebruik: $0 \"SELECT …\" [--als <beheerder-uuid>] [--max N]" >&2; exit 2; }
[[ -n "$ALS" ]] || { echo "FOUT: geen Beheerder-actor (--als of env LEES_ACTOR_ID) — zonder actor ziet RLS niets; nooit raden" >&2; exit 2; }
# SELECT-only-poort (spiegel van app/lezen/sql_poort.py)
SCHOON="$(printf '%s' "$SQL" | sed -E 's/--[^\n]*//g' | tr '\n' ' ' | sed -E 's/;[[:space:]]*$//')"
[[ "$SCHOON" != *";"* ]] || { echo "FOUT: één statement per keer" >&2; exit 2; }
printf '%s' "$SCHOON" | grep -qiE '^[[:space:]]*(select|with)\b' || { echo "FOUT: alleen SELECT (of WITH … SELECT)" >&2; exit 2; }
if printf '%s' "$SCHOON" | grep -qiwE 'insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|copy|call|do|vacuum|set|reset|begin|commit|rollback|pg_read_file|pg_ls_dir|lo_import|lo_export|pg_terminate_backend|dblink|pg_sleep|set_config'; then
  echo "FOUT: schrijf-/DDL-/systeemwoord in de query — geweigerd" >&2; exit 2
fi
command -v cloud-sql-proxy >/dev/null || { echo "FOUT: cloud-sql-proxy ontbreekt (brew install cloud-sql-proxy)" >&2; exit 3; }
command -v psql >/dev/null || { echo "FOUT: psql ontbreekt" >&2; exit 3; }
CONN="$(gcloud sql instances describe "$REPLICA" --project "$PROJECT" --format='value(connectionName)' "${NAMETING_GCLOUD_FLAGS[@]}" 2>/dev/null || true)"
[[ -n "$CONN" ]] || { echo "FOUT: replica $REPLICA niet gevonden/leesbaar — klikpunt scripts/gcp/leesreplica.sh --apply (owner)" >&2; exit 3; }
PROXY_ARGS=(--port "$POORT" --auto-iam-authn "$CONN")
[[ -n "${NAMETING_SA:-}" && ${#NAMETING_GCLOUD_FLAGS[@]} -gt 0 ]] && PROXY_ARGS=(--impersonate-service-account "$NAMETING_SA" "${PROXY_ARGS[@]}")
cloud-sql-proxy "${PROXY_ARGS[@]}" >/dev/null 2>&1 &
PROXY_PID=$!
trap 'kill $PROXY_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do pg_isready -h 127.0.0.1 -p "$POORT" >/dev/null 2>&1 && break; sleep 0.5; done
echo ">> db_lezen: replica $REPLICA als $IAM_DB_USER (rol rlz_lezer), actor $ALS, max $MAX rijen — READ ONLY" >&2
psql "host=127.0.0.1 port=$POORT dbname=$DB user=$IAM_DB_USER sslmode=disable" -v ON_ERROR_STOP=1 -X -q \
  -c "BEGIN READ ONLY;" \
  -c "SELECT set_config('app.current_actor_id', '$ALS', true);" \
  -c "SELECT set_config('app.current_administratie_id', '$ADM', true);" \
  -c "SELECT set_config('statement_timeout', '60000', true);" \
  -c "SELECT * FROM ($SCHOON) AS lees LIMIT $MAX;" \
  -c "ROLLBACK;"
