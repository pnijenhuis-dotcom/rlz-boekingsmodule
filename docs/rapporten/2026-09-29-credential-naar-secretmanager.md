# 2026-09-29 — Jarvis-logins: credential-store → Secret Manager (opdracht Peter 29-09)

1. Gebouwd: job-CLI `credential-naar-secretmanager` (`backend/app/beheer/credential_naar_secretmanager.py`): negen vaste administraties → `RLZ_WS_USER_<PREFIX>` + `RLZ_WS_PASSWORD_<PREFIX>`, store-unwrap → Secret Manager REST `:addVersion`, uitvoer alleen "‹naam›: versie N gezet (n tekens)" (besluit 0012), bestaande versie nooit stil overschreven, `--dry-run`, audit zonder waarde; 7 tests groen (waarde-lek-guard op uitvoer én audit, REST-vorm gestubd).
2. Stand 29-09 geverifieerd (lees-only, owner-sessie): 18 containers bestaan (user-managed europe-west4), 0 versies; `jarvis-run-jobs@` bestaat.
3. IAM-script `scripts/gcp/credential_naar_secretmanager_iam.sh` (run-jobs@ viewer + secretVersionAdder, jarvis-run-jobs@ secretAccessor, secret-scoped, idempotent) — **NIET uitgevoerd: de permission-classifier weigert een IAM-grant in de CC-run** → klikpunt Peter.
4. Job-executie NIET gedraaid: het commando bestaat pas op de image ná de deploy van deze commit (push via de Stop-hook, regel 08-09) → stappen 0–3 in `opdrachten/terminal/2026-09-29-credential-naar-secretmanager.md` (IAM → deploy-check → dry-run 18 × "ZOU" → executie → `gcloud secrets versions list`).
5. Vastgelegd: BESLISSINGEN "JARVIS-LOGINS — CREDENTIAL-STORE → SECRET MANAGER ALS JOB-EXECUTIE, NOOIT TONEN (Peter 29-09)", regels-alinea 29-09 in `werkloop-productie.md` (amendement 23-09: machine-kopie mag), CLAUDE.md-verwijsregel 10.
6. Meldingen per prefix "versie 1 gezet (n tekens)": volgen uit de executie (stap 2) — Peter/Cowork plakt de 18 uitvoerregels hier onder "Gemeten".
7. Werkt in productie: niet gemeten.

## Gelezen regels
- `docs/regels/werkloop-productie.md` (333 regels vóór deze run) — volledig
- `docs/regels/administraties-instellingen.md` (236 regels) — volledig
