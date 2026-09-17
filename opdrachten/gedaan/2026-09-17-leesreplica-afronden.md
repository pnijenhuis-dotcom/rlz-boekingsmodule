uitgevoerd 2026-09-17, rapport: docs/rapporten/2026-09-17-leesreplica-afronden.md

# OPDRACHT 17-09 — Leesreplica afronden: GRANT als migratie + `LEES_DATABASE_URL` in deploy.yml + nameting

**Stand (Peter 17-09 ~13:50, owner-sessie, `scripts/gcp/leesreplica.sh --apply` gelukt ná twee scriptfixes door Cowork):**
- Replica `rlz-sql2-lees` RUNNABLE, europe-west4-c, POSTGRES_16, tier db-custom-1-3840, **edition ENTERPRISE**, ZONAL; flags
  `cloudsql.iam_authentication=on`, `cloudsql.enable_pgaudit=on`, `pgaudit.log=read` gezet (patch gelukt). CMEK geërfd van de primary
  (`--disk-encryption-key` mag NIET bij een replica in dezelfde regio — scriptfix + les in het script).
- IAM-DB-gebruiker `nameting@rlz-boekhouding.iam` aangemaakt op de primary; projectrollen `roles/cloudsql.client` +
  `roles/cloudsql.instanceUser` voor nameting@ toegekend.
- Verbindingsnaam: `rlz-boekhouding:europe-west4:rlz-sql2-lees`.
- Scriptfixes (`--edition=enterprise`, geen `--disk-encryption-key`) staan al in de werkboom — meenemen in de commit.
- Bucket-IAM: `run-backend@` heeft nu `roles/storage.objectViewer` op `gs://rlz-boekhouding-app-bundels` (klikpunt OTA gedaan).

## Te doen (geen Terminal-werk voor Peter meer)
1. **GRANT als Alembic-migratie 0157** (schema-only, idempotent): `GRANT rlz_lezer TO "nameting@rlz-boekhouding.iam"` — alleen als de
   rol bestaat (`DO $$ … IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nameting@rlz-boekhouding.iam') …`), anders overslaan mét
   NOTICE (lokale dev-DB kent die IAM-rol niet). Downgrade = REVOKE onder dezelfde voorwaarde. Afsluitroutine (dev-DB, live 200, dump).
   Controleer eerst dat 0154 (rol `rlz_lezer`) in productie gedeployd is (`gcloud run services describe rlz-backend` image = commit ≥ 0154).
2. **`LEES_DATABASE_URL`** op service én jobs in deploy.yml (één envset-stap, guard `test_deploy_yml_envset_compleet.py`): waarde volgens
   GCP_UITROL §F7.4 mét connection `rlz-boekhouding:europe-west4:rlz-sql2-lees` en `--add-cloudsql-instances` voor de replica op service
   én jobs (anders geen socket). Smoketest: `POST /lezen/sql` geeft geen 503 meer (lees-only toets).
3. **Nameting ná deploy** via `gh workflow run nameting.yml` onderdeel `query`: één bibliotheek-query + één vrije SELECT (`SELECT 1`) op de
   replica; `scripts/gcp/db_lezen.sh "SELECT 1"` als nameting@ (impersonatie) — bewijs dat rol + IAM-login + READ ONLY werken; een
   INSERT moet weigeren (bewijs SELECT-only).
4. GCP_UITROL §F7.4 bijwerken met de werkelijke stand (edition, geen CMEK-flag, IP), BESLISSINGEN-rij "FEITEN EERST …" status → LIVE
   ná stap 3; rapport + INDEX mét "werkt in productie: ja/nee".
