/**
 * Marketingversie van de goedkeur-app (één web-bron; mini-run 09-09).
 *
 * Moet gelijk lopen met `MARKETING_VERSION` in native/ios/App/App.xcodeproj/project.pbxproj en
 * `versionName` in native/android/app/build.gradle — bewaakt door
 * backend/tests/unit/test_app_marketingversie_consistent.py. Het BUILDnummer staat hier bewust
 * niet: iOS krijgt dat van Xcode Cloud (CI_BUILD_NUMBER), Android van versionCode.
 *
 * Train-regel Apple: ná elke goedkeuring van een versie sluit App Store Connect die train;
 * de marketingversie moet dan omhoog vóór de volgende push, anders bouwt Xcode Cloud voor niets
 * (ITMS-90186/ITMS-90062 op build 98, 09-09).
 */
export const APP_MARKETING_VERSIE = '1.1'
