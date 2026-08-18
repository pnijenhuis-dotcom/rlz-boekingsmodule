# TestFlight-draaiboek "RLZ Goedkeuren" (iOS, deel A van de run 2026-08-18)

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

Klaarzetten (jouw klikwerk, vergt gcloud-login):

```bash
cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
cd backend
APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten \
    .venv/bin/python scripts/cloud_seed_review_demo.py
```

Het script print de activatielink → open
`https://app.administratiekantoornijenhuis.nl/activeren?token=…`, kies dáár het
review-wachtwoord (komt in de reviewnotities; bewaar het ook zelf). Raakt de wachtrij ooit
leeg (reviewer heeft alles beoordeeld), draai het script opnieuw met een batch-letter:
`… cloud_seed_review_demo.py b`.

## 1. App-registratie in App Store Connect (A4)

Vooraf: door de kliktest-builds met "automatically manage signing" bestaat het App ID
`nl.aknijenhuis.goedkeuren` waarschijnlijk al in het Developer-portaal, mét de capabilities
Associated Domains en Push Notifications. Controleer dat eerst:

1. https://developer.apple.com → Account (PDL Powerhouse) → **Certificates, Identifiers &
   Profiles → Identifiers**. Staat `nl.aknijenhuis.goedkeuren` er? Klik erop en check dat
   **Associated Domains** én **Push Notifications** aangevinkt zijn. Ontbreekt het App ID:
   **+** → App IDs → App → Description "RLZ Goedkeuren", Bundle ID **Explicit**
   `nl.aknijenhuis.goedkeuren`, vink beide capabilities aan → Register.
2. https://appstoreconnect.apple.com → **My Apps** (Apps) → **+** → **New App**:
   - Platforms: **iOS**
   - Name: **RLZ Goedkeuren** (zichtbare App Store-naam; moet uniek zijn in de store —
     wijkt hij af, neem "RLZ Goedkeuren — Nijenhuis")
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
- Password: <invullen>

Sign-in flow: enter email + password. On first sign-in on a new device the app registers a
passkey via the iOS system prompt (ASAuthorizationController / Face ID); this requires
iCloud Keychain to be enabled on the device. After that, the app unlocks with the passkey
once per app launch. If a terms & privacy screen appears, tap agree to continue.

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
8. iPhone: installeer **TestFlight** uit de App Store → open de uitnodiging → installeer
   "RLZ Goedkeuren". NB dit vervangt de kabel-/dev-build op het toestel.

## 4. APNS_SANDBOX omzetten (A6) — pas NA de eerste TestFlight-install

De TestFlight-build is production-signed (`aps-environment: production`) en praat alleen
met productie-APNs; de kliktest-config staat nog op sandbox. **Zodra de TestFlight-build op
je toestel staat**: zeg "zet A6 om" tegen de agent, of doe het zelf —
`.github/workflows/deploy.yml`, twee plekken (job-stap ± regel 218 én service-stap
± regel 248): `APNS_SANDBOX=true` → `APNS_SANDBOX=false`, commit + push (deploy zet het live).

**Gevolg, expliciet:** je kabel-/dev-build krijgt daarna GÉÉN push meer — het oude
sandbox-token faalt zichtbaar als BadDeviceToken in de job-logs en wordt als vervallen
opgeruimd; push test je vanaf dat moment via de TestFlight-build. Zet dáár na installatie
de meldingen (opnieuw) aan via het 🔔-hoekje, zodat er een vers productie-token
geregistreerd staat. Terug naar de kabel-build testen = de vlag terugzetten (zelfde twee
plekken) — het is een óf-óf-schakelaar.

## 5. Daarna

- Interne test met jou (en desgewenst kantoor) — de accordeurs blijven op de PWA tot de
  echte uitrol (PWA blijft terugval, besluit 14-08).
- Externe TestFlight-groepen of App Store-release = beta-/app-review → dan moeten §0
  (demo-account geseed + geactiveerd) en §1 (reviewnotities) af zijn.
- Android/Firebase-ronde is een eigen spoor (STORE_GEREEDHEID §5 punt 4; keystore,
  assetlinks, apk-key-hash-origin, FCM).
