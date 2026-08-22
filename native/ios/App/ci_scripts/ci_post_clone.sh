#!/bin/sh
# Xcode Cloud — ci_post_clone (blok D, 2026-08-22): elke cloud-build bundelt automatisch de
# ACTUELE web-assets (frontend --mode native → cap sync ios) en krijgt het buildnummer uit
# CI_BUILD_NUMBER. Draait vanuit native/ios/App/ci_scripts (Apple-conventie: naast het
# .xcodeproj); de repo-root staat in CI_PRIMARY_REPOSITORY_PATH.
#
# NB `npm ci` in native/ is hard nodig VÓÓR de SPM-resolve: CapApp-SPM/Package.swift draagt
# een lokale path-dependency naar ../../../node_modules/@capacitor/push-notifications.
set -e
set -x

REPO="${CI_PRIMARY_REPOSITORY_PATH:-$(cd "$(dirname "$0")/../../../.." && pwd)}"

# 1) Node bootstrap — het Xcode Cloud-image draagt geen Node; Homebrew wél. Versie gepind op
#    de major uit .nvmrc (repo-root); node@22 is keg-only, dus expliciet in de PATH.
NODE_MAJOR="$(cut -d. -f1 "$REPO/.nvmrc" 2>/dev/null | tr -d 'v' || true)"
NODE_FORMULE="node@${NODE_MAJOR:-22}"
if ! command -v node >/dev/null 2>&1; then
  brew install "$NODE_FORMULE" || brew install node
  BREW_NODE="$(brew --prefix "$NODE_FORMULE" 2>/dev/null || brew --prefix node)"
  export PATH="$BREW_NODE/bin:$PATH"
fi
node --version
npm --version

# 2) Webbundel bouwen: frontend (VITE_API_BASE uit frontend/.env.native) + cap sync ios
#    (kopieert dist → ios/App/App/public + genereert capacitor.config.json — beide bewust
#    niet ingecheckt).
cd "$REPO/frontend"
npm ci
cd "$REPO/native"
npm ci
npm run bouw-web
npx cap sync ios

# 3) Buildnummer uit Xcode Cloud (CI_BUILD_NUMBER) — deterministisch op beide plekken in het
#    pbxproj (Debug + Release); Info.plist leest CFBundleVersion uit $(CURRENT_PROJECT_VERSION).
#    MARKETING_VERSION blijft handmatig (versiebeleid STORE_GEREEDHEID §6).
if [ -n "$CI_BUILD_NUMBER" ]; then
  PBXPROJ="$REPO/native/ios/App/App.xcodeproj/project.pbxproj"
  sed -i '' -E "s/CURRENT_PROJECT_VERSION = [0-9]+;/CURRENT_PROJECT_VERSION = ${CI_BUILD_NUMBER};/g" "$PBXPROJ"
  grep -n "CURRENT_PROJECT_VERSION" "$PBXPROJ"
fi

echo "ci_post_clone klaar — web-assets gebundeld, buildnummer ${CI_BUILD_NUMBER:-'(lokaal, ongewijzigd)'}"
