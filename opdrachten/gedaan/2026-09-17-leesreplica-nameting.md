uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-leesreplica-nameting.md

# OPDRACHT 17-09 — Leesreplica: nameting ná deploy (query op de replica, IAM-login nameting@, SELECT-only bewijs)

Domeinen: werkloop-productie

Vervolg op `docs/rapporten/2026-09-17-leesreplica-afronden.md` (migratie 0157, `CLOUD_SQL_LEES`/`LEES_CLOUD_SQL_VERBINDING` in deploy.yml,
smoketest `SELECT 1` op de replica). Lees-only.

## Stap 0
- `gh run list --workflow=deploy.yml --limit 1` GROEN incl. stap 11 (smoketest) mét log "deploy-smoketest: leesreplica antwoordt (SELECT 1, READ ONLY)";
  rood op de replica-toets → letterlijke fouttekst in het rapport (socket? IAM? URL?), stoppen.
- Migratie 0157 toegepast (migratie-job groen): NOTICE of GRANT in het job-log.

## Stap 1 — meting
- `gh workflow run nameting -f onderdeel=query -f query="sync-status"` → `verkenning/lezen-17-09-sync-status.txt` (bibliotheek-query op de runtime-verbinding).
- `scripts/gcp/db_lezen.sh "SELECT 1" --als <beheerder-uuid>` (impersonatie nameting@, IAM-login op `rlz-sql2-lees`, READ ONLY) = bewijs rol + login;
  `scripts/gcp/db_lezen.sh "INSERT INTO platform.groep (naam) VALUES ('x')" --als …` hoort door de poort GEWEIGERD te worden (exit 2) = bewijs SELECT-only;
  een `POST /lezen/sql` als Beheerder (lees-only toets) geeft geen 503 meer.

## Stap 2 — afronding
BESLISSINGEN "FEITEN EERST — …" alinea "Afronding leesreplica 17-09": status → LIVE + "werkt in productie: ja/nee"; GCP_UITROL §F7.4 stand; rapport + INDEX; opdracht → gedaan.
