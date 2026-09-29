# 2026-09-29 — Jarvis-logins: credential-store → Secret Manager (opdracht Peter 29-09)

1. Gebouwd: job-CLI `credential-naar-secretmanager` (`backend/app/beheer/credential_naar_secretmanager.py`): negen vaste administraties → `RLZ_WS_USER_<PREFIX>` + `RLZ_WS_PASSWORD_<PREFIX>`, store-unwrap → Secret Manager REST `:addVersion`, uitvoer alleen "‹naam›: versie N gezet (n tekens)" (besluit 0012), bestaande versie nooit stil overschreven, `--dry-run`, audit zonder waarde; 7 tests groen (waarde-lek-guard op uitvoer én audit, REST-vorm gestubd).
2. Stand 29-09 geverifieerd (lees-only, owner-sessie): 18 containers bestaan (user-managed europe-west4), 0 versies; `jarvis-run-jobs@` bestaat.
3. IAM-script `scripts/gcp/credential_naar_secretmanager_iam.sh` (run-jobs@ viewer + secretVersionAdder, jarvis-run-jobs@ secretAccessor, secret-scoped, idempotent) — de CC-run kon de grant niet zelf zetten (permission-classifier) → klikpunt Peter; **uitgevoerd 29-09 door Peter** als stap 0 van `scripts/gcp/jarvis_logins_alles.sh` (18 × "run-jobs@ viewer+versionAdder, jarvis-run-jobs@ accessor").
4. Job-executie NIET in de CC-run (het commando bestaat pas op de image ná de deploy van deze commit, regel 08-09) → **uitgevoerd 29-09 door Peter** via `scripts/gcp/jarvis_logins_alles.sh` (alles-in-één owner-script: stap 0 IAM → stap 1 wacht tot de job-image het commando draagt (image `backend:c6dd3bd…`) → stap 2 dry-run → stap 3 executie → stap 4 meetlat; stopt bij de eerste afwijking, toont nooit een waarde). Volledige terminal-log: `docs/rapporten/2026-09-29-credential-naar-secretmanager.terminal.log` (alleen secretnamen, IAM-tekst en versienummers).
5. Vastgelegd: BESLISSINGEN "JARVIS-LOGINS — CREDENTIAL-STORE → SECRET MANAGER ALS JOB-EXECUTIE, NOOIT TONEN (Peter 29-09)", regels-alinea 29-09 in `werkloop-productie.md` (amendement 23-09: machine-kopie mag), CLAUDE.md-verwijsregel 10.
6. Meldingen per prefix: zie "Gemeten" hieronder (18 regels uit het Cloud Logging van executie `rlz-reconciliatie-t2ts9`).
7. **Werkt in productie: ja** — dry-run `rlz-reconciliatie-868zv` en echte executie `rlz-reconciliatie-t2ts9` beide "successfully completed"; meetlat `gcloud secrets versions list` = 18 van 18 secrets één actieve versie (versie 1 ENABLED); slotregel van de job: "18 versie(s) gezet, 0 al aanwezig, 0 administratie(s) mét fout". Herdraaien blijft veilig (bestaande versie = "niet overschreven").

## Gemeten (29-09, Cloud Logging executie `rlz-reconciliatie-t2ts9`, job `rlz-reconciliatie`, project `rlz-boekhouding`)

Uitvoer van de job — uitsluitend secretnaam + aantal tekens, nooit de waarde (besluit 0012):

```
credential-naar-secretmanager: 9 administratie(s) → project rlz-boekhouding
  RLZ_WS_USER_UNIVERSAL_NEDERLAND: versie 1 gezet (9 tekens)
  RLZ_WS_PASSWORD_UNIVERSAL_NEDERLAND: versie 1 gezet (16 tekens)
  RLZ_WS_USER_UNIVERSAL_VERKOOP: versie 1 gezet (11 tekens)
  RLZ_WS_PASSWORD_UNIVERSAL_VERKOOP: versie 1 gezet (16 tekens)
  RLZ_WS_USER_UNIVERSAL_MATERIAAL: versie 1 gezet (13 tekens)
  RLZ_WS_PASSWORD_UNIVERSAL_MATERIAAL: versie 1 gezet (16 tekens)
  RLZ_WS_USER_UNIVERSAL_STEIGERBOUW: versie 1 gezet (18 tekens)
  RLZ_WS_PASSWORD_UNIVERSAL_STEIGERBOUW: versie 1 gezet (14 tekens)
  RLZ_WS_USER_BWC_STEIGERS: versie 1 gezet (7 tekens)
  RLZ_WS_PASSWORD_BWC_STEIGERS: versie 1 gezet (16 tekens)
  RLZ_WS_USER_BRADWOLFF_CONSTRUCTIE: versie 1 gezet (9 tekens)
  RLZ_WS_PASSWORD_BRADWOLFF_CONSTRUCTIE: versie 1 gezet (16 tekens)
  RLZ_WS_USER_INPENSAS_BEHEER: versie 1 gezet (12 tekens)
  RLZ_WS_PASSWORD_INPENSAS_BEHEER: versie 1 gezet (16 tekens)
  RLZ_WS_USER_BRADWOLFF_HOLDING: versie 1 gezet (12 tekens)
  RLZ_WS_PASSWORD_BRADWOLFF_HOLDING: versie 1 gezet (16 tekens)
  RLZ_WS_USER_DE_WIT_BEHEER_OSS: versie 1 gezet (9 tekens)
  RLZ_WS_PASSWORD_DE_WIT_BEHEER_OSS: versie 1 gezet (16 tekens)
credential-naar-secretmanager: klaar — 18 versie(s) gezet, 0 al aanwezig, 0 administratie(s) mét fout (waarden nooit getoond — besluit 0012)
```

| Meetlat | Verwacht | Gemeten |
|---|---|---|
| Dry-run (`rlz-reconciliatie-868zv`) | voltooid, schrijft niets | successfully completed |
| Executie (`rlz-reconciliatie-t2ts9`) | 18 × "versie 1 gezet" | 18 × "versie 1 gezet", 0 al aanwezig, 0 fout |
| `gcloud secrets versions list` (owner-sessie, stap 4 van het script) | 18 × versie 1 ENABLED | 18 van 18 secrets één actieve versie (1) |

Uitvoerrecept (voor een volgende kopie of rotatie): `scripts/gcp/jarvis_logins_alles.sh` (owner-sessie, éénmalig; rotatie = de executie mét `--overschrijven`).

## Gelezen regels
- `docs/regels/werkloop-productie.md` (333 regels vóór deze run) — volledig
- `docs/regels/administraties-instellingen.md` (236 regels) — volledig
