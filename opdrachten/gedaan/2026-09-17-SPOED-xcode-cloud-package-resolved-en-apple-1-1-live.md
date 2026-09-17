> uitgevoerd 2026-09-17 (SPOED-run; Package.resolved + guard, 1.2, STORE_APP_VERSIE_IOS=1.1, bucket-script, nameting via gh; werkt in productie: niet gemeten — vervolg-opdracht apple-1-2-xcode-cloud-nameting), rapport: docs/rapporten/2026-09-17-apple-1-1-live-xcode-cloud.md

# SPOEDOPDRACHT 17-09 — Xcode Cloud build 144 rood (Package.resolved verouderd door de OTA-plugins) + Apple 1.1 GOEDGEKEURD → STORE_APP_VERSIE_IOS=1.1 en marketingversie → 1.2 + deploys weer groen (bucket bestaat nu)

**Feiten (mails Peter 17-09 ochtend):**
1. **Apple: 1.1 goedgekeurd** ("eligible for distribution", Submission dad3608e…, automatisch vrijgeven stond aan → 1.1 (140) gaat live in
   de App Store). Train-regel (§0f): vóór de volgende push marketingversie → **1.2** (pbxproj ×2, `versionName` + vc6, `appVersie.ts`,
   guard `test_app_marketingversie_consistent.py`); `STORE_APP_VERSIE_IOS=1.1` in deploy.yml (de uitnodigingsmail toont dan de
   App Store-link mét de nieuwe login). Controleer lees-only in ASC (of via de store-URL) dat 1.1 daadwerkelijk "Ready for Distribution"
   is vóór de env-wijziging; anders wachten.
2. **Xcode Cloud build 144 (main) rood:** "out-of-date resolved file … Package.resolved … dependencies were added: 'version'
   (mrackwitz/Version), 'zipfoundation' (weichsel/ZIPFoundation)" — de OTA-run (Capgo-updater) voegde SPM-afhankelijkheden toe
   zonder `native/ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved` bij te werken; Xcode Cloud draait
   met automatische resolutie UIT. Fix: lokaal `xcodebuild -resolvePackageDependencies -project native/ios/App/App.xcodeproj -scheme App`
   (of `xcodebuild -workspace … -resolvePackageDependencies` conform de bestaande bouwscripts in `native/`), het bijgewerkte
   Package.resolved committen; guard: `tests/unit/test_ios_package_resolved_actueel.py` vergelijkt de package-lijst in het pbxproj/
   Package.swift met Package.resolved (nieuwe dep zonder resolved-update = rood). Lees TESTFLIGHT_DRAAIBOEK §0c voor de
   build-nummer-conventie (Xcode Cloud telt per push; 1.2-build volgt vanzelf).
3. **Deploys bc3f7c1 e.v. rood op stap 10 "OTA-webbundel" (bucket 404):** Peter heeft `app_bundels_bucket.sh --apply` 17-09 ~09:15
   gedraaid → bucket + versioning + IAM deploy@/run-jobs@ staan; **service-SA-binding ontbreekt** (script gaf `service-sa=?`).
   Stap 0: service-SA lees-only achterhalen (`gcloud run services describe rlz-backend --format='value(spec.template.spec.serviceAccountName)'`
   → leeg = default compute-SA `<projectnummer>-compute@developer.gserviceaccount.com`), de ontbrekende `roles/storage.objectViewer`
   als één owner-commando in het rapport (Peter draait), script fixen (fallback default-SA, nooit `?`), en de eerstvolgende deploy
   moet groen zijn incl. stap 10. Blijkt de OTA-stap zonder die binding al groen (alleen deploy@ schrijft), dan is de service-binding
   alleen nodig voor het serveren → meetrecept: `GET /app/update-manifest?runtime=1.1&platform=ios` ná deploy.
4. **Nameting-inbox-run kan niet herinloggen** ("Reauthentication failed … non-interactive"): Workspace-reauth-beleid raakt de
   launchd-sessie. Regel vastleggen: productiemetingen vanuit de inbox lopen via `gh workflow run nameting.yml` (WIF, nooit lokale
   gcloud), zoals CC vannacht al deed; `scripts/gcp/nameting.sh` krijgt een `--via-gh`-pad als default voor niet-interactieve runs.

## Afronding
Commits gescheiden (ios-resolved / versie-bump + env / scripts); TESTFLIGHT §0f "1.1 LIVE <datum>", PLAY ongewijzigd (vc4 nog in review);
BESLISSINGEN "APPLE 1.1 GOEDGEKEURD 17-09 — 1.2 VOLGT; XCODE CLOUD PACKAGE.RESOLVED-GUARD; NAMETING VIA GH"; WAT_IS_NIEUW ("De app in de
App Store heeft nu de nieuwe inlog zonder wachtwoord"); rapport + INDEX mét "werkt in productie: ja/nee" (meetrecept: Xcode Cloud-build
ná de push groen; deploy groen incl. stap 10; uitnodigingsmail toont App Store-link; manifest-route 200).
