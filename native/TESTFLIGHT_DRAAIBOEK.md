# TestFlight-draaiboek "Nijenhuis Boekingsmodule" (iOS, deel A van de run 2026-08-18)

> **Hernoemd 2026-08-19 (besluit Peter):** productnaam/App Store-naam = **"Nijenhuis
> Boekingsmodule"** (was "RLZ Goedkeuren"), ondertitel blijft "Facturen goedkeuren";
> beginscherm-weergavenaam = kort **"Nijenhuis"** (CFBundleDisplayName/Android-label,
> i.v.m. afkapping onder het icoon). Bundle-id blijft `nl.aknijenhuis.goedkeuren`
> (onzichtbaar; wijzigen zou signing/AASA raken).

Klik-voor-klik-recept voor Peter. Voorwerk door de agent is af: publieke privacy-URL
(A1, live ná de eerstvolgende deploy), screenshots (A3, `store-assets/screenshots/`),
demo-account-strategie + seedscript (A2, `backend/scripts/cloud_seed_review_demo.py`),
`ITSAppUsesNonExemptEncryption=false` in Info.plist (scheelt de export-compliance-vraag
bij elke upload). STORE_GEREEDHEID.md blijft het canonieke dossier; dit is het draaiboek.

## 0. Demo-account voor App Review (A2) — strategie

**De passkey-laag wordt niet verzwakt: geen bypass, geen reviewer-achterdeur.** De reviewer
krijgt een gewoon accordeur-account en doorloopt exact de normale flow: e-mail + wachtwoord
→ passkey-registratie op het reviewtoestel (Face ID, nieuw apparaat = volledige login) →
wachtrij. Apple's richtlijn (2.1/demo-account) vraagt werkende inloggegevens — die geven we;
de passkey is een tweede stap ná dat wachtwoord en werkt op elk iOS-toestel met
iCloud-sleutelhanger.

- Account: `p.nijenhuis+applereview@kempengroep.nl` (plus-adressering → landt in jouw eigen
  postvak, dus géén bounce-ruis van herinnermails en niets in de facturen@-intake).
- Administratie: SEED-PASSKEYTEST, met uitsluitend FICTIEVE demo-facturen (eigen PDF's,
  voettekst "Fictieve demonstratiefactuur") — nooit echte klantfacturen voor reviewers.
- Twee accorderingslagen (review-account → passkeytest-account): het reviewer-akkoord is
  nooit het láátste akkoord, dus de boekmotor op deze credential-loze administratie wordt
  nooit geraakt — de reviewer ziet gewoon "akkoord → volgende".
- **Bekend risico (Apple-forum, o.a. thread 796151):** passkeys falen soms op
  review-toestellen (vermoedelijk iCloud-sleutelhanger-configuratie). Mitigatie: in de
  reviewnotities expliciet benoemen dat de passkey-stap door iOS zelf wordt afgehandeld en
  iCloud-sleutelhanger vereist. Wijst Apple af op een falende passkey, dan is dat een
  reply/appeal met verwijzing naar de notities — NIET een reden om een bypass te bouwen.

Klaarzetten (jouw klikwerk, vergt gcloud-login; **HERZIEN 07-09 ná de 2.1-afwijzing — zie §0b**):

```bash
cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
cd backend
APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten \
    .venv/bin/python scripts/cloud_seed_review_demo.py --genereer-wachtwoord
```

Het script maakt het account zélf volledig geactiveerd (status actief, definitief wachtwoord,
open links vervallen, bestaande demo-passkeys ingetrokken, audit) en **print het wachtwoord** —
dat gaat 1-op-1 naar App Store Connect › App Review Information én de reviewnotities. Er is géén
activatielink meer te doorlopen (de oude route liet het wachtwoord op de link geparkeerd staan
tot de passkey-registratie — dáár ging het 02-09 mis). Zonder `--genereer-wachtwoord` blijft een
bestaand wachtwoord staan (alleen herseed van facturen). De seed weigert zonder
`DOCUMENT_GCS_BUCKET`, verifieert élke PDF-upload en herstelt ontbrekende PDF-objecten van
eerdere runs. Raakt de wachtrij ooit leeg (reviewer heeft alles beoordeeld), draai het script
opnieuw met een batch-letter: `… cloud_seed_review_demo.py b`.

> ⚠️ Netwerk-bevinding 2026-08-18: op het kantoornetwerk (gateway 192.168.30.1) wordt
> uitgaand TCP 3307/5432 per direct geweigerd — de Cloud SQL Auth Proxy komt er dan niet
> doorheen ("connection refused" in ~2 ms = lokale firewall, niet Google). De seed draaien
> lukt dus alleen vanaf een netwerk zónder die blokkade (hotspot/thuis) of ná een
> firewall-uitzondering voor 3307.

## 0b. Afwijzing 2.1 op build 1.0 (44) — wortel + herstel (07-09)

Apple wees build 1.0 (44) af (guideline 2.1): de reviewer kon op een iPad Air niet inloggen met
het demo-account. **Wortel (Cloud Logging + audit-log, 07-09):** 20 pogingen op 04-09
09:49–09:59 UTC vanaf twee Apple-adressen (17.185.64.112 / 139.178.129.4, iOS 18.7) en één op
05-09 12:07 UTC (iPad, Three Ireland) — álle `POST /auth/accordeur/login` → 401 mét een
`login_mislukt`-auditrij op het demo-account. Het adres klopte dus, het account was actief mét
hash, de rol klopte: het enige resterende faalpad is `verify_password` → **het wachtwoord in App
Review Information kwam niet overeen met het wachtwoord dat op 02-09 bij de activatie op het
Xiaomi-toestel is gekozen.** Op 03-09 was de wachtwoordstap nog 17× groen (Peters eigen
Android-tests), dus de hash was niet kapot — het opgegeven wachtwoord was een ander.
De reviewer kwam dus nooit bij de passkey-sheet; de eerdere hypothesen (vastlopen op de sheet,
registratie geweigerd zonder iCloud-sleutelhanger) zijn hiermee uitgesloten voor déze afwijzing.

**Herstel 07-09:** herziene seed (§0) gedraaid tegen productie: nieuw wachtwoord, Android-passkey
ingetrokken, wachtrij 9 fictieve facturen. **Tweede vondst tijdens de simulator-verificatie:**
drie demo-documenten uit de seed-run van 02-09 hadden géén PDF-object in de bucket (500 op
`/bestand`, "factuurbeeld kon niet geladen worden") — hersteld door het identieke PDF-object te
kopiëren; de seed doet dat sinds 07-09 zelf. **Volledige reviewer-flow bewezen** in de iPad
Air 11"-simulator (verse staat, webbundel HEAD 07-09 tegen `app.administratiekantoornijenhuis.nl`;
het loginpad is sinds build 44 alleen met het uitlegblok "Nog niet geactiveerd?" uitgebreid):
wachtwoordscherm → 200 → iOS-passkey-sheet → Touch ID → code kiezen + bevestigen → wachtrij →
factuur-PDF → Akkoord → volgende; herstart → code-slot → wachtrij. Build 44 zelf faalde nergens.

**Concept-reply App Store Connect (Resolution Center, Engels, kort):**

```
Thank you for the review. We investigated the failed sign-in on the iPad Air with build 1.0 (44).
Our server logs show that every attempt reached our backend and was rejected as "invalid
credentials": the password listed in App Review Information did not match the demo account.
We have reset the demo account and verified the complete sign-in flow end to end on an
iPad Air (11-inch) against our production backend.

Updated demo credentials (also updated in App Review Information):
Email: p.nijenhuis+applereview@kempengroep.nl
Password: <nieuw wachtwoord>

Steps: open the app → tap "Inloggen met wachtwoord" (sign in with password) → enter the email
and password → confirm the iOS passkey prompt with Face ID / Touch ID → choose a 5-digit app
code → the approval queue with demonstration invoices appears. The passkey prompt is Apple's
standard ASAuthorizationController flow and requires iCloud Keychain to be enabled on the
device. No app changes were needed; the same build can be reviewed again.
```

> **Waar je opnieuw indient (08-09):** ná een 2.1-afwijzing staat de submissiepagina zelf
> (App Store-tab van de versie) meestal nog grijs/inactief — dat is geen bug, de opnieuw-
> indienen-actie zit dan op de **versiepagina**: App Store Connect → jouw app → tab **App
> Store** → de betreffende versie (status "Rejected") → reageer eerst in **Resolution
> Center** (de conceptreply hierboven) → daarna verschijnt bovenaan de versiepagina de knop
> **"Update Review"** — die stuurt de bestaande versie (met de bijgewerkte App Review
> Information/wachtwoord) opnieuw ter review, zonder een nieuwe build te hoeven kiezen. Pas
> als je ook een nieuwe build wilt koppelen (zie §0c) selecteer je die eerst onder "Build" op
> dezelfde pagina, vóórdat je "Update Review" gebruikt.

> **Aanvulling 07-09 (Play-afwijzing, blok PLAY):** Google Play wees dezelfde build óók af ("Login
> credentials are incorrect"), maar met een ÁNDERE wortel: Cloud Logging toont op 03-09 vanaf Google-IP's
> 7× resp. 11× een geslaagde wachtwoordstap (200) zonder vervolg — de reviewer strandde op de passkey-
> registratie (Android Credential Manager: "No create options available" op een toestel zonder
> Google-account). Gereproduceerd in een kale Pixel-7-emulator. Daarom staan hieronder in §1 en in
> `PLAY_DRAAIBOEK.md` §10/§11 de toestelvereisten (schermvergrendeling + Google-account / iCloud-
> sleutelhanger) nu expliciet in de reviewnotities. Het wachtwoord is op 07-09 13:27 (blok PLAY) NOGMAALS
> vernieuwd — het wachtwoord uit het ochtendrapport van 07-09 is daarmee ONGELDIG; gebruik het
> wachtwoord uit het eindrapport van de fixrun 07-09.

Klikwerk: (1) nieuw wachtwoord in App Review Information zetten, (2) de notes in §1 hierboven
overnemen, (3) reply plaatsen en de submission opnieuw ter review aanbieden — óf, als de
universal-link-fix (06-09, `@capacitor/app`) meteen mee moet, eerst de eerstvolgende build laten
bouwen (destijds op 07-09 verwacht als build 45; werd build 89 — zie §0c) (package-lock +
Package.swift zijn 07-09 gecommit; Xcode Cloud `npm ci` faalde anders).

### 0c. Eerstvolgende build klaarzetten (vervolgrun 07-09, blok 12d) — NIET ingediend

> **Correctie 08-09 (bouwagent BLOK 8):** Xcode Cloud telt het buildnummer per PUSH naar `main`
> (élke commit-batch die iets in de app-relevante boom raakt, niet alleen een bewust
> "app-release"-moment) — het is dus geen teller die je met "de eerstvolgende push" op 45 kunt
> vasthouden zodra er tussentijds meerdere runs met commits naar `main` gaan (elk met een eigen
> Stop-hook-push). Tussen deze paragraaf (07-09) en de huidige bundelrun (08-09) zijn dat er veel
> geweest: de eerstvolgende Xcode Cloud-build op `main` is daardoor **build 89**, niet 45. Overal
> hieronder waar destijds "45" stond is dat gecorrigeerd naar het huidige, juiste getal; waar de
> tekst destijds een verwachting uitsprak staat "(destijds verwacht als 45; werd 89)" erbij — niets
> is stilzwijgend herschreven. Dit is een documentcorrectie, geen nieuwe Xcode Cloud-run: het
> werkelijke buildnummer wordt pas bevestigd door de eerstvolgende "processing completed"-mail:
> toets dat live vóór je in App Store Connect een buildnummer aan de versie koppelt.

**Hoe build 44 → 89 werkt:** het iOS-buildnummer komt NIET uit de repo. `ci_scripts/ci_post_clone.sh`
zet bij élke Xcode Cloud-build `CURRENT_PROJECT_VERSION ← CI_BUILD_NUMBER` (beide pbxproj-plekken);
de repo blijft op `3`, `MARKETING_VERSION` blijft `1.0`. Build 44 was dus gewoon Xcode Cloud-build
nr. 44 op `main`. **De eerstvolgende push naar `main` ná de commit van deze run krijgt het
eerstvolgende Xcode Cloud-buildnummer (destijds op 07-09 verwacht als build 45; werd build 89 —
zie de correctie hierboven)** — er is geen handmatige bump; Xcode Cloud bundelt via `bouw-web
--mode native` + `cap sync ios` automatisch de actuele web-assets (incl. 12a/12b/13 hieronder) en
de `@capacitor/app`-plugin (E1 06-09, Package.swift gecommit 0f6a085). Handmatig archiveren (§3)
blijft de terugval; lokaal is `npm run bouw-web && npx cap sync` op 07-09 gedraaid
(ios/App/App/public ververst — niet ingecheckt, CLI-managed).

**Wat build 89 inhoudelijk meeneemt t.o.v. 44 (destijds verwacht als 45; werd 89):**
universal-link-fix (E1), activatie-hulpblok (E2), diagnoseregel (12a), geen verloren boot-refresh
in native (12b), eerlijke Android-melding bij ontbrekende passkey-beheerder (13 — raakt iOS niet)
— plus alles wat sindsdien op `main` is gecommit tot aan de daadwerkelijke build-run (toets de
inhoud tegen de "processing completed"-mail, niet tegen deze lijst).

**Diagnoseregel als kliktest-/reviewer-hulp (12a):** in de app → ⚙ (Toegang tot de app) → onderaan
"Diagnose › Laatste koude start": één regel `web <sha-datum> · app 1.0 (89) · boot … ms · sessie … ms
· server … ms · netwerk … ms · totaal … ms · dd-mm HH:MM` (destijds verwacht als `app 1.0 (45)`;
werd `app 1.0 (89)`). Blijft lokaal op het toestel; een screenshot (of "Kopiëren") volstaat — de
Web Inspector-instructie uit BESLISSINGEN "KOUDE START" beslispunt 1 is daarmee overbodig. De
diagnoseregel bevestigt meteen dat het juiste, daadwerkelijke buildnummer draait — lees dat getal
altijd live af (TestFlight of de diagnoseregel zelf), plak het niet blind uit dit document.

Klikwerk Peter: (a) commits van de vervolgrun op `main` → Xcode Cloud bouwt de eerstvolgende build
(mail "processing completed" noemt het echte nummer — destijds verwacht als 45, werd 89); (b)
TestFlight → die build op het eigen toestel → kliktest E1 (mail-link opent de app op de
code-keuze) + 12a (diagnoseregel toont het echte buildnummer); (c) dán pas in App Store Connect
dat buildnummer aan de versie 1.0 koppelen + reply §0b + opnieuw ter review. Android-tegenhanger:
PLAY_DRAAIBOEK §3 (versionCode 3).

#### 2c — uitnodigingslink in Safari (08-09)

**Melding:** op 08-09 08:31 (NL) opende een uitnodigingslink op een iPhone in Safari i.p.v. in de app.
**Toetsing (agent BLOK 2, 08-09, code + live):**

- **AASA live OK:** `curl https://app.administratiekantoornijenhuis.nl/.well-known/apple-app-site-association`
  → HTTP 200, `content-type: application/json`, 210 bytes: `applinks.details[0].appIDs =
  ["VRQP26CX43.nl.aknijenhuis.goedkeuren"]`, `components = [{"/": "/accordeur*"}, {"/": "/activeren*"}]`
  (+ `webcredentials` voor de passkeys). `/activeren` staat er dus in; de uitnodigingsmail linkt rechtstreeks
  (`{app_basis_url}/activeren?token=…`, `berichten/uitnodigingsmail.py`), geen tracking-redirect ertussen.
- **Build 44 heeft dit gedrag (Safari) NIET door de AASA maar door de app zelf:** build 44 is vóór 04-09 gebouwd
  (review-log 04-09 09:49 UTC); de E1-fix (`@capacitor/app` toegevoegd, `native/package.json`, commit `e40b91f`)
  dateert van 06-09 11:43. Zonder die plugin komt een universal link wél de app in, maar het `appUrlOpen`-event
  bereikt de webcode nooit → login-scherm; dát was de casus van 04-09. **"Opent in Safari" is een ándere
  faalvorm:** dan heeft iOS de link niet eens aan de app gegeven.
- **Build 89 bevat E1:** het is de eerstvolgende Xcode Cloud-build op `main` ná `e40b91f`/`0f6a085`
  (Package.swift 07-09); Xcode Cloud draait `bouw-web --mode native` + `cap sync ios` → `@capacitor/app` zit in de
  bundel (`capacitor.plugins.json`, 12d). Toets op het toestel: Toegang › Diagnose toont `app 1.0 (89)`.
- **Waarom dan tóch Safari (08-09)?** Niet live vast te stellen zonder het toestel; de bekende oorzaken, in
  volgorde van waarschijnlijkheid: (1) op dat toestel stond op 08:31 nog build 44 (of géén TestFlight-build) —
  universal links werken alleen als de geïnstalleerde app de AASA bij installatie heeft opgehaald; ná een
  (her)installatie duurt dat soms minuten; (2) de gebruiker heeft eerder rechtsboven "Openen in Safari" gekozen
  of de link lang ingedrukt → iOS onthoudt die keuze per domein (herstel: link in Safari openen → banner
  "Open in app" tikken, óf lang-drukken op de link → "Openen in Nijenhuis"); (3) de link is niet vanuit de
  mail-app maar vanuit Safari zelf gevolgd (zelfde-domein-navigatie triggert nooit een universal link) of via een
  omhullende mailclient (Outlook Safe Links-achtige redirect) — de mail van het kantoor zelf linkt direct.
  Werkende terugval bestaat al sinds E2: in de app "Nog niet geactiveerd? → Link plakken" accepteert dezelfde URL.
- **Advies:** eerst het buildnummer op het toestel controleren (diagnoseregel) en de gebruiker de lang-druk-route
  laten proberen; pas als build 89 aantoonbaar draait én de link uit de kantoormail nog steeds in Safari opent, is
  het een echte E1-regressie (dan: `sysdiagnose`/`swcutil` niet nodig — `Instellingen › Ontwikkelaar ›
  Universal Links › Diagnostics` op het toestel geeft het AASA-oordeel direct).

## 1. App-registratie in App Store Connect (A4)

Vooraf: door de kliktest-builds met "automatically manage signing" bestaat het App ID
`nl.aknijenhuis.goedkeuren` waarschijnlijk al in het Developer-portaal, mét de capabilities
Associated Domains en Push Notifications. Controleer dat eerst:

1. https://developer.apple.com → Account (PDL Powerhouse) → **Certificates, Identifiers &
   Profiles → Identifiers**. Staat `nl.aknijenhuis.goedkeuren` er? Klik erop en check dat
   **Associated Domains** én **Push Notifications** aangevinkt zijn. Ontbreekt het App ID:
   **+** → App IDs → App → Description "Nijenhuis Boekingsmodule", Bundle ID **Explicit**
   `nl.aknijenhuis.goedkeuren`, vink beide capabilities aan → Register.
2. https://appstoreconnect.apple.com → **My Apps** (Apps) → **+** → **New App**:
   - Platforms: **iOS**
   - Name: **Nijenhuis Boekingsmodule** (zichtbare App Store-naam, 24 tekens — past binnen
     de 30-tekens-limiet; moet uniek zijn in de store — is hij bezet (onwaarschijnlijk),
     dan niet zelf variëren maar even afstemmen)
   - Primary Language: **Dutch (Nederlands)**
   - Bundle ID: kies **nl.aknijenhuis.goedkeuren** uit de lijst
   - SKU: `rlz-goedkeuren` (intern, vrij te kiezen, permanent)
   - User Access: Full Access → **Create**
3. **App Information** (linkermenu):
   - Subtitle: "Facturen goedkeuren — Administratiekantoor Nijenhuis" (max 30 tekens is de
     limiet — dit is te lang; neem **"Facturen goedkeuren"** en zet de rest in de
     beschrijving)
   - Category: **Business** (primair); Secondary leeg of Finance
   - Content Rights: bevat geen third-party content → "No"
4. **App Privacy** (linkermenu):
   - Privacy Policy URL: `https://app.administratiekantoornijenhuis.nl/accordeur/privacy`
     (live ná de eerstvolgende deploy — check 'm eerst even in de browser)
   - "Get Started" → vul de nutrition labels exact volgens **STORE_GEREEDHEID.md §2** in
     (Email Address, Name, Other Financial Info, User ID — alle "linked to identity", geen
     tracking; Usage Data/Diagnostics: niet verzameld) → Publish.
5. **Pricing and Availability**: Price **0** (gratis); Availability: alleen **Nederland**
   volstaat (intern gebruik; meer landen mag).
6. **App Review Information** (staat op de versiepagina onderaan, zie stap 3 hierna):
   - Sign-in required: **aanvinken** → Username `p.nijenhuis+applereview@kempengroep.nl`,
     Password: het review-wachtwoord uit §0.
   - Contact: jouw naam + telefoonnummer + p.nijenhuis@kempengroep.nl.
   - Notes: onderstaande Engelse tekst (aanvullen met het wachtwoord):

```
Invitation-only business app for clients of Dutch accounting firm Administratiekantoor
Nijenhuis. Accountants prepare purchase invoices; designated client users ("approvers")
approve or reject them. There is no open registration.

Demo account (demo administration, contains FICTITIOUS demonstration invoices only):
- Email: p.nijenhuis+applereview@kempengroep.nl
- Password: <wachtwoord uit het eindrapport>

IMPORTANT — device prerequisites for the first sign-in:
- The first sign-in registers a passkey on the review device through the operating system's
  standard passkey flow (Apple: ASAuthorizationController). This requires a device passcode
  and iCloud Keychain (Passwords) to be enabled and signed in on the test device. Without them
  iOS cannot store the passkey and the sign-in cannot complete; this is platform behaviour, not
  an app defect. Face ID / Touch ID is optional (the device passcode also works).

Sign-in steps (verified end to end on an iPad Air 11-inch against our production backend):
1. Open the app. The first screen is the passkey sign-in for returning devices; tap the white
   button "Inloggen met wachtwoord" (= sign in with password) underneath the green one.
2. Enter the email and password above and tap "Inloggen".
3. iOS shows its system passkey sheet ("Een passkey bewaren?" = save a passkey). Confirm with
   Face ID / Touch ID or the device passcode. If the sheet is dismissed, simply sign in again
   (steps 1-2).
4. Choose a 5-digit app code and repeat it. This code unlocks the app on later launches (the
   app never asks for the password again on this device).
5. The approval queue with demonstration invoices appears. Tap an invoice to view the PDF and
   approve ("Akkoord") or reject ("Afwijzen"); the next invoice opens automatically.

If step 3 fails with a passkey error: enable iCloud Keychain (Settings > [Apple ID] > iCloud >
Passwords & Keychain) and set a device passcode, then repeat from step 1.

Push notifications: a daily 09:00 reminder and a "new invoices ready for you" message —
only sent while work is pending. Approving from a notification is deliberately impossible;
tapping opens the app, which unlocks with the passkey first.

Account deletion: accounts exist only by invitation of the accounting firm; deletion /
anonymization is handled by the firm on request (GDPR process; the approval audit log has a
7-year statutory retention in the Netherlands). Contact: p.nijenhuis@kempengroep.nl.

The app bundles its assets and uses native passkeys, native push and deep links — it is not
a wrapper around a website (guideline 4.2).
```

## 2. Versiepagina invullen (1.0)

Onder **iOS App 1.0** (Prepare for Submission):
- **Screenshots**: sleep uit `native/store-assets/screenshots/` de drie
  `iphone-6p9-*.png` in het 6.9"-vak (volgorde: wachtrij, factuurbeeld, ontgrendelen).
  De `iphone-6p3-*.png` kunnen in het 6.3"-vak (optioneel — ASC schaalt anders zelf;
  `-04-meldingenkaart` is een optionele vierde). Alleen de 6.9"-set is verplicht.
  **iPad (29-08, iPad blijft ondersteund):** zodra de app-record iPad-ondersteuning draagt
  (`TARGETED_DEVICE_FAMILY = 1,2` — dat is al zo) vraagt ASC óók iPad-screenshots: sleep de drie
  `ipad-13-0{1,2,3}-*.png` (2064×2752, portret) in het **iPad 13"**-vak; ASC schaalt ze zelf naar
  de kleinere iPad-vakken.
- **Description** (NL), voorstel:
  "Keur inkoopfacturen van je eigen administratie goed of wijs ze af — veilig met een
  passkey (Face ID), alleen op uitnodiging van Administratiekantoor Nijenhuis. Je ziet de
  factuur op volledig scherm, met het boekvoorstel van het kantoor eronder. Een dagelijkse
  herinnering en een melding bij nieuwe facturen, alleen als er echt iets openstaat."
- Keywords: `facturen,goedkeuren,accorderen,administratie,boekhouding,nijenhuis`
- Support URL: `https://app.administratiekantoornijenhuis.nl/accordeur/privacy` (of de
  kantoorwebsite), Marketing URL leeg.
- Build: koppel je ná de upload (stap 3). Age rating-vragenlijst: alles "None" → 4+.

## 3. Archive + upload (A5)

De webbundel staat al klaar (productie-API-base, `cap sync` gedraaid). Zou je zelf nog
webcode wijzigen: eerst `cd native && npm run bouw-web && npx cap sync ios`.

1. `cd native && npx cap open ios` (of open `native/ios/App/App.xcodeproj`).
2. Selecteer bovenin het scheme **App** en als destination **Any iOS Device (arm64)** —
   géén simulator, anders is Product → Archive grijs.
3. Target App → Signing & Capabilities: Team = PDL Powerhouse, "Automatically manage
   signing" aan (stond zo bij de kliktest). General: Version **1.0**, Build **1**.
4. Menu **Product → Archive** (duurt enkele minuten). De **Organizer** opent vanzelf.
5. Organizer → selecteer het archief → **Distribute App** → **App Store Connect** →
   **Upload** → alle defaults (upload symbols aan, automatically manage signing) →
   **Upload**. Xcode vraagt eenmalig om je Apple-account-login als die sessie verlopen is.
6. Wacht op de mail "has completed processing" (5–30 min). De export-compliance-vraag komt
   niet — `ITSAppUsesNonExemptEncryption=false` staat in Info.plist (alleen standaard
   https/TLS).
7. App Store Connect → jouw app → tab **TestFlight** → de build verschijnt onder iOS.
   - **Internal Testing** → **+** naast Internal Testing → groep "Interne test" →
     voeg jezelf toe (je ASC-gebruiker) → selecteer de build. Interne testers = geen
     beta-review nodig; je krijgt direct de TestFlight-uitnodiging per mail.
     **Let op (08-09):** Internal Testing kan uitsluitend App Store Connect-teamleden
     bevatten (een gebruiker met een rol op déze app in ASC — Admin/App Manager/Developer/
     Marketing e.d.), geen los e-mailadres. Kantoormedewerkers die geen ASC-teamlid zijn
     (de gewone situatie) kun je dus niet als interne tester toevoegen — voor hen is de
     **External Testing**-groep de juiste weg (los e-mailadres volstaat, wél een eenmalige
     lichte beta-review door Apple per build/groep, geen store-review). Zie §5 "Daarna".
8. iPhone: installeer **TestFlight** uit de App Store → open de uitnodiging → installeer
   "Nijenhuis Boekingsmodule" (op het beginscherm heet de app kort "Nijenhuis").
   NB dit vervangt de kabel-/dev-build op het toestel.

## 4. APNS_SANDBOX omzetten (A6) — ✅ UITGEVOERD (deploy.yml 2026-08-21; afgerond 2026-08-23)

De TestFlight-build is production-signed (`aps-environment: production`) en praat alleen
met productie-APNs. `APNS_SANDBOX=false` staat sindsdien in `.github/workflows/deploy.yml`
(twee plekken: job-stap + service-stap) én in `scripts/gcp/apns_afronden.sh` (de directe
spiegel — een her-run zet de live config niet meer terug naar sandbox).

**Gevolg, expliciet:** je kabel-/dev-build krijgt daarna GÉÉN push meer — het oude
sandbox-token faalt zichtbaar als BadDeviceToken in de job-logs en wordt als vervallen
opgeruimd; push test je vanaf dat moment via de TestFlight-build. Zet dáár na installatie
de meldingen (opnieuw) aan via het 🔔-hoekje, zodat er een vers productie-token
geregistreerd staat. Terug naar de kabel-build testen = de vlag terugzetten (zelfde twee
plekken) — het is een óf-óf-schakelaar.

## 5. Daarna

- Interne test met jou (ASC-teamlid) — de accordeurs blijven op de PWA tot de echte
  uitrol (PWA blijft terugval, besluit 14-08). **Wil je kantoormedewerkers (Boekhouding e.d.)
  laten meekijken:** die zijn normaliter géén ASC-teamlid, dus niet toe te voegen aan
  Internal Testing (08-09-advies) — gebruik daarvoor de External Testing-groep (los
  e-mailadres, met een eenmalige lichte beta-review per build/groep, geen volle
  store-review).
- Externe TestFlight-groepen of App Store-release = beta-/app-review → dan moeten §0
  (demo-account geseed + geactiveerd) en §1 (reviewnotities) af zijn.
- Android/Firebase-ronde: eigen draaiboek `native/PLAY_DRAAIBOEK.md` (bouwronde 28-08 —
  Firebase-registratie + FCM-verzendkant klaar; keystore, AAB, Play-app onder PDL, assetlinks,
  apk-key-hash-origins, listing/Data safety = klikwerk).
