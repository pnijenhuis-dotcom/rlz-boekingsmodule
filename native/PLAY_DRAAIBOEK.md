# Play-draaiboek "Nijenhuis Boekingsmodule" (Android, bouwronde 2026-08-28)

Klik-voor-klik-recept voor Peter, analoog aan `TESTFLIGHT_DRAAIBOEK.md`. Het doel van deze
ronde is een **interne test-track in Play Console** met een werkende, met FCM-push uitgeruste
Android-build — nog géén productierelease. STORE_GEREEDHEID.md blijft het canonieke dossier
(§3 Data safety, §4 reviewnotities, §6 versiebeleid); dit is het draaiboek. Geofence /
achtergrondlocatie zit **niet** in deze release — er is dus geen locatiemotivering nodig en
het bouwscript bewaakt dat het manifest geen `ACCESS_BACKGROUND_LOCATION` draagt.

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

**Alternatief zonder Android Studio (CLI-only):** `brew install --cask temurin@21
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

- **Elke volgende upload: versionCode +1** (Play weigert een hergebruikt nummer); versionName
  volgt de iOS `MARKETING_VERSION` (STORE_GEREEDHEID §6).
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
2. **Backend-config in `.github/workflows/deploy.yml`** (service-stap `--set-env-vars`), door de
   agent zodra jij de twee vingerafdrukken doorgeeft — of zelf:
   - `ANDROID_CERT_SHA256_VINGERAFDRUKKEN=["<SHA256-app-signing>","<SHA256-upload>"]` — activeert
     de referentie-route `/.well-known/assetlinks.json` op het app-subdomein
     (`app/auth/wellknown.py`, tot dan fail-closed 404);
   - in `WEBAUTHN_ORIGINS` de twee origins **erbij**:
     `android:apk-key-hash:<base64url-sha256-app-signing>` en
     `android:apk-key-hash:<base64url-sha256-upload>` (base64url zonder `=`; `android_keystore.sh`
     print die vorm voor de upload-key; voor Google's key: SHA-256-hex → bytes → base64url, bv.
     `echo "AA:BB:…" | tr -d ':' | xxd -r -p | base64 | tr '+/' '-_' | tr -d '='`).
   De deploy-run zet 'm live; daarna werkt de activeringsflow (wachtwoord → passkey via
   Credential Manager) in de Play-build. **Controle op het toestel** = §8 stap 1.

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
- Categorie: **Business**; Tags optioneel; Contact details: e-mail `p.nijenhuis@kempengroep.nl`,
  website `https://app.administratiekantoornijenhuis.nl`; External marketing: uit.

## 7. App content (dashboard-checklist) — antwoorden

Bron: STORE_GEREEDHEID §2/§3 (privacy-labels) + §1. Play stelt de vragen in deze volgorde:

| Onderdeel | Antwoord |
|---|---|
| **Privacy policy** | `https://app.administratiekantoornijenhuis.nl/accordeur/privacy` |
| **App access** | "All or some functionality is restricted" → **Add new instructions**: naam *Demo-account review*, gebruikersnaam `p.nijenhuis+applereview@kempengroep.nl`, wachtwoord = het review-wachtwoord uit TESTFLIGHT_DRAAIBOEK §0 (zelfde demo-account: SEED-PASSKEYTEST, uitsluitend fictieve facturen; seed met `backend/scripts/cloud_seed_review_demo.py` als dat nog niet gebeurd is). Extra uitleg: *"Invitation-only app. Sign in with e-mail + password; on first sign-in the app registers a passkey via the Android system prompt (Google Password Manager must be available on the device). Accept the terms screen to continue."* |
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
  (App access mét werkend demo-wachtwoord) volledig; reviewnotities-tekst staat in
  TESTFLIGHT_DRAAIBOEK §1 stap 6 (Engels; vervang de iOS-zinnen door *"registers a passkey via
  the Android Credential Manager / Google Password Manager"*).
- Gefaseerde uitrol; de PWA blijft parallel live als terugval (besluit 14-08) — passkeys blijven
  geldig (zelfde rp_id).
- Later, aparte afweging: CI-build van de AAB (Xcode Cloud-equivalent — bv. GitHub Actions met
  de upload-keystore als secret) zodat, net als op iOS, elke `main`-push een testbuild oplevert.
