#!/usr/bin/env bash
# =============================================================================
# Upload-keystore voor Google Play (Play App Signing-model) — Android-bouwronde 28-08.
#
# MODEL: Google bewaart en gebruikt de échte app-signing-key (Play App Signing, aan bij het
# aanmaken van de app in Play Console). Wij signeren alleen de UPLOAD met deze upload-key;
# raakt die kwijt/lek, dan is 'm resetten bij Google klikwerk (geen appverlies). Daarom:
#   - keystore BUITEN de repo (default ~/Sleutels/), nooit in git (vangnet in .gitignore);
#   - wachtwoorden alleen in native/android/keystore.properties (gitignored) én in Peters
#     wachtwoordmanager (dit script print precies wat daar in moet);
#   - één alias 'upload', RSA 4096, 25+ jaar geldig (Play eist geldigheid tot ná 2033-10-22).
#
# WAT HET DOET (idempotent — een bestaande keystore wordt NOOIT overschreven):
#   1. controleert een échte JDK (het macOS-stub-keytool zonder JRE faalt hier luid);
#   2. maakt ~/Sleutels/nijenhuis-goedkeuren-upload.jks (of $KEYSTORE_PAD) mét één
#      wachtwoord voor store én key (Play accepteert dat; minder om kwijt te raken);
#   3. schrijft native/android/keystore.properties (chmod 600) voor app/build.gradle;
#   4. print de SHA-256 van het upload-certificaat in twee vormen: de assetlinks-vingerafdruk
#      met dubbele punten (dé configwaarde: ANDROID_CERT_SHA256_VINGERAFDRUKKEN) en ter controle
#      de WebAuthn-origin android:apk-key-hash:<base64url>, die de backend sinds 30-08 zélf
#      afleidt (app/auth/android_signing.py) — NB dat zijn de waarden van de UPLOAD-key; de
#      door Play gedistribueerde app is gesigneerd met Google's app-signing-key, dus
#      PLAY_DRAAIBOEK.md §5 vult daar de tweede set uit Play Console bij.
#
# Gebruik:  native/scripts/android_keystore.sh
#           KEYSTORE_PAD=/pad/naar/anders.jks native/scripts/android_keystore.sh
# =============================================================================
set -euo pipefail

HIER="$(cd "$(dirname "$0")/.." && pwd)"
KEYSTORE_PAD="${KEYSTORE_PAD:-${HOME}/Sleutels/nijenhuis-goedkeuren-upload.jks}"
ALIAS="upload"
PROPS="${HIER}/android/keystore.properties"
DN="CN=Nijenhuis Boekingsmodule upload, OU=Administratiekantoor Nijenhuis, O=PDL Powerhouse, L=Veldhoven, C=NL"

echo "== 1/4: JDK-controle =="
if ! keytool -help >/dev/null 2>&1; then
  echo "   FOUT: 'keytool' werkt niet — er staat geen Java Runtime op deze Mac (het macOS-stub"
  echo "   /usr/bin/keytool verwijst naar niets). Installeer eerst JDK 21 (PLAY_DRAAIBOEK.md §1):"
  echo "     brew install --cask temurin@21"
  echo "   en open daarna een nieuwe terminal. Gestopt — niets aangemaakt."
  exit 1
fi
JAVA_VERSIE="$(java -version 2>&1 | head -1)"
echo "   ${JAVA_VERSIE}"

echo
echo "== 2/4: upload-keystore =="
if [ -f "${KEYSTORE_PAD}" ]; then
  echo "   ${KEYSTORE_PAD} bestaat al — NIET overschreven (een tweede upload-key maakt de"
  echo "   Play-upload ongeldig). Alleen keystore.properties + vingerafdrukken worden bijgewerkt."
  read -r -s -p "   Wachtwoord van de bestaande keystore: " WACHTWOORD; echo
else
  mkdir -p "$(dirname "${KEYSTORE_PAD}")"
  chmod 700 "$(dirname "${KEYSTORE_PAD}")"
  echo "   Kies een sterk wachtwoord (≥ 16 tekens; komt in je wachtwoordmanager als"
  echo "   'Play upload-keystore Nijenhuis Boekingsmodule'). Zelfde wachtwoord voor store én key."
  while true; do
    read -r -s -p "   Wachtwoord: " WACHTWOORD; echo
    read -r -s -p "   Nogmaals:   " WACHTWOORD2; echo
    if [ "${WACHTWOORD}" != "${WACHTWOORD2}" ]; then echo "   Komt niet overeen — opnieuw."; continue; fi
    if [ "${#WACHTWOORD}" -lt 16 ]; then echo "   Te kort (< 16) — opnieuw."; continue; fi
    break
  done
  keytool -genkeypair -v \
    -keystore "${KEYSTORE_PAD}" -storetype PKCS12 \
    -alias "${ALIAS}" -keyalg RSA -keysize 4096 -validity 10000 \
    -dname "${DN}" \
    -storepass "${WACHTWOORD}" -keypass "${WACHTWOORD}" >/dev/null
  chmod 600 "${KEYSTORE_PAD}"
  echo "   aangemaakt: ${KEYSTORE_PAD} (alias '${ALIAS}', RSA 4096, 10000 dagen)."
fi

echo
echo "== 3/4: native/android/keystore.properties (gitignored) =="
# Gradle's Properties-loader: backslashes/`=`/`:` in het wachtwoord escapen.
escape_prop() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/=/\\=/g' -e 's/:/\\:/g' -e 's/#/\\#/g' -e 's/!/\\!/g'; }
umask 077
cat > "${PROPS}" <<EOF
# Upload-signing (Play App Signing-model) — GEGENEREERD door native/scripts/android_keystore.sh.
# Nooit committen (gitignored). Zelfde waarden staan in Peters wachtwoordmanager.
storeFile=${KEYSTORE_PAD}
storePassword=$(escape_prop "${WACHTWOORD}")
keyAlias=${ALIAS}
keyPassword=$(escape_prop "${WACHTWOORD}")
EOF
chmod 600 "${PROPS}"
echo "   geschreven: ${PROPS}"
if git -C "${HIER}" check-ignore -q "${PROPS}"; then
  echo "   git negeert het bestand (vangnet werkt)."
else
  echo "   FOUT: git negeert ${PROPS} NIET — commit dit niet; controleer native/.gitignore. Gestopt."
  exit 1
fi

echo
echo "== 4/4: vingerafdrukken van het UPLOAD-certificaat =="
CERT_DER="$(mktemp)"
keytool -exportcert -rfc -keystore "${KEYSTORE_PAD}" -alias "${ALIAS}" -storepass "${WACHTWOORD}" 2>/dev/null \
  | openssl x509 -outform DER -out "${CERT_DER}"
SHA_HEX="$(openssl dgst -sha256 -binary "${CERT_DER}" | xxd -p -c 256 | tr 'a-f' 'A-F')"
SHA_COLON="$(printf '%s' "${SHA_HEX}" | sed 's/../&:/g; s/:$//')"
SHA_B64URL="$(openssl dgst -sha256 -binary "${CERT_DER}" | base64 | tr '+/' '-_' | tr -d '=')"
rm -f "${CERT_DER}"
cat <<EOF
   SHA-256 (assetlinks.json / ANDROID_CERT_SHA256_VINGERAFDRUKKEN):
     ${SHA_COLON}
   WebAuthn-origin (ter controle — de backend leidt deze ZELF af uit de vingerafdruk hierboven,
   app/auth/android_signing.py; NIET met de hand in WEBAUTHN_ORIGINS zetten):
     android:apk-key-hash:${SHA_B64URL}

   ⚠️  Dit is de UPLOAD-key. Een via Play geïnstalleerde build (interne test, productie) is
   gesigneerd met Google's APP-SIGNING-key — die tweede SHA-256 haal je uit Play Console →
   Test and release → Setup → App signing ("App signing key certificate") en gaat er in
   beide config-lijsten BIJ (PLAY_DRAAIBOEK.md §5). Beide sets moeten erin staan zolang
   je ook lokaal (bundletool/apk uit deze keystore) installeert.

IN JE WACHTWOORDMANAGER (nu, vóór je iets anders doet):
   naam      : Play upload-keystore Nijenhuis Boekingsmodule (nl.aknijenhuis.goedkeuren)
   bestand   : ${KEYSTORE_PAD}   (maak óók een kopie van het .jks-bestand als bijlage)
   alias     : ${ALIAS}
   wachtwoord: <wat je net koos — store én key>
   SHA-256   : ${SHA_COLON}
EOF
