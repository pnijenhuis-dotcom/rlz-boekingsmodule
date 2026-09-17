#!/usr/bin/env bash
# Feiten eerst (besluit Peter 17-09, BESLISSINGEN "FEITEN EERST — LEES-ONLY DB-/RLZ-TOEGANG VOOR ANALYSES + KLIKPUNT-GUARD"):
# Cloud SQL-LEESREPLICA van `rlz-sql2` + IAM-databasetoegang voor het nameting-SA op de SELECT-only rol `rlz_lezer` (migratie 0154).
#   scripts/gcp/leesreplica.sh            → toont wat er gedaan zou worden (dry-run)
#   scripts/gcp/leesreplica.sh --apply    → voert uit (OWNER; eenmalig, idempotent waar Cloud SQL dat toelaat)
# Stappen:
#   1. leesreplica `rlz-sql2-lees` (zelfde regio, zelfde CMEK-key `cmek-sql`, tier instelbaar) mét database-flags
#      cloudsql.iam_authentication=on (IAM-login) + cloudsql.enable_pgaudit=on + pgaudit.log=read (100 % audit van élke leesquery);
#      ⚠️ flags op de PRIMARY worden geërfd; een replica kán eigen flags dragen — hier zetten we ze op de replica.
#   2. IAM-databasegebruiker `nameting@rlz-boekhouding.iam` op de PRIMARY (gebruikers repliceren mee) + projectrollen
#      roles/cloudsql.client + roles/cloudsql.instanceUser voor nameting@ (verbinden via Auth Proxy mét --auto-iam-authn).
#   3. GRANT rlz_lezer TO "nameting@rlz-boekhouding.iam" — psql op de primary als postgres (wachtwoord uit Secret Manager, alleen in
#      deze owner-sessie); de rol zelf komt uit migratie 0154 (deploy vóór deze stap).
# Daarna: env LEES_DATABASE_URL op service én jobs (deploy.yml) = postgresql+psycopg://<app-rol>@/boekhouding?host=/cloudsql/<replica-connection>
# (de service leest de replica via de Cloud SQL-connector, zelfde rol als nu) — en `scripts/gcp/db_lezen.sh` voor CC.
set -euo pipefail
PROJECT="${PROJECT:-rlz-boekhouding}"
REGION="${REGION:-europe-west4}"
PRIMARY="${PRIMARY:-rlz-sql2}"
REPLICA="${REPLICA:-rlz-sql2-lees}"
TIER="${TIER:-db-custom-1-3840}"
NAMETING_SA="nameting@${PROJECT}.iam.gserviceaccount.com"
IAM_DB_USER="nameting@${PROJECT}.iam"
KMS_KEY="projects/${PROJECT}/locations/${REGION}/keyRings/rlz/cryptoKeys/cmek-sql"
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
run() { echo "+ $*"; [[ $APPLY -eq 1 ]] && "$@"; return 0; }
echo "project=$PROJECT primary=$PRIMARY replica=$REPLICA tier=$TIER (dry-run: $((1-APPLY)))"

# 1. replica
if gcloud sql instances describe "$REPLICA" --project "$PROJECT" --format='value(name)' >/dev/null 2>&1; then
  echo "= replica $REPLICA bestaat al — create overgeslagen; flags worden (opnieuw) gezet"
else
  run gcloud sql instances create "$REPLICA" --project "$PROJECT" --master-instance-name "$PRIMARY" --region "$REGION" \
    --tier "$TIER" --availability-type ZONAL --disk-encryption-key "$KMS_KEY" \
    --database-flags "cloudsql.iam_authentication=on,cloudsql.enable_pgaudit=on,pgaudit.log=read"
fi
run gcloud sql instances patch "$REPLICA" --project "$PROJECT" \
  --database-flags "cloudsql.iam_authentication=on,cloudsql.enable_pgaudit=on,pgaudit.log=read" --quiet

# 2. IAM-databasegebruiker + projectrollen (op de PRIMARY: gebruikers repliceren mee)
if gcloud sql users list --instance "$PRIMARY" --project "$PROJECT" --format='value(name)' 2>/dev/null | grep -qx "$IAM_DB_USER"; then
  echo "= IAM-databasegebruiker $IAM_DB_USER bestaat al"
else
  run gcloud sql users create "$IAM_DB_USER" --instance "$PRIMARY" --project "$PROJECT" --type cloud_iam_service_account
fi
run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$NAMETING_SA" --role roles/cloudsql.client --condition=None
run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$NAMETING_SA" --role roles/cloudsql.instanceUser --condition=None

# 3. GRANT rlz_lezer (rol uit migratie 0154 — deploy eerst)
cat <<SQL
= daarna als postgres op de primary (psql via de Auth Proxy, wachtwoord uit Secret Manager, alleen in deze owner-sessie):
    GRANT rlz_lezer TO "$IAM_DB_USER";
    -- controle:
    SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('rlz_lezer', '$IAM_DB_USER');
= controle replica: gcloud sql instances describe $REPLICA --format='value(state,masterInstanceName,settings.databaseFlags)'
= verbindingsnaam voor LEES_DATABASE_URL / db_lezen.sh: $(gcloud sql instances describe "$REPLICA" --project "$PROJECT" --format='value(connectionName)' 2>/dev/null || echo "${PROJECT}:${REGION}:${REPLICA}")
SQL
echo "klaar (dry-run: $((1-APPLY)))"
