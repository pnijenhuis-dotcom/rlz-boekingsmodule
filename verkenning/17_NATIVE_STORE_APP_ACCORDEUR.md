# Voorverkenning native store-app accordeur (Capacitor-schil)

**Datum:** 2026-08-16 · **Status:** voorverkenning uitgevoerd — dit rapport is de basis voor
het go/no-go-bouwbesluit (besluit Peter 2026-08-14: store-apps zsm, PWA blijft interim +
terugval; BESLISSINGEN "Mobiele bouwstenen accordeur-PWA" punt 8, platformbesluit 0010/0020/0022).

> **GO (besluit Peter 2026-08-16): bouw gestart langs de aanbevolen route** — native-
> passkey-plugin + APNs/FCM + gebundelde assets + bearer-refresh in Keychain/Keystore, géén
> remote-wrapper; bundle-id `nl.aknijenhuis.goedkeuren` akkoord. Bouwstatus per fase +
> kliktest-blokken: zie "Bouwstatus (ná GO)" onderaan dit rapport. Statusregister:
> BESLISSINGEN "NATIVE-APP FASE …".

**Wat er nu staat (deze run, GEEN publicatie):** map `native/` met een werkende
Capacitor 8-schil rond de bestaande PWA-build — `capacitor.config.ts`
(appId-vóórstel `nl.aknijenhuis.goedkeuren`, appName destijds "RLZ Goedkeuren" —
**hernoemd 2026-08-19, besluit Peter: productnaam "Nijenhuis Boekingsmodule",
beginscherm-naam kort "Nijenhuis"; bundle-id ongewijzigd** —,
`webDir: ../frontend/dist` — **de webcode is niet geraakt**), iOS-project via **Swift
Package Manager** (bewust geen CocoaPods-afhankelijkheid) én Android-project, beide met de
actuele PWA-build gebundeld (`npx cap sync` geverifieerd). Gegenereerde sync-artefacten
staan in .gitignore.

## Lokale iOS-build — wat werkt al, wat ontbreekt

Werkt al op deze Mac: `cd native && npm install && npm run bouw-web && npx cap sync`
(webassets + Package.swift up-to-date). **Ontbreekt lokaal: de volledige Xcode-app** — er
staan alleen Command Line Tools (`xcode-select -p` → CommandLineTools; `xcodebuild` weigert).
Zodra Xcode (App Store, ~12 GB) geïnstalleerd is, is de build:

```
cd native && npx cap open ios     # opent ios/App/App.xcodeproj
# of headless: xcodebuild -project ios/App/App.xcodeproj -scheme App \
#   -destination 'platform=iOS Simulator,name=iPhone 16' build
```

Simulator-build vergt géén Developer-account; op een echt toestel draaien kan met een gratis
personal team (7-dagen-profiel), distribueren niet. CocoaPods is dankzij de SPM-keuze niet
nodig. Android: build vergt Android Studio/SDK (niet aanwezig, zelfde patroon).

## (a) Passkeys/WebAuthn in de native context — HET kernvraagstuk

De accordeur-auth-cadans hangt volledig aan WebAuthn (`navigator.credentials` in
`frontend/src/accordeur/webauthnClient.ts`). In een Capacitor-app draait de webcode in een
**WKWebView, en die heeft géén WebAuthn**: Apple beperkt de web-API tot Safari/
SFSafariViewController — `navigator.credentials.create/get` bestaat simpelweg niet in de
webview (en `webauthnBeschikbaar()` geeft daar dus netjes false). Drie routes:

1. **Native passkey-plugin (AANBEVOLEN).** Een Capacitor-plugin bridged naar de native
   passkey-API's: iOS `ASAuthorizationPlatformPublicKeyCredential…` (ASAuthorizationController),
   Android Credential Manager. De webcode houdt dezelfde base64url-JSON-flows
   (registratie-opties → attestation, login-opties → assertion); alleen `webauthnClient.ts`
   krijgt een seam "native beschikbaar? → plugin, anders navigator.credentials". Backend
   (py_webauthn) blijft ongewijzigd op één punt na: `webauthn_origins` moet de native
   origins accepteren — **de lijst-vorm bestaat al** (`webauthn_service.py`, expected_origin
   is een list). iOS levert als origin `https://administratiekantoornijenhuis.nl` (het
   associated domain), Android `android:apk-key-hash:<sha256-van-de-signing-key>`.
   Voorwaarden:
   - **rp_id blijft de apex** `administratiekantoornijenhuis.nl` (besluit 0022) — bestaande
     passkeys van PWA-gebruikers blijven dan gewoon wérken in de native app (zelfde rp_id!).
   - iOS **Associated Domains**: entitlement `webcredentials:administratiekantoornijenhuis.nl`
     + een `/.well-known/apple-app-site-association` op de apex met het app-id.
   - Android: `/.well-known/assetlinks.json` op de apex met de signing-key-hash.
   - Beide bestanden kan onze backend/hosting serveren; klein infra-taakje (F2-domein).
2. **ASWebAuthenticationSession / Custom Tabs**: login in een echte browser-sheet. Werkt
   zonder plugin, maar de cadans "passkey-assertion éénmaal per app-opening" wordt dan een
   browser-popup per opening — UX-breuk met het hele blok-2-ontwerp. Alleen terugval.
3. **Wachtwoord+TOTP in de webview**: werkt technisch, maar is precies wat besluit 0020
   (passkeys eerste lijn) niet wil. Geen route.

**Beslispunt:** route 1 bevestigen. Kandidaat-plugins bestaan (o.a. community
"capacitor-native-passkey"-varianten); gezien het beveiligingsgewicht is een eigen dunne
plugin (~200 regels Swift/Kotlin rond de platform-API's) te overwegen — geen supply-chain-
afhankelijkheid op een klein community-pakket in de auth-kern.

## (b) Push: Web Push werkt NIET in de iOS-webview — APNs/FCM erbij

Bevestigd vermoeden: de service worker + `pushManager.subscribe` (`pushClient.ts`) bestaan
niet in een WKWebView. Voor de store-apps is native push nodig:

- **Client:** `@capacitor/push-notifications` — permissie-flow vanuit dezelfde expliciete
  klik als nu, levert een **device token** (APNs op iOS; FCM-token op Android) i.p.v. een
  Web-Push-subscriptie. Notification-tap → deep-link naar `/accordeur?document=<id>`
  (Capacitor App-plugin, zelfde payload-contract als `accordeur-sw.js` — titel/tekst/url is
  herbruikbaar als datacontract).
- **Serverkant (het echte werk):** een tweede subscriptie-soort naast
  `platform.push_subscriptie` (of een `soort`-kolom: `webpush` | `apns` | `fcm`) mét dezelfde
  apparaat-binding en kill-switch-semantiek, plus een verzend-adapter naast pywebpush.
  Simpelste dekking voor beide platforms: **FCM** (één API voor iOS én Android; vergt een
  Firebase-project — gegevensstroom via Google, AVG-notitie nodig) óf **APNs direct**
  (token-based auth met een .p8-sleutel uit het Apple Developer-account; geen Firebase,
  maar dan aparte Android-route via FCM alsnog). Voorstel: APNs direct voor iOS + FCM voor
  Android, achter één `verzending.py`-achtige adapterlaag; beslispunt vanwege de
  AVG-afweging rond Firebase.
- De bestaande daily/bundel-jobs raken alleen de adapterlaag (`verstuur_push_anders_mail`
  kiest per subscriptie-soort) — de idempotentie-/volumerem-logica blijft onaangeraakt.

## (c) Wat Peter moet regelen

> **CORRECTIE 2026-08-17 (Peter, ná het fase-1–5-eindrapport): de store-accounts BESTAAN
> al.** Apple Developer én Google Play Console onder **PDL Powerhouse** zijn actief (de
> Vastly-app draait eronder), inclusief D-U-N-S. Het "kritieke pad bij derden" (D-U-N-S-
> doorloop 1–2 weken, organisatie-verificaties) is daarmee VERVALLEN — wat rest is klikwerk
> onder de bestaande accounts. De punten hieronder zijn hierop bijgewerkt.

1. ~~Apple Developer Program aanvragen~~ **BESTAAT AL** (organisatie-account PDL Powerhouse,
   actief incl. D-U-N-S). Rest-klikwerk: toegang/rol voor deze app + nieuwe app-registratie
   in App Store Connect met bundle-id `nl.aknijenhuis.goedkeuren` onder het bestaande team;
   APNs-sleutel (.p8) aanmaken kan per direct.
2. ~~Google Play Console aanvragen~~ **BESTAAT AL** (PDL Powerhouse, actief). NB de
   "gesloten test ≥ 12 testers / 14 dagen"-eis geldt alleen voor ná nov 2023 aangemaakte
   pérsoonlijke accounts — het PDL-organisatieaccount valt daarbuiten. Een eigen
   interne/gesloten testronde met de accordeurs blijft de bedoeling, maar is geen
   Play-poort meer.
3. **Bundle-id:** `nl.aknijenhuis.goedkeuren` — **DEFINITIEF** (akkoord Peter bij het
   GO-besluit 2026-08-16; staat zo in de schil), te registreren onder het bestaande
   PDL-team. Bundle-id is permanent per app — nooit meer wijzigen.
4. **Signing:** met Xcode "automatically manage signing" onder het PDL-team; voor CI-builds
   later een distributiecertificaat + App Store Connect API-key. Android: een upload-keystore
   (Play App Signing beheert de echte release-key — aanrader).
5. **Klikwerk domein:** `apple-app-site-association` + `assetlinks.json` op de apex laten
   serveren (passkeys, zie (a)) — technisch werk voor ons, DNS/hosting-akkoord voor Peter.

## (d) Overige bevindingen die vóór go/no-go een besluit vragen

- **API-base-URL + refresh-cookie.** De webcode heeft géén configureerbare API-base (alle
  fetches root-relatief) en de refresh loopt via een httpOnly-cookie met `SameSite=Strict`
  en pad `/auth/token/vernieuwen`. In de native webview (origin `capacitor://localhost`)
  breekt beide: relatieve paden wijzen nergens heen en de cookie is daar third-party (WKWebView/
  ITP blokkeert hard). Opties: (1) `server.url` naar het productiedomein — lost álles in
  één keer op maar maakt de app een remote-loading wrapper (App Store-reviewrisico
  "minimal functionality", offline een lege huls) — **afgeraden**; (2) gebundelde assets +
  een kleine webcode-aanpassing: `VITE_API_BASE` in `api/client.ts` én de refresh-flow voor
  native naar een bearer-refresh-token in **secure native storage** (Keychain/Keystore via
  plugin) i.p.v. de cookie — meer werk (auth-serviceniveau: refresh-token als
  body/header accepteren voor apparaat-gebonden sessies), maar een échte app. **Voorstel:
  route 2**; de kill-switch/rotatie-semantiek blijft identiek (het token blijft
  apparaat-gebonden).
- **Startroute.** De schil laadt `index.html` op `/` — dat is de kántoor-route. De app moet
  bij openen naar `/accordeur`: één regel in de webcode (redirect wanneer
  `window.Capacitor` bestaat) of een eigen `index.html` in de schil. Minimale aanpassing,
  hoort bij de bouwfase.
- **Service worker/manifest zijn in de app overbodig** (geen SW in WKWebView) — geen
  conflict: `main.tsx` deregistreert al alles buiten `/accordeur`-scope en de SW faalt daar
  stil; opruimen kan in de bouwfase.
- **Store-review "wrapper-risico":** een app die alleen een website inpakt wordt geweigerd
  (guideline 4.2). Mitigatie is precies wat hierboven al nodig is: gebundelde assets,
  native passkeys, native push, deep-links — dan is het een echte app.
- **Updates:** gebundelde assets betekenen dat elke frontend-wijziging een store-release
  vergt (review: uren tot dagen). De PWA blijft daarom terugval én snelste kanaal;
  live-update-diensten (Appflow e.d.) zijn een latere afweging (kosten/AVG).
- **Node-pinning:** `native/` draait op dezelfde Node 26 als de rest; een `.nvmrc`/engines
  ontbreekt repo-breed (bevinding, geen blokkade).

## Voorstel vervolgstappen (ná go-besluit Peter)

1. ~~Peter: Apple-/Play-accounts~~ VERVALLEN (correctie 2026-08-17: accounts bestaan al
   onder PDL Powerhouse) — rest: app-registraties + signing onder het bestaande team (c).
2. Bouwblok 1: API-base + native refresh-flow (d) — raakt backend-auth, eigen ontwerpnotitie.
3. Bouwblok 2: native passkey-plugin + Associated Domains/assetlinks (a).
4. Bouwblok 3: APNs/FCM-adapter + subscriptie-soort (b) — hergebruikt de berichten-laag.
5. TestFlight/gesloten Play-test met de echte accordeurs; PWA blijft parallel live.

---

## Bouwstatus (ná GO, bijgehouden per fase)

### Fase 1 — snelheidslaag PWA: GEBOUWD + GETEST; BEWEZEN OP TOESTEL (kliktest ronde 1, 2026-08-17)

In de bestaande accordeur-chunk (native schil + web-terugval profiteren automatisch):
optimistisch akkoord/afwijzen via een achtergrond-verzendrij met begrensde retry
(`besluitQueue.ts`; definitief mislukt = zichtbaar terug in de rij), prefetch + prerender
van de eerstvolgende factuur (`pdfCache.ts` + verborgen vooruit-gemonteerd factuurbeeld),
backend-idempotente besluit-herhaling (`accordering/service.py::_herhaald_besluit` — maakt
de retries veilig), dubbeltik-vangnet 300 ms. Details: BESLISSINGEN "NATIVE-APP FASE 1".

### Fase 2 — native passkey-plugin: BEWEZEN OP ECHT TOESTEL (kliktest Peter 2026-08-17)

**Kliktest ronde 1 (Peter, echt iPhone-toestel, 2026-08-17):** passkey-registratie én login
werken met de echte native Face ID-prompt — de AASA/entitlement-keten klopt live (fase 2-kern
bewezen). De akkoord-flow met de hergeboden testfactuur voelt zoals bedoeld (fase 1 op toestel
bevestigd). Koude herstart (app wegvegen → openen → alleen Face ID) staat nog open in de
ronde 2-checklist onderaan. **Bevinding + fix (zelfde dag):** de app-kop liep onder de
iOS-statusbalk door — de viewport-meta miste `viewport-fit=cover`, waardoor
`env(safe-area-inset-*)` in de edge-to-edge Capacitor-webview overal 0 was (de PWA schuift
zelf onder de statusbalk vandaan, dáár viel het niet op). Structureel gefikst: viewport-meta
(`frontend/index.html`, PWA/desktop onveranderd — de CSS rekende al overal met env()),
sweep over álle accordeur-schermen (`.acc-content`-onderrand, `.acc-vol`-schermen incl.
inline-override VoorwaardenScherm, zijranden landschap), statusbalk-tekst wit
(Info.plist `UIStatusBarStyleLightContent` — spiegel van de PWA-`theme_color`) mét donkere
statusbalk-cap op de themavolgende vol-schermen (`.acc-vol::before`), zodat de klok in het
lichte thema leesbaar blijft. Actiebalk/sheets onderaan: de bestaande
`env(safe-area-inset-bottom)`-paddings zijn door de meta-fix actief geworden — home-indicator
gedekt. Bundel herbouwd + `cap sync ios` gedraaid; zichtcontrole = ronde 2.

Gebouwd (route 1 uit dit rapport, eigen dunne plugin — geen community-pakket in de auth-kern):

- **Webcode-seam** (lokaal getest, 8 tests): `frontend/src/accordeur/nativePasskey.ts`
  detecteert de plugin via de Capacitor-bridge-globals (géén @capacitor-dependency in de
  webcode; fail-closed — half plugin-oppervlak of niet-native = webpad);
  `webauthnClient.ts` routeert `registreerPasskey`/`ondertekenAssertie`/`webauthnBeschikbaar`
  door de plugin wanneer die er is. Options-JSON erin, credential-JSON eruit — backend en
  schermen (activeren, login, ontgrendel) merken het verschil niet; de auth-cadans blijft
  exact blok 2.
- **iOS**: `native/ios/App/App/NatievePasskeyPlugin.swift` (ASAuthorizationController;
  registratie + assertie, base64url-vertaling, annuleren = 'geannuleerd', iOS 16-poort,
  excludeCredentials vanaf 17.4), registratie via `MainViewController.swift`
  (capacitorDidLoad → registerPluginInstance; Main.storyboard wijst ernaar), Associated
  Domains-entitlement `App.entitlements` (webcredentials: apex) gewired in het Xcode-project.
- **Android**: `NatievePasskeyPlugin.java` (androidx.credentials Credential Manager —
  registrationResponseJson/authenticationResponseJson zijn al de juiste WebAuthn-vorm),
  registratie in MainActivity, dependencies in app/build.gradle.
- **Backend** (lokaal getest, 4 tests): `app/auth/wellknown.py` serveert
  `/.well-known/apple-app-site-association` + `/.well-known/assetlinks.json` — fail-closed
  404 zolang `apple_team_id` resp. `android_cert_sha256_vingerafdrukken` leeg zijn
  (config.py). `webauthn_origins` (lijst) hoeft niet verbouwd: iOS stuurt de apex-origin
  (staat er in productie al in); Android vergt t.z.t. `android:apk-key-hash:<b64url-sha256>`
  erbij (deploy-config, kan pas als de signing-key bestaat).

**iOS-COMPILE-RONDE UITGEVOERD (2026-08-17, Xcode 26.6 — BESLISSINGEN "NATIVE-APP
iOS-COMPILE-RONDE"):** simulator-build groen op de eerste poging (nul Swift-fouten),
runtime-smoke OK. **Bug gevonden + gefikst:** `SceneDelegate` zette een kale
`CAPBridgeViewController()` als root waardoor `MainViewController.capacitorDidLoad` — en
dus de registratie van NatievePasskey/VeiligeOpslag — nooit draaide (met een
webview-probe bewezen: plugins ontbraken in `Capacitor.Plugins`; beide seams zouden op
het toestel stil zijn teruggevallen op het kapotte webpad). Ná de fix bewezen: beide
plugins in de bridge én live `To Native → VeiligeOpslag haal` bij de opstart-refresh.
Kliktest-prep-correcties in dezelfde ronde: apex-origin in `WEBAUTHN_ORIGINS` (de claim
hierboven "staat er in productie al in" was drift — deploy.yml had alleen het
app-subdomein), `capacitor://localhost` in `CORS_ALLOWED_ORIGINS` (stond op `[]`),
`VITE_API_BASE` definitief het app-subdomein. Java/Android-SDK ontbreken op deze Mac —
Android-compile in de eigen ronde.

**Kliktest-blok fase 2 — AFGEROND (kliktest rondes 1+2, 2026-08-17; alleen het Android-spoor
rest):**
1. ~~Xcode installeren + eerste compile-ronde~~ UITGEVOERD 2026-08-17 (zie hierboven).
2. ~~Signing onder het PDL-team + Associated Domains~~ UITGEVOERD (commit 2732d12).
3. ~~apple_team_id in productieconfig + statische AASA op de WordPress-apex~~ UITGEVOERD
   (commit 7bd9f57 + kliktest-bewijs: de native prompt kwam, dus iOS heeft de AASA
   geaccepteerd). Voor Android t.z.t. idem `assetlinks.json`.
4. ~~Activeringsflow: passkey-registratie + login in de native Face ID-prompt~~ BEWEZEN
   (kliktest ronde 1). ~~Koude herstart → alleen ontgrendel-assertion~~ BEWEZEN in ronde 2
   (2026-08-17): automatische Face ID-ontgrendeling bij koude start, geen wachtwoord —
   tegelijk het fase 4-Keychain-bewijs. Ook de bestaande PWA-passkey van hetzelfde account
   werkt in de native app (zelfde rp_id — 0022-lijn live bevestigd, ronde 2).
5. Android idem zodra upload-keystore bestaat (assetlinks + apk-key-hash-origin eerst;
   Play Console-account bestaat al) — **draaiboek klaar (2026-08-28): `native/PLAY_DRAAIBOEK.md`**
   (§2 keystore-script, §5 assetlinks mét BEIDE certificaten — Google's app-signing-key én de
   upload-key — + twee `android:apk-key-hash:`-origins, §8 kliktest).

### Fase 3 — native push: BEWEZEN OP TOESTEL (kliktest ronde 2, 2026-08-17)

Route conform (b) hierboven: **APNs direct voor iOS + FCM voor Android, achter één
adapterlaag** — de AVG-afweging valt daarmee zo klein mogelijk uit (Firebase alleen voor
Android-bezorging; payload uitsluitend aantal + deep-link, nooit financiële details).

- **Serverzijde (lokaal getest, migratie 0055 volledig afgerond incl. dev-upgrade + dump):**
  `platform.push_subscriptie` heeft een `soort` (webpush | apns | fcm; native: endpoint =
  device-token, geen RFC 8291-sleutels — DB-check dwingt de combinatie af). Adapters
  `app/berichten/apns.py` (HTTP/2 via httpx[http2], ES256-JWT met de .p8, ~50 min hergebruikt;
  BadDeviceToken/Unregistered → vervallen) en `fcm.py` (HTTP v1, service-account via
  google-auth; UNREGISTERED → vervallen); dispatch per soort in `push.py` — `verzending.py`
  (dagelijkse 09:00, bundelmelding, herinner-knop) merkt níéts: zelfde
  push-anders-mail-keuze, native telt gewoon mee. Kill-switch bewezen over native rijen
  (zelfde apparaat-binding; test). Registratie: `POST /notificaties/push/subscripties/native`
  {soort, token} — zelfde voorwaarden-/apparaat-poorten en audit als Web Push; fail-closed
  409 zolang de soort niet geconfigureerd is (geen tokens verzamelen die nooit bediend worden).
- **Webcode (lokaal getest):** `nativePush.ts` (bridge-globals, zelfde patroon als
  nativePasskey) + native pad in `pushClient.ts` — permissie alleen vanuit de expliciete
  klik, register()-token mét timeout (nooit eeuwig "Bezig…"), tap opent uitsluitend
  /accordeur-deep-links (auth-cadans blijft de poort), uitzetten trekt het token server-side
  in. Schil: `@capacitor/push-notifications` 8.1.2 geïnstalleerd + `cap sync` geverifieerd
  (iOS SPM + Android gradle), AppDelegate-token-forwarding + `aps-environment`-entitlement.
- **Config (deploy, pas bij activatie):** APNs `APNS_KEY_P8` (Secret Manager) +
  `APNS_KEY_ID` (+ `APPLE_TEAM_ID` uit fase 2, `APNS_SANDBOX` voor TestFlight); FCM —
  **HERZIEN 2026-08-28 (Android-bouwronde):** Firebase is aan HETZELFDE GCP-project
  toegevoegd, dus de verzendkant gebruikt Application Default Credentials van de Cloud
  Run-identiteit (`run-backend@`/`run-jobs@`, IAM `roles/firebasecloudmessaging.admin`) mét
  alleen `FCM_PROJECT_ID` als config — het geplande `FCM_SERVICE_ACCOUNT_JSON`-secret is
  vervallen als standaardroute (blijft als terugval in `fcm.py` voor omgevingen zonder ADC).
  Uitgevoerd via `scripts/gcp/fcm_afronden.sh`; live geverifieerd zonder toestel.
- **Kliktest-blok fase 3 — KLAARGEZET (2026-08-17):** het volledige pad is gebundeld in
  `scripts/gcp/apns_afronden.sh` (stdin-patroon, idempotent — zelfde grondhouding als
  notificaties_afronden.sh): .p8-aanmaakinstructies (Developer-portaal → Keys, níét App
  Store Connect), secret-slots APNS_KEY_P8 + APNS_KEY_ID + accessors (jobs én backend —
  registratie-endpoint + handmatige herinner-knop draaien in de service), directe
  service-/job-updates (spiegel van de nieuwe deploy.yml-stappen), verificatiepoort met
  één handmatige run van rlz-accordeur-herinneringen. ⚠️ `APNS_SANDBOX=true` zolang de
  geïnstalleerde build dev-signed is (aps-environment 'development' = sandbox-APNs);
  TestFlight/App Store = false — staat als comment in deploy.yml en in
  STORE_GEREEDHEID. **Bewijs op het toestel GELEVERD (ronde 2, 2026-08-17):** registratie
  via de meldingen-kaart geslaagd, APNs-banner binnen op het toestel, tap = deep-link naar
  het document ná ontgrendeling. **Android-kant VOORBEREID (2026-08-28):**
  `google-services.json` in `native/android/app/` (gecommit, Analytics UIT), google-services-
  plugin hard toegepast, `POST_NOTIFICATIONS` + monochroom statusbalk-icoon, FCM-verzendkant
  live (ADC) — ontvangstbewijs op een Android-toestel = `native/PLAY_DRAAIBOEK.md` §8
  (vergt eerst JDK/SDK + keystore + Play-interne-test; Java/Android-SDK ontbreken nog op de Mac).

### Fase 4 — gebundelde assets + bearer-refresh Keychain/Keystore: BEWEZEN OP TOESTEL (kliktest ronde 2, 2026-08-17)

Route 2 uit (d): een échte app met gebundelde assets — geen remote-wrapper.

- **Backend (getest, web-contract bewaakt):** de vernieuwen-familie accepteert het
  refresh-token óók als `X-Refresh-Token`-header; een client die zich expliciet als native
  aandient (`X-Native-Client: 1` of een header-token) krijgt het token-paar in de body en
  GÉÉN cookie (één kanaal per client; `_lever_token_paar`/`_lees_refresh_token` in
  `app/auth/router.py`). Rotatie/grace/kill-switch: exact dezelfde service-laag. Het webpad
  is byte-voor-byte ongewijzigd: zonder native-aankondiging bestaat `refresh_token` niet
  eens in de response-body (serializer-guard + tests) — een web-XSS kan het token dus nog
  steeds niet lezen (cookie blijft httpOnly).
- **Webcode (getest):** `VITE_API_BASE` in `api/client.ts` (native bundel →
  `frontend/.env.native`, build via `npm run bouw-web` = `--mode native`; web/dev
  ongewijzigd root-relatief); `api/nativeSessie.ts` = brug naar de eigen
  VeiligeOpslag-plugin; de refresh-flow stuurt in de schil het Keychain-token als header en
  bewaart het geroteerde token uit de body; AuthContext bewaart/wist het token bij
  inloggen/uitloggen; startroute: native opent op /accordeur (main.tsx).
- **Native (geschreven, compileert pas met Xcode/Android-SDK — zelfde eerlijke status als
  fase 2):** `VeiligeOpslagPlugin.swift` (Keychain, AfterFirstUnlockThisDeviceOnly — nooit
  in backups) en `VeiligeOpslagPlugin.java` (EncryptedSharedPreferences, Keystore-gedekt);
  eigen dunne plugins, geen community-pakket in de auth-kern.
- **Kliktest-blok fase 4 — AFGEROND (ronde 2, 2026-08-17):** volledige cyclus op het
  toestel bewezen — koude herstart → automatische Face ID-ontgrendeling zónder nieuwe
  login (Keychain-refresh bewezen); kill-switch op Instellingen → app viel per direct terug
  naar login, passkey onbruikbaar, apparatenlijst leeg. Vooraf:
  ~~VITE_API_BASE-domein bevestigen~~ BESLIST 2026-08-17:
  `https://app.administratiekantoornijenhuis.nl` (de apex draait de WordPress-site en
  routeert niet naar Cloud Run — zie de fase-2-compile-ronde-notitie hierboven).

### Fase 5 — store-gereedheid: VOORBEREID (2026-08-17); kliktest-blokken GROEN (ronde 2) — iOS-publicatiepad open

De store-accounts bestaan al (correctie 2026-08-17, zie (c)) — geen kritiek pad bij derden;
alles tot aan de kliktest-blokken staat klaar:

- **Iconen + splash** voor beide schillen, herhaalbaar gegenereerd uit de canonieke
  accordeur-icoon-SVG via `native/scripts/genereer_assets.sh` (qlmanage, geen extra
  dependencies): App Store-icoon 1024 full-bleed (geen transparante hoeken), iOS-splash
  2732 (donker, icoon gecentreerd — zelfde kleur als de webview-achtergrond, geen
  witflits), Android launcher/round/adaptive-foreground per dichtheid +
  ic_launcher_background #0e1514 + alle splash-drawables.
- **`native/STORE_GEREEDHEID.md` (canoniek voor deze fase):** privacy nutrition labels
  (App Store) + Data safety (Play) voor-ingevuld, reviewnotities (demo-accordeur op de
  TEST-administratie, pushpermissie-uitleg, 4.2-onderbouwing), publicatie-checklist in
  volgorde (TestFlight; Play interne/gesloten test — de 12-testers-eis geldt het
  PDL-organisatieaccount niet, zie (c); assetlinks + apk-key-hash-origin ná de keystore),
  versiebeleid.
- Open taakjes die bij de checklist horen: privacyverklaring als publieke URL,
  demo-account voor review, screenshots — allemaal ná de kliktest-blokken.

### Kliktest-checklist ronde 2 — UITGEVOERD, VOLLEDIG GROEN (kliktest Peter, echt toestel, 2026-08-17)

Vooraf, in deze volgorde:
1. `scripts/gcp/apns_afronden.sh` draaien (owner-account) — het script dicteert eerst de
   .p8-aanmaakstappen (Developer-portaal → Keys) en zet daarna slots, config en de
   bewijs-push klaar. Stap 4 (bewijs-push) kan pas ná punt 3 hieronder.
2. Nieuwe build op het toestel: Xcode → Run (de bundel met de safe-area-fix + Info.plist-
   statusbalkwijziging is al ge-`cap sync`'d; even Product → Clean hoeft niet).
3. Open accordering aanwezig? Zo niet: `backend/scripts/cloud_seed_accordering.py`
   (docstring = draaiboek) — de meldingen-flow én de herinnering-job hebben ≥1 open
   accordering nodig.

Aftiklijst op het toestel (alle zes ✅, 2026-08-17):
- [x] **Safe-area (de ronde 1-bevinding):** kop start ónder de klok/notch (statusbalktekst
      wit op de donkere kop); actiebalk Akkoord/Afwijzen vrij van de home-indicator; afwijs-
      en staande-goedkeuring-sheets idem; licht thema: klok leesbaar op de donkere cap —
      zichtcontrole geslaagd, de ronde 1-fix is daarmee afgesloten.
- [x] **Koude herstart (fase 4-bewijs):** app wegvegen → opnieuw openen → automatische
      Face ID-ontgrendeling, GEEN wachtwoord — Keychain-refresh-token bewezen.
- [x] **Meldingen aan** via de meldingen-kaart → iOS-toestemmingsprompt → registratie
      geslaagd (apns_afronden.sh-config live).
- [x] **Bewijs-push (fase 3):** APNs-banner binnen op het toestel; tap opent de app op het
      document (deep-link, ná ontgrendeling — goedkeuren-vanuit-de-melding bestaat bewust
      niet).
- [x] **Kill-switch (fase 3+4-bewijs):** apparaat ingetrokken op Instellingen → app viel
      per direct terug naar login, passkey onbruikbaar, apparatenlijst leeg — bedoeld
      gedrag bevestigd (push-stilte volgt uit dezelfde apparaat-gebonden intrekking;
      server-side met test bewezen, fase 3).
- [x] **Bestaande PWA-passkey** van hetzelfde account werkt óók in de native app (zelfde
      rp_id — 0022-lijn live bevestigd).

**Uitkomst vastgelegd in BESLISSINGEN "NATIVE KLIKTEST RONDE 2"; fases 1–4 staan hierboven
op bewezen-op-toestel. Volgende halte (fase 5-publicatiepad):**
1. **TestFlight** — mét als EXPLICIETE stap `APNS_SANDBOX=false` (TestFlight/App
   Store-builds zijn production-signed; de dev-build draaide sandbox — zie de
   deploy.yml-comment + STORE_GEREEDHEID), plus de open taakjes uit fase 5
   (privacyverklaring-URL, review-demo-account, screenshots).
2. **Android/Firebase-ronde** — Android Studio/SDK-compile, Firebase-project +
   google-services.json + FCM_SERVICE_ACCOUNT_JSON, Play-keystore → assetlinks +
   apk-key-hash-origin in WEBAUTHN_ORIGINS.
