#!/usr/bin/env bash
# =============================================================================
# Release-AAB voor Google Play — Android-bouwronde 28-08.
#
# Bouwt de webbundel (--mode native, VITE_API_BASE uit frontend/.env.native), synct 'm in de
# Capacitor-Android-schil en maakt een met de UPLOAD-key gesigneerde Android App Bundle.
# Daarna valideert het script het resultaat (signatuur = onze upload-key, package-naam,
# versionCode/-Name, google-services-resources aanwezig) en print pad + SHA-256.
#
# Upload-artefacten náást de AAB (Play-nazorg 30-08 — de twee Play-waarschuwingen "geen
# deobfuscation-bestand" en "native code zonder debug-symbolen"):
#   - <naam>-mapping.txt          R8-mapping (identiteitsmodus, zie app/proguard-rules.pro); zit óók
#                                 in de AAB als BUNDLE-METADATA/com.android.tools.build.obfuscation/
#                                 proguard.map — Play leest 'm dan automatisch;
#   - <naam>-native-debug-symbols.zip   <abi>/<lib>.so uit de bundel, Play's uploadvorm voor
#                                 "native debug symbols" (App bundle explorer → Downloads). De app heeft
#                                 géén eigen native code — de enige .so is androidx-datastore (Firebase),
#                                 zoals geleverd door de bibliotheek; er is dus geen NDK nodig.
#
# Vereisten (PLAY_DRAAIBOEK.md §1): JDK 21, Android SDK (platform 36 + build-tools),
# native/android/local.properties of ANDROID_HOME, en keystore.properties (§2).
#
# Gebruik:  native/scripts/bouw_android_release.sh                # versionCode uit build.gradle
#           native/scripts/bouw_android_release.sh 2 1.0          # -PversionCode=2 -PversionName=1.0
#           SLA_WEB_OVER=1 native/scripts/bouw_android_release.sh # webbundel niet opnieuw bouwen
# =============================================================================
set -euo pipefail

HIER="$(cd "$(dirname "$0")/.." && pwd)"
ANDROID="${HIER}/android"
VERSION_CODE="${1:-}"
VERSION_NAME="${2:-}"

echo "== 0/5: omgeving =="
if ! java -version >/dev/null 2>&1; then
  echo "   FOUT: geen Java Runtime — installeer JDK 21 (brew install --cask temurin@21) en open een nieuwe terminal."
  exit 1
fi
java -version 2>&1 | head -1 | sed 's/^/   /'
if [ -z "${ANDROID_HOME:-}" ] && [ ! -f "${ANDROID}/local.properties" ]; then
  echo "   FOUT: Android SDK niet gevonden — zet ANDROID_HOME (bv. ~/Library/Android/sdk) of"
  echo "   maak ${ANDROID}/local.properties met 'sdk.dir=/Users/<jij>/Library/Android/sdk'."
  echo "   Installatie: PLAY_DRAAIBOEK.md §1. Gestopt."
  exit 1
fi
if [ ! -f "${ANDROID}/keystore.properties" ]; then
  echo "   FOUT: ${ANDROID}/keystore.properties ontbreekt — draai eerst native/scripts/android_keystore.sh (§2)."
  exit 1
fi
if [ ! -f "${ANDROID}/app/google-services.json" ]; then
  echo "   FOUT: native/android/app/google-services.json ontbreekt (Firebase-registratie) — hoort in git te staan."
  exit 1
fi
echo "   SDK/keystore/google-services aanwezig."

echo
echo "== 1/5: webbundel (--mode native) + cap sync android =="
cd "${HIER}"
if [ "${SLA_WEB_OVER:-0}" = "1" ] && [ -d "${HIER}/../frontend/dist" ]; then
  echo "   webbundel overgeslagen (SLA_WEB_OVER=1) — bestaande ../frontend/dist gebruikt."
else
  npm run bouw-web
fi
npx cap sync android

echo
echo "== 2/5: gradle bundleRelease =="
cd "${ANDROID}"
GRADLE_ARGS=(bundleRelease --no-daemon)
[ -n "${VERSION_CODE}" ] && GRADLE_ARGS+=("-PversionCode=${VERSION_CODE}")
[ -n "${VERSION_NAME}" ] && GRADLE_ARGS+=("-PversionName=${VERSION_NAME}")
./gradlew "${GRADLE_ARGS[@]}"
AAB="${ANDROID}/app/build/outputs/bundle/release/app-release.aab"
[ -f "${AAB}" ] || { echo "   FOUT: ${AAB} niet gevonden ná de build."; exit 1; }

echo
echo "== 3/5: validatie =="
# (a) signatuur: de AAB is een jar-signed zip; het certificaat moet onze upload-key zijn.
KEYSTORE_PAD="$(sed -n 's/^storeFile=//p' keystore.properties)"
STORE_PASS="$(sed -n 's/^storePassword=//p' keystore.properties | sed -e 's/\\\(.\)/\1/g')"
VERWACHT="$(keytool -list -v -keystore "${KEYSTORE_PAD}" -storepass "${STORE_PASS}" 2>/dev/null | sed -n 's/.*SHA256: //p' | head -1)"
GEVONDEN="$(keytool -printcert -jarfile "${AAB}" 2>/dev/null | sed -n 's/.*SHA256: //p' | head -1)"
if [ -z "${GEVONDEN}" ]; then
  echo "   FOUT: de AAB draagt GEEN signatuur — keystore.properties werd niet opgepikt (zie de Gradle-waarschuwing)."
  exit 1
fi
if [ "${VERWACHT}" != "${GEVONDEN}" ]; then
  echo "   FOUT: AAB-signatuur (${GEVONDEN}) ≠ upload-key (${VERWACHT})."
  exit 1
fi
echo "   signatuur = upload-key ✓  (SHA-256 ${GEVONDEN})"
# (b) inhoud: manifest + google-services-resource (values.xml met google_app_id) aanwezig.
INHOUD="$(unzip -l "${AAB}")"
printf '%s\n' "${INHOUD}" | grep -q "base/manifest/AndroidManifest.xml" || { echo "   FOUT: base/manifest ontbreekt in de AAB."; exit 1; }
printf '%s\n' "${INHOUD}" | grep -q "base/assets/public/index.html" || { echo "   FOUT: webbundel (assets/public/index.html) ontbreekt — cap sync mislukt?"; exit 1; }
printf '%s\n' "${INHOUD}" | grep -q "base/res/drawable/ic_stat_nijenhuis" || { echo "   FOUT: notificatie-icoon ic_stat_nijenhuis ontbreekt."; exit 1; }
echo "   manifest + webbundel + notificatie-icoon aanwezig ✓"
# (b2) geen lokale-debug-plumbing in de release (Android-bouwronde 29-08): de emulator-screenshot-
#      build zet via NATIVE_LOKALE_BACKEND=1 `allowMixedContent` in de gebundelde Capacitor-config en
#      de debug-manifest-overlay `usesCleartextTraffic` — beide horen NOOIT in een Play-upload.
if unzip -p "${AAB}" base/assets/capacitor.config.json | grep -q "allowMixedContent"; then
  echo "   FOUT: allowMixedContent in de gebundelde capacitor.config.json — NATIVE_LOKALE_BACKEND stond aan bij cap sync."; exit 1
fi
if unzip -p "${AAB}" base/assets/public/index.html >/dev/null 2>&1 && unzip -l "${AAB}" | grep -q "base/assets/public/assets/" && unzip -p "${AAB}" 'base/assets/public/assets/*.js' | grep -q "10\.0\.2\.2"; then
  echo "   FOUT: de webbundel wijst naar de emulator-host 10.0.2.2 — bouw de web opnieuw zónder VITE_API_BASE-override."; exit 1
fi
echo "   geen mixed-content-vlag / emulator-API-base in de bundel ✓"
# (c) bundletool (optioneel, als geïnstalleerd: brew install bundletool) — officiële validatie + manifest-dump.
if command -v bundletool >/dev/null 2>&1; then
  bundletool validate --bundle="${AAB}" >/dev/null && echo "   bundletool validate ✓"
  MANIFEST="$(bundletool dump manifest --bundle="${AAB}")"
  PKG="$(printf '%s' "${MANIFEST}" | sed -n 's/.*package="\([^"]*\)".*/\1/p' | head -1)"
  VC="$(printf '%s' "${MANIFEST}" | sed -n 's/.*android:versionCode="\([^"]*\)".*/\1/p' | head -1)"
  VN="$(printf '%s' "${MANIFEST}" | sed -n 's/.*android:versionName="\([^"]*\)".*/\1/p' | head -1)"
  [ "${PKG}" = "nl.aknijenhuis.goedkeuren" ] || { echo "   FOUT: package ${PKG} ≠ nl.aknijenhuis.goedkeuren"; exit 1; }
  echo "   package ${PKG} · versionCode ${VC} · versionName ${VN} ✓"
  printf '%s' "${MANIFEST}" | grep -q "POST_NOTIFICATIONS" && echo "   POST_NOTIFICATIONS gedeclareerd ✓"
  printf '%s' "${MANIFEST}" | grep -q "ACCESS_BACKGROUND_LOCATION" && { echo "   FOUT: ACCESS_BACKGROUND_LOCATION in het manifest — geofence zit NIET in deze release."; exit 1; }
  printf '%s' "${MANIFEST}" | grep -q 'usesCleartextTraffic="true"' && { echo "   FOUT: usesCleartextTraffic in het release-manifest — de debug-overlay (app/src/debug) is in de release gelekt."; exit 1; }
  echo "   geen ACCESS_BACKGROUND_LOCATION / usesCleartextTraffic ✓"
else
  echo "   (bundletool niet geïnstalleerd — 'brew install bundletool' voor de officiële validatie + manifest-dump; niet verplicht)"
fi

# (d) R8-mapping ingebed (Play-nazorg 30-08): met minifyEnabled=true bundelt AGP de mapping als
#     BUNDLE-METADATA — ontbreekt die, dan is de gradle-config teruggedraaid en komt Play's
#     "geen deobfuscation-bestand"-waarschuwing terug.
printf '%s\n' "${INHOUD}" | grep -q "BUNDLE-METADATA/com.android.tools.build.obfuscation/proguard.map" \
  || { echo "   FOUT: proguard.map ontbreekt in de AAB (BUNDLE-METADATA) — minifyEnabled staat uit? Zie app/build.gradle."; exit 1; }
MAPPING="${ANDROID}/app/build/outputs/mapping/release/mapping.txt"
[ -f "${MAPPING}" ] || { echo "   FOUT: ${MAPPING} niet gevonden ná de build."; exit 1; }
echo "   R8-mapping aanwezig (ingebed + ${MAPPING##*/}) ✓"

echo
echo "== 4/5: resultaat =="
UIT="${ANDROID}/app/release"; mkdir -p "${UIT}"
STEMPEL="$(date +%Y%m%d-%H%M)"
NAAM="nijenhuis-goedkeuren-${VERSION_NAME:-versie}-vc${VERSION_CODE:-gradle}-${STEMPEL}"
DOEL="${UIT}/${NAAM}.aab"
cp "${AAB}" "${DOEL}"
echo "   ${DOEL}"
echo "   SHA-256: $(shasum -a 256 "${DOEL}" | cut -d' ' -f1)"
echo "   grootte: $(du -h "${DOEL}" | cut -f1)"
# Upload-artefacten náást de AAB (zie kop): mapping + native debug-symbols.
cp "${MAPPING}" "${UIT}/${NAAM}-mapping.txt"
echo "   ${UIT}/${NAAM}-mapping.txt"
SYMBOLEN_WERK="$(mktemp -d)"
if unzip -q -o "${AAB}" 'base/lib/*' -d "${SYMBOLEN_WERK}" 2>/dev/null && [ -d "${SYMBOLEN_WERK}/base/lib" ]; then
  SYMBOLEN_ZIP="${UIT}/${NAAM}-native-debug-symbols.zip"
  rm -f "${SYMBOLEN_ZIP}"
  (cd "${SYMBOLEN_WERK}/base/lib" && zip -q -r -X "${SYMBOLEN_ZIP}" .)
  echo "   ${SYMBOLEN_ZIP}  ($(unzip -l "${SYMBOLEN_ZIP}" | grep -c '\.so$') .so-bestanden: $(ls "${SYMBOLEN_WERK}/base/lib" | tr '\n' ' '))"
else
  echo "   (geen native bibliotheken in de bundel — geen debug-symbols-zip nodig)"
fi
rm -rf "${SYMBOLEN_WERK}"

echo
echo "== 5/5: volgende stap =="
echo "   Upload deze .aab in Play Console → Test and release → Testing → Internal testing →"
echo "   Create new release (PLAY_DRAAIBOEK.md §4). Elke volgende upload: versionCode +1."
echo "   Ná de upload: App bundle explorer → (deze versie) → Downloads → 'Native debug symbols' →"
echo "   upload de -native-debug-symbols.zip. De mapping zit al ín de AAB (ReTrace-bestand hoeft"
echo "   niet apart, de -mapping.txt is de losse kopie voor als Play er tóch om vraagt)."
