# Store-gereedheid "Nijenhuis Boekingsmodule" (fase 5)

> **Hernoemd 2026-08-19 (besluit Peter):** App Store-/productnaam = **"Nijenhuis
> Boekingsmodule"** (was "RLZ Goedkeuren"), ondertitel blijft "Facturen goedkeuren";
> beginscherm-weergavenaam = kort **"Nijenhuis"** (CFBundleDisplayName in Info.plist +
> `app_name` in het Android-manifest, i.v.m. afkapping onder het icoon; PWA-manifest:
> name "Nijenhuis Boekingsmodule", short_name "Nijenhuis"). Bundle-id blijft
> `nl.aknijenhuis.goedkeuren` — wijzigen zou signing/AASA raken. **De in-app wordmark is
> per 2026-08-19 (besluit Peter) gelijkgetrokken naar "Nijenhuis Boekingsmodule"** (alle
> schermen + mockup-norm `accordeur.html`); de store-screenshots zijn dezelfde dag
> hergenereerd met de nieuwe kop. Zie BESLISSINGEN "IN-APP WORDMARK".

**Status 2026-08-17:** alles tot aan de kliktest-blokken is klaar (iconen/splash uit één
SVG-bron via `scripts/genereer_assets.sh`, naamgeving, dit dossier). **Iconen + splash
DEFINITIEF (2026-08-18, besluit Peter):** beeldmerk = `mockup/app-icoon-n.svg` — de N van
Reisburo Nijenhuis (familielogo, exact gereconstrueerd; geometrie nooit aanpassen), witte
contour op het wordmark-verloop, mint-driehoeken. Alle iOS/Android/PWA-iconen en splashes
zijn eruit hergenereerd (splash = verloop schermvullend + monogram gecentreerd; renderer
sinds 18-08 NSImage/CoreSVG i.p.v. qlmanage — dat plette transparantie, waardoor de
Android-adaptive-foreground een wit vlak was) en de dev-build staat op Peters iPhone.
Zie BESLISSINGEN "APP-BEELDMERK". **De store-accounts
BESTAAN al (correctie Peter 2026-08-17): Apple Developer én Play Console onder PDL
Powerhouse zijn actief (Vastly-app draait eronder), incl. D-U-N-S — geen kritiek pad bij
derden.** Publicatie wacht alleen nog op de kliktest-blokken (verkenning/17) + de
app-registraties onder het bestaande PDL-team. Bundle-id definitief:
`nl.aknijenhuis.goedkeuren` (akkoord Peter bij het GO-besluit 16-08 — permanent, nooit meer
wijzigen; registreren onder het bestaande team).

**Klik-voor-klik-recept voor de TestFlight-ronde (registratie ASC, archive/upload,
APNS_SANDBOX-omslag, demo-account): `native/TESTFLIGHT_DRAAIBOEK.md` (2026-08-18).**

## 1. Wat de app is (voor reviewnotities en listing)

Interne zakelijke app voor klanten van Administratiekantoor Nijenhuis: accordeurs keuren
inkoopfacturen van hun eigen administratie goed of wijzen ze af (met verplichte reden).
Alleen op uitnodiging — er is géén open registratie. Auth: e-mailuitnodiging → wachtwoord →
passkey per apparaat (Face ID/Touch ID); daarna ontgrendelt de app per opening met een
passkey-assertion.

## 2. App Store — privacy nutrition labels (in te vullen in App Store Connect)

| Categorie | Verzameld? | Gekoppeld aan identiteit | Tracking |
|---|---|---|---|
| Contact Info → Email Address | Ja (accountbasis: login/uitnodiging/mail-terugval) | Ja | Nee |
| Contact Info → Name | Ja (gebruikersnaam in het platform) | Ja | Nee |
| Financial Info → Other Financial Info | Ja (facturen van de eigen administratie worden getoond/beoordeeld; verwerking op onze servers) | Ja | Nee |
| Identifiers → User ID | Ja (platform-gebruikers-id; apparaat-gebonden sessie/push-token) | Ja | Nee |
| Usage Data / Diagnostics | Nee (geen analytics/tracking-SDK's) | — | — |

- **Tracking (ATT):** geen — geen advertenties, geen tracking over apps/sites heen, geen
  third-party-SDK's behalve Capacitor zelf. ATT-prompt niet nodig.
- **Verwerking:** EU (Google Cloud europe-west4, CMEK — platformbesluit 0021). Push via APNs
  (Apple) en, op Android, FCM (Google) — payload bevat uitsluitend een aantal + deep-link,
  nooit factuur- of financiële gegevens (dataminimalisatie, zie app/berichten/).
- **Account-verwijdering (App Store-eis bij accounts):** accounts bestaan alleen op
  uitnodiging van het kantoor; verwijdering loopt via het kantoor (AVG-proces:
  pseudonimiseren ná relatie-einde + 7 jaar bewaarplicht — koppelcontract/platformafspraak).
  In de reviewnotities benoemen + contactadres geven; raakvlak platformbesluit 0010.

## 3. Google Play — Data safety-formulier

Zelfde inhoud als §2 in Play-vorm: verzamelt e-mail, naam, gebruikers-id, financiële info
(facturen); alles versleuteld in transit (https); verwijdering via het kantoor; geen data
gedeeld met derden (FCM = verwerker voor bezorging); geen advertenties.

## 4. Reviewnotities (Apple én Play — demo-toegang)

- **Demo-account: strategie + seedscript KLAAR (2026-08-18, TESTFLIGHT_DRAAIBOEK.md §0):**
  gewoon accordeur-account `p.nijenhuis+applereview@kempengroep.nl` op SEED-PASSKEYTEST via
  `backend/scripts/cloud_seed_review_demo.py` — normale wachtwoord→passkey-flow op het
  reviewtoestel (passkey-laag NIET verzwakt, geen bypass), uitsluitend FICTIEVE
  demo-facturen (eigen PDF's), en twee accorderingslagen (review → passkeytest) zodat het
  reviewer-akkoord nooit de boekmotor raakt. Engelse reviewnotities-tekst staat kant-en-
  klaar in het draaiboek. Peter: script draaien + activatielink doorlopen (wachtwoord kiezen).
  Bekend risico: passkeys falen soms op Apple-reviewtoestellen (iCloud-sleutelhanger) —
  in de notities benoemd; bij afwijzing = reply/appeal, nooit een bypass bouwen.
- Inloggegevens + korte flow-uitleg in het reviewnotitieveld; expliciet vermelden dat de
  passkey-stap ná de wachtwoordstap komt en dat de reviewer bij "Voorwaarden" moet
  accepteren.
- Uitleggen waarom pushpermissie gevraagd wordt (dagelijkse herinnering + nieuwe facturen,
  alleen bij openstaand werk) en dat goedkeuren nooit vanuit de melding zelf kan.
- Guideline 4.2 (minimal functionality): benoemen dat de app gebundelde assets, native
  passkeys, native push en deep-links gebruikt — geen remote-loading wrapper.

**Voortgang App Store Connect (klikwerk Peter, 2026-08-21):** app-registratie + App
Information (subtitle "Facturen goedkeuren", categorie Business, geen third-party content),
Age Rating (nieuwe 7-staps-vragenlijst op de App Information-pagina, alles None/No →
**4+**, Age Categories "Not Applicable"), App Privacy (privacy-URL gezet, labels exact
conform §2 — vier datatypes, alle App Functionality + linked to identity, geen tracking —
gepubliceerd onder "Data Linked to You") en Pricing (€ 0,00, basisland NL, Availability
alleen Nederland) zijn ÁF. Aandachtspunt: **Apple Silicon Mac-beschikbaarheid staat op de
ASC-default AAN** ("Make this app available", Automatic macOS 11.0) — advies: uitzetten
(alleen iPhone getest; passkey-/viewport-gedrag op macOS onbekend), besluit Peter open.
Nog open in ASC: versiepagina 1.0 (screenshots/description/keywords/support-URL), App
Review Information (vergt het demo-wachtwoord uit draaiboek §0 — pas nodig vóór
béta-/app-review, niet voor interne TestFlight), build koppelen ná de eerste upload.

## 5. Checklist tot publicatie (volgorde)

1. **Peter:** ~~accounts aanmaken~~ **VERVALLEN** (bestaan al onder PDL Powerhouse, actief —
   correctie 2026-08-17). Rest: nieuwe app-registratie in App Store Connect (bundle-id
   `nl.aknijenhuis.goedkeuren` onder het bestaande team) + nieuwe app in Play Console.
2. Xcode installeren → fase 2/3/4-kliktest-blokken (verkenning/17): compile, passkeys op
   toestel, push-ontvangst, koude-herstart-ontgrendeling. Dáár horen ook:
   `apple_team_id`/AASA live, APNs .p8 + secrets, VITE_API_BASE-domein bevestigen.
3. ⚠️ **Bij de eerste TestFlight-build: `APNS_SANDBOX` op `false`** (deploy.yml, twee
   plekken — jobs + service). De kliktest-configuratie staat op `true` omdat een dev-signed
   Xcode-build (`aps-environment: development`) uitsluitend met sandbox-APNs praat;
   TestFlight/App Store-builds krijgen automatisch `production` en hun tokens werken alléén
   tegen productie-APNs. Vergeten = pushes falen met BadDeviceToken (fail-zichtbaar in de
   job-logs, nooit stil).
4. `npm run bouw-web && npx cap sync` → archive/upload naar **TestFlight** (interne testers:
   Peter + kantoor); Android: upload-keystore aanmaken (Play App Signing aan), **interne/
   gesloten test** (de ≥ 12 testers/14 dagen-eis geldt alleen persoonlijke accounts — het
   PDL-organisatieaccount valt daarbuiten; de accordeurs blijven de testgroep) +
   `assetlinks.json` met de definitieve signing-hash + `android:apk-key-hash:`-origin in
   `webauthn_origins`.
5. Store-listing (NL): naam "Nijenhuis Boekingsmodule" (hernoemd 19-08), ondertitel "Facturen goedkeuren" (ASC-limiet
   30 tekens). **Iconen: DEFINITIEF (2026-08-18)** — N-beeldmerk uit `mockup/app-icoon-n.svg`
   (zie status bovenaan). **Screenshots: KLAAR — hergenereerd 2026-08-19 mét de nieuwe
   in-app wordmark** — `store-assets/screenshots/` (6.9" + 6.3", donker thema: wachtrij,
   factuurbeeld, ontgrendelscherm + meldingen-kaart; gemaakt in de simulator tegen een
   lokale backend met uitsluitend fictieve demo-facturen — zelfde opzet als 18-08).
   **Aangevuld 2026-08-21 met de 6.5"-maat** (`iphone-6p5-*`, 1284×2778 — iPhone
   11 Pro Max-klasse, de derde maat die ASC op de versiepagina kan vragen): wachtrij,
   factuurbeeld, ontgrendelscherm (drie schermen, conform de 6.9"-set; zelfde
   simulator-opzet met uitsluitend fictieve demo-facturen). **Privacy-URL: GEBOUWD (2026-08-18)** —
   `https://app.administratiekantoornijenhuis.nl/accordeur/privacy`
   (`backend/app/auth/privacy_pagina.py`, wellknown-patroon: rendert de akkoordtekst uit
   `app/auth/voorwaarden.py` — één bron van waarheid, versie zichtbaar; live ná de
   eerstvolgende deploy). NB de tekst draagt nog de versie "2026-08-11-concept-v1"
   (jurist-toets open) en de in-app-tekst verwijst nog zonder link naar "de
   privacyverklaring" — de URL erin opnemen = tekstwijziging = versie-ophoging = iedereen
   opnieuw akkoord (bewust besluit voor later, zie BESLISSINGEN).
6. Ná review-akkoord: gefaseerde uitrol; PWA blijft parallel live als terugval (besluit
   14-08) — accordeurs migreren op eigen tempo, passkeys blijven geldig (zelfde rp_id).

## 6. Versiebeleid

MARKETING_VERSION/versionName starten op 1.0; elke webcode-wijziging in de bundel vergt een
store-release (review: uren–dagen) — de PWA blijft daarom het snelste kanaal; een
live-update-dienst (Appflow e.d.) is een latere, aparte afweging (kosten/AVG).

## 7. Xcode Cloud (blok D 2026-08-22) — automatische TestFlight-builds vanaf `main`

**Wat er in de repo staat (gebouwd, geen klikwerk):**

- `native/ios/App/ci_scripts/ci_post_clone.sh` — draait bij élke cloud-build automatisch:
  Node-bootstrap (Homebrew, major uit `.nvmrc` in de repo-root), `npm ci` in `frontend/` én
  `native/` (dat laatste is hard nodig vóór de SPM-resolve: `CapApp-SPM/Package.swift` heeft
  een lokale path-dependency op `node_modules/@capacitor/push-notifications`),
  `npm run bouw-web` (frontend `--mode native`, `VITE_API_BASE` uit `frontend/.env.native`)
  en `npx cap sync ios` — **elke build bundelt dus de actuele web-assets**, er hoeft nooit
  meer een dist ingecheckt of handmatig gesynct te worden.
- **Buildnummer-automatisering:** het script zet `CURRENT_PROJECT_VERSION` (beide plekken in
  het pbxproj) op Xcode Clouds `CI_BUILD_NUMBER`; `Info.plist` leest `CFBundleVersion` daar
  al uit. `MARKETING_VERSION` blijft handmatig (§6). NB het Xcode Cloud-buildnummer telt
  per workflow vanaf 1 — zet bij het aanmaken van de workflow de teller éénmalig hoger dan
  de laatst geüploade build (nu Build 2 → "Start build number" ≥ 3, zie klikstap 5).
- **Gedeeld scheme:** `App.xcodeproj/xcshareddata/xcschemes/App.xcscheme` is aangemaakt en
  ingecheckt — zonder gedeeld scheme kan Xcode Cloud niets bouwen (het scheme leefde tot
  22-08 alleen in xcuserdata).
- NB: dit vervangt het handmatige archive/upload-recept in `TESTFLIGHT_DRAAIBOEK.md` §3 —
  dat blijft de terugval als de cloud-build ooit stilligt. **Vastly is hier bewust géén
  voorbeeld:** die app bouwt via Expo/EAS (eas.json, `autoIncrement`), niet via Xcode Cloud;
  dit is de eerste Xcode Cloud-opzet binnen het platform.

**Eenmalige klikstappen Peter (workflow koppelen — ~10 min, daarna rolt elke `main`-push):**

1. Open het project op de Mac: `cd native && npx cap open ios` (of open
   `native/ios/App/App.xcodeproj`), log in Xcode in met het PDL Powerhouse-account
   (team VRQP26CX43).
2. Xcode-menu **Integrate → Create Workflow…** (of Report navigator → tab **Cloud** →
   "Get started"). Kies de app **App** (product "Nijenhuis Boekingsmodule").
3. **Grant Access** voor de GitHub-repo `pnijenhuis-dotcom/rlz-boekingsmodule` (Xcode stuurt
   je door naar GitHub → installeer de "Xcode Cloud"-app op precies die repo). Dit hoeft
   maar één keer per repo.
4. Workflow-instellingen (de default "Default" workflow aanpassen):
   - **Start Conditions:** Branch Changes → branch `main` (default).
   - **Environment:** nieuwste macOS/Xcode (defaults volstaan; "Clean" hoeft niet aan —
     ci_post_clone bouwt de webbundel toch elke keer vers).
   - **Actions:** één **Archive**-actie, platform iOS, scheme **App**, deployment
     preparation **TestFlight (Internal Testing Only)**.
   - **Post-Actions:** **TestFlight Internal Testing** → kies/maak de interne groep
     (Peter + kantoor — dezelfde groep als Build 1/2).
5. Onder **Settings → Build Number** van de workflow: zet **Start build number** op een
   waarde boven de laatst geüploade build (Build 2 staat op TestFlight → kies bv. 3 of 10);
   Xcode Cloud verhoogt daarna zelf per build en het script schrijft dat nummer in het
   pbxproj.
6. **Save** → eerste build start direct (of klik "Start Build" op `main`). Volg de build in
   Xcode (Report navigator → Cloud) of App Store Connect → app → **Xcode Cloud**. De build
   verschijnt daarna vanzelf in TestFlight bij de interne groep.
7. ⚠️ Vergeet checklist-stap 3 hierboven niet (`APNS_SANDBOX=false` in deploy.yml, twee
   plekken) — dat staat los van Xcode Cloud maar hoort bij dezelfde eerste
   TestFlight-ronde. Voor de export-compliance-vraag: `ITSAppUsesNonExemptEncryption=false`
   staat al in Info.plist, TestFlight vraagt er dan niet meer om.

**Build 3 (planning-tab + jaaragenda in de veld-app) staat klaar:** de web-assets komen bij
elke cloud-build automatisch uit `main` — zodra de workflow gekoppeld is, is de eerste build
die eruit rolt meteen Build 3 met de planning-weergave; er is geen extra klaarzet-stap.
