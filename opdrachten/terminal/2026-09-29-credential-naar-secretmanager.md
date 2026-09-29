> **UITGEVOERD 29-09 door Peter** via `scripts/gcp/jarvis_logins_alles.sh` (stap 0–4 in één run). Dry-run `rlz-reconciliatie-868zv`, executie `rlz-reconciliatie-t2ts9`, 18/18 secrets versie 1 ENABLED. Rapport: `docs/rapporten/2026-09-29-credential-naar-secretmanager.md` (Gemeten); log: `docs/rapporten/2026-09-29-credential-naar-secretmanager.terminal.log`.

# Terminal 29-09 — Jarvis-logins: credential-store → Secret Manager (ná deploy van de commit "credential-naar-secretmanager")

Volgorde: stap 0 (IAM, eenmalig) → stap 1 (deploy live?) → stap 2 (dry-run) → stap 3 (echte executie) → stap 4 (versies tellen).
Owner-sessie. Geen enkele stap toont een waarde (besluit 0012): alleen secretnaam + aantal tekens.

## Stap 0 — IAM (eenmalig; de CC-run kon dit niet: classifier weigert een IAM-grant)
```
bash scripts/gcp/credential_naar_secretmanager_iam.sh
```
Verwacht: 18 regels "…: run-jobs@ viewer+versionAdder, jarvis-run-jobs@ accessor". Idempotent.

## Stap 1 — deploy live? (lees-only)
```
gcloud run jobs describe rlz-reconciliatie --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image)"
```
Verwacht: image = de commit die `credential-naar-secretmanager` draagt (of nieuwer). Anders wachten.

## Stap 2 — dry-run (leest de store, schrijft niets)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|credential-naar-secretmanager|--dry-run"
```
Verwacht: 18 × "RLZ_WS_…: ZOU versie zetten (n tekens) — dry-run", "0 administratie(s) mét fout". Een regel "niet (eenduidig) gevonden" of
"geen credential in de store" = eerst de administratienaam/credential nakijken (Instellingen › Administraties), niet doorgaan.

## Stap 3 — echte executie (zet versie 1 op 18 secrets)
```
gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait --args="^|^-m|app.cli|credential-naar-secretmanager"
```
Verwacht: per prefix twee regels "RLZ_WS_USER_<PREFIX>: versie 1 gezet (n tekens)" / "RLZ_WS_PASSWORD_<PREFIX>: versie 1 gezet (n tekens)",
slot "18 versie(s) gezet, 0 al aanwezig, 0 administratie(s) mét fout". Herdraaien is veilig: "heeft al versie 1 — niet overschreven".
Log teruglezen als `--wait` de uitvoer niet toont:
```
gcloud logging read 'resource.type="cloud_run_job" AND labels."run.googleapis.com/execution_name"="<executie>"' --project rlz-boekhouding --limit 60 --format="value(textPayload)"
```

## Stap 4 — meetlat
```
for P in UNIVERSAL_NEDERLAND UNIVERSAL_VERKOOP UNIVERSAL_MATERIAAL UNIVERSAL_STEIGERBOUW BWC_STEIGERS BRADWOLFF_CONSTRUCTIE INPENSAS_BEHEER BRADWOLFF_HOLDING DE_WIT_BEHEER_OSS; do for S in RLZ_WS_USER_$P RLZ_WS_PASSWORD_$P; do printf '%s: ' "$S"; gcloud secrets versions list "$S" --project rlz-boekhouding --format="value(name,state)" | tr '\n' ' '; echo; done; done
```
Verwacht: 18 × "1 ENABLED". De 18 uitvoerregels van stap 3 onder "Gemeten" in `docs/rapporten/2026-09-29-credential-naar-secretmanager.md`
plakken + "werkt in productie: ja".
