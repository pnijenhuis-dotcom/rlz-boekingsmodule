# Rapport 17-09 (SPOED, inbox-run) — Xcode Cloud build 144 rood (Package.resolved) + Apple 1.1 live → STORE_APP_VERSIE_IOS=1.1, marketingversie 1.2, bucket-binding, nameting via gh

Opdracht: `opdrachten/gedaan/2026-09-17-SPOED-xcode-cloud-package-resolved-en-apple-1-1-live.md`. Geen RLZ-/Odoo-writes, geen migratie.
**Werkt in productie: niet gemeten** — de fixes zijn pas meetbaar ná de push (Xcode Cloud-build ≥ 145) en ná de deploy van deze commits
(stap 10 + uitnodigingsmail). Meetrecept staat onderaan; vervolg-opdracht `opdrachten/inbox/2026-09-17-apple-1-2-xcode-cloud-nameting.md`.

## Feiten (lees-only geverifieerd in deze run)

| Feit | Bron | Uitkomst |
|---|---|---|
| Apple 1.1 live | `itunes.apple.com/lookup?id=6803862748&country=nl` (publiek, lees-only) | `version 1.1`, `currentVersionReleaseDate 2026-09-16T23:23:27Z`, trackName "Nijenhuis Boekingsmodule" → voorwaarde §0f vervuld |
| Xcode Cloud build 144 | mail Peter 17-09 | "out-of-date resolved file … dependencies were added: 'version', 'zipfoundation'" — Package.resolved droeg alleen capacitor-swift-pm 8.5.0 |
| Deploy-stand | `gh run list --workflow=deploy.yml`: runs 35154845937 (`bc3f7c1`), 35188489798 (`ea859d6`), 35189339460 (`fb54c58`) | alle drie rood **uitsluitend** op stap 10 "OTA-webbundel …": `ERROR: (gcloud.storage.cp) gs://rlz-boekhouding-app-bundels not found: 404` (laatste 06:23:49 UTC) — stappen 7/8/9 groen, service + jobs op hetzelfde beeld |
| Bucket | `gcloud storage buckets describe` | bestaat sinds **17-09 07:48:59 UTC** (ná de laatste deploy), europe-west4, uniform access, versioning aan |
| Bucket-IAM | `gcloud storage buckets get-iam-policy` | deploy@ objectCreator + objectViewer, run-jobs@ objectViewer — **run-backend@ ontbreekt** |
| Service-SA | `gcloud run services describe rlz-backend --format='value(spec.template.spec.serviceAccountName)'` | `run-backend@rlz-boekhouding.iam.gserviceaccount.com` (projectnummer 652591056217) |
| gcloud lokaal | `gcloud auth print-access-token` | groen in deze (interactieve) sessie; de inbox-run van 07:00 kon niet herinloggen |

## Gedaan

1. **Package.resolved bijgewerkt** (`xcodebuild -resolvePackageDependencies -project native/ios/App/App.xcodeproj -scheme App`): capacitor-swift-pm 8.5.0 · Alamofire 5.12.2 · Version 0.8.0 · ZIPFoundation 0.9.20. Guard `backend/tests/unit/test_ios_package_resolved_actueel.py` (4 tests): remote deps van CapApp-SPM/Package.swift én van de lokale plugin-packages (node_modules) staan in Package.resolved; vaste set van 17-09; rood mét het xcodebuild-recept.
2. **Marketingversie 1.2** (train-regel §0f): pbxproj ×2, `build.gradle` versionName 1.2 / versionCode 6, `appVersie.ts`; guard aangepast (`…_is_1_2_sinds_17_09_en_versioncode_6`). `APP_MIN_RUNTIME_VERSIE` blijft 1.1.
3. **`STORE_APP_VERSIE_IOS=1.1`** in deploy.yml — service-envset én `BASIS_ENVS` van de jobs (`STORE_LINK_IOS` reist nu ook in BASIS_ENVS mee); sleutel in `test_deploy_yml_envset_compleet.py`; nieuwe guard: waarde 1.1 op ≥ 2 plekken en nooit boven de marketingversie. Effect ná deploy: uitnodigingsmail toont de App Store-link.
4. **`scripts/gcp/app_bundels_bucket.sh`**: service-SA uit de service, anders default compute-SA (`<projectnummer>-compute@…`), `SERVICE_SA=`-env overschrijft; nooit `?`; bucket-create idempotent.
5. **`scripts/gcp/nameting.sh` `NAMETING_VIA_GH=auto|0|1`**: niet-interactief (geen TTY) of geen gcloud-token → `gh workflow run nameting -f onderdeel=<…>` + `gh run watch`; commando zonder workflow-onderdeel = exit 3 mét reden.
6. Docs: TESTFLIGHT §0f "STAND 17-09", BESLISSINGEN nieuwe sectie, CLAUDE.md verwijsregel, WAT_IS_NIEUW "De app in de App Store heeft nu de nieuwe inlog zonder wachtwoord" (noemt versie 1.1 én 1.2). PLAY ongewijzigd (vc4 in review).

## Tests
`test_ios_package_resolved_actueel.py` 4 · `test_app_marketingversie_consistent.py` 6 · `test_deploy_yml_envset_compleet.py` + `…envvar_delimiters.py` · `test_nameting_workflow.py` 16 · `test_cc_inbox_pull.py` — 31 + 22 groen; `bash -n` op beide scripts groen; frontend `changelog`-test 5 groen.

## Klikpunten Peter (compleet: bron-id + datum + wat)

1. **IAM-binding service-SA op de bundel-bucket** (bron: `get-iam-policy gs://rlz-boekhouding-app-bundels` 17-09 ~10:55 lokaal, binding voor `run-backend@` ontbreekt), één owner-commando:
   ```
   gcloud storage buckets add-iam-policy-binding gs://rlz-boekhouding-app-bundels --member serviceAccount:run-backend@rlz-boekhouding.iam.gserviceaccount.com --role roles/storage.objectViewer
   ```
   (of `scripts/gcp/app_bundels_bucket.sh --apply` opnieuw — idempotent). Zonder binding is stap 10 wél groen (deploy@ schrijft, de job registreert) maar kan de service de zip niet serveren.
2. **Xcode Cloud**: de eerstvolgende build op `main` ná deze push is 1.2 (≥ 145) mét de OTA-plugins → TestFlight-kliktest §0e; indienen pas als er iets in de schil moet (OTA dekt de web-laag).

## Beslispunten (default gekozen — zie `docs/rapporten/2026-09-17-beslispunten-peter.md`)
1. `STORE_LINK_IOS` + `STORE_APP_VERSIE_IOS` óók in BASIS_ENVS van de jobs (herinneringsmails).
2. Nameting-via-gh: alleen commando's mét een workflow-onderdeel; ad-hoc `rlz-lezen` blijft interactief.
3. De OTA-bundel registreert per RUNTIME → ná de bump 1.2 krijgt de live 1.1-schil geen OTA-bundel (train-regel: OTA volgt de gebouwde schil).

## Meetrecept (vervolg-opdracht)
1. `gh run list --workflow=deploy.yml --limit 1` groen incl. stap 10, log "OTA-bundel … (runtime 1.2 …) geregistreerd".
2. Xcode Cloud: mail "processing completed" voor 1.2 (≥ 145) — build groen.
3. `GET https://app.administratiekantoornijenhuis.nl/app/update-manifest?runtime=1.2&platform=ios` → 200 mét bundel_id; ná klikpunt 1: `GET /app/bundels/<id>.zip` 200.
4. Verse uitnodiging voor een app-rol → mail toont "iPhone / iPad — App Store" (geen TestFlight-instructie).
