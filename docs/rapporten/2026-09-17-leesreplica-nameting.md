# Rapport 17-09 — Leesreplica: nameting ná deploy `ef48eec` (query op de replica, IAM-login nameting@, SELECT-only bewijs)

Opdracht: `opdrachten/gedaan/2026-09-17-leesreplica-nameting.md` (vervolg op `2026-09-17-leesreplica-afronden.md`). Lees-only: geen migratie,
geen writes, geen deploy-handelingen. Meting 17-09 ~17:30–17:45 CEST.

**Werkt in productie: JA** — de leesreplica-keten (migratie 0157, `LEES_CLOUD_SQL_VERBINDING`, smoketest, IAM-login als `nameting@`, SELECT-only
rol) staat en is op vier onafhankelijke manieren nagemeten. Eén onderdeel is niet direct gemeten: `POST /lezen/sql` als Beheerder (zie Klikpunt).

## Stap 0 — deploy en migratie
| Toets | Uitkomst |
|---|---|
| Laatste deploy | run 35239577138 op `ef48eec` (draagt commit `1002125` mét migratie 0157 en de deploy.yml-wijziging): **success**, alle stappen incl. Post-deploy-smoketest |
| Smoketest-log (Cloud Logging, executie `rlz-smoketest-46zjr`) | letterlijk: `deploy-smoketest: leesreplica antwoordt (SELECT 1, READ ONLY)` + `alles groen (…, leesreplica)`; service en 15 jobs op `ef48eec` |
| Migratie-job (executie `rlz-migratie-lg5ns`) | `Running upgrade 0156 -> 0157, Leesreplica afronden …` — de NOTICE-/GRANT-tak zelf staat niet in het job-log (psycopg-notices worden niet gelogd); de GRANT is bewezen via stap 1c |

Een volgende deploy (`4f13d1f`, run 35240809763) liep tijdens deze meting nog; de meting is op `ef48eec` gedaan, de code-inhoud is voor dit onderdeel gelijk.

## Stap 1 — meting
**a. Bibliotheek-query op de runtime-verbinding (Cowork-pad).** `gh workflow run nameting.yml -f onderdeel=query -f query=sync-status` → run 35241571375
success; bot-commit `c875e07` "nameting 17-09 query — db-lezen sync-status — 289 rij(en) over 77 administratie(s)" → `verkenning/lezen-17-09-sync-status.txt`
(295 regels, 929 ms). Inhoud: laatste `administratie_sync_run`/`bank_sync_run` per administratie; bank-sync 17-09 05:04–05:06 UTC overal `klaar`.

**b. IAM-login + rol op de replica (`scripts/gcp/db_lezen.sh`, impersonatie `nameting@`, Auth Proxy `--auto-iam-authn`, `rlz-sql2-lees`):**
```
 een |         current_user         | is_rlz_lezer | ro | replica
-----+------------------------------+--------------+----+---------
   1 | nameting@rlz-boekhouding.iam | t            | on | t
```
(`pg_has_role(current_user,'rlz_lezer','member')`, `current_setting('transaction_read_only')`, `pg_is_in_recovery()`.) Met `--als 2f2262cd-0423-4910-b7b5-335ba37a6ef5`
(Peter, actieve Beheerder) geeft `platform.current_actor_is_beheerder()` = t — RLS-scope werkt op de replica zoals op de primary.

**c. SELECT-only op DB-niveau (onafhankelijk van de bash-poort):** `information_schema.role_table_grants` voor `rlz_lezer` = uitsluitend `SELECT` op
171 tabellen, geen andere privilege_type; `pg_roles`: `rlz_lezer` en `nameting@rlz-boekhouding.iam` beide super/createrole/createdb/bypassrls = f, alleen de
IAM-gebruiker canlogin. Dat de rol via de IAM-gebruiker werkt (`is_rlz_lezer` = t) is tevens het bewijs dat migratie 0157 de GRANT heeft uitgevoerd.

**d. INSERT door de poort:** `scripts/gcp/db_lezen.sh "INSERT INTO platform.groep (naam) VALUES ('x')" --als …` → `FOUT: alleen SELECT (of WITH … SELECT)`,
exit 2 — geweigerd vóór er een verbinding is.

**e. `POST /lezen/sql` als Beheerder:** niet direct gemeten. Een CC-run heeft geen Beheerder-sessie (passkey/TOTP) en het request-log toont sinds de deploy
geen aanroep op `/lezen/`. Afgeleid: de servicetemplate (revisie `rlz-backend-00628-djn`) draagt `LEES_CLOUD_SQL_VERBINDING=rlz-boekhouding:europe-west4:rlz-sql2-lees`
en `cloudsql-instances` mét beide instanties; de 503 (`GeenLeesreplica`) ontstaat alleen bij een lege `settings.lees_database_url`, en de smoketest-job leest
via exact dezelfde `config.py`-compositie. Bewust geen sessie nagebootst (geen schrijvende of auth-omzeilende poging).

## Keuzes in deze run
- **Beheerder-uuid:** de opdracht noemt `<beheerder-uuid>` zonder waarde. Gevonden via de replica zelf: `platform.gebruiker` draagt geen RLS-policy
  (schema_referentie), dus `SELECT id, naam FROM platform.gebruiker WHERE rol='beheerder' AND status='actief'` levert Peter (`2f2262cd…`) en Niek Peters
  (`7ee63a62…`). De eerste toets (b, zonder RLS-tabel) liep met de nil-uuid `00000000-…-0000` als expliciet niet-actor; daarna alles als Peter.
- **Les poort:** `has_table_privilege(…,'INSERT')` wordt door de bash-poort geweigerd omdat het woord INSERT in de query staat, óók als string-literal.
  Rechten toets je via `information_schema.role_table_grants`/`pg_roles`. Vastgelegd in GCP_UITROL §F7.4 en BESLISSINGEN.
- **Geen `tac` op macOS**: `tail -r` gebruiken bij het omkeren van Cloud-Logging-uitvoer.

## Klikpunt Peter
- `POST /lezen/sql` als Beheerder: in de kantoor-UI (of via `curl` mét een Beheerder-token) `{"sql":"SELECT 1"}` sturen → verwacht 200 mét één rij;
  een 503 "leesreplica niet geconfigureerd" zou een regressie zijn (dan: servicetemplate op `LEES_CLOUD_SQL_VERBINDING` toetsen). Geen beslispunt.

## Afronding
BESLISSINGEN "FEITEN EERST — …" alinea "Afronding leesreplica 17-09": kop → LIVE, werkt in productie: JA + nameting-bullet; GCP_UITROL §F7.4 kop + stand;
`docs/regels/werkloop-productie.md` alinea "Leesreplica afgerond 17-09" → werkt in productie: JA (regel-update, capture-at-acceptance); INDEX-regel; opdracht → gedaan.

## Gelezen regels
- `docs/regels/werkloop-productie.md` (55 regels) — volledig, vóór de start (Domeinen-kopregel).
