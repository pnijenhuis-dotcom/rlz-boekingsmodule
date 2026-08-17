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
(appId-vóórstel `nl.aknijenhuis.goedkeuren`, appName "RLZ Goedkeuren",
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

1. **Apple Developer Program** onder de juiste entiteit (**PDL**): organisatie-account
   (€ 99/jr) vergt een **D-U-N-S-nummer** van PDL + een Apple-ID op een PDL-adres; doorloop
   duurt soms 1–2 weken (D-U-N-S-verificatie) — vroeg starten. Nodig vóór: signing voor
   echte toestellen/TestFlight, Associated Domains, APNs-sleutel (.p8).
2. **Google Play Console** onder PDL: eenmalig $ 25, organisatie-verificatie (KvK-gegevens);
   sinds 2024 vereist Play voor nieuwe developer-accounts een **gesloten test met ≥ 12
   testers gedurende 14 dagen** vóór productie-release — de accordeurs zelf kunnen die
   testgroep zijn, maar plan het in.
3. **Bundle-id-voorstel:** `nl.aknijenhuis.goedkeuren` (staat zo in de schil; consistent met
   ak-nijenhuis.nl en kort). Alternatief `nl.administratiekantoornijenhuis.goedkeuren` als de
   store-vermelding strikt de apex moet volgen. Eén keuze, daarna nooit meer wijzigen
   (bundle-id is permanent per app). **Beslispunt.**
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

1. Peter: Apple-/Play-accounts (c1/c2, langste doorlooptijd eerst) + bundle-id-keuze.
2. Bouwblok 1: API-base + native refresh-flow (d) — raakt backend-auth, eigen ontwerpnotitie.
3. Bouwblok 2: native passkey-plugin + Associated Domains/assetlinks (a).
4. Bouwblok 3: APNs/FCM-adapter + subscriptie-soort (b) — hergebruikt de berichten-laag.
5. TestFlight/gesloten Play-test met de echte accordeurs; PWA blijft parallel live.

---

## Bouwstatus (ná GO, bijgehouden per fase)

### Fase 1 — snelheidslaag PWA: GEBOUWD + GETEST (2026-08-17)

In de bestaande accordeur-chunk (native schil + web-terugval profiteren automatisch):
optimistisch akkoord/afwijzen via een achtergrond-verzendrij met begrensde retry
(`besluitQueue.ts`; definitief mislukt = zichtbaar terug in de rij), prefetch + prerender
van de eerstvolgende factuur (`pdfCache.ts` + verborgen vooruit-gemonteerd factuurbeeld),
backend-idempotente besluit-herhaling (`accordering/service.py::_herhaald_besluit` — maakt
de retries veilig), dubbeltik-vangnet 300 ms. Details: BESLISSINGEN "NATIVE-APP FASE 1".

### Fase 2 — native passkey-plugin: CODE STAAT (2026-08-17), bewijs = kliktest echt toestel

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

**NIET lokaal verifieerbaar (eerlijk gemeld):** Swift/Java compileren hier niet (alleen
Command Line Tools, geen Android-SDK). Het bewijs van fase 2 — activerings- én
ontgrendel-flow op een echt toestel — is het kliktest-blok hieronder.

**Kliktest-blok fase 2 (Peter + Claude, kan pas als het Apple Developer-account er is):**
1. Xcode installeren (App Store, ~12 GB) → `cd native && npm install && npm run bouw-web &&
   npx cap sync && npx cap open ios`; eerste compile-ronde is verwacht werk (Swift is
   ongecompileerd geschreven).
2. Signing onder het PDL-team + capability Associated Domains (het entitlement staat al in
   het project — met een gratis personal team faalt device-signing hierop, dus deze test
   wacht écht op het account).
3. Backend-productieconfig: `apple_team_id` zetten → AASA live op de apex controleren
   (`curl https://administratiekantoornijenhuis.nl/.well-known/apple-app-site-association`).
   NB: de apex moet naar onze backend routeren vóór iOS de koppeling kan valideren.
4. Op het toestel: activeringsflow (wachtwoord → passkey-registratie in de native prompt →
   voorwaarden) én koude herstart → ontgrendel-assertion; bestaande PWA-passkey van
   hetzelfde account moet het in de app ook doen (zelfde rp_id).
5. Android idem zodra Play Console + upload-keystore bestaan (assetlinks +
   apk-key-hash-origin eerst).

### Fase 3 (APNs/FCM), fase 4 (API-base + Keychain-refresh), fase 5 (store-gereedheid)

Nog niet gestart — volgorde conform de GO-opdracht; fase 3/4 hebben elk een eigen
ontwerpnotitie-moment (subscriptie-soort serverzijde resp. auth-serviceniveau).
