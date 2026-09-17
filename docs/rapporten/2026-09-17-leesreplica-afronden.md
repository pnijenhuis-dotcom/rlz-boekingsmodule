# Rapport 17-09 — Leesreplica afronden: GRANT als migratie 0157 + `LEES_CLOUD_SQL_VERBINDING` op service/jobs/smoketest + replica-toets in de smoketest

Opdracht: `opdrachten/gedaan/2026-09-17-leesreplica-afronden.md`. Migratie 0157 (schema-only, voorwaardelijke GRANT).
**Werkt in productie: niet gemeten** — meetbaar ná deploy (vervolg `opdrachten/inbox/2026-09-17-leesreplica-nameting.md`). Stap 0154-in-productie: ja (deploy `7418cd5` groen incl. migratie-job, head 0156).

## Stand (Peter, owner-sessie 17-09 ~13:50) — overgenomen in GCP_UITROL §F7.4
Replica `rlz-sql2-lees` RUNNABLE (europe-west4-c, POSTGRES_16, db-custom-1-3840, **ENTERPRISE**, ZONAL), flags IAM-auth + pgaudit `read`; **CMEK geërfd** (geen `--disk-encryption-key` bij een replica in dezelfde regio — scriptfix, mét `--edition=enterprise`, meegecommit); IAM-DB-gebruiker `nameting@rlz-boekhouding.iam` + `roles/cloudsql.client`/`instanceUser`; verbindingsnaam `rlz-boekhouding:europe-west4:rlz-sql2-lees`.

## Gedaan
1. **Migratie 0157** `rlz_lezer_grant_iam_nameting`: `GRANT rlz_lezer TO "nameting@rlz-boekhouding.iam"` alleen als de IAM-rol én `rlz_lezer` bestaan (anders NOTICE); downgrade = REVOKE onder dezelfde voorwaarde. Afsluitroutine: dev-DB `alembic upgrade head` 0156 → 0157 (NOTICE lokaal), `alembic check` "No new upgrade operations detected", `scripts/dump_schema.sh` ververst (head 0157), tijdelijke backend op de dev-DB: `GET /health` 200.
2. **deploy.yml**: `CLOUD_SQL_LEES` in het env-blok; `--set-cloudsql-instances "${CLOUD_SQL},${CLOUD_SQL_LEES}"` op de service, álle F3-jobs (lus) en de smoketest-job — de migratie-job blijft primary-only; `LEES_CLOUD_SQL_VERBINDING=${CLOUD_SQL_LEES}` in de service-envset, `BASIS_ENVS` en de smoketest-envset (één envset-stap, geen losse update). Guards: `test_deploy_yml_envset_compleet.py` (+ `test_leesreplica_socket_en_env_op_service_en_alle_jobs_behalve_de_migratie`), sleutel toegevoegd aan `SERVICE_ENV_SLEUTELS`; `test_deploy_kvk_config.py` gerepareerd (was op HEAD al rood: de regex stopte niet op `|`).
3. **config.py**: `lees_cloud_sql_verbinding` → composeert `lees_database_url` mét het app-wachtwoord op de replica-socket; expliciete `LEES_DATABASE_URL` wint; nooit het owner-wachtwoord. Tests `test_config_cloud_sql.py` (+2).
4. **Smoketest** `_smoketest_leesreplica`: `SELECT 1` in READ ONLY op de replica zodra geconfigureerd — fout = deploy rood; niet geconfigureerd = overgeslagen mét melding.
5. GCP_UITROL §F7.4 = werkelijke stand + nameting-recept; BESLISSINGEN "FEITEN EERST …" alinea "Afronding leesreplica 17-09"; CLAUDE.md-regel.

## Nameting ná deploy (vervolg-opdracht)
Smoketest-log "deploy-smoketest: leesreplica antwoordt (SELECT 1, READ ONLY)"; `gh workflow run nameting -f onderdeel=query -f query=sync-status`; `scripts/gcp/db_lezen.sh "SELECT 1" --als <beheerder-uuid>` (IAM-login als nameting@) + een INSERT die door de poort geweigerd wordt = bewijs SELECT-only; `POST /lezen/sql` geen 503 → status LIVE.

## Klikpunt Peter
Geen (alles via deploy). Beslispunt: geen — de replica leest als `boekhouding_app` (app-rol), de IAM-gebruiker `nameting@` is voor CC/Cowork via de Auth Proxy.

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/werkloop-productie.md` (55 regels)
- `docs/regels/administraties-instellingen.md` (114 regels)
