# Play-draaiboek "Nijenhuis Boekingsmodule" (Android, bouwronde 2026-08-28)

Klik-voor-klik-recept voor Peter, analoog aan `TESTFLIGHT_DRAAIBOEK.md`. Het doel van deze
ronde is een **interne test-track in Play Console** met een werkende, met FCM-push uitgeruste
Android-build — nog géén productierelease. STORE_GEREEDHEID.md blijft het canonieke dossier
(§3 Data safety, §4 reviewnotities, §6 versiebeleid); dit is het draaiboek. Geofence /
achtergrondlocatie zit **niet** in deze release — er is dus geen locatiemotivering nodig en
het bouwscript bewaakt dat het manifest geen `ACCESS_BACKGROUND_LOCATION` draagt.

> **STAND 29-08 (uitgevoerd door de agent, besluit Peter 29-08 "installs toegestaan"):** §1 (JDK 21 +
> Android SDK, CLI-route), §2 (upload-keystore in `~/Sleutels/`) en §3 (release-AAB, gevalideerd) zijn
> **KLAAR** — details onderaan elke paragraaf. Ook de drie Play-screenshots (§6) staan in
> `store-assets/play/`. Wat er nog van jou nodig is: **§2 stap 2 (wachtwoordmanager) → §4 → §5 → §6
> (uploaden) → §7 → §8.** Twee Android-bevindingen uit de emulator-run zijn gefikst en zitten in de AAB
> (BESLISSINGEN "ANDROID-BOUWRONDE 28-08" rij 7): pdf.js-legacy-build (factuurbeeld faalde in WebView
> < 140) en het ⏻-glyph als SVG (tofu-blokje in de Android-font).

## 0. Wat er al klaar staat (voorwerk agent, 28-08 — geen klikwerk)

- **Firebase-registratie in de schil:** `native/android/app/google-services.json` staat in de
  repo (package `nl.aknijenhuis.goedkeuren`, project `rlz-boekhouding`; geen geheim — alleen
  project-id/-nummer, app-id en de publieke Android-API-key; Analytics UIT). `app/build.gradle`
  past het google-services-plugin **onvoorwaardelijk** toe (ontbreekt het bestand → build faalt
  luid), `variables.gradle` pint `firebase-messaging 25.0.1` voor `@capacitor/push-notifications`.
- **Manifest:** `POST_NOTIFICATIONS` (Android 13+) gedeclareerd; FCM-meta-data voor het
  statusbalk-icoon (`drawable/ic_stat_nijenhuis` — het N-monogram als monochrome
  VectorDrawable) en de meldingskleur (`color/notificatie_accent`, wordmark-teal).
- **Signing-plumbing:** `app/build.gradle` leest `native/android/keystore.properties`
  (gitignored) en signeert de release-variant met de upload-key; zonder dat bestand
  waarschuwt Gradle luid en blijft de AAB ongesigneerd. `versionCode`/`versionName` zijn
  overschrijfbaar (`-PversionCode=… -PversionName=…`).
- **Backend-verzendkant FCM: LIVE.** Firebase zit in hetzelfde GCP-project, dus de backend
  verstuurt via FCM HTTP v1 met de eigen Cloud Run-identiteit (Application Default
  Credentials): `run-backend@` (service — registratie-endpoint + handmatige herinner-knop) en
  `run-jobs@` (09:00-herinnering + nieuwe-facturen-bundel) hebben
  `roles/firebasecloudmessaging.admin`; `FCM_PROJECT_ID=rlz-boekhouding` staat op service +
  beide jobs (uitgevoerd via `scripts/gcp/fcm_afronden.sh`, én verankerd in deploy.yml). Geen
  server-key-secret — niets te roteren. Kill-switch en web-push zijn ongewijzigd.
  De Android-webview-origin `https://localhost` staat in `CORS_ALLOWED_ORIGINS` (deploy.yml;
  live bij de eerstvolgende deploy).
- **Scripts:** `native/scripts/android_keystore.sh` (§2), `native/scripts/bouw_android_release.sh`
  (§3), `native/scripts/genereer_play_assets.sh` (§6 — icoon 512 + feature graphic staan al in
  `store-assets/play/`).

Wat er van jou nodig is, in volgorde: **§1 → §2 → §3 → §4 → §5 → §6/§7 → §8.**

## 1. Eenmalig: JDK 21 + Android SDK op deze Mac (klikwerk, ~20 min)

Op deze Mac staan geen Java en geen Android SDK (gecontroleerd 28-08: `/usr/bin/java` is de
macOS-stub zonder runtime; `~/Library/Android/sdk` bestaat niet). De Gradle-schil vereist
JDK 21 (`capacitor.build.gradle` compileert op Java 21) en Android-platform 36.

**Aanbevolen route — Android Studio (levert SDK, build-tools, emulator én logcat):**

1. `brew install --cask temurin@21` → nieuwe terminal → `java -version` toont `openjdk 21…`.
   (Android Studio heeft een eigen JBR, maar de command-line-scripts hieronder gebruiken
   `java`/`keytool` uit PATH — daarom een losse JDK.)
2. `brew install --cask android-studio` → open **Android Studio** → Setup Wizard:
   *Standard* → licenties accepteren → Finish. Dit installeert de SDK in
   `~/Library/Android/sdk` mét de nieuwste platform + build-tools + emulator.
3. Android Studio → **More Actions → SDK Manager** → tab *SDK Platforms*: vink **Android 16
   (API 36)** aan; tab *SDK Tools*: **Android SDK Build-Tools 36**, **Android SDK
   Command-line Tools (latest)**, **Android Emulator**, **Android SDK Platform-Tools** →
   Apply.
4. Terminal, éénmalig in je shell-profiel (`~/.zshrc`):
   ```bash
   export ANDROID_HOME="$HOME/Library/Android/sdk"
   export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
   ```
   en voor Gradle: `echo "sdk.dir=$HOME/Library/Android/sdk" > native/android/local.properties`
   (gitignored).
5. Optioneel maar handig: `brew install bundletool` (officiële AAB-validatie + manifest-dump
   in §3) en een emulator voor §6/§8: Android Studio → **Device Manager → + → Pixel 8 →
   systeemimage API 36 (Google Play)** → Finish.
6. Controle: `cd native/android && ./gradlew --version` (Gradle 8.14.3, JVM 21) en
   `./gradlew assembleDebug` — een groene debug-build bewijst SDK + google-services-plugin.
   **Eerste compile van de Java-plugins** (`NatievePasskeyPlugin`, `VeiligeOpslagPlugin`) is
   hier — die zijn tot nu toe alleen op iOS-equivalent bewezen; compileert er iets niet, dan
   is dat een bevinding voor de agent, niet iets om zelf te patchen.

**✅ UITGEVOERD 29-08 (CLI-route, géén Android Studio):** `brew install openjdk@21` (de cask
`temurin@21` vereist `sudo` voor de pkg-installer en kon niet onbeheerd draaien — de Homebrew-formule is
dezelfde JDK 21, keg-only), `brew install --cask android-commandlinetools` + `brew install bundletool`,
`sdkmanager --licenses`, `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`
(+ `emulator` en `system-images;android-36;google_apis;arm64-v8a` voor §6), `local.properties` gezet
(`sdk.dir=/opt/homebrew/share/android-commandlinetools`, gitignored). `./gradlew --version` = Gradle
8.14.3 op JVM 21; **`./gradlew assembleDebug` groen — eerste échte compile van `NatievePasskeyPlugin` en
`VeiligeOpslagPlugin` zonder één fix** (javac zonder waarschuwingen op onze bronnen). Omdat de JDK
keg-only is, zetten de scripts/jij per shell:
```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
```
(zet dit in `~/.zshrc`; optioneel éénmalig `sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk
/Library/Java/JavaVirtualMachines/openjdk-21.jdk` zodat ook het macOS-stub-`java` werkt). Emulator-AVD
`play_1080x1920` (Pixel 2-profiel, API 36 google_apis) bestaat in `~/.android/avd/`. De melding "SDK XML
versions up to 3 … version 4" bij Gradle is cosmetisch (nieuwere cmdline-tools dan AGP kent).

**Alternatief zonder Android Studio (CLI-only, de gevolgde route):** `brew install --cask temurin@21
android-commandlinetools` → `sdkmanager --licenses` → `sdkmanager "platforms;android-36"
"build-tools;36.0.0" "platform-tools"` → `ANDROID_HOME=/opt/homebrew/share/android-commandlinetools`.
Geen emulator → screenshots (§6) en de kliktest (§8) dan op een echt Android-toestel.

## 2. Upload-keystore (Play App Signing-model) + wachtwoordmanager

Model: **Google bewaart de échte app-signing-key** (Play App Signing, aan bij het aanmaken van
de app). Wij signeren alleen de *upload* met een eigen upload-key. Kwijt of gelekt = reset via
Play Console-support (geen appverlies) — maar behandel 'm als productiegeheim.

1. `native/scripts/android_keystore.sh` — het script:
   - stopt luid als `keytool` geen echte JDK heeft (§1 eerst);
   - maakt `~/Sleutels/nijenhuis-goedkeuren-upload.jks` (BUITEN de repo; alias `upload`,
     RSA 4096, 10000 dagen — Play eist geldigheid tot ná 2033); een bestaande keystore wordt
     NOOIT overschreven;
   - vraagt één wachtwoord (≥ 16 tekens, voor store én key);
   - schrijft `native/android/keystore.properties` (gitignored, chmod 600) en bewijst dat git
     het negeert;
   - print de SHA-256 van het upload-certificaat in de twee vormen die §5 nodig heeft.
2. **Nu, meteen, in je wachtwoordmanager** (het script print dit blok):
   - naam: *Play upload-keystore Nijenhuis Boekingsmodule (nl.aknijenhuis.goedkeuren)*
   - bestand `~/Sleutels/nijenhuis-goedkeuren-upload.jks` — **voeg het .jks-bestand als
     bijlage toe** (Time Machine is geen kluis)
   - alias `upload`, het wachtwoord (store = key), de SHA-256-vingerafdruk.
3. Controle: `git status` mag geen `.jks`/`keystore.properties` tonen (vangnet in
   `native/.gitignore` én `native/android/.gitignore`).

**✅ UITGEVOERD 29-08:** keystore `~/Sleutels/nijenhuis-goedkeuren-upload.jks` (alias `upload`, RSA 4096,
10000 dagen) + `native/android/keystore.properties` (gitignored, bewezen). Het wachtwoord is door de
agent gegenereerd (32 tekens) en staat UITSLUITEND in **`~/Sleutels/nijenhuis-goedkeuren-upload.wachtwoord.txt`**
(chmod 600) — nergens in chat, log of repo. **Jouw stap 2:** zet keystore-bestand + wachtwoord in je
wachtwoordmanager en verwijder daarna desgewenst het .txt-bestand. Upload-key-vingerafdruk (géén geheim):
- SHA-256: `4A:B4:3C:F1:E9:86:EA:58:02:D7:3F:7A:78:13:FB:F5:EF:C0:17:0F:E8:35:00:01:2E:2C:45:02:00:E9:8F:A1`
- WebAuthn-origin: `android:apk-key-hash:SrQ88emG6lgC1z96eBP79e_AFw_oNQABLixFAgDpj6E`

## 3. Release-AAB bouwen + valideren

`native/scripts/bouw_android_release.sh [versionCode] [versionName]` — eerste upload:
```bash
native/scripts/bouw_android_release.sh 1 1.0
```
Het script bouwt de webbundel (`--mode native`, `VITE_API_BASE` = app-subdomein), doet
`cap sync android`, `./gradlew bundleRelease`, en valideert: signatuur = jouw upload-key
(`keytool -printcert -jarfile`), manifest + webbundel + notificatie-icoon aanwezig, en — als
`bundletool` er is — `bundletool validate` + package `nl.aknijenhuis.goedkeuren`,
versionCode/-Name, `POST_NOTIFICATIONS` aanwezig, `ACCESS_BACKGROUND_LOCATION` afwezig. Resultaat
+ SHA-256 komt in `native/android/app/release/` (gitignored).

**✅ UITGEVOERD 29-08:** `native/android/app/release/nijenhuis-goedkeuren-1.0-vc1-20260829-0919.aab`
(14 MB, gitignored) — signatuur = upload-key, bundletool validate ✓, package/versionCode 1/versionName
1.0 ✓, `POST_NOTIFICATIONS` ✓, geen `ACCESS_BACKGROUND_LOCATION` ✓, én de nieuwe guards: geen
`allowMixedContent`/emulator-API-base in de bundel, geen `usesCleartextTraffic` in het release-manifest
(die horen alleen bij de lokale debug-screenshotbuild, zie §6). Dít bestand sleep je in §4 stap 4.

**✅ versionCode 3 KLAARGEZET 07-09 (vervolgrun, blok 12d — NIET geüpload):**
`native/scripts/bouw_android_release.sh 3 1.0` (JAVA_HOME/ANDROID_HOME per shell, keystore.properties
aanwezig → gesigneerd met de upload-key, SHA-256 `4A:B4:3C:…:8F:A1` = de vingerafdruk in de live
assetlinks) → `native/android/app/release/nijenhuis-goedkeuren-1.0-vc3-20260907-1711.aab` (15 MB,
SHA-256 `1ccebc371b3eb7dc58ec75e92647e326be07e8d4a8e5c8dc11926c2f7cd9cdb2`) + `-mapping.txt` +
`-native-debug-symbols.zip`; bundletool validate ✓, versionCode 3 · versionName 1.0 ✓, alle guards ✓.
Webbundel = HEAD 07-09 mét build-id `fcc35a8-20260907-1511` (12a), `capacitor.plugins.json` noemt
`@capacitor/app` (E1 universal-link-fix). Inhoud t.o.v. vc2: E1 + E2 (06-09), 12a diagnoseregel, 12b
(geen verloren boot-refresh), **13 eerlijke melding bij ontbrekende passkey-beheerder** (§10).
Klikwerk: §4 stap 4 met dít bestand (interne test-track eerst), daarna App access (§11) + review.

- **Elke volgende upload: versionCode +1** (Play weigert een hergebruikt nummer); versionName
  volgt de iOS `MARKETING_VERSION` (STORE_GEREEDHEID §6).
- **Upload-artefacten náást de AAB (sinds 30-08):** het script legt in `app/release/` óók
  `<naam>-mapping.txt` (R8-mapping — identiteitsmodus, de app wordt bewust niet geobfusceerd; de
  mapping zit ook ín de AAB, Play leest 'm automatisch) en `<naam>-native-debug-symbols.zip`
  (de .so's uit de bundel — alleen androidx-datastore via Firebase, geen eigen native code). Die
  zip upload je ná de AAB-upload via App bundle explorer → versie → Downloads → *Native debug
  symbols*; daarmee verdwijnen de twee Play-waarschuwingen ("geen deobfuscation-bestand",
  "native code zonder debug-symbolen").
- Lokaal op een toestel proberen vóór de upload (optioneel): `bundletool build-apks
  --bundle=<aab> --output=/tmp/app.apks --ks=~/Sleutels/nijenhuis-goedkeuren-upload.jks
  --ks-key-alias=upload --connected-device` → `bundletool install-apks --apks=/tmp/app.apks`.
  NB zo'n lokale installatie is gesigneerd met de **upload**-key — passkeys werken dan pas als
  óók die vingerafdruk in §5 staat.

## 4. Play Console: app aanmaken onder PDL Powerhouse + interne test-track

Play Console = https://play.google.com/console → kies het **PDL Powerhouse**-ontwikkelaarsaccount
(waar de Vastly-app onder staat). Alles hieronder is klikwerk van jou; de agent maakt níéts aan.

1. **Create app**: App name **Nijenhuis Boekingsmodule** · Default language **Dutch –
   nl-NL** · App or game: **App** · Free or paid: **Free** (onomkeerbaar — gratis is juist) →
   verklaringen (Developer Program Policies, US export laws) aanvinken → **Create app**.
2. **Set up your app** (dashboard-checklist "Provide information about your app…") — de
   antwoorden staan in §7. Werk de lijst af: Privacy policy → App access → Ads → Content
   rating → Target audience → News apps → COVID-19 → Data safety → Government apps →
   Financial features → Health.
3. **Test and release → Setup → App signing** (verschijnt ná de eerste upload, maar het
   model kies je hier): laat **"Use Google-generated key"** staan (= Play App Signing; de key
   die jij in §2 maakte is dan automatisch de *upload key* zodra je de eerste AAB uploadt).
   NIET kiezen voor "export and upload a key" — we hebben geen bestaande app-signing-key.
4. **Test and release → Testing → Internal testing → Create new release**:
   - App bundles: upload de `.aab` uit §3 (sleep 'm erin). Play toont daarna versionCode 1,
     package, en "Signed by Google Play" (bewijs dat App Signing actief is).
   - Release name: `1.0 (1)` (default is prima). Release notes (nl-NL):
     `Eerste interne testversie: facturen goedkeuren met passkey, meldingen bij nieuwe facturen.`
   - **Next → Save → Review release → Start rollout to Internal testing.** Interne test =
     géén Google-review, direct beschikbaar (max. 100 testers).
5. **Testers** (tab *Testers* onder Internal testing): **Create email list** "Interne test
   Nijenhuis" → jouw Google-account(s) + kantoor → Save → onder *How testers join your test*
   → **Copy link** (opt-in-URL `https://play.google.com/apps/internaltest/…`). Testers openen
   die link op het toestel (ingelogd met een e-mail uit de lijst), tikken **Become a tester**
   → **Download it on Google Play**. Het duurt soms tot een uur voor de build zichtbaar is.
   ⚠️ De ≥ 12 testers / 14 dagen-eis geldt alleen voor *persoonlijke* developer-accounts —
   het PDL-organisatieaccount valt daarbuiten (STORE_GEREEDHEID §5 punt 4).
6. Noteer uit **Test and release → Setup → App signing** de twee certificaten (nodig in §5):
   - **App signing key certificate** → *SHA-256 certificate fingerprint* (Google's key — dit
     is waarmee de app bij testers geïnstalleerd wordt);
   - **Upload key certificate** → *SHA-256* (moet gelijk zijn aan wat §2 printte).

## 5. Passkeys op Android: assetlinks + `apk-key-hash`-origins (twee certificaten)

Zonder deze keten weigert Android de passkey-prompt in de app ("origin not allowed"/geen
credentials). De rp_id blijft de apex `administratiekantoornijenhuis.nl` (platformbesluit 0022),
dus **beide** vingerafdrukken uit §4 stap 6 moeten in twee configs:

1. **Statisch bestand op de WordPress-apex** (zelfde plek als de AASA, bindend):
   `https://administratiekantoornijenhuis.nl/.well-known/assetlinks.json`, inhoud —
   vervang beide `<SHA256-…>` door de vingerafdrukken mét dubbele punten, hoofdletters:
   ```json
   [{
     "relation": ["delegate_permission/common.handle_all_urls", "delegate_permission/common.get_login_creds"],
     "target": {
       "namespace": "android_app",
       "package_name": "nl.aknijenhuis.goedkeuren",
       "sha256_cert_fingerprints": ["<SHA256-app-signing-key>", "<SHA256-upload-key>"]
     }
   }]
   ```
   Content-Type moet `application/json` zijn; controleer met
   `curl -sI https://administratiekantoornijenhuis.nl/.well-known/assetlinks.json` en met
   Google's checker:
   `https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://administratiekantoornijenhuis.nl&relation=delegate_permission/common.get_login_creds`
   (moet beide statements teruggeven).
2. **Backend-config in `.github/workflows/deploy.yml`** (service-stap `--set-env-vars`) — één
   variabele, de rest leidt de code af (herzien 30-08, `app/auth/android_signing.py`):
   - `ANDROID_CERT_SHA256_VINGERAFDRUKKEN=["<SHA256-app-signing>","<SHA256-upload>"]` — activeert
     de referentie-route `/.well-known/assetlinks.json` op het app-subdomein
     (`app/auth/wellknown.py`, tot dan fail-closed 404) **én** levert de WebAuthn-origins:
     de backend berekent zélf `android:apk-key-hash:<base64url-sha256>` per certificaat en voegt ze
     toe aan de toegestane origins (`toegestane_webauthn_origins`). **Niets met de hand in
     `WEBAUTHN_ORIGINS` zetten** — de handmatige afleiding was precies de foutbron die hiermee
     verdwijnt. Een kapotte vingerafdruk laat de backend luid weigeren te starten (validator).
   - Het statische apex-bestand uit stap 1 komt uit dezelfde generator:
     `cd backend && .venv/bin/python -m app.auth.android_signing "<cert1>" "<cert2>" --schrijf
     ../native/apex-well-known/assetlinks.json` (print óók de origins ter controle); de test
     `tests/auth/test_android_signing.py` bewaakt dat apex-bestand en deploy.yml gelijk zijn.
   De deploy-run zet 'm live; daarna werkt de activeringsflow (wachtwoord → passkey via
   Credential Manager) in de Play-build. **Controle op het toestel** = §8 stap 1.

**✅ UITGEVOERD 30-08 (agent-kant):** beide certificaten in `deploy.yml` (Google app-signing-key
`2C:EA:…:3F:49` eerst, upload-key `4A:B4:…:8F:A1`), `native/apex-well-known/assetlinks.json`
gegenereerd, origins door de backend afgeleid (`android:apk-key-hash:LOoy-USnUvnbHoe0D9-HLPcUCSAd8VTJFnAsPeM-P0k`
voor Google's key, `…SrQ88emG6lgC1z96eBP79e_AFw_oNQABLixFAgDpj6E` voor de upload-key — de laatste is gelijk
aan wat `android_keystore.sh` op 29-08 onafhankelijk printte). **Jouw klikwerk:** stap 1 — het
gegenereerde `assetlinks.json` naar `/.well-known/` op de WordPress-hosting (op 30-08 gaf de apex nog
404) en daarna de curl + Google's checker hierboven; de deploy volgt automatisch de push naar main.

## 6. Store-listing (Main store listing) — teksten + grafisch

**Grow users → Store presence → Main store listing** (nl-NL). Teksten (uit STORE_GEREEDHEID §1/§5
en het TestFlight-draaiboek §2, in Play-limieten):

- **App name** (30): `Nijenhuis Boekingsmodule`
- **Short description** (80): `Facturen van je eigen administratie goedkeuren — veilig met een passkey.`
- **Full description** (4000):
  ```
  Keur inkoopfacturen van je eigen administratie goed of wijs ze af — veilig met een passkey,
  alleen op uitnodiging van Administratiekantoor Nijenhuis.

  • Factuur op volledig scherm, met het boekvoorstel van het kantoor eronder
  • Akkoord → automatisch de volgende factuur
  • Afwijzen met reden; vragen van het kantoor beantwoord je in de app
  • Melding bij nieuwe facturen en een dagelijkse herinnering — alleen als er echt iets openstaat
  • Ontgrendelen met vingerafdruk of gezichtsherkenning (passkey per apparaat)

  Deze app is bedoeld voor klanten van Administratiekantoor Nijenhuis. Er is geen open
  registratie: je ontvangt een uitnodiging per e-mail van het kantoor.
  ```
- **App icon** (512×512): `native/store-assets/play/icoon-512.png`.
- **Feature graphic** (1024×500, verplicht): `native/store-assets/play/feature-graphic-1024x500.png`.
  Beide komen uit `native/scripts/genereer_play_assets.sh` (zelfde bron-SVG als alle iconen).
- **Phone screenshots** (min. 2, max. 8; elke zijde 320–3840 px; **lange zijde ≤ 2× de korte**
  — de bestaande iPhone-screenshots zijn 2,17:1 en worden geweigerd). Maak ze in de emulator
  van §1 stap 5 met een **9:16-profiel** (Device Manager → nieuw toestel → *Pixel 2*
  1080×1920, of een eigen profiel 1080×1920) tegen een lokale backend met uitsluitend de
  fictieve demo-facturen (zelfde opzet als de iOS-set, STORE_GEREEDHEID §5 punt 5): wachtrij,
  factuurbeeld, ontgrendelscherm. Screenshot = emulator-camera-knop → `~/Desktop`; bewaar ze
  als `native/store-assets/play/screenshot-0{1,2,3}-*.png`.
  **✅ GEMAAKT 29-08:** `store-assets/play/screenshot-01-wachtrij.png`, `-02-factuurbeeld.png`,
  `-03-ontgrendelen.png` (1080×1920, donker thema, demo-statusbalk, uitsluitend de fictieve
  DEMO-2026-facturen op een lokale "Administratiekantoor Nijenhuis (demo)"-administratie). Recept
  (herhaalbaar, alles lokaal): lokale backend-instantie met
  `CORS_ALLOWED_ORIGINS='["https://localhost"]' AUTH_BIOMETRIE_DEV_STUB=true` op :8010; seed via
  `cloud_seed_accordeur.py` + `cloud_seed_review_demo.py` tegen de dev-DB (failsafe omzeild in een
  scratch-wrapper); debug-build met `VITE_API_BASE=http://10.0.2.2:8010 npm run bouw-web` +
  `NATIVE_LOKALE_BACKEND=1 npx cap sync android` (zet `allowMixedContent`; de debug-manifest-overlay
  `app/src/debug/AndroidManifest.xml` levert `usesCleartextTraffic`) + `assembleDebug`; emulator
  `play_1080x1920` headless (`-no-window`), `adb exec-out screencap`. De emulator heeft geen
  passkey-provider: de login liep via de dev-stub door in de debuggable webview (Chrome DevTools-
  protocol op `localabstract:webview_devtools_remote_<pid>`) de plugin-detectie uit te zetten; het
  ontgrendelscherm is het échte scherm (plugin-assertion faalt stil). Nooit echte klantdata.
- Categorie: **Business**; Tags optioneel; Contact details: e-mail `p.nijenhuis@kempengroep.nl`,
  website `https://app.administratiekantoornijenhuis.nl`; External marketing: uit.

## 7. App content (dashboard-checklist) — antwoorden

Bron: STORE_GEREEDHEID §2/§3 (privacy-labels) + §1. Play stelt de vragen in deze volgorde:

| Onderdeel | Antwoord |
|---|---|
| **Privacy policy** | `https://app.administratiekantoornijenhuis.nl/accordeur/privacy` |
| **App access** | "All or some functionality is restricted" → **Add new instructions**: naam *Demo-account review*, gebruikersnaam `p.nijenhuis+applereview@kempengroep.nl`, wachtwoord = het review-wachtwoord uit TESTFLIGHT_DRAAIBOEK §0 (zelfde demo-account: SEED-PASSKEYTEST, uitsluitend fictieve facturen; seed met `backend/scripts/cloud_seed_review_demo.py` als dat nog niet gebeurd is). Extra uitleg ("Any other information"): de tekst uit **§11** (herzien 07-09 ná de Play-afwijzing — mét de toestelvereisten schermvergrendeling + Google-account). Wachtwoord = het wachtwoord uit het eindrapport van de fixrun 07-09 (dezelfde waarde als in App Store Connect). |
| **Ads** | No, my app does not contain ads |
| **Content rating** | Start questionnaire → e-mail `p.nijenhuis@kempengroep.nl` → category **Utility, Productivity, Communication, or Other** → alle vragen **No** (geen geweld, seks, taal, gecontroleerde middelen, gokken, user-generated content, locatie-delen, aankopen) → Save → **Everyone / PEGI 3** |
| **Target audience and content** | Target age: **18 and over** only → "Store presence: appeal to children?" **No** |
| **News apps** | No |
| **COVID-19 contact tracing and status apps** | No (niet van toepassing) |
| **Data safety** | zie het blok hieronder |
| **Government apps** | No |
| **Financial features** | "My app doesn't provide any financial features" — de app toont en beoordeelt facturen van de eigen administratie maar biedt geen leningen, betalingen, bankieren, beleggen of crypto aan (facturen goedkeuren is een zakelijke workflow, geen financieel product). Twijfelt Play hierover in review: kies dan *Other financial products/services* en beschrijf exact dit. |
| **Health** | My app does not have health features |
| **Advertising ID** | No — de app gebruikt de advertising-ID niet (geen ad-/analytics-SDK) |

**Data safety-formulier (vragenlijst, Play-vorm van STORE_GEREEDHEID §3):**

1. *Does your app collect or share any of the required user data types?* → **Yes**.
2. *Is all of the user data collected by your app encrypted in transit?* → **Yes** (https/TLS).
3. *Do you provide a way for users to request that their data is deleted?* → **Yes** — via het
   kantoor (AVG-proces: pseudonimiseren ná relatie-einde + 7 jaar bewaarplicht; contactadres in
   de privacyverklaring). *Does your app allow users to create an account?* → **No**
   (uitnodiging-only) → geen account-deletion-URL vereist.
4. *Data types* — per type: **Collected: Yes · Shared: No · Processed ephemerally: No ·
   Required: Yes · Purpose: App functionality + Account management**:
   - Personal info → **Name**, **Email address**, **User IDs** (platform-gebruikers-id)
   - Financial info → **Other financial info** (facturen van de eigen administratie worden
     getoond en beoordeeld; verwerking op onze servers in de EU)
   - Device or other IDs → **Device or other IDs** (apparaat-gebonden sessie + FCM-pushtoken)
   - NIET aangevinkt: Location, Messages, Photos/videos, Audio, Files, Calendar, Contacts,
     App activity, Web browsing, App info and performance (geen crash-/analytics-SDK), Health.
5. FCM (Google) bezorgt alleen de melding als *service provider* op onze instructie — dat is
   in Play-termen géén "sharing"; de payload bevat uitsluitend een aantal + deep-link.
6. **Submit** → de samenvatting toont "Data is encrypted in transit / You can request that data
   be deleted / Data shared with third parties: none".

## 8. Kliktest op een Android-toestel (bewijs FCM + passkeys)

Ná §4 (build via de opt-in-link geïnstalleerd) en §5 (assetlinks + origins live):

1. **Passkey-keten:** open de app → activatielink/inloggen met een accordeur-account → de
   Android-passkey-prompt (Google Password Manager) verschijnt bij registratie en bij
   ontgrendelen. Verschijnt hij niet of meldt de app "origin"/"niet toegestaan": §5 nog niet
   compleet (beide vingerafdrukken?) of de Play-build is met een ander certificaat gesigneerd
   dan verwacht — controleer `Play Console → App signing` vs. het assetlinks-bestand.
2. **Meldingen aan:** in de activeringsflow (meldingen-kaart) → Android 13+ vraagt toestemming
   → de app registreert het FCM-token (`POST /notificaties/push/subscripties/native`
   soort=fcm). Een **409** hier = FCM niet geconfigureerd op de server → deploy nog niet
   gelopen ná deze ronde (FCM_PROJECT_ID staat al live; de code-deploy volgt de push naar main).
3. **Bewijs-push:** kantoor-UI → klantpagina → accorderingssectie → **handmatige herinner-knop**
   (max 1 per document per dag) óf `gcloud run jobs execute rlz-accordeur-herinneringen
   --region europe-west4 --wait`. Verwacht: melding met het N-monogram (teal) in de statusbalk,
   tap = deep-link naar het document ná ontgrendeling. Geen melding? Logs:
   `gcloud logging read 'resource.labels.job_name=rlz-accordeur-herinneringen' --limit=20` —
   `FCM weigerde (403)` = IAM (draai `scripts/gcp/fcm_afronden.sh` opnieuw), `UNREGISTERED` =
   token vervallen (app opnieuw installeren en meldingen opnieuw aanzetten).
4. **Kill-switch:** Instellingen → apparaten → intrekken → de app valt terug naar login en de
   push stopt (zelfde bewijs als de iOS-ronde 2).
5. Leg de uitkomst vast: BESLISSINGEN "ANDROID-BOUWRONDE 28-08" (status → *bewezen op toestel*).

## 9. Daarna

- **Closed test → Production** = Google-review (1–7 dagen): dan tellen §6 (screenshots) en §7
  (App access mét werkend demo-wachtwoord) volledig; de reviewer-instructie voor Play staat in
  **§11** (Engels, genummerd, mét toestelvereisten) — de iOS-variant in TESTFLIGHT_DRAAIBOEK §1
  stap 6. Afwijzing 07-09 ("Login credentials are incorrect"): wortel + herstel in **§10**.
- Gefaseerde uitrol; de PWA blijft parallel live als terugval (besluit 14-08) — passkeys blijven
  geldig (zelfde rp_id).
- Later, aparte afweging: CI-build van de AAB (Xcode Cloud-equivalent — bv. GitHub Actions met
  de upload-keystore als secret) zodat, net als op iOS, elke `main`-push een testbuild oplevert.

## 10. Afwijzing 07-09 — wortel + herstel (Play; zelfde build als de Apple-2.1-afwijzing)

> **Noot 08-09 (besluit Peter 08-09, platformbesluit 0029):** de wortel hieronder — passkey-registratie via Credential Manager,
> die zonder Google-account (en schermvergrendeling) faalt — is **structureel weg**: de app kent sinds de run van 08-09 geen
> passkey, wachtwoord of TOTP meer; activeren = activatiecode (of link) → 5-cijferige app-code. Variant A/B/C uit de
> beslispunten van 07-09 zijn daarmee vervallen (B zat in versionCode 3, is nu uit de bundel). De logtabel en de
> emulator-reproductie blijven staan als historie. Nieuwe reviewer-instructie: **§11 (herschreven 08-09)**; toestelvereisten
> vooraf zijn er niet meer. Android-build: `bouw_android_release.sh 4 1.0` ná de commit van 08-09 (TESTFLIGHT §0e).

Play Console wees de ingediende build af met *"Login credentials are incorrect"* (demo-account).
Apple wees dezelfde dag build 1.0 (44) af op 2.1 (TESTFLIGHT_DRAAIBOEK §0b). **Bij Play is de wortel
een ándere dan bij Apple** (blok PLAY, fixrun 07-09 — Cloud Logging op `rlz-backend`, auth-routes,
03–07-09):

| Wanneer (UTC) | Herkomst | Wat de reviewer deed | Uitkomst |
|---|---|---|---|
| 03-09 10:55–11:00 | `2001:4860:…` = **Google LLC (IPv6)**, UA *Android 12; Pixel 6 … wv* | 3× "Inloggen met passkey" → `passkey-login/opties` **409**; daarna **7× `/auth/accordeur/login` → 200** (wachtwoord GOED) zonder vervolgstap; daarna 3× 401 (varianten geprobeerd) | strandde ná de wachtwoordstap = op de passkey-registratie |
| 03-09 19:48–19:52 | 103.62.154.196 (PH, Parasat Cable TV), UA *Android 12; SM-S928B … wv* | 2× 409, daarna **11× login → 200** zonder vervolg | idem — tweede reviewer/toestel |
| 04-09 09:49–09:59 | Apple (17.185.64.x / 139.178.129.4, iOS 18.7) | 20× login → **401** | Apple: wachtwoord-mismatch (§0b TestFlight) |

De aanname in de Apple-analyse ("03-09 was de wachtwoordstap 17× groen = Peters eigen Android-tests")
klopt dus niet: die 18 groene wachtwoordstappen kwamen van Google's reviewers. Zij hadden het juiste
wachtwoord en kwamen niet voorbij de passkey-stap — Play rapporteert dat als "credentials incorrect".

**Reproductie (07-09, kale reviewer-emulator):** AVD `review_pixel` (Pixel 7, `system-images;android-36;
google_apis_playstore;arm64-v8a`, koude start, géén schermvergrendeling, géén Google-account), release-APK
gesigneerd met de upload-key (staat in de live assetlinks) tegen productie:

1. Start → passkey-eerst-scherm → "Inloggen met wachtwoord" → e-mail + wachtwoord → **200**
   (`accordeur_login_wachtwoord_ok` in het audit-log).
2. Passkey-registratie faalt direct, zonder enige systeemdialoog, met de in-app-melding
   **"Passkey-registratie mislukt: No create options available."** De reviewer blijft op het
   loginscherm (velden gevuld, rode balk) en kan niet verder. logcat: `Auth.Api.Credentials:
   [CreateRemotePasskeyOperation] Operation failed … [28433]`, `[CreatePasswordOrPasskeyOperation]
   Operation failed … [28434]`, `CredentialManager: Provider status changed: CANCELED, source:
   REMOTE_PROVIDER`.
3. Mét schermvergrendeling (`adb shell locksettings set-pin 1234`) en opnieuw inloggen: **identieke
   fout.** De schermvergrendeling alléén is dus niet genoeg: Google Password Manager maakt alleen
   passkeys voor een **op het toestel aangemeld Google-account** (de passkey wordt aan dat account
   gesynchroniseerd); zonder account biedt Credential Manager geen enkele aanmaak-optie. Een
   Google-account toevoegen was in deze run niet mogelijk (geen testaccount) — de stap "passkey →
   code → wachtrij → PDF" is op Android daarom niet in de emulator bewezen; op een echt toestel mét
   account is die keten wél bewezen (Peters Xiaomi-activatie 02-09; iOS-keten iPad-simulator 07-09).
4. Passkey-eerst-pad zonder passkey ("Inloggen met passkey" + e-mail) geeft de generieke melding
   *"Geen passkey voor dit adres — vraag het kantoor om een nieuwe activatielink"* (bewust, 0022-lijn).

**Herstel (één herstel voor beide stores):**
- Demo-account 07-09 13:27 opnieuw definitief gezet (`cloud_seed_review_demo.py --genereer-wachtwoord`
  tegen productie; passkeys 0; wachtrij 8 fictieve facturen). Het wachtwoord staat uitsluitend in het
  eindrapport van de fixrun — **het wachtwoord uit het ochtendrapport van 07-09 is daarmee ongeldig.**
- Reviewer-instructie **§11** mét toestelvereisten (schermvergrendeling + Google-account) vóór de
  eerste login; zelfde tekst (iOS-variant) in TESTFLIGHT_DRAAIBOEK §1.
- **Geen app-wijziging** in de fixrun van 07-09. Het kleinste codepad voor "wachtwoord-login mét
  uitgestelde passkey-setup" (variant A) staat als beslispunt in BESLISSINGEN "GOOGLE PLAY AFWIJZING
  07-09" — het verzwakt platformbesluit 0020 (passkeys-eerst) en is bewust NIET gebouwd.
- **Variant B GEBOUWD (vervolgrun 07-09, blok 13; zit in versionCode 3, §3):** herkent de
  Credential-Manager-fout ("No create options available", GMS 28433/28434, `CANCELED … REMOTE_PROVIDER`,
  "No provider dependencies") in `frontend/src/accordeur/passkeyFouten.ts` en toont op Android i.p.v.
  de kale fout: *"Op dit toestel is geen passkey-beheerder actief — voeg een Google-account toe of zet
  schermvergrendeling aan; of gebruik een ander toestel."* Een weggetikte sheet blijft "geannuleerd";
  iOS/web ongewijzigd; géén alternatieve loginroute (0020 onverkort). De reviewer op een kaal toestel
  ziet nu dus wat hij moet doen — §11 blijft de instructie vóóraf.
- **Diagnoseregel (blok 12a) als kliktest-hulp:** in de app → ⚙ (Toegang tot de app) → "Diagnose ›
  Laatste koude start" toont één kopieerbare regel `web <sha-datum> · app 1.0 (3) · boot … ms ·
  sessie … ms · server … ms · netwerk … ms · totaal … ms · dd-mm HH:MM` (lokaal, nooit naar de server).
  `app 1.0 (3)` bevestigt de juiste versionCode; een screenshot vervangt `chrome://inspect`.

> **Aanvulling 08-09 (bouwagent BLOK 8) — Play-bewijs 07-09 toonde "Ongeldige inloggegevens":**
> tijdens (of kort na) de herstel-run van 07-09 gaf een Play-testpoging op het demo-account de
> melding "Ongeldige inloggegevens" — geverifieerd in de code dat dit de generieke, opzettelijk
> niet-onthullende foutmelding is die het backend-endpoint `POST /auth/accordeur/login` teruggeeft
> als **HTTP 401** (`webauthn_service.start_accordeur_login`: elk faalpad — onbekend e-mailadres,
> verkeerde rol/status, of een fout wachtwoord via `verify_password` — geeft dezelfde tekst
> `"Ongeldige inloggegevens"`, bewust géén account-enumeratie; `backend/app/auth/router.py` vertaalt
> `AuthError` op deze route naar `HTTP_401_UNAUTHORIZED`). Dat is dus GEEN app-fout en geen aparte
> bug — het is precies het gedrag dat een verkeerd wachtwoord hoort te geven. **Aannemelijkste
> verklaring:** het demo-wachtwoord is op 07-09 tweemaal gewijzigd (een ochtend-reset vóór 13:27
> UTC, daarna nogmaals door de fixrun van blok PLAY om 13:27 UTC — zie de "Herstel"-bullets
> hierboven) — een testpoging met een wachtwoord van vóór 13:27 UTC (bv. het ochtendwachtwoord, of
> een reviewer/Peter die het net ververste wachtwoord nog niet had) faalt daarna correct met 401.
> **Niet live geverifieerd:** de gcloud-tokens waren bij het schrijven van deze aanvulling verlopen
> (`gcloud auth print-access-token` → Reauthentication failed), dus de exacte timing kon niet tegen
> Cloud Logging getoetst worden. Klaargezet commando (ná `gcloud auth login`) om te bevestigen dat
> de 401-poging(en) vóór 13:27 UTC liggen (dus verklaard door het oude wachtwoord) en niet erna
> (wat een nieuw probleem zou zijn):
> ```bash
> gcloud logging read '
>   resource.type="cloud_run_revision"
>   resource.labels.service_name="rlz-backend"
>   httpRequest.requestUrl:"/auth/accordeur/login"
>   httpRequest.status=401
>   timestamp>="2026-09-07T00:00:00Z"
>   timestamp<="2026-09-08T00:00:00Z"
> ' --project rlz-boekhouding --format=json --limit 50
> ```
> Toets ook `platform.audit_event` (actie `login_mislukt`) op dezelfde vensters voor een tweede
> bevestiging. Bevestigt de log geen 401-pogingen rond die tijd, dan is de "ochtend-reset"-verklaring
> onjuist en moet de wortel opnieuw onderzocht worden.

**Klikwerk Peter (Play Console):** Policy → **App content → App access** → de instructie
*Demo-account review* bewerken: username `p.nijenhuis+applereview@kempengroep.nl`, password = het
nieuwe wachtwoord, "Any other information" = §11 → Save. Daarna de afgewezen release opnieuw ter
review aanbieden (**Publishing overview → Send changes for review**, of de release opnieuw
uitrollen op dezelfde track). Play kent geen reply-kanaal zoals het Resolution Center; de uitleg
moet volledig in App access staan.

## 11. Reviewer-instructie "Sign in details" (Play Console › App content › App access)

**HERSCHREVEN 08-09 (besluit 0029 — geen passkey meer in de app).** Velden: *Instruction name* `Demo-account review` ·
*Username* `p.nijenhuis+applereview@kempengroep.nl` · *Password* **`<activatiecode uit het eindrapport>`** (de app heeft
geen wachtwoord meer; het verplichte Password-veld draagt de 8-tekens activatiecode `XXXX-XXXX` — herbruikbaar en
niet-verlopend voor uitsluitend dit demo-account, gezet met `cloud_seed_review_demo.py --genereer-activatiecode`,
TESTFLIGHT §0e) · *Any other information* = onderstaande tekst (Engels).

> Het veld "Any other information" heeft een harde limiet van **500 tekens** (correctie 08-09 blok 8). Onderstaande tekst is
> **481 tekens** (geteld met Python `len()` op de kale string, incl. spaties/regeleinden, exclusief de code-fence).
> Wijzig je de tekst ooit weer: tel opnieuw vóór het opslaan (`python3 -c "print(len(open('tekst.txt').read()))"`).

```
Invitation-only app. No passkey, Google account, screen lock or password needed.

Steps: 1) Open the app: screen "Activatiecode invoeren". 2) Enter the activation code given as the password above (8 characters, XXXX-XXXX), tap "Activeren". 3) If a terms screen appears, tick and confirm. 4) Choose a 5-digit app code and repeat it. 5) The approval queue with demo invoices appears; tap an invoice, approve or reject.

Code rejected? Mail p.nijenhuis@kempengroep.nl for a fresh one.
```

**App Store Connect › App Review Information › Notes** is een ANDER, veel ruimer veld en draagt de volledige, uitgeschreven
iOS-tekst — zie **TESTFLIGHT_DRAAIBOEK.md §1 stap 6 (herschreven 08-09)**. Beide teksten dragen dezelfde kernboodschap
(geen toestelvereisten meer; activatiecode → app-code → wachtrij) — wijzig ze samen als de flow verandert.

**Klikwerk Peter (Play Console, ná deploy + seed + AAB versionCode 4 op de interne test-track):** Policy → App content → App
access → *Demo-account review* bewerken: Password = activatiecode, "Any other information" = de tekst hierboven → Save →
release opnieuw ter review (**Publishing overview → Send changes for review**). Play kent geen reply-kanaal; de uitleg moet
volledig in App access staan.

> Historische versie van §11 (07-09: "tik Inloggen met wachtwoord", toestelvereisten schermvergrendeling + Google-account,
> 497 tekens): vervangen op 08-09; niet meer indienen. De emulator-reproductie in §10 blijft de bron voor de oude wortel.
