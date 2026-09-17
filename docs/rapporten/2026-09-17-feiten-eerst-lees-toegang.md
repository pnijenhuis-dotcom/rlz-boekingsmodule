# Rapport 17-09 (inbox-run) — "Feiten eerst": lees-only DB-/RLZ-toegang voor analyses + klikpunt-guard (besluit Peter 17-09)

Opdracht: `opdrachten/gedaan/2026-09-17-feiten-eerst-lees-toegang-en-klikpunt-guard.md`. Geen RLZ-/Odoo-writes; migratie 0154
(afsluitroutine gedaan). **Werkt in productie: niet gemeten** — de nieuwe CLI's (`db-lezen`, `rlz-feiten`) en routes (`/lezen/*`)
staan pas ná de deploy op de job-image/service; de leesreplica is een owner-klikpunt (script gecommit, niets aangemaakt).

## Besluit Peter 17-09 (bindend) → wat er nu staat

| Besluitpunt | Gebouwd |
|---|---|
| (1) Leesreplica `rlz-sql2-lees` + SELECT-only rol `rlz_lezer`, pgaudit = 100 % audit | Migratie 0154 (rol, grants, default-privileges, EXECUTE op RLS-functies; NOBYPASSRLS) + `scripts/gcp/leesreplica.sh` (dry-run/`--apply`, CMEK `cmek-sql`, flags `cloudsql.iam_authentication=on`/`cloudsql.enable_pgaudit=on`/`pgaudit.log=read`, IAM-DB-gebruiker `nameting@rlz-boekhouding.iam`, GRANT-recept). Lees-only vastgesteld: nog geen replica, geen IAM-DB-gebruiker, geen flags op `rlz-sql2`. |
| (2) CC vrije SELECT op de replica via Auth Proxy + IAM als `nameting@` | `scripts/gcp/db_lezen.sh "SELECT …" --als <beheerder-uuid> [--administratie <uuid>]`: SELECT-only-poort (bash-spiegel), `BEGIN READ ONLY`, actor-GUC (RLS-scope), rijenplafond, `cloud-sql-proxy --auto-iam-authn` mét impersonatie. **Amendement op de regel van 08-09** vastgelegd in BESLISSINGEN + CLAUDE.md + WERKWIJZE v1.17. |
| (3) RLZ/Odoo lees-only zonder `--top`-plafond voor analyses | `rlz-feiten` leest gepagineerd de volledige collectie (bank ± venster) via `lees_collectie` — geen `--top`; `rlz-lezen --alles` is NIET gebouwd (beslispunt 1). |
| (4) Cowork: `POST /lezen/sql` + workflow-input `query` | Routes `GET /lezen/queries`, `POST /lezen/query/{naam}`, `POST /lezen/sql` (Beheerder-only, replica-only → 503 zolang `LEES_DATABASE_URL` leeg, plafond 5.000, audit `db_lezen_sql`); nameting-workflow onderdeel `query` (input `query`, `--sql/--als` geweigerd) → `verkenning/lezen-<dd-mm>-<query>.txt` door de bot. |

## Blok A — `db-lezen` + querybibliotheek (`backend/app/lezen/`)
Zeven gereviewde queries (`document-feiten`, `bankmutatie-feiten`, `reconciliatie-bevindingen`, `sync-status`, `project-cache`,
`whitelist-doelen`, `documenten-zonder`) mét kop (naam/versie/doel/scope/parameters/kolommen); loader weigert kop-loos,
onbekende bind-parameters en alles wat geen SELECT is. Uitvoering per administratie in `scoped_session(aid, actor=systeem)` —
RLS onverkort; uitvoer markdown + JSON, PII geanonimiseerd (naam → initialen, IBAN → laatste 4), max 500 rijen; audit `db_lezen`.
CLI `db-lezen` (+ `--sql --als <beheerder-e-mail>` = replica-route) in de nameting-allowlist. **Rol `rlz_lezer` aantoonbaar
read-only**: `SET ROLE rlz_lezer` → SELECT ok, INSERT/UPDATE/DELETE/CREATE = `permission denied` (echte niet-eigenaar-test, én
handmatig op de dev-DB: "insert geweigerd: InsufficientPrivilege").

## Blok B — `rlz-feiten` (`backend/app/rlz/feiten_cli.py`)
`rlz-feiten rlz --administratie … --boekstuk|--id` → document over vier collecties + regels + bank in één tabel (bewijs 1 =
`PaymentReferenceList/Document`, bewijs 2 = cent-exact ± 3 d zelfde richting, oordeel) of "bestaat niet (meer)";
`rlz-feiten bank --administratie … --omschrijving|--iban|--bedrag|--datum` → mutaties mét afletterstand en koppelingen, of
"niets gevonden". Lees-only (`LeesOnlyClient`), geanonimiseerd, Odoo zichtbaar overgeslagen.

## Blok C — guards
`tests/unit/test_rapporten_klikpunten.py`: klikpunt/opruimpunt/beslispunt mét RLZ-/Odoo-/bank-object zonder datum + bedrag +
bron = rood (rapporten ≥ 17-09; "vervalt/ingetrokken" uitgezonderd). `schoonlijst.beoordeel_dubbelen` zet `bank_toets`
(`bevestigd`/`weerlegd`/`geen_mutatie`) op élke dubbelen-rij — guard `tests/migratie/test_schoonlijst_bank_toets.py`.

## Blok D — Cowork-leestoegang
Platform `WERKWIJZE.md` v1.17 sectie "Feiten eerst"; nameting.yml onderdeel `query`; commit-pattern van de bot uitgebreid
met `verkenning/lezen-*.txt` (guard aangepast). GCP_UITROL §F7.4 beschrijft de owner-stappen.

## Migratie 0154 (afsluitroutine)
`alembic upgrade head` dev-DB: `Running upgrade 0153 -> 0154` · `alembic check` schoon · live op uvicorn 8012: `GET /lezen/queries`
200, `POST /lezen/query/project-cache` 200, `POST /lezen/sql` 503 (geen replica — verwacht) · `scripts/dump_schema.sh` ververst
(head 0154). Downgrade laat de cluster-brede rol staan (DROP ROLE faalde in de testrun op de dev-DB-afhankelijkheden — bewust).

## Tests
`tests/lezen/test_lezen.py` 17 (bibliotheek, poort, uitvoer, service per scope + audit, vrije SQL: geen replica/geen beheerder/
READ ONLY met RLS-scope, read-only rol, routes, CLI) · klikpunt-guard 2 · bank_toets-guard 1 · nameting-workflow 16 ·
migratie-metadata-guard · endpoint-gates-sweep — 511 groen.

## Klikpunten Peter (owner, compleet)
1. **Leesreplica + IAM-DB-toegang** (bron: `gcloud sql instances list` 17-09 ~11:40: alleen `rlz-sql2`; `gcloud sql users list`: `boekhouding_app`, `postgres`):
   `scripts/gcp/leesreplica.sh` (dry-run) → `scripts/gcp/leesreplica.sh --apply`; daarna als postgres op de primary
   `GRANT rlz_lezer TO "nameting@rlz-boekhouding.iam";` (pas ná de deploy van 0154).
2. **Env `LEES_DATABASE_URL`** op service én jobs in deploy.yml (waarde in GCP_UITROL §F7.4) — daarna werken `POST /lezen/sql` en `db-lezen --sql`.

## Beslispunten (default gekozen — `2026-09-17-beslispunten-peter.md` opdracht 3)
1. `rlz-lezen --alles` niet gebouwd (rlz-feiten leest zelf volledig; een kaal `--alles` op élk pad = webfilter-risico).
2. Vrije SQL kent optioneel `administratie_id` i.p.v. een RLS-bypass (bank-tabellen hebben geen Beheerder-clausule).
3. Bibliotheek-queries draaien op de runtime-verbinding (zelfde als élke lees-only CLI); alleen vrije SQL eist de replica.
4. Odoo-variant van `rlz-feiten` niet gebouwd (zichtbaar overgeslagen).

## Meetrecept (werkt in productie: ja/nee)
1. Ná deploy: `scripts/gcp/nameting.sh rlz-feiten rlz --administratie "Vastgoedgroep" --boekstuk RLZ-28-00000061` en `… RLZ-28-00000062` → kop + regels + bank (bewijs 1/2).
2. `scripts/gcp/nameting.sh rlz-feiten bank --administratie "Vastgoedgroep" --omschrijving test` → Koppe-mutatie(s) 15-08 óf "niets gevonden".
3. `scripts/gcp/nameting.sh db-lezen bankmutatie-feiten --administratie "Vastgoedgroep" --param omschrijving=test`.
4. `gh workflow run nameting -f onderdeel=query -f query="project-cache --administratie Vastgoedgroep"` → `verkenning/lezen-<dd-mm>-project-cache.txt`.
5. Ná klikpunt 1+2: `scripts/gcp/db_lezen.sh "SELECT count(*) FROM boekhouding.document" --als <Peters id>` en `POST /lezen/sql` 200 mét audit `db_lezen_sql`.
